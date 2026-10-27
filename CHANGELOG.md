# Changelog

All notable project changes are documented here in reverse chronological order.

## [Unreleased]

### M1 — Foundation and data contract — 2026-10-27

- **Features added:** Initial directory layout; SQLite schema; CSV data contract; synthetic-only observation fixture; documented planned metric conventions; tests for schema creation, duplicate-key and statement-basis constraints, and synthetic fixture labelling.
- **Files changed:** `README.md`, `CHANGELOG.md`, `.gitignore`, `requirements.txt`, `config/example.toml`, `docs/data-contract.md`, `docs/database-schema.md`, `docs/financial-metrics.md`, `src/finsight/db/schema.sql`, package placeholders under `src/finsight/`, `data/synthetic/financial_observations.csv`, and `tests/test_schema.py`.
- **Tests executed:** `python -m pytest -q` — 4 passed, including the final documentation/configuration state.
- **Known issues:** No application logic, importer, calculations, validations, analytics, or real financial data. Git repository and remote are not configured.
- **Design decisions:** Keep source provenance and original labels; explicitly distinguish statement basis, currency, and unit; use separate source, observation, validation, metric, and processing-run tables; synthetic rows are labelled and are not actual disclosures.
