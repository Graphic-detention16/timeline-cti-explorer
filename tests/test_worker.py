from __future__ import annotations

from timeline_cti.cti import CtiEngine, ScoreThresholds
from timeline_cti.semantic import NullSemanticScorer
from timeline_cti.worker import prepare_post


def test_prepare_post_rejects_protected_author() -> None:
    engine = CtiEngine(NullSemanticScorer(), set(), ScoreThresholds())
    payload = {
        "post": {"id": "1", "text": "example", "created_at": "2026-01-01T00:00:00Z"},
        "author": {"protected": True},
    }
    assert prepare_post(payload, engine) is None


def test_prepare_post_maps_metrics_and_entities() -> None:
    engine = CtiEngine(NullSemanticScorer(), set(), ScoreThresholds())
    payload = {
        "post": {
            "id": "123",
            "author_id": "7",
            "text": "CVE-2026-4242 at evil.example",
            "created_at": "2026-01-01T00:00:00Z",
            "lang": "en",
            "public_metrics": {"like_count": 10, "retweet_count": 2},
            "entities": {"hashtags": [{"tag": "CTI"}]},
            "edit_history_tweet_ids": ["123"],
        },
        "author": {"id": "7", "username": "analyst", "name": "Analyst"},
    }
    post = prepare_post(payload, engine)
    assert post is not None
    assert post.like_count == 10
    assert post.repost_count == 2
    assert post.hashtags == ["cti"]
    assert post.assessment.indicators.cves == ["CVE-2026-4242"]
