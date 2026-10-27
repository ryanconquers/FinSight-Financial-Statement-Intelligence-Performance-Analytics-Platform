# FinSight — Financial Statement Intelligence & Performance Analytics Platform

FinSight is an early-stage financial analytics application for importing source-backed company statements, calculating documented performance metrics, and displaying their inputs and provenance. No real company disclosures have been onboarded; the interface says so and shows no fabricated financial results.

> **Current status:** M1–M3 are deployed as previously verified. M4A and the M4 history, insight, peer benchmark, report export, and storage safeguards are implemented on this branch but have not been deployed. The live M3 API has no company records, so no company-level metrics, provenance, risk analysis, peer results, or reports have been verified end to end and no financial results are shown.

## Objectives and use cases

The platform is designed to preserve company-reported labels, periods, statement basis, currency, unit, and source details while calculating transparent growth, profitability, cash-flow, working-capital, and leverage measures. Intended users can review company history, investigate cash generation and balance-sheet efficiency, and later compare peers and export data for Power BI. A metric result is an analytical prompt, not a conclusion about misconduct or distress.

## Technology and architecture

- Python, Pandas, Decimal, FastAPI, and SQLite for ingestion, calculations, and API responses; SQLite can use a durable mounted volume for a single API instance
- Next.js 16 with TypeScript for the dashboard
- Pytest, HTTPX, and Node/TypeScript build checks
- GitHub Pages static frontend; FastAPI backend deployed separately on Render

```text
source-backed CSV -> validation -> SQLite observations
                                      |
                      pure Decimal metric engine
                                      |
                      FastAPI read-only analysis and export endpoints
                                      |
                    Next.js dashboard (empty by default)
```

Metric calculations are separate from SQLite reads and HTTP presentation. Metrics, insights, peer comparisons, and reports are calculated at request time and are not stored as derived data. SQLite initialization is versioned and transaction-safe; persistence requires a durable volume in production.

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

M3 implements revenue growth and CAGR; gross profit and margin; EBITDA, EBIT, and net-profit margins; ROA, ROE, and ROCE; operating cash flow, free cash flow, OCF/net-income, OCF/net-income divergence, and OCF year-over-year absolute change; receivable, inventory, and payable days and cash conversion cycle; total debt, net debt, debt-to-equity, interest coverage, and net debt/EBITDA. The full formulas, standardized input IDs, denominator rules, average-balance convention, and missing-input handling are in [`docs/financial-metrics.md`](docs/financial-metrics.md).

M4 derives deterministic historical insights, source-backed peer comparisons, analyst JSON/CSV reports, and M4A's explainable rule assessments from M3 values. It does not duplicate formulas or persist derived results. Peer sets are explicit user choices; incompatible metrics are excluded, and peer medians require two valid peers. Risk thresholds are provisional and configurable. See [`docs/financial-risk-analysis.md`](docs/financial-risk-analysis.md) and [`docs/m4-analysis.md`](docs/m4-analysis.md). No finding is proof of fraud, insolvency, or distress or an investment recommendation.

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
- `GET /api/companies/{company_id}/insights?statement_basis=consolidated&peer_ids=ID1` — deterministic observations from adjacent compatible metrics and flagged M4A rules, with optional selected-peer differences.
- `GET /api/companies/{company_id}/benchmark?statement_basis=consolidated&peer_ids=ID1&peer_ids=ID2&financial_year=FY2025` — explicit peer comparison with exclusions, source evidence, and median only when at least two compatible peer values exist.
- `GET /api/companies/{company_id}/report?statement_basis=consolidated&format=json` — analyst report with metrics, provenance, risk assessments, insights, missing-data notes, and optionally selected peer comparisons.
- `GET /api/companies/{company_id}/report?statement_basis=consolidated&format=csv` — flattened metric rows with formulas and provenance references.
- `GET /api/companies/{company_id}/provenance` — source publisher, URL, retrieval date, basis, and period.
- `GET /api/companies/{company_id}/observations?statement_basis=consolidated&financial_year=FY2025` — original reported labels and values with source references, separate from calculated metrics.

JSON responses use a `data`/`meta` envelope; request errors use a consistent `error` envelope. CSV reports are downloads. CORS origins are set with `FINSIGHT_CORS_ORIGINS`. Database location is set with `FINSIGHT_DATABASE_PATH`; its default is a repository-relative path. Set `FINSIGHT_REQUIRE_PERSISTENT_STORAGE=1` only with an absolute durable-volume path to fail fast on local defaults and ephemeral `/tmp` or `/var/tmp` locations.

Validate and import a source-backed CSV using the documented contract (any validation error rejects the whole dataset):

```bash
PYTHONPATH=src python -m finsight.cli validate path/to/filing.csv --report-json /tmp/validation.json
PYTHONPATH=src python -m finsight.cli ingest path/to/filing.csv --db "$FINSIGHT_DATABASE_PATH" --report-json /tmp/import.json
PYTHONPATH=src python -m finsight.cli db-backup --db "$FINSIGHT_DATABASE_PATH" --output /var/backups/finsight.sqlite3
PYTHONPATH=src python -m finsight.cli db-verify --db /var/backups/finsight.sqlite3
```

CSV metadata retains publisher, source URL, optional filing publication date, retrieval date, reporting period, basis, and original labels. FinSight does not scrape PDFs; source figures must be extracted/reviewed externally and then supplied in the CSV contract.

## Frontend

In a second terminal:

```bash
cd web
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. Set `NEXT_PUBLIC_FINSIGHT_API_URL` to the backend origin when it is not `http://localhost:8000`. The page includes company/basis/year selectors, reported input and provenance views, metrics, M4A risk findings, deterministic insights, selected peer comparison, report downloads, and loading/error/empty/insufficient-data states. No sample chart or company ranking is included.

## Tests and build checks

From the repository root:

```bash
python -m pytest -q
cd web && npm test && npm run lint && npm run typecheck && npm run build
```

Python tests cover formulas, missing/zero/negative inputs, period and unit/currency incompatibility, all M4A rules, compatible/incompatible benchmarks, insight generation, report/API responses, database versioning/backups, strict imports, empty-data behavior, and provenance. Frontend checks include API-client tests (`npm test`), ESLint, TypeScript, and a production build. No browser automation suite is committed.

## Deployment path and constraints

The Next.js frontend is configured for static export to GitHub Pages through [`.github/workflows/deploy-pages.yml`](.github/workflows/deploy-pages.yml). Its browser client calls the Render API; GitHub Pages serves the static UI and does not run FastAPI. A Render service definition remains in [`render.yaml`](render.yaml) for the API. Deployment details are in [`docs/deployment.md`](docs/deployment.md).

The [GitHub Pages site](https://ryanconquers.github.io/FinSight-Financial-Statement-Intelligence-Performance-Analytics-Platform/) is a static dashboard connected to the separately hosted Render API. Prior live checks verified status/company-list requests and empty states. The new M4 endpoints are implemented locally but have not been deployed or live-verified. The live API has no company records; deployment connectivity does not verify statements or figures. The Pages build embeds `NEXT_PUBLIC_FINSIGHT_API_URL`; Render CORS must allow the Pages origin. The current Render blueprint remains a free service using ephemeral `/tmp` SQLite. Before onboarding financial data, provision a persistent disk, set `FINSIGHT_DATABASE_PATH` to its mount path, enable `FINSIGHT_REQUIRE_PERSISTENT_STORAGE=1`, and test backup/recovery. No persistent disk has been configured or verified.

## Data and limitations

There is no real financial data and no synthetic financial dataset in the repository. Automated tests create clearly test-only observations in temporary files/databases. CSV provenance is syntax-checked but sources are not fetched or independently verified. Arbitrary PDF extraction, automatic real-company collection, authentication, and Power BI export are not implemented. Peer results are descriptive of selected companies, not representative group statistics. SQLite `NUMERIC` is not fixed-scale decimal storage; Decimal calculations cannot restore precision rounded before reading. Production durability requires operator-configured persistent storage; the current Render service remains ephemeral. Risk thresholds remain provisional and uncalibrated.

## License

No license has been selected.
