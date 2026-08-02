# ruff: noqa: E501
from __future__ import annotations

import argparse
import time

import clickhouse_connect

from .config import get_settings

SYNTHETIC_INSERT = r"""
INSERT INTO posts
(
    source_type, post_id, author_id, conversation_id, text, normalized_text, lang,
    created_at, ingested_at, username, display_name, author_verified, author_protected,
    reply_count, repost_count, quote_count, like_count, bookmark_count, impression_count,
    urls, hashtags, mentions, referenced_post_ids, cti_score, cti_level, cti_rule_score,
    cti_semantic_score, cti_scoring_mode, cti_categories, cti_reasons,
    ioc_ipv4, ioc_ipv6, ioc_domains, ioc_urls, ioc_emails,
    ioc_md5, ioc_sha1, ioc_sha256, ioc_sha512, ioc_cves, ioc_attack_techniques,
    ioc_filenames, ioc_hashtags, ioc_threat_actors, scorer_version, model_revision,
    content_version, source_updated_at, compliance_checked_at
)
SELECT
    'synthetic',
    concat('9', leftPad(toString(number), 19, '0')),
    toString(number % 100000),
    toString(number),
    arrayElement([
        'Critical CVE-2026-4242 exploitation observed with 203.0.113.42 and evil.example payload.',
        'Yeni fidye yazılımı kampanyası hxxps://malware[.]example üzerinden zararlı dosya dağıtıyor.',
        'APT42 campaign uses T1059.001 and phishing infrastructure for credential theft.',
        'Security teams published indicators and mitigation guidance for a remote code execution flaw.',
        'Ordinary engineering update about a stable software release and documentation.',
        'Bugün hava güzel ve açık kaynak topluluğu yeni bir etkinlik düzenliyor.'
    ], toUInt32(number % 6) + 1) AS body,
    lowerUTF8(body),
    if(number % 2 = 0, 'en', 'tr'),
    now64(3) - toIntervalSecond(number % 31536000),
    now64(3),
    concat('synthetic_', toString(number % 100000)),
    'Synthetic Fixture',
    false, false,
    number % 50, number % 20, number % 7, number % 500, number % 10, number % 10000,
    [], [], [], [],
    toUInt8(number % 101),
    multiIf(number % 101 >= 85, 'critical', number % 101 >= 70, 'high', number % 101 >= 40, 'medium', 'low'),
    toUInt8(number % 101),
    toFloat32(number % 101),
    'synthetic',
    if(number % 3 = 0, ['vulnerability', 'ioc_sharing'], []),
    ['synthetic_benchmark_fixture'],
    if(number % 6 = 0, ['203.0.113.42'], []), [],
    if(number % 6 IN (0, 1), ['malware.example'], []),
    if(number % 6 = 1, ['https://malware.example'], []),
    [], [], [], [], [],
    if(number % 6 = 0, ['CVE-2026-4242'], []),
    if(number % 6 = 2, ['T1059.001'], []),
    [], [], if(number % 6 = 2, ['APT42'], []),
    'synthetic-1.0.0', '', 1, now64(3), now64(3)
FROM numbers({rows:UInt64})
SETTINGS max_threads = 8
"""


def generate(rows: int) -> None:
    settings = get_settings()
    client = clickhouse_connect.get_client(
        host=settings.CLICKHOUSE_HOST,
        port=settings.CLICKHOUSE_PORT,
        username=settings.CLICKHOUSE_INGEST_USER,
        password=settings.CLICKHOUSE_INGEST_PASSWORD.get_secret_value(),
        database=settings.CLICKHOUSE_DATABASE,
        send_receive_timeout=86400,
    )
    started = time.perf_counter()
    client.command(SYNTHETIC_INSERT, parameters={"rows": rows})
    duration = time.perf_counter() - started
    rate = rows / max(duration, 0.001)
    print(f"Inserted {rows} synthetic posts in {duration:.2f}s ({rate:.0f} rows/s)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic synthetic benchmark posts")
    parser.add_argument("--rows", type=int, default=1_000_000)
    args = parser.parse_args()
    if not 1 <= args.rows <= 1_000_000_000:
        raise SystemExit("--rows must be between 1 and 1,000,000,000")
    generate(args.rows)


if __name__ == "__main__":
    main()
