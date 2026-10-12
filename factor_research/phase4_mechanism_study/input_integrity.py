from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from .contracts import (
    ADJUSTMENT_BASIS,
    TRAIN_END,
    TRAIN_SESSIONS,
    TRAIN_START,
    DataIncompleteError,
    Phase4ContractError,
    SessionSpec,
)
from .structural_preflight import (
    EARLY_CLOSES,
    EXPECTED_AUDIT_MANIFEST_SHA256,
    EXPECTED_DATA_SHA256,
    EXPECTED_REHAB_SHA256,
    EXPECTED_TRAIN_BARS,
)
from .volatility import QualifiedData, qualify_ohlc

RAW_BASIS = "AUTYPE_NONE_RAW"
PRICE_COLUMNS = ("open", "high", "low", "close")
REHAB_COLUMNS = (
    "ex_div_date",
    "forward_adj_factor_a",
    "forward_adj_factor_b",
    "per_cash_div",
)
EXPECTED_REHAB_ROWS = (
    ("2025-09-19", 0.99723, 0.0, 1.83111),
    ("2025-12-19", 0.99705, 0.0, 1.99337),
    ("2026-03-20", 0.99727, 0.0, 1.797),
    ("2026-06-18", 0.99743, 0.0, 1.90352),
)
EXPECTED_TRAIN_AFFECTED_ROWS = (0, 4_332, 9_054, 13_890)
ANCHOR_DATE = "2026-06-17"
ANCHOR_RAW_CLOSE = 740.96
ANCHOR_ADJUSTED_CLOSE = 739.0557328


class InputIntegrityError(Phase4ContractError):
    """A fail-closed Phase 4.3.1 input-integrity violation."""


@dataclass(frozen=True)
class RehabEvent:
    ex_div_date: str
    factor_a: float
    factor_b: float
    per_cash_div: float


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_rehab_frame(frame: pd.DataFrame, *, strict_identity: bool = True) -> tuple[RehabEvent, ...]:
    if tuple(frame.columns) != REHAB_COLUMNS:
        raise InputIntegrityError("REHAB_SCHEMA_MISMATCH")
    dates = frame["ex_div_date"].astype(str)
    if dates.duplicated().any():
        raise InputIntegrityError("REHAB_DUPLICATE_EVENT")
    if not dates.is_monotonic_increasing:
        raise InputIntegrityError("REHAB_EVENT_ORDER_MISMATCH")
    numeric = frame.loc[:, REHAB_COLUMNS[1:]].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise InputIntegrityError("REHAB_NONFINITE_COEFFICIENT")
    if (numeric["forward_adj_factor_a"] <= 0).any():
        raise InputIntegrityError("REHAB_INVALID_FACTOR_A")
    events = tuple(
        RehabEvent(
            str(row.ex_div_date),
            float(row.forward_adj_factor_a),
            float(row.forward_adj_factor_b),
            float(row.per_cash_div),
        )
        for row in frame.itertuples(index=False)
    )
    if strict_identity:
        expected_dates = tuple(row[0] for row in EXPECTED_REHAB_ROWS)
        observed_dates = tuple(event.ex_div_date for event in events)
        if len(events) != len(EXPECTED_REHAB_ROWS) or set(observed_dates) != set(expected_dates):
            raise InputIntegrityError("REHAB_MISSING_EVENT")
        observed = tuple((e.ex_div_date, e.factor_a, e.factor_b, e.per_cash_div) for e in events)
        if observed != EXPECTED_REHAB_ROWS:
            raise InputIntegrityError("REHAB_FACTOR_MISMATCH")
    return events


def apply_dynamic_forward_adjustments(
    raw: pd.DataFrame,
    events: Iterable[RehabEvent],
) -> tuple[pd.DataFrame, tuple[dict[str, Any], ...]]:
    if "adjustment_basis" in raw.columns:
        raise InputIntegrityError("ALREADY_ADJUSTED_INPUT")
    if "source_adjustment_basis" not in raw.columns or not raw["source_adjustment_basis"].eq(RAW_BASIS).all():
        raise InputIntegrityError("RAW_AUTYPE_NONE_IDENTITY_REQUIRED")
    missing = sorted(set(("session_date", "time_et", *PRICE_COLUMNS)).difference(raw.columns))
    if missing:
        raise InputIntegrityError(f"RAW_OHLC_COLUMNS_MISSING:{missing}")
    adjusted = raw.copy()
    adjusted.loc[:, PRICE_COLUMNS] = adjusted.loc[:, PRICE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(adjusted.loc[:, PRICE_COLUMNS].to_numpy(dtype=float)).all():
        raise InputIntegrityError("RAW_NONFINITE_OHLC")

    audit: list[dict[str, Any]] = []
    ordered = tuple(events)
    if tuple(event.ex_div_date for event in ordered) != tuple(sorted(event.ex_div_date for event in ordered)):
        raise InputIntegrityError("REHAB_EVENT_ORDER_MISMATCH")
    for event in ordered:
        mask = adjusted["session_date"].astype(str) < event.ex_div_date
        for column in PRICE_COLUMNS:
            adjusted.loc[mask, column] = event.factor_a * adjusted.loc[mask, column] + event.factor_b
        audit.append(
            {
                "ex_div_date": event.ex_div_date,
                "factor_a": event.factor_a,
                "factor_b": event.factor_b,
                "affected_rows": int(mask.sum()),
            }
        )

    values = adjusted.loc[:, PRICE_COLUMNS].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise InputIntegrityError("ADJUSTED_INVALID_OHLC")
    if (
        (adjusted["high"] < adjusted[["open", "close", "low"]].max(axis=1))
        | (adjusted["low"] > adjusted[["open", "close", "high"]].min(axis=1))
    ).any():
        raise InputIntegrityError("ADJUSTED_INVALID_OHLC_ENVELOPE")
    adjusted["adjustment_basis"] = ADJUSTMENT_BASIS
    return adjusted, tuple(audit)


def validate_adjusted_frame(
    raw: pd.DataFrame,
    adjusted: pd.DataFrame,
    events: Iterable[RehabEvent],
    *,
    phase3_reference: pd.DataFrame | None = None,
) -> None:
    if len(raw) != len(adjusted) or not adjusted["adjustment_basis"].eq(ADJUSTMENT_BASIS).all():
        raise InputIntegrityError("ADJUSTMENT_BASIS_MISMATCH")
    expected = raw.loc[:, PRICE_COLUMNS].astype(float).copy()
    dates = raw["session_date"].astype(str)
    for event in events:
        mask = dates < event.ex_div_date
        for column in PRICE_COLUMNS:
            expected.loc[mask, column] = event.factor_a * expected.loc[mask, column] + event.factor_b
    actual_values = adjusted.loc[:, PRICE_COLUMNS].to_numpy(dtype=float)
    expected_values = expected.to_numpy(dtype=float)
    if np.array_equal(actual_values, raw.loc[:, PRICE_COLUMNS].to_numpy(dtype=float)):
        raise InputIntegrityError("LABEL_ONLY_ADJUSTMENT")
    if not np.array_equal(actual_values, expected_values):
        raise InputIntegrityError("NUMERIC_ADJUSTMENT_MISMATCH")
    if phase3_reference is not None:
        reference_values = phase3_reference.loc[:, [f"px_{column}" for column in PRICE_COLUMNS]].to_numpy(dtype=float)
        if not np.array_equal(actual_values, reference_values):
            raise InputIntegrityError("PHASE3_ADJUSTMENT_PARITY_MISMATCH")


def validate_qualified_derivations(adjusted: pd.DataFrame, qualified: QualifiedData) -> None:
    """Bind qualified prices and volatility fields to the adjusted OHLC arrays."""

    expected_bars = adjusted.reset_index(drop=True)
    actual_bars = qualified.bars.reset_index(drop=True)
    if (
        len(expected_bars) != len(actual_bars)
        or not actual_bars["session_date"].equals(expected_bars["session_date"].astype(str))
        or not actual_bars["time_et"].equals(expected_bars["time_et"].astype(str))
        or not np.array_equal(
            actual_bars.loc[:, PRICE_COLUMNS].to_numpy(dtype=float),
            expected_bars.loc[:, PRICE_COLUMNS].to_numpy(dtype=float),
        )
    ):
        raise InputIntegrityError("QUALIFIED_PRICE_BASIS_MISMATCH")

    previous_close = expected_bars.groupby("session_date", sort=False)["close"].shift(1)
    high_low = expected_bars["high"] - expected_bars["low"]
    intraday_tr = pd.concat(
        [
            high_low,
            (expected_bars["high"] - previous_close).abs(),
            (expected_bars["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1, skipna=True)
    first_bar = expected_bars.groupby("session_date", sort=False).cumcount().eq(0)
    intraday_tr.loc[first_bar] = high_low.loc[first_bar]
    intraday_atr20 = intraday_tr.shift(1).rolling(20, min_periods=20).mean()
    if not np.array_equal(
        actual_bars[["intraday_tr", "intraday_atr20"]].to_numpy(dtype=float),
        np.column_stack([intraday_tr.to_numpy(dtype=float), intraday_atr20.to_numpy(dtype=float)]),
        equal_nan=True,
    ):
        raise InputIntegrityError("INTRADAY_VOLATILITY_BASIS_MISMATCH")

    expected_daily = expected_bars.groupby("session_date", sort=False).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")
    )
    expected_daily["previous_close"] = expected_daily["close"].shift(1)
    expected_daily["daily_tr"] = pd.concat(
        [
            expected_daily["high"] - expected_daily["low"],
            (expected_daily["high"] - expected_daily["previous_close"]).abs(),
            (expected_daily["low"] - expected_daily["previous_close"]).abs(),
        ],
        axis=1,
    ).max(axis=1, skipna=False)
    expected_daily["daily_atr20"] = expected_daily["daily_tr"].shift(1).rolling(20, min_periods=20).mean()
    daily_columns = ["open", "high", "low", "close", "previous_close", "daily_tr", "daily_atr20"]
    if (
        list(qualified.daily.index.astype(str)) != list(expected_daily.index.astype(str))
        or not np.array_equal(
            qualified.daily.loc[:, daily_columns].to_numpy(dtype=float),
            expected_daily.loc[:, daily_columns].to_numpy(dtype=float),
            equal_nan=True,
        )
    ):
        raise InputIntegrityError("DAILY_VOLATILITY_BASIS_MISMATCH")


def _read_train_raw(data_path: Path) -> pd.DataFrame:
    rows: list[list[str]] = []
    with data_path.open("r", encoding="utf-8", newline="") as handle:
        header = next(csv.reader([handle.readline()]))
        if header != ["time_key", *PRICE_COLUMNS]:
            raise InputIntegrityError("OHLC_SCHEMA_MISMATCH")
        for raw_line in handle:
            session_date = raw_line.split(",", 1)[0].strip('"')[:10]
            if TRAIN_START <= session_date <= TRAIN_END:
                parsed = next(csv.reader([raw_line]))
                if len(parsed) != 5:
                    raise InputIntegrityError("OHLC_ROW_SHAPE_MISMATCH")
                rows.append(parsed)
    if len(rows) != EXPECTED_TRAIN_BARS:
        raise DataIncompleteError("DATA_INCOMPLETE: TRAIN_BAR_COUNT")
    frame = pd.DataFrame(rows, columns=["time_key", *PRICE_COLUMNS])
    frame["time_key"] = pd.to_datetime(frame["time_key"], errors="raise")
    for column in PRICE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    frame["session_date"] = frame["time_key"].dt.strftime("%Y-%m-%d")
    frame["time_et"] = frame["time_key"].dt.strftime("%H:%M")
    frame["source_adjustment_basis"] = RAW_BASIS
    return frame[["session_date", "time_et", *PRICE_COLUMNS, "source_adjustment_basis"]]


def _xnys_schedule() -> tuple[SessionSpec, ...]:
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(TRAIN_START, TRAIN_END)
    specs: list[SessionSpec] = []
    observed_early: list[str] = []
    for session in sessions:
        session_date = session.strftime("%Y-%m-%d")
        close_time = calendar.session_close(session).tz_convert("America/New_York").strftime("%H:%M")
        if close_time == "13:00":
            observed_early.append(session_date)
        elif close_time != "16:00":
            raise InputIntegrityError("UNEXPECTED_XNYS_CLOSE")
        specs.append(SessionSpec(session_date, close_time))
    if len(specs) != TRAIN_SESSIONS or tuple(observed_early) != EARLY_CLOSES:
        raise InputIntegrityError("XNYS_SCHEDULE_MISMATCH")
    return tuple(specs)


def qualify_authorized_train_repaired(
    data_path: Path,
    manifest_path: Path,
) -> tuple[QualifiedData, dict[str, Any]]:
    rehab_path = manifest_path.with_name("opend_rehab.csv")
    for path in (data_path, manifest_path, rehab_path):
        if not path.is_file():
            raise InputIntegrityError(f"REQUIRED_INPUT_MISSING:{path.name}")
    hashes = {
        "ohlc": _sha256_file(data_path),
        "audit_manifest": _sha256_file(manifest_path),
        "rehab": _sha256_file(rehab_path),
    }
    expected_hashes = {
        "ohlc": EXPECTED_DATA_SHA256,
        "audit_manifest": EXPECTED_AUDIT_MANIFEST_SHA256,
        "rehab": EXPECTED_REHAB_SHA256,
    }
    if hashes != expected_hashes:
        raise InputIntegrityError("FROZEN_DATA_HASH_MISMATCH")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract = manifest.get("query_contract", {})
    required_contract = {
        "adjustment": ADJUSTMENT_BASIS,
        "bar_type": "K_5M",
        "extended_time": False,
        "historical_autype": "NONE",
        "session": "RTH",
        "symbol": "US.SPY",
        "time_label": "America/New_York bar end",
        "start": "2025-07-01",
        "end": TRAIN_END,
    }
    if any(contract.get(key) != value for key, value in required_contract.items()):
        raise InputIntegrityError("AUDIT_CONTRACT_MISMATCH")
    declared = manifest.get("artifacts", {})
    if declared.get("opend_5m_ohlc.csv", {}).get("sha256") != hashes["ohlc"]:
        raise InputIntegrityError("OHLC_MANIFEST_HASH_MISMATCH")
    if declared.get("opend_rehab.csv", {}).get("sha256") != hashes["rehab"]:
        raise InputIntegrityError("REHAB_MANIFEST_HASH_MISMATCH")

    rehab = pd.read_csv(rehab_path)
    events = validate_rehab_frame(rehab)
    if any(event.ex_div_date > TRAIN_END for event in events):
        raise InputIntegrityError("POST_TRAIN_REHAB_EVENT_FORBIDDEN")
    raw = _read_train_raw(data_path)
    adjusted, event_audit = apply_dynamic_forward_adjustments(raw, events)

    from factor_research.phase3_edge_engine.factors import _apply_forward_adjustments

    phase3_reference = _apply_forward_adjustments(raw, rehab_path)
    validate_adjusted_frame(raw, adjusted, events, phase3_reference=phase3_reference)
    affected = tuple(item["affected_rows"] for item in event_audit)
    if affected != EXPECTED_TRAIN_AFFECTED_ROWS:
        raise InputIntegrityError("REHAB_APPLICATION_RANGE_MISMATCH")

    qualified = qualify_ohlc(
        adjusted[["session_date", "time_et", *PRICE_COLUMNS, "adjustment_basis"]],
        _xnys_schedule(),
        expected_session_count=TRAIN_SESSIONS,
    )
    validate_qualified_derivations(adjusted, qualified)
    anchor = qualified.bars.loc[qualified.bars["session_date"].eq(ANCHOR_DATE), "close"].iloc[-1]
    prior_close = qualified.daily.loc["2026-06-18", "previous_close"]
    if (
        abs(float(anchor) - ANCHOR_ADJUSTED_CLOSE) > 1e-12
        or abs(float(prior_close) - ANCHOR_ADJUSTED_CLOSE) > 1e-12
    ):
        raise InputIntegrityError("M06_PREVIOUS_CLOSE_ANCHOR_MISMATCH")

    return qualified, {
        "status": "DATA_GATE_PASS_NUMERIC_ADJUSTMENT_VERIFIED",
        "symbol": "US.SPY",
        "train_start": TRAIN_START,
        "train_end": TRAIN_END,
        "train_sessions": TRAIN_SESSIONS,
        "train_bars": EXPECTED_TRAIN_BARS,
        "source_basis": RAW_BASIS,
        "adjustment_basis": ADJUSTMENT_BASIS,
        "adjustment_formula": "price = factor_a * price + factor_b",
        "adjustment_order": "ex_div_date_ascending",
        "rehab_events": list(event_audit),
        "phase3_cross_check": "EXACT_ARRAY_MATCH",
        "m06_anchor": {
            "session_date": ANCHOR_DATE,
            "raw_close": ANCHOR_RAW_CLOSE,
            "adjusted_close": float(anchor),
        },
        "as_of_contract": {
            "rehab_snapshot_generated_at_utc": manifest.get("generated_at_utc"),
            "meaning": "FROZEN_RETROSPECTIVE_FINAL_BASIS_THROUGH_TRAIN_END",
            "post_train_rehab_events": 0,
            "future_bar_access": False,
            "pre_train_price_warmup": False,
        },
        "input_hashes": hashes,
        "validation_oos_accessed": False,
    }
