"""Deterministic peer comparisons over compatible M3 metric results."""

from __future__ import annotations

from decimal import Decimal
from statistics import median
from typing import Iterable

from finsight.metrics.models import MetricResult


def build_peer_benchmark(
    company_id: str,
    peer_ids: Iterable[str],
    metric_results: dict[str, Iterable[MetricResult]],
    *,
    statement_basis: str,
    financial_year: str | None = None,
) -> dict[str, object]:
    """Compare the target to explicitly selected peers for an exact fiscal period.

    Incompatible periods, bases, units, currencies, and non-calculated results are
    excluded and described. A peer median is reported only with two valid peers.
    """
    peers = list(dict.fromkeys(peer for peer in peer_ids if peer != company_id))
    if not peers:
        raise ValueError("Select at least one peer company.")
    normalized_sets: dict[str, list[MetricResult]] = {}
    for mapped_company, results in metric_results.items():
        entries = list(results)
        seen: set[tuple[str, str]] = set()
        for item in entries:
            if item.company_id != mapped_company:
                raise ValueError("Metric results must match their mapped company identifier.")
            key = (item.metric_id, item.financial_year)
            if key in seen:
                raise ValueError(f"Duplicate metric result for {mapped_company} {item.metric_id} {item.financial_year}.")
            seen.add(key)
        normalized_sets[mapped_company] = entries
    target = normalized_sets.get(company_id, [])
    target_years = sorted({item.financial_year for item in target if item.statement_basis == statement_basis})
    year = financial_year or (target_years[-1] if target_years else None)
    if year is not None and (len(year) != 6 or not year.startswith("FY") or not year[2:].isdigit()):
        raise ValueError("Financial year must use FY followed by four digits.")
    if year is None:
        return {
            "company_id": company_id,
            "statement_basis": statement_basis,
            "financial_year": None,
            "status": "insufficient_data",
            "peers_requested": peers,
            "maximum_compatible_peer_count_for_any_metric": 0,
            "sample_disclosure": "Selected companies are an explicitly chosen comparison set and are not asserted to represent an industry or market.",
            "exclusions": {peer: ["No compatible target financial year is available."] for peer in peers},
            "metrics": [],
        }

    target_by_id = {item.metric_id: item for item in target if item.financial_year == year and item.statement_basis == statement_basis}
    all_metrics = sorted({item.metric_id for item in target if item.financial_year == year and item.statement_basis == statement_basis})
    output: list[dict[str, object]] = []
    excluded_by_peer: dict[str, list[str]] = {peer: [] for peer in peers}
    valid_peer_count = 0
    for metric_id in all_metrics:
        baseline = target_by_id.get(metric_id)
        if baseline is None or baseline.status != "calculated" or baseline.value is None:
            output.append({"metric_id": metric_id, "status": "insufficient_data", "reason": "Target metric is not calculated for this period.", "values": []})
            continue
        baseline_days = (baseline.period_end - baseline.period_start).days + 1
        if not 350 <= baseline_days <= 380 or baseline.period_end.year != int(year[2:]):
            output.append({"metric_id": metric_id, "status": "insufficient_data", "reason": "Target metric does not cover a compatible annual period.", "values": []})
            continue
        included: list[dict[str, object]] = [{"company_id": company_id, "value": str(baseline.value), "unit": baseline.unit, "currency": baseline.currency, "period_start": baseline.period_start.isoformat(), "period_end": baseline.period_end.isoformat(), "is_target": True, "evidence": baseline.to_dict()}]
        for peer in peers:
            candidates = [item for item in normalized_sets.get(peer, ()) if item.metric_id == metric_id and item.financial_year == year]
            candidate = candidates[0] if len(candidates) == 1 else None
            reason = None
            if candidate is None:
                reason = "Metric or unique period result is missing."
            elif candidate.status != "calculated" or candidate.value is None:
                reason = f"Metric status is {candidate.status}."
            elif candidate.statement_basis != statement_basis:
                reason = "Statement basis differs."
            elif (candidate.period_start, candidate.period_end) != (baseline.period_start, baseline.period_end):
                reason = "Reporting period dates differ."
            elif not 350 <= (baseline.period_end - baseline.period_start).days + 1 <= 380:
                reason = "Reporting period is not annual."
            elif (candidate.unit, candidate.currency) != (baseline.unit, baseline.currency):
                reason = "Metric unit or currency differs."
            elif not baseline.input_observations or not candidate.input_observations:
                reason = "Source observation references are unavailable."
            elif {
                (item.unit, item.currency, item.statement_basis, item.period_start, item.period_end)
                for item in baseline.input_observations
            } != {
                (item.unit, item.currency, item.statement_basis, item.period_start, item.period_end)
                for item in candidate.input_observations
            }:
                reason = "Input provenance uses incompatible units, currencies, bases, or periods."
            if reason:
                excluded_by_peer[peer].append(f"{metric_id}: {reason}")
                continue
            assert candidate is not None and candidate.value is not None
            included.append({"company_id": peer, "value": str(candidate.value), "unit": candidate.unit, "currency": candidate.currency, "period_start": candidate.period_start.isoformat(), "period_end": candidate.period_end.isoformat(), "is_target": False, "evidence": candidate.to_dict()})
        peer_values = [Decimal(str(item["value"])) for item in included[1:]]
        if peer_values:
            valid_peer_count = max(valid_peer_count, len(peer_values))
        status = "available" if len(peer_values) >= 2 else "insufficient_data"
        output.append({
            "metric_id": metric_id,
            "status": status,
            "unit": baseline.unit,
            "currency": baseline.currency,
            "period_start": baseline.period_start.isoformat(),
            "period_end": baseline.period_end.isoformat(),
            "target_value": str(baseline.value),
            "peer_count": len(peer_values),
            "peer_median": str(Decimal(str(median(peer_values)))) if len(peer_values) >= 2 else None,
            "values": included,
            "exclusions": {peer: reasons[0] for peer, reasons in excluded_by_peer.items() if any(reason.startswith(f"{metric_id}:") for reason in reasons)},
        })
    return {
        "company_id": company_id,
        "statement_basis": statement_basis,
        "financial_year": year,
        "status": "available" if valid_peer_count >= 2 else "insufficient_data",
        "peers_requested": peers,
        "maximum_compatible_peer_count_for_any_metric": valid_peer_count,
        "sample_disclosure": "Selected companies are an explicitly chosen comparison set and are not asserted to represent an industry or market.",
        "exclusions": excluded_by_peer,
        "metrics": output,
    }
