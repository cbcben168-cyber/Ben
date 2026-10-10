PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS factors (
    factor_id TEXT PRIMARY KEY,
    formula TEXT NOT NULL,
    symbol TEXT NOT NULL,
    bar_size TEXT NOT NULL,
    horizons_json TEXT NOT NULL,
    development_stage TEXT NOT NULL,
    data_gate TEXT NOT NULL,
    edge_status TEXT NOT NULL,
    code_present INTEGER NOT NULL DEFAULT 0 CHECK (code_present IN (0, 1)),
    blocking_reason TEXT,
    next_action TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS factor_versions (
    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    factor_id TEXT NOT NULL REFERENCES factors(factor_id),
    strategy_version TEXT NOT NULL,
    strategy_hash TEXT NOT NULL,
    parameter_version TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at_utc TEXT NOT NULL,
    UNIQUE (factor_id, strategy_version, strategy_hash, parameter_version)
);

CREATE TABLE IF NOT EXISTS data_gate_evidence (
    gate_id TEXT PRIMARY KEY,
    factor_id TEXT REFERENCES factors(factor_id),
    symbol TEXT NOT NULL,
    bar_size TEXT NOT NULL,
    dimension TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence_version TEXT NOT NULL,
    scope_note TEXT NOT NULL,
    source_path TEXT,
    source_sha256 TEXT,
    observed_at_utc TEXT,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_files (
    file_sha256 TEXT PRIMARY KEY,
    canonical_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL,
    encoding TEXT,
    marker_version TEXT,
    classification TEXT NOT NULL,
    import_status TEXT NOT NULL,
    rows_total INTEGER NOT NULL DEFAULT 0,
    rows_marked INTEGER NOT NULL DEFAULT 0,
    parse_success_rate REAL,
    error_text TEXT,
    system_log_start_local TEXT,
    system_log_end_local TEXT
);

CREATE TABLE IF NOT EXISTS file_observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    normalized_path TEXT NOT NULL,
    file_sha256 TEXT NOT NULL REFERENCES source_files(file_sha256),
    size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL,
    UNIQUE (normalized_path, file_sha256, mtime_ns)
);

CREATE TABLE IF NOT EXISTS research_runs (
    run_instance_id TEXT PRIMARY KEY,
    declared_run_id TEXT NOT NULL,
    version_id INTEGER NOT NULL REFERENCES factor_versions(version_id),
    file_sha256 TEXT NOT NULL REFERENCES source_files(file_sha256),
    run_status TEXT NOT NULL,
    research_verdict TEXT NOT NULL DEFAULT 'NOT_ASSESSED',
    version_binding_status TEXT NOT NULL DEFAULT 'EMBEDDED_HASH',
    study_partition TEXT NOT NULL,
    settings_start_et TEXT,
    settings_end_et TEXT,
    actual_start_et TEXT,
    actual_end_et TEXT,
    timezone TEXT NOT NULL,
    session TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    select_value INTEGER NOT NULL,
    signal_count INTEGER NOT NULL DEFAULT 0,
    label_count INTEGER NOT NULL DEFAULT 0,
    completeness REAL NOT NULL DEFAULT 0,
    coverage_key TEXT NOT NULL,
    imported_at_utc TEXT NOT NULL,
    UNIQUE (file_sha256, declared_run_id)
);

CREATE TABLE IF NOT EXISTS signals (
    run_instance_id TEXT NOT NULL REFERENCES research_runs(run_instance_id) ON DELETE CASCADE,
    signal_id TEXT NOT NULL,
    signal_time_et TEXT NOT NULL,
    signal_time_utc TEXT NOT NULL,
    signal_close REAL NOT NULL,
    factor_value TEXT NOT NULL,
    factor_numeric REAL,
    PRIMARY KEY (run_instance_id, signal_id)
);

CREATE TABLE IF NOT EXISTS labels (
    run_instance_id TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    horizon_bars INTEGER NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    target_time_et TEXT NOT NULL,
    target_time_utc TEXT NOT NULL,
    target_close REAL NOT NULL,
    forward_return REAL NOT NULL,
    PRIMARY KEY (run_instance_id, signal_id, horizon_bars),
    FOREIGN KEY (run_instance_id, signal_id)
        REFERENCES signals(run_instance_id, signal_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS run_statistics (
    run_instance_id TEXT NOT NULL REFERENCES research_runs(run_instance_id) ON DELETE CASCADE,
    horizon_minutes INTEGER NOT NULL,
    cohort TEXT NOT NULL,
    n INTEGER NOT NULL,
    mean_return REAL,
    median_return REAL,
    positive_rate REAL,
    baseline_mean REAL,
    edge_bps REAL,
    PRIMARY KEY (run_instance_id, horizon_minutes, cohort)
);

CREATE TABLE IF NOT EXISTS run_analyses (
    run_instance_id TEXT NOT NULL REFERENCES research_runs(run_instance_id) ON DELETE CASCADE,
    horizon_minutes INTEGER NOT NULL,
    analysis_version TEXT NOT NULL,
    analysis_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY (run_instance_id, horizon_minutes, analysis_version)
);

CREATE TABLE IF NOT EXISTS run_audits (
    run_instance_id TEXT NOT NULL REFERENCES research_runs(run_instance_id) ON DELETE CASCADE,
    audit_type TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY (run_instance_id, audit_type)
);

CREATE TABLE IF NOT EXISTS issues (
    issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    issue_code TEXT NOT NULL,
    factor_id TEXT REFERENCES factors(factor_id),
    run_instance_id TEXT REFERENCES research_runs(run_instance_id),
    file_sha256 TEXT REFERENCES source_files(file_sha256),
    message TEXT NOT NULL,
    next_action TEXT,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL,
    resolved_at_utc TEXT
);

CREATE TABLE IF NOT EXISTS app_state (
    state_key TEXT PRIMARY KEY,
    state_value TEXT,
    updated_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_factor_version ON research_runs(version_id, imported_at_utc DESC);
CREATE INDEX IF NOT EXISTS idx_runs_coverage ON research_runs(coverage_key);
CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status, last_seen_utc DESC);
CREATE INDEX IF NOT EXISTS idx_observations_path ON file_observations(normalized_path, last_seen_utc DESC);
CREATE INDEX IF NOT EXISTS idx_analyses_run ON run_analyses(run_instance_id, horizon_minutes);
