"""Pure Decimal forecasting with explicit assumptions and missing-data states."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from finsight.metrics.models import FinancialObservation

FORECAST_VERSION = "finsight-driver-forecast-v1"
_MAX_HORIZON = 10
_PERCENT_KEYS = {"tax_rate", "gross_margin", "ebitda_margin", "opex_percent_revenue", "da_percent_revenue", "capex_percent_revenue"}


def _decimal(value: Any, name: str, *, minimum: Decimal | None = None, maximum: Decimal | None = None) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a finite decimal number.") from exc
    if not number.is_finite():
        raise ValueError(f"{name} must be a finite decimal number.")
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name} must be no more than {maximum}.")
    return number


def _annual(observations: list[FinancialObservation], year: str, basis: str) -> dict[tuple[str, str], FinancialObservation]:
    entries = [item for item in observations if item.financial_year == year and item.statement_basis == basis]
    if not entries:
        raise ValueError(f"No historical observations are available for {year} on the {basis} basis.")
    periods = {(item.period_start, item.period_end) for item in entries}
    if len(periods) != 1 or (entries[0].period_end - entries[0].period_start).days + 1 not in range(350, 381):
        raise ValueError(f"Historical baseline {year} is not one compatible annual reporting period.")
    if entries[0].period_end.year != int(year[2:]):
        raise ValueError(f"Historical baseline {year} does not end in its labeled fiscal year.")
    if len({(item.currency, item.unit) for item in entries}) != 1:
        raise ValueError("Historical baseline mixes currencies or financial units.")
    indexed: dict[tuple[str, str], FinancialObservation] = {}
    for item in entries:
        key = (item.statement_type, item.line_item_id)
        if key in indexed:
            raise ValueError(f"Historical baseline contains duplicate input {item.line_item_id}.")
        indexed[key] = item
    return indexed


def _get(index: dict[tuple[str, str], FinancialObservation], statement: str, item: str) -> FinancialObservation | None:
    return index.get((statement, item))


def _value(index: dict[tuple[str, str], FinancialObservation], statement: str, item: str) -> Decimal | None:
    source = _get(index, statement, item)
    return source.value if source else None


def _actual_period(index: dict[tuple[str, str], FinancialObservation], year: str, *, unavailable: list[dict[str, str]] | None = None) -> dict[str, Any]:
    observations = list(index.values())
    anchor = observations[0]
    revenue = _value(index, "income_statement", "revenue")
    cogs = _value(index, "income_statement", "cost_of_goods_sold")
    reported = {item.line_item_id: str(item.value) if item.value is not None else None for item in observations}
    gross_profit = revenue - abs(cogs) if revenue is not None and cogs is not None else None
    ebitda = Decimal(reported["ebitda"]) if reported.get("ebitda") is not None else None
    ebit = Decimal(reported["ebit"]) if reported.get("ebit") is not None else None
    net_income = Decimal(reported["net_income"]) if reported.get("net_income") is not None else None
    values: dict[str, str | None] = {
        "revenue": str(revenue) if revenue is not None else None,
        "gross_profit": str(gross_profit) if gross_profit is not None else None,
        "gross_margin": str(gross_profit / revenue) if gross_profit is not None and revenue is not None and revenue > 0 else None,
        "cost_of_goods_sold": str(abs(cogs)) if cogs is not None else None,
        "ebitda": reported.get("ebitda"),
        "ebitda_margin": str(ebitda / revenue) if ebitda is not None and revenue is not None and revenue > 0 else None,
        "ebit": reported.get("ebit"),
        "ebit_margin": str(ebit / revenue) if ebit is not None and revenue is not None and revenue > 0 else None,
        "net_income": reported.get("net_income"),
        "net_profit_margin": str(net_income / revenue) if net_income is not None and revenue is not None and revenue > 0 else None,
        "operating_expenses": str(gross_profit - ebitda) if gross_profit is not None and ebitda is not None else reported.get("operating_expenses"),
        "depreciation_amortization": str(ebitda - ebit) if ebitda is not None and ebit is not None else reported.get("depreciation_amortization"),
        "interest_expense": reported.get("finance_costs"),
        "tax_expense": reported.get("tax_expense", reported.get("income_tax_expense")),
        "capital_expenditure": reported.get("capital_expenditure"),
        "operating_cash_flow": reported.get("operating_cash_flow"),
        "accounts_receivable": reported.get("trade_receivables"),
        "inventory": reported.get("inventory"),
        "accounts_payable": reported.get("trade_payables"),
        "unlevered_free_cash_flow": None,
    }
    if all(values.get(key) is not None for key in ("accounts_receivable", "inventory", "accounts_payable")):
        values["net_operating_working_capital"] = str(Decimal(str(values["accounts_receivable"])) + Decimal(str(values["inventory"])) - Decimal(str(values["accounts_payable"])))
    else:
        values["net_operating_working_capital"] = None
    reasons = list(unavailable or [])
    reasons.extend({"metric": key, "reason": "Required source-reported input or compatible components are unavailable for this actual period."} for key, value in values.items() if value is None)
    return {
        "financial_year": year, "period_type": "actual", "period_start": anchor.period_start.isoformat(),
        "period_end": anchor.period_end.isoformat(), "currency": anchor.currency, "unit": anchor.unit,
        "values": values, "reported_line_items": reported,
        "source_observation_ids": sorted(item.observation_id for item in observations),
        "source_ids": sorted({item.source_id for item in observations}), "unavailable": reasons,
    }


def _assumptions(raw: dict[str, Any], horizon: int, *, baseline: dict[tuple[str, str], FinancialObservation], year: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("assumptions must be an object.")
    allowed = {"revenue_growth", "gross_margin", "ebitda_margin", "opex_percent_revenue", "da_percent_revenue", "tax_rate", "capex_percent_revenue", "receivable_days", "inventory_days", "payable_days", "interest_expense"}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Unsupported assumptions: {', '.join(sorted(unknown))}.")
    if "revenue_growth" not in raw:
        raise ValueError("revenue_growth is required as a decimal fraction for each forecast year.")
    growth_values = raw["revenue_growth"]
    if not isinstance(growth_values, list) or len(growth_values) != horizon:
        raise ValueError("revenue_growth must be an array with one assumption per forecast year.")
    growth = [_decimal(value, f"revenue_growth[{i}]", minimum=Decimal("-0.99"), maximum=Decimal("5")) for i, value in enumerate(growth_values)]
    result: dict[str, Any] = {"revenue_growth": [str(value) for value in growth]}
    for key in _PERCENT_KEYS:
        value = raw.get(key)
        if value is None:
            result[key] = None
            continue
        minimum = Decimal("-1") if key == "gross_margin" else Decimal("-5") if key == "ebitda_margin" else Decimal("0")
        maximum = Decimal("1") if key in _PERCENT_KEYS else None
        result[key] = str(_decimal(value, key, minimum=minimum, maximum=maximum))
    if result.get("gross_margin") is None and _value(baseline, "income_statement", "revenue") not in (None, Decimal("0")):
        revenue = _value(baseline, "income_statement", "revenue")
        cogs = _value(baseline, "income_statement", "cost_of_goods_sold")
        if revenue is not None and cogs is not None and revenue > 0:
            result["gross_margin"] = str((revenue - abs(cogs)) / revenue)
    if result.get("ebitda_margin") is None:
        ebitda = _value(baseline, "income_statement", "ebitda")
        revenue = _value(baseline, "income_statement", "revenue")
        if ebitda is not None and revenue is not None and revenue > 0:
            result["ebitda_margin"] = str(ebitda / revenue)
    if result.get("opex_percent_revenue") is None and result.get("gross_margin") is not None and result.get("ebitda_margin") is not None:
        result["opex_percent_revenue"] = str(Decimal(result["gross_margin"]) - Decimal(result["ebitda_margin"]))
    elif result.get("opex_percent_revenue") is not None and result.get("gross_margin") is not None and result.get("ebitda_margin") is not None:
        if Decimal(result["gross_margin"]) - Decimal(result["opex_percent_revenue"]) != Decimal(result["ebitda_margin"]):
            raise ValueError("gross_margin, opex_percent_revenue, and ebitda_margin do not reconcile.")
    if result.get("da_percent_revenue") is None:
        ebitda = _value(baseline, "income_statement", "ebitda")
        ebit = _value(baseline, "income_statement", "ebit")
        revenue = _value(baseline, "income_statement", "revenue")
        if ebitda is not None and ebit is not None and revenue is not None and revenue > 0:
            result["da_percent_revenue"] = str((ebitda - ebit) / revenue)
    revenue = _value(baseline, "income_statement", "revenue")
    cogs = _value(baseline, "income_statement", "cost_of_goods_sold")
    if result.get("capex_percent_revenue") is None and revenue is not None and revenue > 0:
        capex = _value(baseline, "cash_flow_statement", "capital_expenditure")
        if capex is not None:
            result["capex_percent_revenue"] = str(abs(capex) / revenue)
    for key in ("receivable_days", "inventory_days", "payable_days"):
        if raw.get(key) is None:
            result[key] = None
        else:
            result[key] = str(_decimal(raw[key], key, minimum=Decimal("0"), maximum=Decimal("1000")))
    if revenue is not None and revenue > 0 and result["receivable_days"] is None:
        receivables = _value(baseline, "balance_sheet", "trade_receivables")
        if receivables is not None and receivables >= 0:
            result["receivable_days"] = str(receivables / revenue * Decimal("365"))
    if cogs is not None and cogs != 0:
        for key, item_id in (("inventory_days", "inventory"), ("payable_days", "trade_payables")):
            if result[key] is None:
                balance = _value(baseline, "balance_sheet", item_id)
                if balance is not None and balance >= 0:
                    result[key] = str(balance / abs(cogs) * Decimal("365"))
    interest = raw.get("interest_expense")
    if interest is not None:
        if isinstance(interest, list):
            if len(interest) != horizon:
                raise ValueError("interest_expense must be one amount or an array with one amount per forecast year.")
            result["interest_expense"] = [str(_decimal(value, f"interest_expense[{i}]")) for i, value in enumerate(interest)]
        else:
            value = str(_decimal(interest, "interest_expense"))
            result["interest_expense"] = [value] * horizon
    else:
        base_interest = _value(baseline, "income_statement", "finance_costs")
        result["interest_expense"] = [str(base_interest)] * horizon if base_interest is not None else None
    # Keep input provenance explicit when an assumption is derived from reported baseline values.
    result["derived_from_baseline"] = {
        key: key not in raw and result.get(key) is not None
        for key in ("gross_margin", "ebitda_margin", "opex_percent_revenue", "da_percent_revenue", "capex_percent_revenue", "receivable_days", "inventory_days", "payable_days", "interest_expense")
    }
    return result


def _forecast_scenario(
    company_id: str,
    basis: str,
    baseline_year: str,
    baseline: dict[tuple[str, str], FinancialObservation],
    assumptions: dict[str, Any],
    actual_history: list[dict[str, Any]],
) -> dict[str, Any]:
    revenue = _value(baseline, "income_statement", "revenue")
    if revenue is None:
        raise ValueError("Revenue baseline is missing; forecasts cannot be generated.")
    if revenue <= 0:
        raise ValueError("Revenue baseline must be positive for a percentage-growth forecast.")
    anchor = next(iter(baseline.values()))
    currency, unit = anchor.currency, anchor.unit
    result: list[dict[str, Any]] = []
    prior_revenue = revenue
    previous_nwc: Decimal | None = None
    ar = _value(baseline, "balance_sheet", "trade_receivables")
    inventory = _value(baseline, "balance_sheet", "inventory")
    ap = _value(baseline, "balance_sheet", "trade_payables")
    if ar is not None and inventory is not None and ap is not None:
        previous_nwc = ar + inventory - ap
    for index, growth_text in enumerate(assumptions["revenue_growth"], start=1):
        fiscal_year = f"FY{int(baseline_year[2:]) + index:04d}"
        growth = Decimal(growth_text)
        revenue = prior_revenue * (Decimal("1") + growth)
        row: dict[str, Any] = {
            "financial_year": fiscal_year, "period_type": "forecast", "currency": currency, "unit": unit,
            "revenue": str(revenue), "revenue_growth": str(growth), "gross_profit": None, "gross_margin": assumptions.get("gross_margin"), "cost_of_goods_sold": None,
            "operating_expenses": None, "ebitda": None, "ebitda_margin": None, "depreciation_amortization": None,
            "ebit": None, "interest_expense": None, "earnings_before_tax": None, "tax_expense": None,
            "net_income": None, "capital_expenditure": None, "accounts_receivable": None, "inventory": None,
            "accounts_payable": None, "net_operating_working_capital": None, "change_in_working_capital": None,
            "operating_cash_flow": None, "unlevered_free_cash_flow": None, "unavailable": [],
        }
        gm, em, da_ratio = assumptions.get("gross_margin"), assumptions.get("ebitda_margin"), assumptions.get("da_percent_revenue")
        opex_ratio = assumptions.get("opex_percent_revenue")
        if gm is not None:
            gross_profit = revenue * Decimal(gm)
            row.update(gross_profit=str(gross_profit), cost_of_goods_sold=str(revenue - gross_profit))
            if em is not None:
                if Decimal(em) > Decimal(gm):
                    raise ValueError("EBITDA margin cannot exceed gross margin when modeled operating expenses are non-negative.")
                ebitda = revenue * Decimal(em)
                if da_ratio is not None:
                    da = revenue * Decimal(da_ratio)
                    row.update(operating_expenses=str(gross_profit - ebitda), ebitda=str(ebitda), ebitda_margin=str(em), depreciation_amortization=str(da), ebit=str(ebitda - da))
                else:
                    row.update(operating_expenses=str(gross_profit - ebitda), ebitda=str(ebitda), ebitda_margin=str(em))
                    row["unavailable"].append({"metric": "ebit", "reason": "Depreciation and amortization assumption or compatible historical components are required."})
            elif opex_ratio is not None:
                ebitda = gross_profit - revenue * Decimal(opex_ratio)
                row.update(operating_expenses=str(revenue * Decimal(opex_ratio)), ebitda=str(ebitda), ebitda_margin=str(ebitda / revenue))
                if da_ratio is not None:
                    da = revenue * Decimal(da_ratio)
                    row.update(depreciation_amortization=str(da), ebit=str(ebitda - da))
                else:
                    row["unavailable"].append({"metric": "ebit", "reason": "Depreciation and amortization assumption is missing."})
            else:
                row["unavailable"].append({"metric": "ebitda", "reason": "Provide EBITDA margin or operating expense as a percentage of revenue."})
        else:
            row["unavailable"].append({"metric": "gross_profit", "reason": "Gross margin is unavailable; provide an assumption or compatible historical revenue and cost of goods sold."})
            if em is not None:
                ebitda = revenue * Decimal(em)
                row.update(ebitda=str(ebitda), ebitda_margin=str(em))
                if da_ratio is not None:
                    da = revenue * Decimal(da_ratio)
                    row.update(depreciation_amortization=str(da), ebit=str(ebitda - da))
                else:
                    row["unavailable"].append({"metric": "ebit", "reason": "Depreciation and amortization assumption or compatible historical components are required."})
        ebit = Decimal(row["ebit"]) if row["ebit"] is not None else None
        interest_values = assumptions.get("interest_expense")
        interest = Decimal(interest_values[index - 1]) if interest_values is not None else None
        if ebit is not None and interest is not None:
            ebt = ebit - interest
            tax_rate = assumptions.get("tax_rate")
            if tax_rate is not None:
                tax = max(ebt, Decimal("0")) * Decimal(tax_rate)
                row.update(interest_expense=str(interest), earnings_before_tax=str(ebt), tax_expense=str(tax), net_income=str(ebt - tax))
            else:
                row.update(interest_expense=str(interest), earnings_before_tax=str(ebt))
                row["unavailable"].append({"metric": "net_income", "reason": "Tax-rate assumption is missing; no tax benefit is assumed on losses."})
        else:
            row["unavailable"].append({"metric": "net_income", "reason": "Calculated EBIT and an interest-expense assumption are required."})
        capex_ratio = assumptions.get("capex_percent_revenue")
        if capex_ratio is not None:
            capex = revenue * Decimal(capex_ratio)
            row["capital_expenditure"] = str(capex)
        else:
            capex = None
            row["unavailable"].append({"metric": "capital_expenditure", "reason": "Capital expenditure assumption is missing."})
        days = {key: assumptions.get(key) for key in ("receivable_days", "inventory_days", "payable_days")}
        cogs = Decimal(row["cost_of_goods_sold"]) if row["cost_of_goods_sold"] is not None else None
        if all(value is not None for value in days.values()) and cogs is not None:
            ar = revenue * Decimal(days["receivable_days"]) / Decimal("365")
            inventory = cogs * Decimal(days["inventory_days"]) / Decimal("365")
            ap = cogs * Decimal(days["payable_days"]) / Decimal("365")
            nwc = ar + inventory - ap
            change_nwc = nwc - previous_nwc if previous_nwc is not None else None
            row.update(accounts_receivable=str(ar), inventory=str(inventory), accounts_payable=str(ap), net_operating_working_capital=str(nwc), change_in_working_capital=str(change_nwc) if change_nwc is not None else None)
            if previous_nwc is None:
                row["unavailable"].append({"metric": "change_in_working_capital", "reason": "Compatible baseline receivables, inventory, and payables are required."})
            previous_nwc = nwc
        else:
            change_nwc = None
            row["unavailable"].append({"metric": "working_capital", "reason": "Receivable, inventory, payable days and gross margin/COGS are required."})
        da = Decimal(row["depreciation_amortization"]) if row["depreciation_amortization"] is not None else None
        tax_rate = Decimal(assumptions["tax_rate"]) if assumptions.get("tax_rate") is not None else None
        net_income = Decimal(row["net_income"]) if row["net_income"] is not None else None
        if net_income is not None and da is not None and change_nwc is not None:
            row["operating_cash_flow"] = str(net_income + da - change_nwc)
        else:
            row["unavailable"].append({"metric": "operating_cash_flow", "reason": "Net income, D&A, and a compatible working-capital change are required by the simplified indirect method."})
        if ebit is not None and da is not None and tax_rate is not None and capex is not None and change_nwc is not None:
            operating_tax = max(ebit, Decimal("0")) * tax_rate
            fcf = ebit - operating_tax + da - capex - change_nwc
            row["unlevered_free_cash_flow"] = str(fcf)
        else:
            row["unavailable"].append({"metric": "unlevered_free_cash_flow", "reason": "EBIT, D&A, tax rate, capex, and baseline plus forecast working-capital change are required."})
        result.append(row)
        prior_revenue = revenue
    actual = next(item for item in actual_history if item["financial_year"] == baseline_year)
    return {"actual_baseline": actual, "actual_history": actual_history, "periods": result}


def build_forecast(
    observations: list[FinancialObservation], *, company_id: str, statement_basis: str,
    baseline_year: str, horizon: int, assumptions: dict[str, Any], scenarios: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate and calculate base/bull/bear forecasts without database I/O."""
    if not re.fullmatch(r"FY\d{4}", baseline_year):
        raise ValueError("baseline_year must use FY followed by four digits.")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= _MAX_HORIZON:
        raise ValueError(f"forecast_horizon must be an integer from 1 to {_MAX_HORIZON}.")
    owned = [item for item in observations if item.company_id == company_id and item.statement_basis == statement_basis]
    if not owned:
        raise ValueError("No source-backed observations exist for this company and statement basis.")
    baseline = _annual(owned, baseline_year, statement_basis)
    base = _assumptions(assumptions, horizon, baseline=baseline, year=baseline_year)
    scenario_input = scenarios or {}
    if set(scenario_input) - {"bull", "bear"}:
        raise ValueError("Only bull and bear scenario overrides are supported.")
    expanded: dict[str, dict[str, Any]] = {"base": base}
    for name, direction in (("bull", Decimal("1")), ("bear", Decimal("-1"))):
        overrides = scenario_input.get(name)
        if overrides is None:
            # Transparent, visible defaults. All generated assumptions are returned and saved.
            scenario_growth = [str(max(Decimal("-0.99"), min(Decimal("5"), Decimal(value) + direction * Decimal("0.02")))) for value in base["revenue_growth"]]
            scenario_values = {"revenue_growth": scenario_growth}
            if base.get("gross_margin") is not None:
                scenario_values["gross_margin"] = str(max(Decimal("-1"), min(Decimal("1"), Decimal(base["gross_margin"]) + direction * Decimal("0.01"))))
            if base.get("ebitda_margin") is not None:
                scenario_values["ebitda_margin"] = str(max(Decimal("-5"), min(Decimal("1"), Decimal(base["ebitda_margin"]) + direction * Decimal("0.01"))))
            overrides = scenario_values
        else:
            if not isinstance(overrides, dict):
                raise ValueError(f"{name} scenario assumptions must be an object.")
            merged = {key: value for key, value in base.items() if key != "derived_from_baseline"}
            merged.update(overrides)
            if "ebitda_margin" in overrides and "opex_percent_revenue" not in overrides:
                merged.pop("opex_percent_revenue", None)
            # Scenario vectors inherit base line-by-line unless explicitly replaced.
            if "revenue_growth" not in overrides:
                merged["revenue_growth"] = base["revenue_growth"]
            overrides = merged
        expanded[name] = _assumptions(overrides, horizon, baseline=baseline, year=baseline_year)
    actual_history: list[dict[str, Any]] = []
    actual_years = sorted({item.financial_year for item in owned if re.fullmatch(r"FY\d{4}", item.financial_year) and item.financial_year <= baseline_year})
    valid_actual_years: set[int] = set()
    for year in actual_years:
        period_observations = [item for item in owned if item.financial_year == year]
        first = period_observations[0]
        try:
            period_data = _annual(owned, year, statement_basis)
            valid_actual_years.add(int(year[2:]))
            actual_row = _actual_period(period_data, year)
        except ValueError as exc:
            actual_row = _actual_period({(item.statement_type, item.line_item_id): item for item in period_observations}, year, unavailable=[{"metric": "historical_period", "reason": str(exc)}])
        actual_history.append(actual_row)
    year_numbers = [int(year[2:]) for year in actual_years]
    missing_actual_years = [f"FY{year:04d}" for year in range(min(year_numbers), int(baseline_year[2:]) + 1) if year not in valid_actual_years] if year_numbers else []
    results = {name: _forecast_scenario(company_id, statement_basis, baseline_year, baseline, values, actual_history) for name, values in expanded.items()}
    fingerprint = forecast_input_fingerprint(owned, baseline_year, statement_basis)
    return {
        "methodology_version": FORECAST_VERSION,
        "company_id": company_id,
        "statement_basis": statement_basis,
        "baseline_year": baseline_year,
        "forecast_horizon": horizon,
        "assumptions": expanded,
        "scenario_adjustments_disclosure": "When not provided, Bull adds 2 percentage points to annual revenue growth and 1 percentage point to available gross/EBITDA margins; Bear subtracts the same. These are editable illustrative defaults, not predictions.",
        "created_from_observation_ids": sorted({item.observation_id for item in baseline.values()}),
        "created_from_source_ids": sorted({item.source_id for item in baseline.values()}),
        "historical_actuals": actual_history,
        "missing_historical_years": missing_actual_years,
        "input_fingerprint": fingerprint,
        "metric_definitions": {
            "revenue": "Prior-period revenue × (1 + annual revenue-growth assumption).",
            "gross_profit": "Forecast revenue × gross-margin assumption; COGS = revenue − gross profit.",
            "operating_expenses": "Gross profit − EBITDA when margin drivers are used; otherwise revenue × operating-expense ratio.",
            "ebitda": "Revenue × EBITDA-margin assumption, or gross profit − operating expenses.",
            "ebit": "EBITDA − depreciation and amortization.",
            "earnings_before_tax": "EBIT − interest expense.",
            "tax_expense": "max(EBT, 0) × tax-rate assumption; no tax benefit on losses.",
            "net_income": "EBT − tax expense.",
            "net_operating_working_capital": "Accounts receivable + inventory − accounts payable.",
            "operating_cash_flow": "Simplified indirect method: net income + D&A − change in net operating working capital.",
            "unlevered_free_cash_flow": "EBIT − operating taxes + D&A − capital expenditure − change in net operating working capital.",
        },
        "scenarios": results,
        "limitations": [
            "Forecasts are deterministic outputs of explicit assumptions and are not predictions or investment recommendations.",
            "Only the selected annual source-backed baseline is used; no missing historical values are imputed.",
            "Cash flow uses the disclosed simplified operating cash flow and unlevered free cash flow formulas; non-cash items and financing details may be incomplete.",
            "Tax expense is zero on negative EBT; no loss tax benefit or tax carryforward is assumed.",
            "Underlying source documents and historical figures are not independently verified by FinSight.",
        ],
    }


def forecast_input_fingerprint(observations: list[FinancialObservation], baseline_year: str, statement_basis: str) -> str:
    """Hash every selected baseline input field that affects forecast reproducibility."""
    refs = sorted(
        (
            item.observation_id, item.source_id, item.line_item_id,
            str(item.value) if item.value is not None else None,
            item.period_start.isoformat(), item.period_end.isoformat(), item.currency, item.unit,
        )
        for item in observations
        if item.financial_year == baseline_year and item.statement_basis == statement_basis
    )
    return hashlib.sha256(json.dumps(refs, separators=(",", ":")).encode()).hexdigest()


def build_sensitivity(
    observations: list[FinancialObservation], *, company_id: str, statement_basis: str, baseline_year: str,
    horizon: int, assumptions: dict[str, Any], growth_values: list[Any], ebitda_margin_values: list[Any],
) -> dict[str, Any]:
    if not 1 <= len(growth_values) <= 11 or not 1 <= len(ebitda_margin_values) <= 11 or len(growth_values) * len(ebitda_margin_values) > 121:
        raise ValueError("Sensitivity ranges must contain 1 to 11 points per driver and at most 121 combinations.")
    results = []
    for growth in growth_values:
        for margin in ebitda_margin_values:
            scenario_assumptions = dict(assumptions)
            scenario_assumptions["revenue_growth"] = [growth] * horizon
            scenario_assumptions["ebitda_margin"] = margin
            scenario_assumptions.pop("opex_percent_revenue", None)
            forecast = build_forecast(observations, company_id=company_id, statement_basis=statement_basis, baseline_year=baseline_year, horizon=horizon, assumptions=scenario_assumptions, scenarios={"bull": {}, "bear": {}})
            results.append({"revenue_growth": str(_decimal(growth, "sensitivity revenue_growth", minimum=Decimal("-0.99"), maximum=Decimal("5"))), "ebitda_margin": str(_decimal(margin, "sensitivity ebitda_margin", minimum=Decimal("-5"), maximum=Decimal("1"))), "base": forecast["scenarios"]["base"]["periods"]})
    return {"methodology_version": FORECAST_VERSION, "sensitivity": results, "saved_assumptions_unchanged": True}
