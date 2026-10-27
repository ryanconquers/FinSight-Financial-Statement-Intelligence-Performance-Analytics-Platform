"""API tests use disposable SQLite files containing test-only observations."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import httpx
import pytest

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


def test_app_fails_early_when_persistent_storage_is_required_but_ephemeral_path_is_configured(monkeypatch):
    monkeypatch.setenv("FINSIGHT_REQUIRE_PERSISTENT_STORAGE", "1")
    with pytest.raises(ValueError, match="durable mounted volume"):
        create_app("/tmp/finsight.sqlite3")


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
    original = request(app, "GET", "/api/companies/TEST_CO/observations?statement_basis=consolidated&financial_year=FY2024")
    assert original.status_code == 200
    assert original.json()["data"][0]["reported_label"] == "revenue"
    assert original.json()["data"][0]["value"] == "100"
    cors = request(app, "GET", "/api/health", headers={"Origin": "http://localhost:3000"})
    assert cors.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_company_analysis_api_returns_versioned_assessments_and_evidence(tmp_path):
    db_path = tmp_path / "analysis.sqlite3"
    with connect_database(db_path) as database:
        add_test_observation(database, year="FY2023", start="2022-04-01", end="2023-03-31", item="revenue", value="120")
        add_test_observation(database, year="FY2024", start="2023-04-01", end="2024-03-31", item="revenue", value="100")
        add_test_observation(database, year="FY2025", start="2024-04-01", end="2025-03-31", item="revenue", value="90")
    app = create_app(db_path)
    response = request(app, "GET", "/api/companies/TEST_CO/analysis?statement_basis=consolidated")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["company_id"] == "TEST_CO"
    assert payload["configuration_version"] == "m4a-risk-v1"
    revenue = next(item for item in payload["assessments"] if item["rule_id"] == "revenue_decline")
    assert revenue["status"] == "flagged"
    assert revenue["periods"] == ["FY2024", "FY2025"]
    assert revenue["thresholds"]["growth_below"] == "0"
    assert revenue["evidence"]
    assert revenue["evidence"][-1]["inputs"][0]["source_id"] == "TEST_SOURCE"


def test_company_analysis_api_returns_not_found_and_validates_basis(tmp_path):
    app = create_app(tmp_path / "analysis-empty.sqlite3")
    missing = request(app, "GET", "/api/companies/UNKNOWN/analysis")
    invalid_basis = request(app, "GET", "/api/companies/UNKNOWN/analysis?statement_basis=mixed")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert invalid_basis.status_code == 422


def test_insights_benchmark_and_report_endpoints_use_compatible_source_backed_data(tmp_path):
    db_path = tmp_path / "m4.sqlite3"
    with connect_database(db_path) as database:
        for company_id, name, amounts in (
            ("TARGET", "Target Test Co", (100, 120, 180)),
            ("PEER_A", "Peer A Test Co", (100, 110, 121)),
            ("PEER_B", "Peer B Test Co", (100, 130, 169)),
        ):
            database.execute("INSERT INTO companies (company_id, company_name, reporting_currency) VALUES (?, ?, 'INR')", (company_id, name))
            source_id = f"TEST_SOURCE_{company_id}"
            database.execute("INSERT INTO sources (source_id, publisher, source_url, retrieved_at) VALUES (?, 'Test Publisher', 'https://example.invalid/test', '2026-10-27')", (source_id,))
            for number, amount in zip((2023, 2024, 2025), amounts):
                database.execute(
                    """INSERT INTO financial_observations (company_id, financial_year, period_start, period_end, statement_basis, statement_type, line_item_id, reported_label, value, unit, currency, source_id)
                    VALUES (?, ?, ?, ?, 'consolidated', 'income_statement', 'revenue', 'test-reported revenue', ?, 'INR_crore', 'INR', ?)""",
                    (company_id, f"FY{number}", f"{number-1}-04-01", f"{number}-03-31", amount, source_id),
                )
        database.commit()
    app = create_app(db_path)

    insights = request(app, "GET", "/api/companies/TARGET/insights?statement_basis=consolidated")
    assert insights.status_code == 200
    assert any("accelerated" in item["finding"] for item in insights.json()["data"]["insights"])
    peer_insights = request(app, "GET", "/api/companies/TARGET/insights?statement_basis=consolidated&peer_ids=PEER_A&peer_ids=PEER_B")
    assert peer_insights.status_code == 200
    assert peer_insights.json()["data"]["peer_benchmark_status"] == "available"
    assert any(item["category"] == "peer_comparison" for item in peer_insights.json()["data"]["insights"])

    benchmark = request(app, "GET", "/api/companies/TARGET/benchmark?statement_basis=consolidated&peer_ids=PEER_A&peer_ids=PEER_B&financial_year=FY2025")
    assert benchmark.status_code == 200
    revenue = next(item for item in benchmark.json()["data"]["metrics"] if item["metric_id"] == "revenue_growth")
    assert revenue["status"] == "available"
    assert revenue["peer_median"] == "0.2"
    assert revenue["peer_count"] == 2
    assert revenue["values"][1]["evidence"]["inputs"][0]["source_id"] == "TEST_SOURCE_PEER_A"
    assert {source["financial_year"] for source in revenue["values"][1]["sources"]} == {"FY2024", "FY2025"}
    assert revenue["values"][1]["sources"][0]["source_url"] == "https://example.invalid/test"

    report = request(app, "GET", "/api/companies/TARGET/report?statement_basis=consolidated&format=json")
    assert report.status_code == 200
    document = report.json()["data"]
    assert document["company"]["company_name"] == "Target Test Co"
    assert document["provenance"][0]["source_id"] == "TEST_SOURCE_TARGET"
    assert document["reported_observations"][0]["reported_label"] == "test-reported revenue"
    absent_basis = request(app, "GET", "/api/companies/TARGET/report?statement_basis=standalone&format=json")
    assert absent_basis.status_code == 200
    assert absent_basis.json()["data"]["report_status"] == "insufficient_data"
    assert absent_basis.json()["data"]["reported_observations"] == []
    assert document["metrics"] and document["insights"]
    report_with_peers = request(app, "GET", "/api/companies/TARGET/report?statement_basis=consolidated&format=json&peer_ids=PEER_A&peer_ids=PEER_B")
    assert report_with_peers.json()["data"]["peer_benchmark"]["status"] == "available"
    csv_response = request(app, "GET", "/api/companies/TARGET/report?format=csv")
    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.headers["content-type"]
    assert "revenue_growth" in csv_response.text


def test_peer_benchmark_and_report_handle_missing_company_and_peer_safely(tmp_path):
    db_path = tmp_path / "m4-empty.sqlite3"
    with connect_database(db_path) as database:
        add_test_observation(database, year="FY2025", start="2024-04-01", end="2025-03-31", item="revenue", value="100")
    app = create_app(db_path)
    missing = request(app, "GET", "/api/companies/UNKNOWN/insights")
    absent_peer = request(app, "GET", "/api/companies/TEST_CO/benchmark?peer_ids=UNKNOWN")
    invalid_target_peer = request(app, "GET", "/api/companies/TEST_CO/benchmark?peer_ids=TEST_CO")
    missing_report = request(app, "GET", "/api/companies/UNKNOWN/report")
    assert missing.status_code == 404
    assert absent_peer.status_code == 404
    assert invalid_target_peer.status_code == 422
    assert missing_report.status_code == 404


def test_provenance_can_be_filtered_to_the_selected_statement_basis(tmp_path):
    db_path = tmp_path / "basis-provenance.sqlite3"
    with connect_database(db_path) as database:
        add_test_observation(database, year="FY2025", start="2024-04-01", end="2025-03-31", item="revenue", value="100")
        database.execute("INSERT INTO sources (source_id, publisher, source_url, retrieved_at) VALUES ('TEST_STANDALONE_SOURCE', 'Test Publisher', 'https://example.invalid/standalone', '2026-10-27')")
        database.execute("""INSERT INTO financial_observations (company_id, financial_year, period_start, period_end, statement_basis, statement_type, line_item_id, reported_label, value, unit, currency, source_id)
            VALUES ('TEST_CO', 'FY2025', '2024-04-01', '2025-03-31', 'standalone', 'income_statement', 'net_income', 'test net income', 5, 'INR_crore', 'INR', 'TEST_STANDALONE_SOURCE')""")
        database.commit()
    app = create_app(db_path)
    standalone = request(app, "GET", "/api/companies/TEST_CO/provenance?statement_basis=standalone")
    assert standalone.status_code == 200
    assert len(standalone.json()["data"]) == 1
    assert standalone.json()["data"][0]["statement_basis"] == "standalone"


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
