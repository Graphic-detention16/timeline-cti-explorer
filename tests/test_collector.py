from __future__ import annotations

from typing import Any

import pytest

from timeline_cti.collector import Collector
from timeline_cti.x_client import TimelinePage


class FakeState:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.usage = 99
        self.seen: set[str] = set()

    def spool_size_bytes(self) -> int:
        return 0

    def current_usage(self) -> int:
        return self.usage

    def get_value(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    def set_value(self, key: str, value: str) -> None:
        self.values[key] = value

    def enqueue(self, source_id: str, payload: dict[str, Any]) -> bool:
        return True

    def add_usage(self, count: int) -> int:
        self.usage += count
        return self.usage

    def audit(self, event_type: str, detail: dict[str, Any]) -> None:
        return None

    def mark_posts_seen(self, post_ids: list[str], tab: str) -> None:
        self.seen.update(post_ids)


class FakeSource:
    name = "api"
    requested_budget = 0

    async def fetch(self, budget: int) -> TimelinePage:
        self.requested_budget = budget
        return TimelinePage(
            posts=[{"id": "100", "text": "fixture", "author_id": "7"}],
            users={"7": {"username": "alice", "name": "Alice"}},
            newest_id="100",
            next_token=None,
        )


@pytest.mark.asyncio
async def test_collector_never_requests_beyond_daily_budget() -> None:
    state = FakeState()
    source = FakeSource()
    collector = Collector(source, state, spool_limit=1_000_000, budget=100)  # type: ignore[arg-type]
    result = await collector.run_once()
    assert source.requested_budget == 1
    assert result["daily_reads"] == 100
    assert result["backend"] == "api"
