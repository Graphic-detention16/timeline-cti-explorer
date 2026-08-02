import { FormEvent, ReactNode, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ApiError, apiRequest } from "./api";
import type {
  CollectorStatus,
  Indicators,
  OverviewStats,
  RecentPost,
  SearchResult,
  SessionData,
} from "./types";

type Tab = "search" | "intelligence" | "api";
type SearchMode = "all" | "any" | "phrase";
type SearchSort = "relevance" | "newest" | "cti";

function App() {
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => apiRequest<SessionData>("/api/v1/auth/session"),
    retry: false,
  });

  if (session.isLoading) return <LoadingScreen />;
  if (session.isError || !session.data) return <Login />;
  return <Console session={session.data.data} />;
}

function Login() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      apiRequest<SessionData>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ password }),
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["session"] }),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (password) mutation.mutate();
  };

  return (
    <main className="login-shell">
      <div className="noise" />
      <section className="login-visual" aria-label={t("brand")}>
        <div className="brand-lockup">
          <Logo />
          <span>{t("privateLabel")}</span>
        </div>
        <div className="radar" aria-hidden="true">
          <span className="radar-ring ring-one" />
          <span className="radar-ring ring-two" />
          <span className="radar-ring ring-three" />
          <span className="radar-sweep" />
          <i className="signal signal-one" />
          <i className="signal signal-two" />
          <i className="signal signal-three" />
        </div>
        <div>
          <p className="eyebrow">CTI / SEARCH / EXPLAIN</p>
          <h1>{t("brand")}</h1>
          <p className="hero-copy">{t("subtitle")}</p>
        </div>
      </section>

      <section className="login-panel">
        <LanguageSwitch language={i18n.language} onChange={(value) => changeLanguage(i18n, value)} />
        <form className="login-form" onSubmit={submit}>
          <span className="status-dot"><i /> TLS protected</span>
          <h2>{t("loginTitle")}</h2>
          <p>{t("loginHint")}</p>
          <label>
            <span>{t("password")}</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoFocus
            />
          </label>
          {mutation.isError && <ErrorNotice error={mutation.error} />}
          <button className="primary-button" disabled={mutation.isPending || !password}>
            {mutation.isPending ? t("signingIn") : t("signIn")}
            <span aria-hidden="true">→</span>
          </button>
          <small>{t("safetyNote")}</small>
        </form>
      </section>
    </main>
  );
}

function Console({ session }: { session: SessionData }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("search");
  const logout = useMutation({
    mutationFn: () =>
      apiRequest("/api/v1/auth/logout", { method: "POST" }, session.csrf_token),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["session"] }),
  });

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <Logo />
          <div><strong>{t("brand")}</strong><span>{t("privateLabel")}</span></div>
        </div>
        <nav aria-label="Main navigation">
          {(["search", "intelligence", "api"] as Tab[]).map((item) => (
            <button key={item} aria-current={tab === item ? "page" : undefined} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>
              {t(item === "api" ? "apiDemo" : item)}
            </button>
          ))}
        </nav>
        <div className="top-actions">
          <LanguageSwitch language={i18n.language} onChange={(value) => changeLanguage(i18n, value)} />
          <button className="ghost-button" onClick={() => logout.mutate()}>{t("signOut")}</button>
        </div>
      </header>

      <main className="workspace">
        {tab === "search" && <SearchWorkspace />}
        {tab === "intelligence" && <IntelligenceWorkspace />}
        {tab === "api" && <ApiWorkspace />}
      </main>
      <footer><span>Timeline CTI Explorer v1.0</span><span>Developed by Rojin Delel Dinçer</span></footer>
    </div>
  );
}

function SearchWorkspace() {
  const { t } = useTranslation();
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("all");
  const [sort, setSort] = useState<SearchSort>("relevance");
  const [language, setLanguage] = useState("");
  const [minimumScore, setMinimumScore] = useState(0);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [level, setLevel] = useState("");
  const [category, setCategory] = useState("");
  const [iocType, setIocType] = useState("");
  const [authorDraft, setAuthorDraft] = useState("");
  const [author, setAuthor] = useState("");
  const [cursor, setCursor] = useState("");
  const [page, setPage] = useState(1);

  const search = useQuery({
    queryKey: [
      "search", query, mode, sort, language, minimumScore, fromDate, toDate,
      level, category, iocType, author, cursor,
    ],
    queryFn: () => {
      const params = new URLSearchParams({ q: query, mode, sort, limit: "50" });
      if (language) params.set("lang", language);
      if (minimumScore) params.set("cti_min", String(minimumScore));
      if (fromDate) params.set("from", `${fromDate}T00:00:00Z`);
      if (toDate) params.set("to", `${toDate}T23:59:59Z`);
      if (level) params.set("cti_level", level);
      if (category) params.set("cti_category", category);
      if (iocType) params.set("ioc_type", iocType);
      if (author) params.set("author", author.trim().replace(/^@/, ""));
      if (cursor) params.set("cursor", cursor);
      return apiRequest<SearchResult[]>(`/api/v1/search?${params}`);
    },
    enabled: query.length >= 3,
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (draft.trim().length >= 3) {
      setCursor("");
      setPage(1);
      setAuthor(authorDraft);
      setQuery(draft.trim());
    }
  };

  const resetCursor = () => {
    setCursor("");
    setPage(1);
  };

  return (
    <section>
      <div className="page-heading">
        <div><p className="eyebrow">FULL-TEXT / IOC / CTI</p><h1>{t("search")}</h1></div>
        <span className="system-badge"><i /> ClickHouse text index</span>
      </div>

      <form className="search-console" onSubmit={submit}>
        <div className="search-line">
          <SearchIcon />
          <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={t("searchPlaceholder")} />
          <button className="primary-button" disabled={draft.trim().length < 3}>{t("runSearch")}</button>
        </div>
        <div className="filters">
          <Segmented<SearchMode>
            value={mode}
            onChange={(value) => { resetCursor(); setMode(value); }}
            options={[
              ["all", t("allTerms")], ["any", t("anyTerm")], ["phrase", t("exactPhrase")],
            ]}
          />
          <label><span>{t("language")}</span><select value={language} onChange={(e) => { resetCursor(); setLanguage(e.target.value); }}>
            <option value="">{t("anyLanguage")}</option><option value="en">English</option><option value="tr">Türkçe</option>
          </select></label>
          <label className="score-filter"><span>{t("minimumScore")} <b>{minimumScore}</b></span>
            <input type="range" min="0" max="100" step="10" value={minimumScore} onChange={(e) => { resetCursor(); setMinimumScore(Number(e.target.value)); }} />
          </label>
          <label><span>{t("level")}</span><select value={level} onChange={(e) => { resetCursor(); setLevel(e.target.value); }}>
            <option value="">{t("anyLevel")}</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option>
          </select></label>
          <label><span>{t("category")}</span><select value={category} onChange={(e) => { resetCursor(); setCategory(e.target.value); }}>
            <option value="">{t("anyCategory")}</option><option value="malware">malware</option><option value="phishing">phishing</option><option value="ransomware">ransomware</option><option value="vulnerability">vulnerability</option><option value="apt_campaign">APT / campaign</option><option value="ioc_sharing">IOC sharing</option>
          </select></label>
          <label><span>{t("iocType")}</span><select value={iocType} onChange={(e) => { resetCursor(); setIocType(e.target.value); }}>
            <option value="">{t("anyIoc")}</option><option value="ip">IP</option><option value="domain">domain</option><option value="url">URL</option><option value="hash">hash</option><option value="cve">CVE</option><option value="attack">ATT&amp;CK</option>
          </select></label>
          <label><span>{t("author")}</span><input className="filter-input" value={authorDraft} onChange={(e) => setAuthorDraft(e.target.value)} placeholder="@handle" /></label>
          <label><span>{t("fromDate")}</span><input className="filter-input" type="date" value={fromDate} onChange={(e) => { resetCursor(); setFromDate(e.target.value); }} /></label>
          <label><span>{t("toDate")}</span><input className="filter-input" type="date" value={toDate} min={fromDate} onChange={(e) => { resetCursor(); setToDate(e.target.value); }} /></label>
          <label><span>{t("sort")}</span><select value={sort} onChange={(e) => { resetCursor(); setSort(e.target.value as SearchSort); }}>
            <option value="relevance">{t("relevance")}</option><option value="newest">{t("newest")}</option><option value="cti">{t("ctiScore")}</option>
          </select></label>
        </div>
      </form>

      {!query && <EmptyState icon={<SearchIcon />} title={t("initialSearch")} />}
      {search.isFetching && <ResultSkeleton />}
      {search.isError && <ErrorState error={search.error} retry={() => void search.refetch()} />}
      {search.data && !search.isFetching && (
        <div className="results-area">
          <div className="result-meta"><span><b>{search.data.data.length}</b> {t("results")} · {t("page")} {page}</span><span>{t("queryTime")}: <b>{String(search.data.meta.took_ms ?? "—")} ms</b></span></div>
          {search.data.data.length === 0 ? <EmptyState title={t("noResults")} /> : search.data.data.map((item) => <ResultCard key={item.post_id} item={item} />)}
          {typeof search.data.meta.next_cursor === "string" && <div className="pagination"><button className="ghost-button" onClick={() => { setCursor(search.data.meta.next_cursor as string); setPage((value) => value + 1); }}>{t("nextPage")} →</button></div>}
        </div>
      )}
    </section>
  );
}

function IntelligenceWorkspace() {
  const { t } = useTranslation();
  const stats = useQuery({ queryKey: ["stats"], queryFn: () => apiRequest<OverviewStats>("/api/v1/stats/overview") });
  const top = useQuery({ queryKey: ["top-cti"], queryFn: () => apiRequest<SearchResult[]>("/api/v1/cti/top?limit=12") });
  const recent = useQuery({
    queryKey: ["recent-posts"],
    queryFn: () => apiRequest<RecentPost[]>("/api/v1/posts/recent?limit=50"),
    refetchInterval: 30_000,
  });
  const collector = useQuery({ queryKey: ["collector"], queryFn: () => apiRequest<CollectorStatus>("/api/v1/collector/status"), refetchInterval: 30_000 });

  return (
    <section>
      <div className="page-heading"><div><p className="eyebrow">SITUATIONAL AWARENESS</p><h1>{t("overview")}</h1></div></div>
      <div className="stat-grid">
        <StatCard label={t("totalPosts")} value={formatNumber(stats.data?.data.total)} tone="neutral" />
        <StatCard label={t("highSignals")} value={formatNumber(stats.data?.data.high)} tone="high" />
        <StatCard label={t("criticalSignals")} value={formatNumber(stats.data?.data.critical)} tone="critical" />
        <StatCard label={t("latestIngest")} value={formatDate(stats.data?.data.latest)} tone="neutral" />
      </div>
      <div className="insight-grid">
        <div className="panel chart-panel">
          <div className="panel-heading"><div><span className="eyebrow">30 DAYS</span><h2>{t("signalTimeline")}</h2></div></div>
          <TimelineChart values={stats.data?.data.timeline ?? []} />
        </div>
        <div className="panel chart-panel">
          <div className="panel-heading"><div><span className="eyebrow">CTI TAXONOMY</span><h2>{t("categoryDistribution")}</h2></div></div>
          <DistributionBars values={stats.data?.data.categories ?? []} />
        </div>
        <div className="panel chart-panel">
          <div className="panel-heading"><div><span className="eyebrow">EXTRACTED</span><h2>{t("iocSummary")}</h2></div></div>
          <IocSummary values={stats.data?.data.ioc_summary} />
        </div>
      </div>
      <div className="panel recent-panel">
        <div className="panel-heading">
          <div><span className="eyebrow">LATEST INGEST</span><h2>{t("recentPosts")}</h2></div>
          <span className="system-badge">{recent.data?.data.length ?? 0} / 50</span>
        </div>
        {recent.isLoading && <div className="mini-empty">{t("loadingRecent")}</div>}
        {recent.isError && <div className="warning-note">{t("recentLoadFailed")}</div>}
        {recent.data && <RecentPostsTable items={recent.data.data} />}
      </div>
      <div className="intelligence-grid">
        <div className="panel wide-panel">
          <div className="panel-heading"><div><span className="eyebrow">PRIORITY QUEUE</span><h2>{t("topSignals")}</h2></div></div>
          {top.isLoading ? <ResultSkeleton /> : top.data?.data.map((item) => <ResultCard key={item.post_id} item={item} compact />)}
        </div>
        <aside className="panel collector-panel">
          <div className="panel-heading"><div><span className="eyebrow">INGESTION</span><h2>{t("collector")}</h2></div><Pulse ok={collectorHealthy(collector.data?.data)} /></div>
          {collector.data && <>
            <HealthRow label={t("collector")} value={collector.data.data.collector_backend === "selenium" ? t("backendSelenium") : t("backendApi")} ok />
            {collector.data.data.collector_backend === "selenium" ? (
              <HealthRow label={t("sessionConnected")} value={collector.data.data.session_connected ? t("connected") : t("disconnected")} ok={collector.data.data.session_connected} />
            ) : (
              <HealthRow label="OAuth" value={collector.data.data.oauth_connected ? t("connected") : t("disconnected")} ok={collector.data.data.oauth_connected} />
            )}
            {collector.data.data.collector_backend === "api" && (
              <HealthRow label={t("compliance")} value={collector.data.data.compliance_stale ? t("stale") : t("current")} ok={!collector.data.data.compliance_stale} />
            )}
            <HealthRow label={t("queued")} value={String(collector.data.data.spool_depth)} ok={collector.data.data.spool_depth < 1000} />
            <HealthRow label={t("dailyReads")} value={`${formatNumber(collector.data.data.daily_post_reads)} / ${formatNumber(collector.data.data.daily_read_budget)}`} ok={collector.data.data.daily_post_reads < collector.data.data.daily_read_budget} />
            {collector.data.data.collector_backend === "api" && (
              <HealthRow label={t("rateRemaining")} value={collector.data.data.rate_limit_remaining ?? "—"} ok={collector.data.data.rate_limit_remaining !== "0"} />
            )}
            <HealthRow label={t("scoringMode")} value={collector.data.data.scoring_mode} ok={collector.data.data.scoring_mode === "hybrid"} />
            <HealthRow label={t("lastSuccess")} value={formatDate(collector.data.data.last_success)} ok={Boolean(collector.data.data.last_success)} />
            {collector.data.data.last_error && <div className="warning-note">{t("collectorError")}: {collector.data.data.last_error}</div>}
            {collector.data.data.scoring_mode === "rules_only" && <div className="warning-note">{t("modelDegraded")}</div>}
            {!collector.data.data.live_collection_enabled && <div className="warning-note">{t("liveDisabled")}</div>}
            {collector.data.data.collector_backend === "selenium" && !collector.data.data.session_connected && (
              <div className="warning-note">{t("sessionMissing")}</div>
            )}
            {collector.data.data.collector_backend === "api" && !collector.data.data.oauth_connected && collector.data.data.live_collection_enabled && (
              <a className="primary-button centered" href="/api/v1/auth/x/start">{t("connectX")}</a>
            )}
          </>}
        </aside>
      </div>
    </section>
  );
}

function ApiWorkspace() {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const example = `curl --request GET \\
  --url 'https://localhost:8443/api/v1/search?q=CVE-2026-4242&mode=all&cti_min=70' \\
  --header 'Authorization: Bearer <YOUR_PRIVATE_API_KEY>'`;
  const response = `{
  "data": [{
    "post_id": "90000000000000000001",
    "cti_score": 92,
    "cti_level": "critical",
    "cti_categories": ["vulnerability", "ioc_sharing"],
    "indicators": { "cves": ["CVE-2026-4242"] },
    "scoring_mode": "hybrid"
  }],
  "meta": { "took_ms": 34.8, "next_cursor": null },
  "error": null
}`;
  const copy = async () => {
    await navigator.clipboard.writeText(example);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  return <section>
    <div className="page-heading"><div><p className="eyebrow">VERSIONED / PRIVATE / READ-ONLY</p><h1>{t("apiDemo")}</h1><p>{t("apiIntro")}</p></div><a className="ghost-button link-button" href="/api/docs" target="_blank" rel="noreferrer">{t("openDocs")} ↗</a></div>
    <div className="api-grid">
      <CodePanel title="Request · cURL" code={example} action={<button onClick={copy}>{copied ? t("copied") : t("copy")}</button>} />
      <CodePanel title="Response · application/json" code={response} />
    </div>
    <div className="api-notes">
      <div><b>GET</b><code>/api/v1/search</code><span>Full-text search with cursor pagination</span></div>
      <div><b>GET</b><code>/api/v1/cti/top</code><span>Highest-priority explainable CTI signals</span></div>
      <div><b>GET</b><code>/api/v1/stats/overview</code><span>Private index and risk totals</span></div>
    </div>
  </section>;
}

function ResultCard({ item, compact = false }: { item: SearchResult; compact?: boolean }) {
  const { t } = useTranslation();
  const indicatorValues = flattenIndicators(item.indicators).slice(0, compact ? 4 : 10);
  return <article className={`result-card ${compact ? "compact" : ""}`}>
    <div className={`score-rail ${item.cti_level}`}><strong>{item.cti_score}</strong><span>{item.cti_level}</span></div>
    <div className="result-body">
      <div className="result-header">
        <div><strong>{item.display_name || item.username}</strong><span>@{item.username} · {formatDate(item.created_at)}</span></div>
        <span className={`mode-badge ${item.scoring_mode === "hybrid" ? "hybrid" : "rules"}`}>{item.scoring_mode === "hybrid" ? t("hybrid") : t("ruleOnly")}</span>
      </div>
      <p className="post-text">{renderHighlightedText(item.text, item.highlights)}</p>
      {item.cti_categories.length > 0 && <div className="category-row">{item.cti_categories.map((category) => <span key={category}>{category.replaceAll("_", " ")}</span>)}</div>}
      {indicatorValues.length > 0 && <div className="indicator-row"><b>{t("indicators")}</b>{indicatorValues.map((indicator) => <code key={indicator}>{indicator}</code>)}</div>}
      {!compact && <details><summary>{t("scoreWhy")}</summary><ul>{item.cti_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></details>}
      <div className="result-footer"><div>{Object.entries(item.metrics).slice(0, 4).map(([name, value]) => <span key={name}>{name} <b>{formatNumber(value)}</b></span>)}</div>{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">{t("viewOriginal")} ↗</a>}</div>
    </div>
  </article>;
}

function renderHighlightedText(text: string, highlights: Array<{ start: number; end: number }>): ReactNode {
  if (!highlights.length) return text;
  const merged = highlights.reduce<Array<{ start: number; end: number }>>((items, current) => {
    const previous = items.at(-1);
    if (previous && current.start <= previous.end) previous.end = Math.max(previous.end, current.end);
    else items.push({ ...current });
    return items;
  }, []);
  const nodes: ReactNode[] = [];
  let cursor = 0;
  merged.forEach((item, index) => {
    nodes.push(text.slice(cursor, item.start));
    nodes.push(<mark key={`${item.start}-${index}`}>{text.slice(item.start, item.end)}</mark>);
    cursor = item.end;
  });
  nodes.push(text.slice(cursor));
  return nodes;
}

function flattenIndicators(indicators: Indicators): string[] {
  return Object.values(indicators).flat();
}

function Segmented<T extends string>({ value, onChange, options }: { value: T; onChange: (value: T) => void; options: Array<[T, string]> }) {
  return <div className="segmented">{options.map(([key, label]) => <button type="button" key={key} aria-pressed={value === key} className={value === key ? "active" : ""} onClick={() => onChange(key)}>{label}</button>)}</div>;
}

function StatCard({ label, value, tone }: { label: string; value: string; tone: string }) {
  return <div className={`stat-card ${tone}`}><span>{label}</span><strong>{value}</strong><i /></div>;
}

function TimelineChart({ values }: { values: Array<{ day: string; posts: number }> }) {
  const { t } = useTranslation();
  const maximum = Math.max(1, ...values.map((item) => item.posts));
  if (!values.length) return <div className="mini-empty">{t("noChartData")}</div>;
  return <div className="timeline-chart" aria-label="Thirty day signal timeline">{values.map((item) => <span key={item.day} title={`${item.day}: ${item.posts}`} style={{ height: `${Math.max(4, item.posts / maximum * 100)}%` }} />)}</div>;
}

function DistributionBars({ values }: { values: Array<{ category: string; posts: number }> }) {
  const { t } = useTranslation();
  const maximum = Math.max(1, ...values.map((item) => item.posts));
  if (!values.length) return <div className="mini-empty">{t("noChartData")}</div>;
  return <div className="distribution-bars">{values.map((item) => <div key={item.category}><span>{item.category.replaceAll("_", " ")}</span><i><b style={{ width: `${item.posts / maximum * 100}%` }} /></i><strong>{formatNumber(item.posts)}</strong></div>)}</div>;
}

function IocSummary({ values }: { values?: { network: number; hashes: number; cve_attack: number } }) {
  return <div className="ioc-summary"><div><span>Network</span><strong>{formatNumber(values?.network)}</strong></div><div><span>Hashes</span><strong>{formatNumber(values?.hashes)}</strong></div><div><span>CVE / ATT&amp;CK</span><strong>{formatNumber(values?.cve_attack)}</strong></div></div>;
}

function RecentPostsTable({ items }: { items: RecentPost[] }) {
  const { t } = useTranslation();
  if (!items.length) return <div className="mini-empty">{t("noRecentPosts")}</div>;
  return <div className="recent-table-wrap">
    <table className="recent-table">
      <thead><tr>
        <th>{t("ingestedAt")}</th>
        <th>{t("author")}</th>
        <th>{t("post")}</th>
        <th>{t("language")}</th>
        <th>{t("ctiScore")}</th>
        <th>{t("level")}</th>
        <th>{t("category")}</th>
        <th><span className="sr-only">{t("viewOriginal")}</span></th>
      </tr></thead>
      <tbody>{items.map((item) => <tr key={item.post_id}>
        <td className="mono-cell">{formatDate(item.ingested_at)}</td>
        <td><strong>{item.display_name || item.username || "—"}</strong><small>{item.username ? `@${item.username}` : ""}</small></td>
        <td className="post-cell" title={item.text}>{item.text}</td>
        <td className="mono-cell">{item.lang}</td>
        <td><strong className={`table-score ${item.cti_level}`}>{item.cti_score}</strong></td>
        <td><span className={`level-pill ${item.cti_level}`}>{item.cti_level}</span></td>
        <td className="category-cell">{item.cti_categories.length ? item.cti_categories.join(", ") : "—"}</td>
        <td>{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer" aria-label={t("viewOriginal")}>↗</a>}</td>
      </tr>)}</tbody>
    </table>
  </div>;
}

function HealthRow({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return <div className="health-row"><span>{label}</span><b className={ok ? "ok" : "bad"}>{value}</b></div>;
}

function Pulse({ ok }: { ok: boolean }) { return <span className={`pulse ${ok ? "ok" : "bad"}`}><i /></span>; }

function collectorHealthy(status: CollectorStatus | undefined): boolean {
  if (!status) return false;
  if (status.collector_backend === "selenium") return status.session_connected;
  return status.oauth_connected;
}

function CodePanel({ title, code, action }: { title: string; code: string; action?: ReactNode }) {
  return <div className="code-panel"><div><span>{title}</span>{action}</div><pre><code>{code}</code></pre></div>;
}

function LanguageSwitch({ language, onChange }: { language: string; onChange: (value: string) => void }) {
  return <div className="language-switch"><button type="button" aria-pressed={language.startsWith("en")} className={language.startsWith("en") ? "active" : ""} onClick={() => onChange("en")}>EN</button><button type="button" aria-pressed={language.startsWith("tr")} className={language.startsWith("tr") ? "active" : ""} onClick={() => onChange("tr")}>TR</button></div>;
}

function EmptyState({ title, icon }: { title: string; icon?: ReactNode }) { return <div className="empty-state">{icon}<p>{title}</p></div>; }
function ResultSkeleton() { return <div className="skeleton-list">{[1, 2, 3].map((item) => <div key={item} className="skeleton"><i /><span /><span /></div>)}</div>; }
function LoadingScreen() { return <div className="loading-screen"><Logo /><span className="loader" /></div>; }
function ErrorNotice({ error }: { error: Error }) { const { t } = useTranslation(); return <div className="error-notice">{error instanceof ApiError ? error.problem.detail : t("requestFailed")}</div>; }
function ErrorState({ error, retry }: { error: Error; retry: () => void }) { const { t } = useTranslation(); return <div className="empty-state error"><p>{error instanceof ApiError ? error.problem.detail : t("requestFailed")}</p><button className="ghost-button" onClick={retry}>{t("retry")}</button></div>; }

function Logo() { return <svg className="logo" viewBox="0 0 48 48" aria-hidden="true"><path d="M24 4 42 14v20L24 44 6 34V14L24 4Z" /><path d="m15 27 6-6 5 5 8-9" /><circle cx="34" cy="17" r="2.5" /></svg>; }
function SearchIcon() { return <svg className="search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m16 16 5 5" /></svg>; }

function formatNumber(value: number | undefined): string { return value === undefined ? "—" : new Intl.NumberFormat().format(value); }
function formatDate(value: string | null | undefined): string { return value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—"; }
function changeLanguage(instance: { changeLanguage: (value: string) => Promise<unknown> }, value: string) { window.localStorage.setItem("timeline-cti-language", value); void instance.changeLanguage(value); }

export default App;
