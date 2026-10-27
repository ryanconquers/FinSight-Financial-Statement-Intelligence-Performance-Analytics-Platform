# FinSight — Financial Statement Intelligence & Performance Analytics Platform

FinSight is an early-stage financial analytics application for importing source-backed company statements, calculating documented performance metrics, and displaying their inputs and provenance. No real company disclosures have been onboarded; the interface says so and shows no fabricated financial results.

> **Current status:** M1–M2 foundations and M3 metrics/web integration are deployed. M4A explainable trend/risk engine and dashboard integration are implemented in the current branch but are not yet deployed. The live M3 API has no company records, so no company-level metrics, provenance, or M4A assessments have been verified end to end and no financial results are shown.

## Objectives and use cases

The platform is designed to preserve company-reported labels, periods, statement basis, currency, unit, and source details while calculating transparent growth, profitability, cash-flow, working-capital, and leverage measures. Intended users can review company history, investigate cash generation and balance-sheet efficiency, and later compare peers and export data for Power BI. A metric result is an analytical prompt, not a conclusion about misconduct or distress.

## Technology and architecture

- Python, Pandas, Decimal, FastAPI, and SQLite for ingestion, calculations, and API responses
- Next.js 16 with TypeScript for the dashboard
- Pytest, HTTPX, and Node/TypeScript build checks
- GitHub Pages static frontend; FastAPI backend deployed separately on Render

```text
source-backed CSV -> validation -> SQLite observations
                                      |
                      pure Decimal metric engine
                                      |
                      FastAPI read-only endpoints
                                      |
                    Next.js dashboard (empty by default)
```

Metric calculations are separate from SQLite reads and HTTP presentation. The database schema is unchanged in M3. Results contain calculation status, formula/version, period, units, and source-observation references.

## Project structure

```text
src/finsight/metrics/   Pure calculations, value models, SQLite read adapter
src/finsight/api/       FastAPI app and read endpoints
src/finsight/db/        Existing schema, connection, ingestion persistence
src/finsight/ingestion/ Existing CSV parser
src/finsight/validation/Existing CSV rules and reports
web/                    Next.js App Router dashboard
config/                 Example configuration
data/raw/               Empty location reserved for source-backed files
docs/                   Data contract, metric formulas, schema, deployment notes
tests/                  Temporary-data Python tests
README.md               Current project and setup guide
CHANGELOG.md            Milestone history
requirements.txt        Python dependencies
render.yaml             Render API service definition
.env.example            Local backend environment example
```

## Implemented metrics and analysis

M3 implements revenue growth and CAGR; EBITDA, EBIT, and net-profit margins; ROA, ROE, and ROCE; operating cash flow, free cash flow, OCF/net-income, OCF/net-income divergence, and OCF year-over-year absolute change; receivable, inventory, and payable days and cash conversion cycle; total debt, net debt, debt-to-equity, interest coverage, and net debt/EBITDA. The full formulas, standardized input IDs, denominator rules, average-balance convention, and missing-input handling are in [`docs/financial-metrics.md`](docs/financial-metrics.md).

M4A derives explainable trend and screening assessments from those M3 results; it does not calculate duplicate financial formulas or persist flags. Provisional configurable thresholds and status semantics are documented in [`docs/financial-risk-analysis.md`](docs/financial-risk-analysis.md) and configured in [`config/financial_risk_thresholds.toml`](config/financial_risk_thresholds.toml). A triggered rule is an analytical prompt for review, not proof of fraud, insolvency, or distress and not an investment recommendation. The thresholds are not empirically calibrated.

Missing inputs produce `unavailable`, invalid denominators or incompatible basis/period/currency/unit produce `invalid_input`, and valid calculations produce `calculated`. Decimal arithmetic is used; ratios are serialized as decimal strings. Values are never zero-filled, converted between currencies, or silently rescaled. No calculation is written to the database in M3.

## API

Start the API from the repository root after installing dependencies:

```bash
python -m pip install -r requirements.txt
cp .env.example .env
set -a && source .env && set +a
PYTHONPATH=src uvicorn finsight.api.app:app --reload --host 127.0.0.1 --port 8000
```

Implemented read endpoints:

- `GET /api/health` — liveness check, independent of the database.
- `GET /api/status` — development status and count of source-backed observations.
- `GET /api/companies` — registered companies with source-backed observations; empty list when none exist.
- `GET /api/companies/{company_id}/metrics?statement_basis=consolidated&financial_year=FY2025` — structured metrics for a company/basis, optionally one year.
- `GET /api/companies/{company_id}/analysis?statement_basis=consolidated` — M4A assessments derived from existing metrics, with thresholds, explanations, and observation/source evidence.
- `GET /api/companies/{company_id}/provenance` — source publisher, URL, retrieval date, basis, and period.

Responses use a `data`/`meta` envelope; request errors use a consistent `error` envelope. CORS origins are set with `FINSIGHT_CORS_ORIGINS`. Database location is set with `FINSIGHT_DATABASE_PATH`; its default is a repository-relative path.

## Frontend

In a second terminal:

```bash
cd web
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. Set `NEXT_PUBLIC_FINSIGHT_API_URL` to the backend origin when it is not `http://localhost:8000`. The page includes navigation, company and statement-basis selectors when data exists, year filtering, metric/provenance sections, loading/error/empty states, and a visible under-development notice. No sample chart or company ranking is included.

## Tests and build checks

From the repository root:

```bash
python -m pytest -q
cd web && npm test && npm run lint && npm run typecheck && npm run build
```

Python tests cover formulas, missing/zero/negative inputs, period and unit/currency incompatibility, M4A rule boundaries and evidence, API responses, empty-data behavior, and provenance. Frontend checks include API-client tests (`npm test`), ESLint, TypeScript, and a production build. No browser automation suite is committed.

## Deployment path and constraints

The Next.js frontend is configured for static export to GitHub Pages through [`.github/workflows/deploy-pages.yml`](.github/workflows/deploy-pages.yml). Its browser client calls the Render API; GitHub Pages serves the static UI and does not run FastAPI. A Render service definition remains in [`render.yaml`](render.yaml) for the API. Deployment details are in [`docs/deployment.md`](docs/deployment.md).

The [GitHub Pages site](https://ryanconquers.github.io/FinSight-Financial-Statement-Intelligence-Performance-Analytics-Platform/) is a static dashboard that reads status, company, metric, and provenance data from the deployed Render API. Live integration checks confirmed successful status and company-list requests; the API currently returns no company records, so company-level metrics and provenance have not been verified end to end. Deployment checks do not verify financial statements or figures, which have not been independently verified. The Pages build embeds the public API origin in `NEXT_PUBLIC_FINSIGHT_API_URL`; the Render API allows the Pages origin through CORS. The included Render definition uses a free service and an ephemeral `/tmp` SQLite file. Render free web services can spin down, and filesystem changes are lost after restart/deploy. Before adding actual statement records, configure durable storage: a paid Render service with a persistent disk mounted at `/var/data`, or migrate the database to managed PostgreSQL.

## Data and limitations

There is no real financial data and no synthetic financial dataset in the repository. Automated tests create small artificial rows only in temporary files/databases. CSV provenance is format-checked but not fetched or independently verified. The currency validator checks code shape, not membership in a maintained registry. Reported EBITDA is used as provided; line-item mappings and accounting definitions still need analyst review. SQLite `NUMERIC` is not a fixed-scale decimal type, so the engine uses Decimal after reading stored observations but cannot restore precision already rounded by SQLite affinity. No peer benchmarking, Power BI export, or authentication is implemented.

## License

No license has been selected.
