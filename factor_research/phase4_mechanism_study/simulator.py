from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .contracts import PRIMARY_COST, DataIncompleteError, Phase4ContractError
from .mechanisms import ScanResult, Signal
from .volatility import QualifiedData


@dataclass(frozen=True)
class ReplayResult:
    hypothesis_id: str
    session_date: str
    signal_time_et: str | None
    signal_bar_in_session: int | None
    direction: int | None
    status: str
    cancellation_reason: str | None
    entry_price: float | None
    stop_price: float | None
    target_price: float | None
    exit_reason_stop_first: str | None
    exit_price_stop_first: float | None
    exit_reason_target_first: str | None
    exit_price_target_first: float | None
    gross_return_stop_first: float | None
    gross_return_target_first: float | None
    net_return_4bp_stop_first: float | None


def _cancel(signal: Signal, reason: str, *, entry: float | None = None, target: float | None = None) -> ReplayResult:
    return ReplayResult(
        signal.hypothesis_id,
        signal.session_date,
        signal.signal_time_et,
        signal.bar_in_session,
        signal.direction,
        "SIGNAL_CANCELED",
        reason,
        entry,
        signal.stop_price,
        target,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )


def _hit(bar, direction: int, stop: float, target: float) -> tuple[bool, bool]:
    if direction == 1:
        return float(bar["low"]) <= stop, float(bar["high"]) >= target
    return float(bar["high"]) >= stop, float(bar["low"]) <= target


def _open_hit(open_price: float, direction: int, stop: float, target: float) -> tuple[bool, bool]:
    if direction == 1:
        return open_price <= stop, open_price >= target
    return open_price >= stop, open_price <= target


def _path_exit(future, direction: int, stop: float, target: float, *, stop_first: bool) -> tuple[float, str]:
    for _, bar in future.iterrows():
        open_price = float(bar["open"])
        open_stop, open_target = _open_hit(open_price, direction, stop, target)
        if open_stop:
            return open_price, "GAP_STOP"
        if open_target:
            return target, "GAP_TARGET_CAPPED"
        stop_hit, target_hit = _hit(bar, direction, stop, target)
        if stop_hit and target_hit:
            return (stop, "STOP_SAME_BAR") if stop_first else (target, "TARGET_SAME_BAR")
        if stop_hit:
            return stop, "STOP"
        if target_hit:
            return target, "TARGET"
    return float(future.iloc[-1]["close"]), "TIME"


def replay_signal(data: QualifiedData, signal: Signal) -> ReplayResult:
    if data.data_gate_status != "PASS":
        raise DataIncompleteError("DATA_INCOMPLETE: DATA_GATE_NOT_PASS")
    day = data.session(signal.session_date).reset_index(drop=True)
    if signal.bar_in_session >= len(day) or int(day.iloc[signal.bar_in_session]["global_pos"]) != signal.global_pos:
        raise Phase4ContractError("SIGNAL_DATA_IDENTITY_MISMATCH")
    entry_pos = signal.bar_in_session + 1
    end_pos = entry_pos + signal.holding_bars
    if end_pos > len(day):
        raise DataIncompleteError("DATA_INCOMPLETE: REQUIRED_FUTURE_BAR")
    future = day.iloc[entry_pos:end_pos]
    expected_global = np.arange(signal.global_pos + 1, signal.global_pos + 1 + signal.holding_bars)
    if len(future) != signal.holding_bars or not np.array_equal(future["global_pos"].to_numpy(), expected_global):
        raise DataIncompleteError("DATA_INCOMPLETE: REQUIRED_FUTURE_BAR")
    entry = float(future.iloc[0]["open"])
    direction = signal.direction
    stop = float(signal.stop_price)
    if signal.target_kind == "FIXED_PRICE":
        target = float(signal.target_value)
    elif signal.target_kind == "ENTRY_R_MULTIPLE":
        risk = direction * (entry - stop)
        target = entry + direction * float(signal.target_value) * risk
    else:
        raise Phase4ContractError("UNKNOWN_TARGET_KIND")
    if direction not in (-1, 1) or direction * (entry - stop) <= 0:
        return _cancel(signal, "INVALID_STOP_GEOMETRY", entry=entry, target=target)
    target_distance = direction * (target - entry)
    if target_distance <= 0:
        reason = "GAP_TARGET_ALREADY_CROSSED" if signal.hypothesis_id == "P4_M06_ALL" else "INVALID_TARGET_GEOMETRY"
        return _cancel(signal, reason, entry=entry, target=target)
    if target_distance / entry <= PRIMARY_COST + 1e-12:
        return _cancel(signal, "NON_POSITIVE_NET_TARGET", entry=entry, target=target)

    stop_price, stop_reason = _path_exit(future, direction, stop, target, stop_first=True)
    target_price, target_reason = _path_exit(future, direction, stop, target, stop_first=False)
    gross_stop = direction * (stop_price - entry) / entry
    gross_target = direction * (target_price - entry) / entry
    return ReplayResult(
        signal.hypothesis_id,
        signal.session_date,
        signal.signal_time_et,
        signal.bar_in_session,
        direction,
        "TRADE_COMPLETED",
        None,
        entry,
        stop,
        target,
        stop_reason,
        stop_price,
        target_reason,
        target_price,
        gross_stop,
        gross_target,
        gross_stop - PRIMARY_COST,
    )


def replay_scan(data: QualifiedData, scan: ScanResult) -> ReplayResult:
    if scan.signal is not None:
        return replay_signal(data, scan.signal)
    return ReplayResult(
        scan.hypothesis_id,
        scan.session_date,
        None,
        None,
        None,
        scan.status,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )
