# FinSight — Financial Statement Intelligence & Performance Analytics Platform

FinSight is a Python-based financial analytics platform planned to standardise and analyse five years of financial statements for five Indian listed companies. Its intended outputs include profitability, cash-flow quality, working-capital efficiency, leverage, and peer comparisons for analysis in Power BI.

> **Current status:** M1 (foundation and data contract) is complete. The project provides a documented import contract, an initial SQLite schema, a synthetic fixture, and schema/fixture tests. M2 (CSV import and validation) is next. Financial calculations, real-data ingestion, validation workflows, analytics, and dashboard exports are not yet implemented.

## Problem and objectives

Company disclosures use different labels, units, and levels of detail. FinSight aims to preserve source context while mapping reported values to standard line-item identifiers, making later analysis traceable and comparable. The priority is data integrity, reproducibility, and transparent financial conventions.

## Business use cases

Planned use cases include reviewing a company's multi-year performance, comparing peers on aligned reporting periods, investigating changes in cash generation and leverage, and exporting clean data for Power BI. Results are analytical aids; unusual values require investigation and are not conclusions about financial distress or misconduct.

## Technology stack

- Python, Pandas, and NumPy for processing and analysis (planned)
- SQLite initially, using portable schema choices intended to support later PostgreSQL migration
- CSV for Excel-compatible import and export
- Pytest for automated tests
- Power BI for the eventual interactive dashboard

## Status and roadmap

- **M1 — Foundation and data contract:** Initial schema, import contract, synthetic fixture, project documentation, and schema/fixture tests. Implemented and tested.
- **M2 — Import and validation:** CSV ingestion, data-quality checks, reconciliation warnings, and validation reports.
- **M3 — Metric engine:** Configurable calculations and unit tests.
- **M4 — Analytics and exports:** Peer comparisons, rankings, and Power BI-ready CSVs.
- **M5 — Real-data onboarding:** Reviewed source mappings for selected companies and periods.

Features are labelled as implemented only after they exist and have been checked. No real company financial data is included in this milestone.

## Architecture

```text
CSV source files -> ingestion -> standardisation -> SQLite
                                        |               |
                                        v               v
                                  validation       metric engine
                                                        |
                                                        v
                                             analytics -> CSV exports -> Power BI
```

The initial code layout separates these responsibilities so later milestones can add functionality without coupling imports, calculations, and reporting. Raw source files are intended to remain immutable; processed records retain their source and original reported label.

## Project structure

```text
config/                 Example application and calculation configuration
data/raw/               Reserved for original imports; no real data included
data/processed/         Reserved for standardised outputs
data/synthetic/         Synthetic test fixture, explicitly labelled
docs/                   Data contract, schema, and formula documentation
src/finsight/           Application package by responsibility
tests/                  Automated tests
README.md               Project guide and current implementation status
CHANGELOG.md            Chronological milestone record
requirements.txt        Runtime and test dependencies
.gitignore              Local/generated file exclusions
```

## Data model

The initial SQLite schema is documented in [`docs/database-schema.md`](docs/database-schema.md) and defined in [`src/finsight/db/schema.sql`](src/finsight/db/schema.sql).

- `companies`: stable identifiers and company master details.
- `sources`: source publisher, URL, retrieval date, and notes.
- `financial_observations`: reported value, standard line-item ID, original label, statement, period, statement basis, unit, currency, and source.
- `validation_results`: check outcome, severity, message, and related record or batch.
- `calculated_metrics`: metric value and unit, calculation/formula version, and provenance to inputs.
- `processing_logs`: processing run, input, timestamps, status, and summary.

Observation uniqueness is scoped to company, fiscal year, statement basis, statement type, and line item. Missing observations are absent/NULL; they must not be silently replaced with zero. A reported zero remains a stored numeric zero. Statement basis (standalone or consolidated), reporting currency, period, and source are explicit.

## Data contract and provenance

The starter contract is in [`docs/data-contract.md`](docs/data-contract.md). Every imported observation must carry company identity, financial year, period end, statement basis, statement type, standard line-item ID, numeric value, unit, currency, and source reference. Keep the original company label so mapping choices can be reviewed. Record source URL and retrieval date. Never represent synthetic fixture values as company disclosures.

## Financial metrics

No metric calculations are implemented in M1. The planned formulas and conventions are documented in [`docs/financial-metrics.md`](docs/financial-metrics.md), including assumptions around average balances, denominator validity, signs, and unavailable inputs. Definitions such as EBITDA and purchases may differ between companies and must be documented before comparing results.

## Data validation

Validation is planned for duplicate observations, mandatory fields, financial years, units and currencies, balance-sheet and cash-flow reconciliations where inputs allow, unexpected signs or implausible values, missing metric inputs, and differences between source values and calculated results. A validation result should explain the issue and whether it is an error, warning, or manual-review item. No automated validation engine is implemented yet.

## Data sources

No external financial data source has been loaded. The recommended initial workflow is to select five listed companies with accessible annual reports, import manually reviewed CSVs, and use company annual reports and exchange filings as primary evidence. Store source URLs, publication details, retrieval dates, statement basis, period, and currency. Review each line-item mapping against the source statement; avoid scraping as the first ingestion method because labels and definitions vary.

## Setup and usage

Python package setup and application commands will be documented when the first runnable application functionality is implemented. For now, the SQL schema and fixture are reviewed as project artifacts; the fixture is synthetic and must only be used for tests. No application command or dashboard is available yet.

Install the test dependency and run the schema/fixture checks from the project root:

```bash
python -m pip install -r requirements.txt
python -m pytest
```

These checks do not create a persistent database. No application command or dashboard is available yet.

## Example outputs

No analytics output or dashboard screenshot exists yet. The synthetic fixture at [`data/synthetic/financial_observations.csv`](data/synthetic/financial_observations.csv) demonstrates the import fields only; every row is marked `synthetic` and does not represent an actual company.

## Limitations and assumptions

- The schema and line-item identifiers are an initial contract and may evolve as disclosure coverage is assessed.
- No real company data, calculations, ingestion workflow, validation engine, exports, or user interface are implemented.
- Financial periods are annual in the initial scope; fiscal year labels need an agreed convention during ingestion.
- Working-capital and return metrics depend on definitions and opening balances that may not be available in the first imported year.
- Currency conversion and cross-period restatement handling are not implemented.

## License

No license has been selected. All rights remain with their respective owners until a license is added.
