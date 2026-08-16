import pytest
from fastapi import HTTPException

from backend.app.api.email_accounts import (
    _check_imap_rate_limit,
    _record_imap_failure,
    _IMAP_FAIL_LOCKOUT,
    _IMAP_TEST_ATTEMPTS,
)


def test_imap_rate_limit_blocks_excessive_attempts() -> None:
    user_id = "test-user-rate-limit"
    email = "test@example.com"
    _IMAP_TEST_ATTEMPTS[user_id] = []

    # First 5 calls should succeed
    for _ in range(5):
        _check_imap_rate_limit(user_id=user_id, email_address=email)

    # 6th call within 60s should raise 429
    with pytest.raises(HTTPException) as exc_info:
        _check_imap_rate_limit(user_id=user_id, email_address=email)
    
    assert exc_info.value.status_code == 429
    assert "Rate limit exceeded" in exc_info.value.detail


def test_imap_lockout_on_consecutive_failures() -> None:
    user_id = "test-user-lockout"
    email = "locked_account@example.com"
    _IMAP_FAIL_LOCKOUT.pop(email.lower(), None)
    _IMAP_TEST_ATTEMPTS[f"fail:{email.lower()}"] = []

    # Record 3 failures
    _record_imap_failure(email)
    _record_imap_failure(email)
    _record_imap_failure(email)

    # Check should now raise 429 lockout
    with pytest.raises(HTTPException) as exc_info:
        _check_imap_rate_limit(user_id=user_id, email_address=email)

    assert exc_info.value.status_code == 429
    assert "failed login attempts" in exc_info.value.detail
