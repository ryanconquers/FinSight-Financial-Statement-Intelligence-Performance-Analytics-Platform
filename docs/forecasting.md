# M5 forecasting and scenario analysis

Forecasting is a deterministic, Decimal-based driver model in `src/finsight/forecasting`. It runs only from source-backed observations belonging to the requested company and statement basis. Forecast assumptions and calculated results are stored in SQLite with a methodology version, source observation IDs, source IDs, a baseline fingerprint, creation/update timestamps, and immutable revision snapshots. Updating a saved forecast creates a new revision; earlier revisions remain retrievable. Reads compare the stored fingerprint with current baseline inputs and disclose when those inputs changed.

## Baseline and assumptions

Choose a valid annual fiscal period (`FYYYYY`) with one consistent period end, statement basis, currency, and unit. It must span 350–380 inclusive days and end in the fiscal year named. Revenue must exist and be positive because ordinary percentage growth is not valid for zero or negative baselines. No historical periods or values are imputed. The baseline displays original reported line-item values and provenance references; historical values and forecasts have separate `period_type` labels. Gaps and invalid historical annual periods are listed explicitly.

Create requests use decimal fractions, not percentages: `0.08` means 8%. The API `revenue_growth` input is an array with one assumption per forecast year; the UI accepts a single value (repeated across the horizon) or an annual comma-separated series. The horizon is 1–10 years (default five). Supported assumptions are:

- `gross_margin`, `ebitda_margin`, `opex_percent_revenue`, `da_percent_revenue`, `tax_rate`, and `capex_percent_revenue`.
- `interest_expense`, one same-currency amount or one amount per forecast year.
- Optional `receivable_days`, `inventory_days`, and `payable_days` (each 0–1000).

Where source-backed baseline line items support it, gross margin, EBITDA margin, operating-expense ratio, D&A ratio, capex ratio, interest, and working-capital days are derived and marked in the stored assumptions. User inputs override derivable values. A baseline gross margin, EBITDA margin, and operating-expense ratio must reconcile. Currency and unit are inherited from the baseline; conversions are rejected.

## Formulas and missing data

- Revenue = previous revenue × (1 + that year’s revenue-growth assumption).
- Gross profit = revenue × gross-margin assumption; COGS = revenue − gross profit.
- Operating expenses = gross profit − EBITDA. EBITDA is revenue × EBITDA margin when supplied, or gross profit − operating expenses when the expense ratio is supplied.
- D&A = revenue × D&A ratio; EBIT = EBITDA − D&A.
- EBT = EBIT − interest expense. Tax expense = max(EBT, 0) × tax rate; a loss does not assume a tax benefit. Net income = EBT − tax expense.
- Receivables = revenue × receivable days / 365; inventory and payables = COGS × their respective days / 365. Net operating working capital = receivables + inventory − payables; change is forecast NWC less prior-year NWC. The first forecast-year change requires compatible baseline balances.
- Simplified operating cash flow = net income + D&A − change in NWC. It assumes no other non-cash adjustments and is unavailable if required components are missing.
- Unlevered FCF = EBIT − max(EBIT, 0) × tax rate + D&A − capex − change in NWC. This is distinct from M3 levered free cash flow and does not use net income as a NOPAT substitute.

Unsupported or missing dependencies stay `null` and include an `unavailable` explanation. Reported source values and calculated forecasts are not conflated. A simplified forecast may not reconcile to a complete filed statement where detailed tax, financing, non-cash, or working-capital components are absent.

## Scenarios and sensitivity

Base uses the user assumptions. If Bull/Bear overrides are omitted, the engine visibly records provisional illustrative defaults: Bull adds 2 percentage points to annual revenue growth and 1 point to available gross/EBITDA margins; Bear subtracts the same. These editable defaults are not calibrated predictions and are not probabilities. Scenarios use the same baseline and formulas; scenario-specific assumptions are saved.

Sensitivity accepts 1–11 revenue-growth values and 1–11 EBITDA-margin values, maximum 121 combinations. Each cell reruns the same engine, reports its input assumptions and projected periods, and does not mutate the saved forecast. The UI offers a compact 3×3 set around the entered Base values.

## API

All JSON routes use the existing `data`/`meta` envelope and validation errors use the existing error envelope. FastAPI OpenAPI documents typed create/update/sensitivity request shapes.

- `POST /api/companies/{company_id}/forecasts?statement_basis=consolidated` — create and save Base/Bull/Bear forecast (`baseline_year`, `forecast_horizon`, assumptions, optional unit/currency assertion, optional scenario overrides); returns 201.
- `GET /api/companies/{company_id}/forecasts` and `GET .../forecasts/{forecast_id}` — list or retrieve saved forecasts. Company ID is checked on every route. Detail includes whether baseline inputs changed.
- `PUT .../forecasts/{forecast_id}` — replace assumptions and save a new revision.
- `PUT .../forecasts/{forecast_id}/scenarios` — replace scenario assumptions and save a new revision.
- `GET .../forecasts/{forecast_id}/revisions` and `GET .../revisions/{revision}` — list and retrieve immutable version snapshots.
- `POST .../forecasts/{forecast_id}/sensitivity` — run a bounded, read-only sensitivity grid.
- `GET .../forecasts/{forecast_id}/actual-vs-forecast` — return historical actual rows and forecast rows with missing historical periods and stale-input disclosure.
- `GET .../forecasts/{forecast_id}/export?format=json|csv` — export stored assumptions/results and line-level scenario rows.

The frontend has baseline, horizon, currency/unit, annual growth, margin, operating expense, tax, D&A, capex, interest, and optional working-capital inputs. Bull/Bear growth and margins are editable; advanced JSON can override any supported scenario assumptions independently. It provides generate/update, retrieve, revision history, sensitivity and export controls. Actual and forecast rows are labeled separately. An empty company list leaves forecasts unavailable without placeholder values.

## Persistence and limitations

Schema version 2 adds `forecasts` and `forecast_revisions`; the v1-to-v2 migration is transactional. Local setup and SQLite backup/restore procedures are in [`database-schema.md`](database-schema.md) and [`m4-analysis.md`](m4-analysis.md). Production durability is not provided by Render’s current `/tmp` database. A persistent disk, persistent database path, `FINSIGHT_REQUIRE_PERSISTENT_STORAGE=1`, backup/recovery drill, and deployment verification are still required before onboarding records. SQLite with WAL is intended for one API instance on a supported local durable volume; no PostgreSQL backend is provided.

The model does not fetch filings, produce statistical predictions, infer probabilities, model detailed expense categories, debt schedules, tax-loss carryforwards, financing waterfalls, or stock valuation. Source data and illustrative assumptions are not independently verified. No company forecast has been compared with future actual results. Automated tests use clearly synthetic fixtures in temporary databases only.
