"""Database read adapter for metric inputs; calculation logic stays pure."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from finsight.metrics.models import FinancialObservation


def load_company_observations(
    connection: sqlite3.Connection,
    company_id: str,
    statement_basis: str,
) -> list[FinancialObservation]:
    """Load observations for one company and statement basis in period order."""
    rows = connection.execute(
        """SELECT f.observation_id, f.company_id, f.financial_year, f.period_start, f.period_end,
                  f.statement_basis, f.statement_type, f.line_item_id, f.value, f.unit, f.currency, f.source_id
           FROM financial_observations f
           JOIN sources s ON s.source_id = f.source_id
           WHERE company_id = ? AND statement_basis = ?
             AND f.is_synthetic = 0 AND s.is_synthetic = 0
           ORDER BY financial_year, statement_type, line_item_id""",
        (company_id, statement_basis),
    ).fetchall()
    return [
        FinancialObservation(
            observation_id=row["observation_id"],
            company_id=row["company_id"],
            financial_year=row["financial_year"],
            period_start=date.fromisoformat(row["period_start"]),
            period_end=date.fromisoformat(row["period_end"]),
            statement_basis=row["statement_basis"],
            statement_type=row["statement_type"],
            line_item_id=row["line_item_id"],
            value=Decimal(str(row["value"])) if row["value"] is not None else None,
            unit=row["unit"],
            currency=row["currency"],
            source_id=row["source_id"],
        )
        for row in rows
    ]


def list_companies(connection: sqlite3.Connection) -> list[dict[str, object]]:
    """List only companies with at least one financial observation."""
    rows = connection.execute(
        """SELECT c.company_id, c.company_name, c.ticker, c.reporting_currency,
                  COUNT(DISTINCT f.financial_year) AS financial_year_count,
                  MIN(f.financial_year) AS first_financial_year,
                  MAX(f.financial_year) AS last_financial_year
           FROM companies c
           JOIN financial_observations f ON f.company_id = c.company_id
           JOIN sources s ON s.source_id = f.source_id AND s.is_synthetic = 0
           WHERE f.is_synthetic = 0
           GROUP BY c.company_id, c.company_name, c.ticker, c.reporting_currency
           ORDER BY c.company_name, c.company_id"""
    ).fetchall()
    return [dict(row) for row in rows]


def company_exists(connection: sqlite3.Connection, company_id: str) -> bool:
    """Check whether a registered company has at least one observation."""
    return connection.execute(
        "SELECT 1 FROM companies c JOIN financial_observations f USING (company_id) JOIN sources s USING (source_id) WHERE c.company_id = ? AND f.is_synthetic = 0 AND s.is_synthetic = 0 LIMIT 1",
        (company_id,),
    ).fetchone() is not None


def company_provenance(connection: sqlite3.Connection, company_id: str) -> list[dict[str, object]]:
    """List distinct sources and periods attached to a company's observations."""
    rows = connection.execute(
        """SELECT DISTINCT s.source_id, s.publisher, s.source_url, s.publication_date,
                  s.retrieved_at, f.financial_year, f.statement_basis, f.statement_type
           FROM sources s
           JOIN financial_observations f ON f.source_id = s.source_id
           WHERE f.company_id = ? AND f.is_synthetic = 0 AND s.is_synthetic = 0
           ORDER BY f.financial_year, f.statement_basis, f.statement_type, s.source_id""",
        (company_id,),
    ).fetchall()
    return [dict(row) for row in rows]
