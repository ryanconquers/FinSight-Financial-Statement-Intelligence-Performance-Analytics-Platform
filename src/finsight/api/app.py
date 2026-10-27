"""FastAPI read API for company availability, metrics, and source provenance."""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Path as PathParameter, Query, Request, status as http_status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from finsight.analytics.benchmark import build_peer_benchmark
from finsight.analytics.config import load_risk_thresholds
from finsight.analytics.insights import build_financial_insights
from finsight.analytics.risk import analyze_financial_risk
from finsight.db.connection import connect_database, validate_database_path
from finsight.metrics.calculator import calculate_company_metrics
from finsight.metrics.repository import company_exists, company_provenance, list_companies, list_company_observations, load_company_observations
from finsight.reports.generator import build_company_report, report_csv
from finsight.forecasting.engine import FORECAST_VERSION, build_forecast, build_sensitivity, forecast_input_fingerprint
from finsight.forecasting.repository import get_forecast, get_revision, list_forecasts, list_revisions, save_forecast
from finsight.forecasting.export import forecast_csv


class ForecastRequest(BaseModel):
    """Structured create request; numerical modeling rules are validated by the engine."""

    model_config = ConfigDict(extra="forbid")
    baseline_year: str = Field(pattern=r"^FY\d{4}$")
    forecast_horizon: int = Field(default=5, ge=1, le=10)
    currency: str | None = None
    unit: str | None = None
    assumptions: dict[str, Any]
    scenarios: dict[Literal["bull", "bear"], dict[str, Any]] | None = None


class ForecastUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_year: str | None = Field(default=None, pattern=r"^FY\d{4}$")
    forecast_horizon: int | None = Field(default=None, ge=1, le=10)
    currency: str | None = None
    unit: str | None = None
    assumptions: dict[str, Any]
    scenarios: dict[Literal["bull", "bear"], dict[str, Any]] | None = None


class ForecastScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenarios: dict[Literal["bull", "bear"], dict[str, Any]]


class ForecastSensitivityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revenue_growth_values: list[float] = Field(min_length=1, max_length=11)
    ebitda_margin_values: list[float] = Field(min_length=1, max_length=11)


def _configured_origins() -> list[str]:
    raw = os.getenv("FINSIGHT_CORS_ORIGINS", "http://localhost:3000")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _attach_peer_provenance(
    connection: sqlite3.Connection,
    benchmark: dict[str, object],
    statement_basis: str,
) -> None:
    """Attach document references for the exact source observations behind peer values."""
    for item in benchmark.get("metrics", []):
        if not isinstance(item, dict):
            continue
        for value in item.get("values", []):
            if not isinstance(value, dict):
                continue
            evidence = value.get("evidence")
            if not isinstance(evidence, dict):
                value["sources"] = []
                continue
            inputs = evidence.get("inputs", [])
            source_periods = {
                (source_input.get("source_id"), source_input.get("financial_year"))
                for source_input in inputs if isinstance(source_input, dict)
            }
            sources = company_provenance(connection, str(value["company_id"]), statement_basis)
            value["sources"] = [
                source for source in sources
                if (source["source_id"], source["financial_year"]) in source_periods
            ]


def _attach_forecast_provenance(connection: sqlite3.Connection, company_id: str, statement_basis: str, result: dict[str, object]) -> None:
    """Snapshot source-register metadata for every actual input period in an exportable forecast."""
    source_ids = set(result.get("created_from_source_ids", []))
    for period in result.get("historical_actuals", []):
        source_ids.update(period.get("source_ids", []))
    provenance = company_provenance(connection, company_id, statement_basis)
    result["source_provenance"] = [source for source in provenance if source["source_id"] in source_ids]


def create_app(
    database_path: str | Path | None = None,
    cors_origins: list[str] | None = None,
    risk_thresholds_path: str | Path | None = None,
) -> FastAPI:
    """Build an app with environment-based runtime settings and injectable test settings."""
    app = FastAPI(
        title="FinSight API",
        version="0.3.0",
        description="Financial observation, metric, analytical, and forecast endpoints. No real filings are onboarded yet.",
    )
    app.state.database_path = str(database_path or os.getenv("FINSIGHT_DATABASE_PATH", "data/finsight.sqlite3"))
    validate_database_path(app.state.database_path)
    default_risk_config = Path(__file__).resolve().parents[3] / "config" / "financial_risk_thresholds.toml"
    app.state.risk_thresholds = load_risk_thresholds(risk_thresholds_path or default_risk_config)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins if cors_origins is not None else _configured_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Accept", "Content-Type"],
    )

    def get_connection():
        connection = connect_database(app.state.database_path)
        try:
            yield connection
        finally:
            connection.close()

    @app.exception_handler(HTTPException)
    async def http_error_handler(_request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
        code = "not_found" if exc.status_code == 404 else "request_error"
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": detail}, "meta": {}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(part) for part in error.get("loc", ())[1:]), "message": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_request", "message": "One or more request parameters are invalid.", "details": details}, "meta": {}},
        )

    @app.get("/api/health", tags=["status"])
    def health() -> dict[str, object]:
        """Liveness endpoint; intentionally independent of local database paths."""
        return {"data": {"status": "ok"}, "meta": {"service": "finsight-api"}}

    @app.get("/api/status", tags=["status"])
    def status(connection: sqlite3.Connection = Depends(get_connection)) -> dict[str, object]:
        count = connection.execute(
            """SELECT COUNT(*) FROM financial_observations f
               JOIN sources s ON s.source_id = f.source_id
               WHERE f.is_synthetic = 0 AND s.is_synthetic = 0"""
        ).fetchone()[0]
        return {
            "data": {
                "project_status": "under_development",
                "data_availability": "available" if count else "empty",
                "source_backed_observation_count": count,
                "real_financial_data_onboarded": bool(count),
            },
            "meta": {},
        }

    @app.get("/api/companies", tags=["companies"])
    def companies(connection: sqlite3.Connection = Depends(get_connection)) -> dict[str, object]:
        results = list_companies(connection)
        return {"data": results, "meta": {"count": len(results)}}

    @app.get("/api/companies/{company_id}/metrics", tags=["metrics"])
    def company_metrics(
        company_id: Annotated[str, PathParameter(min_length=1, max_length=128)],
        statement_basis: Annotated[Literal["standalone", "consolidated"], Query()] = "consolidated",
        financial_year: Annotated[str | None, Query(pattern=r"^FY\d{4}$")] = None,
        connection: sqlite3.Connection = Depends(get_connection),
    ) -> dict[str, object]:
        if not company_exists(connection, company_id):
            raise HTTPException(status_code=404, detail="Company has no source-backed financial observations.")
        inputs = load_company_observations(connection, company_id, statement_basis)
        results = calculate_company_metrics(inputs)
        if financial_year:
            results = [result for result in results if result.financial_year == financial_year]
        return {
            "data": [result.to_dict() for result in results],
            "meta": {
                "company_id": company_id,
                "statement_basis": statement_basis,
                "financial_year": financial_year,
                "count": len(results),
            },
        }

    @app.get("/api/companies/{company_id}/analysis", tags=["analytics"])
    def company_analysis(
        company_id: Annotated[str, PathParameter(min_length=1, max_length=128)],
        statement_basis: Annotated[Literal["standalone", "consolidated"], Query()] = "consolidated",
        connection: sqlite3.Connection = Depends(get_connection),
    ) -> dict[str, object]:
        """Return rule assessments derived from the existing M3 metric results."""
        if not company_exists(connection, company_id):
            raise HTTPException(status_code=404, detail="Company has no source-backed financial observations.")
        observations = load_company_observations(connection, company_id, statement_basis)
        metrics = calculate_company_metrics(observations)
        assessments = analyze_financial_risk(metrics, app.state.risk_thresholds)
        return {
            "data": {
                "company_id": company_id,
                "statement_basis": statement_basis,
                "configuration_version": app.state.risk_thresholds.version,
                "assessments": [assessment.to_dict() for assessment in assessments],
            },
            "meta": {"company_id": company_id, "statement_basis": statement_basis, "count": len(assessments)},
        }

    @app.get("/api/companies/{company_id}/insights", tags=["analytics"])
    def company_insights(
        company_id: Annotated[str, PathParameter(min_length=1, max_length=128)],
        statement_basis: Annotated[Literal["standalone", "consolidated"], Query()] = "consolidated",
        peer_ids: Annotated[list[str] | None, Query(max_length=20)] = None,
        connection: sqlite3.Connection = Depends(get_connection),
    ) -> dict[str, object]:
        """Return deterministic observations derived from adjacent compatible M3 metrics."""
        if not company_exists(connection, company_id):
            raise HTTPException(status_code=404, detail="Company has no source-backed financial observations.")
        metrics = calculate_company_metrics(load_company_observations(connection, company_id, statement_basis))
        assessments = analyze_financial_risk(metrics, app.state.risk_thresholds)
        benchmark = None
        selected_peers = list(dict.fromkeys(peer_ids or []))
        if company_id in selected_peers:
            raise HTTPException(status_code=422, detail="The target company cannot also be listed as a peer.")
        if selected_peers:
            metric_sets: dict[str, list] = {company_id: metrics}
            for peer_id in selected_peers:
                if not company_exists(connection, peer_id):
                    raise HTTPException(status_code=404, detail=f"Selected company {peer_id!r} has no source-backed observations.")
                metric_sets[peer_id] = calculate_company_metrics(load_company_observations(connection, peer_id, statement_basis))
            benchmark = build_peer_benchmark(company_id, selected_peers, metric_sets, statement_basis=statement_basis)
            _attach_peer_provenance(connection, benchmark, statement_basis)
        insights = build_financial_insights(metrics, assessments, benchmark)
        return {"data": {"company_id": company_id, "statement_basis": statement_basis, "insights": insights, "peer_benchmark_status": benchmark.get("status") if benchmark else None}, "meta": {"count": len(insights)}}

    @app.get("/api/companies/{company_id}/benchmark", tags=["analytics"])
    def company_benchmark(
        company_id: Annotated[str, PathParameter(min_length=1, max_length=128)],
        peer_ids: Annotated[list[str], Query(min_length=1, max_length=20)],
        statement_basis: Annotated[Literal["standalone", "consolidated"], Query()] = "consolidated",
        financial_year: Annotated[str | None, Query(pattern=r"^FY\d{4}$")] = None,
        connection: sqlite3.Connection = Depends(get_connection),
    ) -> dict[str, object]:
        """Compare selected source-backed peers using exact-period compatible metrics."""
        if not company_exists(connection, company_id):
            raise HTTPException(status_code=404, detail="Company has no source-backed financial observations.")
        requested = list(dict.fromkeys(peer_ids))
        if company_id in requested:
            raise HTTPException(status_code=422, detail="The target company cannot also be listed as a peer.")
        metric_sets: dict[str, list] = {}
        for selected_id in [company_id, *requested]:
            if not company_exists(connection, selected_id):
                raise HTTPException(status_code=404, detail=f"Selected company {selected_id!r} has no source-backed observations.")
            observations = load_company_observations(connection, selected_id, statement_basis)
            metric_sets[selected_id] = calculate_company_metrics(observations)
        try:
            result = build_peer_benchmark(company_id, requested, metric_sets, statement_basis=statement_basis, financial_year=financial_year)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _attach_peer_provenance(connection, result, statement_basis)
        return {"data": result, "meta": {"metric_count": len(result["metrics"])}}

    @app.get("/api/companies/{company_id}/report", tags=["reports"], response_model=None)
    def company_report(
        company_id: Annotated[str, PathParameter(min_length=1, max_length=128)],
        statement_basis: Annotated[Literal["standalone", "consolidated"], Query()] = "consolidated",
        export_format: Annotated[Literal["json", "csv"], Query(alias="format")] = "json",
        peer_ids: Annotated[list[str] | None, Query(max_length=20)] = None,
        connection: sqlite3.Connection = Depends(get_connection),
    ) -> dict[str, object] | Response:
        """Export a current, read-only analyst report in JSON or flattened metric CSV."""
        if not company_exists(connection, company_id):
            raise HTTPException(status_code=404, detail="Company has no source-backed financial observations.")
        observations = load_company_observations(connection, company_id, statement_basis)
        metrics = calculate_company_metrics(observations)
        assessments = analyze_financial_risk(metrics, app.state.risk_thresholds)
        benchmark = None
        selected_peers = list(dict.fromkeys(peer_ids or []))
        if company_id in selected_peers:
            raise HTTPException(status_code=422, detail="The target company cannot also be listed as a peer.")
        if selected_peers:
            metric_sets: dict[str, list] = {company_id: metrics}
            for peer_id in selected_peers:
                if not company_exists(connection, peer_id):
                    raise HTTPException(status_code=404, detail=f"Selected company {peer_id!r} has no source-backed observations.")
                metric_sets[peer_id] = calculate_company_metrics(load_company_observations(connection, peer_id, statement_basis))
            benchmark = build_peer_benchmark(company_id, selected_peers, metric_sets, statement_basis=statement_basis)
            _attach_peer_provenance(connection, benchmark, statement_basis)
        if export_format == "csv":
            safe_company_id = re.sub(r"[^A-Za-z0-9_-]", "_", company_id)
            return Response(
                content=report_csv(metrics), media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="finsight-{safe_company_id}-{statement_basis}.csv"'},
            )
        report = build_company_report(connection, company_id, statement_basis, observations, metrics, assessments, app.state.risk_thresholds.version, benchmark)
        return {"data": report, "meta": {"report_version": report["report_version"]}}

    @app.get("/api/companies/{company_id}/provenance", tags=["companies"])
    def provenance(
        company_id: Annotated[str, PathParameter(min_length=1, max_length=128)],
        statement_basis: Annotated[Literal["standalone", "consolidated"] | None, Query()] = None,
        connection: sqlite3.Connection = Depends(get_connection),
    ) -> dict[str, object]:
        if not company_exists(connection, company_id):
            raise HTTPException(status_code=404, detail="Company has no source-backed financial observations.")
        sources = company_provenance(connection, company_id, statement_basis)
        return {"data": sources, "meta": {"company_id": company_id, "statement_basis": statement_basis, "count": len(sources)}}

    @app.get("/api/companies/{company_id}/observations", tags=["companies"])
    def reported_observations(
        company_id: Annotated[str, PathParameter(min_length=1, max_length=128)],
        statement_basis: Annotated[Literal["standalone", "consolidated"], Query()] = "consolidated",
        financial_year: Annotated[str | None, Query(pattern=r"^FY\d{4}$")] = None,
        connection: sqlite3.Connection = Depends(get_connection),
    ) -> dict[str, object]:
        """Return original reported line-item labels and values, separate from metrics."""
        if not company_exists(connection, company_id):
            raise HTTPException(status_code=404, detail="Company has no source-backed financial observations.")
        results = list_company_observations(connection, company_id, statement_basis, financial_year)
        return {"data": results, "meta": {"company_id": company_id, "statement_basis": statement_basis, "financial_year": financial_year, "count": len(results)}}

    @app.post("/api/companies/{company_id}/forecasts", tags=["forecasting"], status_code=http_status.HTTP_201_CREATED)
    def create_forecast(
        company_id: Annotated[str, PathParameter(min_length=1, max_length=128)],
        payload: ForecastRequest,
        statement_basis: Annotated[Literal["standalone", "consolidated"], Query()] = "consolidated",
        connection: sqlite3.Connection = Depends(get_connection),
    ) -> dict[str, object]:
        """Validate assumptions and save an immutable-baseline, versioned forecast."""
        if not company_exists(connection, company_id):
            raise HTTPException(status_code=404, detail="Company has no source-backed financial observations.")
        try:
            baseline_year = payload.baseline_year
            horizon = payload.forecast_horizon
            assumptions = payload.assumptions
            scenarios = payload.scenarios
            observations = load_company_observations(connection, company_id, statement_basis)
            result = build_forecast(observations, company_id=company_id, statement_basis=statement_basis, baseline_year=baseline_year, horizon=horizon, assumptions=assumptions, scenarios=scenarios)
            _attach_forecast_provenance(connection, company_id, statement_basis, result)
            baseline = [item for item in observations if item.financial_year == baseline_year]
            for field, expected in (("currency", baseline[0].currency), ("unit", baseline[0].unit)):
                if getattr(payload, field) is not None and getattr(payload, field) != expected:
                    raise ValueError(f"{field} must match the selected historical baseline; conversions are not supported.")
            stored_assumptions = {"assumptions": assumptions, "scenarios": scenarios}
            record = save_forecast(connection, forecast_id=str(uuid.uuid4()), company_id=company_id, basis=statement_basis, baseline_year=baseline_year, horizon=horizon, assumptions=stored_assumptions, result=result)
            record = get_forecast(connection, record["forecast_id"], company_id) or record
            record["input_data_stale"] = False
            return {"data": record, "meta": {"methodology_version": FORECAST_VERSION}}
        except KeyError as exc:
            raise HTTPException(status_code=422, detail=f"Missing required forecast field: {exc.args[0]}.") from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/companies/{company_id}/forecasts", tags=["forecasting"])
    def company_forecasts(company_id: Annotated[str, PathParameter(min_length=1, max_length=128)], connection: sqlite3.Connection = Depends(get_connection)) -> dict[str, object]:
        if not company_exists(connection, company_id):
            raise HTTPException(status_code=404, detail="Company has no source-backed financial observations.")
        items = list_forecasts(connection, company_id)
        observations_by_basis: dict[str, list] = {}
        for item in items:
            basis = item["statement_basis"]
            observations_by_basis.setdefault(basis, load_company_observations(connection, company_id, basis))
            item["input_data_stale"] = forecast_input_fingerprint(observations_by_basis[basis], item["baseline_year"], basis) != item["input_fingerprint"]
        return {"data": items, "meta": {"count": len(items)}}

    @app.get("/api/companies/{company_id}/forecasts/{forecast_id}", tags=["forecasting"])
    def retrieve_forecast(company_id: str, forecast_id: str, connection: sqlite3.Connection = Depends(get_connection)) -> dict[str, object]:
        record = get_forecast(connection, forecast_id, company_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Forecast was not found for this company.")
        observations = load_company_observations(connection, company_id, record["statement_basis"])
        current_fingerprint = forecast_input_fingerprint(observations, record["baseline_year"], record["statement_basis"])
        record["input_data_stale"] = current_fingerprint != record["input_fingerprint"]
        return {"data": record, "meta": {"revision": record["revision"]}}

    @app.get("/api/companies/{company_id}/forecasts/{forecast_id}/revisions", tags=["forecasting"])
    def forecast_revisions(company_id: str, forecast_id: str, connection: sqlite3.Connection = Depends(get_connection)) -> dict[str, object]:
        revisions = list_revisions(connection, forecast_id, company_id)
        if revisions is None:
            raise HTTPException(status_code=404, detail="Forecast was not found for this company.")
        return {"data": revisions, "meta": {"count": len(revisions)}}

    @app.get("/api/companies/{company_id}/forecasts/{forecast_id}/revisions/{revision}", tags=["forecasting"])
    def retrieve_forecast_revision(company_id: str, forecast_id: str, revision: int, connection: sqlite3.Connection = Depends(get_connection)) -> dict[str, object]:
        if revision < 1:
            raise HTTPException(status_code=422, detail="revision must be a positive integer.")
        version = get_revision(connection, forecast_id, company_id, revision)
        if version is None:
            raise HTTPException(status_code=404, detail="Forecast revision was not found for this company.")
        observations = load_company_observations(connection, company_id, version["statement_basis"])
        version["input_data_stale"] = forecast_input_fingerprint(observations, version["baseline_year"], version["statement_basis"]) != version["input_fingerprint"]
        return {"data": version, "meta": {"forecast_id": forecast_id, "revision": revision}}

    @app.put("/api/companies/{company_id}/forecasts/{forecast_id}", tags=["forecasting"])
    def update_forecast(company_id: str, forecast_id: str, payload: ForecastUpdateRequest, connection: sqlite3.Connection = Depends(get_connection)) -> dict[str, object]:
        existing = get_forecast(connection, forecast_id, company_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Forecast was not found for this company.")
        try:
            assumptions = payload.assumptions
            scenarios = payload.scenarios if payload.scenarios is not None else existing["assumptions"].get("scenarios")
            observations = load_company_observations(connection, company_id, existing["statement_basis"])
            baseline_year = payload.baseline_year or existing["baseline_year"]
            horizon = payload.forecast_horizon or existing["forecast_horizon"]
            result = build_forecast(observations, company_id=company_id, statement_basis=existing["statement_basis"], baseline_year=baseline_year, horizon=horizon, assumptions=assumptions, scenarios=scenarios)
            _attach_forecast_provenance(connection, company_id, existing["statement_basis"], result)
            baseline = next(item for item in observations if item.financial_year == baseline_year)
            for field, expected in (("currency", baseline.currency), ("unit", baseline.unit)):
                if getattr(payload, field) is not None and getattr(payload, field) != expected:
                    raise ValueError(f"{field} must match the selected historical baseline; conversions are not supported.")
            record = save_forecast(connection, forecast_id=forecast_id, company_id=company_id, basis=existing["statement_basis"], baseline_year=baseline_year, horizon=horizon, assumptions={"assumptions": assumptions, "scenarios": scenarios}, result=result, update=True)
            record = get_forecast(connection, forecast_id, company_id) or record
            record["input_data_stale"] = False
            return {"data": record, "meta": {"revision": record["revision"]}}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.put("/api/companies/{company_id}/forecasts/{forecast_id}/scenarios", tags=["forecasting"])
    def update_forecast_scenarios(company_id: str, forecast_id: str, payload: ForecastScenarioRequest, connection: sqlite3.Connection = Depends(get_connection)) -> dict[str, object]:
        existing = get_forecast(connection, forecast_id, company_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Forecast was not found for this company.")
        scenarios = dict(existing["assumptions"].get("scenarios") or {}) | payload.scenarios
        assumptions = existing["assumptions"]["assumptions"]
        observations = load_company_observations(connection, company_id, existing["statement_basis"])
        try:
            result = build_forecast(observations, company_id=company_id, statement_basis=existing["statement_basis"], baseline_year=existing["baseline_year"], horizon=existing["forecast_horizon"], assumptions=assumptions, scenarios=scenarios)
            _attach_forecast_provenance(connection, company_id, existing["statement_basis"], result)
            record = save_forecast(connection, forecast_id=forecast_id, company_id=company_id, basis=existing["statement_basis"], baseline_year=existing["baseline_year"], horizon=existing["forecast_horizon"], assumptions={"assumptions": assumptions, "scenarios": scenarios}, result=result, update=True)
            record = get_forecast(connection, forecast_id, company_id) or record
            record["input_data_stale"] = False
            return {"data": record, "meta": {"revision": record["revision"]}}
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/companies/{company_id}/forecasts/{forecast_id}/sensitivity", tags=["forecasting"])
    def forecast_sensitivity(company_id: str, forecast_id: str, payload: ForecastSensitivityRequest, connection: sqlite3.Connection = Depends(get_connection)) -> dict[str, object]:
        record = get_forecast(connection, forecast_id, company_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Forecast was not found for this company.")
        try:
            observations = load_company_observations(connection, company_id, record["statement_basis"])
            assumptions = record["assumptions"]["assumptions"]
            result = build_sensitivity(observations, company_id=company_id, statement_basis=record["statement_basis"], baseline_year=record["baseline_year"], horizon=record["forecast_horizon"], assumptions=assumptions, growth_values=payload.revenue_growth_values, ebitda_margin_values=payload.ebitda_margin_values)
            return {"data": result, "meta": {"forecast_id": forecast_id, "saved_revision": record["revision"]}}
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/companies/{company_id}/forecasts/{forecast_id}/actual-vs-forecast", tags=["forecasting"])
    def forecast_actual_comparison(company_id: str, forecast_id: str, connection: sqlite3.Connection = Depends(get_connection)) -> dict[str, object]:
        record = get_forecast(connection, forecast_id, company_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Forecast was not found for this company.")
        observations = load_company_observations(connection, company_id, record["statement_basis"])
        current = forecast_input_fingerprint(observations, record["baseline_year"], record["statement_basis"])
        result = record["result"]
        base_scenario = result["scenarios"]["base"]
        return {"data": {"company_id": company_id, "statement_basis": record["statement_basis"], "periods": [*base_scenario.get("actual_history", [base_scenario["actual_baseline"]]), *base_scenario["periods"]], "missing_historical_years": result.get("missing_historical_years", []), "input_data_stale": current != record["input_fingerprint"]}, "meta": {"forecast_id": forecast_id}}

    @app.get("/api/companies/{company_id}/forecasts/{forecast_id}/export", tags=["forecasting"], response_model=None)
    def export_forecast(company_id: str, forecast_id: str, export_format: Annotated[Literal["json", "csv"], Query(alias="format")] = "json", connection: sqlite3.Connection = Depends(get_connection)) -> dict[str, object] | Response:
        record = get_forecast(connection, forecast_id, company_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Forecast was not found for this company.")
        observations = load_company_observations(connection, company_id, record["statement_basis"])
        record["input_data_stale"] = forecast_input_fingerprint(observations, record["baseline_year"], record["statement_basis"]) != record["input_fingerprint"]
        if export_format == "json":
            return {"data": record, "meta": {"export_version": "finsight-forecast-export-v1"}}
        content = forecast_csv(record, input_data_stale=record["input_data_stale"])
        return Response(content=content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="finsight-forecast-{forecast_id}.csv"'})

    return app


app = create_app()
