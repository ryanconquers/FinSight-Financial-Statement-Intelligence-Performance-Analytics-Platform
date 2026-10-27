# Database schema

The authoritative DDL is `src/finsight/db/schema.sql`. M2 opens SQLite with foreign-key enforcement enabled and initializes this schema before importing.

## Tables and relationships

- `companies`: stable company identifiers, name, ticker, and reporting currency.
- `sources`: publisher, URL, retrieval date, and synthetic-data marker. M2 accepts only source-backed records and registers `is_synthetic = 0`.
- `financial_observations`: one reported line item per company, period, statement basis, and statement type. A unique constraint prevents duplicate observation keys.
- `processing_logs`: one row per successful import transaction, or a separate failed-attempt record after rollback.
- `validation_results`: errors, warnings, and manual-review findings associated with a processing run.
- `calculated_metrics`: reserved for M3; no calculations are performed in M2.

The importer registers company/source rows and valid observations inside one transaction. For a mixed-validity file, validated rows are imported together and the report identifies every invalid row. A database write failure rolls back the registrations, observations, validation results, and success log together; the importer then attempts to record a failed run. Missing CSV values are rejected and never coerced to zero. A numeric zero remains a valid amount.

SQLite's `NUMERIC` affinity does not impose currency or scale conversions. M2 checks consistency and reports mismatches but does not convert units, reconcile statements, or enforce a complete line-item taxonomy.
