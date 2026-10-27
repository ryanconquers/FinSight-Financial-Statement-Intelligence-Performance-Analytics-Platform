"""Typed value objects shared by the pure metrics engine and its adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

CalculationStatus = Literal["calculated", "unavailable", "invalid_input"]


@dataclass(frozen=True)
class FinancialObservation:
    """One financial statement observation with its source and period metadata."""

    observation_id: int
    company_id: str
    financial_year: str
    period_start: date
    period_end: date
    statement_basis: str
    statement_type: str
    line_item_id: str
    value: Decimal | None
    unit: str
    currency: str
    source_id: str


@dataclass(frozen=True)
class MetricResult:
    """A metric output or an explicit reason the metric could not be calculated."""

    metric_id: str
    metric_name: str
    company_id: str
    financial_year: str
    period_start: date
    period_end: date
    statement_basis: str
    value: Decimal | None
    unit: str
    currency: str | None
    status: CalculationStatus
    formula: str
    formula_version: str
    explanation: str
    input_observations: tuple[FinancialObservation, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return an API-safe representation that preserves decimal precision."""
        return {
            "metric_id": self.metric_id,
            "metric_name": self.metric_name,
            "company_id": self.company_id,
            "financial_year": self.financial_year,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "statement_basis": self.statement_basis,
            "value": str(self.value) if self.value is not None else None,
            "unit": self.unit,
            "currency": self.currency,
            "status": self.status,
            "formula": self.formula,
            "formula_version": self.formula_version,
            "explanation": self.explanation,
            "inputs": [
                {
                    "observation_id": item.observation_id,
                    "line_item_id": item.line_item_id,
                    "statement_type": item.statement_type,
                    "value": str(item.value) if item.value is not None else None,
                    "unit": item.unit,
                    "currency": item.currency,
                    "source_id": item.source_id,
                    "financial_year": item.financial_year,
                    "period_start": item.period_start.isoformat(),
                    "period_end": item.period_end.isoformat(),
                }
                for item in self.input_observations
            ],
            "warnings": list(self.warnings),
        }
