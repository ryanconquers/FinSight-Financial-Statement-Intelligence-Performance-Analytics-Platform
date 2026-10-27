import sqlite3
from pathlib import Path

import pytest

from finsight.db.connection import connect_database


ROOT = Path(__file__).resolve().parents[1]


def test_schema_creates_expected_tables(tmp_path):
    with connect_database(tmp_path / "schema.sqlite3") as database:
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


def test_observation_rejects_duplicate_key(tmp_path):
    with connect_database(tmp_path / "unique.sqlite3") as database:
        database.execute(
            "INSERT INTO companies (company_id, company_name, reporting_currency) VALUES ('TEST_CO', 'Test Company', 'INR')"
        )
        database.execute(
            "INSERT INTO sources (source_id, publisher, source_url, retrieved_at) VALUES ('TEST_SOURCE', 'Test Registry', 'https://example.invalid/a', '2026-10-27')"
        )
        insert = """INSERT INTO financial_observations (
            company_id, financial_year, period_start, period_end, statement_basis,
            statement_type, line_item_id, reported_label, value, unit, currency,
            source_id
        ) VALUES ('TEST_CO', 'FY2025', '2024-04-01', '2025-03-31', 'standalone',
            'income_statement', 'revenue', 'Test reported label', 0, 'INR_crore',
            'INR', 'TEST_SOURCE')"""
        database.execute(insert)
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(insert)


def test_observation_rejects_invalid_statement_basis(tmp_path):
    with connect_database(tmp_path / "basis.sqlite3") as database:
        database.execute(
            "INSERT INTO companies (company_id, company_name, reporting_currency) VALUES ('TEST_CO', 'Test Company', 'INR')"
        )
        database.execute(
            "INSERT INTO sources (source_id, publisher, source_url, retrieved_at) VALUES ('TEST_SOURCE', 'Test Registry', 'https://example.invalid/a', '2026-10-27')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            database.execute(
                """INSERT INTO financial_observations (
                    company_id, financial_year, period_start, period_end,
                    statement_basis, statement_type, line_item_id, reported_label,
                    value, unit, currency, source_id
                ) VALUES ('TEST_CO', 'FY2025', '2024-04-01', '2025-03-31', 'mixed',
                    'income_statement', 'revenue', 'Test reported label', 1,
                    'INR_crore', 'INR', 'TEST_SOURCE')"""
            )
