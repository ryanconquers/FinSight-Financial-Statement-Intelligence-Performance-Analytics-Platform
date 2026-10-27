# Initial database schema (M1)

The authoritative DDL is `src/finsight/db/schema.sql`. The schema uses SQLite-compatible types, explicit foreign keys, ISO date text, and numeric values. These choices can be mapped to PostgreSQL types later.

## Tables and relationships

- `companies` has a stable primary key; observations reference it.
- `sources` stores data provenance; observations and processing logs reference it where applicable.
- `financial_observations` stores one source-reported line item per company, period, statement basis, and statement type. A unique constraint prevents duplicate keys.
- `validation_results` records check name, severity, message, and optional observation or run reference.
- `calculated_metrics` stores calculated values with formula version and traceable input references.
- `processing_logs` records run-level input and outcome details.

`statement_basis` is constrained to `standalone` or `consolidated`; currencies and units are explicit text fields so the importer can enforce a controlled vocabulary. Missing values are not coerced to zero. A numeric zero is valid and remains distinguishable from an absent/NULL value.

Foreign-key enforcement must be enabled by each SQLite connection. Reconciliation rules and line-item taxonomy are not enforced in this initial DDL; they belong to the validation and standardisation milestones.
