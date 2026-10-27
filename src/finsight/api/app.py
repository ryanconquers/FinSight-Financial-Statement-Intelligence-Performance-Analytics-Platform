"""FastAPI read API for company availability, metrics, and source provenance."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Path as PathParameter, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from finsight.db.connection import connect_database
from finsight.metrics.calculator import calculate_company_metrics
from finsight.metrics.repository import company_exists, company_provenance, list_companies, load_company_observations


def _configured_origins() -> list[str]:
    raw = os.getenv("FINSIGHT_CORS_ORIGINS", "http://localhost:3000")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app(
    database_path: str | Path | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Build an app with environment-based runtime settings and injectable test settings."""
    app = FastAPI(
        title="FinSight API",
        version="0.3.0",
        description="Read-only financial observation and metric endpoints. No real filings are onboarded yet.",
    )
    app.state.database_path = str(database_path or os.getenv("FINSIGHT_DATABASE_PATH", "data/finsight.sqlite3"))
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

    @app.get("/api/companies/{company_id}/provenance", tags=["companies"])
    def provenance(
        company_id: Annotated[str, PathParameter(min_length=1, max_length=128)],
        connection: sqlite3.Connection = Depends(get_connection),
    ) -> dict[str, object]:
        if not company_exists(connection, company_id):
            raise HTTPException(status_code=404, detail="Company has no source-backed financial observations.")
        sources = company_provenance(connection, company_id)
        return {"data": sources, "meta": {"company_id": company_id, "count": len(sources)}}

    return app


app = create_app()
