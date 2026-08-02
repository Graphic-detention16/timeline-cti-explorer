from __future__ import annotations

from timeline_cti.selenium_extraction import build_author, build_post, parse_metric_label


def test_parse_metric_label_handles_suffixes() -> None:
    assert parse_metric_label("1,234 Replies") == 1234
    assert parse_metric_label("1.2K Reposts") == 1200
    assert parse_metric_label("3M Views") == 3_000_000


def test_build_post_emits_api_shape() -> None:
    post = build_post(
        {
            "post_id": "1234567890",
            "permalink": "/alice/status/1234567890",
            "created_at": "2026-01-15T10:00:00.000Z",
            "text": "CVE-2026-4242 observed in the wild https://example.com",
            "lang": "en",
            "username": "alice",
            "display_name": "Alice",
            "verified": True,
            "reply_label": "12 Replies",
            "retweet_label": "4 Reposts",
            "like_label": "99 Likes",
            "impression_label": "1.5K Views",
            "urls": [{"url": "https://t.co/abc", "expanded_url": "https://example.com"}],
            "hashtags": ["cti"],
            "mentions": ["bob"],
            "quoted_post_id": "9988776655",
            "quoted_text": "quoted body",
        }
    )
    assert post is not None
    assert post["id"] == "1234567890"
    assert post["public_metrics"]["reply_count"] == 12
    assert post["public_metrics"]["retweet_count"] == 4
    assert post["public_metrics"]["like_count"] == 99
    assert post["public_metrics"]["impression_count"] == 1500
    assert post["entities"]["hashtags"] == [{"tag": "cti"}]
    assert post["referenced_tweets"] == [{"type": "quoted", "id": "9988776655"}]
    assert post["_referenced_posts"]["9988776655"]["text"] == "quoted body"


def test_build_post_rejects_empty_text() -> None:
    assert build_post({"post_id": "1", "text": "   "}) is None


def test_build_author_maps_profile_fields() -> None:
    author = build_author(
        {"username": "@alice", "display_name": "Alice", "verified": True},
    )
    assert author["username"] == "alice"
    assert author["name"] == "Alice"
    assert author["verified"] is True
