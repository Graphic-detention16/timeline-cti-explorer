from __future__ import annotations

import asyncio
import random
import time
from datetime import UTC, datetime

import structlog

from .compliance import ComplianceError, ComplianceRunner
from .config import Settings, get_settings
from .logging import configure_logging
from .selenium_client import SeleniumSessionError
from .sources import SeleniumSource, TimelineSource, create_timeline_source
from .state import StateStore
from .x_client import XApiError, XClient, XRateLimitError

logger = structlog.get_logger()


class Collector:
    def __init__(
        self,
        source: TimelineSource,
        state_store: StateStore,
        spool_limit: int,
        budget: int,
        *,
        tab: str | None = None,
    ) -> None:
        self.source = source
        self.state_store = state_store
        self.spool_limit = spool_limit
        self.budget = budget
        self.tab = tab

    async def run_once(self) -> dict[str, int | str]:
        if self.state_store.spool_size_bytes() >= self.spool_limit:
            raise XApiError("durable spool reached its configured byte limit")
        starting_usage = self.state_store.current_usage()
        if starting_usage >= self.budget:
            raise XApiError("daily post-read budget has been reached")

        remaining_budget = self.budget - starting_usage
        page = await self.source.fetch(remaining_budget)
        inserted = 0
        fetched = len(page.posts)
        newest_id: str | None = None
        tab = self.tab or self.state_store.get_value("selenium_last_tab") or "following"

        for post in page.posts:
            post_id = str(post["id"])
            author = page.users.get(post_id) or page.users.get(str(post.get("author_id", "")), {})
            if bool(author.get("protected")):
                continue
            payload = {"post": post, "author": author}
            if not self.state_store.enqueue(post_id, payload):
                continue
            inserted += 1
            if isinstance(self.source, SeleniumSource):
                self.state_store.mark_posts_seen([post_id], tab)
            newest_id = newest_id or post_id

        usage = self.state_store.add_usage(fetched)
        if newest_id and self.source.name == "api":
            self.state_store.set_value("timeline_since_id", newest_id)
        now = datetime.now(UTC).isoformat()
        self.state_store.set_value("last_collector_success", now)
        self.state_store.set_value("last_collector_error", "")
        self.state_store.set_value("collector_backend", self.source.name)
        self.state_store.audit(
            "collector_success",
            {
                "backend": self.source.name,
                "fetched": fetched,
                "enqueued": inserted,
                "daily_reads": usage,
            },
        )
        return {
            "backend": self.source.name,
            "fetched": fetched,
            "enqueued": inserted,
            "daily_reads": usage,
        }


async def service_loop() -> None:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    state = StateStore(settings.STATE_DATABASE_PATH, settings.token_encryption_key_bytes)
    client = XClient(settings, state)
    source = create_timeline_source(settings, state, client)
    collector = Collector(source, state, settings.SPOOL_MAX_BYTES, settings.X_DAILY_READ_BUDGET)
    compliance = ComplianceRunner(settings, state)
    backoff = settings.X_POLL_SECONDS

    while True:
        if not collection_enabled(settings, state):
            await asyncio.sleep(idle_sleep_seconds(settings))
            continue
        try:
            if settings.COLLECTOR_BACKEND == "api" and compliance.is_due():
                await compliance.run_once()
            if settings.COLLECTOR_BACKEND == "selenium":
                state.prune_seen_posts(settings.SELENIUM_SEEN_RETENTION_DAYS)
            result = await collector.run_once()
            logger.info("collector_cycle_complete", **result)
            backoff = idle_sleep_seconds(settings)
        except XRateLimitError as exc:
            backoff = max(settings.X_POLL_SECONDS, exc.reset_at - int(time.time()) + 2)
            state.set_value("last_collector_error", "rate limited")
            logger.warning("collector_rate_limited", retry_seconds=backoff)
        except (ComplianceError, XApiError, SeleniumSessionError, OSError, ValueError) as exc:
            state.set_value("last_collector_error", str(exc)[:240])
            backoff = min(max(backoff * 2, 60), 3600) + random.randint(  # noqa: S311  # nosec B311
                0, 10
            )
            if isinstance(exc, SeleniumSessionError):
                backoff = idle_sleep_seconds(settings)
            logger.error(
                "collector_cycle_failed",
                backend=settings.COLLECTOR_BACKEND,
                error_type=type(exc).__name__,
                retry_seconds=backoff,
            )
        await asyncio.sleep(backoff)


def collection_enabled(settings: Settings, state: StateStore) -> bool:
    if settings.COLLECTOR_BACKEND == "api":
        return settings.X_USE_CASE_APPROVED
    return state.browser_session_connected()


def idle_sleep_seconds(settings: Settings) -> int:
    if settings.COLLECTOR_BACKEND == "selenium":
        return settings.SELENIUM_IDLE_SECONDS + random.randint(  # noqa: S311  # nosec B311
            0, settings.SELENIUM_IDLE_JITTER_SECONDS
        )
    return settings.X_POLL_SECONDS


def run() -> None:
    asyncio.run(service_loop())


if __name__ == "__main__":
    run()
