"""Pure metric tests use artificial values only in temporary in-test objects."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from finsight.metrics.calculator import calculate_company_metrics
from finsight.metrics.models import FinancialObservation


def observation(year, item, value, statement, *, basis="consolidated", unit="INR_crore", currency="INR", start=None, end=None, observation_id=None):
    year_number = int(year[2:])
    start = start or date(year_number - 1, 4, 1)
    end = end or date(year_number, 3, 31)
    return FinancialObservation(
        observation_id=observation_id or year_number * 100 + len(item),
        company_id="TEST_CO",
        financial_year=year,
        period_start=start,
        period_end=end,
        statement_basis=basis,
        statement_type=statement,
        line_item_id=item,
        value=Decimal(str(value)) if value is not None else None,
        unit=unit,
        currency=currency,
        source_id="TEST_SOURCE",
    )


def complete_history():
    values = {
        "FY2024": {
            "income_statement": {
                "revenue": 100, "ebitda": 20, "ebit": 15, "net_income": 10,
                "finance_costs": -2, "cost_of_goods_sold": 40, "purchases": 35,
            },
            "cash_flow_statement": {"operating_cash_flow": 12, "capital_expenditure": -3},
            "balance_sheet": {
                "total_assets": 100, "current_liabilities": 30, "total_equity": 50,
                "short_term_borrowings": 10, "long_term_borrowings": 20,
                "cash_and_cash_equivalents": 5, "trade_receivables": 10,
                "inventory": 8, "trade_payables": 7,
            },
        },
        "FY2025": {
            "income_statement": {
                "revenue": 120, "ebitda": 24, "ebit": 18, "net_income": 12,
                "finance_costs": -3, "cost_of_goods_sold": 48, "purchases": 42,
            },
            "cash_flow_statement": {"operating_cash_flow": 14, "capital_expenditure": -4},
            "balance_sheet": {
                "total_assets": 130, "current_liabilities": 40, "total_equity": 60,
                "short_term_borrowings": 12, "long_term_borrowings": 24,
                "cash_and_cash_equivalents": 6, "trade_receivables": 14,
                "inventory": 10, "trade_payables": 9,
            },
        },
    }
    result = []
    next_id = 1
    for year, statements in values.items():
        for statement, line_items in statements.items():
            for item, value in line_items.items():
                result.append(observation(year, item, value, statement, observation_id=next_id))
                next_id += 1
    return result


def result_map(observations):
    return {
        (item.financial_year, item.metric_id): item
        for item in calculate_company_metrics(observations)
    }


def test_growth_profitability_cash_flow_and_leverage_formulas():
    metrics = result_map(complete_history())
    expected = {
        "revenue_growth": Decimal("0.2"),
        "revenue_cagr": Decimal("0.2"),
        "ebitda_margin": Decimal("0.2"),
        "ebit_margin": Decimal("0.15"),
        "net_profit_margin": Decimal("0.1"),
        "operating_cash_flow": Decimal("14"),
        "free_cash_flow": Decimal("10"),
        "ocf_net_income": Decimal("14") / Decimal("12"),
        "ocf_net_income_divergence": Decimal("2"),
        "ocf_yoy_change": Decimal("2"),
        "total_debt": Decimal("36"),
        "net_debt": Decimal("30"),
        "debt_to_equity": Decimal("0.6"),
        "interest_coverage": Decimal("6"),
        "net_debt_to_ebitda": Decimal("1.25"),
    }
    for metric_id, value in expected.items():
        item = metrics[("FY2025", metric_id)]
        assert item.status == "calculated", (metric_id, item.explanation)
        assert item.value == pytest.approx(value)
        assert item.formula
        assert item.formula_version == "finsight-metrics-v1"
        assert item.input_observations


def test_average_balance_returns_and_working_capital_days():
    metrics = result_map(complete_history())
    expected = {
        "roa": Decimal(12) / Decimal(115),
        "roe": Decimal(12) / Decimal(55),
        "roce": Decimal(18) / Decimal(80),
        "receivable_days": Decimal(36.5),
        "inventory_days": Decimal(9) / Decimal(48) * Decimal(365),
        "payable_days": Decimal(8) / Decimal(42) * Decimal(365),
    }
    for metric_id, value in expected.items():
        item = metrics[("FY2025", metric_id)]
        assert item.status == "calculated", (metric_id, item.explanation)
        assert item.value == pytest.approx(value)
        if metric_id.endswith("_days"):
            assert item.unit == "days"
    ccc = metrics[("FY2025", "cash_conversion_cycle")]
    assert ccc.status == "calculated"
    assert ccc.value == pytest.approx(expected["receivable_days"] + expected["inventory_days"] - expected["payable_days"])
    assert ccc.unit == "days"


def test_missing_opening_balance_is_unavailable_not_zero():
    items = [observation("FY2025", "net_income", 5, "income_statement"), observation("FY2025", "total_assets", 20, "balance_sheet")]
    metrics = result_map(items)
    roa = metrics[("FY2025", "roa")]
    assert roa.status == "unavailable"
    assert "Opening balance" in roa.explanation
    assert roa.value is None


@pytest.mark.parametrize(
    ("metric_id", "balance_id"),
    [("roe", "total_equity"), ("roce", "current_liabilities")],
)
def test_missing_return_metric_balance_is_unavailable(metric_id, balance_id):
    items = [item for item in complete_history() if not (item.financial_year == "FY2024" and item.line_item_id == balance_id)]
    result = result_map(items)[("FY2025", metric_id)]
    assert result.status == "unavailable"
    assert result.value is None


@pytest.mark.parametrize("metric_id", ["receivable_days", "inventory_days", "payable_days"])
def test_missing_working_capital_balance_is_unavailable_with_days_unit(metric_id):
    balance_id = {
        "receivable_days": "trade_receivables",
        "inventory_days": "inventory",
        "payable_days": "trade_payables",
    }[metric_id]
    items = [item for item in complete_history() if not (item.financial_year == "FY2024" and item.line_item_id == balance_id)]
    result = result_map(items)[("FY2025", metric_id)]
    assert result.status == "unavailable"
    assert result.unit == "days"


@pytest.mark.parametrize(
    ("metric_id", "balance_id", "change"),
    [
        ("roa", "total_assets", {"period_end": date(2024, 3, 30)}),
        ("roe", "total_equity", {"currency": "USD"}),
        ("roce", "total_assets", {"unit": "INR_lakh"}),
        ("receivable_days", "trade_receivables", {"currency": "USD"}),
        ("inventory_days", "inventory", {"period_end": date(2024, 3, 30)}),
        ("payable_days", "trade_payables", {"unit": "INR_lakh"}),
    ],
)
def test_present_incompatible_balance_is_invalid_input(metric_id, balance_id, change):
    items = complete_history()
    items = [
        replace(item, **change)
        if item.financial_year == "FY2024" and item.line_item_id == balance_id
        else item
        for item in items
    ]
    result = result_map(items)[("FY2025", metric_id)]
    assert result.status == "invalid_input"
    assert result.value is None
    if metric_id.endswith("_days"):
        assert result.unit == "days"


@pytest.mark.parametrize("metric_id", ["receivable_days", "inventory_days", "payable_days"])
def test_invalid_working_capital_flow_uses_days_unit(metric_id):
    flow_id = {
        "receivable_days": "revenue",
        "inventory_days": "cost_of_goods_sold",
        "payable_days": "purchases",
    }[metric_id]
    items = [replace(item, value=Decimal(0)) if item.financial_year == "FY2025" and item.line_item_id == flow_id else item for item in complete_history()]
    result = result_map(items)[("FY2025", metric_id)]
    assert result.status == "invalid_input"
    assert result.unit == "days"


@pytest.mark.parametrize(
    ("metric_id", "flow_id"),
    [("receivable_days", "revenue"), ("inventory_days", "cost_of_goods_sold"), ("payable_days", "purchases")],
)
def test_missing_working_capital_flow_uses_days_unit(metric_id, flow_id):
    items = [item for item in complete_history() if not (item.financial_year == "FY2025" and item.line_item_id == flow_id)]
    result = result_map(items)[("FY2025", metric_id)]
    assert result.status == "unavailable"
    assert result.unit == "days"


def test_incompatible_working_capital_balance_takes_precedence_over_missing_flow():
    items = [
        replace(item, currency="USD")
        if item.financial_year == "FY2024" and item.line_item_id == "trade_receivables"
        else item
        for item in complete_history()
        if not (item.financial_year == "FY2025" and item.line_item_id == "revenue")
    ]
    result = result_map(items)[("FY2025", "receivable_days")]
    assert result.status == "invalid_input"
    assert result.unit == "days"
    assert "incompatible currencies" in result.explanation


def test_mixed_statement_basis_is_rejected_at_company_input_boundary():
    items = complete_history()
    items = [
        replace(item, statement_basis="standalone")
        if item.financial_year == "FY2024" and item.line_item_id == "total_assets"
        else item
        for item in items
    ]
    with pytest.raises(ValueError, match="one company and one statement basis"):
        calculate_company_metrics(items)


def test_missing_operating_inputs_return_unavailable_with_named_requirements():
    metrics = result_map([observation("FY2025", "revenue", 10, "income_statement")])
    margin = metrics[("FY2025", "ebit_margin")]
    assert margin.status == "unavailable"
    assert "ebit" in margin.explanation
    assert margin.value is None


def test_zero_and_negative_denominators_are_invalid_inputs():
    zero_history = [
        observation("FY2024", "revenue", 0, "income_statement"),
        observation("FY2025", "revenue", 10, "income_statement"),
        observation("FY2025", "ebit", 1, "income_statement"),
        observation("FY2025", "net_income", 0, "income_statement"),
        observation("FY2025", "total_equity", 0, "balance_sheet"),
        observation("FY2025", "short_term_borrowings", 1, "balance_sheet"),
        observation("FY2025", "long_term_borrowings", 2, "balance_sheet"),
        observation("FY2025", "finance_costs", 0, "income_statement"),
        observation("FY2025", "operating_cash_flow", 4, "cash_flow_statement"),
    ]
    metrics = result_map(zero_history)
    assert metrics[("FY2025", "revenue_growth")].status == "invalid_input"
    assert metrics[("FY2025", "debt_to_equity")].status == "invalid_input"
    assert metrics[("FY2025", "interest_coverage")].status == "invalid_input"
    assert metrics[("FY2025", "ocf_net_income")].status == "invalid_input"


def test_incompatible_currency_unit_or_period_is_never_silently_converted():
    inputs = [
        observation("FY2025", "ebitda", 4, "income_statement"),
        observation("FY2025", "revenue", 20, "income_statement", currency="USD"),
    ]
    metrics = result_map(inputs)
    margin = metrics[("FY2025", "ebitda_margin")]
    assert margin.status == "invalid_input"
    assert "currencies" in margin.explanation
    assert margin.value is None

    unit_inputs = [
        observation("FY2025", "ebitda", 4, "income_statement"),
        observation("FY2025", "revenue", 20, "income_statement", unit="INR_lakh"),
    ]
    margin = result_map(unit_inputs)[("FY2025", "ebitda_margin")]
    assert margin.status == "invalid_input"
    assert "units" in margin.explanation

    mismatched_period = [
        observation("FY2025", "ebitda", 4, "income_statement"),
        observation("FY2025", "revenue", 20, "income_statement", start=date(2024, 4, 2)),
    ]
    margin = result_map(mismatched_period)[("FY2025", "ebitda_margin")]
    assert margin.status == "invalid_input"
    assert "mismatched financial periods" in margin.explanation


def test_non_adjacent_prior_year_is_invalid_and_negative_average_equity_is_invalid():
    growth = result_map([
        observation("FY2024", "revenue", 80, "income_statement", start=date(2023, 4, 1), end=date(2024, 2, 29)),
        observation("FY2025", "revenue", 100, "income_statement"),
    ])[("FY2025", "revenue_growth")]
    assert growth.status == "invalid_input"
    assert "adjacent" in growth.explanation

    negative_equity = [
        observation("FY2024", "total_equity", -10, "balance_sheet"),
        observation("FY2025", "total_equity", -20, "balance_sheet"),
        observation("FY2025", "net_income", 4, "income_statement"),
    ]
    roe = result_map(negative_equity)[("FY2025", "roe")]
    assert roe.status == "invalid_input"
    assert roe.value is None


def test_negative_net_income_ratio_is_calculated_with_caution():
    metrics = result_map([
        observation("FY2025", "operating_cash_flow", 4, "cash_flow_statement"),
        observation("FY2025", "net_income", -2, "income_statement"),
    ])
    result = metrics[("FY2025", "ocf_net_income")]
    assert result.status == "calculated"
    assert result.value == Decimal("-2")
    assert result.warnings


def test_incompatible_company_or_basis_is_rejected():
    items = [observation("FY2025", "revenue", 1, "income_statement"), observation("FY2025", "ebit", 1, "income_statement", basis="standalone")]
    with pytest.raises(ValueError, match="one company and one statement basis"):
        calculate_company_metrics(items)


def test_result_serialization_keeps_provenance_and_decimal_as_text():
    result = result_map(complete_history())[("FY2025", "ebitda_margin")]
    payload = result.to_dict()
    assert payload["value"] == "0.2"
    assert payload["inputs"][0]["observation_id"]
    assert payload["inputs"][0]["source_id"] == "TEST_SOURCE"
