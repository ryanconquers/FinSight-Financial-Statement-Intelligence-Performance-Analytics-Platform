# Database schema

The authoritative DDL is `src/finsight/db/schema.sql`. SQLite initialization enables foreign keys and WAL mode, applies a 30-second busy timeout, and tracks the installed schema with `PRAGMA user_version` (current version 1). Existing databases with version 0 are bootstrapped against the idempotent initial schema; a database declaring a future version is rejected. Incremental future schema changes must add explicit migrations and increment `SCHEMA_VERSION`.

## Tables and relationships

- `companies`: stable company identifiers, name, ticker, and reporting currency.
- `sources`: publisher, URL, optional publication date, retrieval date, and synthetic-data marker. The CSV importer preserves publication dates when supplied and registers `is_synthetic = 0`.
- `financial_observations`: one reported line item per company, period, statement basis, and statement type. A unique constraint prevents duplicate observation keys.
- `processing_logs`: one row per successful import transaction, or a separate failed-attempt record after rollback.
- `validation_results`: errors, warnings, and manual-review findings associated with a processing run.
- `calculated_metrics`: reserved; current M3/M4 calculations are performed at request time and are not persisted.

The importer registers company/source rows and observations inside one transaction only when the entire CSV has no validation errors. A mixed-validity file is rejected before any company, source, or observation is registered. Duplicate or conflicting existing records fail without overwriting data. A database write failure rolls back registrations, observations, validation results, and success log together; the importer then attempts to record a failed run. Missing CSV values are rejected and never coerced to zero. A numeric zero remains a valid amount.

SQLite's `NUMERIC` affinity does not impose currency or scale conversions. The importer checks consistency and reports mismatches but does not convert units, reconcile statements, or enforce a complete line-item taxonomy. `FINSIGHT_DATABASE_PATH` selects the database file; configure it to a durable mounted volume for production. Set `FINSIGHT_REQUIRE_PERSISTENT_STORAGE=1` to reject ephemeral `/tmp` and `/var/tmp` paths. The current Render service is still configured for ephemeral `/tmp` storage; a persistent disk and backups have not been provisioned or verified. Use the online SQLite backup and integrity commands documented in [`m4-analysis.md`](m4-analysis.md).
