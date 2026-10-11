from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


MARKER = "FUTU_FACTOR_BATCH_V1|"
EXPECTED_SHA256 = "bda31dddd8fc878663ce6827f11cb336ab4508c0fe0459259d88e321827af742"
SYSTEM_START = "2025-07-01"
SENSITIVITY_START = "2025-09-02"
TRAIN_START = "2025-10-01"
TRAIN_END = "2026-06-30"
EXPECTED_WARMUP_BARS = 4956
EXPECTED_WARMUP_SESSIONS = 64
EXPECTED_FACTOR_EVENTS = 12083
EXPECTED_LABELS = 36249
EMA_ALPHA = 2.0 / 21.0
TOLERANCE = 1e-8


@dataclass(frozen=True)
class Bar:
    time_key: str
    open: float
    high: float
    low: float
    close: float

    @property
    def date(self) -> str:
        return self.time_key[:10]

    @property
    def clock(self) -> str:
        return self.time_key[11:16]


@dataclass(frozen=True)
class RehabEvent:
    ex_div_date: str
    forward_adj_factor_a: float
    forward_adj_factor_b: float
    per_cash_div: float | None = None


@dataclass(frozen=True)
class EmaPoint:
    close: float
    ema: float


@dataclass(frozen=True)
class EmaState:
    current: EmaPoint
    previous: EmaPoint
    three_back: EmaPoint


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def normalized_text_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return sha256_bytes(text.encode("utf-8"))


def decode_runlog(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("RUNLOG_ENCODING_UNSUPPORTED")


def extract_events(raw: bytes) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    events: list[dict[str, Any]] = []
    for line in decode_runlog(raw).splitlines():
        marker_at = line.find(MARKER)
        if marker_at < 0:
            continue
        payload, _ = decoder.raw_decode(line[marker_at + len(MARKER) :])
        if not isinstance(payload, dict):
            raise ValueError("MARKER_PAYLOAD_NOT_OBJECT")
        events.append(payload)
    if not events:
        raise ValueError("NO_FACTOR_BATCH_EVENTS")
    return events


def _transform_history(history: list[EmaPoint], a: float, b: float) -> list[EmaPoint]:
    return [EmaPoint(a * point.close + b, a * point.ema + b) for point in history]


def build_dynamic_ema_states(
    bars: Iterable[Bar],
    rehab_events: Iterable[RehabEvent],
    *,
    start_date: str,
) -> dict[str, EmaState]:
    rehab = {item.ex_div_date: item for item in rehab_events}
    ema: float | None = None
    history: list[EmaPoint] = []
    states: dict[str, EmaState] = {}
    active_date = ""
    for bar in sorted(bars, key=lambda item: item.time_key):
        if bar.date < start_date:
            continue
        if bar.date != active_date:
            adjustment = rehab.get(bar.date)
            if adjustment is not None and ema is not None:
                ema = adjustment.forward_adj_factor_a * ema + adjustment.forward_adj_factor_b
                history = _transform_history(
                    history,
                    adjustment.forward_adj_factor_a,
                    adjustment.forward_adj_factor_b,
                )
            active_date = bar.date
        ema = bar.close if ema is None else EMA_ALPHA * bar.close + (1.0 - EMA_ALPHA) * ema
        history.append(EmaPoint(bar.close, ema))
        if len(history) > 4:
            history.pop(0)
        if len(history) == 4:
            states[bar.time_key] = EmaState(history[-1], history[-2], history[-4])
    return states


def build_skip_final_ema_states(
    bars: Iterable[Bar],
    *,
    start_date: str,
) -> dict[str, EmaState]:
    ordered = sorted(bars, key=lambda item: item.time_key)
    last_key_by_date: dict[str, str] = {}
    for bar in ordered:
        last_key_by_date[bar.date] = bar.time_key
    ema: float | None = None
    history: list[EmaPoint] = []
    states: dict[str, EmaState] = {}
    for bar in ordered:
        if bar.date < start_date or bar.time_key == last_key_by_date[bar.date]:
            continue
        ema = bar.close if ema is None else EMA_ALPHA * bar.close + (1.0 - EMA_ALPHA) * ema
        history.append(EmaPoint(bar.close, ema))
        if len(history) > 4:
            history.pop(0)
        if len(history) == 4:
            states[bar.time_key] = EmaState(history[-1], history[-2], history[-4])
    return states


def expected_adjusted_prior_close(prior_close: float, adjustment: RehabEvent | None) -> float:
    if adjustment is None:
        return prior_close
    return adjustment.forward_adj_factor_a * prior_close + adjustment.forward_adj_factor_b


def _factor_states(state: EmaState, *, prior_close: float | None = None) -> dict[str, str]:
    previous_close = state.previous.close if prior_close is None else prior_close
    return {
        "f001": "PASS" if state.current.close > state.current.ema else "FAIL",
        "f002": "PASS" if state.current.ema > state.three_back.ema else "FAIL",
        "f003": (
            "PASS"
            if previous_close <= state.previous.ema and state.current.close > state.current.ema
            else "FAIL"
        ),
    }


def _max_or_zero(values: list[float]) -> float:
    return max(values) if values else 0.0


def _count_over(values: list[float], tolerance: float = TOLERANCE) -> int:
    return sum(value > tolerance for value in values)


def audit_run(
    *,
    raw: bytes,
    bars: list[Bar],
    rehab_events: list[RehabEvent],
    expected_sha256: str = EXPECTED_SHA256,
) -> dict[str, Any]:
    raw_sha256 = sha256_bytes(raw)
    if raw_sha256 != expected_sha256:
        raise ValueError("RUNLOG_SHA256_MISMATCH")
    events = extract_events(raw)
    factor_events = [item for item in events if item.get("event_type") == "FACTOR_EVENT"]
    warmup_events = [item for item in events if item.get("event_type") == "WARMUP_AUDIT"]
    run_ends = [item for item in events if item.get("event_type") == "RUN_END"]
    errors = [item for item in events if item.get("event_type") == "ERROR"]
    day_ends = [item for item in events if item.get("event_type") == "DAY_END"]
    if len(warmup_events) != 1 or len(run_ends) != 1:
        raise ValueError("RUN_CONTROL_EVENT_COUNT_MISMATCH")
    if len(factor_events) != EXPECTED_FACTOR_EVENTS:
        raise ValueError("FACTOR_EVENT_COUNT_MISMATCH")

    ordered_bars = sorted(bars, key=lambda item: item.time_key)
    bar_lookup = {item.time_key: item for item in ordered_bars}
    bar_position = {item.time_key: index for index, item in enumerate(ordered_bars)}
    rehab_lookup = {item.ex_div_date: item for item in rehab_events}
    warmup_bars = [item for item in ordered_bars if SYSTEM_START <= item.date < TRAIN_START]
    warmup_dates = sorted({item.date for item in warmup_bars})
    warmup_last = {day: [item for item in warmup_bars if item.date == day][-1] for day in warmup_dates}
    rth_outside = [item.time_key for item in ordered_bars if item.clock < "09:35" or item.clock > "16:00"]

    signal_diffs: list[float] = []
    target_diffs: list[float] = []
    select2_diffs: list[float] = []
    select3_diffs: list[float] = []
    first_events = [item for item in factor_events if str(item["signal_time_et"]).endswith("T09:35:00")]
    for event in factor_events:
        signal_key = str(event["signal_time_et"])
        signal_bar = bar_lookup.get(signal_key)
        if signal_bar is None:
            raise ValueError("MISSING_OPEND_SIGNAL_BAR:" + signal_key)
        signal_diffs.append(abs(float(event["signal_close"]) - signal_bar.close))
        for horizon in (3, 6, 12):
            target_key = str(event[f"target_{horizon}_et"])
            target_bar = bar_lookup.get(target_key)
            if target_bar is None:
                raise ValueError("MISSING_OPEND_TARGET_BAR:" + target_key)
            target_diffs.append(abs(float(event[f"target_{horizon}_close"]) - target_bar.close))
    for event in first_events:
        signal_key = str(event["signal_time_et"])
        index = bar_position[signal_key]
        if index == 0:
            raise ValueError("MISSING_PRIOR_BAR:" + signal_key)
        current = ordered_bars[index]
        prior = ordered_bars[index - 1]
        select2_diffs.append(abs(float(event["signal_close"]) - current.close))
        expected_prior = expected_adjusted_prior_close(prior.close, rehab_lookup.get(current.date))
        select3_diffs.append(abs(float(event["close_1"]) - expected_prior))

    full_long = build_dynamic_ema_states(ordered_bars, rehab_events, start_date=SYSTEM_START)
    full_short = build_dynamic_ema_states(ordered_bars, rehab_events, start_date=SENSITIVITY_START)
    skip_long = build_skip_final_ema_states(ordered_bars, start_date=SYSTEM_START)
    skip_short = build_skip_final_ema_states(ordered_bars, start_date=SENSITIVITY_START)
    platform_long_diffs: list[float] = []
    platform_short_diffs: list[float] = []
    platform_ema1_diffs: list[float] = []
    platform_ema3_diffs: list[float] = []
    logged_skip_long_diffs: list[float] = []
    logged_skip_short_diffs: list[float] = []
    corrected_state_mismatches = {"f001": 0, "f002": 0, "f003": 0}
    logged_skip_state_mismatches = {"f001": 0, "f002": 0, "f003": 0}
    for event in factor_events:
        key = str(event["signal_time_et"])
        long_state = full_long[key]
        short_state = full_short[key]
        skipped_long_state = skip_long[key]
        skipped_short_state = skip_short[key]
        platform_long_diffs.append(abs(float(event["ema20_platform_0"]) - long_state.current.ema))
        platform_short_diffs.append(abs(float(event["ema20_platform_0"]) - short_state.current.ema))
        platform_ema1_diffs.append(abs(float(event["ema20_platform_1"]) - long_state.previous.ema))
        platform_ema3_diffs.append(abs(float(event["ema20_platform_3"]) - long_state.three_back.ema))
        logged_skip_long_diffs.append(
            abs(float(event["ema20_system_start_0"]) - skipped_long_state.current.ema)
        )
        logged_skip_short_diffs.append(
            abs(float(event["ema20_sensitivity_start_0"]) - skipped_short_state.current.ema)
        )
        corrected_states = _factor_states(long_state)
        logged_skip_states = _factor_states(
            skipped_long_state,
            prior_close=float(event["close_1"]),
        )
        for factor in corrected_state_mismatches:
            if corrected_states[factor] != event[factor + "_state"]:
                corrected_state_mismatches[factor] += 1
            if logged_skip_states[factor] != event[factor + "_system_state"]:
                logged_skip_state_mismatches[factor] += 1

    warmup = warmup_events[0]
    run_end = run_ends[0]
    incomplete_days = [item for item in day_ends if item.get("status") != "COMPLETE"]
    label_count = len(factor_events) * 3
    metrics = {
        "raw_event_counts": {
            "all_marked": len(events),
            "factor_events": len(factor_events),
            "labels": label_count,
            "day_ends": len(day_ends),
            "errors": len(errors),
        },
        "raw_status_preserved": {
            "warmup_audit_status": warmup.get("status"),
            "warmup_bars_before_train": int(warmup["warmup_bars_before_train"]),
            "run_end_status": run_end.get("status"),
            "incomplete_day_count": len(incomplete_days),
            "error_codes": [str(item.get("code")) for item in errors],
        },
        "opend_coverage": {
            "bars": len(ordered_bars),
            "sessions": len({item.date for item in ordered_bars}),
            "warmup_bars": len(warmup_bars),
            "warmup_sessions": len(warmup_dates),
            "warmup_last_label_counts": {
                label: sum(item.clock == label for item in warmup_last.values())
                for label in ("13:00", "16:00")
            },
            "outside_rth_label_range": len(rth_outside),
        },
        "price_alignment": {
            "signal_compared": len(signal_diffs),
            "signal_mismatch_gt_1e_8": _count_over(signal_diffs),
            "signal_max_abs_diff": _max_or_zero(signal_diffs),
            "target_compared": len(target_diffs),
            "target_mismatch_gt_1e_8": _count_over(target_diffs),
            "target_max_abs_diff": _max_or_zero(target_diffs),
        },
        "select_identity": {
            "sessions": len(first_events),
            "select2_current_0935_mismatch_gt_1e_8": _count_over(select2_diffs),
            "select2_max_abs_diff": _max_or_zero(select2_diffs),
            "select3_prior_session_final_mismatch_gt_1e_8": _count_over(select3_diffs),
            "select3_max_abs_diff": _max_or_zero(select3_diffs),
        },
        "ema_alignment": {
            "platform_vs_full_long_max_abs_diff": _max_or_zero(platform_long_diffs),
            "platform_vs_full_long_mismatch_gt_1e_8": _count_over(platform_long_diffs),
            "platform_vs_full_short_max_abs_diff": _max_or_zero(platform_short_diffs),
            "platform_vs_full_short_mismatch_gt_1e_8": _count_over(platform_short_diffs),
            "platform_ema1_max_abs_diff": _max_or_zero(platform_ema1_diffs),
            "platform_ema3_max_abs_diff": _max_or_zero(platform_ema3_diffs),
            "logged_system_vs_skip_close_max_abs_diff": _max_or_zero(logged_skip_long_diffs),
            "logged_sensitivity_vs_skip_close_max_abs_diff": _max_or_zero(logged_skip_short_diffs),
            "corrected_state_mismatches": corrected_state_mismatches,
            "logged_skip_state_mismatches": logged_skip_state_mismatches,
        },
    }
    supported = (
        label_count == EXPECTED_LABELS
        and len(warmup_bars) == EXPECTED_WARMUP_BARS
        and len(warmup_dates) == EXPECTED_WARMUP_SESSIONS
        and int(warmup["warmup_bars_before_train"]) == EXPECTED_WARMUP_BARS - EXPECTED_WARMUP_SESSIONS
        and _count_over(signal_diffs) == 0
        and _count_over(target_diffs) == 0
        and _count_over(select2_diffs) == 0
        and _count_over(select3_diffs) == 0
        and _count_over(platform_long_diffs) == 0
        and _count_over(platform_short_diffs) == 0
        and all(value == 0 for value in corrected_state_mismatches.values())
        and _count_over(logged_skip_long_diffs) == 0
        and _count_over(logged_skip_short_diffs) == 0
        and all(value == 0 for value in logged_skip_state_mismatches.values())
    )
    return {
        "audit_contract": "C1_TRAIN_EMA_SUPPLEMENT_AUDIT_V1",
        "status": "SUPPORTED" if supported else "NOT_SUPPORTED",
        "raw_run_sha256": raw_sha256,
        "raw_run_status_preserved": "INCOMPLETE",
        "dashboard_validation_upgrade": "PROHIBITED",
        "edge_claim": "PROHIBITED",
        "query_contract": {
            "symbol": "US.SPY",
            "bar_type": "K_5M",
            "session": "RTH",
            "extended_time": False,
            "historical_autype": "NONE",
            "adjustment": "AS_OF_DYNAMIC_FORWARD_FROM_GET_REHAB",
            "time_label": "America/New_York bar end",
            "start": SYSTEM_START,
            "end": TRAIN_END,
        },
        "rehab_events": [asdict(item) for item in sorted(rehab_events, key=lambda item: item.ex_div_date)],
        "metrics": metrics,
    }


def fetch_opend_evidence(host: str, port: int) -> tuple[list[Bar], list[RehabEvent], str]:
    from futu import AuType, KLType, OpenQuoteContext, RET_OK, __version__ as futu_version

    context = OpenQuoteContext(host=host, port=port)
    frames: list[Any] = []
    page_key: Any = None
    seen_keys: set[str] = set()
    try:
        while True:
            ret, data, next_key = context.request_history_kline(
                code="US.SPY",
                start=SYSTEM_START,
                end=TRAIN_END,
                ktype=KLType.K_5M,
                autype=AuType.NONE,
                max_count=1000,
                page_req_key=page_key,
                extended_time=False,
            )
            if ret != RET_OK:
                raise RuntimeError("OPEND_HISTORY_FAILED:" + str(data))
            frames.append(data[["time_key", "open", "high", "low", "close"]].copy())
            if next_key is None:
                break
            token = repr(next_key)
            if token in seen_keys:
                raise RuntimeError("OPEND_REPEATED_PAGE_TOKEN")
            seen_keys.add(token)
            page_key = next_key
        ret, rehab_frame = context.get_rehab("US.SPY")
        if ret != RET_OK:
            raise RuntimeError("OPEND_REHAB_FAILED:" + str(rehab_frame))
    finally:
        context.close()

    import pandas as pd

    frame = pd.concat(frames, ignore_index=True)
    frame = frame.drop_duplicates("time_key").sort_values("time_key")
    bars = [
        Bar(
            time_key=str(row.time_key).replace(" ", "T"),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
        )
        for row in frame.itertuples(index=False)
    ]
    rehab_events = [
        RehabEvent(
            ex_div_date=str(row.ex_div_date),
            forward_adj_factor_a=float(row.forward_adj_factorA),
            forward_adj_factor_b=float(row.forward_adj_factorB),
            per_cash_div=(None if pd.isna(row.per_cash_div) else float(row.per_cash_div)),
        )
        for row in rehab_frame.itertuples(index=False)
        if SYSTEM_START <= str(row.ex_div_date) <= TRAIN_END
    ]
    return bars, rehab_events, str(futu_version)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="")
    temporary.replace(path)


def _csv_text(fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> str:
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def render_report(summary: dict[str, Any]) -> str:
    metrics = summary["metrics"]
    raw_status = metrics["raw_status_preserved"]
    coverage = metrics["opend_coverage"]
    prices = metrics["price_alignment"]
    identity = metrics["select_identity"]
    ema = metrics["ema_alignment"]
    return f"""# C1 TRAIN V1 EMA补充审计

## 结论

- 补充审计：`{summary['status']}`
- 原始运行状态保持：`{summary['raw_run_status_preserved']}`
- Dashboard直接升级：`{summary['dashboard_validation_upgrade']}`
- Edge结论：`{summary['edge_claim']}`
- 原始CSV SHA256：`{summary['raw_run_sha256']}`

本报告只补充验证EMA数据资格，不改写原始CSV、`WARMUP_AUDIT`、`RUN_END`、数据库或Gate状态。

## 原始运行

- 原始预热柱：{raw_status['warmup_bars_before_train']}；预期：{EXPECTED_WARMUP_BARS}。
- 原始预热状态：`{raw_status['warmup_audit_status']}`。
- 原始RUN_END：`{raw_status['run_end_status']}`。
- ERROR：{', '.join(raw_status['error_codes'])}。
- 共享事件/标签：{metrics['raw_event_counts']['factor_events']} / {metrics['raw_event_counts']['labels']}。

## OpenD只读证据

- US.SPY、5分钟、RTH、`extended_time=False`、历史价格`AuType.NONE`。
- 时间戳：America/New_York柱结束时间。
- 系统区间：{coverage['sessions']}个交易日、{coverage['bars']}根K线。
- 预热区间：{coverage['warmup_sessions']}个交易日、{coverage['warmup_bars']}根K线。
- 预热最后柱：13:00共{coverage['warmup_last_label_counts']['13:00']}日，16:00共{coverage['warmup_last_label_counts']['16:00']}日。
- RTH标签范围外：{coverage['outside_rth_label_range']}根。

## 价格与select身份

- 信号价：{prices['signal_compared']}条，误差超1e-8为{prices['signal_mismatch_gt_1e_8']}，最大绝对误差{prices['signal_max_abs_diff']:.12g}。
- 目标价：{prices['target_compared']}条，误差超1e-8为{prices['target_mismatch_gt_1e_8']}，最大绝对误差{prices['target_max_abs_diff']:.12g}。
- 09:35 `select=2`：{identity['sessions']}日，身份误差{identity['select2_current_0935_mismatch_gt_1e_8']}。
- 09:35 `select=3`：按当日除权因子还原上一交易日最后一根，身份误差{identity['select3_prior_session_final_mismatch_gt_1e_8']}。

## EMA递推

- OpenD NONE价格加`get_rehab()`逐日动态前复权后，长线EMA最大误差：{ema['platform_vs_full_long_max_abs_diff']:.12g}。
- 短线EMA最大误差：{ema['platform_vs_full_short_max_abs_diff']:.12g}。
- 修正递推与平台F001/F002/F003状态差异：{json.dumps(ema['corrected_state_mismatches'], ensure_ascii=False, sort_keys=True)}。
- 每日删除最后一根柱的重建与原日志长线EMA最大误差：{ema['logged_system_vs_skip_close_max_abs_diff']:.12g}。
- 每日删除最后一根柱的重建与原日志短线EMA最大误差：{ema['logged_sensitivity_vs_skip_close_max_abs_diff']:.12g}。

## 限制

本报告证明现有TRAIN事件、标签、平台EMA及因子状态可以独立重建；它不把原始`INCOMPLETE`改成`VALIDATED`，不允许进入Validation/OOS，也不构成Edge证据。
"""


def write_evidence(
    *,
    output_dir: Path,
    summary: dict[str, Any],
    bars: list[Bar],
    rehab_events: list[RehabEvent],
    futu_version: str,
    script_path: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    bars_path = output_dir / "opend_5m_ohlc.csv"
    rehab_path = output_dir / "opend_rehab.csv"
    summary_path = output_dir / "audit_summary.json"
    report_path = output_dir / "REPORT.md"
    _atomic_write(
        bars_path,
        _csv_text(
            ["time_key", "open", "high", "low", "close"],
            (asdict(item) for item in bars),
        ),
    )
    _atomic_write(
        rehab_path,
        _csv_text(
            ["ex_div_date", "forward_adj_factor_a", "forward_adj_factor_b", "per_cash_div"],
            (asdict(item) for item in rehab_events),
        ),
    )
    _atomic_write(summary_path, json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _atomic_write(report_path, render_report(summary))
    artifacts = [bars_path, rehab_path, summary_path, report_path]
    manifest = {
        "audit_contract": summary["audit_contract"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "futu_sdk_version": futu_version,
        "script_normalized_sha256": normalized_text_sha256(script_path),
        "raw_run_sha256": summary["raw_run_sha256"],
        "query_contract": summary["query_contract"],
        "artifacts": {
            path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in artifacts
        },
        "raw_run_status_preserved": "INCOMPLETE",
        "dashboard_validation_upgrade": "PROHIBITED",
        "edge_claim": "PROHIBITED",
    }
    _atomic_write(output_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="C1 TRAIN V1 EMA只读补充审计")
    parser.add_argument("--runlog", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-sha256", default=EXPECTED_SHA256)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11111)
    args = parser.parse_args()
    raw = args.runlog.read_bytes()
    bars, rehab_events, futu_version = fetch_opend_evidence(args.host, args.port)
    summary = audit_run(
        raw=raw,
        bars=bars,
        rehab_events=rehab_events,
        expected_sha256=args.expected_sha256,
    )
    write_evidence(
        output_dir=args.output_dir,
        summary=summary,
        bars=bars,
        rehab_events=rehab_events,
        futu_version=futu_version,
        script_path=Path(__file__),
    )
    print(json.dumps({"status": summary["status"], "output_dir": str(args.output_dir)}, ensure_ascii=False))
    return 0 if summary["status"] == "SUPPORTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
