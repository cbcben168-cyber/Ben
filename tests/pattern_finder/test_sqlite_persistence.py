from __future__ import annotations

import importlib.util
from concurrent.futures import ThreadPoolExecutor
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


def test_multiple_pending_migrations_commit_as_one_atomic_set(tmp_path: Path) -> None:
    database = SqliteDatabase(
        tmp_path / "atomic.db",
        migrations=(
            Migration(1, "first", (
                "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, migration_id TEXT NOT NULL UNIQUE, checksum TEXT NOT NULL, applied_at_utc TEXT NOT NULL)",
                "CREATE TABLE first_table(id INTEGER)",
            )),
            Migration(2, "broken", ("CREATE TABLE second_table(id INTEGER)", "INVALID SQL")),
        ),
    )
    with pytest.raises(MigrationError):
        database.migrate()
    with database.connect() as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "schema_migrations" not in tables
    assert "first_table" not in tables
    assert "second_table" not in tables


def test_checksum_mismatch_blocks_all_pending_migrations(tmp_path: Path) -> None:
    first = Migration(1, "first", (
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, migration_id TEXT NOT NULL UNIQUE, checksum TEXT NOT NULL, applied_at_utc TEXT NOT NULL)",
        "CREATE TABLE first_table(id INTEGER)",
    ))
    path = tmp_path / "checksum.db"
    SqliteDatabase(path, migrations=(first,)).migrate()
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE schema_migrations SET checksum='tampered' WHERE version=1")
    database = SqliteDatabase(
        path,
        migrations=(first, Migration(2, "second", ("CREATE TABLE second_table(id INTEGER)",))),
    )
    with pytest.raises(MigrationError, match="checksum mismatch"):
        database.migrate()
    with pytest.raises(MigrationError, match="checksum mismatch"):
        database.validate_schema()
    with database.connect() as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "second_table" not in tables


def test_concurrent_migration_attempts_serialize_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "concurrent.db"
    with ThreadPoolExecutor(max_workers=2) as pool:
        versions = tuple(pool.map(lambda _: SqliteDatabase(path).migrate(), range(2)))
    assert versions == (1, 1)
    with SqliteDatabase(path).connect() as connection:
        assert connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1


def test_foreign_keys_reject_orphan_profile_version(tmp_path: Path) -> None:
    database = SqliteDatabase(tmp_path / "foreign-key.db")
    database.migrate()
    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        connection.execute(
            """INSERT INTO profile_versions(
                profile_version_id,profile_id,version,status,parent_profile_version_id,
                created_at_utc,published_at_utc,change_note,schema_version,profile_payload_json,
                content_sha256,filter_content_sha256
            ) VALUES('MISSING:v1','MISSING',1,'PUBLISHED',NULL,'2026-01-01T00:00:00+00:00',
                     '2026-01-01T00:00:00+00:00','x','v1','{}',?,?)""",
            ("0" * 64, "0" * 64),
        )


def test_published_profile_is_idempotent_and_immutable(tmp_path: Path) -> None:
    database = SqliteDatabase(tmp_path / "profiles.db")
    database.migrate()
    repository = ProfileRepository(database)
    profile = core_v1()

    repository.put_published(profile)
    repository.put_published(profile)
    loaded = repository.get_published("CORE:v1")

    assert loaded == profile
    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute("UPDATE profile_versions SET change_note='changed' WHERE profile_version_id='CORE:v1'")
    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute("UPDATE profile_rules SET rules_json='{}' WHERE profile_version_id='CORE:v1'")
    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute("DELETE FROM profile_rules WHERE profile_version_id='CORE:v1'")


def test_profile_payload_reconstruction_rejects_hash_tampering(tmp_path: Path) -> None:
    database = SqliteDatabase(tmp_path / "profile-integrity.db")
    database.migrate()
    repository = ProfileRepository(database)
    repository.put_published(core_v1())
    with database.connect() as connection:
        connection.execute("DROP TRIGGER profile_versions_immutable_update")
        connection.execute(
            "UPDATE profile_versions SET profile_payload_json=replace(profile_payload_json, 'universe-profile/v1', 'universe-profile/v2') WHERE profile_version_id='CORE:v1'"
        )
    with pytest.raises(ValueError, match="canonical profile payload hash"):
        repository.get_published("CORE:v1")


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
