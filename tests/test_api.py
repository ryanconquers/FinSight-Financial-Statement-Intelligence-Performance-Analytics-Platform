"""API tests use disposable SQLite files containing test-only observations."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import httpx

from finsight.api.app import create_app
from finsight.db.connection import connect_database


def request(app, method: str, path: str, **kwargs) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def add_test_observation(database, *, year: str, start: str, end: str, item: str, value: str, synthetic: int = 0):
    database.execute(
        "INSERT OR IGNORE INTO companies (company_id, company_name, ticker, reporting_currency) VALUES ('TEST_CO', 'Test Company', 'TST', 'INR')"
    )
    database.execute(
        "INSERT OR IGNORE INTO sources (source_id, publisher, source_url, retrieved_at, is_synthetic) VALUES ('TEST_SOURCE', 'Test Publisher', 'https://example.invalid/source', '2026-10-27', ?) ",
        (synthetic,),
    )
    database.execute(
        """INSERT INTO financial_observations (
            company_id, financial_year, period_start, period_end, statement_basis,
            statement_type, line_item_id, reported_label, value, unit, currency,
            source_id, is_synthetic
        ) VALUES ('TEST_CO', ?, ?, ?, 'consolidated', 'income_statement', ?, ?, ?, 'INR_crore', 'INR', 'TEST_SOURCE', ?)""",
        (year, start, end, item, item, value, synthetic),
    )
    database.commit()


def test_health_is_healthy_without_creating_or_exposing_database(tmp_path):
    db_path = tmp_path / "private.sqlite3"
    app = create_app(db_path)
    response = request(app, "GET", "/api/health")
    assert response.status_code == 200
    assert response.json() == {"data": {"status": "ok"}, "meta": {"service": "finsight-api"}}
    assert not db_path.exists()


def test_empty_status_and_company_list_are_explicit(tmp_path):
    app = create_app(tmp_path / "empty.sqlite3")
    status = request(app, "GET", "/api/status")
    companies = request(app, "GET", "/api/companies")
    assert status.status_code == 200
    assert status.json()["data"] == {
        "project_status": "under_development",
        "data_availability": "empty",
        "source_backed_observation_count": 0,
        "real_financial_data_onboarded": False,
    }
    assert companies.json() == {"data": [], "meta": {"count": 0}}


def test_company_metrics_and_provenance_api_return_source_linked_results(tmp_path):
    db_path = tmp_path / "company.sqlite3"
    with connect_database(db_path) as database:
        add_test_observation(database, year="FY2024", start="2023-04-01", end="2024-03-31", item="revenue", value="100")
        add_test_observation(database, year="FY2025", start="2024-04-01", end="2025-03-31", item="revenue", value="120")
    app = create_app(db_path, cors_origins=["http://localhost:3000"])
    companies = request(app, "GET", "/api/companies")
    assert companies.json()["meta"]["count"] == 1
    metrics = request(app, "GET", "/api/companies/TEST_CO/metrics?statement_basis=consolidated&financial_year=FY2025")
    assert metrics.status_code == 200
    growth = next(item for item in metrics.json()["data"] if item["metric_id"] == "revenue_growth")
    assert growth["value"] == "0.2"
    assert growth["inputs"][0]["source_id"] == "TEST_SOURCE"
    provenance = request(app, "GET", "/api/companies/TEST_CO/provenance")
    assert provenance.status_code == 200
    assert provenance.json()["data"][0]["source_url"] == "https://example.invalid/source"
    cors = request(app, "GET", "/api/health", headers={"Origin": "http://localhost:3000"})
    assert cors.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_request_errors_use_consistent_json_and_validate_periods(tmp_path):
    app = create_app(tmp_path / "requests.sqlite3")
    missing = request(app, "GET", "/api/companies/UNKNOWN/metrics")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    invalid_year = request(app, "GET", "/api/companies/TEST/metrics?financial_year=2025")
    assert invalid_year.status_code == 422
    assert invalid_year.json()["error"]["code"] == "invalid_request"
    invalid_basis = request(app, "GET", "/api/companies/TEST/metrics?statement_basis=mixed")
    assert invalid_basis.status_code == 422
    assert invalid_basis.json()["error"]["code"] == "invalid_request"


def test_api_excludes_synthetic_marked_records(tmp_path):
    db_path = tmp_path / "synthetic-test-only.sqlite3"
    with connect_database(db_path) as database:
        add_test_observation(database, year="FY2025", start="2024-04-01", end="2025-03-31", item="revenue", value="10", synthetic=1)
    app = create_app(db_path)
    assert request(app, "GET", "/api/status").json()["data"]["data_availability"] == "empty"
    assert request(app, "GET", "/api/companies").json()["data"] == []
