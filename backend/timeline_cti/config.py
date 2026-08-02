from __future__ import annotations

import base64
import binascii
import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_MARKERS = ("change-me", "replace-me", "example", "your-")
WEAK_API_KEY_DIGESTS = {
    hashlib.sha256(value).hexdigest() for value in (b"", b"test", b"api-key", b"change-me")
}


class Settings(BaseSettings):
    """Tüm yapılandırmayı yalnız ortam değişkenlerinden yükler."""

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=True,
        extra="ignore",
    )

    APP_ENV: Literal["development", "test", "production"] = "development"
    APP_HOSTNAME: str = "localhost"
    HTTPS_PORT: int = Field(default=8443, ge=1024, le=65535)
    DEFAULT_LOCALE: Literal["en", "tr"] = "en"
    ALLOWED_ORIGINS: str = "https://localhost:8443"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    TLS_MODE: Literal["internal", "files"] = "internal"
    TLS_CERT_FILE: str = ""
    TLS_KEY_FILE: str = ""

    ADMIN_PASSWORD_HASH: SecretStr
    SESSION_SECRET: SecretStr
    TOKEN_ENCRYPTION_KEY: SecretStr
    API_KEY_SHA256: SecretStr
    SESSION_MAX_AGE_SECONDS: int = Field(default=43200, ge=900, le=604800)

    CLICKHOUSE_HOST: str = "clickhouse"
    CLICKHOUSE_PORT: int = Field(default=8123, ge=1, le=65535)
    CLICKHOUSE_SECURE: bool = False
    CLICKHOUSE_DATABASE: str = "timeline_cti"
    CLICKHOUSE_API_USER: str = "api_ro"
    CLICKHOUSE_API_PASSWORD: SecretStr
    CLICKHOUSE_INGEST_USER: str = "ingest_rw"
    CLICKHOUSE_INGEST_PASSWORD: SecretStr
    QUERY_TIMEOUT_SECONDS: int = Field(default=5, ge=1, le=30)

    STATE_DATABASE_PATH: Path = Path("/var/lib/timeline-cti/state.db")
    SPOOL_MAX_BYTES: int = Field(default=536_870_912, ge=1_048_576)

    X_CLIENT_ID: str = ""
    X_CLIENT_SECRET: SecretStr = SecretStr("")
    X_BEARER_TOKEN: SecretStr = SecretStr("")
    X_REDIRECT_URI: str = "https://localhost:8443/api/v1/auth/x/callback"
    X_POLL_SECONDS: int = Field(default=60, ge=30, le=3600)
    X_DAILY_READ_BUDGET: int = Field(default=10_000, ge=100)
    X_USE_CASE_APPROVED: bool = False
    X_API_BASE_URL: str = "https://api.x.com"
    X_AUTHORIZE_URL: str = "https://x.com/i/oauth2/authorize"

    COLLECTOR_BACKEND: Literal["selenium", "api"] = "selenium"
    SELENIUM_REMOTE_URL: str = "http://browser:4444/wd/hub"
    SELENIUM_SCROLL_SECONDS: int = Field(default=600, ge=60, le=3600)
    SELENIUM_IDLE_SECONDS: int = Field(default=3600, ge=300, le=86400)
    SELENIUM_IDLE_JITTER_SECONDS: int = Field(default=120, ge=0, le=900)
    SELENIUM_SEEN_RETENTION_DAYS: int = Field(default=30, ge=1, le=365)
    SELENIUM_LOCALE: str = "tr-TR"
    SELENIUM_TIMEZONE: str = "Europe/Istanbul"

    CTI_MEDIUM_THRESHOLD: int = Field(default=40, ge=1, le=98)
    CTI_HIGH_THRESHOLD: int = Field(default=70, ge=2, le=99)
    CTI_CRITICAL_THRESHOLD: int = Field(default=85, ge=3, le=100)
    CTI_TRUSTED_HANDLES: str = ""
    CTI_MODEL_PATH: Path = Path("/models/cti")
    CTI_MODEL_ID: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    CTI_MODEL_REVISION: str = "e62509716f15c5fd03a6fd3156a4bc5e43f83f26"
    CTI_MODEL_SHA256: str = ""
    CTI_MODEL_BATCH_SIZE: int = Field(default=16, ge=1, le=128)

    BACKUP_TARGET: str = "/backups"

    @field_validator("APP_HOSTNAME")
    @classmethod
    def validate_hostname(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9.-]+", value):
            raise ValueError("APP_HOSTNAME contains unsafe characters")
        return value

    @field_validator("SESSION_SECRET")
    @classmethod
    def validate_session_secret(cls, value: SecretStr) -> SecretStr:
        cls._validate_secret(value, "SESSION_SECRET", 32)
        return value

    @field_validator("API_KEY_SHA256")
    @classmethod
    def validate_api_hash(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not re.fullmatch(r"[a-fA-F0-9]{64}", raw) or raw.lower() in WEAK_API_KEY_DIGESTS:
            raise ValueError("API_KEY_SHA256 must be a 64-character hexadecimal digest")
        return value

    @field_validator("TOKEN_ENCRYPTION_KEY")
    @classmethod
    def validate_encryption_key(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        try:
            decoded = base64.b64decode(raw.encode("ascii"), altchars=b"-_", validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("TOKEN_ENCRYPTION_KEY must be URL-safe base64") from exc
        if len(decoded) != 32:
            raise ValueError("TOKEN_ENCRYPTION_KEY must decode to exactly 32 bytes")
        return value

    @model_validator(mode="after")
    def validate_security_posture(self) -> Settings:
        if not (self.CTI_MEDIUM_THRESHOLD < self.CTI_HIGH_THRESHOLD < self.CTI_CRITICAL_THRESHOLD):
            raise ValueError("CTI thresholds must increase monotonically")

        for name, value in (
            ("ADMIN_PASSWORD_HASH", self.ADMIN_PASSWORD_HASH),
            ("CLICKHOUSE_API_PASSWORD", self.CLICKHOUSE_API_PASSWORD),
            ("CLICKHOUSE_INGEST_PASSWORD", self.CLICKHOUSE_INGEST_PASSWORD),
        ):
            self._validate_secret(value, name, 12)

        admin_hash = self.ADMIN_PASSWORD_HASH.get_secret_value()
        if not admin_hash.startswith("$argon2id$"):
            raise ValueError("ADMIN_PASSWORD_HASH must use Argon2id")
        parameters = re.search(r"\$m=(\d+),t=(\d+),p=(\d+)\$", admin_hash)
        if not parameters or int(parameters[1]) < 65_536 or int(parameters[2]) < 3:
            raise ValueError("ADMIN_PASSWORD_HASH uses weak Argon2id cost parameters")

        if self.X_USE_CASE_APPROVED:
            if not self.X_CLIENT_ID:
                raise ValueError("approved live mode requires X_CLIENT_ID")
            if not self.X_BEARER_TOKEN.get_secret_value():
                raise ValueError("approved live mode requires X_BEARER_TOKEN for compliance jobs")

        if self.APP_ENV == "production":
            if not re.fullmatch(r"[a-fA-F0-9]{64}", self.CTI_MODEL_SHA256):
                raise ValueError("production requires a pinned CTI_MODEL_SHA256")
            if self.TLS_MODE == "files" and not (self.TLS_CERT_FILE and self.TLS_KEY_FILE):
                raise ValueError("file TLS mode requires a certificate and private key")
        return self

    @staticmethod
    def _validate_secret(value: SecretStr, name: str, minimum: int) -> None:
        raw = value.get_secret_value()
        normalized = re.sub(r"[\s_]+", "-", raw.lower())
        if len(raw) < minimum or any(marker in normalized for marker in PLACEHOLDER_MARKERS):
            raise ValueError(f"{name} is missing, weak, or still a placeholder")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    @property
    def trusted_handles(self) -> set[str]:
        return {
            handle.strip().lower().lstrip("@")
            for handle in self.CTI_TRUSTED_HANDLES.split(",")
            if handle.strip()
        }

    @property
    def token_encryption_key_bytes(self) -> bytes:
        return base64.b64decode(
            self.TOKEN_ENCRYPTION_KEY.get_secret_value(),
            altchars=b"-_",
            validate=True,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
