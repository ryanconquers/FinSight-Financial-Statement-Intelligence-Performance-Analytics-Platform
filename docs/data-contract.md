# Financial observation CSV contract

One row contains one source-reported line item for one company, financial year, statement basis, and statement type. Import uses the exact column names below; headers are case-sensitive. Keep one reporting currency and consistent units for each company's comparable line item across periods.

| Field | Required | Meaning |
|---|---:|---|
| `company_id` | Yes | Stable internal company identifier. |
| `company_name` | Yes | Company name as shown in the source/master data. |
| `ticker` | No | Exchange ticker when available. |
| `financial_year` | Yes | Fiscal-year label in `FYYYYY` form, such as `FY2025`. Its year must match `period_end`. |
| `period_start`, `period_end` | Yes | Inclusive reporting-period dates, ISO `YYYY-MM-DD`. Annual periods outside 350–380 days need manual review. |
| `statement_basis` | Yes | Exactly `standalone` or `consolidated`; never mix silently. |
| `statement_type` | Yes | `income_statement`, `balance_sheet`, or `cash_flow_statement`. |
| `line_item_id` | Yes | Standardised line-item identifier. Retain the source wording in `reported_label`. |
| `reported_label` | Yes | Original label from the disclosure. |
| `value` | Yes | Finite numeric amount. A literal `0` is valid; blank means unavailable and is rejected for that observation. |
| `unit` | Yes | Explicit scale, for example `INR_crore`; do not silently rescale values. |
| `currency` | Yes | Uppercase three-letter ISO 4217 currency code. |
| `source_id` | Yes | Stable source registry identifier. |
| `source_publisher` | Yes | Publisher or filing authority named by the source. |
| `source_url` | Yes | Absolute HTTP/HTTPS URL to the underlying disclosure. |
| `retrieved_at` | Yes | Date the source file was retrieved, ISO `YYYY-MM-DD`. |
| `is_synthetic` | Yes | Must be `false` or `0`. Synthetic records and source labels indicating synthetic data are rejected. |

One accepted header layout, with the optional `ticker` column included, is:

```csv
company_id,company_name,ticker,financial_year,period_start,period_end,statement_basis,statement_type,line_item_id,reported_label,value,unit,currency,source_id,source_publisher,source_url,retrieved_at,is_synthetic
```

Leading/trailing whitespace in required fields is reported as an error rather than silently trimmed. Optional columns outside `ticker` are rejected to prevent accidental data loss. Extra information should be preserved in source notes and added to the contract deliberately.

The importer registers company and source metadata from these fields, enables SQLite foreign keys, and writes observations only after row validation. Rows with errors are omitted and explicitly counted in the report; other valid rows may be imported as one transaction with status `partial_import_with_validation_errors`. Database failures roll back every write from the file.
