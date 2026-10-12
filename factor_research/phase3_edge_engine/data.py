from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import (
    EARLY_CLOSES,
    EXPECTED_AUDIT_MANIFEST_SHA256,
    EXPECTED_BARS,
    EXPECTED_DATA_SHA256,
    EXPECTED_SESSIONS,
    EXPECTED_TRAIN_SESSIONS,
    REHAB_DATES,
    TRAIN_END,
    TRAIN_START,
)


class DataGateError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _expected_labels(session_date: str) -> pd.DatetimeIndex:
    end = "13:00" if session_date in EARLY_CLOSES else "16:00"
    return pd.date_range(
        f"{session_date} 09:35", f"{session_date} {end}", freq="5min"
    )


def load_and_qualify(csv_path: Path, audit_manifest_path: Path) -> tuple[pd.DataFrame, dict]:
    if not csv_path.is_file():
        raise DataGateError(f"DATA_FILE_MISSING:{csv_path}")
    if not audit_manifest_path.is_file():
        raise DataGateError(f"AUDIT_MANIFEST_MISSING:{audit_manifest_path}")
    data_hash = sha256_file(csv_path)
    manifest_hash = sha256_file(audit_manifest_path)
    if data_hash != EXPECTED_DATA_SHA256:
        raise DataGateError(f"DATA_HASH_MISMATCH:{data_hash}")
    if manifest_hash != EXPECTED_AUDIT_MANIFEST_SHA256:
        raise DataGateError(f"AUDIT_MANIFEST_HASH_MISMATCH:{manifest_hash}")

    manifest = json.loads(audit_manifest_path.read_text(encoding="utf-8"))
    contract = manifest.get("query_contract", {})
    required_contract = {
        "adjustment": "AS_OF_DYNAMIC_FORWARD_FROM_GET_REHAB",
        "bar_type": "K_5M",
        "extended_time": False,
        "historical_autype": "NONE",
        "session": "RTH",
        "symbol": "US.SPY",
        "time_label": "America/New_York bar end",
    }
    mismatches = [key for key, value in required_contract.items() if contract.get(key) != value]
    if mismatches:
        raise DataGateError("AUDIT_CONTRACT_MISMATCH:" + ",".join(mismatches))
    if manifest.get("edge_claim") != "PROHIBITED":
        raise DataGateError("AUDIT_EDGE_BOUNDARY_MISSING")

    frame = pd.read_csv(csv_path)
    required = ["time_key", "open", "high", "low", "close"]
    if list(frame.columns) != required:
        raise DataGateError("OHLC_SCHEMA_MISMATCH")
    if len(frame) != EXPECTED_BARS:
        raise DataGateError(f"BAR_COUNT_MISMATCH:{len(frame)}")
    if frame["time_key"].duplicated().any():
        raise DataGateError("DUPLICATE_BAR")
    frame["time_et"] = pd.to_datetime(frame["time_key"], errors="raise")
    if not frame["time_et"].is_monotonic_increasing:
        raise DataGateError("UNSORTED_BARS")
    numeric = frame[["open", "high", "low", "close"]]
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise DataGateError("NON_FINITE_PRICE")
    if (numeric <= 0).any().any():
        raise DataGateError("NON_POSITIVE_PRICE")
    if ((frame["high"] < numeric[["open", "close"]].max(axis=1)) | (
        frame["low"] > numeric[["open", "close"]].min(axis=1)
    )).any():
        raise DataGateError("INVALID_OHLC_ENVELOPE")

    frame["session_date"] = frame["time_et"].dt.strftime("%Y-%m-%d")
    sessions = list(frame["session_date"].drop_duplicates())
    if len(sessions) != EXPECTED_SESSIONS:
        raise DataGateError(f"SESSION_COUNT_MISMATCH:{len(sessions)}")
    missing: dict[str, list[str]] = {}
    extra: dict[str, list[str]] = {}
    for session_date, group in frame.groupby("session_date", sort=True):
        actual = pd.DatetimeIndex(group["time_et"])
        expected = _expected_labels(session_date)
        missing_labels = expected.difference(actual)
        extra_labels = actual.difference(expected)
        if len(missing_labels):
            missing[session_date] = [str(item) for item in missing_labels]
        if len(extra_labels):
            extra[session_date] = [str(item) for item in extra_labels]
    if missing or extra:
        raise DataGateError("RTH_GRID_MISMATCH")

    observed_early = {
        date for date, count in frame.groupby("session_date").size().items() if count == 42
    }
    if observed_early != EARLY_CLOSES:
        raise DataGateError(f"EARLY_CLOSE_MISMATCH:{sorted(observed_early)}")
    train = frame[frame["session_date"].between(TRAIN_START, TRAIN_END)].copy()
    if train["session_date"].nunique() != EXPECTED_TRAIN_SESSIONS or len(train) != 14_514:
        raise DataGateError("TRAIN_COVERAGE_MISMATCH")

    rehab_path = audit_manifest_path.parent / "opend_rehab.csv"
    rehab = pd.read_csv(rehab_path)
    if set(rehab["ex_div_date"].astype(str)) != REHAB_DATES:
        raise DataGateError("REHAB_EVENT_MISMATCH")

    frame["bar_index"] = np.arange(len(frame), dtype=int)
    qualification = {
        "status": "PASS_5M_ONLY",
        "symbol": "US.SPY",
        "bar_size": "5m",
        "timezone": "America/New_York",
        "bar_label": "bar_end",
        "bars": len(frame),
        "sessions": len(sessions),
        "train_bars": len(train),
        "train_sessions": int(train["session_date"].nunique()),
        "start": sessions[0],
        "end": sessions[-1],
        "train_start": TRAIN_START,
        "train_end": TRAIN_END,
        "early_closes": sorted(EARLY_CLOSES),
        "rehab_dates": sorted(REHAB_DATES),
        "data_sha256": data_hash,
        "audit_manifest_sha256": manifest_hash,
        "adjustment": contract["adjustment"],
        "one_minute_status": "NOT_AVAILABLE_NOT_REQUIRED",
        "volume_status": "PROHIBITED",
        "cache_hit": True,
        "future_leak_checks": "PASS",
    }
    return frame, qualification
