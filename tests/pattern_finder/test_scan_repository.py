from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
import sys

import pytest

from tv_quant.pattern_finder.application.scan_persistence import build_flat_base_scan
from tv_quant.pattern_finder.persistence.database import SqliteDatabase
from tv_quant.pattern_finder.persistence.repositories import (
    ProfileRepository,
    SnapshotRepository,
)
from tv_quant.pattern_finder.universe_foundation import SnapshotNotFoundError, core_v1


ROOT = Path(__file__).resolve().parents[2]
COMPLETED = datetime(2026, 8, 29, 18, 30, tzinfo=UTC)


def _snapshot(tmp_path: Path):
    module_name = "m3d_scan_repository_snapshot_fixture"
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


@pytest.fixture
def database(tmp_path: Path) -> SqliteDatabase:
    result = SqliteDatabase(tmp_path / "pattern-finder.db")
    result.migrate()
    ProfileRepository(result).put_published(core_v1())
    return result


@pytest.fixture
def snapshot(tmp_path: Path, database: SqliteDatabase):
    result = _snapshot(tmp_path)
    SnapshotRepository(database).append(result)
    return result


@pytest.fixture
def batch(tmp_path: Path, snapshot):
    return build_flat_base_scan(
        snapshot,
        cache_root=tmp_path / "empty-cache",
        completed_at_utc=COMPLETED,
        code_commit="ff6d44d",
    )


def test_completed_batch_round_trips_and_is_idempotent(database, batch) -> None:
    from tv_quant.pattern_finder.persistence.scan_repository import ScanRepository

    repository = ScanRepository(database)
    first = repository.append_completed(batch)
    second = repository.append_completed(batch)

    assert first == batch
    assert second == batch
    assert repository.get(batch.scan_batch_id) == batch
    assert repository.list_completed() == (batch,)
    assert repository.latest() == batch
    assert repository.candidate_count() == batch.manifest.ordered_input_count
    assert repository.candidate_count(batch.scan_batch_id) == len(batch.results)


def test_same_batch_id_with_different_content_is_conflict(database, batch) -> None:
    from dataclasses import replace

    from tv_quant.pattern_finder.persistence.scan_repository import (
        ScanConflictError,
        ScanRepository,
    )

    repository = ScanRepository(database)
    repository.append_completed(batch)

    with pytest.raises(ScanConflictError, match="scan batch conflict"):
        repository.append_completed(replace(batch, result_hash="f" * 64))


def test_any_candidate_insert_failure_rolls_back_every_scan_row(database, batch) -> None:
    from tv_quant.pattern_finder.persistence.scan_repository import ScanRepository

    with database.connect() as connection:
        connection.execute(
            """CREATE TRIGGER reject_scan_candidate BEFORE INSERT ON pattern_candidates
               BEGIN SELECT RAISE(ABORT, 'simulated candidate failure'); END"""
        )
    repository = ScanRepository(database)

    with pytest.raises(sqlite3.IntegrityError, match="simulated candidate failure"):
        repository.append_completed(batch)

    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM scan_batches").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM scan_batch_manifests").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM pattern_candidates").fetchone()[0] == 0


def test_missing_snapshot_is_rejected_before_any_scan_write(
    tmp_path: Path, database: SqliteDatabase
) -> None:
    from tv_quant.pattern_finder.persistence.scan_repository import ScanRepository

    missing_snapshot = _snapshot(tmp_path)
    batch = build_flat_base_scan(
        missing_snapshot,
        cache_root=tmp_path / "empty-cache",
        completed_at_utc=COMPLETED,
        code_commit="ff6d44d",
    )

    with pytest.raises(SnapshotNotFoundError, match="snapshot not found"):
        ScanRepository(database).append_completed(batch)
    assert ScanRepository(database).list_completed() == ()


def test_snapshot_content_binding_is_verified_before_scan_write(database, batch) -> None:
    from dataclasses import replace

    from tv_quant.pattern_finder.persistence.scan_repository import ScanRepository

    provenance = dict(batch.manifest.provenance)
    provenance["snapshot_sha256"] = "f" * 64
    mismatched = replace(
        batch,
        manifest=replace(batch.manifest, provenance=provenance),
    )

    with pytest.raises(ValueError, match="Snapshot content binding"):
        ScanRepository(database).append_completed(mismatched)
    assert ScanRepository(database).list_completed() == ()


def test_read_detects_result_payload_tampering(database, batch) -> None:
    from tv_quant.pattern_finder.persistence.scan_repository import (
        ScanCorruptError,
        ScanRepository,
    )

    repository = ScanRepository(database)
    repository.append_completed(batch)
    with database.connect() as connection:
        connection.execute("DROP TRIGGER pattern_candidates_immutable_update")
        row = connection.execute(
            "SELECT candidate_id,features_json FROM pattern_candidates LIMIT 1"
        ).fetchone()
        features = json.loads(row["features_json"])
        features["cache_sha256"] = "f" * 64
        connection.execute(
            "UPDATE pattern_candidates SET features_json=? WHERE candidate_id=?",
            (json.dumps(features, sort_keys=True), row["candidate_id"]),
        )

    with pytest.raises(ScanCorruptError, match="result hash mismatch"):
        repository.get(batch.scan_batch_id)


def test_read_detects_manifest_tampering(database, batch) -> None:
    from tv_quant.pattern_finder.persistence.scan_repository import (
        ScanCorruptError,
        ScanRepository,
    )

    repository = ScanRepository(database)
    repository.append_completed(batch)
    with database.connect() as connection:
        connection.execute("DROP TRIGGER scan_batch_manifests_immutable_update")
        connection.execute(
            "UPDATE scan_batch_manifests SET code_commit='changed' WHERE scan_batch_id=?",
            (batch.scan_batch_id,),
        )

    with pytest.raises(ScanCorruptError, match="batch ID mismatch"):
        repository.get(batch.scan_batch_id)


def test_completed_header_manifest_and_candidates_are_immutable(database, batch) -> None:
    from tv_quant.pattern_finder.persistence.scan_repository import ScanRepository

    ScanRepository(database).append_completed(batch)

    statements = (
        ("UPDATE scan_batches SET status='FAILED' WHERE scan_batch_id=?", "completed scan batch"),
        (
            "UPDATE scan_batch_manifests SET code_commit='changed' WHERE scan_batch_id=?",
            "scan batch manifest",
        ),
        (
            "DELETE FROM pattern_candidates WHERE scan_batch_id=?",
            "completed pattern candidate",
        ),
    )
    for sql, message in statements:
        with database.connect() as connection:
            with pytest.raises(sqlite3.IntegrityError, match=message):
                connection.execute(sql, (batch.scan_batch_id,))


def test_get_restores_source_rank_order_not_candidate_id_order(database, batch) -> None:
    from tv_quant.pattern_finder.persistence.scan_repository import ScanRepository

    repository = ScanRepository(database)
    repository.append_completed(batch)

    with database.connect() as connection:
        stored = connection.execute(
            "SELECT features_json FROM pattern_candidates WHERE scan_batch_id=?",
            (batch.scan_batch_id,),
        ).fetchall()
    ranks = tuple(json.loads(row[0])["source_rank"] for row in stored)

    assert ranks == tuple(range(len(batch.results)))
    assert tuple(row.source_rank for row in repository.get(batch.scan_batch_id).results) == ranks
