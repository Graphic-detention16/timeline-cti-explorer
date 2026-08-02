from datetime import UTC, datetime
from typing import Any

from timeline_cti.clickhouse import ClickHouseRepository, highlight_offsets
from timeline_cti.models import SearchMode, SearchSort


class EmptyQueryResult:
    column_names: list[str] = []
    result_rows: list[tuple[Any, ...]] = []


class CapturingClient:
    def __init__(self) -> None:
        self.sql = ""
        self.parameters: dict[str, Any] = {}

    def query(self, sql: str, parameters: dict[str, Any]) -> EmptyQueryResult:
        self.sql = sql
        self.parameters = parameters
        return EmptyQueryResult()


def test_highlight_offsets_are_plain_ranges() -> None:
    offsets = highlight_offsets("Critical CVE and another CVE", "CVE")
    assert [(item.start, item.end) for item in offsets] == [(9, 12), (25, 28)]


def test_highlight_offsets_survive_casefold_expansion() -> None:
    offsets = highlight_offsets("İSTANBUL signal", "İstanbul")
    assert [(item.start, item.end) for item in offsets] == [(0, 8)]


def test_search_uses_bound_parameters_for_untrusted_terms(settings) -> None:  # type: ignore[no-untyped-def]
    repository = ClickHouseRepository(settings, role="api", session_secret="cursor-secret")
    client = CapturingClient()
    repository._client = client
    attack = "malware' OR 1=1 --"
    items, cursor = repository.search(
        attack,
        mode=SearchMode.ALL,
        sort=SearchSort.NEWEST,
        limit=20,
    )
    assert items == [] and cursor is None
    assert attack not in client.sql
    assert client.parameters["terms"] == ["malware'", "or", "1=1", "--"]


def test_recent_posts_are_ordered_by_ingestion_time(settings) -> None:  # type: ignore[no-untyped-def]
    repository = ClickHouseRepository(settings, role="api", session_secret="cursor-secret")
    client = CapturingClient()
    now = datetime.now(UTC)
    result = EmptyQueryResult()
    result.column_names = [
        "source_type",
        "post_id",
        "text",
        "username",
        "display_name",
        "lang",
        "created_at",
        "ingested_at",
        "cti_score",
        "cti_level",
        "cti_categories",
    ]
    result.result_rows = [
        (
            "x_home",
            "42",
            "recent text",
            "analyst",
            "Analyst",
            "en",
            now,
            now,
            70,
            "high",
            ["malware"],
        )
    ]
    client.query = lambda sql, parameters: (  # type: ignore[method-assign]
        setattr(client, "sql", sql),
        setattr(client, "parameters", parameters),
        result,
    )[-1]
    repository._client = client

    items = repository.recent_posts(limit=10)

    assert "ORDER BY ingested_at DESC" in client.sql
    assert client.parameters["limit"] == 10
    assert items[0].post_id == "42"
    assert items[0].source_url == "https://x.com/i/web/status/42"
