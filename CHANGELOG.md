# Changelog

All notable project changes are documented here in reverse chronological order.

## [Unreleased]

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
