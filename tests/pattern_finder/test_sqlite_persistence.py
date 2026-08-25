from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import sys

import pytest

from tv_quant.pattern_finder.persistence.database import Migration, MigrationError, SqliteDatabase
from tv_quant.pattern_finder.persistence.legacy_import import migrate_snapshot_store
from tv_quant.pattern_finder.persistence.repositories import ProfileRepository, SnapshotRepository
from tv_quant.pattern_finder.universe_foundation import UniverseSnapshotStore, core_v1


ROOT = Path(__file__).resolve().parents[2]


def _snapshot_fixture(tmp_path: Path):
    module_name = "m3cc_snapshot_fixture"
    module = sys.modules.get(module_name)
    if module is None:
        path = ROOT / "tests/pattern_finder/universe_foundation/test_ui_read_model.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    store, snapshot = module._persist_complete_snapshot(tmp_path / "legacy")
    return snapshot, store


def test_empty_database_migrates_once_and_enables_foreign_keys(tmp_path: Path) -> None:
    database = SqliteDatabase(tmp_path / "pattern_finder.db")

    assert database.migrate() == database.latest_version
    assert database.migrate() == database.latest_version
    assert database.current_version() == database.latest_version
    with database.connect() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        count = connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
        assert count == database.latest_version
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "app_runs", "audit_events", "profiles", "profile_versions", "profile_rules",
        "universe_snapshots", "snapshot_securities", "snapshot_security_decisions",
        "scan_batches", "pattern_candidates", "manual_reviews", "backtest_runs",
        "backtest_horizons",
    } <= tables


def test_failed_migration_rolls_back_schema_and_version(tmp_path: Path) -> None:
    database = SqliteDatabase(
        tmp_path / "broken.db",
        migrations=(
            Migration(1, "broken", ("CREATE TABLE partial_table(id INTEGER)", "INVALID SQL")),
        ),
    )
    with pytest.raises(MigrationError):
        database.migrate()
    with database.connect() as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "partial_table" not in tables
    assert "schema_migrations" not in tables


def test_published_profile_is_idempotent_and_immutable(tmp_path: Path) -> None:
    database = SqliteDatabase(tmp_path / "profiles.db")
    database.migrate()
    repository = ProfileRepository(database)
    profile = core_v1()

    repository.put_published(profile)
    repository.put_published(profile)
    loaded = repository.get_published("CORE:v1")

    assert loaded is not None
    assert loaded["content_sha256"] == profile.content_sha256
    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute("UPDATE profile_versions SET change_note='changed' WHERE profile_version_id='CORE:v1'")


def test_snapshot_round_trip_preserves_rows_hashes_and_s0_s10(tmp_path: Path) -> None:
    snapshot, _ = _snapshot_fixture(tmp_path)
    database = SqliteDatabase(tmp_path / "snapshots.db")
    database.migrate()
    ProfileRepository(database).put_published(core_v1())
    repository = SnapshotRepository(database)

    repository.append(snapshot)
    repository.append(snapshot)
    loaded = repository.get(snapshot.header.universe_snapshot_id)

    assert loaded == snapshot
    assert len(loaded.rows) == len(snapshot.rows)
    assert loaded.header.members_sha256 == snapshot.header.members_sha256
    assert loaded.header.snapshot_content_sha256 == snapshot.header.snapshot_content_sha256
    assert loaded.header.snapshot_record_sha256 == snapshot.header.snapshot_record_sha256
    with database.connect() as connection:
        stages = connection.execute(
            """SELECT stage FROM snapshot_security_decisions
               WHERE snapshot_id=? AND stock_id=? AND futu_code=? ORDER BY stage_order""",
            (str(snapshot.header.universe_snapshot_id), snapshot.rows[0].stock_id, snapshot.rows[0].futu_code),
        ).fetchall()
    assert [row[0] for row in stages] == [f"S{i}" for i in range(11)]


def test_legacy_import_dry_run_then_import_keeps_source_and_verifies_hashes(tmp_path: Path) -> None:
    snapshot, store = _snapshot_fixture(tmp_path)
    database = SqliteDatabase(tmp_path / "migration.db")
    database.migrate()
    ProfileRepository(database).put_published(core_v1())
    repository = SnapshotRepository(database)

    dry = migrate_snapshot_store(store, repository, dry_run=True)
    actual = migrate_snapshot_store(store, repository, dry_run=False)

    assert dry.validated == 1 and dry.imported == 0
    assert actual.imported == 1 and actual.conflicts == 0 and actual.errors == ()
    assert repository.get(snapshot.header.universe_snapshot_id) == snapshot
    assert tuple((tmp_path / "legacy").glob("*.json"))
