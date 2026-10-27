"""Loading and validation for M4A's provisional screening thresholds."""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RiskThresholds:
    """Versioned, explicit thresholds used by the risk rules engine."""

    version: str
    revenue_growth_below: Decimal
    revenue_decline_consecutive_years: int
    margin_decline_lookback_years: int
    margin_decline_ratio: Decimal
    ocf_to_net_income_below: Decimal
    ocf_conversion_consecutive_years: int
    net_debt_to_ebitda_above: Decimal
    debt_to_equity_above: Decimal
    interest_coverage_below: Decimal
    receivable_days_increase_at_least: Decimal
    inventory_days_increase_at_least: Decimal
    working_capital_increase_consecutive_years: int
    negative_fcf_below: Decimal
    negative_fcf_consecutive_years: int


_DECIMAL_FIELDS = {
    "revenue_growth_below": (Decimal("-1"), Decimal("0")),
    "margin_decline_ratio": (Decimal("0"), Decimal("1")),
    "ocf_to_net_income_below": (Decimal("0"), Decimal("10")),
    "net_debt_to_ebitda_above": (Decimal("0"), Decimal("100")),
    "debt_to_equity_above": (Decimal("0"), Decimal("100")),
    "interest_coverage_below": (Decimal("0"), Decimal("100")),
    "receivable_days_increase_at_least": (Decimal("0"), Decimal("3650")),
    "inventory_days_increase_at_least": (Decimal("0"), Decimal("3650")),
    "negative_fcf_below": (Decimal("-1e30"), Decimal("0")),
}
_INTEGER_FIELDS = {
    "revenue_decline_consecutive_years",
    "margin_decline_lookback_years",
    "ocf_conversion_consecutive_years",
    "working_capital_increase_consecutive_years",
    "negative_fcf_consecutive_years",
}
_FIELDS = set(_DECIMAL_FIELDS) | _INTEGER_FIELDS


def _as_decimal(name: str, value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"Threshold {name!r} must be a finite decimal number.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"Threshold {name!r} must be a finite decimal number.")
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Threshold {name!r} must be a finite decimal number.") from exc
    if not decimal.is_finite():
        raise ValueError(f"Threshold {name!r} must be a finite decimal number.")
    lower, upper = _DECIMAL_FIELDS[name]
    valid = lower < decimal <= upper
    if name == "negative_fcf_below" and decimal != 0:
        raise ValueError("Threshold 'negative_fcf_below' must be zero because FCF units vary by company.")
    if not valid:
        raise ValueError(f"Threshold {name!r} must be in the range ({lower}, {upper}].")
    return decimal


def thresholds_from_mapping(document: dict[str, Any]) -> RiskThresholds:
    """Validate a TOML-shaped mapping and return immutable threshold settings."""
    unknown_tables = set(document) - {"meta", "thresholds"}
    if unknown_tables:
        raise ValueError(f"Unknown risk threshold configuration tables: {', '.join(sorted(unknown_tables))}.")
    meta = document.get("meta")
    values = document.get("thresholds")
    if not isinstance(meta, dict) or not isinstance(meta.get("version"), str) or not meta["version"].strip():
        raise ValueError("Risk threshold configuration requires a non-empty [meta].version.")
    if not isinstance(values, dict):
        raise ValueError("Risk threshold configuration requires a [thresholds] table.")
    unknown = set(values) - _FIELDS
    missing = _FIELDS - set(values)
    if unknown or missing:
        detail = []
        if missing:
            detail.append(f"missing {', '.join(sorted(missing))}")
        if unknown:
            detail.append(f"unknown {', '.join(sorted(unknown))}")
        raise ValueError("Invalid risk threshold fields: " + "; ".join(detail) + ".")

    parsed: dict[str, Any] = {"version": meta["version"].strip()}
    for name in sorted(_DECIMAL_FIELDS):
        parsed[name] = _as_decimal(name, values[name])
    for name in _INTEGER_FIELDS:
        value = values[name]
        if type(value) is not int or not 1 <= value <= 10:
            raise ValueError(f"Threshold {name!r} must be an integer from 1 through 10.")
        parsed[name] = value
    return RiskThresholds(**parsed)


def load_risk_thresholds(path: str | Path) -> RiskThresholds:
    """Read and validate a versioned TOML threshold file."""
    with Path(path).open("rb") as stream:
        document = tomllib.load(stream)
    return thresholds_from_mapping(document)
