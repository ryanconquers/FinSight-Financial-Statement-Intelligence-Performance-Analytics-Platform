# M4 historical analysis, peer comparison, and reporting

M4 builds on the existing Decimal M3 metric engine and M4A configurable screening rules. All derived output is computed at request time and is not written to SQLite.

## Historical analysis and insights

The metrics endpoint returns each available fiscal year's calculated and unavailable results, with formula, status, units, periods, and source observation references. M4 adds gross profit (`revenue - abs(cost_of_goods_sold)`) and gross margin (`gross_profit / revenue`) using the same-period standardized inputs. Other metric formulas and denominator conventions are in [`financial-metrics.md`](financial-metrics.md).

`GET /api/companies/{company_id}/observations?statement_basis=consolidated&financial_year=FY2025` exposes the original stored reported labels and values with source metadata, separate from calculated metrics. Synthetic-marked records and sources are excluded.

`GET /api/companies/{company_id}/insights?statement_basis=consolidated&peer_ids=ID1` returns deterministic observations from adjacent annual metrics. It describes observed revenue-growth, margin, cash-conversion, leverage, interest-coverage, and working-capital changes and includes metric/source evidence. If peers are supplied, it also reports exact numeric differences from compatible selected-peer medians. It can group multiple M4A flags as coincident indicators and describe contrasting revenue-growth/margin directions. Grouping does not create a composite score, establish a shared cause, or imply misconduct, insolvency, distress, or investment merit. Gaps, incompatible periods, units, currencies, and bases are not filled or converted.

## Peer benchmarking

`GET /api/companies/{company_id}/benchmark?statement_basis=consolidated&peer_ids=ID1&peer_ids=ID2&financial_year=FY2025` compares explicitly selected companies for an exact annual fiscal period, matching period start/end, statement basis, metric unit/currency, and source-input unit/currency/basis. Invalid, unavailable, missing, or incompatible peer values are excluded with reasons. The API includes each eligible peer's metric evidence, periods, source observation references, publisher, and source URL where available. A descriptive median is returned only with at least two compatible peers; otherwise the result is `insufficient_data` with counts and exclusions. User-selected peers are not claimed to represent an industry or broader market. Numeric peer differences are descriptive and are not assigned a materiality label.

## Reports

- `GET /api/companies/{company_id}/report?statement_basis=consolidated&format=json` returns company and period details, source register, M3 metrics, M4A assessments, insights, missing-data disclosures, selected limitations, and optional peer comparison when `peer_ids` are supplied.
- `GET /api/companies/{company_id}/report?statement_basis=consolidated&format=csv` downloads a metric-level CSV containing values/status, formulas, periods, units, and source/observation IDs. JSON is the complete analyst report; CSV is a flattened metric export.

Reports use current stored source-backed data. No source document is fetched or independently verified by report generation. The frontend offers both exports for a selected company and can include the selected peer group in JSON.

## Import requirements

Use the documented CSV contract and `python -m finsight.cli validate` / `ingest` commands. Only source-backed filing data with traceable publisher, source URL, retrieval date, reported period, basis, unit, currency, original reported label, and standardized line-item ID is accepted. `source_publication_date` is optional when available. Any row error rejects the whole batch before company, source, or observation registration. Existing company/source conflicts and duplicate keys fail the transaction; valid existing records are never overwritten. Warnings and manual-review findings are retained. Arbitrary PDF parsing is not supported; values must be transcribed or extracted with an independently reviewed process before the contract CSV is submitted.

## Persistence and recovery

Local development uses SQLite at `FINSIGHT_DATABASE_PATH` (default `data/finsight.sqlite3`). Schema bootstrap is versioned with `PRAGMA user_version`; unsupported future versions fail clearly. SQLite foreign keys and WAL mode are enabled. `FINSIGHT_REQUIRE_PERSISTENT_STORAGE=1` requires an absolute path and rejects `:memory:`, `/tmp`, and `/var/tmp` paths so a production process cannot accidentally accept the local default or a temporary database. The flag must only be enabled after setting `FINSIGHT_DATABASE_PATH` to a durable mounted volume.

Create a consistent backup with `PYTHONPATH=src python -m finsight.cli db-backup --db /var/data/finsight.sqlite3 --output /var/data/backups/finsight.sqlite3` and check it with `PYTHONPATH=src python -m finsight.cli db-verify --db /var/data/backups/finsight.sqlite3`. Restore a verified backup to a new destination with `PYTHONPATH=src python -m finsight.cli db-restore --backup /var/data/backups/finsight.sqlite3 --db /var/data/finsight-restored.sqlite3`; existing files are never overwritten. Keep backups outside the primary database file and test restore procedures before onboarding statements. Existing hosted Render service configuration uses ephemeral `/tmp` storage and has not been upgraded or verified with a persistent disk. Durable production storage remains an operator configuration requirement; see [`deployment.md`](deployment.md).

## Boundaries

There are no verified company records in the current project deployment. Unit/API tests use clearly test-only synthetic observations in temporary databases. No M4 peer result, insight, or report is a real company analysis until source-backed records are onboarded. The provisional M4A thresholds are documented separately in [`financial-risk-analysis.md`](financial-risk-analysis.md).
