from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class SearchMode(StrEnum):
    ALL = "all"
    ANY = "any"
    PHRASE = "phrase"


class SearchSort(StrEnum):
    RELEVANCE = "relevance"
    NEWEST = "newest"
    CTI = "cti"


class CtiLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IndicatorSet(BaseModel):
    ipv4: list[str] = Field(default_factory=list)
    ipv6: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    md5: list[str] = Field(default_factory=list)
    sha1: list[str] = Field(default_factory=list)
    sha256: list[str] = Field(default_factory=list)
    sha512: list[str] = Field(default_factory=list)
    cves: list[str] = Field(default_factory=list)
    attack_techniques: list[str] = Field(default_factory=list)
    filenames: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    threat_actors: list[str] = Field(default_factory=list)

    def total(self) -> int:
        return sum(len(value) for value in self.model_dump().values())


class CtiAssessment(BaseModel):
    score: int = Field(ge=0, le=100)
    level: CtiLevel
    rule_score: int = Field(ge=0, le=100)
    semantic_score: float | None = Field(default=None, ge=0, le=100)
    scoring_mode: Literal["hybrid", "rules_only"]
    categories: list[str]
    indicators: IndicatorSet
    reasons: list[str]
    scorer_version: str
    model_revision: str | None = None


class PostRecord(BaseModel):
    source_type: Literal["x_home", "synthetic"] = "x_home"
    post_id: str
    author_id: str = ""
    conversation_id: str = ""
    text: str
    normalized_text: str
    lang: str = "und"
    created_at: datetime
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    username: str = ""
    display_name: str = ""
    author_verified: bool = False
    author_protected: bool = False
    reply_count: int = 0
    repost_count: int = 0
    quote_count: int = 0
    like_count: int = 0
    bookmark_count: int = 0
    impression_count: int = 0
    urls: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    referenced_post_ids: list[str] = Field(default_factory=list)
    assessment: CtiAssessment
    content_version: int = 1
    source_updated_at: datetime
    compliance_checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Highlight(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class RecentPostResult(BaseModel):
    post_id: str
    text: str
    username: str
    display_name: str
    lang: str
    created_at: datetime
    ingested_at: datetime
    cti_score: int
    cti_level: CtiLevel
    cti_categories: list[str]
    source_url: str | None


class SearchResult(BaseModel):
    post_id: str
    text: str
    username: str
    display_name: str
    lang: str
    created_at: datetime
    cti_score: int
    cti_level: CtiLevel
    cti_categories: list[str]
    cti_reasons: list[str]
    indicators: IndicatorSet
    scoring_mode: str
    scorer_version: str
    model_revision: str
    highlights: list[Highlight]
    metrics: dict[str, int]
    source_url: str | None


class ApiEnvelope(BaseModel):
    data: Any
    meta: dict[str, Any]
    error: None = None
