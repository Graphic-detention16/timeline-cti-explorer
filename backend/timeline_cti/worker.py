from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import structlog
from clickhouse_connect.driver.exceptions import ClickHouseError

from .clickhouse import ClickHouseRepository
from .config import get_settings
from .cti import CtiEngine, ScoreThresholds
from .logging import configure_logging
from .models import PostRecord
from .normalization import normalize_text
from .semantic import OnnxSemanticScorer
from .state import StateStore

logger = structlog.get_logger()


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def prepare_post(payload: dict[str, Any], engine: CtiEngine) -> PostRecord | None:
    post = payload.get("post", {})
    author = payload.get("author", {})
    if not isinstance(post, dict) or not post.get("id") or not post.get("text"):
        return None
    if bool(author.get("protected")):
        return None

    text = str(post["text"])
    referenced = post.get("referenced_tweets", [])
    referenced_map = post.get("_referenced_posts", {})
    if isinstance(referenced, list) and isinstance(referenced_map, dict):
        for relation in referenced:
            if not isinstance(relation, dict) or relation.get("type") not in {
                "retweeted",
                "quoted",
            }:
                continue
            expanded = referenced_map.get(str(relation.get("id", "")))
            if isinstance(expanded, dict) and len(str(expanded.get("text", ""))) > len(text):
                text = str(expanded["text"])

    public_metrics = post.get("public_metrics", {})
    metrics = {
        "replies": int(public_metrics.get("reply_count", 0)),
        "reposts": int(public_metrics.get("retweet_count", 0)),
        "quotes": int(public_metrics.get("quote_count", 0)),
        "likes": int(public_metrics.get("like_count", 0)),
        "bookmarks": int(public_metrics.get("bookmark_count", 0)),
        "impressions": int(public_metrics.get("impression_count", 0)),
    }
    assessment = engine.assess(text, str(author.get("username", "")), metrics)
    entities = post.get("entities", {}) if isinstance(post.get("entities"), dict) else {}
    urls = [
        str(item.get("expanded_url") or item.get("url"))
        for item in entities.get("urls", [])
        if isinstance(item, dict) and (item.get("expanded_url") or item.get("url"))
    ]
    hashtags = [
        str(item.get("tag", "")).lower()
        for item in entities.get("hashtags", [])
        if isinstance(item, dict) and item.get("tag")
    ]
    mentions = [
        str(item.get("username", "")).lower()
        for item in entities.get("mentions", [])
        if isinstance(item, dict) and item.get("username")
    ]
    referenced_ids = (
        [str(item["id"]) for item in referenced if isinstance(item, dict) and item.get("id")]
        if isinstance(referenced, list)
        else []
    )
    edit_history = post.get("edit_history_tweet_ids", [])
    created_at = _parse_datetime(post.get("created_at"))
    now = datetime.now(UTC)
    return PostRecord(
        post_id=str(post["id"]),
        author_id=str(post.get("author_id", "")),
        conversation_id=str(post.get("conversation_id", "")),
        text=text,
        normalized_text=normalize_text(text),
        lang=str(post.get("lang", "und")),
        created_at=created_at,
        username=str(author.get("username", "")).lower(),
        display_name=str(author.get("name", "")),
        author_verified=bool(author.get("verified")),
        author_protected=False,
        reply_count=metrics["replies"],
        repost_count=metrics["reposts"],
        quote_count=metrics["quotes"],
        like_count=metrics["likes"],
        bookmark_count=metrics["bookmarks"],
        impression_count=metrics["impressions"],
        urls=urls,
        hashtags=hashtags,
        mentions=mentions,
        referenced_post_ids=referenced_ids,
        assessment=assessment,
        content_version=max(1, len(edit_history) if isinstance(edit_history, list) else 1),
        source_updated_at=now,
        compliance_checked_at=now,
    )


def service_loop() -> None:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    state = StateStore(settings.STATE_DATABASE_PATH, settings.token_encryption_key_bytes)
    repository = ClickHouseRepository(
        settings,
        role="ingest",
        session_secret=settings.SESSION_SECRET.get_secret_value(),
    )
    semantic = OnnxSemanticScorer(
        settings.CTI_MODEL_PATH,
        settings.CTI_MODEL_REVISION,
        settings.CTI_MODEL_SHA256,
    )
    engine = CtiEngine(
        semantic,
        trusted_handles=settings.trusted_handles,
        thresholds=ScoreThresholds(
            medium=settings.CTI_MEDIUM_THRESHOLD,
            high=settings.CTI_HIGH_THRESHOLD,
            critical=settings.CTI_CRITICAL_THRESHOLD,
        ),
    )
    state.set_value("worker_scoring_mode", "hybrid" if semantic.available else "rules_only")
    logger.info("worker_started", semantic_model_available=semantic.available)

    while True:
        batch = state.fetch_spool_batch(100)
        if not batch:
            time.sleep(1)
            continue
        row_ids = [row_id for row_id, _ in batch]
        try:
            posts = [
                prepared for _, payload in batch if (prepared := prepare_post(payload, engine))
            ]
            repository.insert_posts(posts)
            state.acknowledge_spool(row_ids)
            logger.info("worker_batch_complete", received=len(batch), inserted=len(posts))
        except (ClickHouseError, OSError, RuntimeError, ValueError) as exc:
            state.retry_spool(row_ids, delay_seconds=30)
            logger.error(
                "worker_batch_failed", error_type=type(exc).__name__, batch_size=len(batch)
            )
            time.sleep(5)


def run() -> None:
    service_loop()


if __name__ == "__main__":
    run()
