# Changelog

All notable project changes are documented here in reverse chronological order.

## [Unreleased]

### M4 — Historical analysis, insights, peer comparison, and reporting

- **Features added:** M4A configurable risk rules remain integrated. Added gross profit/margin, deterministic trend/contrasting/coincident indicators, exact-period peer comparisons with compatibility exclusions and descriptive medians, raw reported-observation inspection, analyst JSON and metric CSV exports, SQLite schema versioning, strict all-or-nothing CSV imports, persistent-volume guard, and backup/verify/restore commands. No derived analytics are persisted.
- **Tests:** Python suite — 133 passed; frontend API-client tests — 15 passed; ESLint, TypeScript, production build, and `git diff --check` passed on the final implementation.
- **Limitations:** The M4 source changes have not been deployed or live-verified. The live API has no company records. Render still uses ephemeral SQLite storage; a durable disk, persistent path, and backup/recovery drill are operator prerequisites. Risk thresholds remain provisional. No financial disclosures or figures are independently verified.

### M3 — Financial metrics engine and web foundation — 2026-10-27

- **Features added:** Pure Decimal metric engine for growth, profitability, returns, cash flow, working capital, and leverage; SQLite observation adapter; FastAPI health/status, company, metrics, and provenance endpoints; environment-based database/CORS settings; Next.js dashboard with honest empty/loading/error states; GitHub Pages static frontend workflow and Render API blueprint.
- **Files changed:** `.gitignore`, `.env.example`, `README.md`, `CHANGELOG.md`, `requirements.txt`, `render.yaml`, `docs/data-contract.md`, `docs/financial-metrics.md`, `docs/deployment.md`, `.github/workflows/deploy-pages.yml`, `src/finsight/metrics/`, `src/finsight/api/`, `web/`, `tests/test_metrics.py`, and `tests/test_api.py`.
- **Tests executed:** `python -m pytest -q` — 57 passed; API client tests — 6 passed; `npm run lint` — passed; `npm run typecheck` — passed; GitHub Pages production build — passed (Next.js 16.4.3) with the Render API URL embedded; live Chromium check — Pages, `/api/status`, and `/api/companies` returned HTTP 200 and the dashboard showed the empty-data state.
- **Known issues:** No real company data has been onboarded; the Render API currently returns an empty company list, so the connected dashboard shows its empty states. GitHub Pages serves the static frontend and does not host the FastAPI API. Render's free service uses ephemeral SQLite storage and may spin down; real data requires persistent storage. SQLite `NUMERIC` affinity may round source amounts before Decimal calculations read them.
- **Design decisions:** Keep the existing SQLite schema unchanged; calculate through pure Decimal functions and return input provenance rather than persisting M3 metric rows. Use GitHub Pages for the static frontend and Render for a separately deployed API; defer persistent storage until data onboarding to avoid provisioning paid infrastructure for an empty dataset. Revenue CAGR spans the earliest and latest available revenue years.

### M2 — CSV ingestion and data validation — 2026-10-27

- **Features added:** Pandas CSV parser; contract validation for required fields, dates, numeric finiteness, statement metadata, provenance, duplicate keys, unit/currency consistency, and synthetic-data prohibition; structured JSON/CSV reports; CLI validate/ingest commands; transactional SQLite registration/import and rollback handling.
- **Files changed:** `README.md`, `CHANGELOG.md`, `requirements.txt`, `docs/data-contract.md`, `docs/database-schema.md`, `src/finsight/cli.py`, `src/finsight/ingestion/csv_importer.py`, `src/finsight/validation/observations.py`, `src/finsight/validation/report.py`, `src/finsight/db/connection.py`, `src/finsight/db/repository.py`, `tests/conftest.py`, `tests/test_schema.py`, and `tests/test_ingestion.py`; removed `data/synthetic/financial_observations.csv`.
- **Tests executed:** `python -m pytest -q` — 42 passed.
- **Known issues:** Currency code shape and URL syntax are validated locally but not externally verified; units are not converted; annual period exceptions need manual review; no financial calculations or real source data.
- **Design decisions:** Invalid rows are identified and excluded while valid rows in the same file can be imported in one clearly labelled partial import; any SQLite write failure rolls back the complete file transaction. Synthetic records and synthetic source identifiers are rejected.

### M1 — Foundation and data contract — 2026-10-27

- **Features added:** Initial directory layout; SQLite schema; CSV data contract; initial test fixture (removed in M2 per the project's no-synthetic-dataset policy); documented planned metric conventions; schema tests.
- **Files changed:** Initial schema, documentation, configuration, test fixture, and package placeholders as recorded in commit `f2bbf870c538f3168955cc84d07ac2fbff9b3ba3`.
- **Tests executed:** `python -m pytest -q` — 4 passed at M1 completion.
- **Known issues:** No application logic, importer, calculations, validations, analytics, or real financial data at M1 completion.
- **Design decisions:** Preserve source provenance and reported labels; explicitly distinguish statement basis, currency, and unit; separate source, observation, validation, metric, and processing-run tables.
