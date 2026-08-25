from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from streamlit.testing.v1 import AppTest

from tv_quant.pattern_finder.application.system_dashboard import (
    build_dashboard_state,
    build_diagnostics_state,
    load_project_progress,
)
from tv_quant.pattern_finder.persistence.bootstrap import initialize_local_foundation
from tv_quant.pattern_finder.persistence.repositories import ProfileRepository, SnapshotRepository
from tv_quant.pattern_finder.runtime.config import RuntimeConfig


ROOT = Path(__file__).resolve().parents[2]


def _snapshot(tmp_path: Path):
    module_name = "m3cd_snapshot_fixture"
    module = sys.modules.get(module_name)
    if module is None:
        path = ROOT / "tests/pattern_finder/universe_foundation/test_ui_read_model.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    _, snapshot = module._persist_complete_snapshot(tmp_path / "legacy")
    return snapshot


def test_project_progress_computes_percent_from_tasks() -> None:
    progress = load_project_progress(ROOT / "config/project_progress.yaml")
    by_id = {item.milestone_id: item for item in progress.milestones}

    assert by_id["M3C-B"].status == "IN PROGRESS"
    assert by_id["M3C-B"].percent_complete == 80
    assert by_id["M3D"].status == "NOT STARTED"
    assert by_id["M3D"].percent_complete == 0
    assert progress.percent_complete == round(
        100 * sum(task.done for item in progress.milestones for task in item.tasks)
        / sum(len(item.tasks) for item in progress.milestones)
    )


def test_dashboard_uses_real_database_profile_and_snapshot_counts(tmp_path: Path, monkeypatch) -> None:
    config = RuntimeConfig.from_environment(ROOT)
    config = config.__class__(
        repository_root=config.repository_root,
        database_path=tmp_path / "dashboard.db",
        log_root=tmp_path / "logs",
        host=config.host,
        port=config.port,
        app_path=config.app_path,
        pid_path=tmp_path / "logs/pid.json",
        futu_host=config.futu_host,
        futu_port=config.futu_port,
    )
    monkeypatch.setenv("PATTERN_FINDER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("PATTERN_FINDER_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    database = initialize_local_foundation(config)
    snapshot = _snapshot(tmp_path)
    SnapshotRepository(database).append(snapshot)

    state = build_dashboard_state(config)

    assert state.system_status == "ERROR"
    assert state.database_status == "CONNECTED"
    assert state.schema_version == database.latest_version
    assert state.active_profile == "CORE v1"
    assert state.snapshot_id == str(snapshot.header.universe_snapshot_id)
    assert state.member_count == snapshot.header.member_count
    assert state.fail_count == snapshot.header.candidate_count - snapshot.header.member_count - snapshot.header.quarantine_count
    assert state.quarantine_count == snapshot.header.quarantine_count
    assert state.candidate_count == 0 and state.pending_review_count == 0


def test_diagnostics_contains_no_secret_values(tmp_path: Path, monkeypatch) -> None:
    config = RuntimeConfig.from_environment(ROOT)
    config = config.__class__(
        repository_root=config.repository_root,
        database_path=tmp_path / "diagnostics.db",
        log_root=tmp_path / "logs",
        host=config.host,
        port=config.port,
        app_path=config.app_path,
        pid_path=tmp_path / "logs/pid.json",
        futu_host=config.futu_host,
        futu_port=config.futu_port,
    )
    monkeypatch.setenv("PATTERN_FINDER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("PATTERN_FINDER_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    database = initialize_local_foundation(config)
    diagnostics = build_diagnostics_state(config)
    rendered = repr(diagnostics).casefold()

    assert diagnostics.database_path == str(config.database_path)
    assert diagnostics.schema_version == database.latest_version
    assert "api_key" not in rendered and "password" not in rendered and "secret" not in rendered


def test_home_defaults_to_system_dashboard_and_has_system_navigation(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("PATTERN_FINDER_DB_PATH", str(tmp_path / "home.db"))
    monkeypatch.setenv("PATTERN_FINDER_LOG_ROOT", str(tmp_path / "logs"))
    monkeypatch.setenv("PATTERN_FINDER_REPOSITORY_ROOT", str(ROOT))
    monkeypatch.setenv("PATTERN_FINDER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("PATTERN_FINDER_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    initialize_local_foundation(RuntimeConfig.from_environment(ROOT))

    app = AppTest.from_file(ROOT / "app/Home.py")
    app.run(timeout=20)
    visible = "\n".join(
        str(element.value)
        for kind in ("title", "header", "subheader", "caption", "markdown", "info", "success", "warning", "error")
        for element in app.get(kind)
    )

    assert not app.exception
    assert "Pattern Research System" in visible
    assert "CORE v1" in visible
    assert "CONNECTED" in visible
    source = (ROOT / "app/Home.py").read_text(encoding="utf-8")
    assert "Project Progress" in source and "Diagnostics" in source
    assert "sqlite3" not in source
    assert "initialize_local_foundation" not in source
    assert "SnapshotRepository" not in source


def test_read_only_dashboard_does_not_create_missing_database(tmp_path: Path) -> None:
    base = RuntimeConfig.from_environment(ROOT)
    config = base.__class__(
        repository_root=base.repository_root,
        database_path=tmp_path / "missing" / "dashboard.db",
        log_root=tmp_path / "logs",
        host=base.host,
        port=base.port,
        app_path=base.app_path,
        pid_path=tmp_path / "logs/pid.json",
        futu_host=base.futu_host,
        futu_port=base.futu_port,
    )

    dashboard = build_dashboard_state(config)
    diagnostics = build_diagnostics_state(config)

    assert dashboard.database_status == "ERROR"
    assert diagnostics.schema_version == 0
    assert diagnostics.latest_error is not None
    assert not config.database_path.exists()
    assert not config.database_path.parent.exists()
