"""Forecast API tests use temporary SQLite databases and test-only statements."""

import asyncio
from decimal import Decimal

import httpx
import pytest

from finsight.api.app import create_app
from finsight.db.connection import connect_database


def request(app, method, path, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(run())


def forecast_app(tmp_path):
    path = tmp_path / "forecast.sqlite3"
    with connect_database(path) as db:
        db.execute("INSERT INTO companies (company_id, company_name, reporting_currency) VALUES ('TEST_CO', 'Test Company', 'INR')")
        db.execute("INSERT INTO sources (source_id, publisher, source_url, retrieved_at) VALUES ('TEST_SOURCE', 'Test Publisher', 'https://example.invalid/report', '2026-10-27')")
        rows = [
            ("income_statement", "revenue", "100"), ("income_statement", "cost_of_goods_sold", "60"),
            ("income_statement", "ebitda", "15"), ("income_statement", "ebit", "10"),
            ("income_statement", "finance_costs", "2"), ("balance_sheet", "trade_receivables", "10"),
            ("balance_sheet", "inventory", "12"), ("balance_sheet", "trade_payables", "8"),
        ]
        for statement, item, value in rows:
            db.execute("""INSERT INTO financial_observations (company_id, financial_year, period_start, period_end, statement_basis, statement_type, line_item_id, reported_label, value, unit, currency, source_id)
                VALUES ('TEST_CO', 'FY2024', '2023-04-01', '2024-03-31', 'consolidated', ?, ?, ?, ?, 'INR_crore', 'INR', 'TEST_SOURCE')""", (statement, item, item, value))
        db.commit()
    return create_app(path)


def payload():
    return {
        "baseline_year": "FY2024", "forecast_horizon": 2,
        "assumptions": {
            "revenue_growth": [0.1, 0.1], "gross_margin": 0.35, "ebitda_margin": 0.15,
            "opex_percent_revenue": 0.2, "da_percent_revenue": 0.05, "tax_rate": 0.25,
            "capex_percent_revenue": 0.04, "interest_expense": [2, 2],
            "receivable_days": 36.5, "inventory_days": 73, "payable_days": 36.5,
        },
        "scenarios": {"bull": {"revenue_growth": [0.2, 0.2]}, "bear": {"revenue_growth": [0.05, 0.05]}},
    }


def test_forecast_create_revision_retrieval_sensitivity_and_exports_are_company_scoped(tmp_path):
    app = forecast_app(tmp_path)
    created = request(app, "POST", "/api/companies/TEST_CO/forecasts?statement_basis=consolidated", json=payload())
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    forecast_id = data["forecast_id"]
    assert data["revision"] == 1
    assert Decimal(data["result"]["scenarios"]["bull"]["periods"][0]["revenue"]) == Decimal("120")
    assert data["result"]["scenarios"]["base"]["periods"][0]["unlevered_free_cash_flow"] is not None
    listed = request(app, "GET", "/api/companies/TEST_CO/forecasts")
    assert listed.status_code == 200 and len(listed.json()["data"]) == 1
    detail = request(app, "GET", f"/api/companies/TEST_CO/forecasts/{forecast_id}")
    assert detail.json()["data"]["input_data_stale"] is False
    sensitivity = request(app, "POST", f"/api/companies/TEST_CO/forecasts/{forecast_id}/sensitivity", json={"revenue_growth_values": [0.08, 0.1], "ebitda_margin_values": [0.14, 0.15]})
    assert sensitivity.status_code == 200 and len(sensitivity.json()["data"]["sensitivity"]) == 4
    comparison = request(app, "GET", f"/api/companies/TEST_CO/forecasts/{forecast_id}/actual-vs-forecast")
    assert comparison.status_code == 200
    assert [row["period_type"] for row in comparison.json()["data"]["periods"]] == ["actual", "forecast", "forecast"]
    exported = request(app, "GET", f"/api/companies/TEST_CO/forecasts/{forecast_id}/export?format=csv")
    assert exported.status_code == 200 and "assumptions_json" in exported.text and "metric_definitions_json" in exported.text and "model_limitations_json" in exported.text and "unlevered_free_cash_flow" in exported.text and "base,actual,FY2024" in exported.text
    updated_payload = payload()
    updated_payload["assumptions"]["revenue_growth"] = [0.12, 0.12]
    updated = request(app, "PUT", f"/api/companies/TEST_CO/forecasts/{forecast_id}", json=updated_payload)
    assert updated.status_code == 200 and updated.json()["data"]["revision"] == 2
    history = request(app, "GET", f"/api/companies/TEST_CO/forecasts/{forecast_id}/revisions")
    assert [item["revision"] for item in history.json()["data"]] == [1, 2]
    archived = request(app, "GET", f"/api/companies/TEST_CO/forecasts/{forecast_id}/revisions/1")
    assert archived.status_code == 200 and archived.json()["data"]["current"] is False
    scenario_update = request(app, "PUT", f"/api/companies/TEST_CO/forecasts/{forecast_id}/scenarios", json={"scenarios": {"bull": {"revenue_growth": [0.3, 0.3]}}})
    assert scenario_update.status_code == 200 and scenario_update.json()["data"]["revision"] == 3
    assert Decimal(scenario_update.json()["data"]["result"]["scenarios"]["bull"]["periods"][0]["revenue"]) == Decimal("130")
    with connect_database(app.state.database_path) as db:
        db.execute("UPDATE financial_observations SET value='101' WHERE company_id='TEST_CO' AND line_item_id='revenue'")
        db.commit()
    stale = request(app, "GET", f"/api/companies/TEST_CO/forecasts/{forecast_id}")
    assert stale.json()["data"]["input_data_stale"] is True
    assert request(app, "GET", f"/api/companies/OTHER/forecasts/{forecast_id}").status_code == 404


def test_forecast_validation_and_missing_company_errors_are_actionable(tmp_path):
    app = forecast_app(tmp_path)
    request_schema = app.openapi()["paths"]["/api/companies/{company_id}/forecasts"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/ForecastRequest")
    missing = request(app, "POST", "/api/companies/UNKNOWN/forecasts", json=payload())
    invalid = request(app, "POST", "/api/companies/TEST_CO/forecasts", json={**payload(), "forecast_horizon": 99})
    bad_sensitivity = request(app, "POST", "/api/companies/TEST_CO/forecasts/unknown/sensitivity", json={"revenue_growth_values": [], "ebitda_margin_values": []})
    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert bad_sensitivity.status_code == 422


@pytest.mark.parametrize("method", ["POST", "PUT"])
def test_forecast_write_preflight_allows_github_pages_origin(tmp_path, method):
    origin = "https://ryanconquers.github.io"
    app = create_app(tmp_path / "cors.sqlite3", cors_origins=[origin])
    response = request(
        app,
        "OPTIONS",
        "/api/companies/TEST_CO/forecasts",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert method in response.headers["access-control-allow-methods"]
