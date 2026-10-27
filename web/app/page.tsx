"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
  source_url: string;
  publication_date: string | null;
  retrieved_at: string;
  financial_year: string;
  statement_basis: string;
  statement_type: string;
};

type LoadState = "loading" | "ready" | "error";
const API_BASE = (process.env.NEXT_PUBLIC_FINSIGHT_API_URL || "http://localhost:8000").replace(/\/$/, "");
const STATIC_PAGES_MODE = process.env.NEXT_PUBLIC_FINSIGHT_STATIC_PAGES === "true";

const percentageMetrics = new Set([
  "revenue_growth", "revenue_cagr", "ebitda_margin", "ebit_margin",
  "net_profit_margin", "roa", "roe", "roce",
]);
const metricGroups = [
  { title: "Growth & profitability", ids: ["revenue_growth", "revenue_cagr", "ebitda_margin", "ebit_margin", "net_profit_margin", "roa", "roe", "roce"] },
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
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${metric.currency ?? ""} ${metric.unit}`.trim();
}

export default function Home() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState("");
  const [status, setStatus] = useState<ProjectStatus | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState("");
  const [basis, setBasis] = useState<"consolidated" | "standalone">("consolidated");
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [provenance, setProvenance] = useState<Provenance[]>([]);
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
      }
      setCompanyId((current) => nextCompanies.some((company) => company.company_id === current) ? current : nextCompanies[0]?.company_id || "");
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
    Promise.all([
      requestData<Metric[]>(API_BASE, `/api/companies/${encodeURIComponent(companyId)}/metrics?statement_basis=${basis}`),
      requestData<Provenance[]>(API_BASE, `/api/companies/${encodeURIComponent(companyId)}/provenance`),
    ]).then(([nextMetrics, nextProvenance]) => {
      if (!active) return;
      setMetrics(nextMetrics);
      setProvenance(nextProvenance);
      setDetailState("ready");
    }).catch((error: unknown) => {
      if (!active) return;
      setDetailError(error instanceof Error ? error.message : "Could not load this company's data.");
      setDetailState("error");
    });
    return () => { active = false; };
  }, [companyId, basis, detailAttempt]);

  const years = useMemo(() => [...new Set(metrics.map((metric) => metric.financial_year))].sort().reverse(), [metrics]);
  const visibleMetrics = useMemo(
    () => metrics.filter((metric) => financialYear === "all" || metric.financial_year === financialYear),
    [metrics, financialYear],
  );
  const selectedCompany = companies.find((company) => company.company_id === companyId);
  const metricsById = new Map(visibleMetrics.map((metric) => [metric.metric_id, metric]));

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
          <a className="nav-link" href="#provenance"><span className="nav-icon">↗</span>Data provenance</a>
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note"><span className="status-dot" />M3 foundation</div>
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
            <div className="summary-foot"><span className="summary-muted">Verified statement line items</span></div>
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
              <select id="company-select" value={companyId} onChange={(event) => { setCompanyId(event.target.value); setFinancialYear("all"); }}>
                {companies.map((company) => <option value={company.company_id} key={company.company_id}>{company.company_name}{company.ticker ? ` · ${company.ticker}` : ""}</option>)}
              </select>
              <label className="sr-only" htmlFor="basis-select">Statement basis</label>
              <select id="basis-select" value={basis} onChange={(event) => setBasis(event.target.value as "standalone" | "consolidated")}>
                <option value="consolidated">Consolidated</option><option value="standalone">Standalone</option>
              </select>
            </div>}
          </div>
          {loadState === "loading" && <div className="empty-card loading-card"><span className="spinner" /><div><strong>Connecting to FinSight</strong><p>The API may be waking after inactivity. This first request can take a little longer.</p></div></div>}
          {loadState === "ready" && companies.length === 0 && <div className="empty-card"><div className="empty-icon">⌕</div><div><span className="empty-kicker">NO COMPANIES YET</span><h3>Your research workspace is ready.</h3><p>When reviewed annual statement data is added, company history and analysis will appear here. No sample financial results are displayed.</p></div><div className="empty-meta"><span>01</span><span>Source first<br />analysis</span></div></div>}
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
          {selectedCompany && detailState === "ready" && metrics.length === 0 && <div className="metrics-empty"><span className="metric-empty-icon">↗</span><div><strong>No {basis} observations for this company.</strong><p>Choose another statement basis or onboard reviewed source-backed observations.</p></div></div>}
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

        <section className="content-section provenance-section" id="provenance">
          <div className="section-heading"><div><p className="eyebrow">TRACEABLE DISCLOSURES</p><h2>Data provenance</h2><p className="section-subtitle">Source documents and reporting periods behind imported observations.</p></div></div>
          {detailState === "loading" && selectedCompany && <div className="empty-inline"><span className="spinner" />Loading source register…</div>}
          {loadState === "ready" && !companies.length && <div className="provenance-empty"><span>↗</span><div><strong>Source register is empty</strong><p>Publisher, URL, retrieval date, reporting basis, and financial period will be shown after data onboarding.</p></div></div>}
          {selectedCompany && detailState === "ready" && provenance.length === 0 && <div className="provenance-empty"><span>↗</span><div><strong>No source references for this company</strong><p>Only reviewed records with source provenance are included.</p></div></div>}
          {provenance.length > 0 && <div className="source-list">{provenance.map((source, index) => <article className="source-row" key={`${source.source_id}-${source.financial_year}-${source.statement_type}`}><div className="source-index">{String(index + 1).padStart(2, "0")}</div><div className="source-main"><strong>{source.publisher}</strong><a href={source.source_url} target="_blank" rel="noreferrer">Open disclosure <span>↗</span></a></div><div className="source-period">{source.financial_year}<span>{source.statement_basis} · {source.statement_type.replaceAll("_", " ")}</span></div><div className="source-date">Retrieved {source.retrieved_at}</div></article>)}</div>}
        </section>

        <footer className="footer"><span>FinSight <span className="footer-separator">·</span> Financial statement intelligence</span><span>Analysis ready when source data is verified.</span></footer>
      </main>
    </div>
  );
}
