CREATE TABLE IF NOT EXISTS posts
(
    source_type LowCardinality(String),
    post_id String,
    author_id String,
    conversation_id String,
    text String CODEC(ZSTD(3)),
    normalized_text String CODEC(ZSTD(3)),
    lang LowCardinality(String),
    created_at DateTime64(3, 'UTC'),
    ingested_at DateTime64(3, 'UTC'),
    username LowCardinality(String),
    display_name String,
    author_verified Bool,
    author_protected Bool,
    reply_count UInt64,
    repost_count UInt64,
    quote_count UInt64,
    like_count UInt64,
    bookmark_count UInt64,
    impression_count UInt64,
    urls Array(String),
    hashtags Array(String),
    mentions Array(String),
    referenced_post_ids Array(String),
    cti_score UInt8,
    cti_level Enum8('low' = 1, 'medium' = 2, 'high' = 3, 'critical' = 4),
    cti_rule_score UInt8,
    cti_semantic_score Float32,
    cti_scoring_mode LowCardinality(String),
    cti_categories Array(LowCardinality(String)),
    cti_reasons Array(String),
    ioc_ipv4 Array(String),
    ioc_ipv6 Array(String),
    ioc_domains Array(String),
    ioc_urls Array(String),
    ioc_emails Array(String),
    ioc_md5 Array(String),
    ioc_sha1 Array(String),
    ioc_sha256 Array(String),
    ioc_sha512 Array(String),
    ioc_cves Array(String),
    ioc_attack_techniques Array(String),
    ioc_filenames Array(String),
    ioc_hashtags Array(String),
    ioc_threat_actors Array(String),
    scorer_version LowCardinality(String),
    model_revision String,
    content_version UInt16,
    source_updated_at DateTime64(3, 'UTC'),
    compliance_checked_at DateTime64(3, 'UTC'),
    INDEX idx_normalized_text normalized_text TYPE text(tokenizer = 'splitByNonAlpha') GRANULARITY 64,
    INDEX idx_author username TYPE bloom_filter GRANULARITY 4,
    INDEX idx_cti_categories cti_categories TYPE bloom_filter GRANULARITY 4
)
ENGINE = ReplacingMergeTree(content_version)
PARTITION BY toYYYYMM(created_at)
ORDER BY (toDate(created_at), post_id)
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS daily_cti_stats
(
    day Date,
    cti_level LowCardinality(String),
    posts UInt64
)
ENGINE = SummingMergeTree
ORDER BY (day, cti_level);

CREATE MATERIALIZED VIEW IF NOT EXISTS daily_cti_stats_mv TO daily_cti_stats AS
SELECT toDate(created_at) AS day, toString(cti_level) AS cti_level, count() AS posts
FROM posts
GROUP BY day, cti_level;

