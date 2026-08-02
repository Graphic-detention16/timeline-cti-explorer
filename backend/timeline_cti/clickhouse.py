from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from typing import Any

import clickhouse_connect
from itsdangerous import BadSignature, URLSafeSerializer

from .config import Settings
from .models import (
    CtiLevel,
    Highlight,
    IndicatorSet,
    PostRecord,
    RecentPostResult,
    SearchMode,
    SearchResult,
    SearchSort,
)
from .normalization import normalize_text, query_terms

POST_COLUMNS = [
    "source_type",
    "post_id",
    "author_id",
    "conversation_id",
    "text",
    "normalized_text",
    "lang",
    "created_at",
    "ingested_at",
    "username",
    "display_name",
    "author_verified",
    "author_protected",
    "reply_count",
    "repost_count",
    "quote_count",
    "like_count",
    "bookmark_count",
    "impression_count",
    "urls",
    "hashtags",
    "mentions",
    "referenced_post_ids",
    "cti_score",
    "cti_level",
    "cti_rule_score",
    "cti_semantic_score",
    "cti_scoring_mode",
    "cti_categories",
    "cti_reasons",
    "ioc_ipv4",
    "ioc_ipv6",
    "ioc_domains",
    "ioc_urls",
    "ioc_emails",
    "ioc_md5",
    "ioc_sha1",
    "ioc_sha256",
    "ioc_sha512",
    "ioc_cves",
    "ioc_attack_techniques",
    "ioc_filenames",
    "ioc_hashtags",
    "ioc_threat_actors",
    "scorer_version",
    "model_revision",
    "content_version",
    "source_updated_at",
    "compliance_checked_at",
]

SEARCH_SELECT = """
source_type, post_id, text, username, display_name, lang, created_at,
cti_score, cti_level, cti_categories, cti_reasons,
ioc_ipv4, ioc_ipv6, ioc_domains, ioc_urls, ioc_emails,
ioc_md5, ioc_sha1, ioc_sha256, ioc_sha512, ioc_cves,
ioc_attack_techniques, ioc_filenames, ioc_hashtags, ioc_threat_actors,
cti_scoring_mode, scorer_version, model_revision,
reply_count, repost_count, quote_count, like_count, bookmark_count, impression_count
"""


class InvalidCursorError(ValueError):
    pass


class ClickHouseRepository:
    def __init__(self, settings: Settings, role: str, session_secret: str) -> None:
        self.settings = settings
        self.role = role
        self._client: Any = None
        self._cursor = URLSafeSerializer(session_secret, salt="timeline-cti-cursor-v1")

    def _get_client(self) -> Any:
        if self._client is None:
            ingest = self.role == "ingest"
            username = (
                self.settings.CLICKHOUSE_INGEST_USER
                if ingest
                else self.settings.CLICKHOUSE_API_USER
            )
            password = (
                self.settings.CLICKHOUSE_INGEST_PASSWORD
                if ingest
                else self.settings.CLICKHOUSE_API_PASSWORD
            ).get_secret_value()
            self._client = clickhouse_connect.get_client(
                host=self.settings.CLICKHOUSE_HOST,
                port=self.settings.CLICKHOUSE_PORT,
                username=username,
                password=password,
                database=self.settings.CLICKHOUSE_DATABASE,
                secure=self.settings.CLICKHOUSE_SECURE,
                connect_timeout=5,
                send_receive_timeout=self.settings.QUERY_TIMEOUT_SECONDS,
            )
        return self._client

    def ping(self) -> bool:
        return bool(self._get_client().ping())

    def insert_posts(self, posts: list[PostRecord]) -> None:
        if not posts:
            return
        rows = [self._record_to_row(post) for post in posts]
        self._get_client().insert("posts", rows, column_names=POST_COLUMNS)

    @staticmethod
    def _record_to_row(post: PostRecord) -> list[Any]:
        assessment = post.assessment
        indicators = assessment.indicators
        semantic = assessment.semantic_score if assessment.semantic_score is not None else -1.0
        return [
            post.source_type,
            post.post_id,
            post.author_id,
            post.conversation_id,
            post.text,
            post.normalized_text,
            post.lang,
            post.created_at,
            post.ingested_at,
            post.username,
            post.display_name,
            post.author_verified,
            post.author_protected,
            post.reply_count,
            post.repost_count,
            post.quote_count,
            post.like_count,
            post.bookmark_count,
            post.impression_count,
            post.urls,
            post.hashtags,
            post.mentions,
            post.referenced_post_ids,
            assessment.score,
            assessment.level.value,
            assessment.rule_score,
            semantic,
            assessment.scoring_mode,
            assessment.categories,
            assessment.reasons,
            indicators.ipv4,
            indicators.ipv6,
            indicators.domains,
            indicators.urls,
            indicators.emails,
            indicators.md5,
            indicators.sha1,
            indicators.sha256,
            indicators.sha512,
            indicators.cves,
            indicators.attack_techniques,
            indicators.filenames,
            indicators.hashtags,
            indicators.threat_actors,
            assessment.scorer_version,
            assessment.model_revision or "",
            post.content_version,
            post.source_updated_at,
            post.compliance_checked_at,
        ]

    def search(
        self,
        query: str,
        mode: SearchMode,
        sort: SearchSort,
        limit: int,
        cursor: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        lang: str | None = None,
        cti_min: int | None = None,
        cti_level: CtiLevel | None = None,
        cti_category: str | None = None,
        ioc_type: str | None = None,
        author: str | None = None,
    ) -> tuple[list[SearchResult], str | None]:
        normalized_query = normalize_text(query)
        # Güncel text index fonksiyonları kullanıcı girdisini parametre olarak alır.
        if mode == SearchMode.PHRASE:
            conditions = ["hasPhrase(normalized_text, {query:String})"]
            params: dict[str, Any] = {"query": normalized_query, "limit": limit + 1}
        else:
            function = "hasAllTokens" if mode == SearchMode.ALL else "hasAnyTokens"
            conditions = [f"{function}(normalized_text, {{terms:Array(String)}})"]
            params = {"terms": query_terms(normalized_query), "limit": limit + 1}

        if from_date:
            conditions.append("created_at >= {from_date:DateTime64(3, 'UTC')}")
            params["from_date"] = from_date
        if to_date:
            conditions.append("created_at <= {to_date:DateTime64(3, 'UTC')}")
            params["to_date"] = to_date
        if lang:
            conditions.append("lang = {lang:String}")
            params["lang"] = lang
        if cti_min is not None:
            conditions.append("cti_score >= {cti_min:UInt8}")
            params["cti_min"] = cti_min
        if cti_level:
            conditions.append("toString(cti_level) = {cti_level:String}")
            params["cti_level"] = cti_level.value
        if cti_category:
            conditions.append("has(cti_categories, {cti_category:String})")
            params["cti_category"] = cti_category
        if author:
            conditions.append("username = {author:String}")
            params["author"] = author.lstrip("@").lower()

        ioc_columns = {
            "ip": "length(ioc_ipv4) + length(ioc_ipv6) > 0",
            "domain": "notEmpty(ioc_domains)",
            "url": "notEmpty(ioc_urls)",
            "hash": (
                "length(ioc_md5) + length(ioc_sha1) + length(ioc_sha256) + length(ioc_sha512) > 0"
            ),
            "cve": "notEmpty(ioc_cves)",
            "attack": "notEmpty(ioc_attack_techniques)",
        }
        if ioc_type:
            conditions.append(ioc_columns[ioc_type])

        order_sql = "created_at DESC, post_id DESC"
        cursor_payload = self._decode_cursor(cursor) if cursor else None
        if sort in {SearchSort.CTI, SearchSort.RELEVANCE}:
            order_sql = "cti_score DESC, created_at DESC, post_id DESC"
            if cursor_payload:
                conditions.append(
                    "(cti_score, created_at, post_id) < "
                    "({cursor_score:UInt8}, {cursor_date:DateTime64(3, 'UTC')}, {cursor_id:String})"
                )
        elif cursor_payload:
            conditions.append(
                "(created_at, post_id) < ({cursor_date:DateTime64(3, 'UTC')}, {cursor_id:String})"
            )
        if cursor_payload:
            params.update(
                {
                    "cursor_score": int(cursor_payload.get("score", 0)),
                    "cursor_date": datetime.fromisoformat(str(cursor_payload["date"])),
                    "cursor_id": str(cursor_payload["id"]),
                }
            )

        # SQL parçaları yalnız doğrulanmış enum ve sabitlerden gelir.
        sql = (
            f"SELECT {SEARCH_SELECT} FROM posts FINAL WHERE {' AND '.join(conditions)} "  # nosec B608
            f"ORDER BY {order_sql} LIMIT {{limit:UInt16}}"
        )
        result = self._get_client().query(sql, parameters=params)
        items = [
            self._row_to_result(dict(zip(result.column_names, row, strict=True)), query)
            for row in result.result_rows
        ]
        next_cursor = None
        if len(items) > limit:
            items = items[:limit]
            last = items[-1]
            next_cursor = self._cursor.dumps(
                {
                    "score": last.cti_score,
                    "date": last.created_at.isoformat(),
                    "id": last.post_id,
                }
            )
        return items, next_cursor

    def recent_posts(self, limit: int = 50) -> list[RecentPostResult]:
        result = self._get_client().query(
            "SELECT source_type, post_id, text, username, display_name, lang, "
            "created_at, ingested_at, cti_score, cti_level, cti_categories "
            "FROM posts FINAL ORDER BY ingested_at DESC, post_id DESC LIMIT {limit:UInt16}",
            parameters={"limit": limit},
        )
        items: list[RecentPostResult] = []
        for raw_row in result.result_rows:
            row = dict(zip(result.column_names, raw_row, strict=True))
            created_at = row["created_at"]
            ingested_at = row["ingested_at"]
            items.append(
                RecentPostResult(
                    post_id=str(row["post_id"]),
                    text=str(row["text"]),
                    username=str(row["username"]),
                    display_name=str(row["display_name"]),
                    lang=str(row["lang"]),
                    created_at=created_at.replace(tzinfo=UTC)
                    if created_at.tzinfo is None
                    else created_at,
                    ingested_at=ingested_at.replace(tzinfo=UTC)
                    if ingested_at.tzinfo is None
                    else ingested_at,
                    cti_score=int(row["cti_score"]),
                    cti_level=CtiLevel(row["cti_level"]),
                    cti_categories=list(row["cti_categories"]),
                    source_url=(
                        f"https://x.com/i/web/status/{row['post_id']}"
                        if row["source_type"] == "x_home"
                        else None
                    ),
                )
            )
        return items

    def get_post(self, post_id: str) -> SearchResult | None:
        result = self._get_client().query(
            f"SELECT {SEARCH_SELECT} FROM posts FINAL WHERE post_id = {{post_id:String}} "  # nosec B608
            "ORDER BY content_version DESC LIMIT 1",
            parameters={"post_id": post_id},
        )
        if not result.result_rows:
            return None
        row = dict(zip(result.column_names, result.result_rows[0], strict=True))
        return self._row_to_result(row, "")

    def top_cti(self, limit: int = 20) -> list[SearchResult]:
        result = self._get_client().query(
            f"SELECT {SEARCH_SELECT} FROM posts FINAL WHERE cti_score >= {{minimum:UInt8}} "  # nosec B608
            "ORDER BY cti_score DESC, created_at DESC LIMIT {limit:UInt16}",
            parameters={"minimum": self.settings.CTI_HIGH_THRESHOLD, "limit": limit},
        )
        return [
            self._row_to_result(dict(zip(result.column_names, row, strict=True)), "")
            for row in result.result_rows
        ]

    def stats(self) -> dict[str, Any]:
        client = self._get_client()
        result = client.query(
            "SELECT count() AS total, countIf(cti_score >= {high:UInt8}) AS high, "
            "countIf(cti_score >= {critical:UInt8}) AS critical, max(ingested_at) AS latest "
            "FROM posts FINAL",
            parameters={
                "high": self.settings.CTI_HIGH_THRESHOLD,
                "critical": self.settings.CTI_CRITICAL_THRESHOLD,
            },
        )
        if not result.result_rows:
            overview: dict[str, Any] = {
                "total": 0,
                "high": 0,
                "critical": 0,
                "latest": None,
            }
        else:
            overview = dict(zip(result.column_names, result.result_rows[0], strict=True))

        timeline = client.query(
            "SELECT toString(toDate(created_at)) AS day, count() AS posts FROM posts FINAL "
            "WHERE created_at >= now() - INTERVAL 30 DAY GROUP BY day ORDER BY day"
        )
        categories = client.query(
            "SELECT category, count() AS posts FROM "
            "(SELECT arrayJoin(cti_categories) AS category FROM posts FINAL "
            "WHERE created_at >= now() - INTERVAL 30 DAY) "
            "GROUP BY category ORDER BY posts DESC LIMIT 8"
        )
        iocs = client.query(
            "SELECT "
            "sum(length(ioc_ipv4) + length(ioc_ipv6) + length(ioc_domains) + "
            "length(ioc_urls)) AS network, "
            "sum(length(ioc_md5) + length(ioc_sha1) + length(ioc_sha256) + "
            "length(ioc_sha512)) AS hashes, "
            "sum(length(ioc_cves) + length(ioc_attack_techniques)) AS cve_attack "
            "FROM posts FINAL"
        )
        ioc_summary = {"network": 0, "hashes": 0, "cve_attack": 0}
        if iocs.result_rows:
            ioc_summary = {
                key: int(value)
                for key, value in zip(iocs.column_names, iocs.result_rows[0], strict=True)
            }
        overview["timeline"] = [
            dict(zip(timeline.column_names, row, strict=True)) for row in timeline.result_rows
        ]
        overview["categories"] = [
            dict(zip(categories.column_names, row, strict=True)) for row in categories.result_rows
        ]
        overview["ioc_summary"] = ioc_summary
        return overview

    def list_x_post_ids(self) -> list[str]:
        result = self._get_client().query(
            "SELECT post_id FROM posts FINAL WHERE source_type = 'x_home' GROUP BY post_id"
        )
        return [str(row[0]) for row in result.result_rows]

    def delete_posts(self, post_ids: list[str]) -> None:
        if not post_ids:
            return
        self._get_client().command(
            "DELETE FROM posts WHERE has({post_ids:Array(String)}, post_id)",
            parameters={"post_ids": post_ids},
        )

    def _decode_cursor(self, cursor: str) -> dict[str, Any]:
        try:
            payload = self._cursor.loads(cursor)
        except BadSignature as exc:
            raise InvalidCursorError("cursor signature is invalid") from exc
        if not isinstance(payload, dict) or not {"date", "id", "score"} <= payload.keys():
            raise InvalidCursorError("cursor payload is invalid")
        return payload

    @staticmethod
    def _row_to_result(row: dict[str, Any], query: str) -> SearchResult:
        indicators = IndicatorSet(
            ipv4=row["ioc_ipv4"],
            ipv6=row["ioc_ipv6"],
            domains=row["ioc_domains"],
            urls=row["ioc_urls"],
            emails=row["ioc_emails"],
            md5=row["ioc_md5"],
            sha1=row["ioc_sha1"],
            sha256=row["ioc_sha256"],
            sha512=row["ioc_sha512"],
            cves=row["ioc_cves"],
            attack_techniques=row["ioc_attack_techniques"],
            filenames=row["ioc_filenames"],
            hashtags=row["ioc_hashtags"],
            threat_actors=row["ioc_threat_actors"],
        )
        return SearchResult(
            post_id=str(row["post_id"]),
            text=row["text"],
            username=row["username"],
            display_name=row["display_name"],
            lang=row["lang"],
            created_at=row["created_at"].replace(tzinfo=UTC)
            if row["created_at"].tzinfo is None
            else row["created_at"],
            cti_score=int(row["cti_score"]),
            cti_level=CtiLevel(row["cti_level"]),
            cti_categories=row["cti_categories"],
            cti_reasons=row["cti_reasons"],
            indicators=indicators,
            scoring_mode=row["cti_scoring_mode"],
            scorer_version=row["scorer_version"],
            model_revision=row["model_revision"],
            highlights=highlight_offsets(row["text"], query),
            metrics={
                "replies": int(row["reply_count"]),
                "reposts": int(row["repost_count"]),
                "quotes": int(row["quote_count"]),
                "likes": int(row["like_count"]),
                "bookmarks": int(row["bookmark_count"]),
                "impressions": int(row["impression_count"]),
            },
            source_url=(
                f"https://x.com/i/web/status/{row['post_id']}"
                if row["source_type"] == "x_home"
                else None
            ),
        )


def highlight_offsets(text: str, query: str) -> list[Highlight]:
    if not query:
        return []
    lowered, source_offsets = _fold_with_offsets(text)
    offsets: list[Highlight] = []
    for term in query_terms(query):
        start = 0
        while len(offsets) < 20:
            index = lowered.find(term, start)
            if index < 0:
                break
            source_start = source_offsets[index]
            source_end = source_offsets[index + len(term) - 1] + 1
            offsets.append(Highlight(start=source_start, end=source_end))
            start = index + len(term)
    return sorted(offsets, key=lambda item: item.start)


def _fold_with_offsets(text: str) -> tuple[str, list[int]]:
    folded: list[str] = []
    offsets: list[int] = []
    for source_index, character in enumerate(text):
        normalized = unicodedata.normalize("NFKC", character).casefold()
        folded.append(normalized)
        offsets.extend([source_index] * len(normalized))
    return "".join(folded), offsets
