from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher

from .config import Settings, get_settings
from .state import StateStore


def hash_password(value: str) -> str:
    return PasswordHasher().hash(value)


def hash_api_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_secrets() -> None:
    api_key = secrets.token_urlsafe(36)
    session_secret = secrets.token_urlsafe(48)
    token_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    print(f"SESSION_SECRET={session_secret}")
    print(f"TOKEN_ENCRYPTION_KEY={token_key}")
    print(f"API_KEY={api_key}")
    print(f"API_KEY_SHA256={hash_api_key(api_key)}")


def _normalize_cookie(cookie: dict[str, Any]) -> dict[str, Any] | None:
    name = str(cookie.get("name", "")).strip()
    value = str(cookie.get("value", "")).strip()
    if not name or not value:
        return None
    normalized: dict[str, Any] = {"name": name, "value": value}
    if domain := cookie.get("domain"):
        normalized["domain"] = str(domain)
    if path := cookie.get("path"):
        normalized["path"] = str(path)
    if "secure" in cookie:
        normalized["secure"] = bool(cookie["secure"])
    return normalized


def import_cookies(path: Path, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    raw = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("cookie export must be a JSON array")
    cookies: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_cookie(item)
        if normalized is not None:
            cookies.append(normalized)
    names = {cookie["name"] for cookie in cookies}
    required = {"auth_token", "ct0"}
    if not required <= names:
        missing = ", ".join(sorted(required - names))
        raise ValueError(f"cookie export is missing required fields: {missing}")
    store = StateStore(settings.STATE_DATABASE_PATH, settings.token_encryption_key_bytes)
    store.store_browser_session(cookies)
    return len(cookies)


def main() -> None:
    parser = argparse.ArgumentParser(description="Timeline CTI Explorer administration helpers")
    subcommands = parser.add_subparsers(dest="command", required=True)
    password_parser = subcommands.add_parser("hash-password")
    password_parser.add_argument("password")
    api_parser = subcommands.add_parser("hash-api-key")
    api_parser.add_argument("api_key")
    subcommands.add_parser("generate-secrets")
    cookie_parser = subcommands.add_parser("import-cookies")
    cookie_parser.add_argument(
        "path",
        type=Path,
        help="JSON cookie file path, or - to read JSON from stdin",
    )
    args = parser.parse_args()
    if args.command == "hash-password":
        print(hash_password(args.password))
    elif args.command == "hash-api-key":
        print(hash_api_key(args.api_key))
    elif args.command == "import-cookies":
        count = import_cookies(args.path)
        print(f"imported {count} encrypted browser cookies")
    else:
        generate_secrets()


if __name__ == "__main__":
    main()
