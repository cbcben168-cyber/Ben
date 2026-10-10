from pathlib import Path
import hashlib
import shutil

import pytest

from quant_workflow.factor_research.progress_dashboard.db import Database
from quant_workflow.factor_research.progress_dashboard.ingest import FolderWatcher, Importer, parse_runlog


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path / "factor.sqlite3")
    db.initialize()
    return db


def test_seed_is_truthful_and_contains_no_fabricated_results(database):
    snapshot = database.dashboard_snapshot()
    factor = snapshot["factors"][0]
    assert factor["factor_id"] == "SPY_F001_CLOSE_GT_EMA20"
    assert factor["development_stage"] == "SPECIFIED"
    assert factor["valid_run_count"] == 0
    assert factor["edge_status"] == "NOT_TESTED"
    comparison = snapshot["comparison"]
    assert comparison["rows"][0]["pass_mean_return"] is None
    assert comparison["rows"][0]["rank"] is None
    assert "MISSING_ELIGIBLE_RUN" in comparison["reason_codes"]
    assert snapshot["summary"]["waiting_export"] == 1
    statuses = {gate["gate_id"]: gate["status"] for gate in snapshot["gates"]}
    assert statuses["GATE5C_VOLUME_NATIVE_VS_1M"] == "FAIL"
    assert statuses["QQQ_PLATFORM_FACTOR_RUN"] == "NOT_TESTED"


def test_fixture_is_blocked_from_production_database(database, runlog_fixture):
    result = Importer(database).import_file(runlog_fixture)
    assert result["status"] == "INVALID"
    assert database.dashboard_snapshot()["runs"] == []


def test_valid_fixture_imports_stats_and_duplicate_is_idempotent(database, runlog_fixture):
    importer = Importer(database, allow_fixtures=True)
    first = importer.import_file(runlog_fixture)
    second = importer.import_file(runlog_fixture)
    assert first["status"] == "VALIDATED"
    assert second["status"] == "DUPLICATE"

    detail = database.factor_detail("SPY_F001_CLOSE_GT_EMA20")
    assert detail is not None
    assert len(detail["runs"]) == 1
    run = detail["runs"][0]
    assert run["signal_count"] == 2
    assert run["label_count"] == 6
    assert run["completeness"] == 1.0
    pass_h15 = next(
        row for row in run["statistics"]
        if row["horizon_minutes"] == 15 and row["cohort"] == "PASS"
    )
    assert pass_h15["n"] == 1
    assert pass_h15["mean_return"] == pytest.approx(0.01)
    assert pass_h15["positive_rate"] == pytest.approx(1.0)
    snapshot = database.dashboard_snapshot()
    row = snapshot["comparison"]["rows"][0]
    assert row["pass_mean_return"] == pytest.approx(0.01)
    assert row["fail_mean_return"] == pytest.approx(0.01)
    assert row["pass_fail_diff_bps"] == pytest.approx(0.0)
    assert row["coverage_trading_days"] == 1
    assert row["stable_eligible_days"] == 1
    assert row["stable_better_days"] == 0
    assert row["daily_stability"] == pytest.approx(0.0)
    assert row["rank"] is None
    assert snapshot["summary"]["waiting_export"] == 0

    detail = database.factor_detail("SPY_F001_CLOSE_GT_EMA20", horizon_minutes=15)
    assert detail is not None
    selected = detail["runs"][0]["selected_window"]
    assert selected["monthly"][0]["month"] == "2026-10"
    assert selected["monthly"][0]["pass_fail_diff_bps"] == pytest.approx(0.0)


def test_comparison_blocks_mismatched_ranges_then_ranks_matching_scope(
    database, runlog_fixture
):
    Importer(database, allow_fixtures=True).import_file(runlog_fixture)
    now = "2026-10-10T00:00:00Z"
    with database.connect() as connection:
        connection.execute(
            "UPDATE factors SET data_gate='PASS' WHERE factor_id='SPY_F001_CLOSE_GT_EMA20'"
        )
        connection.execute(
            """
            INSERT INTO factors (
                factor_id, formula, symbol, bar_size, horizons_json,
                development_stage, data_gate, edge_status, code_present,
                blocking_reason, next_action, created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "SPY_F002_TEST",
                "test formula",
                "US.SPY",
                "5m",
                "[15, 30, 60]",
                "PLATFORM_VALIDATED",
                "PASS",
                "INSUFFICIENT_EVIDENCE",
                1,
                "测试比较范围",
                "继续验证",
                now,
                now,
            ),
        )
        original_version = connection.execute(
            """
            SELECT v.* FROM factor_versions v
            JOIN research_runs r ON r.version_id=v.version_id
            WHERE v.factor_id='SPY_F001_CLOSE_GT_EMA20'
            LIMIT 1
            """
        ).fetchone()
        cursor = connection.execute(
            """
            INSERT INTO factor_versions (
                factor_id, strategy_version, strategy_hash, parameter_version, active, created_at_utc
            ) VALUES (?, ?, ?, ?, 1, ?)
            """,
            (
                "SPY_F002_TEST",
                "SPY_FACTOR_RESEARCH_V1.1",
                original_version["strategy_hash"],
                "F002-P1",
                now,
            ),
        )
        version_id = cursor.lastrowid
        original_run = connection.execute(
            "SELECT * FROM research_runs LIMIT 1"
        ).fetchone()
        clone_id = "f002-clone"
        connection.execute(
            """
            INSERT INTO research_runs (
                run_instance_id, declared_run_id, version_id, file_sha256,
                run_status, research_verdict, version_binding_status,
                study_partition, settings_start_et, settings_end_et,
                actual_start_et, actual_end_et, timezone, session, symbol,
                timeframe, select_value, signal_count, label_count,
                completeness, coverage_key, imported_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clone_id,
                "FIXTURE_F002_RUN_001",
                version_id,
                original_run["file_sha256"],
                original_run["run_status"],
                original_run["research_verdict"],
                original_run["version_binding_status"],
                original_run["study_partition"],
                "2026-10-05",
                original_run["settings_end_et"],
                original_run["actual_start_et"],
                original_run["actual_end_et"],
                original_run["timezone"],
                original_run["session"],
                original_run["symbol"],
                original_run["timeframe"],
                original_run["select_value"],
                original_run["signal_count"],
                original_run["label_count"],
                original_run["completeness"],
                "f002-coverage",
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO signals
            SELECT ?, signal_id, signal_time_et, signal_time_utc,
                   signal_close, factor_value, factor_numeric
            FROM signals WHERE run_instance_id=?
            """,
            (clone_id, original_run["run_instance_id"]),
        )
        connection.execute(
            """
            INSERT INTO labels
            SELECT ?, signal_id, horizon_bars, horizon_minutes,
                   target_time_et, target_time_utc, target_close, forward_return
            FROM labels WHERE run_instance_id=?
            """,
            (clone_id, original_run["run_instance_id"]),
        )
        connection.execute(
            """
            INSERT INTO run_statistics
            SELECT ?, horizon_minutes, cohort, n, mean_return, median_return,
                   positive_rate, baseline_mean, edge_bps
            FROM run_statistics WHERE run_instance_id=?
            """,
            (clone_id, original_run["run_instance_id"]),
        )

    mismatch = database.dashboard_snapshot(planned_factor_count=2)["comparison"]
    assert mismatch["ranking_ready"] is False
    assert "COMPARISON_SCOPE_MISMATCH" in mismatch["reason_codes"]
    assert all(row["rank"] is None for row in mismatch["rows"])

    with database.connect() as connection:
        connection.execute(
            "UPDATE research_runs SET settings_start_et='2026-10-06' WHERE run_instance_id=?",
            (clone_id,),
        )
    ready = database.dashboard_snapshot(planned_factor_count=2)["comparison"]
    assert ready["ranking_ready"] is True
    assert {row["rank"] for row in ready["rows"]} == {1, 2}


def test_same_path_new_hash_creates_new_audit_and_repeated_coverage_warning(database, tmp_path, runlog_fixture):
    target = tmp_path / "RunLog_changed.csv"
    shutil.copy2(runlog_fixture, target)
    importer = Importer(database, allow_fixtures=True)
    assert importer.import_file(target)["status"] == "VALIDATED"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert importer.import_file(target)["status"] == "VALIDATED"
    snapshot = database.dashboard_snapshot()
    assert len(snapshot["runs"]) == 2
    codes = {item["issue_code"] for item in snapshot["issues"]}
    assert "SOURCE_PATH_CONTENT_CHANGED" in codes
    assert "REPEATED_COVERAGE" in codes


def test_non_factor_and_unsupported_marker_are_rejected_without_runs(database, tmp_path):
    old_probe = tmp_path / "RunLog_old.csv"
    old_probe.write_text("time,message\n1,FUTU_DATA_PROBE {}\n", encoding="utf-8")
    unsupported = tmp_path / "RunLog_new.csv"
    unsupported.write_text('time,message\n1,"FUTU_FACTOR_V9|{}"\n', encoding="utf-8")
    importer = Importer(database)
    assert importer.import_file(old_probe)["status"] == "IGNORED"
    assert importer.import_file(unsupported)["status"] == "INVALID"
    assert database.dashboard_snapshot()["runs"] == []


def test_missing_run_end_is_incomplete(database, tmp_path, runlog_fixture):
    target = tmp_path / "RunLog_incomplete.csv"
    lines = runlog_fixture.read_text(encoding="utf-8").splitlines()
    target.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    result = Importer(database, allow_fixtures=True).import_file(target)
    assert result["status"] == "INCOMPLETE"
    assert database.dashboard_snapshot()["runs"][0]["run_status"] == "INCOMPLETE"


def test_unapproved_multi_factor_batch_is_rejected_without_partial_import(
    database, tmp_path, runlog_fixture
):
    lines = runlog_fixture.read_text(encoding="utf-8").splitlines()
    second_start = lines[1].replace(
        "SPY_F001_CLOSE_GT_EMA20", "SPY_F002_TEST"
    ).replace("FIXTURE_F001_RUN_001", "FIXTURE_F002_RUN_001")
    batch = tmp_path / "RunLog_unapproved_batch.csv"
    batch.write_text("\n".join([lines[0], lines[1], second_start, *lines[2:]]) + "\n", encoding="utf-8")

    result = Importer(database, allow_fixtures=True).import_file(batch)

    assert result["status"] == "PARSE_FAILED"
    assert result["error"] == "RUN_START_COUNT:2"
    assert database.dashboard_snapshot()["runs"] == []


def test_watcher_requires_stability_and_restart_backfills(database, tmp_path, runlog_fixture):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    target = inbox / "RunLog_fixture.csv"
    shutil.copy2(runlog_fixture, target)
    watcher = FolderWatcher(Importer(database, allow_fixtures=True), [inbox], stable_checks=2)
    assert watcher.scan_once() == []
    assert watcher.scan_once()[0]["status"] == "VALIDATED"

    restarted = Database(database.path)
    restarted.initialize()
    snapshot = restarted.dashboard_snapshot()
    assert len(snapshot["runs"]) == 1
    assert snapshot["runs"][0]["run_status"] == "VALIDATED"
    assert snapshot["summary"]["waiting_export"] == 0


def test_csv_parser_handles_quoted_json_with_commas(runlog_fixture):
    result = parse_runlog(runlog_fixture, allow_fixtures=True)
    assert result.import_status == "VALIDATED"
    assert result.rows_marked == 10
    assert result.parsed_rows == 10
    assert result.success_rate == 1.0


def test_legacy_functional_run_imports_without_edge_claim_and_is_idempotent(
    database, legacy_runlog_fixture
):
    original_hash = hashlib.sha256(legacy_runlog_fixture.read_bytes()).hexdigest()
    importer = Importer(database)
    first = importer.import_file(legacy_runlog_fixture)
    second = importer.import_file(legacy_runlog_fixture)

    assert first["status"] == "VALIDATED"
    assert second["status"] == "DUPLICATE"
    assert hashlib.sha256(legacy_runlog_fixture.read_bytes()).hexdigest() == original_hash

    snapshot = database.dashboard_snapshot()
    assert len(snapshot["runs"]) == 1
    run = snapshot["runs"][0]
    assert run["symbol"] == "US.SPY"
    assert run["timeframe"] == "5m"
    assert run["signal_count"] == 455
    assert run["label_count"] == 1365
    assert run["research_verdict"] == "FUNCTIONAL_VALIDATION_PASS"
    assert run["version_binding_status"] == "LEGACY_MARKER_CONTRACT_ONLY"
    factor = snapshot["factors"][0]
    assert factor["development_stage"] == "PLATFORM_VALIDATED"
    assert factor["edge_status"] == "INSUFFICIENT_EVIDENCE"
    assert factor["latest_verdict"] == "FUNCTIONAL_VALIDATION_PASS"
    assert "TRAIN" in factor["next_action"]


def test_legacy_contract_mismatch_is_rejected(database, legacy_runlog_fixture):
    altered = legacy_runlog_fixture.read_text(encoding="utf-8").replace(
        "volume_enabled=False", "volume_enabled=True", 1
    )
    legacy_runlog_fixture.write_text(altered, encoding="utf-8")
    result = Importer(database).import_file(legacy_runlog_fixture)
    assert result["status"] == "INVALID"
    assert database.dashboard_snapshot()["runs"][0]["run_status"] == "INVALID"
