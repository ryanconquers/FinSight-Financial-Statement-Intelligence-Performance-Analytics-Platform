import csv
import sqlite3
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src" / "finsight" / "db" / "schema.sql"
FIXTURE = ROOT / "data" / "synthetic" / "financial_observations.csv"


@pytest.fixture
def database():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA.read_text(encoding="utf-8"))
    connection.execute(
        "INSERT INTO companies (company_id, company_name, reporting_currency) "
        "VALUES ('TEST', 'Synthetic Test Company', 'INR')"
    )
    connection.execute(
        "INSERT INTO sources (source_id, publisher, retrieved_at, is_synthetic) "
        "VALUES ('SYNTHETIC_TEST_ONLY', 'FinSight test fixture', '2026-10-27', 1)"
    )
    try:
        yield connection
    finally:
        connection.close()


def test_schema_creates_expected_tables(database):
    tables = {
        row[0]
        for row in database.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "companies",
        "sources",
        "financial_observations",
        "validation_results",
        "calculated_metrics",
        "processing_logs",
    } <= tables


def test_observation_rejects_duplicate_key(database):
    observation = (
        "TEST", "FY2025", "2024-04-01", "2025-03-31", "standalone",
        "income_statement", "revenue", "Revenue", 1000, "INR_crore", "INR",
        "SYNTHETIC_TEST_ONLY", 1,
    )
    insert = """INSERT INTO financial_observations (
        company_id, financial_year, period_start, period_end, statement_basis,
        statement_type, line_item_id, reported_label, value, unit, currency,
        source_id, is_synthetic
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
    database.execute(insert, observation)
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(insert, observation)


def test_observation_rejects_invalid_statement_basis(database):
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            """INSERT INTO financial_observations (
                company_id, financial_year, period_start, period_end,
                statement_basis, statement_type, line_item_id, reported_label,
                value, unit, currency, source_id
            ) VALUES ('TEST', 'FY2025', '2024-04-01', '2025-03-31', 'mixed',
                'income_statement', 'revenue', 'Revenue', 1, 'INR_crore',
                'INR', 'SYNTHETIC_TEST_ONLY')"""
        )


def test_fixture_is_explicitly_synthetic():
    with FIXTURE.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert rows
    assert all(row["record_origin"] == "synthetic" for row in rows)
    assert all(row["is_synthetic"].lower() == "true" for row in rows)
    assert all(row["source_id"] == "SYNTHETIC_TEST_ONLY" for row in rows)
