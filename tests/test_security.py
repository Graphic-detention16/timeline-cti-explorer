from __future__ import annotations

import hashlib

from argon2 import PasswordHasher

from timeline_cti.security import AuthManager, SlidingWindowRateLimiter


def test_password_session_and_api_key() -> None:
    api_key = "private-api-key"
    manager = AuthManager(
        PasswordHasher().hash("very strong password"),
        "session-secret-with-more-than-thirty-two-characters",
        hashlib.sha256(api_key.encode()).hexdigest(),
        3600,
    )
    assert manager.verify_password("very strong password")
    assert not manager.verify_password("wrong")
    token, expected = manager.issue_session()
    assert manager.verify_session(token) == expected
    assert manager.verify_api_key(api_key)
    assert not manager.verify_api_key("wrong")


def test_rate_limiter_rejects_excess() -> None:
    limiter = SlidingWindowRateLimiter()
    assert limiter.allow("login:client", 2)
    assert limiter.allow("login:client", 2)
    assert not limiter.allow("login:client", 2)
