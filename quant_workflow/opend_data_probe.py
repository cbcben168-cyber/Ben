"""Bounded quote-only single-session probe, not a backtest or a full data gate.

Example: py -3.14 quant_workflow/opend_data_probe.py --date 2026-10-06
         --output quant_workflow/artifacts/spy-20261006
Requires existing futu-api, pandas, numpy and exchange-calendars installations.
No subscription, account, trade, scheduler, or automatic retry operations.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform

import exchange_calendars as xcals
import numpy as np
import pandas as pd


FIELDS = ["code", "time_key", "open", "high", "low", "close", "volume"]
PRICES = ["open", "high", "low", "close"]
PRICE_TOLERANCE = 1e-8  # Fixed before observing results; raw NONE prices only.


def expected_grid(day, minutes):
    calendar = xcals.get_calendar("XNYS")
    opening = calendar.session_open(day)
    closing = calendar.session_close(day)
    return pd.date_range(opening, closing, freq=f"{minutes}min", inclusive="left").as_unit("ns")


def validate_frame(frame, day, minutes, symbol):
    result = {"rows": len(frame), "errors": [], "warnings": [],
              "label_semantics": "NOT_VERIFIED"}
    errors = result["errors"]
    missing = sorted(set(FIELDS) - set(frame.columns))
    if missing or frame.empty:
        errors.append("EMPTY_OR_MISSING_COLUMNS")
        result["missing_columns"] = missing
        return result, None
    if not frame["code"].eq(symbol).all():
        errors.append("SYMBOL_MISMATCH")
    numeric = frame[PRICES + ["volume"]].apply(pd.to_numeric, errors="coerce")
    bools = frame[PRICES + ["volume"]].map(lambda v: isinstance(v, (bool, np.bool_)))
    if bools.any().any():
        errors.append("BOOLEAN_VALUE")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        errors.append("NONFINITE_OHLCV")
    prices = numeric[PRICES]
    if (prices <= 0).any().any() or (prices["low"] > prices[["open", "close"]].min(axis=1)).any() or (prices["high"] < prices[["open", "close"]].max(axis=1)).any():
        errors.append("INVALID_OHLC")
    if (numeric["volume"] < 0).any():
        errors.append("NEGATIVE_VOLUME")
    if (numeric["volume"] == 0).any():
        result["warnings"].append("ZERO_VOLUME_REQUIRES_REVIEW")
    try:
        labels = pd.DatetimeIndex(pd.to_datetime(frame["time_key"], errors="raise"))
        if labels.tz is not None:
            raise ValueError("expected provider naive US market timestamps")
        labels = labels.tz_localize("America/New_York", ambiguous="raise", nonexistent="raise").tz_convert("UTC").as_unit("ns")
        if labels.isna().any():
            raise ValueError("missing timestamp")
    except (ValueError, TypeError):
        errors.append("INVALID_TIMESTAMP")
        return result, None
    result["first_label_utc"] = labels[0].isoformat()
    result["last_label_utc"] = labels[-1].isoformat()
    if labels.has_duplicates:
        errors.append("DUPLICATE_TIMESTAMP")
    if not labels.is_monotonic_increasing:
        errors.append("UNSORTED_TIMESTAMP")
    starts = expected_grid(day, minutes)
    ends = starts + pd.Timedelta(minutes=minutes)
    result["expected_rows"] = len(starts)
    result["coverage_candidates"] = {
        name: {"missing": len(grid.difference(labels)), "unexpected": len(labels.difference(grid))}
        for name, grid in (("start", starts), ("end", ends))
    }
    if labels.equals(starts):
        result["label_semantics"] = "start"
    elif labels.equals(ends):
        result["label_semantics"] = "end"
    else:
        errors.append("COVERAGE_OR_LABELS_UNRESOLVED")
    if errors:
        return result, None
    normalized = numeric.copy()
    normalized.index = starts
    return result, normalized


def audit_frames(one, five, day, symbol):
    check1, bars1 = validate_frame(one, day, 1, symbol)
    check5, bars5 = validate_frame(five, day, 5, symbol)
    result = {"status": "FAILED_DATA", "1m": check1, "5m": check5,
              "cross_period": "NOT_VERIFIED", "strategy_qualification": "NOT_VERIFIED"}
    if bars1 is None or bars5 is None:
        return result
    derived = bars1.resample("5min", origin=bars1.index[0]).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    delta = (derived - bars5).abs()
    price_bad = (delta[PRICES] > PRICE_TOLERANCE).any(axis=1)
    volume_bad = delta["volume"] != 0
    examples = []
    for timestamp in delta.index[price_bad | volume_bad][:10]:
        examples.append({"bar_start_utc": timestamp.isoformat(),
                         "derived_volume": float(derived.at[timestamp, "volume"]),
                         "native_volume": float(bars5.at[timestamp, "volume"]),
                         "max_price_difference": float(delta.loc[timestamp, PRICES].max())})
    result["cross_period"] = {
        "price_tolerance": PRICE_TOLERANCE, "volume_tolerance": 0,
        "price_mismatch_bars": int(price_bad.sum()),
        "volume_mismatch_bars": int(volume_bad.sum()), "examples": examples,
    }
    if not price_bad.any() and not volume_bad.any():
        result["status"] = "NOT_VERIFIED" if check1["warnings"] or check5["warnings"] else "SAMPLE_CHECKS_PASS"
    return result


def fetch_history(context, symbol, day, ktype):
    from futu import AuType, RET_OK, Session

    pages, seen, page_key = [], set(), None
    for _ in range(4):
        ret, data, next_key = context.request_history_kline(
            symbol, start=day, end=day, ktype=ktype, autype=AuType.NONE,
            max_count=1000, page_req_key=page_key, session=Session.RTH)
        if ret != RET_OK:
            raise RuntimeError("HISTORY_REQUEST_REJECTED")  # Never persist raw server errors.
        if not set(FIELDS).issubset(data.columns):
            raise RuntimeError("HISTORY_SCHEMA_MISMATCH")
        pages.append(data[FIELDS].copy())
        if next_key is None:
            return pd.concat(pages, ignore_index=True)
        if data.empty or next_key in seen:
            raise RuntimeError("PAGINATION_NO_PROGRESS")
        seen.add(next_key)
        page_key = next_key
    raise RuntimeError("PAGINATION_LIMIT")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", choices=["US.SPY", "US.QQQ"], default="US.SPY")
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Calendar and end-of-session guards run before connecting or creating artifacts.
    expected_grid(args.date, 1)
    if xcals.get_calendar("XNYS").session_close(args.date) >= pd.Timestamp.now(tz="UTC"):
        parser.error("Only completed historical sessions are allowed")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"status": "BLOCKED", "symbol": args.symbol, "date": args.date,
              "source": "OpenD_history", "host": "127.0.0.1", "port": 11111,
              "session": "RTH", "adjustment": "NONE", "requests": "1m + 5m; max 4 pages each; no retries",
              "collected_at_utc": datetime.now(timezone.utc).isoformat(),
              "python_version": platform.python_version(),
              "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "versions": {n: version(n) for n in ("futu-api", "pandas", "exchange-calendars")},
              "platform_data": "NOT_VERIFIED", "strategy_qualification": "NOT_VERIFIED",
              "limits": ["One session only", "Same provider, not independent accuracy validation",
                         "No platform dynamic-QFQ comparison", "No realtime permission or fill validation"],
              "files": {}}
    context = None
    try:
        from futu import KLType, OpenQuoteContext, SysConfig

        SysConfig.set_all_thread_daemon(True)
        context = OpenQuoteContext(host="127.0.0.1", port=11111)
        frames = []
        for name, ktype in (("1m", KLType.K_1M), ("5m", KLType.K_5M)):
            frame = fetch_history(context, args.symbol, args.date, ktype)
            path = args.output / (name + ".csv")
            frame.to_csv(path, index=False)
            report["files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            frames.append(frame)
        report.update(audit_frames(*frames, args.date, args.symbol))
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["error_code"] = str(exc) if str(exc) in {
            "HISTORY_REQUEST_REJECTED", "HISTORY_SCHEMA_MISMATCH",
            "PAGINATION_NO_PROGRESS", "PAGINATION_LIMIT"} else "PROBE_FAILED"
    finally:
        if context is not None:
            context.close()
        (args.output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(args.output / "report.json")}, ensure_ascii=False))
    return 0 if report["status"] == "SAMPLE_CHECKS_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
