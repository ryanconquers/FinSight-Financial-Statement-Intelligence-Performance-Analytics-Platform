"""Explainable M4A screening rules built only from existing M3 metrics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Callable, Iterable

from finsight.analytics.config import RiskThresholds
from finsight.analytics.models import AssessmentStatus, RiskAssessment
from finsight.metrics.models import FinancialObservation, MetricResult

_YEAR_PATTERN = re.compile(r"^FY(\d{4})$")
_FLAG_INTERPRETATION = (
    "The configured screening condition was met. This is an analytical signal for review, "
    "not a conclusion about the company."
)
_CLEAR_INTERPRETATION = (
    "The configured screening condition was not met for this assessment window; "
    "this does not establish the absence of financial risk."
)


@dataclass(frozen=True)
class _Window:
    status: AssessmentStatus
    metrics: tuple[MetricResult, ...]
    reason: str | None = None


def _year_number(year: str) -> int | None:
    match = _YEAR_PATTERN.fullmatch(year)
    return int(match.group(1)) if match else None


def _periods_advance(previous: MetricResult, current: MetricResult) -> bool:
    previous_year = _year_number(previous.financial_year)
    current_year = _year_number(current.financial_year)
    return previous_year is not None and current_year == previous_year + 1 and previous.period_end + timedelta(days=1) == current.period_start


def _metric_window(
    by_metric: dict[str, dict[str, MetricResult]], metric_id: str, years: tuple[str, ...]
) -> _Window:
    available = tuple(by_metric.get(metric_id, {}).get(year) for year in years)
    evidence = tuple(metric for metric in available if metric is not None)
    if any(metric.status == "invalid_input" for metric in evidence):
        return _Window("invalid_input", evidence, f"{metric_id} contains an invalid M3 metric input.")
    if any(metric is None for metric in available):
        return _Window("insufficient_data", evidence, f"{metric_id} is missing for one or more required fiscal years.")
    metrics = tuple(metric for metric in available if metric is not None)
    if any(metric.status != "calculated" or metric.value is None for metric in metrics):
        return _Window("insufficient_data", metrics, f"{metric_id} is unavailable for one or more required fiscal years.")
    if any(_year_number(year) is None for year in years):
        return _Window("invalid_input", metrics, "Financial years must use the documented FYYYYY format.")
    if any(metric.unit != metrics[0].unit or metric.currency != metrics[0].currency for metric in metrics[1:]):
        return _Window("invalid_input", metrics, f"{metric_id} changes unit or currency across the comparison window.")
    evidence_units: list[tuple[str, str]] = []
    for metric in metrics:
        refs = metric.input_observations
        if refs:
            if any(ref.company_id != metric.company_id or ref.statement_basis != metric.statement_basis for ref in refs):
                return _Window("invalid_input", metrics, f"{metric_id} has evidence from a different company or statement basis.")
            metadata = {(ref.unit, ref.currency) for ref in refs}
            if len(metadata) != 1:
                return _Window("invalid_input", metrics, f"{metric_id} has incompatible evidence units or currencies.")
            evidence_units.extend(metadata)
    if evidence_units and any(metadata != evidence_units[0] for metadata in evidence_units[1:]):
        return _Window("invalid_input", metrics, f"{metric_id} evidence changes unit or currency across the comparison window.")
    if any(not _periods_advance(left, right) for left, right in zip(metrics, metrics[1:])):
        return _Window("insufficient_data", metrics, "Required fiscal periods are not contiguous annual periods.")
    return _Window("not_flagged", metrics)


def _net_income_observation(metric: MetricResult) -> FinancialObservation | None:
    for observation in metric.input_observations:
        if observation.line_item_id == "net_income":
            return observation
    return None


def _assessment(
    *,
    rule_id: str,
    title: str,
    status: AssessmentStatus,
    company_id: str,
    statement_basis: str,
    latest_year: str,
    thresholds: RiskThresholds,
    threshold_values: dict[str, Decimal | int],
    periods: tuple[str, ...],
    comparison: str,
    fact: str,
    reason: str | None,
    evidence: tuple[MetricResult, ...],
) -> RiskAssessment:
    interpretation = _FLAG_INTERPRETATION if status == "flagged" else _CLEAR_INTERPRETATION
    if status == "insufficient_data":
        interpretation = "This rule could not be evaluated from the available compatible observations."
    elif status == "invalid_input":
        interpretation = "This rule was not evaluated because an input was invalid or incompatible."
    return RiskAssessment(
        rule_id=rule_id,
        title=title,
        status=status,
        company_id=company_id,
        statement_basis=statement_basis,
        financial_year=latest_year,
        configuration_version=thresholds.version,
        thresholds=threshold_values,
        periods=periods,
        comparison=comparison,
        fact=fact,
        interpretation=interpretation,
        reason=reason,
        evidence=evidence,
    )


def analyze_financial_risk(
    metric_results: Iterable[MetricResult], thresholds: RiskThresholds
) -> list[RiskAssessment]:
    """Evaluate documented screening rules over one company's existing M3 metrics.

    The engine does not calculate financial ratios, fill missing values, or compare
    metrics across companies, statement bases, currencies, units, or non-adjacent periods.
    """
    items = list(metric_results)
    if not items:
        return []
    companies = {item.company_id for item in items}
    bases = {item.statement_basis for item in items}
    if len(companies) != 1 or len(bases) != 1:
        raise ValueError("Analyze one company and one statement basis at a time.")

    by_metric: dict[str, dict[str, MetricResult]] = {}
    for item in items:
        year_results = by_metric.setdefault(item.metric_id, {})
        if item.financial_year in year_results:
            raise ValueError(f"Duplicate metric result for {item.metric_id} {item.financial_year}.")
        year_results[item.financial_year] = item
    year_numbers = [_year_number(item.financial_year) for item in items]
    if any(year is None for year in year_numbers):
        raise ValueError("Financial years must use the documented FYYYYY format.")
    latest_number = max(year for year in year_numbers if year is not None)
    latest_year = f"FY{latest_number:04d}"
    company_id = next(iter(companies))
    basis = next(iter(bases))
    assessments: list[RiskAssessment] = []

    def evaluate_window(
        *, rule_id: str, title: str, metric_id: str, years: tuple[str, ...],
        configured: dict[str, Decimal | int], comparison: str,
        predicate, fact_builder,
    ) -> None:
        window = _metric_window(by_metric, metric_id, years)
        status = window.status
        fact = window.reason or "Required M3 metrics were available."
        reason = window.reason
        if status == "not_flagged":
            status = "flagged" if predicate(window.metrics) else "not_flagged"
            fact = fact_builder(window.metrics)
            reason = "Configured threshold met." if status == "flagged" else "Configured threshold not met."
        assessments.append(_assessment(
            rule_id=rule_id, title=title, status=status, company_id=company_id,
            statement_basis=basis, latest_year=latest_year, thresholds=thresholds,
            threshold_values=configured, periods=years, comparison=comparison,
            fact=fact, reason=reason, evidence=window.metrics,
        ))

    revenue_years = tuple(f"FY{year:04d}" for year in range(latest_number - thresholds.revenue_decline_consecutive_years + 1, latest_number + 1))
    evaluate_window(
        rule_id="revenue_decline", title="Revenue decline", metric_id="revenue_growth",
        years=revenue_years,
        configured={"growth_below": thresholds.revenue_growth_below, "consecutive_years": thresholds.revenue_decline_consecutive_years},
        comparison=f"revenue_growth < {thresholds.revenue_growth_below} in every period",
        predicate=lambda values: all(item.value < thresholds.revenue_growth_below for item in values),
        fact_builder=lambda values: "Revenue growth: " + ", ".join(f"{item.financial_year} {item.value * 100:.2f}%" for item in values) + ".",
    )

    margin_years = tuple(f"FY{year:04d}" for year in range(latest_number - thresholds.margin_decline_lookback_years, latest_number + 1))
    for metric_id, title in (
        ("ebitda_margin", "EBITDA margin deterioration"),
        ("ebit_margin", "EBIT margin deterioration"),
        ("net_profit_margin", "Net profit margin deterioration"),
    ):
        evaluate_window(
            rule_id=f"{metric_id}_decline", title=title, metric_id=metric_id,
            years=margin_years,
            configured={"lookback_years": thresholds.margin_decline_lookback_years, "decline_ratio_at_least": thresholds.margin_decline_ratio},
            comparison=f"margin at start − latest margin >= {thresholds.margin_decline_ratio} ratio units",
            predicate=lambda values: values[0].value - values[-1].value >= thresholds.margin_decline_ratio,
            fact_builder=lambda values: f"{metric_id} moved from {values[0].value * 100:.2f}% in {values[0].financial_year} to {values[-1].value * 100:.2f}% in {values[-1].financial_year}.",
        )

    ocf_years = tuple(f"FY{year:04d}" for year in range(latest_number - thresholds.ocf_conversion_consecutive_years + 1, latest_number + 1))
    ocf_window = _metric_window(by_metric, "ocf_net_income", ocf_years)
    ocf_reason = ocf_window.reason
    ocf_status = ocf_window.status
    if ocf_status == "not_flagged":
        net_income_observations = [_net_income_observation(item) for item in ocf_window.metrics]
        if any(observation is None for observation in net_income_observations):
            ocf_status, ocf_reason = "invalid_input", "OCF/net-income evidence is missing its net income observation."
        elif any(
            observation.value is None
            or observation.financial_year != metric.financial_year
            or (observation.period_start, observation.period_end) != (metric.period_start, metric.period_end)
            for metric, observation in zip(ocf_window.metrics, net_income_observations)
            if observation is not None
        ):
            ocf_status, ocf_reason = "invalid_input", "OCF/net-income evidence has missing or mismatched net income period data."
        elif any(observation.value <= 0 for observation in net_income_observations if observation is not None and observation.value is not None):
            ocf_status, ocf_reason = "insufficient_data", "The cash-conversion rule applies only when net income is positive in every period."
    if ocf_status == "not_flagged":
        ocf_flagged = all(item.value < thresholds.ocf_to_net_income_below for item in ocf_window.metrics)
        ocf_status = "flagged" if ocf_flagged else "not_flagged"
        ocf_reason = "Configured threshold met." if ocf_flagged else "Configured threshold not met."
    ocf_fact = ocf_reason or "OCF/net income was available."
    if ocf_status in {"flagged", "not_flagged"}:
        ocf_fact = "OCF/net income: " + ", ".join(f"{item.financial_year} {item.value:.3f}×" for item in ocf_window.metrics) + "."
    assessments.append(_assessment(
        rule_id="weak_cash_conversion", title="Operating cash flow conversion", status=ocf_status,
        company_id=company_id, statement_basis=basis, latest_year=latest_year,
        thresholds=thresholds,
        threshold_values={"ocf_to_net_income_below": thresholds.ocf_to_net_income_below, "consecutive_years": thresholds.ocf_conversion_consecutive_years},
        periods=ocf_years,
        comparison=f"ocf_net_income < {thresholds.ocf_to_net_income_below} in every period, with net income > 0",
        fact=ocf_fact, reason=ocf_reason, evidence=ocf_window.metrics,
    ))

    for metric_id, title, threshold_name, threshold, operator, predicate, unit in (
        ("net_debt_to_ebitda", "Net debt / EBITDA", "net_debt_to_ebitda_above", thresholds.net_debt_to_ebitda_above, ">", lambda value: value > thresholds.net_debt_to_ebitda_above, "×"),
        ("debt_to_equity", "Debt / equity", "debt_to_equity_above", thresholds.debt_to_equity_above, ">", lambda value: value > thresholds.debt_to_equity_above, "×"),
        ("interest_coverage", "Interest coverage", "interest_coverage_below", thresholds.interest_coverage_below, "<", lambda value: value < thresholds.interest_coverage_below, "×"),
    ):
        window = _metric_window(by_metric, metric_id, (latest_year,))
        status = window.status
        reason = window.reason
        fact = reason or "Required M3 metric was available."
        if status == "not_flagged":
            value = window.metrics[0].value
            status = "flagged" if predicate(value) else "not_flagged"
            reason = "Configured threshold met." if status == "flagged" else "Configured threshold not met."
            fact = f"{metric_id} for {latest_year}: {value:.3f}{unit}."
        assessments.append(_assessment(
            rule_id=metric_id, title=title, status=status, company_id=company_id,
            statement_basis=basis, latest_year=latest_year, thresholds=thresholds,
            threshold_values={threshold_name: threshold}, periods=(latest_year,),
            comparison=f"{metric_id} {operator} {threshold}{unit}", fact=fact,
            reason=reason, evidence=window.metrics,
        ))

    wc_period_count = thresholds.working_capital_increase_consecutive_years + 1
    wc_years = tuple(f"FY{year:04d}" for year in range(latest_number - wc_period_count + 1, latest_number + 1))
    for metric_id, title, threshold_name, threshold in (
        ("receivable_days", "Receivables days increase", "receivable_days_increase_at_least", thresholds.receivable_days_increase_at_least),
        ("inventory_days", "Inventory days increase", "inventory_days_increase_at_least", thresholds.inventory_days_increase_at_least),
    ):
        window = _metric_window(by_metric, metric_id, wc_years)
        status = window.status
        reason = window.reason
        fact = reason or f"{metric_id} was available."
        if status == "not_flagged":
            changes = [right.value - left.value for left, right in zip(window.metrics, window.metrics[1:])]
            status = "flagged" if all(change >= threshold for change in changes) else "not_flagged"
            reason = "Configured threshold met." if status == "flagged" else "Configured threshold not met."
            fact = f"{metric_id} annual changes: " + ", ".join(f"{value:+.1f} days" for value in changes) + "."
        assessments.append(_assessment(
            rule_id=f"{metric_id}_increase", title=title, status=status,
            company_id=company_id, statement_basis=basis, latest_year=latest_year,
            thresholds=thresholds,
            threshold_values={threshold_name: threshold, "consecutive_increases": thresholds.working_capital_increase_consecutive_years},
            periods=wc_years,
            comparison=f"year-over-year increase >= {threshold} days in every comparison",
            fact=fact, reason=reason, evidence=window.metrics,
        ))

    fcf_years = tuple(f"FY{year:04d}" for year in range(latest_number - thresholds.negative_fcf_consecutive_years + 1, latest_number + 1))
    evaluate_window(
        rule_id="negative_free_cash_flow", title="Negative free cash flow", metric_id="free_cash_flow",
        years=fcf_years,
        configured={"free_cash_flow_below": thresholds.negative_fcf_below, "consecutive_years": thresholds.negative_fcf_consecutive_years},
        comparison=f"free_cash_flow < {thresholds.negative_fcf_below} in every period",
        predicate=lambda values: all(item.value < thresholds.negative_fcf_below for item in values),
        fact_builder=lambda values: "Free cash flow: " + ", ".join(f"{item.financial_year} {item.value} {item.unit} {item.currency or ''}".strip() for item in values) + ".",
    )

    return assessments
