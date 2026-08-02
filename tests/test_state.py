from __future__ import annotations

import secrets
import time
from pathlib import Path

from timeline_cti.state import StateStore


def test_oauth_state_is_one_time_and_encrypted(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    store = StateStore(path, secrets.token_bytes(32))
    store.store_oauth_state("random-state", {"verifier": "super-secret-verifier"})
    assert b"super-secret-verifier" not in path.read_bytes()
    assert store.consume_oauth_state("random-state") == {"verifier": "super-secret-verifier"}
    assert store.consume_oauth_state("random-state") is None


def test_spool_deduplicates_and_acknowledges(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    store = StateStore(path, secrets.token_bytes(32))
    assert store.enqueue("post-1", {"post": {"id": "post-1", "text": "private-fixture"}})
    assert not store.enqueue("post-1", {"post": {"id": "post-1"}})
    assert b"private-fixture" not in path.read_bytes()
    batch = store.fetch_spool_batch()
    assert len(batch) == 1
    store.acknowledge_spool([batch[0][0]])
    assert store.spool_depth() == 0


def test_tokens_are_encrypted_at_rest(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    store = StateStore(path, secrets.token_bytes(32))
    store.store_oauth_token({"access_token": "sensitive-token"}, "42")
    assert b"sensitive-token" not in path.read_bytes()
    assert store.get_oauth_token() == ({"access_token": "sensitive-token"}, "42")


def test_browser_session_is_encrypted_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    store = StateStore(path, secrets.token_bytes(32))
    cookies = [
        {"name": "auth_token", "value": "secret-auth"},
        {"name": "ct0", "value": "secret-ct0"},
    ]
    store.store_browser_session(cookies)
    assert b"secret-auth" not in path.read_bytes()
    assert store.get_browser_session() == cookies
    assert store.browser_session_connected()


def test_seen_posts_deduplicate_and_prune(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    store = StateStore(path, secrets.token_bytes(32))
    store.mark_posts_seen(["1", "2"], "following")
    assert store.filter_unseen_post_ids(["1", "2", "3"]) == ["3"]
    time.sleep(1.1)
    removed = store.prune_seen_posts(retention_days=0)
    assert removed >= 2
    assert store.filter_unseen_post_ids(["1"]) == ["1"]
