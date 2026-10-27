"""Assemble exportable analyst reports from stored observations and calculations."""

from __future__ import annotations

import csv
import io
import sqlite3
from typing import Iterable

from finsight.analytics.insights import build_financial_insights
from finsight.analytics.models import RiskAssessment
from finsight.metrics.models import FinancialObservation, MetricResult
from finsight.metrics.repository import company_provenance, list_company_observations


def build_company_report(
    connection: sqlite3.Connection,
    company_id: str,
    statement_basis: str,
    observations: Iterable[FinancialObservation],
    metrics: Iterable[MetricResult],
    assessments: Iterable[RiskAssessment],
    configuration_version: str,
    peer_benchmark: dict[str, object] | None = None,
) -> dict[str, object]:
    """Create a deterministic JSON-ready report without storing derived output."""
    company = connection.execute(
        "SELECT company_id, company_name, ticker, reporting_currency FROM companies WHERE company_id = ?",
        (company_id,),
    ).fetchone()
    metric_items = list(metrics)
    assessment_items = list(assessments)
    observation_items = list(observations)
    years = sorted({item.financial_year for item in observation_items})
    return {
        "report_version": "finsight-analyst-report-v1",
        "report_status": "available" if observation_items else "insufficient_data",
        "company": dict(company) if company is not None else None,
        "statement_basis": statement_basis,
        "periods": years,
        "source_backed_observation_count": len(observation_items),
        "reported_observations": list_company_observations(connection, company_id, statement_basis),
        "provenance": company_provenance(connection, company_id, statement_basis),
        "metrics": [metric.to_dict() for metric in metric_items],
        "risk_configuration_version": configuration_version,
        "risk_assessments": [assessment.to_dict() for assessment in assessment_items],
        "insights": build_financial_insights(metric_items, assessment_items, peer_benchmark),
        "peer_benchmark": peer_benchmark,
        "missing_data": [
            {"metric_id": metric.metric_id, "financial_year": metric.financial_year, "status": metric.status, "explanation": metric.explanation}
            for metric in metric_items if metric.status != "calculated"
        ],
        "limitations": [
            "Metrics depend on the standardized mapping of source-reported line items and the disclosed formulas.",
            "Missing inputs are not imputed; incompatible currencies, units, statement bases, or periods are not converted or bridged.",
            "Risk thresholds are provisional screening heuristics and are not investment recommendations or evidence of misconduct, insolvency, or distress.",
            "Source references are recorded, but source documents and reported figures have not been independently verified by this software.",
            "Peer benchmarking is a separate endpoint and is included only when compatible peer records are explicitly selected.",
        ],
    }


def report_csv(metrics: Iterable[MetricResult]) -> str:
    """Flatten calculated/reportable metrics while keeping provenance references."""
    stream = io.StringIO(newline="")
    columns = ("metric_id", "metric_name", "financial_year", "period_start", "period_end", "statement_basis", "value", "unit", "currency", "status", "formula", "formula_version", "explanation", "source_ids", "observation_ids")
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for metric in metrics:
        inputs = metric.input_observations
        writer.writerow({
            "metric_id": metric.metric_id,
            "metric_name": metric.metric_name,
            "financial_year": metric.financial_year,
            "period_start": metric.period_start.isoformat(),
            "period_end": metric.period_end.isoformat(),
            "statement_basis": metric.statement_basis,
            "value": str(metric.value) if metric.value is not None else "",
            "unit": metric.unit,
            "currency": metric.currency or "",
            "status": metric.status,
            "formula": metric.formula,
            "formula_version": metric.formula_version,
            "explanation": metric.explanation,
            "source_ids": ";".join(dict.fromkeys(item.source_id for item in inputs)),
            "observation_ids": ";".join(str(item.observation_id) for item in inputs),
        })
    return stream.getvalue()
