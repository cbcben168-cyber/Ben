CREATE TABLE IF NOT EXISTS strategy_versions (
    strategy_version TEXT PRIMARY KEY,
    created_at_utc TIMESTAMPTZ NOT NULL,
    config_json JSON NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS universe_versions (
    universe_version TEXT PRIMARY KEY,
    created_at_utc TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    member_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS universe_members (
    universe_member_id TEXT PRIMARY KEY,
    universe_version TEXT NOT NULL,
    ticker TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    added_at_utc TIMESTAMPTZ NOT NULL,
    UNIQUE (universe_version, ticker)
);

CREATE TABLE IF NOT EXISTS option_liquidity_daily (
    liquidity_id TEXT PRIMARY KEY,
    supersedes_id TEXT REFERENCES option_liquidity_daily(liquidity_id),
    logical_date DATE NOT NULL,
    ticker TEXT NOT NULL,
    total_option_volume BIGINT NOT NULL,
    observed_at_utc TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS option_snapshots (
    option_snapshot_id TEXT PRIMARY KEY,
    supersedes_id TEXT REFERENCES option_snapshots(option_snapshot_id),
    scan_run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    expiry DATE NOT NULL,
    option_type TEXT NOT NULL,
    strike DOUBLE NOT NULL,
    bid DOUBLE NOT NULL,
    ask DOUBLE NOT NULL,
    iv DOUBLE NOT NULL,
    delta DOUBLE NOT NULL,
    open_interest BIGINT NOT NULL,
    volume BIGINT NOT NULL,
    contract_symbol TEXT,
    captured_at_utc TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS earnings_events (
    earnings_event_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    event_date DATE,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    raw_value TEXT,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    UNIQUE (ticker, event_date, source, fetched_at_utc)
);

CREATE TABLE IF NOT EXISTS scan_runs (
    scan_run_id TEXT PRIMARY KEY,
    strategy_version TEXT NOT NULL,
    universe_version TEXT NOT NULL,
    logical_session_date DATE NOT NULL,
    status TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    claimed_at_utc TIMESTAMPTZ NOT NULL,
    lease_expires_at_utc TIMESTAMPTZ,
    completed_at_utc TIMESTAMPTZ,
    created_at_utc TIMESTAMPTZ NOT NULL,
    UNIQUE (strategy_version, logical_session_date)
);

CREATE TABLE IF NOT EXISTS scan_results (
    scan_result_id TEXT PRIMARY KEY,
    scan_run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    status TEXT NOT NULL,
    failed_fields_json JSON NOT NULL,
    details_json JSON NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL,
    UNIQUE (scan_run_id, ticker)
);

CREATE TABLE IF NOT EXISTS signals (
    signal_id TEXT PRIMARY KEY,
    scan_run_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    scan_date DATE NOT NULL,
    ticker TEXT NOT NULL,
    t1_expiry DATE NOT NULL,
    t2_expiry DATE NOT NULL,
    status TEXT NOT NULL,
    sigma_1 DOUBLE,
    sigma_2 DOUBLE,
    forward_variance DOUBLE,
    sigma_forward DOUBLE,
    ff DOUBLE,
    relative_spread DOUBLE,
    created_at_utc TIMESTAMPTZ NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL,
    UNIQUE (strategy_version, scan_date, ticker, t1_expiry, t2_expiry)
);

CREATE TABLE IF NOT EXISTS positions (
    position_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    status TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    opened_price DOUBLE NOT NULL,
    opened_at_utc TIMESTAMPTZ NOT NULL,
    closed_price DOUBLE,
    closed_at_utc TIMESTAMPTZ,
    notes TEXT,
    created_at_utc TIMESTAMPTZ NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS position_legs (
    position_leg_id TEXT PRIMARY KEY,
    position_id TEXT NOT NULL,
    contract_symbol TEXT NOT NULL,
    option_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    expiry DATE NOT NULL,
    strike DOUBLE NOT NULL,
    quantity INTEGER NOT NULL,
    filled_price DOUBLE NOT NULL,
    filled_at_utc TIMESTAMPTZ NOT NULL,
    UNIQUE (position_id, contract_symbol, direction)
);

CREATE TABLE IF NOT EXISTS notifications (
    notification_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json JSON NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at_utc TIMESTAMPTZ,
    provider_message_id TEXT,
    last_error TEXT,
    created_at_utc TIMESTAMPTZ NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_outbox (
    sync_outbox_id TEXT PRIMARY KEY,
    target TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    payload_json JSON NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at_utc TIMESTAMPTZ,
    last_error TEXT,
    created_at_utc TIMESTAMPTZ NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL,
    UNIQUE (target, record_id, updated_at_utc)
);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    details_json JSON NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL
);
