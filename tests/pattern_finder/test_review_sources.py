from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from tv_quant.pattern_finder.cache import CacheEntry
from tv_quant.pattern_finder.data_quality import DataQualityReport
from tv_quant.pattern_finder.validation import build_pattern_validation


AS_OF = datetime(2026, 8, 28, 20, 1, tzinfo=UTC)
PATTERN_TYPE = "flat_base"
DIAGNOSTICS = {
    "base_length": 25,
    "base_depth": 0.14,
    "bottom_tests": 2,
    "normalized_slope": 0.0,
    "support": 99.0,
    "resistance": 102.0,
}


def _entry(path: Path, symbol: str, final_session: date) -> CacheEntry:
    return CacheEntry(
        symbol=symbol,
        path=path,
        rows=100,
        new_rows=0,
        updated_rows=0,
        quality=DataQualityReport(
            symbol=symbol,
            expected_latest_session=final_session,
            first_session=date(2026, 1, 2),
            last_session=final_session,
            missing_sessions=(),
            errors=(),
            warnings=(),
        ),
    )


def _patch_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, symbols: tuple[str, ...]) -> None:
    from tv_quant.pattern_finder.application import review_sources

    paths = {}
    for symbol in symbols:
        path = tmp_path / f"{symbol}_daily.csv"
        path.write_text(f"cache for {symbol}\n", encoding="utf-8")
        paths[symbol] = path

    monkeypatch.setattr(review_sources, "cached_symbols", lambda _: symbols)
    monkeypatch.setattr(
        review_sources,
        "load_cache_entry",
        lambda symbol, *, cache_root, as_of_utc: _entry(
            paths[symbol], symbol, date(2026, 8, 27)
        ),
    )


def test_cache_source_is_deterministic_and_explicitly_provisional(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tv_quant.pattern_finder.application.review_queue import QueueSourceKind
    from tv_quant.pattern_finder.application.review_sources import build_cache_queue_source

    _patch_cache(monkeypatch, tmp_path, ("AAPL", "MSFT"))

    first = build_cache_queue_source(tmp_path, AS_OF, PATTERN_TYPE, ())
    second = build_cache_queue_source(tmp_path, AS_OF, PATTERN_TYPE, ())

    assert first == second
    assert first.source_kind is QueueSourceKind.PROVISIONAL_CACHE
    assert first.label == "LOCAL CACHE · NOT A FORMAL SCAN BATCH"
    assert tuple(item.symbol for item in first.items) == ("AAPL", "MSFT")
    assert tuple(item.source_rank for item in first.items) == (0, 1)
    assert all(item.computer_decision is None for item in first.items)
    assert all(item.data_quality_passed for item in first.items)
    assert all(item.scan_as_of_date == "2026-08-27" for item in first.items)


def test_cache_source_never_runs_detector(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tv_quant.pattern_finder import flat_base
    from tv_quant.pattern_finder.application.review_sources import build_cache_queue_source

    _patch_cache(monkeypatch, tmp_path, ("AAPL",))
    monkeypatch.setattr(
        flat_base,
        "detect_flat_base",
        lambda *_args, **_kwargs: pytest.fail("cache source must not run detector"),
    )

    source = build_cache_queue_source(tmp_path, AS_OF, PATTERN_TYPE, ())

    assert source.items[0].computer_decision is None


def test_cache_file_identity_changes_item_and_source_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tv_quant.pattern_finder.application.review_sources import build_cache_queue_source

    _patch_cache(monkeypatch, tmp_path, ("AAPL",))
    initial = build_cache_queue_source(tmp_path, AS_OF, PATTERN_TYPE, ())
    (tmp_path / "AAPL_daily.csv").write_text("changed cache contents\n", encoding="utf-8")

    changed = build_cache_queue_source(tmp_path, AS_OF, PATTERN_TYPE, ())

    assert changed.items[0].item_id != initial.items[0].item_id
    assert changed.source_id != initial.source_id


def test_cache_source_attaches_only_matching_current_validation_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tv_quant.pattern_finder.application.review_sources import build_cache_queue_source

    _patch_cache(monkeypatch, tmp_path, ("AAPL",))
    matching = build_pattern_validation(
        recorded_at_utc=AS_OF,
        symbol="AAPL",
        pattern_type=PATTERN_TYPE,
        detector_version="phase1-v1",
        scan_as_of_date=date(2026, 8, 27),
        computer_result="YES",
        human_label="像",
        reason_tags=(),
        note="",
        review_window_start=date(2026, 8, 1),
        review_window_end=date(2026, 8, 27),
        diagnostics=DIAGNOSTICS,
    )
    older = build_pattern_validation(
        recorded_at_utc=AS_OF + timedelta(minutes=1),
        symbol="AAPL",
        pattern_type=PATTERN_TYPE,
        detector_version="phase1-v1",
        scan_as_of_date=date(2026, 8, 26),
        computer_result="NO",
        human_label="不像",
        reason_tags=("整体仍明显向下",),
        note="",
        review_window_start=date(2026, 8, 1),
        review_window_end=date(2026, 8, 26),
        diagnostics=DIAGNOSTICS,
    )

    source = build_cache_queue_source(tmp_path, AS_OF, PATTERN_TYPE, (older, matching))
    item = source.items[0]

    assert item.human_label == "像"
    assert item.validation_result == "true_positive_like"
    assert item.history_count == 1

    stale_only = build_cache_queue_source(tmp_path, AS_OF, PATTERN_TYPE, (older,))
    assert stale_only.items[0].human_label is None
    assert stale_only.items[0].validation_result is None
    assert stale_only.items[0].history_count == 0


def test_cache_source_rejects_duplicate_symbols(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tv_quant.pattern_finder.application.review_sources import build_cache_queue_source

    _patch_cache(monkeypatch, tmp_path, ("AAPL", "AAPL"))

    with pytest.raises(ValueError, match="duplicate cached symbol"):
        build_cache_queue_source(tmp_path, AS_OF, PATTERN_TYPE, ())


def _formal_batch():
    from tv_quant.pattern_finder.application.scan_persistence import (
        CompletedScanBatch,
        MachineDecision,
        ScanManifest,
        ScanResult,
    )

    batch_id = "scan-" + "1" * 64
    decisions = (
        ("AAPL", MachineDecision.YES, ()),
        ("MSFT", MachineDecision.NO, ()),
        ("BAC", MachineDecision.NOT_EVALUATED, ("MISSING_CACHE",)),
    )
    results = tuple(
        ScanResult(
            candidate_id=f"candidate-{rank}",
            scan_batch_id=batch_id,
            source_rank=rank,
            stock_id=f"stock-{rank}",
            symbol=symbol,
            pattern_type=PATTERN_TYPE,
            pattern_version="phase1-v1",
            signal_date="2026-08-27",
            computer_decision=decision,
            features={"adjustment": "QFQ"},
            reason_codes=reasons,
            created_at_utc=AS_OF,
        )
        for rank, (symbol, decision, reasons) in enumerate(decisions)
    )
    return CompletedScanBatch(
        scan_batch_id=batch_id,
        snapshot_id="11111111-1111-1111-1111-111111111111",
        profile_version_id="CORE:v1",
        pattern_type=PATTERN_TYPE,
        pattern_version="phase1-v1",
        started_at_utc=AS_OF,
        completed_at_utc=AS_OF,
        status="COMPLETED",
        input_hash="a" * 64,
        config_hash="b" * 64,
        result_hash="c" * 64,
        manifest=ScanManifest(
            scan_as_of_date="2026-08-27",
            ordered_input_count=3,
            quality_pass_count=2,
            quality_fail_count=1,
            yes_count=1,
            no_count=1,
            code_commit="b8f0784",
            ordered_input_hash="a" * 64,
            provenance={"adjustment": "QFQ"},
        ),
        results=results,
    )


def _formal_validation(*, scan_as_of_date: date = date(2026, 8, 27)):
    return build_pattern_validation(
        recorded_at_utc=AS_OF,
        symbol="AAPL",
        pattern_type=PATTERN_TYPE,
        detector_version="phase1-v1",
        scan_as_of_date=scan_as_of_date,
        computer_result="YES",
        human_label="像",
        reason_tags=(),
        note="",
        review_window_start=date(2026, 8, 1),
        review_window_end=scan_as_of_date,
        diagnostics=DIAGNOSTICS,
    )


def test_formal_scan_source_preserves_batch_order_results_and_exact_history() -> None:
    from tv_quant.pattern_finder.application.review_queue import QueueSourceKind
    from tv_quant.pattern_finder.application.review_sources import (
        build_scan_batch_queue_source,
    )

    source = build_scan_batch_queue_source(
        _formal_batch(),
        (_formal_validation(scan_as_of_date=date(2026, 8, 26)), _formal_validation()),
    )

    assert source.source_kind is QueueSourceKind.SCAN_BATCH
    assert source.source_id == "scan-" + "1" * 64
    assert source.label == "FORMAL SCAN BATCH · IMMUTABLE"
    assert tuple(item.symbol for item in source.items) == ("AAPL", "MSFT", "BAC")
    assert tuple(item.source_rank for item in source.items) == (0, 1, 2)
    assert tuple(item.computer_decision for item in source.items) == (
        "YES",
        "NO",
        "NOT_EVALUATED",
    )
    assert source.items[0].human_label == "像"
    assert source.items[0].validation_result == "true_positive_like"
    assert source.items[0].history_count == 1
    assert source.items[1].history_count == 0


def test_not_evaluated_formal_result_is_data_blocked_never_machine_no() -> None:
    from tv_quant.pattern_finder.application.review_queue import (
        QueueFilters,
        QueueState,
        project_queue,
    )
    from tv_quant.pattern_finder.application.review_sources import (
        build_scan_batch_queue_source,
    )

    source = build_scan_batch_queue_source(_formal_batch(), ())
    blocked = source.items[2]
    view = project_queue(source.items, {}, QueueFilters(), None)

    assert blocked.computer_decision == "NOT_EVALUATED"
    assert blocked.computer_decision != "NO"
    assert not blocked.data_quality_passed
    assert blocked.quality_reason == "MISSING_CACHE"
    assert view.states[blocked.item_id] is QueueState.DATA_BLOCKED


def test_formal_scan_source_never_reads_cache_or_runs_detector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tv_quant.pattern_finder import flat_base
    from tv_quant.pattern_finder.application import review_sources

    monkeypatch.setattr(
        review_sources,
        "cached_symbols",
        lambda *_args, **_kwargs: pytest.fail("formal source must not list cache"),
    )
    monkeypatch.setattr(
        review_sources,
        "load_cache_entry",
        lambda *_args, **_kwargs: pytest.fail("formal source must not read cache"),
    )
    monkeypatch.setattr(
        flat_base,
        "detect_flat_base",
        lambda *_args, **_kwargs: pytest.fail("formal source must not run detector"),
    )

    source = review_sources.build_scan_batch_queue_source(_formal_batch(), ())

    assert len(source.items) == 3
