# Planned financial metrics and conventions

No metrics are calculated in milestone M1. This document records intended baseline formulas; configurable conventions and precise input mappings will be implemented and tested in M3. All values in a ratio must use consistent periods, currencies, and statement basis.

## Growth and profitability

- Revenue growth = current-year revenue / prior-year revenue − 1. Undefined for missing or zero prior revenue; negative bases require explicit interpretation.
- Revenue CAGR = (ending revenue / starting revenue)^(1 / number of years) − 1. Requires positive endpoints and matching statement basis.
- EBITDA margin = EBITDA / revenue; EBITDA definition and adjustments must be recorded because reported definitions can differ.
- EBIT margin = EBIT / revenue.
- Net profit margin = net income / revenue.
- ROA = net income / average total assets.
- ROE = net income / average total equity.
- ROCE = EBIT / average capital employed. Initial convention: capital employed = total assets − current liabilities; review against data availability and chosen analytical convention.

## Cash flow

- Operating cash flow (OCF) = reported net cash from operating activities.
- Free cash flow (FCF) = OCF − capital expenditure, with capex normalised as a positive outflow magnitude.
- OCF / net income = OCF / net income; undefined for zero or missing net income. Negative net income should be flagged for interpretation.
- OCF versus net income divergence = OCF − net income (absolute currency amount); any scaled ratio needs a separately documented denominator convention.
- OCF year-over-year change = current OCF − prior OCF in currency; percentage change is only meaningful under a documented positive, non-zero base convention.

## Working capital

Use average opening and closing balance-sheet values when available, and period days (calendar days for the reported period).

- Receivable days = average trade receivables / revenue × period days.
- Inventory days = average inventory / cost of goods sold × period days.
- Payable days = average trade payables / purchases × period days. If purchases are unavailable, do not substitute COGS silently; an explicitly selected proxy must be disclosed.
- Cash conversion cycle = receivable days + inventory days − payable days.

## Leverage and risk

- Total debt = standardised short-term and long-term borrowings; lease liabilities require an explicit policy.
- Net debt = total debt − cash and cash equivalents, when both inputs are available.
- Debt-to-equity = total debt / total equity; negative or zero equity requires a warning and convention-specific handling.
- Interest coverage = EBIT / finance costs, after normalising finance cost sign and confirming the reported definition.
- Net debt / EBITDA = net debt / EBITDA only when the required inputs exist and EBITDA is positive and meaningful.

For all formulas, missing inputs produce unavailable results, not zero. Invalid or negative denominators are surfaced with validation context. Ratios are not interpreted as proof of fraud or distress. Use matching periods and standalone/consolidated basis; document exceptions and source definitions.
