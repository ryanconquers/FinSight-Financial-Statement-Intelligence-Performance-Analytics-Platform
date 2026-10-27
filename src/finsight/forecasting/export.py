"""Portable CSV export for saved, reproducible forecast snapshots."""

from __future__ import annotations

import csv
import io
import json
from typing import Any


def forecast_csv(record: dict[str, Any], *, input_data_stale: bool) -> str:
    columns = (
        "scenario", "period_type", "financial_year", "period_start", "period_end", "currency", "unit",
        "revenue", "revenue_growth", "gross_profit", "gross_margin", "cost_of_goods_sold", "operating_expenses",
        "ebitda", "ebitda_margin", "depreciation_amortization", "ebit", "interest_expense", "earnings_before_tax",
        "tax_expense", "net_income", "capital_expenditure", "accounts_receivable", "inventory", "accounts_payable",
        "net_operating_working_capital", "change_in_working_capital", "operating_cash_flow", "unlevered_free_cash_flow",
        "source_ids", "source_observation_ids", "company_id", "statement_basis", "baseline_year", "forecast_horizon",
        "assumptions_json", "scenario_adjustments_disclosure", "metric_definitions_json", "model_limitations_json",
        "methodology_version", "revision", "input_fingerprint", "input_data_stale",
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    result = record["result"]
    for scenario_name, scenario in result["scenarios"].items():
        periods = [*scenario.get("actual_history", [scenario["actual_baseline"]]), *scenario["periods"]]
        for period in periods:
            values = period.get("values", period)
            writer.writerow({
                **{key: values.get(key) for key in columns if key in values},
                "scenario": scenario_name,
                "period_type": period.get("period_type"),
                "financial_year": period.get("financial_year"),
                "period_start": period.get("period_start"),
                "period_end": period.get("period_end"),
                "currency": period.get("currency"),
                "unit": period.get("unit"),
                "source_ids": ";".join(period.get("source_ids", [])),
                "source_observation_ids": ";".join(str(value) for value in period.get("source_observation_ids", [])),
                "company_id": record["company_id"],
                "statement_basis": record["statement_basis"],
                "baseline_year": result["baseline_year"],
                "forecast_horizon": result["forecast_horizon"],
                "assumptions_json": json.dumps(record["assumptions"], sort_keys=True, separators=(",", ":")),
                "scenario_adjustments_disclosure": result.get("scenario_adjustments_disclosure"),
                "metric_definitions_json": json.dumps(result.get("metric_definitions", {}), sort_keys=True, separators=(",", ":")),
                "model_limitations_json": json.dumps(result.get("limitations", []), sort_keys=True, separators=(",", ":")),
                "methodology_version": record["methodology_version"],
                "revision": record["revision"],
                "input_fingerprint": record["input_fingerprint"],
                "input_data_stale": str(input_data_stale).lower(),
            })
    return stream.getvalue()
