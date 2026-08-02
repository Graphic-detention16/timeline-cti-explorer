from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from .config import Settings
from .selenium_client import (
    SeleniumSessionError,
    build_fingerprint,
    crawl_timeline,
    create_remote_driver,
    ensure_session_ready,
    load_session,
    next_tab,
)
from .state import StateStore
from .x_client import TimelinePage, XApiError, XClient


class TimelineSource(Protocol):
    name: str

    async def fetch(self, budget: int) -> TimelinePage: ...


@dataclass
class XApiSource:
    x_client: XClient
    state_store: StateStore
    name: str = "api"

    async def fetch(self, budget: int) -> TimelinePage:
        token, user_id = await self.x_client.refresh_if_needed()
        access_token = str(token["access_token"])
        since_id = self.state_store.get_value("timeline_since_id") or None
        pagination_token: str | None = None
        posts: list[dict[str, Any]] = []
        users: dict[str, dict[str, Any]] = {}
        newest_id: str | None = None
        fetched = 0

        while fetched < budget:
            page = await self.x_client.fetch_home_page(
                access_token,
                user_id,
                since_id=since_id,
                pagination_token=pagination_token,
                max_results=min(100, budget - fetched),
            )
            fetched += len(page.posts)
            posts.extend(page.posts)
            users.update(page.users)
            newest_id = newest_id or page.newest_id
            pagination_token = page.next_token
            if not pagination_token:
                break

        return TimelinePage(
            posts=posts[:budget],
            users=users,
            newest_id=newest_id,
            next_token=None,
        )


@dataclass
class SeleniumSource:
    settings: Settings
    state_store: StateStore
    name: str = "selenium"

    async def fetch(self, budget: int) -> TimelinePage:
        cookies = self.state_store.get_browser_session()
        if cookies is None:
            raise SeleniumSessionError("browser session has not been imported")

        last_tab = self.state_store.get_value("selenium_last_tab", "for_you")
        tab = next_tab(last_tab)
        fingerprint = build_fingerprint(self.settings)

        def _run() -> TimelinePage:
            driver = create_remote_driver(self.settings, fingerprint)
            try:
                load_session(driver, cookies)
                ensure_session_ready(driver)
                items = crawl_timeline(
                    driver,
                    tab=tab,
                    scroll_seconds=self.settings.SELENIUM_SCROLL_SECONDS,
                    budget=budget,
                )
            finally:
                driver.quit()

            unseen_ids = self.state_store.filter_unseen_post_ids(
                [str(item["_raw_id"]) for item in items if item.get("_raw_id")]
            )
            unseen = {post_id for post_id in unseen_ids}
            posts: list[dict[str, Any]] = []
            users: dict[str, dict[str, Any]] = {}
            for item in items:
                post_id = str(item.get("_raw_id", ""))
                if post_id not in unseen:
                    continue
                post = item["post"]
                author = item["author"]
                posts.append(post)
                users[post_id] = author
            return TimelinePage(posts=posts, users=users, newest_id=None, next_token=None)

        page = await asyncio.to_thread(_run)
        self.state_store.set_value("selenium_last_tab", tab)
        self.state_store.set_value("collector_backend", self.name)
        return page


def create_timeline_source(
    settings: Settings,
    state_store: StateStore,
    x_client: XClient | None = None,
) -> TimelineSource:
    if settings.COLLECTOR_BACKEND == "api":
        if x_client is None:
            raise XApiError("X API source requires an XClient instance")
        return XApiSource(x_client=x_client, state_store=state_store)
    return SeleniumSource(settings=settings, state_store=state_store)
