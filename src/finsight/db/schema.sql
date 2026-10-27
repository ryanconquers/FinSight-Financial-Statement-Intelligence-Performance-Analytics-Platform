PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    company_id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    ticker TEXT,
    exchange TEXT,
    reporting_currency TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    publisher TEXT NOT NULL,
    source_url TEXT,
    publication_date TEXT,
    retrieved_at TEXT NOT NULL,
    source_description TEXT,
    is_synthetic INTEGER NOT NULL DEFAULT 0 CHECK (is_synthetic IN (0, 1))
);

CREATE TABLE IF NOT EXISTS financial_observations (
    observation_id INTEGER PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(company_id),
    financial_year TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    statement_basis TEXT NOT NULL CHECK (statement_basis IN ('standalone', 'consolidated')),
    statement_type TEXT NOT NULL CHECK (statement_type IN ('income_statement', 'balance_sheet', 'cash_flow_statement')),
    line_item_id TEXT NOT NULL,
    reported_label TEXT NOT NULL,
    value NUMERIC,
    unit TEXT NOT NULL,
    currency TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    is_synthetic INTEGER NOT NULL DEFAULT 0 CHECK (is_synthetic IN (0, 1)),
    CHECK (period_start <= period_end),
    UNIQUE (company_id, financial_year, statement_basis, statement_type, line_item_id)
);

CREATE TABLE IF NOT EXISTS processing_logs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    input_name TEXT,
    source_id TEXT REFERENCES sources(source_id),
    status TEXT NOT NULL CHECK (status IN ('started', 'succeeded', 'failed', 'completed_with_warnings')),
    records_read INTEGER,
    records_written INTEGER,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS validation_results (
    validation_id INTEGER PRIMARY KEY,
    run_id TEXT REFERENCES processing_logs(run_id),
    observation_id INTEGER REFERENCES financial_observations(observation_id),
    check_name TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('error', 'warning', 'manual_review', 'info')),
    status TEXT NOT NULL CHECK (status IN ('passed', 'failed', 'needs_review')),
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS calculated_metrics (
    metric_record_id INTEGER PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(company_id),
    financial_year TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    statement_basis TEXT NOT NULL CHECK (statement_basis IN ('standalone', 'consolidated')),
    metric_id TEXT NOT NULL,
    value NUMERIC,
    unit TEXT NOT NULL,
    formula_version TEXT NOT NULL,
    input_observation_ids TEXT NOT NULL,
    calculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (company_id, financial_year, statement_basis, metric_id)
);

CREATE INDEX IF NOT EXISTS idx_observations_company_period
    ON financial_observations (company_id, financial_year, statement_basis);
CREATE INDEX IF NOT EXISTS idx_observations_line_item
    ON financial_observations (line_item_id, financial_year);
CREATE INDEX IF NOT EXISTS idx_metrics_period
    ON calculated_metrics (financial_year, statement_basis, metric_id);
