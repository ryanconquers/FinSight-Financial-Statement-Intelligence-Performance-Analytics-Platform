"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { requestData } from "../lib/api-client.mjs";

type ProjectStatus = {
  project_status: string;
  data_availability: "empty" | "available";
  source_backed_observation_count: number;
  real_financial_data_onboarded: boolean;
};
type Company = {
  company_id: string;
  company_name: string;
  ticker: string | null;
  reporting_currency: string;
  financial_year_count: number;
  first_financial_year: string;
  last_financial_year: string;
};
type Metric = {
  metric_id: string;
  metric_name: string;
  company_id: string;
  financial_year: string;
  period_start: string;
  period_end: string;
  statement_basis: string;
  value: string | null;
  unit: string;
  currency: string | null;
  status: "calculated" | "unavailable" | "invalid_input";
  explanation: string;
  formula: string;
  inputs: Array<{ source_id: string; observation_id: number }>;
  warnings: string[];
};
type Provenance = {
  source_id: string;
  publisher: string;
  source_url: string | null;
  publication_date: string | null;
  retrieved_at: string;
  financial_year: string;
  statement_basis: string;
  statement_type: string;
};
type ReportedObservation = {
  observation_id: number;
  company_id: string;
  financial_year: string;
  period_start: string;
  period_end: string;
  statement_basis: "standalone" | "consolidated";
  statement_type: string;
  line_item_id: string;
  reported_label: string;
  value: string | null;
  unit: string;
  currency: string;
  source_id: string;
  publisher: string;
  source_url: string | null;
  publication_date: string | null;
  retrieved_at: string;
};
type RiskAssessment = {
  rule_id: string;
  title: string;
  status: "flagged" | "not_flagged" | "insufficient_data" | "invalid_input";
  financial_year: string;
  configuration_version: string;
  thresholds: Record<string, string | number>;
  periods: string[];
  comparison: string;
  fact: string;
  interpretation: string;
  reason: string | null;
  observed: Array<{ metric_id: string; financial_year: string; value: string | null; unit: string; currency: string | null; status: string }>;
  evidence: Metric[];
};
type CompanyAnalysis = {
  company_id: string;
  statement_basis: "standalone" | "consolidated";
  configuration_version: string;
  assessments: RiskAssessment[];
};
type FinancialInsight = {
  insight_id: string;
  category: "observed_trend" | "screening_indicator" | "coincident_indicators" | "contrasting_indicators" | "peer_comparison";
  finding: string;
  periods: string[];
  rule: string;
  limitations: string;
  evidence: Metric[];
};
type PeerBenchmark = {
  status: "available" | "insufficient_data";
  financial_year: string | null;
  peers_requested: string[];
  metrics: Array<{
    metric_id: string;
    status: "available" | "insufficient_data";
    target_value?: string;
    peer_median?: string | null;
    exclusions?: Record<string, string>;
    unit?: string;
    currency?: string | null;
    peer_count?: number;
    values: Array<{ company_id: string; value: string | null; unit: string; currency: string | null; period_start: string; period_end: string; is_target: boolean; evidence: Metric | null; sources?: Provenance[] }>;
  }>;
};

type LoadState = "loading" | "ready" | "error";
const API_BASE = (process.env.NEXT_PUBLIC_FINSIGHT_API_URL || "http://localhost:8000").replace(/\/$/, "");
const STATIC_PAGES_MODE = process.env.NEXT_PUBLIC_FINSIGHT_STATIC_PAGES === "true";

const percentageMetrics = new Set([
  "revenue_growth", "revenue_cagr", "gross_margin", "ebitda_margin", "ebit_margin",
  "net_profit_margin", "roa", "roe", "roce",
]);
const metricGroups = [
  { title: "Growth & profitability", ids: ["revenue_growth", "revenue_cagr", "gross_profit", "gross_margin", "ebitda_margin", "ebit_margin", "net_profit_margin", "roa", "roe", "roce"] },
  { title: "Cash flow", ids: ["operating_cash_flow", "free_cash_flow", "ocf_net_income", "ocf_net_income_divergence", "ocf_yoy_change"] },
  { title: "Working capital", ids: ["receivable_days", "inventory_days", "payable_days", "cash_conversion_cycle"] },
  { title: "Leverage & risk", ids: ["total_debt", "net_debt", "debt_to_equity", "interest_coverage", "net_debt_to_ebitda"] },
];

function formatValue(metric: Metric): string {
  if (metric.value === null || !Number.isFinite(Number(metric.value))) return "—";
  const value = Number(metric.value);
  if (percentageMetrics.has(metric.metric_id)) return `${(value * 100).toFixed(1)}%`;
  if (metric.unit === "days") return `${value.toFixed(1)} days`;
  if (metric.unit === "amount") return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${metric.currency ?? ""}`.trim();
  if (metric.metric_id.includes("coverage") || metric.metric_id.includes("to_")) return `${value.toFixed(2)}×`;
  if (metric.unit === "ratio") return `${value.toFixed(2)}×`;
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${metric.unit}`.trim();
}

export default function Home() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState("");
  const [status, setStatus] = useState<ProjectStatus | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState("");
  const companyIdRef = useRef("");
  const [basis, setBasis] = useState<"consolidated" | "standalone">("consolidated");
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [provenance, setProvenance] = useState<Provenance[]>([]);
  const [reportedObservations, setReportedObservations] = useState<ReportedObservation[]>([]);
  const [riskAssessments, setRiskAssessments] = useState<RiskAssessment[]>([]);
  const [insights, setInsights] = useState<FinancialInsight[]>([]);
  const [peerIds, setPeerIds] = useState<string[]>([]);
  const [benchmark, setBenchmark] = useState<PeerBenchmark | null>(null);
  const [detailState, setDetailState] = useState<LoadState>("ready");
  const [detailError, setDetailError] = useState("");
  const [detailAttempt, setDetailAttempt] = useState(0);
  const [financialYear, setFinancialYear] = useState("all");

  const loadOverview = useCallback(async () => {
    setLoadState("loading");
    setLoadError("");
    if (STATIC_PAGES_MODE) {
      setStatus({
        project_status: "under_development",
        data_availability: "empty",
        source_backed_observation_count: 0,
        real_financial_data_onboarded: false,
      });
      setCompanies([]);
      setLoadState("ready");
      return;
    }
    try {
      const [nextStatus, nextCompanies] = await Promise.all([
        requestData<ProjectStatus>(API_BASE, "/api/status"),
        requestData<Company[]>(API_BASE, "/api/companies"),
      ]);
      setStatus(nextStatus);
      setCompanies(nextCompanies);
      if (nextCompanies.length === 0) {
        setMetrics([]);
        setProvenance([]);
        setReportedObservations([]);
        setRiskAssessments([]);
        setInsights([]);
        setBenchmark(null);
      }
      const nextCompanyId = nextCompanies.some((company) => company.company_id === companyIdRef.current) ? companyIdRef.current : nextCompanies[0]?.company_id || "";
      companyIdRef.current = nextCompanyId;
      setCompanyId(nextCompanyId);
      setPeerIds(nextCompanies.filter((company) => company.company_id !== nextCompanyId).slice(0, 20).map((company) => company.company_id));
      setLoadState("ready");
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not connect to the FinSight API.");
      setLoadState("error");
    }
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- Starts the initial API load and drives the existing loading state.
  useEffect(() => { void loadOverview(); }, [loadOverview]);

  useEffect(() => {
    if (!companyId) {
      return;
    }
    let active = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Shows the loading state while this selection's requests are in flight.
    setDetailState("loading");
    setDetailError("");
    const peerQuery = new URLSearchParams({ statement_basis: basis });
    peerIds.filter((id) => id !== companyId).forEach((id) => peerQuery.append("peer_ids", id));
    const benchmarkRequest = peerIds.some((id) => id !== companyId)
      ? requestData<PeerBenchmark>(API_BASE, `/api/companies/${encodeURIComponent(companyId)}/benchmark?${peerQuery.toString()}`)
      : Promise.resolve(null);
    Promise.all([
      requestData<Metric[]>(API_BASE, `/api/companies/${encodeURIComponent(companyId)}/metrics?statement_basis=${basis}`),
      requestData<Provenance[]>(API_BASE, `/api/companies/${encodeURIComponent(companyId)}/provenance?statement_basis=${basis}`),
      requestData<ReportedObservation[]>(API_BASE, `/api/companies/${encodeURIComponent(companyId)}/observations?statement_basis=${basis}`),
      requestData<CompanyAnalysis>(API_BASE, `/api/companies/${encodeURIComponent(companyId)}/analysis?statement_basis=${basis}`),
      requestData<{ company_id: string; statement_basis: string; insights: FinancialInsight[] }>(API_BASE, `/api/companies/${encodeURIComponent(companyId)}/insights?${peerQuery.toString()}`),
      benchmarkRequest,
    ]).then(([nextMetrics, nextProvenance, nextObservations, analysis, nextInsights, nextBenchmark]) => {
      if (!active) return;
      setMetrics(nextMetrics);
      setProvenance(nextProvenance);
      setReportedObservations(nextObservations);
      setRiskAssessments(analysis.assessments);
      setInsights(nextInsights.insights);
      setBenchmark(nextBenchmark);
      setDetailState("ready");
    }).catch((error: unknown) => {
      if (!active) return;
      setDetailError(error instanceof Error ? error.message : "Could not load this company's data.");
      setDetailState("error");
    });
    return () => { active = false; };
  }, [companyId, basis, detailAttempt, peerIds]);

  const years = useMemo(() => [...new Set(metrics.map((metric) => metric.financial_year))].sort().reverse(), [metrics]);
  const visibleMetrics = useMemo(
    () => metrics.filter((metric) => financialYear === "all" || metric.financial_year === financialYear),
    [metrics, financialYear],
  );
  const visibleObservations = useMemo(
    () => reportedObservations.filter((item) => financialYear === "all" || item.financial_year === financialYear),
    [reportedObservations, financialYear],
  );
  const selectedCompany = companies.find((company) => company.company_id === companyId);
  const metricsById = new Map(visibleMetrics.map((metric) => [metric.metric_id, metric]));
  const reportQuery = new URLSearchParams({ statement_basis: basis, format: "json" });
  peerIds.filter((id) => id !== companyId).forEach((id) => reportQuery.append("peer_ids", id));
  const csvReportQuery = new URLSearchParams({ statement_basis: basis, format: "csv" });

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#overview" aria-label="FinSight home">
          <span className="brand-mark">F</span><span>FinSight</span>
        </a>
        <div className="sidebar-caption">WORKSPACE</div>
        <nav className="main-nav" aria-label="Main navigation">
          <a className="nav-link active" href="#overview"><span className="nav-icon">◫</span>Overview</a>
          <a className="nav-link" href="#company"><span className="nav-icon">▤</span>Company analysis</a>
          <a className="nav-link" href="#metrics"><span className="nav-icon">⌁</span>Financial metrics</a>
          <a className="nav-link" href="#observations"><span className="nav-icon">▦</span>Reported inputs</a>
          <a className="nav-link" href="#analysis"><span className="nav-icon">◇</span>Trend flags</a>
          <a className="nav-link" href="#insights"><span className="nav-icon">↗</span>Insights</a>
          <a className="nav-link" href="#benchmark"><span className="nav-icon">▥</span>Peer comparison</a>
          <a className="nav-link" href="#report"><span className="nav-icon">⇩</span>Analyst report</a>
          <a className="nav-link" href="#provenance"><span className="nav-icon">↗</span>Data provenance</a>
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note"><span className="status-dot" />M4 analysis</div>
          <p>Transparent analysis starts with traceable source data.</p>
          <span className="sidebar-version">FinSight · v0.3</span>
        </div>
      </aside>

      <main className="main-content" id="overview">
        <header className="topbar">
          <div className="breadcrumb">Workspace <span>/</span> Overview</div>
          <div className="topbar-status"><span className="status-dot" />Application under development</div>
        </header>

        <section className="page-intro">
          <div>
            <p className="eyebrow">FINANCIAL STATEMENT INTELLIGENCE</p>
            <h1>Company performance,<br className="desktop-break" /> made clearer.</h1>
            <p className="intro-copy">A focused workspace for understanding financial performance, cash generation, and balance-sheet risk.</p>
          </div>
          <div className="intro-stamp"><span className="stamp-icon">✳</span><span>Built for<br />careful analysis</span></div>
        </section>

        <section className="notice-banner" aria-live="polite">
          <div className="notice-symbol">i</div>
          <div><strong>{STATIC_PAGES_MODE ? "Static GitHub Pages site" : "Early access foundation"}</strong><p>{STATIC_PAGES_MODE ? "This static site is not connected to the FinSight API. No financial data or company results are included." : "Real financial statements have not been onboarded. No company results or peer rankings are shown until source-backed data is available."}</p></div>
          <span className="notice-pill">IN DEVELOPMENT</span>
        </section>

        <section className="summary-grid" aria-label="Project data status">
          <article className="summary-card">
            <div className="summary-label">SOURCE-BACKED OBSERVATIONS</div>
            <div className="summary-value">{loadState === "loading" ? <span className="skeleton short" /> : loadState === "error" ? "—" : status?.source_backed_observation_count ?? "—"}</div>
            <div className="summary-foot"><span className="summary-muted">Imported non-synthetic observation records</span></div>
          </article>
          <article className="summary-card">
            <div className="summary-label">COMPANIES AVAILABLE</div>
            <div className="summary-value">{loadState === "loading" ? <span className="skeleton short" /> : loadState === "error" ? "—" : companies.length}</div>
            <div className="summary-foot"><span className="summary-muted">With imported source data</span></div>
          </article>
          <article className="summary-card">
            <div className="summary-label">METRIC COVERAGE</div>
            <div className="summary-value">—</div>
            <div className="summary-foot"><span className="summary-muted">Calculated from available inputs</span></div>
          </article>
          <article className="summary-card summary-card-accent">
            <div className="summary-label">DATA STATUS</div>
            <div className="summary-value status-value">{loadState === "loading" ? "Checking" : loadState === "error" ? "Unavailable" : status?.data_availability === "available" ? "Available" : "Awaiting data"}</div>
            <div className="summary-foot"><span className="status-dot" />{loadState === "error" ? "API status unknown" : status?.real_financial_data_onboarded ? "Source-backed records" : "No real company data"}</div>
          </article>
        </section>

        {loadState === "error" && <div className="error-panel" role="alert"><strong>API connection unavailable</strong><p>{loadError}</p><button className="button-secondary" onClick={() => void loadOverview()}>Retry connection</button></div>}

        <section className="content-section" id="company">
          <div className="section-heading">
            <div><p className="eyebrow">RESEARCH WORKSPACE</p><h2>Company analysis</h2><p className="section-subtitle">Review a company&apos;s financial history and source-backed metrics.</p></div>
            {companies.length > 0 && <div className="control-row">
              <label className="sr-only" htmlFor="company-select">Select company</label>
              <select id="company-select" value={companyId} onChange={(event) => { companyIdRef.current = event.target.value; setCompanyId(event.target.value); setPeerIds(companies.filter((company) => company.company_id !== event.target.value).slice(0, 20).map((company) => company.company_id)); setFinancialYear("all"); }}>
                {companies.map((company) => <option value={company.company_id} key={company.company_id}>{company.company_name}{company.ticker ? ` · ${company.ticker}` : ""}</option>)}
              </select>
              <label className="sr-only" htmlFor="basis-select">Statement basis</label>
              <select id="basis-select" value={basis} onChange={(event) => setBasis(event.target.value as "standalone" | "consolidated")}>
                <option value="consolidated">Consolidated</option><option value="standalone">Standalone</option>
              </select>
            </div>}
          </div>
          {loadState === "loading" && <div className="empty-card loading-card"><span className="spinner" /><div><strong>Connecting to FinSight</strong><p>The API may be waking after inactivity. This first request can take a little longer.</p></div></div>}
          {loadState === "ready" && companies.length === 0 && <div className="empty-card"><div className="empty-icon">⌕</div><div><span className="empty-kicker">NO COMPANIES YET</span><h3>Your research workspace is ready.</h3><p>When source-backed annual statement data is added, company history and analysis will appear here. No sample financial results are displayed.</p></div><div className="empty-meta"><span>01</span><span>Source first<br />analysis</span></div></div>}
          {selectedCompany && <div className="company-context">
            <div className="company-initials">{(selectedCompany.ticker || selectedCompany.company_name).slice(0, 2).toUpperCase()}</div>
            <div><strong>{selectedCompany.company_name}</strong><span>{selectedCompany.ticker || "Listed company"} · {selectedCompany.reporting_currency} reporting currency</span></div>
            <div className="context-period">{selectedCompany.first_financial_year} — {selectedCompany.last_financial_year}</div>
          </div>}
        </section>

        <section className="content-section" id="metrics">
          <div className="section-heading">
            <div><p className="eyebrow">CALCULATED FROM REPORTED INPUTS</p><h2>Financial metrics</h2><p className="section-subtitle">Every result retains its formula, period, unit, and input references.</p></div>
            {selectedCompany && years.length > 0 && <div className="control-row"><label className="sr-only" htmlFor="year-select">Select financial year</label><select id="year-select" value={financialYear} onChange={(event) => setFinancialYear(event.target.value)}><option value="all">All years</option>{years.map((year) => <option value={year} key={year}>{year}</option>)}</select></div>}
          </div>
          {detailState === "loading" && selectedCompany && <div className="empty-inline"><span className="spinner" />Loading metrics and source references…</div>}
          {detailState === "error" && selectedCompany && <div className="error-panel" role="alert"><strong>Company data could not be loaded</strong><p>{detailError}</p><button className="button-secondary" onClick={() => setDetailAttempt((attempt) => attempt + 1)}>Retry company requests</button></div>}
          {loadState === "ready" && companies.length === 0 && <div className="metrics-empty"><span className="metric-empty-icon">↗</span><div><strong>Metrics will appear when source data is available.</strong><p>Calculation conventions are documented; this view does not contain placeholder results.</p></div></div>}
          {selectedCompany && detailState === "ready" && metrics.length === 0 && <div className="metrics-empty"><span className="metric-empty-icon">↗</span><div><strong>No {basis} observations for this company.</strong><p>Choose another statement basis or onboard source-backed observations with provenance.</p></div></div>}
          {selectedCompany && detailState === "ready" && visibleMetrics.length > 0 && <div className="metric-groups">
            {metricGroups.map((group) => {
              const groupMetrics = group.ids.map((id) => metricsById.get(id)).filter((item): item is Metric => Boolean(item));
              if (!groupMetrics.length) return null;
              return <div className="metric-group" key={group.title}><div className="metric-group-title">{group.title}<span>{groupMetrics.length} metrics</span></div><div className="metric-grid">
                {groupMetrics.map((metric) => <article className={`metric-card ${metric.status !== "calculated" ? "metric-unavailable" : ""}`} key={`${metric.financial_year}-${metric.metric_id}`}>
                  <div className="metric-card-top"><span>{metric.metric_name}</span><span className={`metric-status ${metric.status}`}>{metric.status === "calculated" ? metric.financial_year : metric.status === "unavailable" ? "Input needed" : "Review"}</span></div>
                  <div className="metric-number">{formatValue(metric)}</div>
                  {metric.status !== "calculated" && <p className="metric-explanation">{metric.explanation}</p>}
                  {metric.warnings.map((warning) => <p className="metric-warning" key={warning}>{warning}</p>)}
                  <details><summary>Formula & inputs</summary><p className="formula-text">{metric.formula}</p><p>{metric.inputs.length} source observation(s) · {metric.statement_basis} · {metric.period_start} to {metric.period_end}</p></details>
                </article>)}
              </div></div>;
            })}
          </div>}
        </section>

        <section className="content-section" id="observations">
          <div className="section-heading"><div><p className="eyebrow">SOURCE-REPORTED VALUES · NOT CALCULATED METRICS</p><h2>Reported statement inputs</h2><p className="section-subtitle">Original reported labels and stored values remain separate from calculated metrics.</p></div></div>
          {loadState === "ready" && companies.length === 0 && <div className="metrics-empty"><strong>Reported inputs await source-backed records.</strong><p>No demonstration company values are included.</p></div>}
          {selectedCompany && detailState === "loading" && <div className="empty-inline"><span className="spinner" />Loading reported inputs and source references…</div>}
          {selectedCompany && detailState === "error" && <div className="metrics-empty" role="alert"><strong>Reported inputs are unavailable.</strong><p>{detailError}</p></div>}
          {selectedCompany && detailState === "ready" && reportedObservations.length === 0 && <div className="metrics-empty"><strong>No reported inputs for this statement basis.</strong><p>Choose a different basis or fiscal year.</p></div>}
          {selectedCompany && detailState === "ready" && reportedObservations.length > 0 && visibleObservations.length === 0 && <div className="metrics-empty"><strong>No reported inputs for {financialYear}.</strong><p>The source register is unchanged; choose another fiscal year.</p></div>}
          {selectedCompany && detailState === "ready" && visibleObservations.length > 0 && <div className="benchmark-table-wrap"><table className="benchmark-table"><thead><tr><th>Period</th><th>Reported label</th><th>Mapped line item</th><th>Reported value</th><th>Statement</th><th>Source</th></tr></thead><tbody>{visibleObservations.map((item) => <tr key={item.observation_id}><td>{item.financial_year}<br />{item.period_start} to {item.period_end}</td><td>{item.reported_label}</td><td>{item.line_item_id}</td><td>{item.value ?? "Missing"} {item.unit} {item.currency}</td><td>{item.statement_type.replaceAll("_", " ")}</td><td>{item.publisher} · {item.source_id}{item.source_url ? <> · <a href={item.source_url} target="_blank" rel="noreferrer">Disclosure</a></> : ""}</td></tr>)}</tbody></table></div>}
        </section>

        <section className="content-section" id="analysis">
          <div className="section-heading"><div><p className="eyebrow">CONFIGURED ANALYTICAL SCREENS</p><h2>Trend and risk signals</h2><p className="section-subtitle">Rule-based prompts for review; these findings are not proof of misconduct, insolvency, or an investment recommendation.</p></div></div>
          {loadState === "ready" && companies.length === 0 && <div className="metrics-empty"><span className="metric-empty-icon">◇</span><div><strong>Analysis awaits company records.</strong><p>No financial records are onboarded, so company-level trends and flags cannot yet be assessed.</p></div></div>}
          {selectedCompany && detailState === "loading" && <div className="empty-inline"><span className="spinner" />Evaluating configured rules…</div>}
          {selectedCompany && detailState === "error" && <div className="metrics-empty"><span className="metric-empty-icon">◇</span><div><strong>Analysis is unavailable.</strong><p>{detailError}</p></div></div>}
          {selectedCompany && detailState === "ready" && (() => {
            const flagged = riskAssessments.filter((item) => item.status === "flagged");
            const other = riskAssessments.filter((item) => item.status !== "flagged");
            const insufficientCount = riskAssessments.filter((item) => item.status === "insufficient_data").length;
            return <div className="risk-analysis">
              <p className="risk-config">Threshold set {riskAssessments[0]?.configuration_version ?? "unavailable"} · {basis} basis · {selectedCompany.company_name}</p>
              {riskAssessments.length === 0 && <div className="metrics-empty"><span className="metric-empty-icon">◇</span><div><strong>No compatible observations for this statement basis.</strong><p>No risk rule could be evaluated. This is missing data, not a clear screen.</p></div></div>}
              {riskAssessments.length > 0 && flagged.length === 0 && <div className="metrics-empty"><span className="metric-empty-icon">✓</span><div><strong>No configured flags for the available assessment window.</strong><p>{insufficientCount} of {riskAssessments.length} rules need more compatible history or inputs. A clear screen does not establish the absence of financial risk.</p></div></div>}
              {flagged.map((item) => <article className="risk-card risk-card-flagged" key={item.rule_id}>
                <div className="risk-card-heading"><strong>{item.title}</strong><span>Flagged · {item.financial_year}</span></div>
                <p>{item.fact}</p><p className="risk-interpretation">{item.interpretation}</p>
                <details><summary>Threshold and evidence</summary><p>{item.comparison} · periods: {item.periods.join(", ")}</p>
                  <ul>{item.evidence.map((evidence) => <li key={`${item.rule_id}-${evidence.metric_id}-${evidence.financial_year}`}>
                    {evidence.financial_year}: {evidence.value ?? "unavailable"} {evidence.unit} {evidence.currency ?? ""} · sources {evidence.inputs.map((input) => `${input.source_id} (#${input.observation_id})`).join(", ") || "not available"}
                  </li>)}</ul>
                </details>
              </article>)}
              {other.length > 0 && <details className="risk-other"><summary>Other checks ({other.length})</summary>{other.map((item) => <article key={item.rule_id}>
                <strong>{item.title}</strong><span className={`risk-status risk-status-${item.status}`}>{item.status.replaceAll("_", " ")}</span>
                <p>{item.fact}</p>{item.reason && item.status !== "not_flagged" && <p>{item.reason}</p>}
                <p>{item.interpretation}</p>
              </article>)}</details>}
            </div>;
          })()}
        </section>

        <section className="content-section" id="insights">
          <div className="section-heading"><div><p className="eyebrow">OBSERVED CHANGES WITH SUPPORTING DATA</p><h2>Financial insights</h2><p className="section-subtitle">Deterministic descriptions of adjacent, compatible metric changes. They do not infer cause or predict future results.</p></div></div>
          {loadState === "ready" && companies.length === 0 && <div className="metrics-empty"><span className="metric-empty-icon">↗</span><div><strong>Insights await company records.</strong><p>Source-backed periods are required before metric changes can be described.</p></div></div>}
          {selectedCompany && detailState === "loading" && <div className="empty-inline"><span className="spinner" />Building evidence-backed insights…</div>}
          {selectedCompany && detailState === "error" && <div className="metrics-empty"><strong>Insights unavailable.</strong><p>{detailError}</p></div>}
          {selectedCompany && detailState === "ready" && insights.length === 0 && <div className="metrics-empty"><span className="metric-empty-icon">↗</span><div><strong>No supported changes were available for this history.</strong><p>Missing, incompatible, or non-adjacent metrics are not filled or compared.</p></div></div>}
          {selectedCompany && detailState === "ready" && insights.length > 0 && <div className="insight-list">{insights.map((insight) => <article className="insight-card" key={insight.insight_id}>
            <div className="insight-meta">{insight.category.replaceAll("_", " ")} · {insight.periods.join(" → ")}</div><h3>{insight.finding}</h3><p>{insight.limitations}</p>
            <details><summary>Method and source evidence</summary><p>{insight.rule}</p><ul>{insight.evidence.map((item) => <li key={`${insight.insight_id}-${item.metric_id}-${item.financial_year}`}>{item.financial_year} · {item.metric_name}: {item.value ?? "unavailable"} {item.unit} {item.currency ?? ""} · {item.inputs.map((input) => `${input.source_id} (#${input.observation_id})`).join(", ") || "No source input reference"}</li>)}</ul></details>
          </article>)}</div>}
        </section>

        <section className="content-section" id="benchmark">
          <div className="section-heading"><div><p className="eyebrow">SELECTED COMPARISON SET</p><h2>Peer benchmarking</h2><p className="section-subtitle">Only same-period, same-basis, same-unit, and same-currency metrics are compared. This selected group is not claimed to represent an industry.</p></div></div>
          {selectedCompany && companies.length > 1 && <div className="peer-controls"><label htmlFor="peer-select">Choose comparison companies (up to 20)</label><select id="peer-select" multiple size={Math.min(4, companies.length)} value={peerIds.filter((id) => id !== companyId)} onChange={(event) => setPeerIds(Array.from(event.target.selectedOptions, (option) => option.value).slice(0, 20))}>{companies.filter((company) => company.company_id !== companyId).map((company) => <option value={company.company_id} key={company.company_id}>{company.company_name}{company.ticker ? ` · ${company.ticker}` : ""}</option>)}</select><small>Use Ctrl/Command-click to select more than one company. A peer median requires at least two compatible peers.</small></div>}
          {loadState === "ready" && companies.length < 2 && <div className="metrics-empty"><span className="metric-empty-icon">▥</span><div><strong>Peer benchmarking needs additional companies.</strong><p>No peer figures are fabricated. At least one other source-backed company is needed; two compatible peers are required for a median.</p></div></div>}
          {selectedCompany && companies.length > 1 && detailState === "loading" && <div className="empty-inline"><span className="spinner" />Comparing compatible metrics…</div>}
          {selectedCompany && companies.length > 1 && detailState === "ready" && (!benchmark || benchmark.status === "insufficient_data") && <div className="metrics-empty"><span className="metric-empty-icon">▥</span><div><strong>Insufficient compatible peer data for a benchmark median.</strong><p>{benchmark?.financial_year ?? "No common period"} · select peers with matching reporting dates, statement basis, units, and currencies.</p></div></div>}
          {benchmark?.metrics.some((item) => item.values.length > 1) && <div className="benchmark-table-wrap"><p className="benchmark-disclosure">{benchmark?.financial_year} · selected peer count shown per metric · incompatible or unavailable inputs are excluded and disclosed below.</p><div className="benchmark-summary">{benchmark.metrics.map((item) => <p key={`${item.metric_id}-median`}><strong>{item.metric_id.replaceAll("_", " ")}</strong>: target {item.target_value ?? "unavailable"} · peer median {item.peer_median ?? "insufficient data"} · n={item.peer_count ?? 0} peers</p>)}</div><table className="benchmark-table"><thead><tr><th>Metric</th><th>Company</th><th>Value</th><th>Period</th><th>Source documents</th></tr></thead><tbody>{benchmark.metrics.flatMap((item) => item.values.map((value) => <tr key={`${item.metric_id}-${value.company_id}`}><td>{item.metric_id.replaceAll("_", " ")}{value.is_target ? " · target" : ""}</td><td>{companies.find((company) => company.company_id === value.company_id)?.company_name ?? value.company_id}</td><td>{value.value ?? "—"} {value.unit} {value.currency ?? ""}</td><td>{value.period_start} to {value.period_end}</td><td>{value.sources?.length ? value.sources.map((source) => <div key={`${source.source_id}-${source.financial_year}`}>{source.publisher} · {source.financial_year}{source.publication_date ? ` · published ${source.publication_date}` : ""}{source.source_url ? <> · <a href={source.source_url} target="_blank" rel="noreferrer">Disclosure</a></> : ""}</div>) : value.evidence?.inputs.map((input) => `${input.source_id} (#${input.observation_id})`).join(", ") || "Not available"}</td></tr>))}</tbody></table><p className="benchmark-disclosure">Peer median appears only when at least two compatible peer values exist. Metrics with fewer peers remain insufficient data.</p></div>}
          {benchmark && benchmark.metrics.some((item) => Object.keys(item.exclusions ?? {}).length > 0) && <details className="risk-other"><summary>Excluded peer comparisons</summary>{benchmark.metrics.filter((item) => Object.keys(item.exclusions ?? {}).length > 0).map((item) => <p key={item.metric_id}>{item.metric_id}: {Object.entries(item.exclusions ?? {}).map(([id, reason]) => `${id} — ${reason}`).join("; ")}</p>)}</details>}
        </section>

        <section className="content-section" id="report">
          <div className="section-heading"><div><p className="eyebrow">ON-DEMAND EXPORT FROM STORED RECORDS</p><h2>Analyst report</h2><p className="section-subtitle">Exports are generated from current API data and include periods, metric definitions, provenance, M4A assessments, insights, and limitations.</p></div></div>
          {loadState === "ready" && companies.length === 0 && <div className="metrics-empty"><strong>Report export awaits company records.</strong><p>No empty or fabricated report is generated.</p></div>}
          {selectedCompany && <div className="report-actions"><a className="button-secondary" href={`${API_BASE}/api/companies/${encodeURIComponent(companyId)}/report?${reportQuery.toString()}`}>Download JSON report</a><a className="button-secondary" href={`${API_BASE}/api/companies/${encodeURIComponent(companyId)}/report?${csvReportQuery.toString()}`}>Download metric CSV</a><p>CSV contains metric rows and provenance references. JSON includes methodology, risk assessments, insights, missing-data disclosures, source register, and selected peer comparisons where requested.</p></div>}
        </section>

        <section className="content-section provenance-section" id="provenance">
          <div className="section-heading"><div><p className="eyebrow">TRACEABLE DISCLOSURES</p><h2>Data provenance</h2><p className="section-subtitle">Source documents and reporting periods behind imported observations.</p></div></div>
          {detailState === "loading" && selectedCompany && <div className="empty-inline"><span className="spinner" />Loading source register…</div>}
          {loadState === "ready" && !companies.length && <div className="provenance-empty"><span>↗</span><div><strong>Source register is empty</strong><p>Publisher, URL, retrieval date, reporting basis, and financial period will be shown after data onboarding.</p></div></div>}
          {selectedCompany && detailState === "ready" && provenance.length === 0 && <div className="provenance-empty"><span>↗</span><div><strong>No source references for this company</strong><p>Only records with source provenance are included.</p></div></div>}
          {provenance.length > 0 && <div className="source-list">{provenance.map((source, index) => <article className="source-row" key={`${source.source_id}-${source.financial_year}-${source.statement_type}`}><div className="source-index">{String(index + 1).padStart(2, "0")}</div><div className="source-main"><strong>{source.publisher}</strong>{source.source_url ? <a href={source.source_url} target="_blank" rel="noreferrer">Open disclosure <span>↗</span></a> : <span>Disclosure link unavailable</span>}</div><div className="source-period">{source.financial_year}<span>{source.statement_basis} · {source.statement_type.replaceAll("_", " ")}</span></div><div className="source-date">{source.publication_date ? `Published ${source.publication_date} · ` : ""}Retrieved {source.retrieved_at}</div></article>)}</div>}
        </section>

        <footer className="footer"><span>FinSight <span className="footer-separator">·</span> Financial statement intelligence</span><span>Analysis ready when source-backed data is available.</span></footer>
      </main>
    </div>
  );
}
