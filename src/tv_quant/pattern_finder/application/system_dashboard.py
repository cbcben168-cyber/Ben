"""Read-only system Dashboard and diagnostics application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
import platform
import os
import socket
import subprocess
from uuid import UUID

import yaml

from tv_quant.pattern_finder.persistence.database import SqliteDatabase
from tv_quant.pattern_finder.persistence.repositories import (
    BacktestRepository,
    ProfileRepository,
    ReviewRepository,
    ScanRepository,
    SnapshotRepository,
    SystemRepository,
)
from tv_quant.pattern_finder.runtime.config import RuntimeConfig
from tv_quant.pattern_finder.runtime.service import service_health
from tv_quant.pattern_finder.universe_foundation import core_v1
from tv_quant.pattern_finder.universe_foundation import ProfileRegistry, UniverseSnapshotStore
from tv_quant.pattern_finder.persistence.legacy_import import migrate_snapshot_store


@dataclass(frozen=True, slots=True)
class ProgressTask:
    task_id: str
    name: str
    done: bool


@dataclass(frozen=True, slots=True)
class MilestoneProgress:
    milestone_id: str
    name: str
    status: str
    percent_complete: int
    tasks: tuple[ProgressTask, ...]


@dataclass(frozen=True, slots=True)
class ProjectProgress:
    version: int
    percent_complete: int
    milestones: tuple[MilestoneProgress, ...]


@dataclass(frozen=True, slots=True)
class DashboardState:
    system_status: str
    database_status: str
    schema_version: int
    futu_status: str
    active_profile: str
    snapshot_id: str | None
    snapshot_time: str | None
    member_count: int
    fail_count: int
    quarantine_count: int
    last_scan: str
    candidate_count: int
    pending_review_count: int
    last_backtest: str
    data_freshness: str


@dataclass(frozen=True, slots=True)
class DiagnosticsState:
    app_version: str
    git_commit: str
    python_version: str
    database_path: str
    schema_version: int
    runtime_pid: int | None
    port: int
    uptime: str
    futu_connection: str
    data_directory: str
    log_directory: str
    latest_error: str | None
    latest_migration: str | None
    latest_snapshot_integrity: str


def load_project_progress(path: str | Path) -> ProjectProgress:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or type(payload.get("version")) is not int:
        raise ValueError("project progress requires an integer version")
    milestones: list[MilestoneProgress] = []
    all_tasks: list[ProgressTask] = []
    for raw in payload.get("milestones", []):
        if not isinstance(raw, dict) or not isinstance(raw.get("tasks"), list) or not raw["tasks"]:
            raise ValueError("each milestone requires tasks")
        tasks = tuple(
            ProgressTask(str(item["id"]), str(item["name"]), item["status"] == "done")
            for item in raw["tasks"]
        )
        if raw.get("blocked"):
            status = "BLOCKED"
        elif all(item.done for item in tasks):
            status = "DONE"
        elif any(item.done for item in tasks):
            status = "IN PROGRESS"
        else:
            status = "NOT STARTED"
        percent = round(100 * sum(item.done for item in tasks) / len(tasks))
        milestones.append(MilestoneProgress(str(raw["id"]), str(raw["name"]), status, percent, tasks))
        all_tasks.extend(tasks)
    if not all_tasks:
        raise ValueError("project progress requires at least one task")
    return ProjectProgress(payload["version"], round(100 * sum(item.done for item in all_tasks) / len(all_tasks)), tuple(milestones))


def initialize_local_foundation(config: RuntimeConfig) -> SqliteDatabase:
    database = SqliteDatabase(config.database_path)
    database.migrate()
    profiles = ProfileRepository(database)
    profile_root = Path(
        os.getenv(
            "PATTERN_FINDER_PROFILE_ROOT",
            str(config.repository_root / "data/pattern_finder/universe_profiles"),
        )
    )
    registry = ProfileRegistry(profile_root)
    registry.bootstrap(core_v1())
    for profile in registry.list_published():
        profiles.put_published(profile)
    snapshot_root = Path(
        os.getenv(
            "PATTERN_FINDER_SNAPSHOT_ROOT",
            str(config.repository_root / "data/pattern_finder/universe_snapshots"),
        )
    )
    if snapshot_root.exists():
        report = migrate_snapshot_store(
            UniverseSnapshotStore(snapshot_root), SnapshotRepository(database), dry_run=False
        )
        if report.conflicts or report.errors:
            raise RuntimeError(
                "legacy Snapshot migration failed: "
                f"conflicts={report.conflicts}, errors={'; '.join(report.errors)}"
            )
    return database


def _futu_available(config: RuntimeConfig) -> bool:
    try:
        with socket.create_connection((config.futu_host, config.futu_port), timeout=0.2):
            return True
    except OSError:
        return False


def build_dashboard_state(config: RuntimeConfig, database: SqliteDatabase) -> DashboardState:
    try:
        schema = database.current_version()
        database_ok = schema == database.latest_version
        active = ProfileRepository(database).active()
        snapshot = SnapshotRepository(database).latest_summary()
        scan = ScanRepository(database).latest()
        backtest = BacktestRepository(database).latest()
        candidate_count = ScanRepository(database).candidate_count()
        pending = ReviewRepository(database).pending_count()
    except Exception:
        return DashboardState("ERROR", "ERROR", 0, "UNAVAILABLE", "-", None, None, 0, 0, 0, "-", 0, 0, "-", "UNKNOWN")
    profile = "-" if active is None else f"{active['profile_id']} v{active['version']}"
    if snapshot is None:
        snapshot_id = snapshot_time = None
        members = fails = quarantines = 0
        freshness = "UNKNOWN"
    else:
        snapshot_id = str(snapshot["snapshot_id"])
        snapshot_time = str(snapshot["created_at_utc"])
        members, fails, quarantines = int(snapshot["member_count"]), int(snapshot["fail_count"]), int(snapshot["quarantine_count"])
        age_days = (datetime.now(UTC).date() - date.fromisoformat(str(snapshot["as_of_date"]))).days
        freshness = "CURRENT" if age_days <= 3 else "STALE"
    last_scan = "-" if scan is None else f"{scan['pattern_type']} {scan.get('completed_at_utc') or scan['started_at_utc']}"
    last_backtest = "-" if backtest is None else str(backtest["created_at_utc"])
    return DashboardState(
        "RUNNING" if database_ok else "ERROR", "CONNECTED" if database_ok else "ERROR", schema,
        "AVAILABLE" if _futu_available(config) else "UNAVAILABLE", profile,
        snapshot_id, snapshot_time, members, fails, quarantines, last_scan,
        candidate_count, pending, last_backtest, freshness,
    )


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=root, text=True, timeout=3,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def build_diagnostics_state(config: RuntimeConfig, database: SqliteDatabase) -> DiagnosticsState:
    system = SystemRepository(database)
    run = system.latest_run()
    migration = system.latest_migration()
    health = service_health(config)
    latest = SnapshotRepository(database).latest_summary()
    integrity = "NO SNAPSHOT"
    if latest is not None:
        try:
            snapshot = SnapshotRepository(database).get(UUID(str(latest["snapshot_id"])))
            integrity = f"VALID {snapshot.header.snapshot_record_sha256}"
        except Exception as error:
            integrity = f"ERROR {type(error).__name__}"
    if run and run.get("started_at_utc"):
        started = datetime.fromisoformat(str(run["started_at_utc"]))
        uptime = str(datetime.now(UTC) - started).split(".")[0] if run.get("status") == "RUNNING" else "STOPPED"
    else:
        uptime = "UNKNOWN"
    return DiagnosticsState(
        "pattern-finder-local/v1", _git_commit(config.repository_root), platform.python_version(),
        str(config.database_path), database.current_version(), health.pid, config.port, uptime,
        "AVAILABLE" if _futu_available(config) else "UNAVAILABLE",
        str(config.repository_root / "data"), str(config.log_root),
        None if not run else run.get("error_summary"),
        None if migration is None else f"v{migration['version']} {migration['migration_id']} {migration['applied_at_utc']}",
        integrity,
    )
