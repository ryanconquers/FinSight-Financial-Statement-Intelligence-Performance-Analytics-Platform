CREATE TABLE IF NOT EXISTS forecasts (
    forecast_id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(company_id),
    statement_basis TEXT NOT NULL CHECK (statement_basis IN ('standalone', 'consolidated')),
    baseline_year TEXT NOT NULL,
    horizon INTEGER NOT NULL CHECK (horizon BETWEEN 1 AND 10),
    methodology_version TEXT NOT NULL,
    assumptions_json TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    result_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS forecast_revisions (
    forecast_id TEXT NOT NULL REFERENCES forecasts(forecast_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    assumptions_json TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    result_json TEXT NOT NULL,
    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (forecast_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_forecasts_company ON forecasts(company_id, created_at DESC);
