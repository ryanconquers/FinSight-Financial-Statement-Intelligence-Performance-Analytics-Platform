"""Typed result models for explainable rule-based financial analysis."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from finsight.metrics.models import MetricResult

AssessmentStatus = Literal["flagged", "not_flagged", "insufficient_data", "invalid_input"]


@dataclass(frozen=True)
class RiskAssessment:
    """One configured screening rule, its observation facts, and interpretation."""

    rule_id: str
    title: str
    status: AssessmentStatus
    company_id: str
    statement_basis: str
    financial_year: str
    configuration_version: str
    thresholds: dict[str, Decimal | int]
    periods: tuple[str, ...]
    comparison: str
    fact: str
    interpretation: str
    reason: str | None
    evidence: tuple[MetricResult, ...]

    def to_dict(self) -> dict[str, object]:
        """Serialize thresholds and M3 evidence without losing decimal text."""
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "status": self.status,
            "company_id": self.company_id,
            "statement_basis": self.statement_basis,
            "financial_year": self.financial_year,
            "configuration_version": self.configuration_version,
            "thresholds": {
                key: str(value) if isinstance(value, Decimal) else value
                for key, value in self.thresholds.items()
            },
            "comparison": self.comparison,
            "fact": self.fact,
            "interpretation": self.interpretation,
            "reason": self.reason,
            "periods": list(self.periods),
            "observed": [
                {
                    "metric_id": metric.metric_id,
                    "financial_year": metric.financial_year,
                    "value": str(metric.value) if metric.value is not None else None,
                    "unit": metric.unit,
                    "currency": metric.currency,
                    "status": metric.status,
                }
                for metric in self.evidence
            ],
            "evidence": [metric.to_dict() for metric in self.evidence],
        }
