# Financial metrics and calculation conventions

M3 implements these calculations in `src/finsight/metrics/calculator.py`. They are pure functions over typed observations; SQLite access is isolated in `metrics/repository.py`. Results contain the formula/version, reporting period, status, source-observation IDs and source IDs.

## Inputs and shared rules

Line-item IDs below are read from the named statement:

| Line item | Statement |
|---|---|
| `revenue`, `ebitda`, `ebit`, `net_income`, `finance_costs`, `cost_of_goods_sold`, `purchases` | `income_statement` |
| `total_assets`, `current_liabilities`, `total_equity`, `short_term_borrowings`, `long_term_borrowings`, `cash_and_cash_equivalents`, `trade_receivables`, `inventory`, `trade_payables` | `balance_sheet` |
| `operating_cash_flow`, `capital_expenditure` | `cash_flow_statement` |

A metric uses one company and one statement basis. Inputs must have compatible reporting periods, currency, and unit; the engine never converts or silently rescales. Adjacent-year calculations require the prior reporting period to end the day before the current one. Return and days metrics require the prior-year closing balance as the current period's opening balance. Missing inputs return `unavailable`; zero or invalid denominators, mismatched periods, and incompatible units/currencies return `invalid_input`. Missing is never treated as zero.

Ratios are returned as decimal fractions (for example `0.15` means 15%) with unit `ratio`; the UI formats percentage metrics for display. Amount results retain the input unit and currency. Days use calendar days in the inclusive period. Values are `Decimal` during calculation and serialized as decimal strings.

## Growth and profitability

- Revenue growth = current revenue / adjacent prior-year revenue − 1. Both values must be positive.
- Revenue CAGR = (latest available revenue / earliest available revenue) ** (1 / elapsed FY years) − 1. Calculated once over the available series, on its latest financial year; endpoints must be positive and use matching basis, unit, and currency.
- EBITDA margin = reported EBITDA / revenue. EBITDA is not reconstructed or adjusted by FinSight.
- EBIT margin = EBIT / revenue.
- Net profit margin = net income / revenue.
- ROA = net income / average total assets.
- ROE = net income / average total equity.
- ROCE = EBIT / average capital employed, where capital employed = total assets − current liabilities.

Margin revenue and average return denominators must be positive. Negative earnings remain valid numerators.

## Cash flow

- Operating cash flow = reported net cash from operating activities.
- Free cash flow = operating cash flow − absolute capital-expenditure outflow.
- OCF / net income = operating cash flow / net income. Zero net income is invalid; a negative net-income denominator is calculated with a caution warning.
- OCF vs net income divergence = operating cash flow − net income, in currency amount.
- OCF year-over-year change = current OCF − adjacent prior-year OCF, in currency amount (not percent).

## Working capital

- Receivable days = average trade receivables / revenue × inclusive period days.
- Inventory days = average inventory / cost of goods sold × inclusive period days.
- Payable days = average trade payables / purchases × inclusive period days. COGS is not substituted for missing purchases.
- Cash conversion cycle = receivable days + inventory days − payable days.

Flow denominators must be positive; average working-capital balances must not be negative. The code does not infer purchases or alter accounting classifications.

## Leverage and risk

- Total debt = short-term borrowings + long-term borrowings. Lease liabilities are excluded unless mapped into those standardized inputs by an analyst.
- Net debt = total debt − cash and cash equivalents.
- Debt-to-equity = total debt / total equity; equity must be positive.
- Interest coverage = EBIT / absolute finance costs; zero finance costs are invalid.
- Net debt / EBITDA = net debt / EBITDA; EBITDA must be positive.

Unusual results and negative earnings are context for review, not proof of misconduct or distress. No metrics are saved to `calculated_metrics` yet; the existing table is unchanged. The API calculates current results from source observations and returns their input provenance.
