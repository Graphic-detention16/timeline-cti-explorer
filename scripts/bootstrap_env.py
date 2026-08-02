#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import secrets
from pathlib import Path

try:
    from argon2 import PasswordHasher
except ImportError as exc:
    raise SystemExit("Install the project first: python -m pip install -e .") from exc


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"
TARGET = ROOT / ".env"


def random_secret(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a secure local .env file")
    parser.add_argument("--force", action="store_true", help="Replace an existing .env")
    args = parser.parse_args()
    if TARGET.exists() and not args.force:
        raise SystemExit(".env already exists; use --force only after backing it up")

    password = getpass.getpass("Administrator password (16+ characters): ")
    confirmation = getpass.getpass("Repeat administrator password: ")
    if password != confirmation or len(password) < 16:
        raise SystemExit("Passwords do not match or are shorter than 16 characters")

    api_key = random_secret(36)
    clickhouse_admin = random_secret(30)
    clickhouse_api = random_secret(30)
    clickhouse_ingest = random_secret(30)
    grafana_admin = random_secret(30)
    values = {
        "ADMIN_PASSWORD_HASH": f"'{PasswordHasher().hash(password)}'",
        "SESSION_SECRET": random_secret(48),
        "TOKEN_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "API_KEY_SHA256": digest(api_key),
        "CLICKHOUSE_ADMIN_PASSWORD": clickhouse_admin,
        "CLICKHOUSE_API_PASSWORD": clickhouse_api,
        "CLICKHOUSE_API_PASSWORD_SHA256": digest(clickhouse_api),
        "CLICKHOUSE_INGEST_PASSWORD": clickhouse_ingest,
        "CLICKHOUSE_INGEST_PASSWORD_SHA256": digest(clickhouse_ingest),
        "GRAFANA_ADMIN_PASSWORD": grafana_admin,
    }

    prepared: list[str] = []
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0] if "=" in line else ""
        prepared.append(f"{key}={values[key]}" if key in values else line)
    TARGET.write_text("\n".join(prepared) + "\n", encoding="utf-8")
    TARGET.chmod(0o600)
    print("Created .env with mode 0600.")
    print("Store this API key now; it will not be written to disk:")
    print(api_key)
    print("The optional Grafana administrator password is stored only in .env:")
    print(grafana_admin)


if __name__ == "__main__":
    main()
