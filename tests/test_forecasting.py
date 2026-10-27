"""M5 forecasting tests use only clearly synthetic test observations."""

from datetime import date
from decimal import Decimal

import pytest

from finsight.forecasting.engine import build_forecast, build_sensitivity
from finsight.metrics.models import FinancialObservation


def actual(item_id, value, *, year="FY2024", statement="income_statement", unit="INR_crore", currency="INR", company="TEST_CO", basis="consolidated", start=date(2023, 4, 1), end=date(2024, 3, 31), observation_id=None):
    return FinancialObservation(
        observation_id=observation_id or abs(hash((company, year, item_id))) % 100000,
        company_id=company, financial_year=year, period_start=start, period_end=end,
        statement_basis=basis, statement_type=statement, line_item_id=item_id,
        value=Decimal(str(value)) if value is not None else None, unit=unit, currency=currency,
        source_id=f"TEST_SOURCE_{company}_{year}",
    )


def baseline():
    return [
        actual("revenue", "100", observation_id=1), actual("cost_of_goods_sold", "60", observation_id=2),
        actual("ebitda", "15", observation_id=3), actual("ebit", "10", observation_id=4),
        actual("finance_costs", "2", observation_id=5),
        actual("trade_receivables", "10", statement="balance_sheet", observation_id=6),
        actual("inventory", "12", statement="balance_sheet", observation_id=7),
        actual("trade_payables", "8", statement="balance_sheet", observation_id=8),
    ]


def assumptions():
    return {
        "revenue_growth": ["0.10", "0.10"], "gross_margin": "0.35", "ebitda_margin": "0.15",
        "opex_percent_revenue": "0.20", "da_percent_revenue": "0.05", "tax_rate": "0.25",
        "capex_percent_revenue": "0.04", "interest_expense": ["2", "2"],
        "receivable_days": "36.5", "inventory_days": "73", "payable_days": "36.5",
    }


def test_driver_forecast_reconciles_income_statement_and_cash_flow_components():
    result = build_forecast(baseline(), company_id="TEST_CO", statement_basis="consolidated", baseline_year="FY2024", horizon=2, assumptions=assumptions())
    base = result["scenarios"]["base"]
    first = base["periods"][0]
    assert first["revenue"] == "110.00"
    assert first["gross_profit"] == "38.5000"
    assert first["cost_of_goods_sold"] == "71.5000"
    assert first["operating_expenses"] == "22.0000"
    assert Decimal(first["ebitda"]) == Decimal("16.5")
    assert Decimal(first["depreciation_amortization"]) == Decimal("5.5")
    assert Decimal(first["ebit"]) == Decimal("11")
    assert Decimal(first["earnings_before_tax"]) == Decimal("9")
    assert Decimal(first["tax_expense"]) == Decimal("2.25")
    assert Decimal(first["net_income"]) == Decimal("6.75")
    assert Decimal(first["change_in_working_capital"]) == Decimal("4.15")
    assert Decimal(first["operating_cash_flow"]) == Decimal("8.10")
    assert Decimal(first["unlevered_free_cash_flow"]) == Decimal("5.20")
    assert base["actual_baseline"]["period_type"] == "actual"
    assert Decimal(base["actual_baseline"]["values"]["gross_profit"]) == Decimal("40")
    assert Decimal(base["actual_baseline"]["values"]["gross_margin"]) == Decimal("0.4")
    assert base["periods"][0]["period_type"] == "forecast"
    assert result["created_from_observation_ids"] == list(range(1, 9))
    assert "net income + D&A" in result["metric_definitions"]["operating_cash_flow"]
    assert "not predictions" in result["limitations"][0]


def test_forecast_scenarios_are_explicit_and_reproducible():
    kwargs = dict(company_id="TEST_CO", statement_basis="consolidated", baseline_year="FY2024", horizon=2, assumptions=assumptions())
    first = build_forecast(baseline(), **kwargs)
    second = build_forecast(baseline(), **kwargs)
    assert first == second
    assert first["assumptions"]["bull"]["revenue_growth"] == ["0.12", "0.12"]
    assert first["assumptions"]["bear"]["revenue_growth"] == ["0.08", "0.08"]
    custom = build_forecast(baseline(), **{**kwargs, "scenarios": {"bull": {"revenue_growth": ["0.3", "0.3"], "ebitda_margin": "0.2"}}})
    assert custom["assumptions"]["bull"]["revenue_growth"] == ["0.3", "0.3"]


@pytest.mark.parametrize("changes, message", [
    ({"revenue_growth": ["NaN", "0.1"]}, "finite"),
    ({"revenue_growth": ["-1", "0.1"]}, "at least"),
    ({"revenue_growth": ["0.1"]}, "one assumption per forecast year"),
    ({"tax_rate": "1.01"}, "no more than"),
    ({"gross_margin": "0.3", "ebitda_margin": "0.2", "opex_percent_revenue": "0.2"}, "do not reconcile"),
])
def test_invalid_forecast_assumptions_are_rejected(changes, message):
    values = assumptions() | changes
    with pytest.raises(ValueError, match=message):
        build_forecast(baseline(), company_id="TEST_CO", statement_basis="consolidated", baseline_year="FY2024", horizon=2, assumptions=values)


def test_forecast_rejects_missing_or_incompatible_baselines_and_periods():
    with pytest.raises(ValueError, match="No source-backed observations"):
        build_forecast([], company_id="TEST_CO", statement_basis="consolidated", baseline_year="FY2024", horizon=2, assumptions=assumptions())
    with pytest.raises(ValueError, match="must be positive"):
        build_forecast([actual("revenue", "0")], company_id="TEST_CO", statement_basis="consolidated", baseline_year="FY2024", horizon=2, assumptions=assumptions())
    with pytest.raises(ValueError, match="must be positive"):
        build_forecast([actual("revenue", "-1")], company_id="TEST_CO", statement_basis="consolidated", baseline_year="FY2024", horizon=2, assumptions=assumptions())
    mixed = baseline() + [actual("other", "1", unit="USD_million")]
    with pytest.raises(ValueError, match="mixes currencies or financial units"):
        build_forecast(mixed, company_id="TEST_CO", statement_basis="consolidated", baseline_year="FY2024", horizon=2, assumptions=assumptions())
    short = [actual("revenue", "100", start=date(2023, 10, 1))]
    with pytest.raises(ValueError, match="compatible annual"):
        build_forecast(short, company_id="TEST_CO", statement_basis="consolidated", baseline_year="FY2024", horizon=2, assumptions=assumptions())


def test_missing_components_remain_unavailable_and_losses_receive_no_tax_benefit():
    sparse = [actual("revenue", "100", observation_id=1)]
    minimal = {"revenue_growth": ["0"], "gross_margin": "0.2", "ebitda_margin": "0.1", "da_percent_revenue": "0.2", "tax_rate": "0.25", "interest_expense": ["1"]}
    row = build_forecast(sparse, company_id="TEST_CO", statement_basis="consolidated", baseline_year="FY2024", horizon=1, assumptions=minimal)["scenarios"]["base"]["periods"][0]
    assert Decimal(row["earnings_before_tax"]) == Decimal("-11")
    assert Decimal(row["tax_expense"]) == Decimal("0")
    assert Decimal(row["net_income"]) == Decimal("-11")
    assert any(item["metric"] == "capital_expenditure" for item in row["unavailable"])
    assert row["unlevered_free_cash_flow"] is None


def test_explicit_ebitda_margin_remains_calculable_when_gross_margin_is_unavailable():
    sparse = [actual("revenue", "100", observation_id=1)]
    drivers = {"revenue_growth": ["0"], "ebitda_margin": "-0.1", "da_percent_revenue": "0.02", "interest_expense": "1", "tax_rate": "0.2"}
    row = build_forecast(sparse, company_id="TEST_CO", statement_basis="consolidated", baseline_year="FY2024", horizon=1, assumptions=drivers)["scenarios"]["base"]["periods"][0]
    assert Decimal(row["ebitda"]) == Decimal("-10.0")
    assert Decimal(row["ebit"]) == Decimal("-12.00")
    assert row["gross_profit"] is None
    assert any(item["metric"] == "gross_profit" for item in row["unavailable"])


def test_sensitivity_recalculates_engine_without_mutating_assumptions():
    base_assumptions = assumptions()
    result = build_sensitivity(baseline(), company_id="TEST_CO", statement_basis="consolidated", baseline_year="FY2024", horizon=2, assumptions=base_assumptions, growth_values=["0.08", "0.1"], ebitda_margin_values=["0.14", "0.15"])
    assert len(result["sensitivity"]) == 4
    assert result["saved_assumptions_unchanged"] is True
    assert base_assumptions["revenue_growth"] == ["0.10", "0.10"]
    assert result["sensitivity"][0]["base"][0]["revenue"] == "108.00"
    with pytest.raises(ValueError, match="1 to 11"):
        build_sensitivity(baseline(), company_id="TEST_CO", statement_basis="consolidated", baseline_year="FY2024", horizon=2, assumptions=base_assumptions, growth_values=[0] * 12, ebitda_margin_values=[0])


def test_historical_period_gaps_are_reported_and_not_filled():
    older = [actual("revenue", "80", year="FY2022", start=date(2021, 4, 1), end=date(2022, 3, 31), observation_id=90)]
    result = build_forecast(older + baseline(), company_id="TEST_CO", statement_basis="consolidated", baseline_year="FY2024", horizon=1, assumptions=assumptions() | {"revenue_growth": ["0.1"], "interest_expense": ["2"]})
    assert result["missing_historical_years"] == ["FY2023"]
    years = [row["financial_year"] for row in result["scenarios"]["base"]["actual_history"]]
    assert years == ["FY2022", "FY2024"]


def test_supported_assumptions_are_derived_from_baseline_and_disclosed():
    raw = {"revenue_growth": ["0.1"], "tax_rate": "0.25"}
    result = build_forecast(baseline(), company_id="TEST_CO", statement_basis="consolidated", baseline_year="FY2024", horizon=1, assumptions=raw)
    expanded = result["assumptions"]["base"]
    assert Decimal(expanded["gross_margin"]) == Decimal("0.4")
    assert Decimal(expanded["ebitda_margin"]) == Decimal("0.15")
    assert Decimal(expanded["da_percent_revenue"]) == Decimal("0.05")
    assert Decimal(expanded["receivable_days"]) == Decimal("36.5")
    assert Decimal(expanded["inventory_days"]) == Decimal("73")
    assert expanded["derived_from_baseline"]["interest_expense"] is True
    assert raw == {"revenue_growth": ["0.1"], "tax_rate": "0.25"}
