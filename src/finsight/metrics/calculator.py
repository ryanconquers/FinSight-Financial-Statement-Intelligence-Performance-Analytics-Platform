"""Pure Decimal calculations for documented FinSight financial metrics."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation, localcontext
from typing import Iterable

from finsight.metrics.models import FinancialObservation, MetricResult

FORMULA_VERSION = "finsight-metrics-v1"
_YEAR = re.compile(r"^FY(\d{4})$")


def calculate_company_metrics(
    observations: Iterable[FinancialObservation],
) -> list[MetricResult]:
    """Calculate documented metrics for one company's observations.

    This function performs no I/O. It keeps statement basis, periods, currency,
    and unit explicit and returns unavailable/invalid results with explanations.
    Revenue CAGR is returned for the latest revenue period across the available
    series; return and days metrics use adjacent-year closing balances.
    """
    items = list(observations)
    if not items:
        return []
    company_ids = {item.company_id for item in items}
    bases = {item.statement_basis for item in items}
    if len(company_ids) != 1 or len(bases) != 1:
        raise ValueError("Calculate one company and one statement basis at a time.")

    by_year: dict[str, dict[tuple[str, str], FinancialObservation]] = defaultdict(dict)
    for item in items:
        key = (item.statement_type, item.line_item_id)
        if key in by_year[item.financial_year]:
            raise ValueError(f"Duplicate metric input for {item.financial_year} {key}.")
        by_year[item.financial_year][key] = item

    years = sorted(by_year, key=_year_number)
    results: list[MetricResult] = []
    for year in years:
        current = by_year[year]
        current_period = _period_anchor(current)
        if current_period is None:
            continue
        previous_year = f"FY{_year_number(year) - 1:04d}"
        previous = by_year.get(previous_year, {})
        results.extend(_calculate_period(current, previous, current_period))

    cagr = _calculate_revenue_cagr(by_year, years)
    if cagr is not None:
        results.append(cagr)
    return results


def _year_number(financial_year: str) -> int:
    match = _YEAR.fullmatch(financial_year)
    if not match:
        raise ValueError(f"Unsupported financial year {financial_year!r}; expected FYYYYY.")
    return int(match.group(1))


def _period_anchor(
    current: dict[tuple[str, str], FinancialObservation],
) -> FinancialObservation | None:
    return next(iter(current.values()), None)


def _key(statement_type: str, line_item_id: str) -> tuple[str, str]:
    return statement_type, line_item_id


def _get(
    current: dict[tuple[str, str], FinancialObservation],
    statement_type: str,
    line_item_id: str,
) -> FinancialObservation | None:
    return current.get(_key(statement_type, line_item_id))


def _result(
    anchor: FinancialObservation,
    metric_id: str,
    name: str,
    formula: str,
    *,
    value: Decimal | None = None,
    unit: str = "ratio",
    currency: str | None = None,
    status: str = "calculated",
    explanation: str = "Calculated from the listed source observations.",
    inputs: Iterable[FinancialObservation] = (),
    warnings: Iterable[str] = (),
    period_start=None,
    period_end=None,
) -> MetricResult:
    return MetricResult(
        metric_id=metric_id,
        metric_name=name,
        company_id=anchor.company_id,
        financial_year=anchor.financial_year,
        period_start=period_start or anchor.period_start,
        period_end=period_end or anchor.period_end,
        statement_basis=anchor.statement_basis,
        value=value,
        unit=unit,
        currency=currency,
        status=status,  # type: ignore[arg-type]
        formula=formula,
        formula_version=FORMULA_VERSION,
        explanation=explanation,
        input_observations=tuple(inputs),
        warnings=tuple(warnings),
    )


def _missing(
    anchor: FinancialObservation,
    metric_id: str,
    name: str,
    formula: str,
    required_names: Iterable[str],
    available: Iterable[FinancialObservation] = (),
    *,
    unit: str = "ratio",
    currency: str | None = None,
) -> MetricResult:
    missing = ", ".join(required_names)
    return _result(
        anchor, metric_id, name, formula, status="unavailable", unit=unit,
        currency=currency,
        explanation=f"Unavailable: required input(s) missing: {missing}.",
        inputs=available,
    )


def _invalid(
    anchor: FinancialObservation,
    metric_id: str,
    name: str,
    formula: str,
    explanation: str,
    inputs: Iterable[FinancialObservation],
    *,
    unit: str = "ratio",
    currency: str | None = None,
) -> MetricResult:
    return _result(
        anchor, metric_id, name, formula, status="invalid_input", unit=unit,
        currency=currency, explanation=explanation, inputs=inputs,
    )


def _current_inputs(
    anchor: FinancialObservation,
    current: dict[tuple[str, str], FinancialObservation],
    required: tuple[tuple[str, str], ...],
    metric_id: str,
    name: str,
    formula: str,
    *,
    unit: str = "ratio",
) -> tuple[list[FinancialObservation], MetricResult | None]:
    values: list[FinancialObservation] = []
    missing: list[str] = []
    for statement_type, item_id in required:
        item = _get(current, statement_type, item_id)
        if item is None or item.value is None:
            missing.append(item_id)
        else:
            values.append(item)
    if missing:
        currency = values[0].currency if values else None
        return values, _missing(anchor, metric_id, name, formula, missing, values, unit=unit, currency=currency)
    metadata_error = _compatible_current(anchor, values)
    if metadata_error:
        return values, _invalid(anchor, metric_id, name, formula, metadata_error, values, unit=unit)
    return values, None


def _compatible_current(
    anchor: FinancialObservation, values: Iterable[FinancialObservation]
) -> str | None:
    items = list(values)
    for item in items:
        if item.statement_basis != anchor.statement_basis:
            return "Inputs use incompatible standalone/consolidated statement bases."
        if (item.period_start, item.period_end) != (anchor.period_start, anchor.period_end):
            return "Inputs refer to mismatched financial periods."
        if item.currency != anchor.currency:
            return "Inputs use incompatible currencies; no conversion was applied."
        if item.unit != anchor.unit:
            return "Inputs use incompatible units; no rescaling was applied."
    return None


def _valid_opening_balance(
    anchor: FinancialObservation,
    opening: FinancialObservation | None,
    closing: FinancialObservation,
) -> tuple[bool, str | None]:
    if opening is None or opening.value is None:
        return False, "Opening balance from the adjacent prior financial year is missing."
    if opening.statement_basis != anchor.statement_basis:
        return False, "Opening and closing balances use different statement bases."
    if opening.period_end + timedelta(days=1) != anchor.period_start:
        return False, "Opening balance date is not the day before the current reporting period."
    if opening.currency != closing.currency:
        return False, "Opening and closing balances use incompatible currencies; no conversion was applied."
    if opening.unit != closing.unit:
        return False, "Opening and closing balances use incompatible units; no rescaling was applied."
    return True, None


def _balance_pair(
    anchor: FinancialObservation,
    current: dict[tuple[str, str], FinancialObservation],
    previous: dict[tuple[str, str], FinancialObservation],
    line_item_id: str,
) -> tuple[FinancialObservation | None, FinancialObservation | None, str | None, bool]:
    closing = _get(current, "balance_sheet", line_item_id)
    opening = _get(previous, "balance_sheet", line_item_id)
    if closing is None or closing.value is None:
        return opening, closing, f"Closing {line_item_id} balance is missing.", True
    valid, reason = _valid_opening_balance(anchor, opening, closing)
    if not valid:
        missing = opening is None or opening.value is None
        return opening, closing, reason, missing
    if (closing.period_start, closing.period_end) != (anchor.period_start, anchor.period_end):
        return opening, closing, f"Closing {line_item_id} balance has a mismatched reporting period.", False
    return opening, closing, None, False


def _average_balance(
    opening: FinancialObservation, closing: FinancialObservation
) -> Decimal:
    assert opening.value is not None and closing.value is not None
    return (opening.value + closing.value) / Decimal(2)


def _calculate_period(
    current: dict[tuple[str, str], FinancialObservation],
    previous: dict[tuple[str, str], FinancialObservation],
    anchor: FinancialObservation,
) -> list[MetricResult]:
    output: list[MetricResult] = []
    formulas = {
        "revenue_growth": "(current revenue / prior-year revenue) - 1",
        "gross_profit": "revenue - absolute cost of goods sold",
        "gross_margin": "gross profit / revenue",
        "ebitda_margin": "EBITDA / revenue",
        "ebit_margin": "EBIT / revenue",
        "net_profit_margin": "net income / revenue",
        "operating_cash_flow": "reported net cash from operating activities",
        "free_cash_flow": "operating cash flow - absolute capital expenditure outflow",
        "ocf_net_income": "operating cash flow / net income",
        "ocf_net_income_divergence": "operating cash flow - net income",
        "ocf_yoy_change": "current operating cash flow - prior-year operating cash flow",
        "receivable_days": "average trade receivables / revenue * period days",
        "inventory_days": "average inventory / cost of goods sold * period days",
        "payable_days": "average trade payables / purchases * period days",
        "cash_conversion_cycle": "receivable days + inventory days - payable days",
        "total_debt": "short-term borrowings + long-term borrowings",
        "net_debt": "short-term borrowings + long-term borrowings - cash and cash equivalents",
        "debt_to_equity": "total debt / total equity",
        "interest_coverage": "EBIT / absolute finance costs",
        "net_debt_to_ebitda": "net debt / EBITDA",
    }

    def get_inputs(metric_id: str, required: tuple[tuple[str, str], ...], unit: str = "ratio"):
        name = metric_id.replace("_", " ").title()
        return _current_inputs(anchor, current, required, metric_id, name, formulas[metric_id], unit=unit)

    # Revenue growth uses the matching prior-year flow and rejects non-positive bases.
    metric_id = "revenue_growth"
    now = _get(current, "income_statement", "revenue")
    old = _get(previous, "income_statement", "revenue")
    if now is None or now.value is None or old is None or old.value is None:
        missing = [name for name, value in (("current revenue", now), ("prior-year revenue", old)) if value is None or value.value is None]
        output.append(_missing(anchor, metric_id, "Revenue growth", formulas[metric_id], missing, [item for item in (now, old) if item and item.value is not None]))
    elif (old.period_end + timedelta(days=1) != now.period_start or _year_number(now.financial_year) - _year_number(old.financial_year) != 1):
        output.append(_invalid(anchor, metric_id, "Revenue growth", formulas[metric_id], "Prior-year revenue is not from the immediately adjacent reporting period.", [old, now]))
    elif (current_period_error := _compatible_current(anchor, [now])) is not None:
        output.append(_invalid(anchor, metric_id, "Revenue growth", formulas[metric_id], current_period_error, [old, now]))
    elif old.currency != now.currency or old.unit != now.unit or old.statement_basis != now.statement_basis:
        output.append(_invalid(anchor, metric_id, "Revenue growth", formulas[metric_id], "Prior/current revenue uses incompatible period basis, currency, or unit; no conversion was applied.", [old, now]))
    elif old.value <= 0:
        output.append(_invalid(anchor, metric_id, "Revenue growth", formulas[metric_id], "Prior-year revenue must be positive for a meaningful growth rate.", [old, now]))
    elif now.value <= 0:
        output.append(_invalid(anchor, metric_id, "Revenue growth", formulas[metric_id], "Current revenue must be positive for a meaningful growth rate.", [old, now]))
    else:
        output.append(_result(anchor, metric_id, "Revenue growth", formulas[metric_id], value=(now.value / old.value) - 1, inputs=[old, now]))

    # Profitability margins.
    metric_id = "gross_profit"
    gross_inputs, issue = get_inputs(metric_id, (("income_statement", "revenue"), ("income_statement", "cost_of_goods_sold")), unit="amount")
    if issue:
        output.append(issue)
        output.append(_result(anchor, "gross_margin", "Gross margin", formulas["gross_margin"], status=issue.status, explanation=issue.explanation, inputs=issue.input_observations))
    elif gross_inputs[0].value <= 0:
        output.append(_invalid(anchor, metric_id, "Gross profit", formulas[metric_id], "Revenue must be positive.", gross_inputs, unit="amount"))
        output.append(_invalid(anchor, "gross_margin", "Gross margin", formulas["gross_margin"], "Revenue must be positive.", gross_inputs))
    else:
        gross_profit = gross_inputs[0].value - abs(gross_inputs[1].value)
        output.append(_result(anchor, metric_id, "Gross profit", formulas[metric_id], value=gross_profit, unit=gross_inputs[0].unit, currency=gross_inputs[0].currency, inputs=gross_inputs))
        output.append(_result(anchor, "gross_margin", "Gross margin", formulas["gross_margin"], value=gross_profit / gross_inputs[0].value, inputs=gross_inputs))

    for metric_id, line_item, name in (
        ("ebitda_margin", "ebitda", "EBITDA margin"),
        ("ebit_margin", "ebit", "EBIT margin"),
        ("net_profit_margin", "net_income", "Net profit margin"),
    ):
        values, issue = get_inputs(metric_id, (("income_statement", line_item), ("income_statement", "revenue")))
        if issue:
            output.append(issue)
        elif values[1].value is None or values[1].value <= 0:
            output.append(_invalid(anchor, metric_id, name, formulas[metric_id], "Revenue denominator must be positive.", values))
        else:
            output.append(_result(anchor, metric_id, name, formulas[metric_id], value=values[0].value / values[1].value, inputs=values))

    # Average-balance returns: opening balance is the adjacent FY closing balance.
    for metric_id, numerator_id, balance_id, name in (
        ("roa", "net_income", "total_assets", "Return on assets"),
        ("roe", "net_income", "total_equity", "Return on equity"),
    ):
        formula = f"net income / average {balance_id}"
        numerator, issue = _current_inputs(anchor, current, (("income_statement", numerator_id),), metric_id, name, formula)
        opening, closing, balance_error, balance_missing = _balance_pair(anchor, current, previous, balance_id)
        if balance_error and not balance_missing:
            available = numerator + [item for item in (opening, closing) if item is not None and item.value is not None]
            explanation = f"{issue.explanation} {balance_error}" if issue and issue.status == "invalid_input" else balance_error
            output.append(_invalid(anchor, metric_id, name, formula, explanation, available))
        elif issue:
            output.append(issue)
        elif balance_error:
            available = numerator + [item for item in (opening, closing) if item is not None and item.value is not None]
            output.append(_missing(anchor, metric_id, name, formula, [balance_error], available))
        else:
            assert opening and closing and opening.value is not None and closing.value is not None
            balance_inputs = [*numerator, opening, closing]
            if any(item.unit != numerator[0].unit or item.currency != numerator[0].currency for item in (opening, closing)):
                output.append(_invalid(anchor, metric_id, name, formula, "Return numerator and balance inputs use incompatible units or currencies.", balance_inputs))
            else:
                denominator = _average_balance(opening, closing)
                if denominator <= 0:
                    output.append(_invalid(anchor, metric_id, name, formula, "Average balance denominator must be positive.", balance_inputs))
                else:
                    output.append(_result(anchor, metric_id, name, formula, value=numerator[0].value / denominator, inputs=balance_inputs))

    # ROCE uses average (total assets - current liabilities).
    metric_id = "roce"
    formula = "EBIT / average (total assets - current liabilities)"
    ebit, issue = _current_inputs(anchor, current, (("income_statement", "ebit"),), metric_id, "Return on capital employed", formula)
    balance_pairs = {line: _balance_pair(anchor, current, previous, line) for line in ("total_assets", "current_liabilities")}
    balance_errors = [(error, missing) for _, _, error, missing in balance_pairs.values() if error]
    missing_errors = [error for error, missing in balance_errors if missing]
    incompatible_errors = [error for error, missing in balance_errors if not missing]
    if incompatible_errors:
        available_balances = [
            item for opening, closing, _, _ in balance_pairs.values()
            for item in (opening, closing)
            if item is not None and item.value is not None
        ]
        issue_detail = f"{issue.explanation} " if issue and issue.status == "invalid_input" else ""
        output.append(_invalid(anchor, metric_id, "Return on capital employed", formula, issue_detail + "; ".join(incompatible_errors), [*ebit, *available_balances]))
    elif issue:
        output.append(issue)
    elif balance_errors:
        output.append(_missing(anchor, metric_id, "Return on capital employed", formula, missing_errors, ebit))
    else:
        assets_open, assets_close, _, _ = balance_pairs["total_assets"]
        liabilities_open, liabilities_close, _, _ = balance_pairs["current_liabilities"]
        assert all(item is not None and item.value is not None for item in (assets_open, assets_close, liabilities_open, liabilities_close))
        refs = [*ebit, assets_open, assets_close, liabilities_open, liabilities_close]
        if any(item.currency != ebit[0].currency or item.unit != ebit[0].unit for item in refs[1:]):
            output.append(_invalid(anchor, metric_id, "Return on capital employed", formula, "EBIT and capital-employed balances use incompatible units or currencies.", refs))
        else:
            opening_capital = assets_open.value - liabilities_open.value
            closing_capital = assets_close.value - liabilities_close.value
            average_capital = (opening_capital + closing_capital) / Decimal(2)
            if average_capital <= 0:
                output.append(_invalid(anchor, metric_id, "Return on capital employed", formula, "Average capital employed must be positive.", refs))
            else:
                output.append(_result(anchor, metric_id, "Return on capital employed", formula, value=ebit[0].value / average_capital, inputs=refs))

    # Cash-flow identity and quality metrics.
    metric_id = "operating_cash_flow"
    values, issue = get_inputs(metric_id, (("cash_flow_statement", "operating_cash_flow"),), unit="amount")
    output.append(issue or _result(anchor, metric_id, "Operating cash flow", formulas[metric_id], value=values[0].value, unit=values[0].unit, currency=values[0].currency, inputs=values))

    metric_id = "free_cash_flow"
    values, issue = get_inputs(metric_id, (("cash_flow_statement", "operating_cash_flow"), ("cash_flow_statement", "capital_expenditure")), unit="amount")
    if issue:
        output.append(issue)
    else:
        value = values[0].value - abs(values[1].value)
        output.append(_result(anchor, metric_id, "Free cash flow", formulas[metric_id], value=value, unit=values[0].unit, currency=values[0].currency, inputs=values))

    metric_id = "ocf_net_income"
    values, issue = get_inputs(metric_id, (("cash_flow_statement", "operating_cash_flow"), ("income_statement", "net_income")))
    if issue:
        output.append(issue)
    elif values[1].value == 0:
        output.append(_invalid(anchor, metric_id, "Operating cash flow / net income", formulas[metric_id], "Net income denominator is zero.", values))
    else:
        warnings = ("Net income is negative; interpret this coverage ratio with care.",) if values[1].value < 0 else ()
        output.append(_result(anchor, metric_id, "Operating cash flow / net income", formulas[metric_id], value=values[0].value / values[1].value, inputs=values, warnings=warnings))

    metric_id = "ocf_net_income_divergence"
    values, issue = get_inputs(metric_id, (("cash_flow_statement", "operating_cash_flow"), ("income_statement", "net_income")), unit="amount")
    if issue:
        output.append(issue)
    else:
        output.append(_result(anchor, metric_id, "Operating cash flow vs net income divergence", formulas[metric_id], value=values[0].value - values[1].value, unit=values[0].unit, currency=values[0].currency, inputs=values))

    metric_id = "ocf_yoy_change"
    now = _get(current, "cash_flow_statement", "operating_cash_flow")
    old = _get(previous, "cash_flow_statement", "operating_cash_flow")
    output.append(_year_over_year_amount(anchor, now, old, metric_id, "Operating cash flow YoY change", formulas[metric_id]))

    # Working-capital days use average opening/closing balances and the reported period's calendar days.
    for metric_id, balance_id, flow_id, statement_type, name in (
        ("receivable_days", "trade_receivables", "revenue", "income_statement", "Receivable days"),
        ("inventory_days", "inventory", "cost_of_goods_sold", "income_statement", "Inventory days"),
        ("payable_days", "trade_payables", "purchases", "income_statement", "Payable days"),
    ):
        formula = formulas[metric_id]
        flow, issue = _current_inputs(anchor, current, ((statement_type, flow_id),), metric_id, name, formula, unit="days")
        opening, closing, balance_error, balance_missing = _balance_pair(anchor, current, previous, balance_id)
        if balance_error and not balance_missing:
            available = flow + [item for item in (opening, closing) if item is not None and item.value is not None]
            explanation = f"{issue.explanation} {balance_error}" if issue and issue.status == "invalid_input" else balance_error
            output.append(_invalid(anchor, metric_id, name, formula, explanation, available, unit="days"))
        elif issue:
            output.append(issue)
        elif balance_error:
            output.append(_missing(anchor, metric_id, name, formula, [balance_error], flow, unit="days"))
        else:
            assert opening and closing and opening.value is not None and closing.value is not None
            refs = [*flow, opening, closing]
            if any(item.unit != flow[0].unit or item.currency != flow[0].currency for item in (opening, closing)):
                output.append(_invalid(anchor, metric_id, name, formula, "Working-capital balances and flow use incompatible units or currencies.", refs, unit="days"))
            elif flow[0].value <= 0:
                output.append(_invalid(anchor, metric_id, name, formula, f"{flow_id} denominator must be positive.", refs, unit="days"))
            else:
                average = _average_balance(opening, closing)
                if average < 0:
                    output.append(_invalid(anchor, metric_id, name, formula, f"Average {balance_id} must not be negative.", refs, unit="days"))
                else:
                    days = Decimal((anchor.period_end - anchor.period_start).days + 1)
                    result = average / flow[0].value * days
                    output.append(_result(anchor, metric_id, name, formula, value=result, unit="days", inputs=refs))

    day_results = {item.metric_id: item for item in output}
    ccc_parts = [day_results.get(metric) for metric in ("receivable_days", "inventory_days", "payable_days")]
    if any(part is None for part in ccc_parts):
        output.append(_missing(anchor, "cash_conversion_cycle", "Cash conversion cycle", formulas["cash_conversion_cycle"], ["receivable, inventory, and payable days"]))
    else:
        parts = [part for part in ccc_parts if part is not None]
        unavailable = [part for part in parts if part.status != "calculated"]
        if unavailable:
            status = "invalid_input" if any(part.status == "invalid_input" for part in unavailable) else "unavailable"
            explanation = "Cash conversion cycle is unavailable because one or more component day metrics could not be calculated: " + "; ".join(part.explanation for part in unavailable)
            output.append(_result(anchor, "cash_conversion_cycle", "Cash conversion cycle", formulas["cash_conversion_cycle"], status=status, explanation=explanation, unit="days", inputs=[item for part in parts for item in part.input_observations]))
        else:
            values = {part.metric_id: part.value for part in parts}
            ccc = values["receivable_days"] + values["inventory_days"] - values["payable_days"]
            output.append(_result(anchor, "cash_conversion_cycle", "Cash conversion cycle", formulas["cash_conversion_cycle"], value=ccc, unit="days", inputs=[item for part in parts for item in part.input_observations]))

    # Debt and leverage metrics.
    debt_required = (("balance_sheet", "short_term_borrowings"), ("balance_sheet", "long_term_borrowings"))
    debt_values, debt_issue = get_inputs("total_debt", debt_required, unit="amount")
    if debt_issue:
        output.append(debt_issue)
    else:
        total_debt = debt_values[0].value + debt_values[1].value
        output.append(_result(anchor, "total_debt", "Total debt", formulas["total_debt"], value=total_debt, unit=debt_values[0].unit, currency=debt_values[0].currency, inputs=debt_values))

    net_debt_required = (*debt_required, ("balance_sheet", "cash_and_cash_equivalents"))
    net_debt_values, net_debt_issue = get_inputs("net_debt", net_debt_required, unit="amount")
    if net_debt_issue:
        output.append(net_debt_issue)
    else:
        net_debt = net_debt_values[0].value + net_debt_values[1].value - net_debt_values[2].value
        output.append(_result(anchor, "net_debt", "Net debt", formulas["net_debt"], value=net_debt, unit=net_debt_values[0].unit, currency=net_debt_values[0].currency, inputs=net_debt_values))

    metric_id = "debt_to_equity"
    leverage_values, issue = get_inputs(metric_id, (*debt_required, ("balance_sheet", "total_equity")))
    if issue:
        output.append(issue)
    elif leverage_values[2].value <= 0:
        output.append(_invalid(anchor, metric_id, "Debt-to-equity ratio", formulas[metric_id], "Total equity denominator must be positive.", leverage_values))
    else:
        total_debt = leverage_values[0].value + leverage_values[1].value
        output.append(_result(anchor, metric_id, "Debt-to-equity ratio", formulas[metric_id], value=total_debt / leverage_values[2].value, inputs=leverage_values))

    metric_id = "interest_coverage"
    coverage_values, issue = get_inputs(metric_id, (("income_statement", "ebit"), ("income_statement", "finance_costs")))
    if issue:
        output.append(issue)
    elif coverage_values[1].value == 0:
        output.append(_invalid(anchor, metric_id, "Interest coverage ratio", formulas[metric_id], "Finance-cost denominator is zero.", coverage_values))
    else:
        value = coverage_values[0].value / abs(coverage_values[1].value)
        output.append(_result(anchor, metric_id, "Interest coverage ratio", formulas[metric_id], value=value, inputs=coverage_values))

    metric_id = "net_debt_to_ebitda"
    ratio_values, issue = get_inputs(metric_id, (*net_debt_required, ("income_statement", "ebitda")))
    if issue:
        output.append(issue)
    elif ratio_values[3].value <= 0:
        output.append(_invalid(anchor, metric_id, "Net debt / EBITDA", formulas[metric_id], "EBITDA denominator must be positive and meaningful.", ratio_values))
    else:
        net_debt = ratio_values[0].value + ratio_values[1].value - ratio_values[2].value
        output.append(_result(anchor, metric_id, "Net debt / EBITDA", formulas[metric_id], value=net_debt / ratio_values[3].value, inputs=ratio_values))

    return output


def _year_over_year_amount(
    anchor: FinancialObservation,
    current: FinancialObservation | None,
    previous: FinancialObservation | None,
    metric_id: str,
    name: str,
    formula: str,
) -> MetricResult:
    available = [item for item in (previous, current) if item is not None and item.value is not None]
    missing = [label for label, item in (("current-period value", current), ("prior-year value", previous)) if item is None or item.value is None]
    if missing:
        return _missing(anchor, metric_id, name, formula, missing, available, unit="amount", currency=available[0].currency if available else None)
    assert current and previous and current.value is not None and previous.value is not None
    anchor_error = _compatible_current(anchor, [current])
    if anchor_error:
        return _invalid(anchor, metric_id, name, formula, anchor_error, available, unit="amount", currency=current.currency)
    if previous.period_end + timedelta(days=1) != current.period_start:
        return _invalid(anchor, metric_id, name, formula, "Prior-year value is not from the immediately adjacent reporting period.", available, unit="amount", currency=current.currency)
    if current.statement_basis != previous.statement_basis or current.currency != previous.currency or current.unit != previous.unit:
        return _invalid(anchor, metric_id, name, formula, "Prior/current values use incompatible statement basis, currency, or unit.", available, unit="amount", currency=current.currency)
    return _result(anchor, metric_id, name, formula, value=current.value - previous.value, unit=current.unit, currency=current.currency, inputs=available)


def _calculate_revenue_cagr(
    by_year: dict[str, dict[tuple[str, str], FinancialObservation]], years: list[str]
) -> MetricResult | None:
    revenues = [
        current[_key("income_statement", "revenue")]
        for year in years
        if (current := by_year[year]).get(_key("income_statement", "revenue")) is not None
        and current[_key("income_statement", "revenue")].value is not None
    ]
    if not revenues:
        return None
    start, end = revenues[0], revenues[-1]
    formula = "(ending revenue / starting revenue) ** (1 / elapsed financial years) - 1"
    if start.financial_year == end.financial_year:
        return _result(start, "revenue_cagr", "Revenue CAGR", formula, status="unavailable", explanation="Unavailable: revenue from at least two financial years is required.", inputs=[start])
    elapsed = _year_number(end.financial_year) - _year_number(start.financial_year)
    if start.period_end + timedelta(days=1) > end.period_start:
        return _result(end, "revenue_cagr", "Revenue CAGR", formula, status="invalid_input", explanation="Revenue periods overlap or are not chronologically ordered.", inputs=[start, end], period_start=start.period_start, period_end=end.period_end)
    if start.currency != end.currency or start.unit != end.unit or start.statement_basis != end.statement_basis:
        return _result(end, "revenue_cagr", "Revenue CAGR", formula, status="invalid_input", explanation="Starting and ending revenue use incompatible currency, unit, or statement basis; no conversion was applied.", inputs=[start, end], period_start=start.period_start, period_end=end.period_end)
    if start.value is None or end.value is None or start.value <= 0 or end.value <= 0:
        return _result(end, "revenue_cagr", "Revenue CAGR", formula, status="invalid_input", explanation="Starting and ending revenue must both be positive.", inputs=[start, end], period_start=start.period_start, period_end=end.period_end)
    try:
        with localcontext() as context:
            context.prec = 28
            ratio = end.value / start.value
            value = ratio ** (Decimal(1) / Decimal(elapsed)) - 1
    except (InvalidOperation, ZeroDivisionError):
        return _result(end, "revenue_cagr", "Revenue CAGR", formula, status="invalid_input", explanation="CAGR could not be evaluated for the supplied revenue values.", inputs=[start, end], period_start=start.period_start, period_end=end.period_end)
    return _result(end, "revenue_cagr", "Revenue CAGR", formula, value=value, inputs=[start, end], period_start=start.period_start, period_end=end.period_end)
