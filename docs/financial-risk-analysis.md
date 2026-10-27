# M4A financial trend and risk analysis

M4A applies explainable screening rules to calculated M3 `MetricResult` values. It does not duplicate the metric formulas, change M3 results, store assessments in SQLite, or make company-level conclusions. Each assessment returns a status, the configured comparison, periods, observed metric values, threshold values, source observation references, and a separate interpretation.

## Assessment statuses

- `flagged`: the configured screening condition was met in the assessment window.
- `not_flagged`: all required compatible data was available and the condition was not met. This does not establish the absence of financial risk.
- `insufficient_data`: one or more required metrics are missing, unavailable, or do not cover contiguous annual periods.
- `invalid_input`: an M3 metric is invalid, or the comparison contains incompatible periods, units, or currencies.

Only one company and statement basis are analyzed at a time. Cross-year comparisons require adjacent fiscal years whose reporting periods also touch. Values are not zero-filled, converted, rescaled, or compared across gaps. An unavailable or invalid M3 result is never treated as a calculated value. OCF/net-income screening is evaluated only when net income is positive; zero net income remains the M3 invalid input case, and negative net income is not screened by that rule.

## Provisional default rules

Defaults are in [`../config/financial_risk_thresholds.toml`](../config/financial_risk_thresholds.toml). The `meta.version` value accompanies every assessment. Each rule's window ends at the latest fiscal year in the calculated metric set. Thresholds are configurable screening heuristics, not empirically calibrated cutoffs or universal accounting standards.

| Rule | Configured condition | Required history |
|---|---|---|
| Revenue decline | Revenue growth is below `0` in each of 2 consecutive comparisons. | 2 calculated growth periods, each from adjacent fiscal years. |
| Profitability deterioration | Each margin is assessed separately. EBITDA, EBIT, or net-profit margin has fallen by at least `0.05` ratio units (5 percentage points) from 2 years earlier. | 3 contiguous calculated annual margins. |
| Weak cash conversion | OCF/net income is below `0.8` in each of 2 consecutive years, with positive net income in both. | 2 contiguous calculated ratios with net-income evidence. |
| Net debt / EBITDA | The latest value is greater than `3.0x`. | Latest calculated ratio. |
| Debt / equity | The latest value is greater than `2.0x`. | Latest calculated ratio. |
| Interest coverage | The latest value is below `1.5x`. | Latest calculated ratio. |
| Receivables days increase | Receivable days increase by at least `15` days in each of 2 consecutive annual comparisons. | 3 contiguous calculated annual values. |
| Inventory days increase | Inventory days increase by at least `15` days in each of 2 consecutive annual comparisons. | 3 contiguous calculated annual values. |
| Negative free cash flow | Free cash flow is below zero in 2 consecutive years. | 2 contiguous calculated annual values in matching units and currency. |

Revenue growth and ratio comparisons use strict `<` or `>` as stated. Margin and working-capital changes use inclusive `>=`. Free cash flow uses the sign boundary zero; its threshold is constrained to zero because its amount unit varies across records. A metric exactly at a strict threshold does not trigger that rule.

## Facts, interpretation, and evidence

The `fact` field describes the observed M3 values and periods. The `interpretation` field states only that a configured screen was met, not met, or could not be evaluated. Triggered flags are prompts for analyst review; they are not proof of fraud, insolvency, financial distress, or an investment recommendation. The API returns the M3 metric evidence, including input observation IDs and source IDs where available, and the actual thresholds used.

The read-only endpoint is `GET /api/companies/{company_id}/analysis?statement_basis=consolidated`. It calculates M3 metrics once for the request and derives assessments from those values. No assessment is persisted. The dashboard displays triggered findings and their evidence; other rule outcomes remain available in the expanded checks list.

## Limitations

Rules operate on annual M3 metrics and standardized line-item mappings. They do not adjust for seasonality, industry, one-off events, accounting-policy differences, or lease-liability mappings. Thresholds require analyst review before production use. The current API has no company records, so company-level behavior and the live analysis endpoint have not been verified end to end. Deployment checks do not verify the underlying financial statements or figures.
