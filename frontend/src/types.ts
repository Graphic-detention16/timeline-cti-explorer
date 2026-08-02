export type CtiLevel = "low" | "medium" | "high" | "critical";

export interface ApiEnvelope<T> {
  data: T;
  meta: Record<string, unknown> & { request_id: string; next_cursor?: string; took_ms?: number };
  error: null;
}

export interface ProblemDetails {
  title: string;
  detail: string;
  code: string;
  request_id: string;
}

export interface Indicators {
  ipv4: string[];
  ipv6: string[];
  domains: string[];
  urls: string[];
  emails: string[];
  md5: string[];
  sha1: string[];
  sha256: string[];
  sha512: string[];
  cves: string[];
  attack_techniques: string[];
  filenames: string[];
  hashtags: string[];
  threat_actors: string[];
}

export interface SearchResult {
  post_id: string;
  text: string;
  username: string;
  display_name: string;
  lang: string;
  created_at: string;
  cti_score: number;
  cti_level: CtiLevel;
  cti_categories: string[];
  cti_reasons: string[];
  indicators: Indicators;
  scoring_mode: string;
  scorer_version: string;
  model_revision: string;
  highlights: Array<{ start: number; end: number }>;
  metrics: Record<string, number>;
  source_url: string | null;
}

export interface RecentPost {
  post_id: string;
  text: string;
  username: string;
  display_name: string;
  lang: string;
  created_at: string;
  ingested_at: string;
  cti_score: number;
  cti_level: CtiLevel;
  cti_categories: string[];
  source_url: string | null;
}

export interface SessionData {
  authenticated: boolean;
  method: "session" | "api_key";
  csrf_token: string | null;
}

export interface OverviewStats {
  total: number;
  high: number;
  critical: number;
  latest: string | null;
  timeline: Array<{ day: string; posts: number }>;
  categories: Array<{ category: string; posts: number }>;
  ioc_summary: { network: number; hashes: number; cve_attack: number };
}

export interface CollectorStatus {
  oauth_connected: boolean;
  session_connected: boolean;
  collector_backend: "selenium" | "api";
  spool_depth: number;
  spool_bytes: number;
  daily_post_reads: number;
  last_success: string | null;
  last_compliance_success: string | null;
  last_error: string | null;
  compliance_stale: boolean;
  live_collection_enabled: boolean;
  daily_read_budget: number;
  rate_limit_remaining: string | null;
  rate_limit_reset: string | null;
  scoring_mode: "hybrid" | "rules_only" | "unknown";
}
