import json
import logging
import secrets
import time
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from fastapi.encoders import jsonable_encoder
from redis import Redis
from sqlalchemy.orm import Session

from backend.app.auth import get_current_user
from backend.app.config import get_settings
from backend.app.db import get_db, get_supabase
from backend.app.models import Profile
from backend.app.services.llm import is_token_limit_error
from backend.app.services.nl_query import NaturalLanguageQueryEngine

router = APIRouter()
logger = logging.getLogger(__name__)

_MEMORY_TICKETS: dict[str, dict] = {}
MAX_CHAT_MESSAGE_LENGTH = 5000


def _store_handshake_ticket(ticket: str, user_id: str, tenant_id: str) -> None:
    settings = get_settings()
    data = json.dumps({"user_id": str(user_id), "tenant_id": str(tenant_id)})
    try:
        cache = Redis.from_url(settings.queue_url, decode_responses=True)
        cache.set(f"chat_ticket:{ticket}", data, ex=60)
        return
    except Exception as e:
        logger.debug("Redis ticket store fallback to memory: %s", e)
    _MEMORY_TICKETS[ticket] = {"user_id": str(user_id), "tenant_id": str(tenant_id), "expires_at": time.time() + 60}


def _consume_handshake_ticket(ticket: str) -> tuple[str | None, str | None]:
    if not ticket:
        return None, None
    settings = get_settings()
    try:
        cache = Redis.from_url(settings.queue_url, decode_responses=True)
        raw = cache.get(f"chat_ticket:{ticket}")
        if raw:
            cache.delete(f"chat_ticket:{ticket}")
            data = json.loads(raw)
            return data.get("user_id"), data.get("tenant_id")
    except Exception as e:
        logger.debug("Redis ticket consume fallback to memory: %s", e)

    record = _MEMORY_TICKETS.pop(ticket, None)
    if record and record.get("expires_at", 0) > time.time():
        return record.get("user_id"), record.get("tenant_id")
    return None, None


@router.post("/api/chat/handshake-token")
def create_chat_handshake_token(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Generate a single-use, short-lived ticket for authenticating chat WebSockets without URL JWT leakage."""
    user_id = current_user["id"]
    tenant_id = current_user.get("tenant_id", user_id)
    ticket = secrets.token_urlsafe(32)
    _store_handshake_ticket(ticket, user_id=str(user_id), tenant_id=str(tenant_id))
    return {"ticket": ticket, "expires_in": 60}


@router.websocket("/ws/chat")
async def chat_socket(websocket: WebSocket, db: Session = Depends(get_db)) -> None:
    await websocket.accept()

    ticket = websocket.query_params.get("ticket")
    token = websocket.query_params.get("token")
    if token:
        token = token.strip('"\'')

    tenant_id = None
    user_id = None

    if ticket:
        ticket_user_id, ticket_tenant_id = _consume_handshake_ticket(ticket)
        if ticket_user_id:
            user_id = UUID(ticket_user_id)
            tenant_id = UUID(ticket_tenant_id) if ticket_tenant_id else user_id
        else:
            logger.warning("WebSocket connection attempt with invalid or expired handshake ticket rejected")
            await websocket.send_json({"type": "error", "message": "Authentication failed. Expired or invalid handshake ticket. Connection closed."})
            await websocket.close()
            return
    elif token and len(token.split(".")) == 3:
        # Legacy fallback with deprecation log
        logger.warning("WebSocket connected using query token parameter (deprecated; upgrade client to handshake ticket)")
        try:
            supabase_client = get_supabase()
            response = supabase_client.auth.get_user(token)
            if response and response.user:
                user_uuid = UUID(response.user.id)
                user_id = user_uuid
                profile = db.query(Profile).filter(Profile.id == user_uuid).first()
                if not profile:
                    await websocket.send_json({"type": "error", "message": "Authentication failed. Missing profile identity. Connection closed."})
                    await websocket.close()
                    return
                tenant_id = user_uuid
        except Exception:
            logger.exception("WebSocket authentication failed with exception")
            await websocket.send_json({"type": "error", "message": "Authentication failed. Connection closed."})
            await websocket.close()
            return
    else:
        logger.warning("WebSocket connection attempt without ticket or valid token format rejected")
        await websocket.send_json({"type": "error", "message": "Authentication failed. Missing handshake ticket. Connection closed."})
        await websocket.close()
        return

    if not tenant_id or not user_id:
        logger.warning("WebSocket connection attempt failed authentication (identity unresolved) rejected")
        await websocket.send_json({"type": "error", "message": "Authentication failed. Missing profile identity. Connection closed."})
        await websocket.close()
        return

    settings = get_settings()
    try:
        cache = Redis.from_url(settings.queue_url, decode_responses=True)
    except Exception:
        cache = None
    engine = NaturalLanguageQueryEngine(db=db, cache=cache)

    try:
        while True:
            message = await websocket.receive_text()
            if len(message) > MAX_CHAT_MESSAGE_LENGTH:
                await websocket.send_json({"type": "error", "message": f"Message exceeds maximum character limit ({MAX_CHAT_MESSAGE_LENGTH})."})
                continue

            try:
                result = engine.answer(message, tenant_id=tenant_id, user_id=user_id)
                await websocket.send_json(jsonable_encoder({"type": "answer", "answer": result.answer, "rows": result.rows}))
            except Exception as exc:
                # Log without raw message content to protect user confidentiality (MED-6)
                logger.error("Chat query execution failed for tenant_id=%s user_id=%s: %s", tenant_id, user_id, exc, exc_info=True)
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Token Limit Reached" if is_token_limit_error(exc) else "MediCORE could not complete that query.",
                    }
                )
    except WebSocketDisconnect:
        return
