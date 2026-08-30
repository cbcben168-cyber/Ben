from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

from tv_quant.pattern_finder.application.review_queue import (
    QueueFilters,
    move_visible,
    project_queue,
)
from tv_quant.pattern_finder.application.review_sources import (
    build_scan_batch_queue_source,
)
from tv_quant.pattern_finder.application.scan_persistence import (
    _canonical_json,
    build_flat_base_scan,
)
from tv_quant.pattern_finder.persistence import ScanRepository
from tv_quant.pattern_finder.persistence.database import SqliteDatabase
from tv_quant.pattern_finder.persistence.repositories import (
    ProfileRepository,
    SnapshotRepository,
)
from tv_quant.pattern_finder.universe_foundation import core_v1


ROOT = Path(__file__).resolve().parents[2]


def _fixture_module():
    module_name = "m3d_formal_acceptance_snapshot_fixture"
    module = sys.modules.get(module_name)
    if module is not None:
        return module
    path = ROOT / "tests/pattern_finder/universe_foundation/test_ui_read_model.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _three_member_snapshot():
    fixture = _fixture_module()
    evidence = tuple(
        fixture._snapshot_evidence(symbol) for symbol in ("AAPL", "MSFT", "BAC")
    )
    prerequisites = tuple(fixture._snapshot_prerequisite(item) for item in evidence)
    classifications = tuple(
        fixture.ClassificationResult(
            decision=fixture.Decision.PASS,
            normalized_class="COMMON_STOCK",
            reason_code="CLASSIFICATION_COMMON_STOCK",
            evidence=item.classification_evidence,
        )
        for item in evidence
    )
    evaluations = tuple(
        fixture.evaluate_security(core_v1(), item, classification, prerequisite)
        for item, classification, prerequisite in zip(
            evidence, classifications, prerequisites
        )
    )
    return fixture.build_snapshot(
        kind=fixture.SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=fixture._snapshot_attempt(evidence, prerequisites),
        evaluations=evaluations,
        funnel=fixture.build_funnel(evaluations),
        universe_snapshot_id=fixture.SNAPSHOT_ID,
        created_at_utc=fixture.UTC_NOW,
    )


def _canonical_batch_sections(batch) -> tuple[bytes, bytes, bytes]:
    header = _canonical_json(
        {
            "scan_batch_id": batch.scan_batch_id,
            "snapshot_id": batch.snapshot_id,
            "profile_version_id": batch.profile_version_id,
            "pattern_type": batch.pattern_type,
            "pattern_version": batch.pattern_version,
            "started_at_utc": batch.started_at_utc,
            "completed_at_utc": batch.completed_at_utc,
            "status": batch.status,
            "input_hash": batch.input_hash,
            "config_hash": batch.config_hash,
            "result_hash": batch.result_hash,
        }
    )
    manifest = _canonical_json(
        {
            "scan_as_of_date": batch.manifest.scan_as_of_date,
            "ordered_input_count": batch.manifest.ordered_input_count,
            "quality_pass_count": batch.manifest.quality_pass_count,
            "quality_fail_count": batch.manifest.quality_fail_count,
            "yes_count": batch.manifest.yes_count,
            "no_count": batch.manifest.no_count,
            "code_commit": batch.manifest.code_commit,
            "ordered_input_hash": batch.manifest.ordered_input_hash,
            "provenance": batch.manifest.provenance,
        }
    )
    results = _canonical_json(
        tuple(
            {
                "candidate_id": result.candidate_id,
                "scan_batch_id": result.scan_batch_id,
                "source_rank": result.source_rank,
                "stock_id": result.stock_id,
                "symbol": result.symbol,
                "pattern_type": result.pattern_type,
                "pattern_version": result.pattern_version,
                "signal_date": result.signal_date,
                "computer_decision": result.computer_decision,
                "features": result.features,
                "reason_codes": result.reason_codes,
                "created_at_utc": result.created_at_utc,
            }
            for result in batch.results
        )
    )
    return header, manifest, results


def test_formal_batch_reopens_and_navigates_without_any_recomputation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tv_quant import futu_downloader
    from tv_quant.pattern_finder import cache, flat_base, futu_service
    from tv_quant.pattern_finder.application import scan_persistence

    database_path = tmp_path / "pattern-finder.db"
    initial_database = SqliteDatabase(database_path)
    initial_database.migrate()
    ProfileRepository(initial_database).put_published(core_v1())
    snapshot = _three_member_snapshot()
    SnapshotRepository(initial_database).append(snapshot)
    batch = build_flat_base_scan(
        snapshot,
        cache_root=tmp_path / "empty-cache",
        completed_at_utc=_fixture_module().UTC_NOW,
        code_commit="task-6-acceptance",
    )
    ScanRepository(initial_database).append_completed(batch)
    original_sections = _canonical_batch_sections(batch)
    assert len(batch.results) == 3

    def forbidden(*_args, **_kwargs):
        pytest.fail("formal reopen/navigation must not build, detect, download, or call OpenD")

    monkeypatch.setattr(scan_persistence, "build_flat_base_scan", forbidden)
    monkeypatch.setattr(flat_base, "detect_flat_base", forbidden)
    monkeypatch.setattr(cache, "refresh_cache_entry", forbidden)
    monkeypatch.setattr(cache, "update_futu_csv", forbidden)
    monkeypatch.setattr(futu_downloader, "download_futu_daily", forbidden)
    monkeypatch.setattr(futu_downloader, "update_futu_csv", forbidden)
    monkeypatch.setattr(futu_service, "refresh_symbols", forbidden)
    monkeypatch.setattr(futu_service, "refresh_cache_entry", forbidden)
    monkeypatch.setattr(futu_service, "_load_futu_sdk", forbidden)

    reopened_database = SqliteDatabase(database_path, read_only=True)
    reopened_database.validate_schema()
    reopened = ScanRepository(reopened_database).get(batch.scan_batch_id)
    source = build_scan_batch_queue_source(reopened, ())
    view = project_queue(source.items, {}, QueueFilters(), None)

    positions = [view.selected_item_id]
    positions.append(move_visible(view, positions[-1], 1))
    positions.append(move_visible(view, positions[-1], 1))

    assert positions == [item.item_id for item in source.items]
    assert reopened == batch
    assert _canonical_batch_sections(reopened) == original_sections
