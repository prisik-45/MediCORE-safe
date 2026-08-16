from uuid import uuid4
import pytest
from backend.app.api.chat import (
    _consume_handshake_ticket,
    _store_handshake_ticket,
)


def test_handshake_ticket_store_and_single_use_consume() -> None:
    ticket = f"test-ticket-{uuid4()}"
    user_id = str(uuid4())
    tenant_id = str(uuid4())

    _store_handshake_ticket(ticket, user_id=user_id, tenant_id=tenant_id)

    # First consumption should succeed
    retrieved_user_id, retrieved_tenant_id = _consume_handshake_ticket(ticket)
    assert retrieved_user_id == user_id
    assert retrieved_tenant_id == tenant_id

    # Second consumption must fail (single-use token protection against replay)
    second_user_id, second_tenant_id = _consume_handshake_ticket(ticket)
    assert second_user_id is None
    assert second_tenant_id is None


def test_handshake_ticket_invalid_lookup() -> None:
    user_id, tenant_id = _consume_handshake_ticket("non-existent-ticket")
    assert user_id is None
    assert tenant_id is None
