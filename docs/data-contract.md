# Financial observation data contract (M1)

The starter CSV contract is demonstrated in `data/synthetic/financial_observations.csv`. One row represents one reported line item for one company, fiscal period, statement basis, and statement type.

| Field | Required | Meaning |
|---|---:|---|
| `record_origin` | Yes | `synthetic` for test fixtures; later imports use a documented source-backed origin. |
| `company_id` | Yes | Stable internal company identifier, not a display name. |
| `company_name` | Yes | Company name as represented in the master data. |
| `ticker` | No | Exchange ticker where available. |
| `financial_year` | Yes | Fiscal-year label, e.g. `FY2025`; convention must be consistent. |
| `period_start` | Yes | Start date of the reported period, ISO `YYYY-MM-DD`. |
| `period_end` | Yes | End date of the reported period, ISO `YYYY-MM-DD`. |
| `statement_basis` | Yes | `standalone` or `consolidated`; never mix silently. |
| `statement_type` | Yes | `income_statement`, `balance_sheet`, or `cash_flow_statement`. |
| `line_item_id` | Yes | Standardised identifier from the project's line-item dictionary. |
| `reported_label` | Yes | Original label from the company source. |
| `value` | Yes | Numeric reported value; `0` is distinct from missing. Do not encode missing as zero. |
| `unit` | Yes | Explicit scale such as `INR_crore`; scale must be consistent within a statement. |
| `currency` | Yes | ISO currency code, for example `INR`. |
| `source_id` | Yes | Source registry identifier; fixture uses `SYNTHETIC_TEST_ONLY`. |
| `source_url` | No | URL for an external source; blank for synthetic fixtures. |
| `retrieved_at` | Yes | Retrieval or fixture-generation date, ISO date. |
| `is_synthetic` | Yes | Boolean marker; must be true for this fixture. |

This is a starter import contract, not a complete taxonomy. Future imports should register companies and sources separately and validate foreign keys before loading observations. Do not load synthetic values into a dataset represented as real disclosures.
