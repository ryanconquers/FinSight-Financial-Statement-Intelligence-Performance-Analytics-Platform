"""Validation rules for the documented financial-observation CSV contract."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from finsight.validation.report import Finding, ValidationReport

REQUIRED_COLUMNS = (
    "company_id", "company_name", "financial_year", "period_start", "period_end",
    "statement_basis", "statement_type", "line_item_id", "reported_label", "value",
    "unit", "currency", "source_id", "source_publisher", "source_url",
    "retrieved_at", "is_synthetic",
)
OPTIONAL_COLUMNS = ("ticker", "source_publication_date")
STATEMENT_BASES = {"standalone", "consolidated"}
STATEMENT_TYPES = {"income_statement", "balance_sheet", "cash_flow_statement"}
CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
FINANCIAL_YEAR_PATTERN = re.compile(r"^FY(\d{4})$")
NUMBER_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
BOOLEAN_TRUE = {"true", "1"}
BOOLEAN_FALSE = {"false", "0"}


def _date(value: str) -> date | None:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.isoformat() == value else None


def _text(value: object) -> str:
    return "" if value is None else str(value)


def validate_observations(
    frame: pd.DataFrame, input_filename: str
) -> tuple[list[dict[str, object]], ValidationReport]:
    """Validate CSV rows and return only error-free records, without coercing values."""
    report = ValidationReport(input_filename=input_filename, total_rows=len(frame))
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    unexpected_columns = [
        str(column) for column in frame.columns
        if column not in REQUIRED_COLUMNS and column not in OPTIONAL_COLUMNS
    ]
    for column in missing_columns:
        report.add(Finding("error", "missing_column", f"Required column '{column}' is missing.", field=column))
    for column in unexpected_columns:
        report.add(Finding("error", "unexpected_column", f"Column '{column}' is not part of the documented contract; preserve it separately or update the contract first.", field=column))
    if missing_columns or unexpected_columns:
        report.invalid_rows = len(frame)
        report.import_status = "validation_failed"
        return [], report

    rows = frame.to_dict(orient="records")
    row_findings: dict[int, list[Finding]] = {index: [] for index in range(len(rows))}
    parsed_values: dict[int, Decimal] = {}
    parsed_dates: dict[int, tuple[date, date, date]] = {}
    parsed_publications: dict[int, date | None] = {}
    parsed_synthetic: dict[int, bool] = {}

    def add(index: int, severity: str, code: str, message: str, field: str | None = None) -> None:
        finding = Finding(severity, code, message, row_number=index + 2, field=field)  # CSV header is row 1.
        report.add(finding)  # type: ignore[arg-type]
        row_findings[index].append(finding)

    for index, record in enumerate(rows):
        for field in REQUIRED_COLUMNS:
            value = _text(record.get(field, ""))
            if not value.strip():
                add(index, "error", "required_value_missing", f"Required value for '{field}' is blank.", field)
            elif value != value.strip():
                add(index, "error", "surrounding_whitespace", f"'{field}' has leading or trailing whitespace; correct the source CSV rather than relying on implicit cleanup.", field)
        if "ticker" in record and _text(record.get("ticker", "")) != _text(record.get("ticker", "")).strip():
            add(index, "error", "surrounding_whitespace", "'ticker' has leading or trailing whitespace; correct the source CSV rather than relying on implicit cleanup.", "ticker")

        basis = _text(record.get("statement_basis", ""))
        if basis and basis not in STATEMENT_BASES:
            add(index, "error", "invalid_statement_basis", "Use exactly 'standalone' or 'consolidated'.", "statement_basis")
        statement_type = _text(record.get("statement_type", ""))
        if statement_type and statement_type not in STATEMENT_TYPES:
            add(index, "error", "invalid_statement_type", f"Use one of: {', '.join(sorted(STATEMENT_TYPES))}.", "statement_type")

        dates = tuple(_date(_text(record.get(field, ""))) for field in ("period_start", "period_end", "retrieved_at"))
        for field, parsed in zip(("period_start", "period_end", "retrieved_at"), dates):
            if _text(record.get(field, "")).strip() and parsed is None:
                add(index, "error", "invalid_date", f"'{field}' must be a valid ISO date in YYYY-MM-DD format.", field)
        if all(parsed is not None for parsed in dates):
            start, end, retrieved = dates
            assert start and end and retrieved
            parsed_dates[index] = (start, end, retrieved)
            if start > end:
                add(index, "error", "period_order", "period_start must be on or before period_end.", "period_start")
            year_match = FINANCIAL_YEAR_PATTERN.fullmatch(_text(record.get("financial_year", "")))
            if not year_match:
                add(index, "error", "invalid_financial_year", "financial_year must use the documented FYYYYY format, for example FY2025.", "financial_year")
            elif end.year != int(year_match.group(1)):
                add(index, "error", "financial_year_period_mismatch", "The FY year must match the calendar year of period_end.", "financial_year")
            duration = (end - start).days + 1
            if start <= end and not 350 <= duration <= 380:
                add(index, "manual_review", "unusual_annual_period", f"Reporting period spans {duration} days; confirm the period is comparable to an annual filing.", "period_start")
        publication_raw = _text(record.get("source_publication_date", ""))
        publication_date = _date(publication_raw) if publication_raw else None
        parsed_publications[index] = publication_date
        if publication_raw and publication_date is None:
            add(index, "error", "invalid_date", "'source_publication_date' must be a valid ISO date in YYYY-MM-DD format when supplied.", "source_publication_date")

        raw_value = _text(record.get("value", ""))
        if raw_value.strip():
            special_non_finite = raw_value.lower() in {
                "nan", "+nan", "-nan", "snan", "+snan", "-snan",
                "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity",
            }
            if not NUMBER_PATTERN.fullmatch(raw_value) and not special_non_finite:
                numeric_value = None
            else:
                try:
                    numeric_value = Decimal(raw_value)
                except InvalidOperation:
                    numeric_value = None
            if numeric_value is None:
                add(index, "error", "non_numeric_value", "value must be a finite numeric amount; blank means unavailable and is not zero.", "value")
            elif not numeric_value.is_finite():
                add(index, "error", "non_finite_value", "value must not be NaN or infinite.", "value")
            elif abs(numeric_value) > Decimal("1.7976931348623157e308"):
                add(index, "error", "value_out_of_sqlite_range", "value exceeds SQLite's finite numeric range and cannot be stored safely.", "value")
            else:
                parsed_values[index] = numeric_value
                if abs(numeric_value) > Decimal("1e15"):
                    add(index, "warning", "extreme_magnitude", "Value exceeds 1e15 in the stated unit; verify the source amount and scale. This is not a conclusion about the company.", "value")
                line_item = _text(record.get("line_item_id", "")).lower()
                if numeric_value < 0 and line_item in {"revenue", "total_assets", "total_debt", "inventory", "trade_receivables"}:
                    add(index, "warning", "unusual_negative_value", f"Negative value for '{line_item}' merits source review; it is not by itself evidence of misconduct or distress.", "value")

        currency = _text(record.get("currency", ""))
        if currency and not CURRENCY_PATTERN.fullmatch(currency):
            add(index, "error", "invalid_currency", "currency must be an uppercase three-letter ISO 4217 code.", "currency")
        unit = _text(record.get("unit", ""))
        if unit and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. /-]*", unit):
            add(index, "error", "invalid_unit", "unit must be a non-empty, readable scale identifier (for example INR_crore).", "unit")

        source_url = _text(record.get("source_url", ""))
        try:
            parsed_url = urlparse(source_url)
            invalid_url = source_url and (parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc)
        except ValueError:
            invalid_url = True
        if invalid_url:
            add(index, "error", "invalid_source_url", "source_url must be an absolute HTTP or HTTPS URL.", "source_url")

        synthetic = _text(record.get("is_synthetic", "")).lower()
        if synthetic not in BOOLEAN_TRUE | BOOLEAN_FALSE:
            add(index, "error", "invalid_synthetic_flag", "is_synthetic must be true/false or 1/0.", "is_synthetic")
        else:
            is_synthetic = synthetic in BOOLEAN_TRUE
            parsed_synthetic[index] = is_synthetic
            labels = " ".join(_text(record.get(field, "")) for field in ("source_id", "source_publisher", "source_url")).lower()
            if is_synthetic:
                add(index, "error", "synthetic_data_prohibited", "Synthetic records are not accepted; import only source-backed financial disclosures.", "is_synthetic")
            if "synthetic" in labels:
                add(index, "error", "synthetic_source_label", "Source identifiers, publisher labels, and URLs must not label a synthetic record as a real disclosure.", "source_id")

    # Duplicate keys mark every participating row invalid to avoid arbitrary winners.
    key_fields = ["company_id", "financial_year", "statement_basis", "statement_type", "line_item_id"]
    if all(field in frame.columns for field in key_fields):
        duplicated = frame.duplicated(subset=key_fields, keep=False)
        for index in frame.index[duplicated]:
            add(int(index), "error", "duplicate_observation", "Observation key is duplicated in this file; resolve duplicates at source.", None)

    # Same company's line-item units and currency must remain consistent across periods.
    valid_for_consistency = frame.copy()
    for field in ("company_id", "statement_basis", "statement_type", "line_item_id", "unit", "currency"):
        valid_for_consistency[field] = valid_for_consistency[field].map(_text)
    for key, group in valid_for_consistency.groupby(["company_id", "statement_basis", "statement_type", "line_item_id"], dropna=False, sort=False):
        if group["unit"].nunique() > 1 or group["currency"].nunique() > 1:
            for index in group.index:
                add(int(index), "error", "inconsistent_company_unit_currency", f"Unit or currency varies across this company's periods for comparable line item {key[-1]!r}; standardise or split the input batch.", "unit")

    # Cross-company peer records with differing scales/currencies remain importable but cannot be directly compared.
    peer_key = ["financial_year", "statement_basis", "statement_type", "line_item_id"]
    for key, group in valid_for_consistency.groupby(peer_key, dropna=False, sort=False):
        if group["company_id"].nunique() > 1 and (group["unit"].nunique() > 1 or group["currency"].nunique() > 1):
            for index in group.index:
                add(int(index), "manual_review", "peer_unit_currency_mismatch", f"Peer values for {key[-1]!r} use different units or currencies; convert/standardise before comparison.", "unit")

    # Repeat source IDs may be reused only when their provenance metadata agrees.
    source_fields = ["source_publisher", "source_url", "retrieved_at"]
    if "source_publication_date" in frame.columns:
        source_fields.append("source_publication_date")
    for source_id, group in frame.groupby("source_id", dropna=False, sort=False):
        if any(group[field].map(_text).nunique() > 1 for field in source_fields):
            for index in group.index:
                add(int(index), "error", "inconsistent_source_reference", f"Source ID {source_id!r} has conflicting publisher, URL, or retrieval-date metadata.", "source_id")

    for company_id, group in frame.groupby("company_id", dropna=False, sort=False):
        ticker_values = {value for value in group["ticker"].map(_text) if value} if "ticker" in group.columns else set()
        if group["company_name"].map(_text).nunique() > 1 or group["currency"].map(_text).nunique() > 1 or len(ticker_values) > 1:
            for index in group.index:
                add(int(index), "error", "inconsistent_company_reference", f"Company ID {company_id!r} has conflicting name, ticker, or reporting-currency metadata.", "company_id")

    valid_records: list[dict[str, object]] = []
    invalid_indices = {index for index, findings in row_findings.items() if any(item.severity == "error" for item in findings)}
    for index, record in enumerate(rows):
        if index in invalid_indices:
            continue
        normalized: dict[str, object] = {key: _text(value) for key, value in record.items() if key in REQUIRED_COLUMNS or key in OPTIONAL_COLUMNS}
        normalized["ticker"] = _text(record.get("ticker", "")) or None
        normalized["value"] = parsed_values[index]
        normalized["period_start"] = parsed_dates[index][0].isoformat()
        normalized["period_end"] = parsed_dates[index][1].isoformat()
        normalized["retrieved_at"] = parsed_dates[index][2].isoformat()
        publication_date = parsed_publications[index]
        normalized["source_publication_date"] = publication_date.isoformat() if publication_date else None
        normalized["is_synthetic"] = parsed_synthetic[index]
        valid_records.append(normalized)

    report.invalid_rows = len(invalid_indices)
    report.valid_rows = len(frame) - report.invalid_rows
    report.import_status = "validation_failed" if report.invalid_rows else "validated"
    return valid_records, report
