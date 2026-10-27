"""Deterministic, evidence-linked descriptions of observed metric changes."""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal
from typing import Iterable

from finsight.analytics.models import RiskAssessment
from finsight.metrics.models import MetricResult

_FINANCIAL_YEAR = re.compile(r"^FY\d{4}$")


def build_financial_insights(
    metric_results: Iterable[MetricResult],
    assessments: Iterable[RiskAssessment] = (),
    peer_benchmark: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """Describe supported trends without inferring causes or future outcomes."""
    items = list(metric_results)
    assessment_items = list(assessments)
    if len({item.company_id for item in items}) > 1 or len({item.statement_basis for item in items}) > 1:
        raise ValueError("Build insights for one company and one statement basis at a time.")
    if assessment_items and not items:
        raise ValueError("Risk assessments require matching M3 metric results.")
    if items and any(item.company_id != items[0].company_id or item.statement_basis != items[0].statement_basis for item in assessment_items):
        raise ValueError("Risk assessments must match the insight company's statement basis.")
    keys = [(item.metric_id, item.financial_year) for item in items]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate metric results are not valid insight inputs.")
    insights: list[dict[str, object]] = []

    def add_change(metric_id: str, title: str, unit_label: str, *, direction: str = "") -> None:
        series = sorted((item for item in items if item.metric_id == metric_id), key=lambda item: item.financial_year)
        for prior, current in zip(series, series[1:]):
            if prior.status != "calculated" or current.status != "calculated" or prior.value is None or current.value is None:
                continue
            if not _FINANCIAL_YEAR.fullmatch(prior.financial_year) or not _FINANCIAL_YEAR.fullmatch(current.financial_year):
                continue
            contiguous_year = int(prior.financial_year[2:]) + 1 == int(current.financial_year[2:])
            if not contiguous_year or prior.period_end + timedelta(days=1) != current.period_start:
                continue
            prior_days = (prior.period_end - prior.period_start).days + 1
            current_days = (current.period_end - current.period_start).days + 1
            if not 350 <= prior_days <= 380 or not 350 <= current_days <= 380:
                continue
            if prior.period_end.year != int(prior.financial_year[2:]) or current.period_end.year != int(current.financial_year[2:]):
                continue
            if (prior.statement_basis, prior.unit, prior.currency) != (current.statement_basis, current.unit, current.currency):
                continue
            if not prior.input_observations or not current.input_observations:
                continue
            prior_metadata = {(item.unit, item.currency, item.statement_basis) for item in prior.input_observations}
            current_metadata = {(item.unit, item.currency, item.statement_basis) for item in current.input_observations}
            if (
                len(prior_metadata) != 1 or prior_metadata != current_metadata
                or any(item.company_id != prior.company_id or item.statement_basis != prior.statement_basis for item in prior.input_observations)
                or any(item.company_id != current.company_id or item.statement_basis != current.statement_basis for item in current.input_observations)
            ):
                continue
            change = current.value - prior.value
            if change == 0:
                continue
            verb = "increased" if change > 0 else "decreased"
            if direction == "margin":
                verb = "expanded" if change > 0 else "compressed"
            elif direction == "growth":
                verb = "accelerated" if change > 0 else "slowed"
            displayed_unit = f"{current.unit} {current.currency or ''}".strip() if unit_label == "amount" else unit_label
            evidence = [prior.to_dict(), current.to_dict()]
            insights.append({
                "insight_id": f"{metric_id}:{prior.financial_year}:{current.financial_year}",
                "category": "observed_trend",
                "finding": f"{title} {verb} by {change} {displayed_unit} from {prior.financial_year} to {current.financial_year}.",
                "periods": [prior.financial_year, current.financial_year],
                "rule": f"Compare adjacent calculated {metric_id} values with matching statement basis, period sequence, units, and currency.",
                "observed_values": [{"metric_id": metric_id, "financial_year": prior.financial_year, "value": str(prior.value), "unit": prior.unit, "currency": prior.currency, "status": prior.status}, {"metric_id": metric_id, "financial_year": current.financial_year, "value": str(current.value), "unit": current.unit, "currency": current.currency, "status": current.status}],
                "evidence": evidence,
                "limitations": "Observed change only; it does not establish a cause or predict future performance.",
            })

    add_change("revenue_growth", "Revenue growth", "ratio units", direction="growth")
    add_change("gross_profit", "Gross profit", "amount")
    for metric_id, title in (("gross_margin", "Gross margin"), ("ebitda_margin", "EBITDA margin"), ("ebit_margin", "EBIT margin"), ("net_profit_margin", "Net profit margin")):
        add_change(metric_id, title, "ratio units", direction="margin")
    add_change("ocf_net_income", "Operating cash flow to net income", "ratio units")
    add_change("net_debt_to_ebitda", "Net debt to EBITDA", "ratio units")
    add_change("debt_to_equity", "Debt to equity", "ratio units")
    add_change("interest_coverage", "Interest coverage", "ratio units")
    add_change("receivable_days", "Receivable days", "days")
    add_change("inventory_days", "Inventory days", "days")
    add_change("payable_days", "Payable days", "days")
    add_change("cash_conversion_cycle", "Cash conversion cycle", "days")
    add_change("free_cash_flow", "Free cash flow", "amount")

    trend_rows = [item for item in insights if item["category"] == "observed_trend"]
    revenue_rows = [item for item in trend_rows if str(item["insight_id"]).startswith("revenue_growth:")]
    margin_rows = [item for item in trend_rows if any(str(item["insight_id"]).startswith(f"{metric_id}:") for metric_id in ("gross_margin", "ebitda_margin", "ebit_margin", "net_profit_margin"))]
    for revenue in revenue_rows:
        for margin in margin_rows:
            if revenue["periods"] != margin["periods"]:
                continue
            revenue_values = revenue["observed_values"]
            margin_values = margin["observed_values"]
            revenue_delta = Decimal(str(revenue_values[1]["value"])) - Decimal(str(revenue_values[0]["value"]))
            margin_delta = Decimal(str(margin_values[1]["value"])) - Decimal(str(margin_values[0]["value"]))
            if revenue_delta * margin_delta >= 0:
                continue
            insights.append({
                "insight_id": f"contrast:{revenue['insight_id']}:{margin['insight_id']}",
                "category": "contrasting_indicators",
                "finding": f"Revenue growth {('slowed' if revenue_delta < 0 else 'accelerated')} while {margin['insight_id'].split(':', 1)[0].replace('_', ' ')} {('expanded' if margin_delta > 0 else 'compressed')} over the same periods.",
                "periods": revenue["periods"],
                "rule": "Compare the direction of adjacent revenue-growth and profitability-margin changes over identical periods.",
                "observed_values": [*revenue_values, *margin_values],
                "evidence": [*revenue["evidence"], *margin["evidence"]],
                "limitations": "These trends move in different directions; the difference does not establish a cause or predict future results.",
            })

    for assessment in assessment_items:
        if assessment.status != "flagged":
            continue
        insights.append({
            "insight_id": f"screen:{assessment.rule_id}:{assessment.financial_year}",
            "category": "screening_indicator",
            "finding": assessment.fact,
            "periods": list(assessment.periods),
            "rule": assessment.comparison,
            "observed_values": assessment.to_dict()["observed"],
            "thresholds": {key: str(value) for key, value in assessment.thresholds.items()},
            "evidence": [item.to_dict() for item in assessment.evidence],
            "limitations": "Provisional screening rule; this is not a conclusion about misconduct, solvency, distress, or investment merit.",
        })
    flagged = [assessment for assessment in assessment_items if assessment.status == "flagged"]
    if len(flagged) > 1:
        periods = sorted({period for assessment in flagged for period in assessment.periods})
        insights.append({
            "insight_id": "screen:coincident-indicators:" + ":".join(sorted(item.rule_id for item in flagged)),
            "category": "coincident_indicators",
            "finding": f"{len(flagged)} configured screening rules were met across the available assessment periods.",
            "periods": periods,
            "rule": "Count only M4A assessments with status flagged; no composite score or causal relationship is inferred.",
            "observed_values": [dict(value, rule_id=item.rule_id) for item in flagged for value in item.to_dict()["observed"]],
            "thresholds": [{key: str(value) for key, value in item.thresholds.items()} for item in flagged],
            "evidence": [metric.to_dict() for item in flagged for metric in item.evidence],
            "limitations": "Co-occurring configured indicators may reinforce the need for review, but do not prove a shared cause, misconduct, insolvency, distress, or investment merit.",
        })
    if peer_benchmark and peer_benchmark.get("status") == "available":
        for benchmark in peer_benchmark.get("metrics", []):
            if not isinstance(benchmark, dict) or benchmark.get("status") != "available" or benchmark.get("peer_median") is None:
                continue
            metric_id = str(benchmark["metric_id"])
            target = Decimal(str(benchmark["target_value"]))
            peer_median = Decimal(str(benchmark["peer_median"]))
            difference = target - peer_median
            if difference == 0:
                continue
            unit = str(benchmark.get("unit", ""))
            currency = benchmark.get("currency")
            display_unit = f"{unit} {currency or ''}".strip()
            included_values = [value for value in benchmark.get("values", []) if isinstance(value, dict)]
            evidence = [value["evidence"] for value in included_values if isinstance(value.get("evidence"), dict)]
            insights.append({
                "insight_id": f"peer:{metric_id}:{peer_benchmark.get('financial_year')}",
                "category": "peer_comparison",
                "finding": f"{metric_id} is {target} versus a selected-peer median of {peer_median}, a difference of {difference} {display_unit}.",
                "periods": [str(peer_benchmark.get("financial_year"))],
                "rule": "Subtract the median of compatible, explicitly selected peer metric values from the target metric value.",
                "observed_values": [
                    {"metric_id": metric_id, "financial_year": str(peer_benchmark.get("financial_year")), "value": str(value.get("value")), "unit": str(value.get("unit", "")), "currency": value.get("currency"), "status": "calculated", "company_id": value.get("company_id")}
                    for value in included_values
                ],
                "thresholds": {"peer_median": str(peer_median), "peer_count": int(benchmark.get("peer_count", 0))},
                "evidence": evidence,
                "limitations": "Descriptive comparison with the selected non-representative peer set; it is not a universal benchmark or a conclusion about performance quality.",
            })
    insights.sort(key=lambda item: (str(item["periods"][-1]) if item["periods"] else "", str(item["insight_id"])))
    return insights
