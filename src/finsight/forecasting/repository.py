"""Transactional SQLite persistence for reproducible forecast revisions."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def save_forecast(connection: sqlite3.Connection, *, forecast_id: str, company_id: str, basis: str, baseline_year: str, horizon: int, assumptions: dict[str, Any], result: dict[str, Any], update: bool = False) -> dict[str, Any]:
    assumptions_json = json.dumps(assumptions, sort_keys=True, separators=(",", ":"))
    result_json = json.dumps(result, sort_keys=True, separators=(",", ":"))
    fingerprint = str(result["input_fingerprint"])
    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = connection.execute("SELECT revision, company_id FROM forecasts WHERE forecast_id = ?", (forecast_id,)).fetchone()
        if update:
            if existing is None:
                raise KeyError("Forecast was not found.")
            if existing["company_id"] != company_id:
                raise PermissionError("Forecast does not belong to the requested company.")
            revision = int(existing["revision"]) + 1
            connection.execute(
                """INSERT INTO forecast_revisions (forecast_id, revision, assumptions_json, input_fingerprint, result_json)
                   SELECT forecast_id, revision, assumptions_json, input_fingerprint, result_json FROM forecasts WHERE forecast_id = ?""",
                (forecast_id,),
            )
            connection.execute(
                """UPDATE forecasts SET baseline_year=?, horizon=?, methodology_version=?, assumptions_json=?, input_fingerprint=?, result_json=?, revision=?, updated_at=CURRENT_TIMESTAMP WHERE forecast_id=?""",
                (baseline_year, horizon, result["methodology_version"], assumptions_json, fingerprint, result_json, revision, forecast_id),
            )
        else:
            if existing is not None:
                raise ValueError("Forecast identifier already exists.")
            revision = 1
            connection.execute(
                """INSERT INTO forecasts (forecast_id, company_id, statement_basis, baseline_year, horizon, methodology_version, assumptions_json, input_fingerprint, result_json, revision)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (forecast_id, company_id, basis, baseline_year, horizon, result["methodology_version"], assumptions_json, fingerprint, result_json),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {"forecast_id": forecast_id, "company_id": company_id, "statement_basis": basis, "baseline_year": baseline_year, "forecast_horizon": horizon, "methodology_version": result["methodology_version"], "assumptions": assumptions, "revision": revision, "created_at": None, "updated_at": None, "input_fingerprint": fingerprint, "result": result}


def get_forecast(connection: sqlite3.Connection, forecast_id: str, company_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM forecasts WHERE forecast_id=? AND company_id=?", (forecast_id, company_id)).fetchone()
    if row is None:
        return None
    return _decode(row)


def list_forecasts(connection: sqlite3.Connection, company_id: str) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT * FROM forecasts WHERE company_id=? ORDER BY created_at DESC, forecast_id", (company_id,)).fetchall()
    return [_decode(row, include_result=False) for row in rows]


def list_revisions(connection: sqlite3.Connection, forecast_id: str, company_id: str) -> list[dict[str, Any]] | None:
    if connection.execute("SELECT 1 FROM forecasts WHERE forecast_id=? AND company_id=?", (forecast_id, company_id)).fetchone() is None:
        return None
    rows = connection.execute("SELECT revision, assumptions_json, input_fingerprint, saved_at FROM forecast_revisions WHERE forecast_id=? ORDER BY revision", (forecast_id,)).fetchall()
    current = connection.execute("SELECT revision, assumptions_json, input_fingerprint, updated_at FROM forecasts WHERE forecast_id=?", (forecast_id,)).fetchone()
    versions = [{"revision": row["revision"], "assumptions": json.loads(row["assumptions_json"]), "input_fingerprint": row["input_fingerprint"], "saved_at": row["saved_at"]} for row in rows]
    versions.append({"revision": current["revision"], "assumptions": json.loads(current["assumptions_json"]), "input_fingerprint": current["input_fingerprint"], "saved_at": current["updated_at"], "current": True})
    return versions


def get_revision(connection: sqlite3.Connection, forecast_id: str, company_id: str, revision: int) -> dict[str, Any] | None:
    parent = connection.execute("SELECT * FROM forecasts WHERE forecast_id=? AND company_id=?", (forecast_id, company_id)).fetchone()
    if parent is None:
        return None
    row = connection.execute("SELECT revision, assumptions_json, input_fingerprint, result_json, saved_at FROM forecast_revisions WHERE forecast_id=? AND revision=?", (forecast_id, revision)).fetchone()
    if row:
        result = json.loads(row["result_json"])
        return {"forecast_id": forecast_id, "company_id": company_id, "statement_basis": result["statement_basis"], "baseline_year": result["baseline_year"], "forecast_horizon": result["forecast_horizon"], "methodology_version": result["methodology_version"], "revision": row["revision"], "assumptions": json.loads(row["assumptions_json"]), "input_fingerprint": row["input_fingerprint"], "result": result, "saved_at": row["saved_at"], "current": False}
    current = connection.execute("SELECT revision, assumptions_json, input_fingerprint, result_json, updated_at FROM forecasts WHERE forecast_id=? AND company_id=? AND revision=?", (forecast_id, company_id, revision)).fetchone()
    if current:
        result = json.loads(current["result_json"])
        return {"forecast_id": forecast_id, "company_id": company_id, "statement_basis": result["statement_basis"], "baseline_year": result["baseline_year"], "forecast_horizon": result["forecast_horizon"], "methodology_version": result["methodology_version"], "revision": current["revision"], "assumptions": json.loads(current["assumptions_json"]), "input_fingerprint": current["input_fingerprint"], "result": result, "saved_at": current["updated_at"], "current": True}
    return None


def _decode(row: sqlite3.Row, *, include_result: bool = True) -> dict[str, Any]:
    result = {
        "forecast_id": row["forecast_id"], "company_id": row["company_id"], "statement_basis": row["statement_basis"],
        "baseline_year": row["baseline_year"], "forecast_horizon": row["horizon"], "methodology_version": row["methodology_version"],
        "assumptions": json.loads(row["assumptions_json"]), "revision": row["revision"], "created_at": row["created_at"],
        "updated_at": row["updated_at"], "input_fingerprint": row["input_fingerprint"],
    }
    if include_result:
        result["result"] = json.loads(row["result_json"])
    return result
