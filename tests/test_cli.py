from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from timeline_cti.cli import import_cookies
from timeline_cti.config import Settings


def test_import_cookies_requires_auth_fields(settings: Settings, tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(json.dumps([{"name": "auth_token", "value": "abc"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="ct0"):
        import_cookies(cookie_file, settings)


def test_import_cookies_stores_encrypted_session(settings: Settings, tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(
        json.dumps(
            [
                {"name": "auth_token", "value": "abc", "domain": ".x.com"},
                {"name": "ct0", "value": "def", "domain": ".x.com"},
            ]
        ),
        encoding="utf-8",
    )
    count = import_cookies(cookie_file, settings)
    assert count == 2
    assert b"abc" not in settings.STATE_DATABASE_PATH.read_bytes()


def test_import_cookies_reads_stdin(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.dumps(
        [
            {"name": "auth_token", "value": "stdin-auth", "domain": ".x.com"},
            {"name": "ct0", "value": "stdin-ct0", "domain": ".x.com"},
        ]
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert import_cookies(Path("-"), settings) == 2
    assert b"stdin-auth" not in settings.STATE_DATABASE_PATH.read_bytes()
