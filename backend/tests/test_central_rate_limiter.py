import pytest

from backend.app import rate_limiter
from backend.app.rate_limiter import (
    _MEMORY_RATE_LIMITS,
    check_rate_limit,
)


@pytest.fixture(autouse=True)
def use_memory_rate_limiter(monkeypatch):
    _MEMORY_RATE_LIMITS.clear()

    def fail_redis(*args, **kwargs):
        raise RuntimeError("redis disabled for rate limiter tests")

    monkeypatch.setattr(rate_limiter.Redis, "from_url", fail_redis)
    yield
    _MEMORY_RATE_LIMITS.clear()


def test_rate_limiter_allows_under_limit() -> None:
    key = "user-test-under-limit"
    scope = "test_scope_1"
    _MEMORY_RATE_LIMITS.clear()

    allowed, retry_after = check_rate_limit(key=key, max_requests=3, window_seconds=60, scope=scope)
    assert allowed is True
    assert retry_after == 0


def test_rate_limiter_blocks_over_limit() -> None:
    key = "user-test-over-limit"
    scope = "test_scope_2"
    _MEMORY_RATE_LIMITS.clear()

    for _ in range(3):
        allowed, _ = check_rate_limit(key=key, max_requests=3, window_seconds=60, scope=scope)
        assert allowed is True

    # 4th request must be rejected
    blocked, retry_after = check_rate_limit(key=key, max_requests=3, window_seconds=60, scope=scope)
    assert blocked is False
    assert retry_after > 0
