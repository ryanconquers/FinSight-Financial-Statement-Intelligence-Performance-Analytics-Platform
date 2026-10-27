"""CSV ingestion tests use temporary, explicitly test-only inputs and databases."""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pytest

from finsight.db.connection import connect_database
from finsight.db.repository import import_records
from finsight.ingestion.csv_importer import read_observations
from finsight.cli import main


COLUMNS = [
    "company_id", "company_name", "ticker", "financial_year", "period_start",
    "period_end", "statement_basis", "statement_type", "line_item_id",
    "reported_label", "value", "unit", "currency", "source_id",
    "source_publisher", "source_url", "source_publication_date", "retrieved_at", "is_synthetic",
]


def row(**changes: str) -> dict[str, str]:
    record = {
        "company_id": "TEST_CO",
        "company_name": "Test Company",
        "ticker": "TST",
        "financial_year": "FY2025",
        "period_start": "2024-04-01",
        "period_end": "2025-03-31",
        "statement_basis": "standalone",
        "statement_type": "income_statement",
        "line_item_id": "revenue",
        "reported_label": "Test-only reported label",
        "value": "0",
        "unit": "INR_crore",
        "currency": "INR",
        "source_id": "TEST_SOURCE",
        "source_publisher": "Test Publisher",
        "source_url": "https://example.invalid/test-source",
        "source_publication_date": "2025-05-01",
        "retrieved_at": "2026-10-27",
        "is_synthetic": "false",
    }
    record.update(changes)
    return record


def write_csv(path: Path, rows: list[dict[str, str]], columns: list[str] = COLUMNS) -> Path:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def test_successful_ingestion_registers_company_source_and_observation(tmp_path):
    path = write_csv(tmp_path / "observations.csv", [row(value="125.75")])
    records, report = read_observations(path)
    with connect_database(tmp_path / "finsight.sqlite3") as database:
        report = import_records(database, records, report)
        assert database.execute("SELECT company_name FROM companies").fetchone()[0] == "Test Company"
        assert database.execute("SELECT publisher FROM sources").fetchone()[0] == "Test Publisher"
        assert database.execute("SELECT publication_date FROM sources").fetchone()[0] == "2025-05-01"
        assert database.execute("SELECT value FROM financial_observations").fetchone()[0] == 125.75
        assert database.execute("SELECT status FROM processing_logs").fetchone()[0] == "succeeded"
    assert report.import_status == "imported"
    assert report.database_rows_written == 1


def test_optional_publication_date_can_be_absent_without_losing_other_provenance(tmp_path):
    columns = [column for column in COLUMNS if column != "source_publication_date"]
    records, report = read_observations(write_csv(tmp_path / "no-publication-date.csv", [row()], columns))
    assert report.errors == []
    assert records[0]["source_publication_date"] is None
    with connect_database(tmp_path / "no-publication-date.sqlite3") as database:
        report = import_records(database, records, report)
        assert report.import_status == "imported"
        assert database.execute("SELECT publication_date FROM sources").fetchone()[0] is None


def test_zero_is_distinct_from_missing_but_invalid_dataset_is_not_imported(tmp_path):
    path = write_csv(tmp_path / "zero-and-missing.csv", [row(value="0"), row(value="", line_item_id="cost")])
    records, report = read_observations(path)
    assert len(records) == 1
    assert records[0]["value"] == 0
    assert report.valid_rows == 1
    assert report.invalid_rows == 1
    with connect_database(tmp_path / "zero.sqlite3") as database:
        report = import_records(database, records, report)
        assert database.execute("SELECT COUNT(*) FROM financial_observations").fetchone()[0] == 0
        assert database.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0
    assert report.import_status == "not_imported_validation_errors"
    assert report.database_rows_written == 0


@pytest.mark.parametrize("missing_column", ["company_id", "value", "source_url"])
def test_missing_columns_are_rejected(tmp_path, missing_column):
    columns = [column for column in COLUMNS if column != missing_column]
    records, report = read_observations(write_csv(tmp_path / "missing-column.csv", [row()], columns))
    assert records == []
    assert report.invalid_rows == 1
    assert "missing_column" in codes(report)


@pytest.mark.parametrize("field", ["company_name", "financial_year", "source_id", "source_publisher", "source_url", "retrieved_at", "is_synthetic"])
def test_blank_required_values_are_reported(tmp_path, field):
    records, report = read_observations(write_csv(tmp_path / "blank.csv", [row(**{field: ""})]))
    assert records == []
    finding = next(item for item in report.findings if item.code == "required_value_missing")
    assert finding.row_number == 2
    assert finding.field == field


def test_invalid_date_and_reversed_reporting_period_are_rejected(tmp_path):
    records, report = read_observations(write_csv(
        tmp_path / "dates.csv",
        [row(period_start="2024-02-30"), row(line_item_id="cost", period_start="2025-03-31", period_end="2024-04-01")],
    ))
    assert records == []
    assert "invalid_date" in codes(report)
    assert "period_order" in codes(report)


@pytest.mark.parametrize("value,expected", [("twelve", "non_numeric_value"), ("1,000", "non_numeric_value"), ("NaN", "non_finite_value"), ("Infinity", "non_finite_value"), ("-Infinity", "non_finite_value"), ("1e999", "value_out_of_sqlite_range")])
def test_invalid_numeric_values_are_rejected(tmp_path, value, expected):
    records, report = read_observations(write_csv(tmp_path / "numeric.csv", [row(value=value)]))
    assert records == []
    assert expected in codes(report)


def test_duplicate_observation_marks_every_duplicate_invalid(tmp_path):
    records, report = read_observations(write_csv(tmp_path / "duplicates.csv", [row(), row()]))
    assert records == []
    assert report.invalid_rows == 2
    assert len([item for item in report.errors if item.code == "duplicate_observation"]) == 2


@pytest.mark.parametrize("field,value,code", [
    ("statement_basis", "mixed", "invalid_statement_basis"),
    ("statement_type", "other", "invalid_statement_type"),
    ("currency", "inr", "invalid_currency"),
])
def test_invalid_statement_metadata_is_rejected(tmp_path, field, value, code):
    records, report = read_observations(write_csv(tmp_path / "statement.csv", [row(**{field: value})]))
    assert records == []
    assert code in codes(report)


def test_source_provenance_is_required_and_validated(tmp_path):
    records, report = read_observations(write_csv(tmp_path / "provenance.csv", [row(source_url="relative/path")]))
    assert records == []
    assert "invalid_source_url" in codes(report)
    records, report = read_observations(write_csv(tmp_path / "bad-publication-date.csv", [row(source_publication_date="2025/05/01")]))
    assert records == []
    assert "invalid_date" in codes(report)
    records, report = read_observations(write_csv(tmp_path / "missing-source.csv", [row(source_id="")]))
    assert records == []
    assert "required_value_missing" in codes(report)
    records, report = read_observations(write_csv(tmp_path / "malformed-url.csv", [row(source_url="http://[")]))
    assert records == []
    assert "invalid_source_url" in codes(report)


def test_synthetic_records_and_synthetic_source_labels_are_rejected(tmp_path):
    records, report = read_observations(write_csv(
        tmp_path / "synthetic-flag.csv", [row(is_synthetic="true")]
    ))
    assert records == []
    assert "synthetic_data_prohibited" in codes(report)
    records, report = read_observations(write_csv(
        tmp_path / "synthetic-source.csv", [row(source_id="SYNTHETIC_TEST_ONLY")]
    ))
    assert records == []
    assert "synthetic_source_label" in codes(report)
    records, report = read_observations(write_csv(
        tmp_path / "bad-flag.csv", [row(is_synthetic="sometimes")]
    ))
    assert records == []
    assert "invalid_synthetic_flag" in codes(report)


@pytest.mark.parametrize("field,value", [("unit", "INR_lakh"), ("currency", "USD")])
def test_inconsistent_company_units_and_currency_are_rejected(tmp_path, field, value):
    first = row(value="1")
    second = row(
        financial_year="FY2024", period_start="2023-04-01", period_end="2024-03-31",
        value="2", **{field: value},
    )
    records, report = read_observations(write_csv(tmp_path / "units.csv", [first, second]))
    assert records == []
    assert "inconsistent_company_unit_currency" in codes(report)


@pytest.mark.parametrize("field,value", [("unit", "INR_lakh"), ("currency", "USD")])
def test_peer_unit_mismatch_is_manual_review_not_an_error(tmp_path, field, value):
    second = row(company_id="OTHER_CO", company_name="Other Test Company", ticker="OTH", **{field: value})
    records, report = read_observations(write_csv(tmp_path / "peer-units.csv", [row(), second]))
    assert len(records) == 2
    assert report.invalid_rows == 0
    assert "peer_unit_currency_mismatch" in codes(report)
    assert any(finding.severity == "manual_review" for finding in report.findings)


def test_unusual_negative_amount_is_manual_review_not_rejection(tmp_path):
    records, report = read_observations(write_csv(
        tmp_path / "negative.csv", [row(line_item_id="total_assets", value="-1")]
    ))
    assert len(records) == 1
    assert report.invalid_rows == 0
    assert "unusual_negative_value" in codes(report)
    assert next(item for item in report.findings if item.code == "unusual_negative_value").severity == "warning"


def test_unusual_annual_period_and_financial_year_mismatch_are_reported(tmp_path):
    records, report = read_observations(write_csv(
        tmp_path / "periods.csv",
        [
            row(period_start="2024-10-01"),
            row(line_item_id="cost", financial_year="FY2024"),
        ],
    ))
    assert len(records) == 1
    assert "unusual_annual_period" in codes(report)
    assert "financial_year_period_mismatch" in codes(report)
    assert any(item.severity == "manual_review" for item in report.findings)


def test_empty_and_header_only_files(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    records, report = read_observations(empty)
    assert records == []
    assert "empty_file" in codes(report)
    header_only = write_csv(tmp_path / "header-only.csv", [])
    records, report = read_observations(header_only)
    assert records == []
    assert report.total_rows == 0
    assert report.import_status == "validated"


def test_ticker_column_is_optional(tmp_path):
    columns = [column for column in COLUMNS if column != "ticker"]
    records, report = read_observations(write_csv(tmp_path / "no-ticker.csv", [row()], columns))
    assert len(records) == 1
    assert records[0]["ticker"] is None
    assert report.invalid_rows == 0


def test_malformed_csv_is_rejected_without_exception(tmp_path):
    path = tmp_path / "malformed.csv"
    path.write_text('company_id,company_name\n"unfinished,Test\n', encoding="utf-8")
    records, report = read_observations(path)
    assert records == []
    assert "malformed_csv" in codes(report)


def test_mixed_valid_and_invalid_records_are_rejected_as_one_dataset(tmp_path):
    path = write_csv(tmp_path / "mixed.csv", [row(value="4"), row(line_item_id="cost", value="bad")])
    records, report = read_observations(path)
    with connect_database(tmp_path / "mixed.sqlite3") as database:
        report = import_records(database, records, report)
        assert database.execute("SELECT COUNT(*) FROM financial_observations").fetchone()[0] == 0
        assert database.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0
        assert database.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
    assert report.import_status == "not_imported_validation_errors"
    assert report.database_rows_written == 0
    assert report.total_rows == 2 and report.invalid_rows == 1


def test_database_failure_rolls_back_every_valid_row_and_registration(tmp_path):
    database = connect_database(tmp_path / "rollback.sqlite3")
    try:
        database.execute("INSERT INTO companies (company_id, company_name, reporting_currency) VALUES ('EXISTING', 'Existing Test Company', 'INR')")
        database.execute("INSERT INTO sources (source_id, publisher, source_url, retrieved_at) VALUES ('TEST_SOURCE', 'Test Publisher', 'https://example.invalid/test-source', '2026-10-27')")
        database.execute("""INSERT INTO financial_observations (
            company_id, financial_year, period_start, period_end, statement_basis,
            statement_type, line_item_id, reported_label, value, unit, currency, source_id
        ) VALUES ('EXISTING', 'FY2025', '2024-04-01', '2025-03-31', 'standalone',
            'income_statement', 'revenue', 'Test-only reported label', 5, 'INR_crore', 'INR', 'TEST_SOURCE')""")
        database.commit()
        rows = [
            row(company_id="NEW_CO", company_name="New Test Company", ticker="NEW", line_item_id="expenses"),
            row(company_id="EXISTING", company_name="Existing Test Company", ticker="", line_item_id="revenue"),
        ]
        path = write_csv(tmp_path / "rollback.csv", rows)
        records, report = read_observations(path)
        report = import_records(database, records, report)
        assert report.import_status == "import_failed_rolled_back"
        assert report.database_rows_written == 0
        assert database.execute("SELECT COUNT(*) FROM financial_observations").fetchone()[0] == 1
        assert database.execute("SELECT COUNT(*) FROM companies WHERE company_id = 'NEW_CO'").fetchone()[0] == 0
        assert database.execute("SELECT status FROM processing_logs").fetchone()[0] == "failed"
    finally:
        database.close()


def test_validation_reports_are_reproducible_and_machine_readable(tmp_path):
    path = write_csv(tmp_path / "report.csv", [row(value="not-a-number")])
    _, first = read_observations(path)
    _, second = read_observations(path)
    assert first.to_dict() == second.to_dict()
    first.write_json(tmp_path / "report.json")
    second.write_json(tmp_path / "report-again.json")
    assert (tmp_path / "report.json").read_bytes() == (tmp_path / "report-again.json").read_bytes()
    assert json.loads((tmp_path / "report.json").read_text()) == first.to_dict()
    first.write_csv(tmp_path / "report-findings.csv")
    second.write_csv(tmp_path / "report-findings-again.csv")
    assert "non_numeric_value" in (tmp_path / "report-findings.csv").read_text()
    assert (tmp_path / "report-findings.csv").read_bytes() == (tmp_path / "report-findings-again.csv").read_bytes()


def test_failed_validation_does_not_touch_database(tmp_path):
    path = write_csv(tmp_path / "invalid.csv", [row(value="bad")])
    records, report = read_observations(path)
    database_path = tmp_path / "untouched.sqlite3"
    with connect_database(database_path) as database:
        report = import_records(database, records, report)
        assert database.execute("SELECT COUNT(*) FROM processing_logs").fetchone()[0] == 0
        assert database.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0
    assert report.database_rows_written == 0


def test_cli_validate_and_ingest_write_requested_reports(tmp_path):
    path = write_csv(tmp_path / "cli.csv", [row(value="7")])
    validate_json = tmp_path / "validation.json"
    assert main(["validate", str(path), "--report-json", str(validate_json)]) == 0
    assert json.loads(validate_json.read_text())["import_status"] == "validated"

    database = tmp_path / "cli.sqlite3"
    import_json = tmp_path / "import.json"
    assert main(["ingest", str(path), "--db", str(database), "--report-json", str(import_json)]) == 0
    assert json.loads(import_json.read_text())["import_status"] == "imported"


def test_sqlite_schema_is_versioned_and_backup_is_consistent(tmp_path):
    from finsight.db.connection import backup_database

    original_path = tmp_path / "original.sqlite3"
    backup_path = tmp_path / "backup" / "finsight.sqlite3"
    with connect_database(original_path) as database:
        database.execute("INSERT INTO companies (company_id, company_name, reporting_currency) VALUES ('TEST_CO', 'Test Company', 'INR')")
        database.commit()
        assert database.execute("PRAGMA user_version").fetchone()[0] == 1
        backup_database(database, backup_path)
    with connect_database(backup_path) as backup:
        assert backup.execute("SELECT company_name FROM companies WHERE company_id = 'TEST_CO'").fetchone()[0] == "Test Company"
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        with pytest.raises(FileExistsError, match="will not be overwritten"):
            backup_database(backup, backup_path)
    restored_path = tmp_path / "restore.sqlite3"
    assert main(["db-restore", "--backup", str(backup_path), "--db", str(restored_path)]) == 0
    with connect_database(restored_path) as restored:
        assert restored.execute("SELECT company_name FROM companies WHERE company_id = 'TEST_CO'").fetchone()[0] == "Test Company"
    assert main(["db-restore", "--backup", str(backup_path), "--db", str(restored_path)]) == 1


def test_future_sqlite_schema_version_fails_clearly(tmp_path):
    path = tmp_path / "newer.sqlite3"
    with sqlite3.connect(path) as database:
        database.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="newer than supported"):
        connect_database(path)


def test_schema_bootstrap_failure_rolls_back_partial_ddl(tmp_path, monkeypatch):
    import finsight.db.connection as database_module

    bad_schema = tmp_path / "invalid-schema.sql"
    bad_schema.write_text("CREATE TABLE should_rollback (id INTEGER); INVALID SQL;", encoding="utf-8")
    monkeypatch.setattr(database_module, "SCHEMA_PATH", bad_schema)
    path = tmp_path / "migration-rollback.sqlite3"
    with pytest.raises(sqlite3.Error):
        connect_database(path)
    with sqlite3.connect(path) as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 0
        assert database.execute("SELECT name FROM sqlite_master WHERE name = 'should_rollback'").fetchone() is None


def test_production_storage_guard_rejects_ephemeral_path_and_accepts_volume(tmp_path, monkeypatch):
    monkeypatch.setenv("FINSIGHT_REQUIRE_PERSISTENT_STORAGE", "1")
    with pytest.raises(ValueError, match="durable mounted volume"):
        connect_database("/tmp/finsight.sqlite3")
    with pytest.raises(ValueError, match="absolute"):
        connect_database("data/finsight.sqlite3")
    with connect_database(tmp_path / "persistent-volume" / "finsight.sqlite3") as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 1
