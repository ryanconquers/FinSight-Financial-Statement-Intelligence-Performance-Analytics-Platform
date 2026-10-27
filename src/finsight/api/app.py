"""FastAPI read API for company availability, metrics, and source provenance."""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Path as PathParameter, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from finsight.analytics.benchmark import build_peer_benchmark
from finsight.analytics.config import load_risk_thresholds
from finsight.analytics.insights import build_financial_insights
from finsight.analytics.risk import analyze_financial_risk
from finsight.db.connection import connect_database, validate_database_path
from finsight.metrics.calculator import calculate_company_metrics
from finsight.metrics.repository import company_exists, company_provenance, list_companies, list_company_observations, load_company_observations
from finsight.reports.generator import build_company_report, report_csv


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


def create_app(
    database_path: str | Path | None = None,
    cors_origins: list[str] | None = None,
    risk_thresholds_path: str | Path | None = None,
) -> FastAPI:
    """Build an app with environment-based runtime settings and injectable test settings."""
    app = FastAPI(
        title="FinSight API",
        version="0.3.0",
        description="Read-only financial observation and metric endpoints. No real filings are onboarded yet.",
    )
    app.state.database_path = str(database_path or os.getenv("FINSIGHT_DATABASE_PATH", "data/finsight.sqlite3"))
    validate_database_path(app.state.database_path)
    default_risk_config = Path(__file__).resolve().parents[3] / "config" / "financial_risk_thresholds.toml"
    app.state.risk_thresholds = load_risk_thresholds(risk_thresholds_path or default_risk_config)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins if cors_origins is not None else _configured_origins(),
        allow_credentials=False,
        allow_methods=["GET", "OPTIONS"],
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

    return app


app = create_app()
