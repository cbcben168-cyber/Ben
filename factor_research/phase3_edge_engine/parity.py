from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .data import sha256_file


RUNLOG_MARKER = "FUTU_FACTOR_STRATEGY_V3_1_1|"
EXPECTED_V311_RUNLOG_SHA256 = "6523875e998a79f17a1047937f70dbe2b383486caa50d53d91e70a1183acd840"
PRICE_ABS_TOLERANCE = 1e-9
RETURN_ABS_TOLERANCE = 1e-12
BASE_VARIANTS = {"S01_BASE", "S02_BASE", "S03_BASE"}


def _iso_second(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%dT%H:%M:%S")


def _direction(value: Any) -> str:
    if value in (1, "1", "LONG"):
        return "LONG"
    if value in (-1, "-1", "SHORT"):
        return "SHORT"
    return str(value)


def _key(strategy_id: Any, signal_time: Any, direction: Any) -> tuple[str, str, str]:
    return str(strategy_id), _iso_second(signal_time), _direction(direction)


def _canonical_id(key: tuple[str, str, str]) -> str:
    return "|".join(key)


def _records_by_key(records: list[dict], source: str) -> tuple[dict[tuple[str, str, str], dict], list[str]]:
    result: dict[tuple[str, str, str], dict] = {}
    duplicates: list[str] = []
    for record in records:
        key = _key(record["strategy_id"], record["signal_time_et"], record["direction"])
        if key in result:
            duplicates.append(_canonical_id(key))
            continue
        result[key] = record
    return result, [f"{source}:{item}" for item in duplicates]


def _load_runlog(path: Path) -> tuple[dict[str, list[dict]], int]:
    events: dict[str, list[dict]] = {
        "STRATEGY_SIGNAL_EVENT": [],
        "TRADE_EVENT": [],
        "ENTRY_REJECTED": [],
    }
    parse_errors = 0
    with path.open("r", encoding="utf-8-sig", errors="strict") as handle:
        for line in handle:
            if RUNLOG_MARKER not in line:
                continue
            try:
                payload = json.loads(line.split(RUNLOG_MARKER, 1)[1].strip())
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            event_type = payload.get("event_type")
            if event_type in events:
                events[event_type].append(payload)
    return events, parse_errors


def _normalize_price(value: Any, session_date: str, rehab: pd.DataFrame) -> float:
    result = float(value)
    for row in rehab.sort_values("ex_div_date").itertuples(index=False):
        if str(session_date) < str(row.ex_div_date):
            result = float(row.forward_adj_factor_a) * result + float(row.forward_adj_factor_b)
    return result


def _abs_diff(left: Any, right: Any) -> float:
    if left is None or right is None or pd.isna(left) or pd.isna(right):
        return 0.0 if (left is None or pd.isna(left)) and (right is None or pd.isna(right)) else np.inf
    return abs(float(left) - float(right))


def _normalized_exit_reason(raw: dict) -> str:
    if bool(raw.get("ambiguous")) and raw.get("exit_reason") == "STOP":
        return "AMBIGUOUS_STOP_FIRST"
    return str(raw.get("exit_reason"))


def audit_trade_parity(
    runlog_path: Path,
    rehab_path: Path,
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    signal_audit: pd.DataFrame,
) -> tuple[dict, pd.DataFrame]:
    errors: list[str] = []
    if not runlog_path.is_file():
        return {
            "status": "PARITY_FAIL",
            "errors": [f"RUNLOG_MISSING:{runlog_path}"],
            "price_abs_tolerance": PRICE_ABS_TOLERANCE,
            "return_abs_tolerance": RETURN_ABS_TOLERANCE,
        }, pd.DataFrame()
    runlog_hash = sha256_file(runlog_path)
    if runlog_hash != EXPECTED_V311_RUNLOG_SHA256:
        return {
            "status": "PARITY_FAIL",
            "errors": [f"RUNLOG_HASH_MISMATCH:{runlog_hash}"],
            "source_file": runlog_path.name,
            "source_sha256": runlog_hash,
            "price_abs_tolerance": PRICE_ABS_TOLERANCE,
            "return_abs_tolerance": RETURN_ABS_TOLERANCE,
        }, pd.DataFrame()

    events, parse_errors = _load_runlog(runlog_path)
    if parse_errors:
        errors.append(f"RUNLOG_JSON_PARSE_ERRORS:{parse_errors}")
    raw_signals, duplicate_errors = _records_by_key(events["STRATEGY_SIGNAL_EVENT"], "RAW_SIGNAL")
    errors.extend(duplicate_errors)
    raw_trades, duplicate_errors = _records_by_key(events["TRADE_EVENT"], "RAW_TRADE")
    errors.extend(duplicate_errors)
    raw_rejects, duplicate_errors = _records_by_key(events["ENTRY_REJECTED"], "RAW_REJECT")
    errors.extend(duplicate_errors)

    offline_signal_records = signals.to_dict("records")
    offline_signals, duplicate_errors = _records_by_key(offline_signal_records, "OFFLINE_SIGNAL")
    errors.extend(duplicate_errors)
    baseline_trades = trades[trades["variant_id"].isin(BASE_VARIANTS)].to_dict("records")
    offline_trades, duplicate_errors = _records_by_key(baseline_trades, "OFFLINE_TRADE")
    errors.extend(duplicate_errors)
    baseline_audit = signal_audit[signal_audit["variant_id"].isin(BASE_VARIANTS)].to_dict("records")
    offline_decisions, duplicate_errors = _records_by_key(baseline_audit, "OFFLINE_DECISION")
    errors.extend(duplicate_errors)
    raw_decisions = {
        **{key: {**record, "decision": "TRADED"} for key, record in raw_trades.items()},
        **{key: {**record, "decision": record.get("reason")} for key, record in raw_rejects.items()},
    }
    if set(raw_trades) & set(raw_rejects):
        errors.append("RAW_TRADE_REJECTION_IDENTITY_OVERLAP")

    expected_counts = {
        "signals": 1_593,
        "trades": 1_072,
        "rejections": 521,
    }
    observed_counts = {
        "raw_signals": len(raw_signals),
        "offline_signals": len(offline_signals),
        "raw_trades": len(raw_trades),
        "offline_trades": len(offline_trades),
        "raw_rejections": len(raw_rejects),
        "offline_decisions": len(offline_decisions),
    }
    if len(raw_signals) != expected_counts["signals"] or len(offline_signals) != expected_counts["signals"]:
        errors.append("SIGNAL_COUNT_MISMATCH")
    if len(raw_trades) != expected_counts["trades"] or len(offline_trades) != expected_counts["trades"]:
        errors.append("TRADE_COUNT_MISMATCH")
    if len(raw_rejects) != expected_counts["rejections"]:
        errors.append("REJECTION_COUNT_MISMATCH")

    rehab = pd.read_csv(rehab_path)
    detail_rows: list[dict] = []
    all_keys = sorted(set(raw_signals) | set(offline_signals) | set(raw_decisions) | set(offline_decisions))
    max_diffs = {
        "signal_price": 0.0,
        "entry_price": 0.0,
        "exit_price": 0.0,
        "stop_price": 0.0,
        "target_price": 0.0,
        "gross_return": 0.0,
        "net_return": 0.0,
    }
    ambiguous_reason_normalizations = 0
    for key in all_keys:
        raw_signal = raw_signals.get(key)
        offline_signal = offline_signals.get(key)
        raw_decision = raw_decisions.get(key)
        offline_decision = offline_decisions.get(key)
        row_errors: list[str] = []
        if raw_signal is None or offline_signal is None:
            row_errors.append("SIGNAL_IDENTITY_MISMATCH")
        if raw_decision is None or offline_decision is None:
            row_errors.append("DECISION_IDENTITY_MISMATCH")
        if raw_signal is not None and raw_decision is not None:
            if str(raw_signal.get("signal_id")) != str(raw_decision.get("signal_id")):
                row_errors.append("RAW_SIGNAL_ID_CHAIN_MISMATCH")
        if offline_signal is not None and offline_decision is not None:
            if str(offline_signal.get("signal_id")) != str(offline_decision.get("signal_id")):
                row_errors.append("OFFLINE_SIGNAL_ID_CHAIN_MISMATCH")
        decision_raw = raw_decision.get("decision") if raw_decision else None
        decision_offline = offline_decision.get("decision") if offline_decision else None
        if decision_raw != decision_offline:
            row_errors.append("DECISION_MISMATCH")

        session_date = key[1][:10]
        signal_price_diff = np.nan
        if raw_signal is not None and offline_signal is not None:
            signal_price_diff = _abs_diff(
                offline_signal.get("signal_close"),
                _normalize_price(raw_signal.get("signal_price"), session_date, rehab),
            )
            max_diffs["signal_price"] = max(max_diffs["signal_price"], signal_price_diff)
            if signal_price_diff > PRICE_ABS_TOLERANCE:
                row_errors.append("SIGNAL_PRICE_MISMATCH")

        raw_trade = raw_trades.get(key)
        offline_trade = offline_trades.get(key)
        trade_diffs: dict[str, float] = {}
        if decision_raw == "TRADED" or decision_offline == "TRADED":
            if raw_trade is None or offline_trade is None:
                row_errors.append("TRADE_IDENTITY_MISMATCH")
            else:
                for field in ("entry_time_et", "entry_observed_at_et", "exit_time_et"):
                    if _iso_second(raw_trade.get(field)) != _iso_second(offline_trade.get(field)):
                        row_errors.append(field.upper() + "_MISMATCH")
                price_pairs = {
                    "entry_price": (offline_trade.get("entry_price"), raw_trade.get("entry_price")),
                    "exit_price": (offline_trade.get("exit_price"), raw_trade.get("exit_price")),
                    "stop_price": (offline_trade.get("stop_price"), raw_trade.get("stop")),
                    "target_price": (offline_trade.get("target_price"), raw_trade.get("target")),
                }
                for field, (offline_value, raw_value) in price_pairs.items():
                    diff = _abs_diff(offline_value, _normalize_price(raw_value, session_date, rehab))
                    trade_diffs[field] = diff
                    max_diffs[field] = max(max_diffs[field], diff)
                    if diff > PRICE_ABS_TOLERANCE:
                        row_errors.append(field.upper() + "_MISMATCH")
                for field in ("gross_return", "net_return"):
                    diff = _abs_diff(offline_trade.get(field), raw_trade.get(field))
                    trade_diffs[field] = diff
                    max_diffs[field] = max(max_diffs[field], diff)
                    if diff > RETURN_ABS_TOLERANCE:
                        row_errors.append(field.upper() + "_MISMATCH")
                cost_diff = _abs_diff(
                    offline_trade.get("cost_bps"),
                    2.0 * float(raw_trade.get("cost_bps_per_side")),
                )
                trade_diffs["cost_bps"] = cost_diff
                if cost_diff > RETURN_ABS_TOLERANCE:
                    row_errors.append("COST_MISMATCH")
                normalized_reason = _normalized_exit_reason(raw_trade)
                if normalized_reason != str(raw_trade.get("exit_reason")):
                    ambiguous_reason_normalizations += 1
                if str(offline_trade.get("exit_reason")) != normalized_reason:
                    row_errors.append("EXIT_REASON_MISMATCH")

        if row_errors:
            errors.extend(f"{_canonical_id(key)}:{item}" for item in row_errors)
        detail_rows.append({
            "canonical_signal_id": _canonical_id(key),
            "strategy_id": key[0],
            "signal_time_et": key[1],
            "direction": key[2],
            "offline_signal_id": offline_signal.get("signal_id") if offline_signal else "",
            "raw_signal_id": raw_signal.get("signal_id") if raw_signal else "",
            "decision_offline": decision_offline or "",
            "decision_raw": decision_raw or "",
            "signal_price_abs_diff": signal_price_diff,
            "entry_price_abs_diff": trade_diffs.get("entry_price", np.nan),
            "exit_price_abs_diff": trade_diffs.get("exit_price", np.nan),
            "stop_price_abs_diff": trade_diffs.get("stop_price", np.nan),
            "target_price_abs_diff": trade_diffs.get("target_price", np.nan),
            "gross_return_abs_diff": trade_diffs.get("gross_return", np.nan),
            "net_return_abs_diff": trade_diffs.get("net_return", np.nan),
            "cost_bps_abs_diff": trade_diffs.get("cost_bps", np.nan),
            "status": "PARITY_FAIL" if row_errors else "MATCH",
            "differences": ";".join(row_errors),
        })

    detail = pd.DataFrame(detail_rows)
    summary = {
        "status": "TRADE_PARITY_PASS" if not errors else "PARITY_FAIL",
        "errors": errors,
        "source_file": runlog_path.name,
        "source_bytes": runlog_path.stat().st_size,
        "source_sha256": runlog_hash,
        "stable_identity": "strategy_id|signal_time_et|direction",
        "price_basis": "FINAL_FORWARD_ADJUSTED",
        "price_abs_tolerance": PRICE_ABS_TOLERANCE,
        "return_abs_tolerance": RETURN_ABS_TOLERANCE,
        "expected_counts": expected_counts,
        "observed_counts": observed_counts,
        "matched_signals": int((detail["status"] == "MATCH").sum()),
        "matched_trades": len(set(raw_trades) & set(offline_trades)),
        "matched_rejections": len(set(raw_rejects) & set(offline_decisions)),
        "max_abs_differences": max_diffs,
        "ambiguous_reason_normalizations": ambiguous_reason_normalizations,
        "allowed_differences": [
            "signal_id encoding differs; canonical stable identity must match one-to-one",
            "raw prices use as-of dynamic basis and are converted to the frozen final forward-adjusted basis",
            "raw STOP plus ambiguous=true maps to AMBIGUOUS_STOP_FIRST",
            "MFE/MAE are excluded because the frozen RunLog records full exit-bar range upper bounds",
        ],
    }
    return summary, detail
