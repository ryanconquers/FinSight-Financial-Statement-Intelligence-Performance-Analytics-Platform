"""Command-line interface for CSV validation and SQLite ingestion."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from finsight.db.connection import backup_database, connect_database, validate_database_path
from finsight.db.repository import import_records
from finsight.ingestion.csv_importer import read_observations
from finsight.validation.report import Finding, ValidationReport


def _add_report_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--report-json", type=Path, help="Write a machine-readable JSON report.")
    parser.add_argument("--report-csv", type=Path, help="Write a machine-readable CSV findings report.")


def _print_report(report: ValidationReport) -> None:
    print(f"Input: {report.input_filename}")
    print(f"Rows: {report.total_rows} total, {report.valid_rows} valid, {report.invalid_rows} invalid")
    print(f"Status: {report.import_status}")
    print(f"Database: {report.database_summary}")
    for finding in report.findings:
        location = f" row {finding.row_number}" if finding.row_number else ""
        field = f" [{finding.field}]" if finding.field else ""
        print(f"{finding.severity.upper()}{location}{field} {finding.code}: {finding.message}")


def _save_reports(report: ValidationReport, args: argparse.Namespace) -> None:
    if args.report_json:
        report.write_json(args.report_json)
    if args.report_csv:
        report.write_csv(args.report_csv)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="finsight", description="Validate and ingest source-backed financial observations.")
    commands = parser.add_subparsers(dest="command", required=True)

    validate_parser = commands.add_parser("validate", help="Validate a contract CSV without writing to a database.")
    validate_parser.add_argument("csv_file", type=Path)
    _add_report_options(validate_parser)

    ingest_parser = commands.add_parser("ingest", help="Validate a CSV and import the complete dataset transactionally.")
    ingest_parser.add_argument("csv_file", type=Path)
    ingest_parser.add_argument("--db", type=Path, required=True, help="SQLite database path.")
    _add_report_options(ingest_parser)

    backup_parser = commands.add_parser("db-backup", help="Create a consistent SQLite backup.")
    backup_parser.add_argument("--db", type=Path, required=True, help="SQLite database path.")
    backup_parser.add_argument("--output", type=Path, required=True, help="Backup destination path.")

    verify_parser = commands.add_parser("db-verify", help="Check SQLite integrity and foreign-key consistency.")
    verify_parser.add_argument("--db", type=Path, required=True, help="SQLite database path.")

    restore_parser = commands.add_parser("db-restore", help="Restore a verified SQLite backup to a new database path.")
    restore_parser.add_argument("--backup", type=Path, required=True, help="Verified backup database.")
    restore_parser.add_argument("--db", type=Path, required=True, help="New destination database path; existing files are never overwritten.")

    args = parser.parse_args(argv)
    if args.command == "db-backup":
        try:
            if not args.db.is_file():
                raise FileNotFoundError(f"Database file does not exist: {args.db}")
            with closing(connect_database(args.db)) as connection:
                backup_database(connection, args.output)
            print(f"Backup created: {args.output}")
            return 0
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            print(f"Backup failed: {exc}", file=sys.stderr)
            return 1
    if args.command == "db-verify":
        try:
            if not args.db.is_file():
                raise FileNotFoundError(f"Database file does not exist: {args.db}")
            with closing(connect_database(args.db)) as connection:
                integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != "ok" or foreign_keys:
                print(f"Database verification failed: integrity={integrity}, foreign_key_violations={len(foreign_keys)}", file=sys.stderr)
                return 1
            print("Database integrity and foreign keys verified.")
            return 0
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            print(f"Database verification failed: {exc}", file=sys.stderr)
            return 1
    if args.command == "db-restore":
        try:
            validate_database_path(args.db)
            if not args.backup.is_file():
                raise FileNotFoundError(f"Backup database does not exist: {args.backup}")
            with closing(connect_database(args.backup)) as source:
                integrity = source.execute("PRAGMA quick_check").fetchone()[0]
                foreign_keys = source.execute("PRAGMA foreign_key_check").fetchall()
                if integrity != "ok" or foreign_keys:
                    raise ValueError("Backup failed integrity or foreign-key verification; restore was not performed.")
                backup_database(source, args.db)
            print(f"Verified backup restored to new database: {args.db}")
            return 0
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            print(f"Restore failed: {exc}", file=sys.stderr)
            return 1
    records, report = read_observations(args.csv_file)
    if args.command == "ingest":
        if records:
            try:
                with closing(connect_database(args.db)) as connection:
                    report = import_records(connection, records, report)
            except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
                report.import_status = "database_unavailable"
                report.add(Finding("error", "database_unavailable", f"Could not open database: {exc}"))
        else:
            report.import_status = "not_imported_validation_errors" if report.errors else "no_rows_to_import"
            report.database_summary = "No valid records; database was not modified."
    elif args.command == "validate":
        report.database_summary = "Validation only; database was not modified."
        report.import_status = "validation_failed" if report.errors else "validated"

    _save_reports(report, args)
    _print_report(report)
    return 1 if report.errors or report.import_status in {"not_imported_validation_errors", "import_failed_rolled_back", "database_unavailable"} else 0


if __name__ == "__main__":
    sys.exit(main())
