from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class StateStore:
    def __init__(self, path: Path, encryption_key: bytes) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        self._cipher = AESGCM(encryption_key)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY,
                    encrypted_payload BLOB NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    encrypted_payload BLOB NOT NULL,
                    user_id TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS collector_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS spool (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL UNIQUE,
                    payload BLOB NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS daily_usage (
                    day TEXT PRIMARY KEY,
                    post_reads INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS browser_session (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    encrypted_payload BLOB NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS seen_posts (
                    post_id TEXT PRIMARY KEY,
                    tab TEXT NOT NULL,
                    seen_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_seen_posts_seen_at ON seen_posts(seen_at);
                """
            )
        os.chmod(self.path, 0o600)

    def _encrypt(self, payload: dict[str, Any]) -> bytes:
        nonce = os.urandom(12)
        plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return nonce + self._cipher.encrypt(nonce, plaintext, b"timeline-cti-state-v1")

    def _decrypt(self, payload: bytes) -> dict[str, Any]:
        nonce, ciphertext = payload[:12], payload[12:]
        plaintext = self._cipher.decrypt(nonce, ciphertext, b"timeline-cti-state-v1")
        decoded = json.loads(plaintext)
        if not isinstance(decoded, dict):
            raise ValueError("encrypted state payload is not an object")
        return decoded

    def store_oauth_state(
        self, state: str, payload: dict[str, Any], ttl_seconds: int = 600
    ) -> None:
        now = int(time.time())
        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM oauth_states WHERE expires_at < ?", (now,))
            connection.execute(
                "INSERT OR REPLACE INTO oauth_states(state, encrypted_payload, expires_at) "
                "VALUES (?, ?, ?)",
                (state, self._encrypt(payload), now + ttl_seconds),
            )

    def consume_oauth_state(self, state: str) -> dict[str, Any] | None:
        now = int(time.time())
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT encrypted_payload, expires_at FROM oauth_states WHERE state = ?",
                (state,),
            ).fetchone()
            connection.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            connection.execute("COMMIT")
        if row is None or row["expires_at"] < now:
            return None
        return self._decrypt(row["encrypted_payload"])

    def store_oauth_token(self, token: dict[str, Any], user_id: str) -> None:
        now = int(time.time())
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO oauth_tokens(id, encrypted_payload, user_id, updated_at) "
                "VALUES (1, ?, ?, ?)",
                (self._encrypt(token), user_id, now),
            )
        self.audit("oauth_token_updated", {"user_id": user_id})

    def get_oauth_token(self) -> tuple[dict[str, Any], str] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT encrypted_payload, user_id FROM oauth_tokens WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        return self._decrypt(row["encrypted_payload"]), row["user_id"]

    def store_browser_session(self, cookies: list[dict[str, Any]]) -> None:
        now = int(time.time())
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO browser_session(id, encrypted_payload, updated_at) "
                "VALUES (1, ?, ?)",
                (self._encrypt({"cookies": cookies}), now),
            )
        self.audit("browser_session_updated", {"cookie_count": len(cookies)})

    def get_browser_session(self) -> list[dict[str, Any]] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT encrypted_payload FROM browser_session WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        payload = self._decrypt(row["encrypted_payload"])
        cookies = payload.get("cookies")
        if not isinstance(cookies, list):
            return None
        return [cookie for cookie in cookies if isinstance(cookie, dict)]

    def browser_session_connected(self) -> bool:
        return self.get_browser_session() is not None

    def mark_posts_seen(self, post_ids: list[str], tab: str) -> None:
        if not post_ids:
            return
        now = int(time.time())
        with self._connection() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO seen_posts(post_id, tab, seen_at) VALUES (?, ?, ?)",
                [(post_id, tab, now) for post_id in post_ids],
            )

    def filter_unseen_post_ids(self, post_ids: list[str]) -> list[str]:
        if not post_ids:
            return []
        placeholders = ",".join("?" for _ in post_ids)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT post_id FROM seen_posts WHERE post_id IN ({placeholders})",  # nosec B608
                post_ids,
            ).fetchall()
        seen = {str(row["post_id"]) for row in rows}
        return [post_id for post_id in post_ids if post_id not in seen]

    def prune_seen_posts(self, retention_days: int) -> int:
        cutoff = int(time.time()) - retention_days * 86_400
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM seen_posts WHERE seen_at < ?", (cutoff,))
            return int(cursor.rowcount)

    def set_value(self, key: str, value: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO collector_state(key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, int(time.time())),
            )

    def get_value(self, key: str, default: str = "") -> str:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM collector_state WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row is not None else default

    def enqueue(self, source_id: str, payload: dict[str, Any]) -> bool:
        encrypted = self._encrypt(payload)
        now = int(time.time())
        try:
            with self._connection() as connection:
                connection.execute(
                    "INSERT INTO spool(source_id, payload, available_at, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (source_id, encrypted, now, now),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def spool_size_bytes(self) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(LENGTH(payload)), 0) AS total FROM spool"
            ).fetchone()
        return int(row["total"] if row else 0)

    def spool_depth(self) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM spool").fetchone()
        return int(row["total"] if row else 0)

    def fetch_spool_batch(self, limit: int = 100) -> list[tuple[int, dict[str, Any]]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, payload FROM spool WHERE available_at <= ? ORDER BY id LIMIT ?",
                (int(time.time()), limit),
            ).fetchall()
        return [(int(row["id"]), self._decrypt(row["payload"])) for row in rows]

    def acknowledge_spool(self, row_ids: list[int]) -> None:
        if not row_ids:
            return
        placeholders = ",".join("?" for _ in row_ids)
        with self._connection() as connection:
            # Placeholder sayısı integer ID listesinden üretilir; değerler daima bind edilir.
            connection.execute(
                f"DELETE FROM spool WHERE id IN ({placeholders})",  # nosec B608
                row_ids,
            )

    def retry_spool(self, row_ids: list[int], delay_seconds: int) -> None:
        if not row_ids:
            return
        placeholders = ",".join("?" for _ in row_ids)
        parameters: list[int] = [int(time.time()) + delay_seconds, *row_ids]
        with self._connection() as connection:
            connection.execute(
                f"UPDATE spool SET attempts = attempts + 1, available_at = ? "  # nosec B608
                f"WHERE id IN ({placeholders})",
                parameters,
            )

    def add_usage(self, count: int) -> int:
        day = datetime.now(UTC).date().isoformat()
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO daily_usage(day, post_reads) VALUES (?, ?) "
                "ON CONFLICT(day) DO UPDATE SET post_reads = post_reads + excluded.post_reads",
                (day, count),
            )
            row = connection.execute(
                "SELECT post_reads FROM daily_usage WHERE day = ?", (day,)
            ).fetchone()
        return int(row["post_reads"] if row else count)

    def current_usage(self) -> int:
        day = datetime.now(UTC).date().isoformat()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT post_reads FROM daily_usage WHERE day = ?", (day,)
            ).fetchone()
        return int(row["post_reads"] if row else 0)

    def audit(self, event_type: str, detail: dict[str, Any]) -> None:
        safe_detail = json.dumps(detail, separators=(",", ":"), ensure_ascii=True)
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO audit(event_type, detail, created_at) VALUES (?, ?, ?)",
                (event_type, safe_detail, int(time.time())),
            )

    def status(self) -> dict[str, Any]:
        last_success = self.get_value("last_collector_success")
        compliance_success = self.get_value("last_compliance_success")
        return {
            "oauth_connected": self.get_oauth_token() is not None,
            "session_connected": self.browser_session_connected(),
            "collector_backend": self.get_value("collector_backend") or None,
            "spool_depth": self.spool_depth(),
            "spool_bytes": self.spool_size_bytes(),
            "daily_post_reads": self.current_usage(),
            "last_success": last_success or None,
            "last_compliance_success": compliance_success or None,
            "last_error": self.get_value("last_collector_error") or None,
        }
