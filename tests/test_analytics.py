"""M4A rule tests use generated, test-only metric results and observations."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from finsight.analytics.config import load_risk_thresholds, thresholds_from_mapping
from finsight.analytics.risk import analyze_financial_risk
from finsight.metrics.models import FinancialObservation, MetricResult

CONFIG = {
    "meta": {"version": "test-risk-v1"},
    "thresholds": {
        "revenue_growth_below": "0",
        "revenue_decline_consecutive_years": 2,
        "margin_decline_lookback_years": 2,
        "margin_decline_ratio": "0.05",
        "ocf_to_net_income_below": "0.8",
        "ocf_conversion_consecutive_years": 2,
        "net_debt_to_ebitda_above": "3.0",
        "debt_to_equity_above": "2.0",
        "interest_coverage_below": "1.5",
        "receivable_days_increase_at_least": "15",
        "inventory_days_increase_at_least": "15",
        "working_capital_increase_consecutive_years": 2,
        "negative_fcf_below": "0",
        "negative_fcf_consecutive_years": 2,
    },
}


def metric(metric_id, year, value, *, unit="ratio", currency=None, status="calculated", start=None, end=None, evidence=()):
    number = int(year[2:])
    start = start or date(number - 1, 4, 1)
    end = end or date(number, 3, 31)
    return MetricResult(
        metric_id=metric_id,
        metric_name=metric_id.replace("_", " "),
        company_id="TEST_CO",
        financial_year=year,
        period_start=start,
        period_end=end,
        statement_basis="consolidated",
        value=Decimal(str(value)) if value is not None else None,
        unit=unit,
        currency=currency,
        status=status,
        formula="test-only M3 result",
        formula_version="finsight-metrics-v1",
        explanation="test evidence",
        input_observations=tuple(evidence),
    )


def positive_net_income_evidence(year, value=10, *, currency="INR", unit="INR_crore"):
    number = int(year[2:])
    return FinancialObservation(
        observation_id=number,
        company_id="TEST_CO",
        financial_year=year,
        period_start=date(number - 1, 4, 1),
        period_end=date(number, 3, 31),
        statement_basis="consolidated",
        statement_type="income_statement",
        line_item_id="net_income",
        value=Decimal(str(value)) if value is not None else None,
        unit=unit,
        currency=currency,
        source_id=f"TEST_SOURCE_{year}",
    )


def thresholds():
    return thresholds_from_mapping(CONFIG)


def assess(items, rule_id):
    return next(item for item in analyze_financial_risk(items, thresholds()) if item.rule_id == rule_id)


def test_default_configuration_loads_and_is_versioned():
    loaded = load_risk_thresholds("config/financial_risk_thresholds.toml")
    assert loaded.version == "m4a-risk-v1"
    assert loaded.margin_decline_ratio == Decimal("0.05")
    assert loaded.revenue_decline_consecutive_years == 2


def test_threshold_overrides_are_used_in_assessment_and_versioned():
    import copy

    document = copy.deepcopy(CONFIG)
    document["meta"]["version"] = "test-risk-v2"
    document["thresholds"]["net_debt_to_ebitda_above"] = "3.5"
    overridden = thresholds_from_mapping(document)
    result = analyze_financial_risk([metric("net_debt_to_ebitda", "FY2025", "3.2")], overridden)
    debt_result = next(item for item in result if item.rule_id == "net_debt_to_ebitda")
    assert debt_result.status == "not_flagged"
    assert debt_result.configuration_version == "test-risk-v2"
    assert debt_result.thresholds["net_debt_to_ebitda_above"] == Decimal("3.5")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda config: config["thresholds"].update(margin_decline_ratio="0"), "margin_decline_ratio"),
        (lambda config: config["thresholds"].update(revenue_decline_consecutive_years=0), "integer from 1 through 10"),
        (lambda config: config["thresholds"].update(unknown_rule=2), "unknown unknown_rule"),
        (lambda config: config["thresholds"].pop("negative_fcf_consecutive_years"), "missing negative_fcf_consecutive_years"),
        (lambda config: config["thresholds"].update(negative_fcf_below="-1"), "must be zero"),
    ],
)
def test_invalid_threshold_configuration_is_rejected(mutate, message):
    import copy

    document = copy.deepcopy(CONFIG)
    mutate(document)
    with pytest.raises(ValueError, match=message):
        thresholds_from_mapping(document)


def test_revenue_decline_requires_two_negative_periods_and_exact_zero_does_not_trigger():
    values = [metric("revenue_growth", "FY2024", "-0.01"), metric("revenue_growth", "FY2025", "-0.02")]
    result = assess(values, "revenue_decline")
    assert result.status == "flagged"
    assert result.periods == ("FY2024", "FY2025")
    assert "FY2025 -2.00%" in result.fact
    assert result.configuration_version == "test-risk-v1"

    boundary = assess([metric("revenue_growth", "FY2024", "0"), metric("revenue_growth", "FY2025", "-0.02")], "revenue_decline")
    assert boundary.status == "not_flagged"


@pytest.mark.parametrize("metric_id", ["ebitda_margin", "ebit_margin", "net_profit_margin"])
@pytest.mark.parametrize(("current", "expected"), [("0.15", "flagged"), ("0.1501", "not_flagged")])
def test_margin_drop_uses_ratio_point_threshold_boundary(metric_id, current, expected):
    values = [metric(metric_id, "FY2023", "0.20"), metric(metric_id, "FY2024", "0.18"), metric(metric_id, "FY2025", current)]
    result = assess(values, f"{metric_id}_decline")
    assert result.status == expected
    assert result.thresholds["decline_ratio_at_least"] == Decimal("0.05")


def test_ocf_conversion_flags_only_positive_net_income_and_uses_strict_boundary():
    values = [
        metric("ocf_net_income", "FY2024", "0.79", evidence=[positive_net_income_evidence("FY2024")]),
        metric("ocf_net_income", "FY2025", "0.8", evidence=[positive_net_income_evidence("FY2025")]),
    ]
    assert assess(values, "weak_cash_conversion").status == "not_flagged"
    values[-1] = metric("ocf_net_income", "FY2025", "-0.2", evidence=[positive_net_income_evidence("FY2025")])
    assert assess(values, "weak_cash_conversion").status == "flagged"

    negative_ni = [metric("ocf_net_income", "FY2024", "0.2", evidence=[positive_net_income_evidence("FY2024", -1)]), values[-1]]
    result = assess(negative_ni, "weak_cash_conversion")
    assert result.status == "insufficient_data"
    assert "net income is positive" in result.reason

    zero_ni = [metric("ocf_net_income", "FY2024", None, status="invalid_input", evidence=[positive_net_income_evidence("FY2024", 0)]), values[-1]]
    assert assess(zero_ni, "weak_cash_conversion").status == "invalid_input"


@pytest.mark.parametrize(
    ("metric_id", "value", "boundary", "rule_id"),
    [
        ("net_debt_to_ebitda", "3.0001", "3.0", "net_debt_to_ebitda"),
        ("debt_to_equity", "2.0001", "2.0", "debt_to_equity"),
        ("interest_coverage", "1.4999", "1.5", "interest_coverage"),
    ],
)
def test_leverage_and_coverage_rules_trigger_beyond_strict_boundaries(metric_id, value, boundary, rule_id):
    assert assess([metric(metric_id, "FY2025", value)], rule_id).status == "flagged"
    assert assess([metric(metric_id, "FY2025", boundary)], rule_id).status == "not_flagged"


@pytest.mark.parametrize(("metric_id", "boundary", "rule_id"), [
    ("receivable_days", "receivable_days_increase_at_least", "receivable_days_increase"),
    ("inventory_days", "inventory_days_increase_at_least", "inventory_days_increase"),
])
def test_working_capital_days_rule_includes_exact_increase_boundary(metric_id, boundary, rule_id):
    amounts = [10, 25, 40]
    values = [metric(metric_id, f"FY{year}", amount, unit="days") for year, amount in zip((2023, 2024, 2025), amounts)]
    assert assess(values, rule_id).status == "flagged"
    assert assess([metric(metric_id, "FY2023", 10, unit="days"), metric(metric_id, "FY2024", 25, unit="days"), metric(metric_id, "FY2025", 39.99, unit="days")], rule_id).status == "not_flagged"
    assert assess(values, rule_id).thresholds[boundary] == Decimal("15")


def test_negative_free_cash_flow_requires_consecutive_negative_years_and_excludes_zero():
    values = [metric("free_cash_flow", "FY2024", "-1", unit="INR_crore", currency="INR"), metric("free_cash_flow", "FY2025", "-0.01", unit="INR_crore", currency="INR")]
    result = assess(values, "negative_free_cash_flow")
    assert result.status == "flagged"
    assert result.evidence[0].input_observations == ()
    assert assess([values[0], metric("free_cash_flow", "FY2025", "0", unit="INR_crore", currency="INR")], "negative_free_cash_flow").status == "not_flagged"


def test_missing_invalid_gap_and_incompatible_metric_windows_are_not_filled_or_bridged():
    assert assess([metric("revenue_growth", "FY2025", "-0.1")], "revenue_decline").status == "insufficient_data"
    invalid = [metric("revenue_growth", "FY2024", None, status="invalid_input"), metric("revenue_growth", "FY2025", "-0.1")]
    assert assess(invalid, "revenue_decline").status == "invalid_input"

    gap = [metric("revenue_growth", "FY2023", "-0.1"), metric("revenue_growth", "FY2025", "-0.1")]
    assert assess(gap, "revenue_decline").status == "insufficient_data"

    incompatible = [metric("free_cash_flow", "FY2024", "-1", unit="INR_crore", currency="INR"), metric("free_cash_flow", "FY2025", "-2", unit="USD_million", currency="USD")]
    assert assess(incompatible, "negative_free_cash_flow").status == "invalid_input"

    noncontiguous = [
        metric("free_cash_flow", "FY2024", "-1", unit="INR_crore", currency="INR"),
        metric("free_cash_flow", "FY2025", "-2", unit="INR_crore", currency="INR", start=date(2024, 4, 2)),
    ]
    assert assess(noncontiguous, "negative_free_cash_flow").status == "insufficient_data"


@pytest.mark.parametrize("metric_id", ["net_debt_to_ebitda", "debt_to_equity", "interest_coverage"])
def test_zero_or_negative_denominator_metric_invalidity_is_not_screened(metric_id):
    invalid_metric = metric(metric_id, "FY2025", None, status="invalid_input")
    assert assess([invalid_metric], metric_id).status == "invalid_input"


def test_unavailable_metrics_and_invalid_working_capital_values_are_not_treated_as_zero():
    assert assess([metric("free_cash_flow", "FY2025", None, status="unavailable")], "negative_free_cash_flow").status == "insufficient_data"
    wc = [metric("receivable_days", "FY2024", 10, unit="days"), metric("receivable_days", "FY2025", None, unit="days", status="invalid_input")]
    assert assess(wc, "receivable_days_increase").status == "invalid_input"


def test_ocf_rule_rejects_missing_net_income_evidence_and_company_basis_mixes():
    missing_evidence = [metric("ocf_net_income", "FY2024", "0.5"), metric("ocf_net_income", "FY2025", "0.5")]
    assert assess(missing_evidence, "weak_cash_conversion").status == "invalid_input"
    wrong_period = [
        metric("ocf_net_income", "FY2024", "0.5", evidence=[positive_net_income_evidence("FY2024")]),
        metric("ocf_net_income", "FY2025", "0.5", evidence=[positive_net_income_evidence("FY2024")]),
    ]
    assert assess(wrong_period, "weak_cash_conversion").status == "invalid_input"
    with pytest.raises(ValueError, match="one company and one statement basis"):
        analyze_financial_risk([metric("revenue_growth", "FY2025", 0), replace(metric("revenue_growth", "FY2024", 0), statement_basis="standalone")], thresholds())


@pytest.mark.parametrize(("year", "unit", "currency"), [(2024, "INR_crore", "USD"), (2025, "USD_million", "USD")])
def test_ratio_series_checks_source_evidence_currency_and_unit(year, unit, currency):
    item_year = f"FY{year}"
    evidence = positive_net_income_evidence(item_year, currency=currency, unit=unit)
    values = [
        metric("ocf_net_income", "FY2024", "0.5", evidence=[positive_net_income_evidence("FY2024", currency="INR", unit="INR_crore")]),
        metric("ocf_net_income", "FY2025", "0.5", evidence=[positive_net_income_evidence("FY2025", currency="INR", unit="INR_crore")]),
    ]
    values[year - 2024] = metric("ocf_net_income", item_year, "0.5", evidence=[evidence])
    result = assess(values, "weak_cash_conversion")
    assert result.status == "invalid_input"
    assert "evidence changes unit or currency" in result.reason


def test_assessment_serialization_includes_thresholds_periods_and_source_evidence():
    evidence = positive_net_income_evidence("FY2024")
    item = metric("ocf_net_income", "FY2024", "0.2", evidence=[evidence])
    result = assess([item, metric("ocf_net_income", "FY2025", "0.3", evidence=[positive_net_income_evidence("FY2025")])], "weak_cash_conversion")
    payload = result.to_dict()
    assert payload["configuration_version"] == "test-risk-v1"
    assert payload["thresholds"]["ocf_to_net_income_below"] == "0.8"
    assert payload["periods"] == ["FY2024", "FY2025"]
    assert payload["evidence"][0]["inputs"][0]["observation_id"] == evidence.observation_id
    assert payload["evidence"][0]["inputs"][0]["source_id"] == evidence.source_id
