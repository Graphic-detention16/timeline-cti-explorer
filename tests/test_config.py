from __future__ import annotations

import base64
import hashlib
import secrets

import pytest
from argon2 import PasswordHasher
from pydantic import ValidationError

from timeline_cti.config import Settings


def valid_values() -> dict[str, object]:
    return {
        "APP_ENV": "test",
        "ADMIN_PASSWORD_HASH": PasswordHasher().hash("correct horse battery staple"),
        "SESSION_SECRET": secrets.token_urlsafe(48),
        "TOKEN_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "API_KEY_SHA256": hashlib.sha256(b"private-api-key").hexdigest(),
        "CLICKHOUSE_API_PASSWORD": "api-password-long-enough",
        "CLICKHOUSE_INGEST_PASSWORD": "ingest-password-long-enough",
    }


def test_rejects_placeholder_secret() -> None:
    values = valid_values()
    values["SESSION_SECRET"] = "CHANGE_ME_with_a_long_but_unsafe_value"
    with pytest.raises(ValidationError):
        Settings(**values)  # type: ignore[arg-type]


def test_rejects_unordered_thresholds() -> None:
    values = valid_values()
    values.update(
        {
            "CTI_MEDIUM_THRESHOLD": 80,
            "CTI_HIGH_THRESHOLD": 70,
            "CTI_CRITICAL_THRESHOLD": 90,
        }
    )
    with pytest.raises(ValidationError):
        Settings(**values)  # type: ignore[arg-type]


def test_rejects_noncanonical_encryption_key() -> None:
    values = valid_values()
    values["TOKEN_ENCRYPTION_KEY"] = "!" + str(values["TOKEN_ENCRYPTION_KEY"])
    with pytest.raises(ValidationError):
        Settings(**values)  # type: ignore[arg-type]


def test_rejects_digest_of_empty_api_key() -> None:
    values = valid_values()
    values["API_KEY_SHA256"] = hashlib.sha256(b"").hexdigest()
    with pytest.raises(ValidationError):
        Settings(**values)  # type: ignore[arg-type]


def test_parses_trusted_handles() -> None:
    values = valid_values()
    values["CTI_TRUSTED_HANDLES"] = "@CISA, threat_feed"
    settings = Settings(**values)  # type: ignore[arg-type]
    assert settings.trusted_handles == {"cisa", "threat_feed"}


def test_approved_live_mode_requires_compliance_credentials() -> None:
    values = valid_values()
    values["X_USE_CASE_APPROVED"] = True
    with pytest.raises(ValidationError):
        Settings(**values)  # type: ignore[arg-type]
