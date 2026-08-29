"""Ordered Pattern Finder SQLite schema migrations."""

from __future__ import annotations


MIGRATION_1_STATEMENTS = (
    """CREATE TABLE schema_migrations (
        version INTEGER PRIMARY KEY,
        migration_id TEXT NOT NULL UNIQUE,
        checksum TEXT NOT NULL,
        applied_at_utc TEXT NOT NULL
    )""",
    """CREATE TABLE app_runs (
        run_id TEXT PRIMARY KEY, started_at_utc TEXT NOT NULL,
        stopped_at_utc TEXT, status TEXT NOT NULL, pid INTEGER NOT NULL,
        port INTEGER NOT NULL, app_version TEXT, git_commit TEXT, error_summary TEXT
    )""",
    """CREATE TABLE audit_events (
        event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL, payload_json TEXT NOT NULL, created_at_utc TEXT NOT NULL
    )""",
    """CREATE TABLE system_settings (
        setting_key TEXT PRIMARY KEY, setting_value_json TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL
    )""",
    """CREATE TABLE profiles (
        profile_id TEXT PRIMARY KEY, profile_kind TEXT NOT NULL, display_name TEXT NOT NULL,
        created_at_utc TEXT NOT NULL
    )""",
    """CREATE TABLE profile_versions (
        profile_version_id TEXT PRIMARY KEY,
        profile_id TEXT NOT NULL REFERENCES profiles(profile_id),
        version INTEGER NOT NULL, status TEXT NOT NULL,
        parent_profile_version_id TEXT REFERENCES profile_versions(profile_version_id),
        created_at_utc TEXT NOT NULL, published_at_utc TEXT,
        change_note TEXT NOT NULL, schema_version TEXT NOT NULL,
        profile_payload_json TEXT NOT NULL, content_sha256 TEXT NOT NULL,
        filter_content_sha256 TEXT NOT NULL,
        UNIQUE(profile_id, version)
    )""",
    """CREATE TABLE profile_rules (
        profile_version_id TEXT PRIMARY KEY REFERENCES profile_versions(profile_version_id),
        rules_json TEXT NOT NULL
    )""",
    """CREATE TABLE universe_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        profile_version_id TEXT REFERENCES profile_versions(profile_version_id),
        draft_id TEXT, snapshot_kind TEXT NOT NULL, completeness TEXT NOT NULL,
        schema_version TEXT NOT NULL, as_of_date TEXT NOT NULL, created_at_utc TEXT NOT NULL,
        total_count INTEGER NOT NULL, member_count INTEGER NOT NULL,
        fail_count INTEGER NOT NULL, quarantine_count INTEGER NOT NULL,
        mapping_hash TEXT, prerequisites_hash TEXT NOT NULL, members_hash TEXT NOT NULL,
        content_hash TEXT NOT NULL, record_hash TEXT NOT NULL UNIQUE,
        provenance_json TEXT NOT NULL, payload_json TEXT NOT NULL
    )""",
    """CREATE TABLE snapshot_securities (
        snapshot_id TEXT NOT NULL REFERENCES universe_snapshots(snapshot_id),
        stock_id TEXT NOT NULL, futu_code TEXT NOT NULL, symbol TEXT NOT NULL,
        name TEXT NOT NULL, exchange TEXT, security_type TEXT, industry_raw TEXT,
        price TEXT, market_cap TEXT, adv20 TEXT, listing_days INTEGER,
        final_status TEXT NOT NULL, first_exit_stage TEXT,
        row_json TEXT NOT NULL,
        PRIMARY KEY(snapshot_id, stock_id, futu_code)
    )""",
    """CREATE TABLE snapshot_security_decisions (
        snapshot_id TEXT NOT NULL, stock_id TEXT NOT NULL, futu_code TEXT NOT NULL,
        stage TEXT NOT NULL, stage_order INTEGER NOT NULL, stage_id TEXT NOT NULL,
        decision TEXT NOT NULL, reason_code TEXT NOT NULL,
        observed_value_json TEXT, threshold_json TEXT, evidence_json TEXT NOT NULL,
        PRIMARY KEY(snapshot_id, stock_id, futu_code, stage),
        FOREIGN KEY(snapshot_id, stock_id, futu_code)
          REFERENCES snapshot_securities(snapshot_id, stock_id, futu_code)
    )""",
    """CREATE TABLE scan_batches (
        scan_batch_id TEXT PRIMARY KEY,
        snapshot_id TEXT NOT NULL REFERENCES universe_snapshots(snapshot_id),
        pattern_type TEXT NOT NULL, pattern_version TEXT NOT NULL,
        started_at_utc TEXT NOT NULL, completed_at_utc TEXT, status TEXT NOT NULL,
        input_hash TEXT NOT NULL, config_hash TEXT NOT NULL, result_hash TEXT
    )""",
    """CREATE TABLE pattern_candidates (
        candidate_id TEXT PRIMARY KEY,
        scan_batch_id TEXT NOT NULL REFERENCES scan_batches(scan_batch_id),
        stock_id TEXT NOT NULL, pattern_type TEXT NOT NULL, pattern_version TEXT NOT NULL,
        signal_date TEXT NOT NULL, computer_decision TEXT NOT NULL,
        computer_score TEXT, features_json TEXT NOT NULL, reason_codes_json TEXT NOT NULL,
        created_at_utc TEXT NOT NULL,
        UNIQUE(scan_batch_id, stock_id, pattern_type, signal_date)
    )""",
    """CREATE TABLE manual_reviews (
        review_id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL REFERENCES pattern_candidates(candidate_id),
        human_label TEXT NOT NULL CHECK(human_label IN ('LIKE','BORDERLINE','DISLIKE')),
        confidence TEXT, reason_codes_json TEXT NOT NULL, notes TEXT NOT NULL,
        reviewed_at_utc TEXT NOT NULL
    )""",
    """CREATE TABLE backtest_runs (
        backtest_run_id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL REFERENCES pattern_candidates(candidate_id),
        methodology_version TEXT NOT NULL, entry_date TEXT NOT NULL,
        entry_price TEXT NOT NULL, benchmark TEXT NOT NULL, created_at_utc TEXT NOT NULL
    )""",
    """CREATE TABLE backtest_horizons (
        backtest_run_id TEXT NOT NULL REFERENCES backtest_runs(backtest_run_id),
        horizon TEXT NOT NULL, return_pct TEXT, benchmark_return_pct TEXT,
        excess_return_pct TEXT, mfe TEXT, mae TEXT, max_drawdown TEXT,
        PRIMARY KEY(backtest_run_id, horizon)
    )""",
    """CREATE TRIGGER profile_versions_immutable_update BEFORE UPDATE ON profile_versions
        WHEN OLD.status='PUBLISHED' BEGIN SELECT RAISE(ABORT, 'published profile version is immutable'); END""",
    """CREATE TRIGGER profile_versions_immutable_delete BEFORE DELETE ON profile_versions
        WHEN OLD.status='PUBLISHED' BEGIN SELECT RAISE(ABORT, 'published profile version is immutable'); END""",
    """CREATE TRIGGER profile_rules_immutable_update BEFORE UPDATE ON profile_rules
        WHEN EXISTS (SELECT 1 FROM profile_versions pv WHERE pv.profile_version_id=OLD.profile_version_id AND pv.status='PUBLISHED')
        BEGIN SELECT RAISE(ABORT, 'published profile rules are immutable'); END""",
    """CREATE TRIGGER profile_rules_immutable_delete BEFORE DELETE ON profile_rules
        WHEN EXISTS (SELECT 1 FROM profile_versions pv WHERE pv.profile_version_id=OLD.profile_version_id AND pv.status='PUBLISHED')
        BEGIN SELECT RAISE(ABORT, 'published profile rules are immutable'); END""",
    """CREATE TRIGGER universe_snapshots_immutable_update BEFORE UPDATE ON universe_snapshots
        BEGIN SELECT RAISE(ABORT, 'universe snapshot is immutable'); END""",
    """CREATE TRIGGER universe_snapshots_immutable_delete BEFORE DELETE ON universe_snapshots
        BEGIN SELECT RAISE(ABORT, 'universe snapshot is immutable'); END""",
    """CREATE TRIGGER snapshot_securities_immutable_update BEFORE UPDATE ON snapshot_securities
        BEGIN SELECT RAISE(ABORT, 'snapshot security is immutable'); END""",
    """CREATE TRIGGER snapshot_securities_immutable_delete BEFORE DELETE ON snapshot_securities
        BEGIN SELECT RAISE(ABORT, 'snapshot security is immutable'); END""",
    """CREATE TRIGGER snapshot_decisions_immutable_update BEFORE UPDATE ON snapshot_security_decisions
        BEGIN SELECT RAISE(ABORT, 'snapshot decision is immutable'); END""",
    """CREATE TRIGGER snapshot_decisions_immutable_delete BEFORE DELETE ON snapshot_security_decisions
        BEGIN SELECT RAISE(ABORT, 'snapshot decision is immutable'); END""",
    "CREATE INDEX idx_snapshots_created ON universe_snapshots(created_at_utc DESC)",
    "CREATE INDEX idx_scans_completed ON scan_batches(completed_at_utc DESC)",
    "CREATE INDEX idx_candidates_scan ON pattern_candidates(scan_batch_id)",
    "CREATE INDEX idx_reviews_candidate ON manual_reviews(candidate_id)",
)


MIGRATION_2_STATEMENTS = (
    """CREATE TABLE scan_batch_manifests (
        scan_batch_id TEXT PRIMARY KEY REFERENCES scan_batches(scan_batch_id),
        scan_as_of_date TEXT NOT NULL,
        ordered_input_count INTEGER NOT NULL CHECK(ordered_input_count >= 0),
        quality_pass_count INTEGER NOT NULL CHECK(quality_pass_count >= 0),
        quality_fail_count INTEGER NOT NULL CHECK(quality_fail_count >= 0),
        yes_count INTEGER NOT NULL CHECK(yes_count >= 0),
        no_count INTEGER NOT NULL CHECK(no_count >= 0),
        code_commit TEXT NOT NULL,
        ordered_input_hash TEXT NOT NULL,
        provenance_json TEXT NOT NULL,
        CHECK(ordered_input_count = quality_pass_count + quality_fail_count),
        CHECK(quality_pass_count = yes_count + no_count)
    )""",
    """CREATE TABLE review_queue_actions (
        action_id TEXT PRIMARY KEY,
        source_kind TEXT NOT NULL CHECK(source_kind IN ('PROVISIONAL_CACHE','SCAN_BATCH')),
        source_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        pattern_type TEXT NOT NULL,
        action_type TEXT NOT NULL CHECK(action_type IN ('SKIP','SNOOZE','RESTORE')),
        created_at_utc TEXT NOT NULL
    )""",
    """CREATE TABLE review_cursors (
        source_kind TEXT NOT NULL CHECK(source_kind IN ('PROVISIONAL_CACHE','SCAN_BATCH')),
        source_id TEXT NOT NULL,
        pattern_type TEXT NOT NULL,
        item_id TEXT NOT NULL,
        filters_json TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL,
        PRIMARY KEY(source_kind, source_id, pattern_type)
    )""",
    """CREATE TRIGGER scan_batches_immutable_update BEFORE UPDATE ON scan_batches
        WHEN OLD.status='COMPLETED'
        BEGIN SELECT RAISE(ABORT, 'completed scan batch is immutable'); END""",
    """CREATE TRIGGER scan_batches_immutable_delete BEFORE DELETE ON scan_batches
        WHEN OLD.status='COMPLETED'
        BEGIN SELECT RAISE(ABORT, 'completed scan batch is immutable'); END""",
    """CREATE TRIGGER scan_batch_manifests_immutable_update BEFORE UPDATE ON scan_batch_manifests
        BEGIN SELECT RAISE(ABORT, 'scan batch manifest is immutable'); END""",
    """CREATE TRIGGER scan_batch_manifests_immutable_delete BEFORE DELETE ON scan_batch_manifests
        BEGIN SELECT RAISE(ABORT, 'scan batch manifest is immutable'); END""",
    """CREATE TRIGGER pattern_candidates_immutable_update BEFORE UPDATE ON pattern_candidates
        WHEN EXISTS (SELECT 1 FROM scan_batches sb WHERE sb.scan_batch_id=OLD.scan_batch_id AND sb.status='COMPLETED')
        BEGIN SELECT RAISE(ABORT, 'completed pattern candidate is immutable'); END""",
    """CREATE TRIGGER pattern_candidates_immutable_delete BEFORE DELETE ON pattern_candidates
        WHEN EXISTS (SELECT 1 FROM scan_batches sb WHERE sb.scan_batch_id=OLD.scan_batch_id AND sb.status='COMPLETED')
        BEGIN SELECT RAISE(ABORT, 'completed pattern candidate is immutable'); END""",
    "CREATE INDEX idx_review_actions_scope_time ON review_queue_actions(source_kind, source_id, pattern_type, created_at_utc)",
    "CREATE INDEX idx_review_cursors_scope ON review_cursors(source_kind, source_id, pattern_type)",
)
