from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import re
import threading
from typing import Any

from .db import Database, utc_now


MARKER = "FUTU_FACTOR_V1|"
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


def parse_runlog(path: Path, *, allow_fixtures: bool = False) -> ParseResult:
    try:
        text, encoding = decode_csv(path)
    except (OSError, ValueError) as exc:
        return ParseResult("FACTOR_RUN", "PARSE_FAILED", "UNKNOWN", None, 0, 0, 0, error=str(exc))

    events: list[dict[str, Any]] = []
    versions: set[str] = set()
    rows_total = 0
    rows_marked = 0
    parsed_rows = 0
    decoder = json.JSONDecoder()
    try:
        reader = csv.reader(io.StringIO(text))
        for row in reader:
            rows_total += 1
            combined = ",".join(row)
            marker_match = re.search(r"FUTU_FACTOR_[A-Z0-9_]+\|", combined)
            if not marker_match:
                continue
            rows_marked += 1
            version = marker_match.group(0)[:-1]
            versions.add(version)
            if version != "FUTU_FACTOR_V1":
                continue
            payload_text = combined[marker_match.end() :].lstrip()
            payload, _ = decoder.raw_decode(payload_text)
            if not isinstance(payload, dict):
                raise ValueError("PAYLOAD_NOT_OBJECT")
            _required(payload, REQUIRED_COMMON)
            events.append(payload)
            parsed_rows += 1
    except (csv.Error, json.JSONDecodeError, ValueError) as exc:
        return ParseResult(
            "FACTOR_RUN",
            "PARSE_FAILED",
            encoding,
            next(iter(versions), None),
            rows_total,
            rows_marked,
            parsed_rows,
            error=str(exc),
        )

    if not rows_marked:
        return ParseResult("IGNORED_NON_FACTOR", "IGNORED", encoding, None, rows_total, 0, 0)
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
    run = {
        **identity,
        "study_partition": str(start.get("study_partition", "UNKNOWN")),
        "study_start_et": start.get("study_start_et"),
        "study_end_et": start.get("study_end_et"),
        "run_status": run_status,
        "signals": signals,
        "labels": labels,
        "issues": run_issues,
    }
    return ParseResult(
        "TEST_FIXTURE" if bool(start.get("fixture")) else "FACTOR_RUN",
        run_status,
        encoding,
        "FUTU_FACTOR_V1",
        rows_total,
        rows_marked,
        parsed_rows,
        run=run,
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
