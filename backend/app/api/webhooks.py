import json
import logging
import secrets

from fastapi import APIRouter, Header, HTTPException, Request, status

from backend.app.config import get_settings
from backend.app.tasks import process_gmail_notification

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_WEBHOOK_PAYLOAD_BYTES = 256 * 1024  # 256 KB


@router.post("/gmail")
async def gmail_push(
    request: Request,
    x_webhook_token: str | None = Header(default=None),
) -> dict[str, str]:
    settings = get_settings()
    if not settings.gmail_webhook_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook is not configured")
    if not x_webhook_token or not secrets.compare_digest(x_webhook_token, settings.gmail_webhook_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook token")

    body_bytes = await request.body()
    if len(body_bytes) > MAX_WEBHOOK_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Webhook payload exceeds limit of {MAX_WEBHOOK_PAYLOAD_BYTES} bytes",
        )

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object")
    except Exception as e:
        logger.warning("Rejected malformed webhook payload: %s", e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    task = process_gmail_notification.delay(payload)
    return {"status": "queued", "task_id": task.id}
