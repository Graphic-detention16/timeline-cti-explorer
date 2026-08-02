from __future__ import annotations

import base64
import hashlib
import secrets
from pathlib import Path

import pytest
from argon2 import PasswordHasher

from timeline_cti.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    api_key = "test-api-key-with-sufficient-entropy"
    return Settings(
        APP_ENV="test",
        APP_HOSTNAME="localhost",
        HTTPS_PORT=8443,
        ALLOWED_ORIGINS="https://localhost:8443",
        ADMIN_PASSWORD_HASH=PasswordHasher().hash("correct horse battery staple"),
        SESSION_SECRET=secrets.token_urlsafe(48),
        TOKEN_ENCRYPTION_KEY=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        API_KEY_SHA256=hashlib.sha256(api_key.encode()).hexdigest(),
        CLICKHOUSE_API_PASSWORD="test-api-password-long",
        CLICKHOUSE_INGEST_PASSWORD="test-ingest-password-long",
        STATE_DATABASE_PATH=tmp_path / "state.db",
    )
