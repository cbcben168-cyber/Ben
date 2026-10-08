from pathlib import Path
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
    assert database.dashboard_snapshot()["summary"]["waiting_export"] == 0


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


def test_csv_parser_handles_quoted_json_with_commas(runlog_fixture):
    result = parse_runlog(runlog_fixture, allow_fixtures=True)
    assert result.import_status == "VALIDATED"
    assert result.rows_marked == 10
    assert result.parsed_rows == 10
    assert result.success_rate == 1.0
