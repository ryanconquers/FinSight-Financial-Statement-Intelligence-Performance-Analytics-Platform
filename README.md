# FinSight — Financial Statement Intelligence & Performance Analytics Platform

FinSight is a Python analytics backend for importing and validating source-backed financial statement observations from Indian listed companies. It is designed to preserve disclosure provenance and prepare consistent data for later financial calculations, peer analysis, and Power BI.

> **Current status:** M2 (CSV ingestion and data validation) is implemented and tested. The importer, validation reports, and transactional SQLite writes are available. No real financial data has been collected or imported. No synthetic financial dataset is included. M3 metric calculations are planned and not implemented.

## Objectives and use cases

FinSight aims to standardise company disclosures while retaining original reported labels, source references, units, currencies, financial periods, and standalone/consolidated basis. Planned use cases include historical company review, peer comparison, investigation of cash generation and leverage, and Power BI export. An unusual value is a review prompt, not proof of misconduct or distress.

## Technology

- Python and Pandas for CSV parsing and validation
- SQLite for transactional storage; schema types are selected with later PostgreSQL migration in mind
- CSV and JSON validation reports
- Pytest for automated checks
- Power BI integration is planned; no dashboard is included

## Status and roadmap

- **M1 — Foundation and data contract:** SQLite schema, documented CSV contract, project structure, formula notes, and schema checks. Complete.
- **M2 — CSV ingestion and validation:** Contract-based parsing, row validation, provenance registration, transactional SQLite import, and machine-readable reports. Implemented and tested (42 passing tests).
- **M3 — Metric engine:** Configurable financial formulas and calculation tests. Planned.
- **M4 — Analytics and exports:** Period-aligned peer comparisons, rankings, and Power BI-ready exports. Planned.
- **M5 — Real-data onboarding:** Select companies and add analyst-reviewed source-backed filings. Planned; no real data is included yet.

## Architecture

```text
Source-backed CSV
      |
      v
Pandas parser -> contract validation -> row-level report
                                       |
                              valid rows only
                                       v
                          SQLite transaction
                    companies + sources + observations
                                       |
                    JSON/CSV validation report
```

The importer lives in `src/finsight/ingestion/`, validation rules and report models in `src/finsight/validation/`, SQLite connection and persistence code in `src/finsight/db/`, and the command-line interface in `src/finsight/cli.py`. Data is not silently trimmed, rescaled, or replaced with zero. Errors, warnings, and manual-review findings are reported separately.

## Project structure

```text
config/                 Example runtime configuration
data/raw/               Reserved for source-backed CSVs; currently empty
docs/                   Data contract, schema, and planned formula notes
src/finsight/
  ingestion/            CSV parsing
  validation/           Contract checks and reports
  db/                   SQLite schema, connection, and transactional writes
  metrics/              Reserved for M3
  analytics/            Reserved for M4
  exports/              Reserved for M4
tests/                  Temporary-input and temporary-database tests
README.md               Project guide and implementation status
CHANGELOG.md            Milestone history
requirements.txt        Runtime/test dependencies
```

## CSV format and provenance

The full column contract is in [`docs/data-contract.md`](docs/data-contract.md). Required values include company identity, `FY2025` style financial-year label, ISO period dates, statement type, statement basis, standard line-item ID, source label, finite numeric amount, unit, currency, source ID/publisher/URL, retrieval date, and an explicit `is_synthetic=false` flag. The optional field is `ticker`. Synthetic data or synthetic source labels are rejected. A blank amount is unavailable and invalid; a disclosed zero is valid.

M2 validates date syntax and order, FY/end-year alignment, statement enums, units, ISO currency code shape, duplicate observation keys, company/source metadata consistency, numeric finiteness, and provenance. It warns on unusually large amounts or negative values for commonly non-negative line items, and flags unusual periods or peer scale mismatches for manual review. It does not transform units or currencies.

## Install and run

From the repository root:

```bash
python -m pip install -r requirements.txt
python -m pytest
```

Validate a real, source-backed CSV without database writes:

```bash
PYTHONPATH=src python -m finsight.cli validate /path/to/observations.csv \
  --report-json /tmp/finsight-validation.json \
  --report-csv /tmp/finsight-validation.csv
```

Validate and import valid rows into SQLite:

```bash
PYTHONPATH=src python -m finsight.cli ingest /path/to/observations.csv \
  --db data/finsight.sqlite3 \
  --report-json /tmp/finsight-import.json \
  --report-csv /tmp/finsight-import.csv
```

The database schema is initialized automatically. Parent directories for the database and report files must already exist. Validation uses exit code 1 when errors exist. Import reports distinguish `imported`, `imported_with_findings`, `partial_import_with_validation_errors`, `not_imported_validation_errors`, and `import_failed_rolled_back` outcomes. Valid rows in a mixed file are committed together; invalid rows and their row/field findings are identified in the report. A database write failure rolls the full file transaction back.

## Report severity

- **Error:** invalid or missing data; the affected row is not imported.
- **Warning:** a data-quality concern that does not prevent import.
- **Manual review:** an unusual period, plausible-but-unusual amount, or non-comparable peer scale requiring analyst/source review.
- **Info:** informational report output.

Findings include CSV line numbers (header is line 1) and fields where applicable. Reports include input filename, counts, status, database write summary, and separate severity collections in JSON, plus a findings-oriented CSV.

## Database

See [`docs/database-schema.md`](docs/database-schema.md) and [`src/finsight/db/schema.sql`](src/finsight/db/schema.sql). Import registers companies and source records before observations within one SQLite transaction. Foreign keys are enabled. Existing company/source identifiers must match their registered metadata. Validation findings and processing outcomes are recorded for successful transactions; after rollback, a failed processing log is attempted separately.

The schema separates `companies`, `sources`, `financial_observations`, `validation_results`, `processing_logs`, and the reserved `calculated_metrics` table. Observation uniqueness is keyed by company, fiscal year, statement basis, statement type, and line-item ID.

## Financial metrics

No financial metrics are calculated in M2. Planned formulas and conventions—including growth, margins, returns, cash flow, working capital, and leverage—remain documented in [`docs/financial-metrics.md`](docs/financial-metrics.md) for M3. Calculations will require matching periods, statement basis, units, and currencies.

## Data sources

No company disclosures have been imported. The importer expects analyst-reviewed CSVs whose source URL, publisher, and retrieval date point to the original disclosure. Source URLs are syntax-checked but not fetched. Company selection and real-data collection are deferred to M5.

## Limitations

- The currency check validates uppercase three-letter code shape; it does not confirm a code against a maintained ISO registry.
- Units are consistency-checked but not converted. Peer records with differing scales or currencies need analyst standardisation before comparison.
- Annual period length outside 350–380 days is a manual-review finding, not an automatic rejection; non-calendar fiscal year label conventions may need a future configurable mapping.
- Source URLs are syntax-checked, not fetched or independently verified.
- Row validation is not a complete accounting reconciliation or line-item taxonomy review.
- M2 does not calculate financial metrics, perform peer analytics, export Power BI datasets, or collect real financial filings.
- The existing schema has no row-number column for database findings; CSV row locations are retained in finding messages.

## License

No license has been selected. All rights remain with their respective owners until a license is added.
