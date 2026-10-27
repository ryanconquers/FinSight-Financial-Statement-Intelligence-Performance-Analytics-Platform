"""M4 analytics tests use clearly synthetic in-memory metric fixtures only."""

from datetime import date
from decimal import Decimal

import pytest

from finsight.analytics.benchmark import build_peer_benchmark
from finsight.analytics.config import load_risk_thresholds
from finsight.analytics.insights import build_financial_insights
from finsight.analytics.risk import analyze_financial_risk
from finsight.metrics.models import FinancialObservation, MetricResult


def source(company, year, *, currency="INR", unit="INR_crore", start=None, end=None):
    number = int(year[2:])
    return FinancialObservation(
        observation_id=number + len(company), company_id=company, financial_year=year,
        period_start=start or date(number - 1, 4, 1), period_end=end or date(number, 3, 31),
        statement_basis="consolidated", statement_type="income_statement", line_item_id="revenue",
        value=Decimal("100"), unit=unit, currency=currency, source_id=f"TEST_{company}_{year}",
    )


def metric(company, metric_id, year, value, *, unit="ratio", currency=None, refs=None, status="calculated", start=None, end=None):
    number = int(year[2:])
    return MetricResult(
        metric_id=metric_id, metric_name=metric_id, company_id=company, financial_year=year,
        period_start=start or date(number - 1, 4, 1), period_end=end or date(number, 3, 31),
        statement_basis="consolidated", value=Decimal(str(value)) if value is not None else None,
        unit=unit, currency=currency, status=status, formula="test-only formula",
        formula_version="test-v1", explanation="test-only result", input_observations=tuple(refs or ()),
    )


def revenue_history(company="TEST_CO", rates=("0.2", "0.5")):
    return [
        metric(company, "revenue_growth", "FY2024", rates[0], refs=[source(company, "FY2024")]),
        metric(company, "revenue_growth", "FY2025", rates[1], refs=[source(company, "FY2025")]),
    ]


def test_benchmark_computes_peer_median_for_compatible_companies():
    metrics = {
        "TARGET": [metric("TARGET", "revenue_growth", "FY2025", "0.2", refs=[source("TARGET", "FY2025")])],
        "PEER_A": [metric("PEER_A", "revenue_growth", "FY2025", "0.1", refs=[source("PEER_A", "FY2025")])],
        "PEER_B": [metric("PEER_B", "revenue_growth", "FY2025", "0.3", refs=[source("PEER_B", "FY2025")])],
    }
    result = build_peer_benchmark("TARGET", ["PEER_A", "PEER_B"], metrics, statement_basis="consolidated")
    assert result["status"] == "available"
    growth = result["metrics"][0]
    assert growth["peer_median"] == "0.2"
    assert growth["peer_count"] == 2
    assert growth["values"][1]["evidence"]["inputs"][0]["source_id"] == "TEST_PEER_A_FY2025"


@pytest.mark.parametrize(
    ("peer", "expected_reason"),
    [
        (metric("PEER", "revenue_growth", "FY2025", "0.1", refs=[source("PEER", "FY2025", currency="USD", unit="USD_million")]), "Input provenance"),
        (metric("PEER", "revenue_growth", "FY2025", "0.1", refs=[source("PEER", "FY2025", start=date(2024, 4, 2))]), "period"),
        (metric("PEER", "revenue_growth", "FY2025", None, status="unavailable", refs=[source("PEER", "FY2025")]), "unavailable"),
    ],
)
def test_benchmark_excludes_incompatible_or_unavailable_peer_metrics(peer, expected_reason):
    result = build_peer_benchmark(
        "TARGET", ["PEER"],
        {"TARGET": [metric("TARGET", "revenue_growth", "FY2025", "0.2", refs=[source("TARGET", "FY2025")])], "PEER": [peer]},
        statement_basis="consolidated",
    )
    assert result["status"] == "insufficient_data"
    assert result["metrics"][0]["peer_count"] == 0
    assert expected_reason.lower() in result["metrics"][0]["exclusions"]["PEER"].lower()


def test_benchmark_requires_two_peers_for_a_median_and_exact_period():
    one_peer = build_peer_benchmark(
        "TARGET", ["PEER_A"],
        {"TARGET": [metric("TARGET", "revenue_growth", "FY2025", "0.2", refs=[source("TARGET", "FY2025")])], "PEER_A": [metric("PEER_A", "revenue_growth", "FY2025", "0.1", refs=[source("PEER_A", "FY2025")])]},
        statement_basis="consolidated",
    )
    assert one_peer["status"] == "insufficient_data"
    assert one_peer["metrics"][0]["peer_median"] is None
    assert one_peer["financial_year"] == "FY2025"


def test_benchmark_rejects_empty_peer_selection():
    with pytest.raises(ValueError, match="at least one peer"):
        build_peer_benchmark("TARGET", [], {}, statement_basis="consolidated")


def test_benchmark_without_target_period_returns_complete_insufficient_data_shape():
    result = build_peer_benchmark("TARGET", ["PEER"], {"TARGET": [], "PEER": []}, statement_basis="consolidated")
    assert result["status"] == "insufficient_data"
    assert result["financial_year"] is None
    assert result["maximum_compatible_peer_count_for_any_metric"] == 0
    assert result["sample_disclosure"]
    assert result["exclusions"] == {"PEER": ["No compatible target financial year is available."]}
    assert result["metrics"] == []


def test_benchmark_rejects_duplicate_or_misassigned_metric_results():
    result = metric("TARGET", "revenue_growth", "FY2025", "0.2", refs=[source("TARGET", "FY2025")])
    peer = metric("PEER", "revenue_growth", "FY2025", "0.1", refs=[source("PEER", "FY2025")])
    with pytest.raises(ValueError, match="Duplicate metric"):
        build_peer_benchmark("TARGET", ["PEER"], {"TARGET": [result, result], "PEER": [peer]}, statement_basis="consolidated")
    with pytest.raises(ValueError, match="mapped company"):
        build_peer_benchmark("TARGET", ["PEER"], {"TARGET": [result], "PEER": [result]}, statement_basis="consolidated")


def test_benchmark_requires_annual_periods_even_when_peer_dates_match():
    short_period = metric("TARGET", "revenue_growth", "FY2025", "0.2", refs=[source("TARGET", "FY2025")], start=date(2024, 10, 1))
    peer = metric("PEER", "revenue_growth", "FY2025", "0.1", refs=[source("PEER", "FY2025", start=date(2024, 10, 1))], start=date(2024, 10, 1))
    result = build_peer_benchmark("TARGET", ["PEER", "PEER2"], {"TARGET": [short_period], "PEER": [peer]}, statement_basis="consolidated")
    assert result["status"] == "insufficient_data"
    assert "annual period" in result["metrics"][0]["reason"]


def test_insights_only_describe_adjacent_compatible_calculated_values_with_evidence():
    results = revenue_history()
    insights = build_financial_insights(results)
    trend = next(item for item in insights if item["category"] == "observed_trend")
    assert "accelerated" in trend["finding"]
    assert trend["periods"] == ["FY2024", "FY2025"]
    assert len(trend["evidence"]) == 2
    assert trend["evidence"][0]["inputs"][0]["source_id"] == "TEST_TEST_CO_FY2024"
    assert "does not establish a cause" in trend["limitations"]


def test_insights_do_not_bridge_gaps_or_compare_incompatible_currencies():
    gap = [metric("TEST_CO", "ebitda_margin", "FY2023", "0.2", refs=[source("TEST_CO", "FY2023")]), metric("TEST_CO", "ebitda_margin", "FY2025", "0.1", refs=[source("TEST_CO", "FY2025")])]
    assert build_financial_insights(gap) == []
    incompatible = [
        metric("TEST_CO", "ebitda_margin", "FY2024", "0.2", refs=[source("TEST_CO", "FY2024")]),
        metric("TEST_CO", "ebitda_margin", "FY2025", "0.1", refs=[source("TEST_CO", "FY2025", currency="USD", unit="USD_million")]),
    ]
    assert build_financial_insights(incompatible) == []
    non_annual = [
        metric("TEST_CO", "ebitda_margin", "FY2024", "0.2", refs=[source("TEST_CO", "FY2024")], start=date(2023, 10, 1)),
        metric("TEST_CO", "ebitda_margin", "FY2025", "0.1", refs=[source("TEST_CO", "FY2025")]),
    ]
    assert build_financial_insights(non_annual) == []


def test_risk_assessment_does_not_treat_adjacent_short_periods_as_annual():
    items = [
        metric("TEST_CO", "revenue_growth", "FY2024", "-0.1", start=date(2023, 10, 1)),
        metric("TEST_CO", "revenue_growth", "FY2025", "-0.2"),
    ]
    result = analyze_financial_risk(items, load_risk_thresholds("config/financial_risk_thresholds.toml"))
    revenue_rule = next(item for item in result if item.rule_id == "revenue_decline")
    assert revenue_rule.status == "insufficient_data"


def test_insights_group_coincident_flags_without_claiming_causality():
    results = [
        metric("TEST_CO", "revenue_growth", "FY2024", "-0.1", refs=[source("TEST_CO", "FY2024")]),
        metric("TEST_CO", "revenue_growth", "FY2025", "-0.2", refs=[source("TEST_CO", "FY2025")]),
        metric("TEST_CO", "net_debt_to_ebitda", "FY2025", "4.0", refs=[source("TEST_CO", "FY2025")]),
    ]
    assessments = analyze_financial_risk(results, load_risk_thresholds("config/financial_risk_thresholds.toml"))
    insights = build_financial_insights(results, assessments)
    grouped = next(item for item in insights if item["category"] == "coincident_indicators")
    assert "2 configured screening rules" in grouped["finding"]
    assert "no composite score" in grouped["rule"]
    assert "do not prove a shared cause" in grouped["limitations"]


def test_insights_describe_contrasting_growth_and_margin_directions():
    results = [
        metric("TEST_CO", "revenue_growth", "FY2024", "0.2", refs=[source("TEST_CO", "FY2024")]),
        metric("TEST_CO", "revenue_growth", "FY2025", "0.1", refs=[source("TEST_CO", "FY2025")]),
        metric("TEST_CO", "ebitda_margin", "FY2024", "0.1", refs=[source("TEST_CO", "FY2024")]),
        metric("TEST_CO", "ebitda_margin", "FY2025", "0.2", refs=[source("TEST_CO", "FY2025")]),
    ]
    insight = next(item for item in build_financial_insights(results) if item["category"] == "contrasting_indicators")
    assert "slowed while ebitda margin expanded" in insight["finding"]
    assert len(insight["evidence"]) == 4


def test_insights_include_numeric_peer_comparison_and_source_evidence():
    target_metrics = [metric("TARGET", "revenue_growth", "FY2025", "0.25", refs=[source("TARGET", "FY2025")])]
    benchmark = build_peer_benchmark(
        "TARGET", ["PEER_A", "PEER_B"],
        {
            "TARGET": target_metrics,
            "PEER_A": [metric("PEER_A", "revenue_growth", "FY2025", "0.1", refs=[source("PEER_A", "FY2025")])],
            "PEER_B": [metric("PEER_B", "revenue_growth", "FY2025", "0.3", refs=[source("PEER_B", "FY2025")])],
        },
        statement_basis="consolidated",
    )
    insight = next(item for item in build_financial_insights(target_metrics, peer_benchmark=benchmark) if item["category"] == "peer_comparison")
    assert "versus a selected-peer median of 0.2" in insight["finding"]
    assert insight["evidence"][1]["inputs"][0]["source_id"] == "TEST_PEER_A_FY2025"
    assert "not a universal benchmark" in insight["limitations"]
