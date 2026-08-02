from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


@dataclass(frozen=True)
class SessionPrincipal:
    subject: str
    csrf_token: str


class AuthManager:
    def __init__(
        self,
        password_hash: str,
        session_secret: str,
        api_key_sha256: str,
        max_age_seconds: int,
    ) -> None:
        self._password_hash = password_hash
        self._api_key_sha256 = api_key_sha256.lower()
        self._max_age_seconds = max_age_seconds
        self._password_hasher = PasswordHasher()
        self._serializer = URLSafeTimedSerializer(session_secret, salt="timeline-cti-session-v1")

    def verify_password(self, password: str) -> bool:
        try:
            return self._password_hasher.verify(self._password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False

    def issue_session(self) -> tuple[str, SessionPrincipal]:
        principal = SessionPrincipal(subject="admin", csrf_token=secrets.token_urlsafe(32))
        token = self._serializer.dumps(
            {"sub": principal.subject, "csrf": principal.csrf_token, "nonce": secrets.token_hex(8)}
        )
        return token, principal

    def verify_session(self, token: str) -> SessionPrincipal | None:
        try:
            payload: dict[str, Any] = self._serializer.loads(
                token,
                max_age=self._max_age_seconds,
            )
        except (BadSignature, SignatureExpired):
            return None
        if payload.get("sub") != "admin" or not isinstance(payload.get("csrf"), str):
            return None
        return SessionPrincipal(subject="admin", csrf_token=payload["csrf"])

    def verify_api_key(self, candidate: str) -> bool:
        digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        return hmac.compare_digest(digest, self._api_key_sha256)


class SlidingWindowRateLimiter:
    """Tek API örneği için kilitli, bellek içi kayan pencere sınırlayıcı."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = time.monotonic()
        threshold = now - window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] < threshold:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True
