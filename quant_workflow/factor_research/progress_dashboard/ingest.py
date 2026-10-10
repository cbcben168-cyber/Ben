from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import re
import threading
from typing import Any

from .db import Database, utc_now


MARKER = "FUTU_FACTOR_V1|"
BATCH_MARKER = "FUTU_FACTOR_BATCH_V1|"
LEGACY_MARKER = "SPY_FACTOR_V1|"
LEGACY_STRATEGY_HASH = "137abf998ac16210d7185bcae3b6c96d77c0fe75344af33d3ac73a6675f28bc3"
MAX_FILE_BYTES = 50 * 1024 * 1024
REQUIRED_COMMON = {
    "contract_version",
    "event_type",
    "factor_id",
    "run_id",
    "strategy_version",
    "strategy_hash",
    "parameter_version",
    "symbol",
    "timeframe",
    "session",
    "select",
    "timezone",
}
BATCH_REQUIRED_COMMON = {
    "contract_version",
    "event_type",
    "batch_id",
    "run_id",
    "strategy_version",
    "strategy_hash",
    "parameter_version",
    "symbol",
    "timeframe",
    "session",
    "select",
    "timezone",
}
BATCH_DEFINITION_HASH = "370c846144bf3e184642acd4a55c97976c75c377073a74f43aa001fef758be23"
BATCH_FACTORS = (
    ("SPY_F001_CLOSE_GT_EMA20", "f001", "F001-C1-BATCH-V1"),
    ("SPY_F002_EMA20_RISING_3", "f002", "F002-C1-BATCH-V1"),
    ("SPY_F003_CLOSE_CROSS_ABOVE_EMA20", "f003", "F003-C1-BATCH-V1"),
    ("SPY_F004_CLOSE_BREAKS_PRIOR_5_HIGH", "f004", "F004-C1-BATCH-V1"),
    ("SPY_F005_THREE_CLOSE_MOMENTUM", "f005", "F005-C1-BATCH-V1"),
    ("SPY_F006_STRONG_BULL_BODY", "f006", "F006-C1-BATCH-V1"),
)
BATCH_FACTOR_IDS = ",".join(item[0] for item in BATCH_FACTORS)
BATCH_CONFIGS = {
    "FUTU_BATCH_FACTORS_V1": {
        "partition": "FUNCTIONAL_VALIDATION",
        "batch_parameter_version": "C1-SIX-FACTOR-S0-V1",
        "factor_parameter_versions": {
            factor_id: parameter_version
            for factor_id, _, parameter_version in BATCH_FACTORS
        },
    },
    "FUTU_BATCH_FACTORS_TRAIN_V1": {
        "partition": "TRAIN",
        "batch_parameter_version": "C1-SIX-FACTOR-TRAIN-20251001-20260630-V1",
        "factor_parameter_versions": {
            factor_id: parameter_version.replace("-V1", "-TRAIN-V1")
            for factor_id, _, parameter_version in BATCH_FACTORS
        },
    },
}
TRAIN_START = "2025-10-01"
TRAIN_END = "2026-06-30"
TRAIN_SYSTEM_START = "2025-07-01"
TRAIN_SENSITIVITY_START = "2025-09-02"
TRAIN_EXPECTED_SESSIONS = 187
TRAIN_EXPECTED_EVENTS = 12083
TRAIN_EXPECTED_LABELS = 36249
TRAIN_EXPECTED_WARMUP_BARS = 4956
TRAIN_EARLY_CLOSE_DAYS = {"2025-11-28", "2025-12-24"}
TRAIN_HOLIDAYS = {
    "2025-11-27",
    "2025-12-25",
    "2026-01-01",
    "2026-01-19",
    "2026-02-16",
    "2026-04-03",
    "2026-05-25",
    "2026-06-19",
}
FACTOR_MARKER_RE = re.compile(r"FUTU_FACTOR_[A-Z0-9_]+\|")
SYSTEM_LOG_TIME_RE = re.compile(r"^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})")


def expected_train_sessions() -> set[str]:
    current = datetime.strptime(TRAIN_START, "%Y-%m-%d").date()
    end = datetime.strptime(TRAIN_END, "%Y-%m-%d").date()
    sessions: set[str] = set()
    while current <= end:
        text = current.isoformat()
        if current.weekday() < 5 and text not in TRAIN_HOLIDAYS:
            sessions.add(text)
        current += timedelta(days=1)
    return sessions


@dataclass
class ParseResult:
    classification: str
    import_status: str
    encoding: str
    marker_version: str | None
    rows_total: int
    rows_marked: int
    parsed_rows: int
    run: dict[str, Any] | None = None
    error: str | None = None
    system_log_start_local: str | None = None
    system_log_end_local: str | None = None

    @property
    def success_rate(self) -> float | None:
        if not self.rows_marked:
            return None
        return self.parsed_rows / self.rows_marked


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def decode_csv(path: Path) -> tuple[str, str]:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("FILE_TOO_LARGE")
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("UNSUPPORTED_ENCODING")


def _system_log_lifecycle(text: str) -> tuple[str | None, str | None]:
    timestamps: list[datetime] = []
    for line in text.splitlines():
        match = SYSTEM_LOG_TIME_RE.match(line)
        if match:
            try:
                timestamps.append(datetime.strptime(match.group(1), "%Y/%m/%d %H:%M:%S"))
            except ValueError:
                continue
    if not timestamps:
        return None, None
    return min(timestamps).isoformat(), max(timestamps).isoformat()


def _attach_system_log_lifecycle(result: ParseResult, text: str) -> ParseResult:
    result.system_log_start_local, result.system_log_end_local = _system_log_lifecycle(text)
    return result


def _decode_factor_marker_line(
    line: str, decoder: json.JSONDecoder
) -> tuple[str, dict[str, Any]] | None:
    marker_match = FACTOR_MARKER_RE.search(line)
    if not marker_match:
        return None

    version = marker_match.group(0)[:-1]
    payload_text = line[marker_match.end() :].lstrip()
    try:
        payload, _ = decoder.raw_decode(payload_text)
    except json.JSONDecodeError:
        row = next(csv.reader([line]))
        combined = ",".join(row)
        csv_marker_match = FACTOR_MARKER_RE.search(combined)
        if not csv_marker_match:
            raise ValueError("MARKER_LOST_DURING_CSV_FALLBACK")
        version = csv_marker_match.group(0)[:-1]
        payload_text = combined[csv_marker_match.end() :].lstrip()
        payload, _ = decoder.raw_decode(payload_text)

    if not isinstance(payload, dict):
        raise ValueError("PAYLOAD_NOT_OBJECT")
    return version, payload


def _parse_time(value: Any, field: str) -> datetime:
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"INVALID_TIMESTAMP:{field}") from exc


def _required(payload: dict[str, Any], fields: set[str]) -> None:
    missing = sorted(field for field in fields if payload.get(field) in (None, ""))
    if missing:
        raise ValueError("MISSING_FIELDS:" + ",".join(missing))


def _legacy_fields(combined: str) -> dict[str, str]:
    payload = combined.split(LEGACY_MARKER, 1)[1]
    fields: dict[str, str] = {}
    for part in payload.split("|"):
        if "=" not in part:
            raise ValueError("LEGACY_FIELD_WITHOUT_EQUALS")
        key, value = part.split("=", 1)
        if not key or key in fields:
            raise ValueError("LEGACY_DUPLICATE_OR_EMPTY_FIELD")
        fields[key] = value.strip()
    return fields


def _parse_legacy_runlog(text: str, encoding: str) -> ParseResult:
    rows_total = 0
    rows_marked = 0
    records: list[dict[str, str]] = []
    try:
        for row in csv.reader(io.StringIO(text)):
            rows_total += 1
            combined = ",".join(row)
            if LEGACY_MARKER not in combined:
                continue
            rows_marked += 1
            records.append(_legacy_fields(combined))
    except (csv.Error, ValueError) as exc:
        return ParseResult(
            "LEGACY_F001_RUN",
            "PARSE_FAILED",
            encoding,
            "SPY_FACTOR_V1",
            rows_total,
            rows_marked,
            len(records),
            error=str(exc),
        )

    starts = [item for item in records if item.get("record") == "START"]
    if len(starts) != 1:
        return ParseResult(
            "LEGACY_F001_RUN",
            "PARSE_FAILED",
            encoding,
            "SPY_FACTOR_V1",
            rows_total,
            rows_marked,
            len(records),
            error=f"LEGACY_START_COUNT:{len(starts)}",
        )
    start = starts[0]
    expected_start = {
        "version": "1",
        "run_phase": "FUNCTIONAL_VALIDATION",
        "date_start_et": "2026-09-28",
        "date_end_et": "2026-10-06",
        "bar_type": "K_5M",
        "select": "2",
        "session": "RTH",
        "factor": "CLOSE_GT_EMA20",
        "horizons_bars": "3,6,12",
        "orders_enabled": "False",
        "volume_enabled": "False",
        "edge_claim": "PROHIBITED",
    }
    mismatches = [
        key for key, expected in expected_start.items() if start.get(key) != expected
    ]
    fatal = bool(mismatches)
    issues: list[dict[str, str]] = []
    if mismatches:
        issues.append(
            {
                "code": "LEGACY_START_CONTRACT_MISMATCH",
                "severity": "ERROR",
                "message": "旧版日志起始契约不匹配：" + ",".join(mismatches),
            }
        )

    signals: list[dict[str, Any]] = []
    signal_map: dict[str, dict[str, Any]] = {}
    for event in (item for item in records if item.get("record") == "EVENT"):
        try:
            _required(
                event,
                {
                    "event_id",
                    "session_date_et",
                    "trigger_et",
                    "trigger_utc",
                    "symbol",
                    "bar_type",
                    "select",
                    "session",
                    "close",
                    "ema20",
                    "factor_state",
                    "horizons_bars",
                },
            )
            signal_id = event["event_id"]
            if signal_id in signal_map:
                raise ValueError("DUPLICATE_SIGNAL_ID")
            if (
                event["symbol"] != "US.SPY"
                or event["bar_type"] != "K_5M"
                or event["select"] != "2"
                or event["session"] != "RTH"
                or event["horizons_bars"] != "3,6,12"
            ):
                raise ValueError("LEGACY_SIGNAL_IDENTITY_MISMATCH")
            signal_time = _parse_time(event["trigger_et"], "trigger_et")
            _parse_time(event["trigger_utc"], "trigger_utc")
            minute = signal_time.hour * 60 + signal_time.minute
            if minute < 575 or minute > 895 or minute % 5:
                raise ValueError("SIGNAL_OUTSIDE_RTH_GRID")
            signal_close = float(event["close"])
            ema20 = float(event["ema20"])
            expected_state = "PASS" if signal_close > ema20 else "FAIL"
            if signal_close <= 0 or ema20 <= 0 or event["factor_state"] != expected_state:
                raise ValueError("LEGACY_FACTOR_RECALCULATION_MISMATCH")
            signal = {
                "signal_id": signal_id,
                "signal_time_et": event["trigger_et"],
                "signal_time_utc": event["trigger_utc"],
                "signal_close": signal_close,
                "factor_value": event["factor_state"],
                "factor_numeric": ema20,
            }
            signals.append(signal)
            signal_map[signal_id] = signal
        except (TypeError, ValueError) as exc:
            fatal = True
            issues.append(
                {"code": "INVALID_LEGACY_SIGNAL", "severity": "ERROR", "message": str(exc)}
            )

    labels: list[dict[str, Any]] = []
    seen_labels: set[tuple[str, int]] = set()
    horizon_map = {3: 15, 6: 30, 12: 60}
    for outcome in (item for item in records if item.get("record") == "OUTCOME"):
        try:
            _required(
                outcome,
                {
                    "event_id",
                    "signal_et",
                    "signal_utc",
                    "outcome_et",
                    "outcome_utc",
                    "symbol",
                    "bar_type",
                    "select",
                    "session",
                    "factor_state",
                    "horizon_bars",
                    "horizon_minutes",
                    "signal_close",
                    "future_close",
                    "return",
                },
            )
            signal_id = outcome["event_id"]
            if signal_id not in signal_map:
                raise ValueError("LABEL_WITHOUT_SIGNAL")
            horizon = int(outcome["horizon_bars"])
            horizon_minutes = int(outcome["horizon_minutes"])
            if horizon_map.get(horizon) != horizon_minutes:
                raise ValueError("HORIZON_MAPPING_MISMATCH")
            key = (signal_id, horizon)
            if key in seen_labels:
                raise ValueError("DUPLICATE_LABEL")
            seen_labels.add(key)
            signal = signal_map[signal_id]
            if (
                outcome["symbol"] != "US.SPY"
                or outcome["bar_type"] != "K_5M"
                or outcome["select"] != "2"
                or outcome["session"] != "RTH"
                or outcome["factor_state"] != signal["factor_value"]
                or outcome["signal_et"] != signal["signal_time_et"]
                or outcome["signal_utc"] != signal["signal_time_utc"]
            ):
                raise ValueError("LEGACY_LABEL_IDENTITY_MISMATCH")
            target_et = _parse_time(outcome["outcome_et"], "outcome_et")
            signal_et = _parse_time(outcome["signal_et"], "signal_et")
            _parse_time(outcome["outcome_utc"], "outcome_utc")
            if (target_et - signal_et).total_seconds() != horizon_minutes * 60:
                raise ValueError("LEGACY_HORIZON_TIME_MISMATCH")
            signal_close = float(outcome["signal_close"])
            target_close = float(outcome["future_close"])
            forward_return = float(outcome["return"])
            if abs(signal_close - float(signal["signal_close"])) > 5e-10:
                raise ValueError("LEGACY_SIGNAL_CLOSE_MISMATCH")
            recomputed = target_close / signal_close - 1.0
            if abs(recomputed - forward_return) > 5e-10:
                raise ValueError("FORWARD_RETURN_MISMATCH")
            labels.append(
                {
                    "signal_id": signal_id,
                    "horizon_bars": horizon,
                    "horizon_minutes": horizon_minutes,
                    "target_time_et": outcome["outcome_et"],
                    "target_time_utc": outcome["outcome_utc"],
                    "target_close": target_close,
                    "forward_return": forward_return,
                }
            )
        except (TypeError, ValueError) as exc:
            fatal = True
            issues.append(
                {"code": "INVALID_LEGACY_LABEL", "severity": "ERROR", "message": str(exc)}
            )

    expected_dates = {
        "2026-09-28",
        "2026-09-29",
        "2026-09-30",
        "2026-10-01",
        "2026-10-02",
        "2026-10-05",
        "2026-10-06",
    }
    days = [item for item in records if item.get("record") == "DAY_STATUS"]
    actual_dates = {item.get("session_date_et") for item in days}
    complete_days = all(
        item.get("status") == "COMPLETE"
        and item.get("event_count") == "65"
        and item.get("outcomes_h3") == "65"
        and item.get("outcomes_h6") == "65"
        and item.get("outcomes_h12") == "65"
        and item.get("pending_count") == "0"
        and item.get("error_count") == "0"
        for item in days
    )
    error_records = [item for item in records if item.get("record") == "ERROR"]
    complete = (
        not fatal
        and len(signals) == 455
        and len(labels) == 1365
        and len(days) == 7
        and actual_dates == expected_dates
        and complete_days
        and not error_records
        and all(
            sum(item["horizon_bars"] == horizon for item in labels) == 455
            for horizon in (3, 6, 12)
        )
    )
    if not complete:
        issues.append(
            {
                "code": "LEGACY_ALTERNATIVE_COMPLETION_FAILED",
                "severity": "ERROR",
                "message": "旧版日志未满足冻结的 7 日、455 信号、每周期 455 标签完整性规则。",
            }
        )
    issues.append(
        {
            "code": "LEGACY_SOURCE_HASH_NOT_EMBEDDED",
            "severity": "INFO",
            "message": "日志只声明 version=1；代码 hash 来自归档源文件，日志本身未嵌入 hash。",
            "next_action": "保留原始 CSV SHA256 与归档源文件；后续运行使用 FUTU_FACTOR_V1 嵌入 hash。",
        }
    )
    run_status = "VALIDATED" if complete else "INVALID"
    run = {
        "factor_id": "SPY_F001_CLOSE_GT_EMA20",
        "run_id": "SPY_F001_20260928_20261006_FV1_LEGACY",
        "strategy_version": "SPY_FACTOR_RESEARCH_V1_LEGACY",
        "strategy_hash": LEGACY_STRATEGY_HASH,
        "parameter_version": "F001-FUNCTIONAL-20260928-20261006",
        "symbol": "US.SPY",
        "timeframe": "5m",
        "session": "RTH",
        "select": 2,
        "timezone": "America/New_York",
        "study_partition": "FUNCTIONAL_VALIDATION",
        "study_start_et": "2026-09-28",
        "study_end_et": "2026-10-06",
        "run_status": run_status,
        "research_verdict": "FUNCTIONAL_VALIDATION_PASS" if complete else "FUNCTIONAL_VALIDATION_FAILED",
        "version_binding_status": "LEGACY_MARKER_CONTRACT_ONLY",
        "signals": signals,
        "labels": labels,
        "issues": issues,
    }
    return ParseResult(
        "LEGACY_F001_RUN",
        run_status,
        encoding,
        "SPY_FACTOR_V1",
        rows_total,
        rows_marked,
        len(records),
        run=run,
        error=None if complete else "LEGACY_ALTERNATIVE_COMPLETION_FAILED",
    )


def _parse_batch_events(
    events: list[dict[str, Any]],
    *,
    encoding: str,
    rows_total: int,
    rows_marked: int,
    parsed_rows: int,
    allow_fixtures: bool,
) -> ParseResult:
    starts = [item for item in events if item["event_type"] == "RUN_START"]
    ends = [item for item in events if item["event_type"] == "RUN_END"]
    if len(starts) != 1:
        return ParseResult(
            "FACTOR_BATCH",
            "PARSE_FAILED",
            encoding,
            "FUTU_FACTOR_BATCH_V1",
            rows_total,
            rows_marked,
            parsed_rows,
            error=f"BATCH_RUN_START_COUNT:{len(starts)}",
        )
    start = starts[0]
    if bool(start.get("fixture")) and not allow_fixtures:
        return ParseResult(
            "TEST_FIXTURE",
            "INVALID",
            encoding,
            "FUTU_FACTOR_BATCH_V1",
            rows_total,
            rows_marked,
            parsed_rows,
            error="FIXTURE_NOT_ALLOWED_IN_PRODUCTION_DB",
        )
    if not re.fullmatch(r"[0-9a-f]{64}", str(start["strategy_hash"])):
        return ParseResult(
            "FACTOR_BATCH",
            "PARSE_FAILED",
            encoding,
            "FUTU_FACTOR_BATCH_V1",
            rows_total,
            rows_marked,
            parsed_rows,
            error="INVALID_STRATEGY_HASH",
        )
    config = BATCH_CONFIGS.get(str(start.get("strategy_version")))
    if config is None:
        return ParseResult(
            "FACTOR_BATCH",
            "PARSE_FAILED",
            encoding,
            "FUTU_FACTOR_BATCH_V1",
            rows_total,
            rows_marked,
            parsed_rows,
            error="UNSUPPORTED_BATCH_STRATEGY_VERSION",
        )
    if (
        start.get("study_partition") != config["partition"]
        or start.get("parameter_version") != config["batch_parameter_version"]
    ):
        return ParseResult(
            "FACTOR_BATCH",
            "PARSE_FAILED",
            encoding,
            "FUTU_FACTOR_BATCH_V1",
            rows_total,
            rows_marked,
            parsed_rows,
            error="BATCH_PARTITION_VERSION_MISMATCH",
        )
    if start.get("factor_ids") != BATCH_FACTOR_IDS:
        return ParseResult(
            "FACTOR_BATCH",
            "PARSE_FAILED",
            encoding,
            "FUTU_FACTOR_BATCH_V1",
            rows_total,
            rows_marked,
            parsed_rows,
            error="BATCH_FACTOR_CATALOG_MISMATCH",
        )
    if start.get("definition_hash") != BATCH_DEFINITION_HASH:
        return ParseResult(
            "FACTOR_BATCH",
            "PARSE_FAILED",
            encoding,
            "FUTU_FACTOR_BATCH_V1",
            rows_total,
            rows_marked,
            parsed_rows,
            error="BATCH_DEFINITION_HASH_MISMATCH",
        )
    if config["partition"] == "TRAIN":
        train_fields = {
            "system_start_target_et": TRAIN_SYSTEM_START,
            "sensitivity_start_et": TRAIN_SENSITIVITY_START,
            "study_start_et": TRAIN_START,
            "study_end_et": TRAIN_END,
            "expected_sessions": TRAIN_EXPECTED_SESSIONS,
            "expected_factor_events": TRAIN_EXPECTED_EVENTS,
            "expected_labels": TRAIN_EXPECTED_LABELS,
            "expected_warmup_bars": TRAIN_EXPECTED_WARMUP_BARS,
            "early_close_dates_et": ",".join(sorted(TRAIN_EARLY_CLOSE_DAYS)),
            "warmup_audit": "DUAL_RECURSIVE_EMA20_V1",
        }
        mismatches = [
            key for key, expected in train_fields.items() if start.get(key) != expected
        ]
        if mismatches:
            return ParseResult(
                "FACTOR_BATCH",
                "PARSE_FAILED",
                encoding,
                "FUTU_FACTOR_BATCH_V1",
                rows_total,
                rows_marked,
                parsed_rows,
                error="TRAIN_CONTRACT_MISMATCH:" + ",".join(mismatches),
            )

    identity = {
        key: start[key]
        for key in (
            "batch_id",
            "run_id",
            "strategy_version",
            "strategy_hash",
            "parameter_version",
            "symbol",
            "timeframe",
            "session",
            "select",
            "timezone",
        )
    }
    for event in events:
        for key, expected in identity.items():
            if event.get(key) != expected:
                return ParseResult(
                    "FACTOR_BATCH",
                    "PARSE_FAILED",
                    encoding,
                    "FUTU_FACTOR_BATCH_V1",
                    rows_total,
                    rows_marked,
                    parsed_rows,
                    error=f"BATCH_IDENTITY_MISMATCH:{key}",
                )

    run_issues: list[dict[str, str]] = []
    fatal = False
    incomplete = False
    if identity["symbol"] != "US.SPY" or identity["timeframe"] != "5m":
        fatal = True
        run_issues.append(
            {
                "code": "SYMBOL_TIMEFRAME_MISMATCH",
                "severity": "ERROR",
                "message": "C1 六因子批次只接受 US.SPY / 5m。",
            }
        )
    if identity["session"] != "RTH" or int(identity["select"]) != 2:
        fatal = True
        run_issues.append(
            {
                "code": "SESSION_SELECT_MISMATCH",
                "severity": "ERROR",
                "message": "C1 六因子批次必须为 RTH 且 select=2。",
            }
        )

    factor_events = [item for item in events if item["event_type"] == "FACTOR_EVENT"]
    normalized_events: list[dict[str, Any]] = []
    seen_signals: set[str] = set()
    observed_platform_system = {"f001": 0, "f002": 0, "f003": 0}
    observed_system_sensitivity = {"f001": 0, "f002": 0, "f003": 0}
    for event in factor_events:
        try:
            required = {
                "signal_id",
                "session_date_et",
                "signal_time_et",
                "signal_time_utc",
                "signal_close",
                "factor_ids",
                "definition_hash",
            }
            for _, prefix, _ in BATCH_FACTORS:
                required.add(prefix + "_state")
            for horizon in (3, 6, 12):
                suffix = str(horizon)
                required.update(
                    {
                        "r" + suffix,
                        "target_" + suffix + "_et",
                        "target_" + suffix + "_utc",
                        "target_" + suffix + "_close",
                    }
                )
            _required(event, required)
            missing_value_keys = [
                prefix + "_value"
                for _, prefix, _ in BATCH_FACTORS
                if prefix + "_value" not in event
            ]
            if missing_value_keys:
                raise ValueError("MISSING_FIELDS:" + ",".join(missing_value_keys))
            if event["factor_ids"] != BATCH_FACTOR_IDS:
                raise ValueError("EVENT_FACTOR_CATALOG_MISMATCH")
            if event["definition_hash"] != BATCH_DEFINITION_HASH:
                raise ValueError("EVENT_DEFINITION_HASH_MISMATCH")
            signal_id = str(event["signal_id"])
            if signal_id in seen_signals:
                raise ValueError("DUPLICATE_SIGNAL_ID")
            seen_signals.add(signal_id)
            signal_et = _parse_time(event["signal_time_et"], "signal_time_et")
            _parse_time(event["signal_time_utc"], "signal_time_utc")
            if str(event["session_date_et"]) != signal_et.date().isoformat():
                raise ValueError("SESSION_DATE_MISMATCH")
            minute = signal_et.hour * 60 + signal_et.minute
            if minute < 575 or minute > 895 or minute % 5:
                raise ValueError("SIGNAL_OUTSIDE_RTH_GRID")
            signal_close = float(event["signal_close"])
            if signal_close <= 0:
                raise ValueError("INVALID_SIGNAL_CLOSE")
            states: dict[str, str] = {}
            values: dict[str, float | None] = {}
            for factor_id, prefix, _ in BATCH_FACTORS:
                state = str(event[prefix + "_state"])
                if state not in {"PASS", "FAIL", "INVALID"}:
                    raise ValueError("INVALID_FACTOR_STATE:" + prefix)
                states[factor_id] = state
                raw_value = event[prefix + "_value"]
                if raw_value is None:
                    if state != "INVALID":
                        raise ValueError("NULL_FACTOR_VALUE:" + prefix)
                    values[factor_id] = None
                else:
                    number = float(raw_value)
                    if number != number or number in {float("inf"), float("-inf")}:
                        raise ValueError("NONFINITE_FACTOR_VALUE:" + prefix)
                    values[factor_id] = number
            if config["partition"] == "TRAIN":
                diagnostic_fields = {
                    "ema20_platform_0",
                    "ema20_platform_1",
                    "ema20_platform_3",
                    "ema20_system_start_0",
                    "ema20_sensitivity_start_0",
                    "close_1",
                }
                for number in (1, 2, 3):
                    prefix = f"f{number:03d}"
                    diagnostic_fields.add(prefix + "_system_state")
                    diagnostic_fields.add(prefix + "_sensitivity_state")
                _required(event, diagnostic_fields)
                diagnostics = {
                    key: float(event[key])
                    for key in (
                        "ema20_platform_0",
                        "ema20_platform_1",
                        "ema20_platform_3",
                        "ema20_system_start_0",
                        "ema20_sensitivity_start_0",
                        "close_1",
                    )
                }
                if any(
                    value != value or value in {float("inf"), float("-inf")}
                    for value in diagnostics.values()
                ):
                    raise ValueError("NONFINITE_WARMUP_DIAGNOSTIC")
                expected_platform_states = {
                    "f001": "PASS" if signal_close > diagnostics["ema20_platform_0"] else "FAIL",
                    "f002": (
                        "PASS"
                        if diagnostics["ema20_platform_0"] > diagnostics["ema20_platform_3"]
                        else "FAIL"
                    ),
                    "f003": (
                        "PASS"
                        if diagnostics["close_1"] <= diagnostics["ema20_platform_1"]
                        and signal_close > diagnostics["ema20_platform_0"]
                        else "FAIL"
                    ),
                }
                for number in (1, 2, 3):
                    prefix = f"f{number:03d}"
                    system_state = str(event[prefix + "_system_state"])
                    sensitivity_state = str(event[prefix + "_sensitivity_state"])
                    if system_state not in {"PASS", "FAIL"} or sensitivity_state not in {
                        "PASS",
                        "FAIL",
                    }:
                        raise ValueError("INVALID_WARMUP_STATE:" + prefix)
                    if str(event[prefix + "_state"]) != expected_platform_states[prefix]:
                        raise ValueError("PLATFORM_STATE_RECOMPUTE_MISMATCH:" + prefix)
                    if str(event[prefix + "_state"]) != system_state:
                        observed_platform_system[prefix] += 1
                    if system_state != sensitivity_state:
                        observed_system_sensitivity[prefix] += 1
            labels: list[dict[str, Any]] = []
            for horizon, minutes in ((3, 15), (6, 30), (12, 60)):
                suffix = str(horizon)
                target_et = _parse_time(event["target_" + suffix + "_et"], "target_et")
                _parse_time(event["target_" + suffix + "_utc"], "target_utc")
                if (target_et - signal_et).total_seconds() != minutes * 60:
                    raise ValueError("TARGET_HORIZON_MISMATCH:H" + suffix)
                target_close = float(event["target_" + suffix + "_close"])
                forward_return = float(event["r" + suffix])
                if target_close <= 0 or target_close != target_close:
                    raise ValueError("INVALID_TARGET_CLOSE:H" + suffix)
                if forward_return != forward_return or forward_return in {
                    float("inf"),
                    float("-inf"),
                }:
                    raise ValueError("NONFINITE_FORWARD_RETURN:H" + suffix)
                recomputed = target_close / signal_close - 1.0
                if abs(recomputed - forward_return) > 5e-10:
                    raise ValueError("FORWARD_RETURN_MISMATCH:H" + suffix)
                labels.append(
                    {
                        "signal_id": signal_id,
                        "horizon_bars": horizon,
                        "horizon_minutes": minutes,
                        "target_time_et": str(event["target_" + suffix + "_et"]),
                        "target_time_utc": str(event["target_" + suffix + "_utc"]),
                        "target_close": target_close,
                        "forward_return": forward_return,
                    }
                )
            normalized_events.append(
                {
                    "signal_id": signal_id,
                    "session_date_et": str(event["session_date_et"]),
                    "signal_time_et": str(event["signal_time_et"]),
                    "signal_time_utc": str(event["signal_time_utc"]),
                    "signal_close": signal_close,
                    "states": states,
                    "values": values,
                    "labels": labels,
                }
            )
        except (TypeError, ValueError) as exc:
            fatal = True
            run_issues.append(
                {"code": "INVALID_BATCH_EVENT", "severity": "ERROR", "message": str(exc)}
            )

    error_events = [item for item in events if item["event_type"] == "ERROR"]
    if error_events:
        incomplete = True
        run_issues.append(
            {
                "code": "PLATFORM_ERROR_EVENTS",
                "severity": "WARNING",
                "message": f"批次日志包含 {len(error_events)} 条 ERROR 事件。",
            }
        )
    warmup_audit: dict[str, Any] | None = None
    if config["partition"] == "TRAIN":
        warmup_events = [item for item in events if item["event_type"] == "WARMUP_AUDIT"]
        if len(warmup_events) != 1:
            fatal = True
            run_issues.append(
                {
                    "code": "TRAIN_WARMUP_AUDIT_COUNT",
                    "severity": "ERROR",
                    "message": f"TRAIN 必须且只能包含一条 WARMUP_AUDIT，实际为 {len(warmup_events)}。",
                }
            )
        else:
            warmup_audit = warmup_events[0]
            try:
                _required(
                    warmup_audit,
                    {
                        "status",
                        "system_start_target_et",
                        "first_observation_et",
                        "study_start_et",
                        "sensitivity_start_et",
                        "warmup_bars_before_train",
                        "expected_warmup_bars",
                        "platform_ema20",
                        "system_start_ema20",
                        "sensitivity_start_ema20",
                    },
                )
                if warmup_audit["status"] != "COMPLETE":
                    raise ValueError("TRAIN_WARMUP_NOT_COMPLETE")
                if warmup_audit["system_start_target_et"] != TRAIN_SYSTEM_START:
                    raise ValueError("TRAIN_SYSTEM_START_MISMATCH")
                if not str(warmup_audit["first_observation_et"]).startswith(
                    TRAIN_SYSTEM_START + "T09:35"
                ):
                    raise ValueError("TRAIN_FIRST_OBSERVATION_MISMATCH")
                if warmup_audit["study_start_et"] != TRAIN_START:
                    raise ValueError("TRAIN_STATISTICS_START_MISMATCH")
                if warmup_audit["sensitivity_start_et"] != TRAIN_SENSITIVITY_START:
                    raise ValueError("TRAIN_SENSITIVITY_START_MISMATCH")
                if int(warmup_audit["warmup_bars_before_train"]) != TRAIN_EXPECTED_WARMUP_BARS:
                    raise ValueError("TRAIN_WARMUP_BAR_COUNT_MISMATCH")
                if int(warmup_audit["expected_warmup_bars"]) != TRAIN_EXPECTED_WARMUP_BARS:
                    raise ValueError("TRAIN_EXPECTED_WARMUP_BAR_COUNT_MISMATCH")
            except (TypeError, ValueError) as exc:
                fatal = True
                run_issues.append(
                    {"code": "INVALID_TRAIN_WARMUP_AUDIT", "severity": "ERROR", "message": str(exc)}
                )
    if len(ends) != 1:
        incomplete = True
        run_issues.append(
            {
                "code": "MISSING_RUN_END",
                "severity": "WARNING",
                "message": "缺少唯一 RUN_END，不能标记 VALIDATED。",
            }
        )
    else:
        end = ends[0]
        try:
            _required(end, {"status", "signal_count", "factor_event_count", "error_count"})
            if str(end["status"]) != "COMPLETE":
                incomplete = True
                run_issues.append(
                    {
                        "code": "RUN_END_INCOMPLETE",
                        "severity": "WARNING",
                        "message": "RUN_END 未声明 COMPLETE。",
                    }
                )
            if str(end["status"]) == "COMPLETE" and int(end["signal_count"]) != len(
                normalized_events
            ):
                raise ValueError("RUN_END_SIGNAL_COUNT_MISMATCH")
            if int(end["factor_event_count"]) != len(normalized_events):
                raise ValueError("RUN_END_EVENT_COUNT_MISMATCH")
            if int(end["error_count"]) != len(error_events):
                raise ValueError("RUN_END_ERROR_COUNT_MISMATCH")
            if config["partition"] == "TRAIN":
                _required(
                    end,
                    {
                        "expected_sessions",
                        "expected_factor_events",
                        "label_count",
                        "expected_labels",
                        "warmup_audit_status",
                        "f001_platform_system_mismatches",
                        "f002_platform_system_mismatches",
                        "f003_platform_system_mismatches",
                        "f001_system_sensitivity_mismatches",
                        "f002_system_sensitivity_mismatches",
                        "f003_system_sensitivity_mismatches",
                    },
                )
                if int(end["completed_days"]) != TRAIN_EXPECTED_SESSIONS:
                    raise ValueError("TRAIN_SESSION_COUNT_MISMATCH")
                if int(end["expected_sessions"]) != TRAIN_EXPECTED_SESSIONS:
                    raise ValueError("TRAIN_EXPECTED_SESSION_COUNT_MISMATCH")
                if len(normalized_events) != TRAIN_EXPECTED_EVENTS:
                    raise ValueError("TRAIN_EVENT_COUNT_MISMATCH")
                if int(end["expected_factor_events"]) != TRAIN_EXPECTED_EVENTS:
                    raise ValueError("TRAIN_EXPECTED_EVENT_COUNT_MISMATCH")
                if int(end["label_count"]) != TRAIN_EXPECTED_LABELS:
                    raise ValueError("TRAIN_LABEL_COUNT_MISMATCH")
                if int(end["expected_labels"]) != TRAIN_EXPECTED_LABELS:
                    raise ValueError("TRAIN_EXPECTED_LABEL_COUNT_MISMATCH")
                if end["warmup_audit_status"] != "COMPLETE":
                    raise ValueError("TRAIN_RUN_END_WARMUP_INCOMPLETE")
                for prefix in ("f001", "f002", "f003"):
                    if int(end[prefix + "_platform_system_mismatches"]) != observed_platform_system[prefix]:
                        raise ValueError("TRAIN_PLATFORM_SYSTEM_MISMATCH_COUNT:" + prefix)
                    if int(end[prefix + "_system_sensitivity_mismatches"]) != observed_system_sensitivity[prefix]:
                        raise ValueError("TRAIN_SYSTEM_SENSITIVITY_MISMATCH_COUNT:" + prefix)
                if warmup_audit is not None:
                    warmup_audit = dict(warmup_audit)
                    warmup_audit["platform_system_mismatches"] = dict(observed_platform_system)
                    warmup_audit["system_sensitivity_mismatches"] = dict(
                        observed_system_sensitivity
                    )
        except (TypeError, ValueError) as exc:
            fatal = True
            run_issues.append(
                {"code": "INVALID_RUN_END", "severity": "ERROR", "message": str(exc)}
            )

    events_by_day: dict[str, int] = {}
    for event in normalized_events:
        day_text = event["session_date_et"]
        events_by_day[day_text] = events_by_day.get(day_text, 0) + 1
    day_ends = [item for item in events if item["event_type"] == "DAY_END"]
    seen_day_ends: set[str] = set()
    for day in day_ends:
        try:
            _required(
                day,
                {
                    "session_date_et",
                    "status",
                    "signal_count",
                    "factor_event_count",
                    "pending_count",
                    "error_count",
                    "expected_events",
                },
            )
            day_text = str(day["session_date_et"])
            if day_text in seen_day_ends:
                raise ValueError("DUPLICATE_DAY_END:" + day_text)
            seen_day_ends.add(day_text)
            actual_count = events_by_day.get(day_text, 0)
            signal_count = int(day["signal_count"])
            expected_count = int(day["expected_events"])
            if day["status"] == "COMPLETE" and signal_count != actual_count:
                raise ValueError("DAY_SIGNAL_COUNT_MISMATCH:" + day_text)
            if int(day["factor_event_count"]) != actual_count:
                raise ValueError("DAY_EVENT_COUNT_MISMATCH:" + day_text)
            if day["status"] == "COMPLETE" and expected_count != actual_count:
                raise ValueError("DAY_EXPECTED_COUNT_MISMATCH:" + day_text)
            if day["status"] != "COMPLETE" and not (
                actual_count <= signal_count <= expected_count
            ):
                raise ValueError("DAY_INCOMPLETE_COUNT_ORDER:" + day_text)
            if int(day["pending_count"]) != 0 or int(day["error_count"]) != 0:
                incomplete = True
            if day["status"] != "COMPLETE":
                incomplete = True
                run_issues.append(
                    {
                        "code": "DAY_INCOMPLETE",
                        "severity": "WARNING",
                        "message": day_text + " 日批次数据不完整。",
                    }
                )
        except (TypeError, ValueError) as exc:
            fatal = True
            run_issues.append(
                {"code": "INVALID_DAY_END", "severity": "ERROR", "message": str(exc)}
            )
    if seen_day_ends != set(events_by_day):
        fatal = True
        run_issues.append(
            {
                "code": "DAY_END_COVERAGE_MISMATCH",
                "severity": "ERROR",
                "message": "DAY_END 日期集合与批次事件日期集合不一致。",
            }
        )
    if config["partition"] == "TRAIN":
        expected_sessions = expected_train_sessions()
        if len(expected_sessions) != TRAIN_EXPECTED_SESSIONS:
            raise RuntimeError("internal TRAIN calendar does not contain 187 sessions")
        if set(events_by_day) != expected_sessions or seen_day_ends != expected_sessions:
            fatal = True
            run_issues.append(
                {
                    "code": "TRAIN_SESSION_CALENDAR_MISMATCH",
                    "severity": "ERROR",
                    "message": "TRAIN 日期集合与冻结的 187 个 XNYS 交易日不一致。",
                }
            )
        events_per_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in normalized_events:
            events_per_day[event["session_date_et"]].append(event)
        for day_text in sorted(events_per_day):
            expected_count = 29 if day_text in TRAIN_EARLY_CLOSE_DAYS else 65
            signal_end = 11 * 60 + 55 if day_text in TRAIN_EARLY_CLOSE_DAYS else 14 * 60 + 55
            expected_minutes = set(range(9 * 60 + 35, signal_end + 1, 5))
            actual_minutes = {
                datetime.fromisoformat(item["signal_time_et"]).hour * 60
                + datetime.fromisoformat(item["signal_time_et"]).minute
                for item in events_per_day[day_text]
            }
            if len(events_per_day[day_text]) != expected_count or actual_minutes != expected_minutes:
                fatal = True
                run_issues.append(
                    {
                        "code": "TRAIN_INTRADAY_GRID_MISMATCH",
                        "severity": "ERROR",
                        "message": day_text + " 的信号网格或事件数不符合冻结口径。",
                    }
                )
                break
    if not normalized_events:
        incomplete = True
        run_issues.append(
            {"code": "NO_FACTOR_EVENTS", "severity": "WARNING", "message": "没有可导入的批次事件。"}
        )
    if config["partition"] == "TRAIN" and any(observed_platform_system.values()):
        run_issues.append(
            {
                "code": "EMA20_PLATFORM_WARMUP_STATE_DIFFERENCE",
                "severity": "WARNING",
                "message": "富途平台EMA与从系统起点递推的EMA导致F001–F003状态差异，需独立核对。",
                "next_action": "保持Data Gate未通过；核对差异事件，必要时执行成对系统起点诊断。",
            }
        )
    if config["partition"] == "TRAIN" and any(observed_system_sensitivity.values()):
        run_issues.append(
            {
                "code": "EMA20_START_SENSITIVITY_STATE_DIFFERENCE",
                "severity": "WARNING",
                "message": "长预热与短预热递推EMA导致F001–F003状态差异，结果对起点敏感。",
                "next_action": "不得升级Edge；保留差异记录并进行独立预热核对。",
            }
        )

    run_status = "INVALID" if fatal else "INCOMPLETE" if incomplete else "VALIDATED"
    if fatal:
        return ParseResult(
            "FACTOR_BATCH",
            "INVALID",
            encoding,
            "FUTU_FACTOR_BATCH_V1",
            rows_total,
            rows_marked,
            parsed_rows,
            error=run_issues[0]["message"] if run_issues else "INVALID_BATCH",
        )
    partition = str(start.get("study_partition", "UNKNOWN"))
    verdicts = {
        "FUNCTIONAL_VALIDATION": "FUNCTIONAL_VALIDATION_PASS",
        "TRAIN": "TRAIN_DATA_VALIDATED",
        "VALIDATION": "VALIDATION_DATA_VALIDATED",
        "OOS": "OOS_DATA_VALIDATED",
    }
    research_verdict = verdicts.get(partition, "NOT_ASSESSED") if run_status == "VALIDATED" else "NOT_ASSESSED"
    runs: list[dict[str, Any]] = []
    for factor_id, prefix, _ in BATCH_FACTORS:
        factor_parameter_version = config["factor_parameter_versions"][factor_id]
        signals: list[dict[str, Any]] = []
        labels: list[dict[str, Any]] = []
        invalid_count = 0
        for event in normalized_events:
            state = event["states"][factor_id]
            if state == "INVALID":
                invalid_count += 1
                continue
            signals.append(
                {
                    "signal_id": event["signal_id"],
                    "signal_time_et": event["signal_time_et"],
                    "signal_time_utc": event["signal_time_utc"],
                    "signal_close": event["signal_close"],
                    "factor_value": state,
                    "factor_numeric": event["values"][factor_id],
                }
            )
            labels.extend(event["labels"])
        factor_issues = list(run_issues)
        if invalid_count:
            factor_issues.append(
                {
                    "code": "INVALID_FACTOR_MEASUREMENTS",
                    "severity": "WARNING",
                    "message": f"{factor_id} 有 {invalid_count} 个无效测量，未纳入该因子统计。",
                }
            )
        runs.append(
            {
                **identity,
                "factor_id": factor_id,
                "run_id": str(identity["batch_id"]) + ":" + prefix.upper(),
                "parameter_version": factor_parameter_version,
                "study_partition": partition,
                "study_start_et": start.get("study_start_et"),
                "study_end_et": start.get("study_end_et"),
                "run_status": run_status,
                "research_verdict": research_verdict,
                "version_binding_status": "BATCH_DEFINITION_HASH",
                "signals": signals,
                "labels": labels,
                "issues": factor_issues,
                "warmup_audit": warmup_audit,
            }
        )
    return ParseResult(
        "TEST_FIXTURE" if bool(start.get("fixture")) else "FACTOR_BATCH",
        run_status,
        encoding,
        "FUTU_FACTOR_BATCH_V1",
        rows_total,
        rows_marked,
        parsed_rows,
        run={"batch_runs": runs, "batch_id": identity["batch_id"]},
    )


def parse_runlog(path: Path, *, allow_fixtures: bool = False) -> ParseResult:
    try:
        text, encoding = decode_csv(path)
    except (OSError, ValueError) as exc:
        return ParseResult("FACTOR_RUN", "PARSE_FAILED", "UNKNOWN", None, 0, 0, 0, error=str(exc))

    if LEGACY_MARKER in text and MARKER not in text:
        return _attach_system_log_lifecycle(_parse_legacy_runlog(text, encoding), text)

    events: list[dict[str, Any]] = []
    versions: set[str] = set()
    rows_total = 0
    rows_marked = 0
    parsed_rows = 0
    decoder = json.JSONDecoder()
    try:
        for line in text.splitlines():
            rows_total += 1
            decoded = _decode_factor_marker_line(line, decoder)
            if decoded is None:
                continue
            rows_marked += 1
            version, payload = decoded
            versions.add(version)
            if version not in {"FUTU_FACTOR_V1", "FUTU_FACTOR_BATCH_V1"}:
                continue
            _required(
                payload,
                REQUIRED_COMMON if version == "FUTU_FACTOR_V1" else BATCH_REQUIRED_COMMON,
            )
            events.append(payload)
            parsed_rows += 1
    except (csv.Error, json.JSONDecodeError, ValueError) as exc:
        return _attach_system_log_lifecycle(
            ParseResult(
                "FACTOR_RUN",
                "PARSE_FAILED",
                encoding,
                next(iter(versions), None),
                rows_total,
                rows_marked,
                parsed_rows,
                error=str(exc),
            ),
            text,
        )

    if not rows_marked:
        return _attach_system_log_lifecycle(
            ParseResult("IGNORED_NON_FACTOR", "IGNORED", encoding, None, rows_total, 0, 0),
            text,
        )
    if versions == {"FUTU_FACTOR_BATCH_V1"}:
        return _attach_system_log_lifecycle(
            _parse_batch_events(
                events,
                encoding=encoding,
                rows_total=rows_total,
                rows_marked=rows_marked,
                parsed_rows=parsed_rows,
                allow_fixtures=allow_fixtures,
            ),
            text,
        )
    if versions != {"FUTU_FACTOR_V1"}:
        return ParseResult(
            "UNSUPPORTED_FACTOR_VERSION",
            "INVALID",
            encoding,
            ",".join(sorted(versions)),
            rows_total,
            rows_marked,
            parsed_rows,
            error="UNSUPPORTED_MARKER_VERSION",
        )
    starts = [item for item in events if item["event_type"] == "RUN_START"]
    ends = [item for item in events if item["event_type"] == "RUN_END"]
    if len(starts) != 1:
        return ParseResult(
            "FACTOR_RUN",
            "PARSE_FAILED",
            encoding,
            "FUTU_FACTOR_V1",
            rows_total,
            rows_marked,
            parsed_rows,
            error=f"RUN_START_COUNT:{len(starts)}",
        )
    start = starts[0]
    if bool(start.get("fixture")) and not allow_fixtures:
        return ParseResult(
            "TEST_FIXTURE",
            "INVALID",
            encoding,
            "FUTU_FACTOR_V1",
            rows_total,
            rows_marked,
            parsed_rows,
            error="FIXTURE_NOT_ALLOWED_IN_PRODUCTION_DB",
        )
    if not re.fullmatch(r"[0-9a-f]{64}", str(start["strategy_hash"])):
        return ParseResult(
            "FACTOR_RUN",
            "PARSE_FAILED",
            encoding,
            "FUTU_FACTOR_V1",
            rows_total,
            rows_marked,
            parsed_rows,
            error="INVALID_STRATEGY_HASH",
        )
    identity = {
        key: start[key]
        for key in (
            "factor_id",
            "run_id",
            "strategy_version",
            "strategy_hash",
            "parameter_version",
            "symbol",
            "timeframe",
            "session",
            "select",
            "timezone",
        )
    }
    for event in events:
        for key, expected in identity.items():
            if event.get(key) != expected:
                return ParseResult(
                    "FACTOR_RUN",
                    "PARSE_FAILED",
                    encoding,
                    "FUTU_FACTOR_V1",
                    rows_total,
                    rows_marked,
                    parsed_rows,
                    error=f"IDENTITY_MISMATCH:{key}",
                )

    run_issues: list[dict[str, str]] = []
    fatal = False
    incomplete = False
    if identity["symbol"] != "US.SPY" or identity["timeframe"] != "5m":
        fatal = True
        run_issues.append(
            {"code": "SYMBOL_TIMEFRAME_MISMATCH", "severity": "ERROR", "message": "F001 只接受 US.SPY / 5m。"}
        )
    if identity["session"] != "RTH" or int(identity["select"]) != 2:
        fatal = True
        run_issues.append(
            {"code": "SESSION_SELECT_MISMATCH", "severity": "ERROR", "message": "日志必须为 RTH 且 select=2。"}
        )

    signals: list[dict[str, Any]] = []
    seen_signals: set[str] = set()
    for event in (item for item in events if item["event_type"] == "SIGNAL"):
        try:
            _required(
                event,
                {"signal_id", "signal_time_et", "signal_time_utc", "signal_close", "factor_value"},
            )
            signal_id = str(event["signal_id"])
            if signal_id in seen_signals:
                raise ValueError("DUPLICATE_SIGNAL_ID")
            seen_signals.add(signal_id)
            et_time = _parse_time(event["signal_time_et"], "signal_time_et")
            _parse_time(event["signal_time_utc"], "signal_time_utc")
            minute = et_time.hour * 60 + et_time.minute
            if minute < 575 or minute > 895 or minute % 5:
                raise ValueError("SIGNAL_OUTSIDE_RTH_GRID")
            factor_value = str(event["factor_value"])
            if factor_value not in {"PASS", "FAIL"}:
                raise ValueError("INVALID_FACTOR_VALUE")
            signal_close = float(event["signal_close"])
            if signal_close <= 0:
                raise ValueError("INVALID_SIGNAL_CLOSE")
            signals.append(
                {
                    "signal_id": signal_id,
                    "signal_time_et": str(event["signal_time_et"]),
                    "signal_time_utc": str(event["signal_time_utc"]),
                    "signal_close": signal_close,
                    "factor_value": factor_value,
                    "factor_numeric": event.get("ema20"),
                }
            )
        except (TypeError, ValueError) as exc:
            fatal = True
            run_issues.append(
                {"code": "INVALID_SIGNAL", "severity": "ERROR", "message": str(exc)}
            )

    signal_map = {item["signal_id"]: item for item in signals}
    labels: list[dict[str, Any]] = []
    seen_labels: set[tuple[str, int]] = set()
    horizon_map = {3: 15, 6: 30, 12: 60}
    for event in (item for item in events if item["event_type"] == "LABEL_MATURED"):
        try:
            _required(
                event,
                {
                    "signal_id",
                    "horizon",
                    "horizon_minutes",
                    "target_time_et",
                    "target_time_utc",
                    "target_close",
                    "forward_return",
                },
            )
            signal_id = str(event["signal_id"])
            horizon = int(event["horizon"])
            horizon_minutes = int(event["horizon_minutes"])
            if signal_id not in signal_map:
                raise ValueError("LABEL_WITHOUT_SIGNAL")
            if horizon not in horizon_map or horizon_map[horizon] != horizon_minutes:
                raise ValueError("HORIZON_MAPPING_MISMATCH")
            key = (signal_id, horizon)
            if key in seen_labels:
                raise ValueError("DUPLICATE_LABEL")
            seen_labels.add(key)
            target_et = _parse_time(event["target_time_et"], "target_time_et")
            signal_et = _parse_time(signal_map[signal_id]["signal_time_et"], "signal_time_et")
            _parse_time(event["target_time_utc"], "target_time_utc")
            if target_et <= signal_et:
                raise ValueError("TARGET_NOT_AFTER_SIGNAL")
            target_close = float(event["target_close"])
            forward_return = float(event["forward_return"])
            recomputed = target_close / float(signal_map[signal_id]["signal_close"]) - 1.0
            if abs(recomputed - forward_return) > 5e-10:
                raise ValueError("FORWARD_RETURN_MISMATCH")
            labels.append(
                {
                    "signal_id": signal_id,
                    "horizon_bars": horizon,
                    "horizon_minutes": horizon_minutes,
                    "target_time_et": str(event["target_time_et"]),
                    "target_time_utc": str(event["target_time_utc"]),
                    "target_close": target_close,
                    "forward_return": forward_return,
                }
            )
        except (TypeError, ValueError) as exc:
            fatal = True
            run_issues.append(
                {"code": "INVALID_LABEL", "severity": "ERROR", "message": str(exc)}
            )

    expected_labels = len(signals) * 3
    if len(labels) != expected_labels:
        incomplete = True
        run_issues.append(
            {
                "code": "MISSING_MATURED_LABELS",
                "severity": "WARNING",
                "message": f"标签数 {len(labels)}，预期 {expected_labels}。",
                "next_action": "检查尾部剔除、漏触发、跨日残留和 RUN_END。",
            }
        )
    error_events = [item for item in events if item["event_type"] == "ERROR"]
    if error_events:
        incomplete = True
        run_issues.append(
            {
                "code": "PLATFORM_ERROR_EVENTS",
                "severity": "WARNING",
                "message": f"日志包含 {len(error_events)} 条 ERROR 事件。",
            }
        )
    if len(ends) != 1:
        incomplete = True
        run_issues.append(
            {"code": "MISSING_RUN_END", "severity": "WARNING", "message": "缺少唯一 RUN_END，不能标记 VALIDATED。"}
        )
    elif str(ends[0].get("status")) != "COMPLETE":
        incomplete = True
        run_issues.append(
            {"code": "RUN_END_INCOMPLETE", "severity": "WARNING", "message": "RUN_END 未声明 COMPLETE。"}
        )
    for day in (item for item in events if item["event_type"] == "DAY_STATUS"):
        if day.get("status") != "COMPLETE":
            incomplete = True
            run_issues.append(
                {"code": "DAY_INCOMPLETE", "severity": "WARNING", "message": f"{day.get('session_date_et')} 日数据不完整。"}
            )

    run_status = "INVALID" if fatal else "INCOMPLETE" if incomplete else "VALIDATED"
    partition = str(start.get("study_partition", "UNKNOWN"))
    if run_status == "VALIDATED" and partition == "FUNCTIONAL_VALIDATION":
        research_verdict = "FUNCTIONAL_VALIDATION_PASS"
    elif run_status == "VALIDATED" and partition == "TRAIN":
        research_verdict = "TRAIN_DATA_VALIDATED"
    else:
        research_verdict = "NOT_ASSESSED"
    run = {
        **identity,
        "study_partition": partition,
        "study_start_et": start.get("study_start_et"),
        "study_end_et": start.get("study_end_et"),
        "run_status": run_status,
        "research_verdict": research_verdict,
        "version_binding_status": "EMBEDDED_HASH",
        "signals": signals,
        "labels": labels,
        "issues": run_issues,
    }
    return _attach_system_log_lifecycle(
        ParseResult(
            "TEST_FIXTURE" if bool(start.get("fixture")) else "FACTOR_RUN",
            run_status,
            encoding,
            "FUTU_FACTOR_V1",
            rows_total,
            rows_marked,
            parsed_rows,
            run=run,
        ),
        text,
    )


class Importer:
    def __init__(self, database: Database, *, allow_fixtures: bool = False):
        self.database = database
        self.allow_fixtures = allow_fixtures

    def import_file(self, path: Path) -> dict[str, Any]:
        path = Path(path)
        stat = path.stat()
        file_hash = sha256_file(path)
        self.database.record_source(
            path=path,
            file_sha256=file_hash,
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT import_status FROM source_files WHERE file_sha256=?", (file_hash,)
            ).fetchone()
        if existing and existing["import_status"] in {
            "VALIDATED",
            "INCOMPLETE",
            "INVALID",
            "IGNORED",
            "PARSE_FAILED",
        }:
            return {"status": "DUPLICATE", "file_sha256": file_hash}

        result = parse_runlog(path, allow_fixtures=self.allow_fixtures)
        self.database.update_source(
            file_hash,
            encoding=result.encoding,
            marker_version=result.marker_version,
            classification=result.classification,
            import_status=result.import_status,
            rows_total=result.rows_total,
            rows_marked=result.rows_marked,
            parse_success_rate=result.success_rate,
            error_text=result.error,
            system_log_start_local=result.system_log_start_local,
            system_log_end_local=result.system_log_end_local,
        )
        if result.run is None:
            if result.import_status not in {"IGNORED"}:
                self.database.add_issue(
                    issue_key=f"FILE:{file_hash}:{result.import_status}",
                    kind="ANOMALY",
                    severity="ERROR" if result.import_status == "PARSE_FAILED" else "WARNING",
                    issue_code=result.import_status,
                    message=result.error or result.classification,
                    next_action="核对日志标记、契约版本、CSV 完整性和导出编码。",
                    file_sha256=file_hash,
                )
            return {"status": result.import_status, "file_sha256": file_hash, "error": result.error}
        if "batch_runs" in result.run:
            status, run_instance_ids = self.database.import_runs(
                file_hash, result.run["batch_runs"]
            )
            error = None
            if status == "INVALID":
                with self.database.connect() as connection:
                    source = connection.execute(
                        "SELECT error_text FROM source_files WHERE file_sha256=?",
                        (file_hash,),
                    ).fetchone()
                error = source["error_text"] if source else None
            return {
                "status": status,
                "file_sha256": file_hash,
                "batch_id": result.run["batch_id"],
                "run_instance_ids": run_instance_ids,
                "error": error,
            }
        status, run_instance_id = self.database.import_run(file_hash, result.run)
        return {
            "status": status,
            "file_sha256": file_hash,
            "run_instance_id": run_instance_id,
        }


class FolderWatcher:
    def __init__(
        self,
        importer: Importer,
        folders: list[Path],
        *,
        poll_seconds: float = 2.0,
        stable_checks: int = 2,
    ):
        self.importer = importer
        self.folders = [Path(folder) for folder in folders]
        self.poll_seconds = poll_seconds
        self.stable_checks = stable_checks
        self._samples: dict[str, tuple[int, int, int]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="factor-runlog-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(2.0, self.poll_seconds + 1.0))

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
                self.last_error = None
            except Exception as exc:  # keep monitoring other cycles; error stays visible
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.importer.database.set_state("watcher_error", self.last_error)
            self._stop.wait(self.poll_seconds)

    def scan_once(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        paths: set[Path] = set()
        for folder in self.folders:
            if not folder.exists():
                continue
            paths.update(folder.glob("RunLog_*.csv"))
        for path in sorted(paths):
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            key = str(path.resolve())
            previous = self._samples.get(key)
            if previous and previous[:2] == (stat.st_size, stat.st_mtime_ns):
                count = previous[2] + 1
            else:
                count = 1
            self._samples[key] = (stat.st_size, stat.st_mtime_ns, count)
            if count < self.stable_checks:
                continue
            try:
                results.append(self.importer.import_file(path))
            except (OSError, ValueError) as exc:
                self.last_error = f"{path.name}: {type(exc).__name__}: {exc}"
        self.importer.database.set_state("last_scan_utc", utc_now())
        self.importer.database.set_state(
            "watch_folders", json.dumps([str(folder) for folder in self.folders], ensure_ascii=False)
        )
        return results
