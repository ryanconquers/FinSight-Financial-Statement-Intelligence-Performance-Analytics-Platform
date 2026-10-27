"""Transactional registration and persistence for validated observations."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Iterable

from finsight.validation.report import Finding, ValidationReport


def _check_existing_company(connection: sqlite3.Connection, record: dict[str, object]) -> None:
    existing = connection.execute(
        "SELECT company_name, ticker, reporting_currency FROM companies WHERE company_id = ?",
        (record["company_id"],),
    ).fetchone()
    if existing is None:
        connection.execute(
            "INSERT INTO companies (company_id, company_name, ticker, reporting_currency) VALUES (?, ?, ?, ?)",
            (record["company_id"], record["company_name"], record.get("ticker"), record["currency"]),
        )
        return
    if existing["company_name"] != record["company_name"]:
        raise ValueError(f"Company ID {record['company_id']!r} is already registered with a different name.")
    if existing["reporting_currency"] != record["currency"]:
        raise ValueError(f"Company ID {record['company_id']!r} has a different registered reporting currency.")
    incoming_ticker = record.get("ticker")
    if existing["ticker"] and incoming_ticker and existing["ticker"] != incoming_ticker:
        raise ValueError(f"Company ID {record['company_id']!r} has a conflicting ticker.")
    if not existing["ticker"] and incoming_ticker:
        connection.execute("UPDATE companies SET ticker = ? WHERE company_id = ?", (incoming_ticker, record["company_id"]))


def _check_existing_source(connection: sqlite3.Connection, record: dict[str, object]) -> None:
    existing = connection.execute(
        "SELECT publisher, source_url, retrieved_at, is_synthetic FROM sources WHERE source_id = ?",
        (record["source_id"],),
    ).fetchone()
    if existing is None:
        connection.execute(
            "INSERT INTO sources (source_id, publisher, source_url, retrieved_at, is_synthetic) VALUES (?, ?, ?, ?, 0)",
            (record["source_id"], record["source_publisher"], record["source_url"], record["retrieved_at"]),
        )
        return
    expected = (record["source_publisher"], record["source_url"], record["retrieved_at"], 0)
    observed = (existing["publisher"], existing["source_url"], existing["retrieved_at"], existing["is_synthetic"])
    if observed != expected:
        raise ValueError(f"Source ID {record['source_id']!r} is already registered with conflicting provenance or synthetic status.")


def _write_findings(
    connection: sqlite3.Connection, run_id: str, findings: Iterable[Finding]
) -> None:
    for finding in findings:
        status = "failed" if finding.severity == "error" else "needs_review" if finding.severity in {"warning", "manual_review"} else "passed"
        location = f"CSV row {finding.row_number}, field {finding.field}: " if finding.row_number else ""
        connection.execute(
            "INSERT INTO validation_results (run_id, check_name, severity, status, message) VALUES (?, ?, ?, ?, ?)",
            (run_id, finding.code, finding.severity, status, location + finding.message),
        )


def import_records(
    connection: sqlite3.Connection,
    records: list[dict[str, object]],
    report: ValidationReport,
) -> ValidationReport:
    """Atomically register metadata, write valid rows and record validation outcomes."""
    if not records:
        report.import_status = "not_imported_validation_errors" if report.errors else "no_rows_to_import"
        report.database_summary = "No valid records; database was not modified."
        return report

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        with connection:
            connection.execute(
                "INSERT INTO processing_logs (run_id, started_at, input_name, status, records_read, records_written) VALUES (?, ?, ?, 'started', ?, 0)",
                (run_id, started_at, report.input_filename, report.total_rows),
            )
            for record in records:
                _check_existing_company(connection, record)
                _check_existing_source(connection, record)
                connection.execute(
                    """INSERT INTO financial_observations (
                        company_id, financial_year, period_start, period_end,
                        statement_basis, statement_type, line_item_id, reported_label,
                        value, unit, currency, source_id, is_synthetic
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                    (
                        record["company_id"], record["financial_year"], record["period_start"],
                        record["period_end"], record["statement_basis"], record["statement_type"],
                        record["line_item_id"], record["reported_label"], str(record["value"]),
                        record["unit"], record["currency"], record["source_id"],
                    ),
                )
            _write_findings(connection, run_id, report.findings)
            final_status = "completed_with_warnings" if report.findings else "succeeded"
            completed_at = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "UPDATE processing_logs SET completed_at = ?, status = ?, records_written = ?, summary = ? WHERE run_id = ?",
                (completed_at, final_status, len(records), f"Imported {len(records)} valid of {report.total_rows} rows.", run_id),
            )
    except (sqlite3.Error, ValueError) as exc:
        # The context manager rolls back metadata, observations, findings, and the initial run log.
        report.import_status = "import_failed_rolled_back"
        report.database_rows_written = 0
        report.database_summary = f"Transaction rolled back; no records were imported: {exc}"
        report.add(Finding("error", "database_write_failed", report.database_summary))
        try:
            with connection:
                connection.execute(
                    "INSERT INTO processing_logs (run_id, started_at, completed_at, input_name, status, records_read, records_written, summary) VALUES (?, ?, ?, ?, 'failed', ?, 0, ?)",
                    (run_id, started_at, datetime.now(timezone.utc).isoformat(), report.input_filename, report.total_rows, report.database_summary),
                )
        except sqlite3.Error:
            # Preserve the original failure report even if the database cannot record its own failure.
            pass
        return report

    report.database_rows_written = len(records)
    report.database_summary = f"Imported {len(records)} valid of {report.total_rows} rows in one transaction."
    if report.invalid_rows:
        report.import_status = "partial_import_with_validation_errors"
    elif report.findings:
        report.import_status = "imported_with_findings"
    else:
        report.import_status = "imported"
    return report
