from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import exchange_calendars as xcals
import pandas as pd
import pytest

from tv_quant.pattern_finder.universe_foundation import (
    Completeness,
    SnapshotKind,
    UniverseSnapshot,
)


COMPLETED = datetime(2026, 8, 28, 23, 30, tzinfo=UTC)
SNAPSHOT_ID = UUID("11111111-1111-4111-8111-111111111111")


def _snapshot(
    symbols: tuple[str, ...],
    *,
    kind: SnapshotKind = SnapshotKind.FORMAL,
    completeness: Completeness = Completeness.COMPLETE,
) -> UniverseSnapshot:
    """Build the minimum validated-type boundary needed by the pure builder."""
    snapshot = object.__new__(UniverseSnapshot)
    object.__setattr__(
        snapshot,
        "header",
        SimpleNamespace(
            universe_snapshot_id=SNAPSHOT_ID,
            snapshot_kind=kind,
            completeness=completeness,
            profile_version_id="CORE:v1" if kind is SnapshotKind.FORMAL else None,
            profile_content_sha256="a" * 64 if kind is SnapshotKind.FORMAL else None,
            as_of_session=date(2026, 8, 28),
            snapshot_sha256="b" * 64,
        ),
    )
    object.__setattr__(
        snapshot,
        "rows",
        tuple(
            SimpleNamespace(
                stock_id=f"stock-{index:03d}",
                futu_code=f"US.{symbol}",
                symbol=symbol,
                is_member=True,
            )
            for index, symbol in enumerate(symbols)
        ),
    )
    object.__setattr__(snapshot, "funnel", SimpleNamespace())
    return snapshot


def _frame(symbol: str, *, detected: bool) -> pd.DataFrame:
    sessions = xcals.get_calendar("XNYS").sessions_window("2026-08-28", -120)
    rows = len(sessions)
    base_start = rows - 30
    pivot_lows = {5: 99.0, 20: 99.5} if detected else {5: 86.4, 20: 86.5}
    values: list[dict[str, object]] = []
    for index, timestamp in enumerate(sessions):
        if index < base_start:
            close = 112.0 - 0.12 * index
            high = close + 1.0
            low = close - 1.0
        else:
            offset = index - base_start
            close = 101.0
            high = close + 1.0
            low = pivot_lows.get(offset, close - 0.5 + 0.002 * offset)
        values.append(
            {
                "timestamp_utc": timestamp,
                "ticker": symbol,
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1_000_000,
            }
        )
    return pd.DataFrame(values)


def _write_cache(root: Path, symbol: str, *, detected: bool) -> Path:
    path = root / f"{symbol}_daily.csv"
    _frame(symbol, detected=detected).to_csv(path, index=False)
    return path


def test_formal_builder_accounts_for_yes_no_and_blocked_members(tmp_path: Path) -> None:
    from tv_quant.pattern_finder.application.scan_persistence import (
        MachineDecision,
        build_flat_base_scan,
    )

    snapshot = _snapshot(("AAPL", "MSFT", "BAC"))
    _write_cache(tmp_path, "AAPL", detected=True)
    _write_cache(tmp_path, "MSFT", detected=False)

    batch = build_flat_base_scan(
        snapshot,
        cache_root=tmp_path,
        completed_at_utc=COMPLETED,
        code_commit="abc1234",
    )

    assert tuple(row.computer_decision for row in batch.results) == (
        MachineDecision.YES,
        MachineDecision.NO,
        MachineDecision.NOT_EVALUATED,
    )
    assert tuple(row.source_rank for row in batch.results) == (0, 1, 2)
    assert batch.manifest.ordered_input_count == 3
    assert batch.manifest.quality_pass_count == 2
    assert batch.manifest.quality_fail_count == 1
    assert batch.manifest.yes_count == 1
    assert batch.manifest.no_count == 1
    assert batch.results[2].reason_codes == ("MISSING_CACHE",)
    assert batch.manifest.provenance["adjustment"] == "QFQ"


@pytest.mark.parametrize(
    ("kind", "completeness"),
    (
        (SnapshotKind.PREVIEW, Completeness.COMPLETE),
        (SnapshotKind.FORMAL, Completeness.INCOMPLETE),
    ),
)
def test_builder_rejects_preview_or_incomplete_snapshot(
    tmp_path: Path,
    kind: SnapshotKind,
    completeness: Completeness,
) -> None:
    from tv_quant.pattern_finder.application.scan_persistence import build_flat_base_scan

    with pytest.raises(ValueError, match="formal complete Universe Snapshot required"):
        build_flat_base_scan(
            _snapshot(("AAPL",), kind=kind, completeness=completeness),
            cache_root=tmp_path,
            completed_at_utc=COMPLETED,
            code_commit="abc1234",
        )


def test_canonical_batch_is_repeatable_and_changes_with_input(tmp_path: Path) -> None:
    from tv_quant.pattern_finder.application.scan_persistence import build_flat_base_scan

    snapshot = _snapshot(("AAPL",))
    cache = _write_cache(tmp_path, "AAPL", detected=True)
    first = build_flat_base_scan(
        snapshot, cache_root=tmp_path, completed_at_utc=COMPLETED, code_commit="abc1234"
    )
    second = build_flat_base_scan(
        snapshot, cache_root=tmp_path, completed_at_utc=COMPLETED, code_commit="abc1234"
    )
    assert first == second

    frame = pd.read_csv(cache)
    frame.loc[len(frame) - 1, "close"] = 100.75
    frame.loc[len(frame) - 1, "open"] = 100.75
    frame.to_csv(cache, index=False)
    changed = build_flat_base_scan(
        snapshot, cache_root=tmp_path, completed_at_utc=COMPLETED, code_commit="abc1234"
    )
    assert changed.scan_batch_id != first.scan_batch_id
    assert changed.input_hash != first.input_hash


def test_builder_preserves_snapshot_member_order_and_blocks_corrupt_cache(tmp_path: Path) -> None:
    from tv_quant.pattern_finder.application.scan_persistence import (
        MachineDecision,
        build_flat_base_scan,
    )

    snapshot = _snapshot(("MSFT", "AAPL"))
    (tmp_path / "MSFT_daily.csv").write_text("not,a,valid,cache\n", encoding="utf-8")
    _write_cache(tmp_path, "AAPL", detected=True)

    batch = build_flat_base_scan(
        snapshot, cache_root=tmp_path, completed_at_utc=COMPLETED, code_commit="abc1234"
    )

    assert tuple(row.symbol for row in batch.results) == ("MSFT", "AAPL")
    assert batch.results[0].computer_decision is MachineDecision.NOT_EVALUATED
    assert batch.results[0].reason_codes == ("INVALID_CACHE",)


def test_formal_member_outside_legacy_m3b_allowlist_is_still_accounted_for(
    tmp_path: Path,
) -> None:
    from tv_quant.pattern_finder.application.scan_persistence import build_flat_base_scan

    batch = build_flat_base_scan(
        _snapshot(("BOUND",)),
        cache_root=tmp_path,
        completed_at_utc=COMPLETED,
        code_commit="abc1234",
    )

    assert tuple(row.symbol for row in batch.results) == ("BOUND",)
    assert batch.results[0].reason_codes == ("MISSING_CACHE",)


def test_unreadable_cache_is_a_blocked_row_not_a_batch_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tv_quant.pattern_finder.application.scan_persistence import build_flat_base_scan

    target = _write_cache(tmp_path, "AAPL", detected=True)
    original = Path.read_bytes

    def unreadable(path: Path) -> bytes:
        if path == target:
            raise OSError("simulated read failure")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", unreadable)

    batch = build_flat_base_scan(
        _snapshot(("AAPL",)),
        cache_root=tmp_path,
        completed_at_utc=COMPLETED,
        code_commit="abc1234",
    )

    assert batch.results[0].reason_codes == ("INVALID_CACHE",)


def test_builder_persists_exact_stale_and_short_history_reasons(tmp_path: Path) -> None:
    from tv_quant.pattern_finder.application.scan_persistence import build_flat_base_scan

    stale = _frame("AAPL", detected=True).iloc[:-1]
    stale.to_csv(tmp_path / "AAPL_daily.csv", index=False)
    short = _frame("MSFT", detected=True).iloc[1:]
    short.loc[:, "ticker"] = "MSFT"
    short.to_csv(tmp_path / "MSFT_daily.csv", index=False)

    batch = build_flat_base_scan(
        _snapshot(("AAPL", "MSFT")),
        cache_root=tmp_path,
        completed_at_utc=COMPLETED,
        code_commit="abc1234",
    )

    assert batch.results[0].reason_codes == ("STALE_CACHE", "MISSING_SESSIONS")
    assert batch.results[1].reason_codes == ("INSUFFICIENT_HISTORY",)


def test_completed_batch_rejects_tampered_manifest_and_is_deeply_frozen(tmp_path: Path) -> None:
    from tv_quant.pattern_finder.application.scan_persistence import build_flat_base_scan

    _write_cache(tmp_path, "AAPL", detected=True)
    batch = build_flat_base_scan(
        _snapshot(("AAPL",)),
        cache_root=tmp_path,
        completed_at_utc=COMPLETED,
        code_commit="abc1234",
    )

    with pytest.raises(ValueError, match="manifest reconciliation"):
        replace(
            batch,
            manifest=replace(batch.manifest, ordered_input_count=2),
        )
    with pytest.raises(ValueError, match="input hash binding"):
        replace(batch, input_hash="f" * 64)
    with pytest.raises(TypeError):
        batch.results[0].features["base_length"] = 1  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        batch.scan_batch_id = "changed"  # type: ignore[misc]
