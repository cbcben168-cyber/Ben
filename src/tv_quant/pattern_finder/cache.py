from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from tv_quant.data_quality import DataQualityError, load_standardized_csv
from tv_quant.futu_downloader import QuoteContext, update_futu_csv

from .data_quality import (
    DataQualityReport,
    assess_symbol_data,
    latest_complete_xnys_session,
)
from .flat_base import FlatBaseResult, detect_flat_base
from .universe import PILOT_SYMBOLS, futu_code


DEFAULT_CACHE_ROOT = Path("data/raw/pattern_finder/qfq")


class PatternCacheError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CacheEntry:
    symbol: str
    path: Path
    rows: int
    new_rows: int
    updated_rows: int
    quality: DataQualityReport


def cache_path(cache_root: str | Path, symbol: str) -> Path:
    normalized = symbol.strip().upper()
    futu_code(normalized)
    return Path(cache_root) / f"{normalized}_daily.csv"


def load_cache_entry(
    symbol: str,
    *,
    cache_root: str | Path = DEFAULT_CACHE_ROOT,
    as_of_utc: datetime,
) -> CacheEntry | None:
    normalized = symbol.strip().upper()
    path = cache_path(cache_root, normalized)
    if not path.exists():
        return None
    data, _ = load_standardized_csv(path)
    quality = assess_symbol_data(data, normalized, as_of_utc)
    return CacheEntry(normalized, path, len(data), 0, 0, quality)


def _quality_gate(data: pd.DataFrame, symbol: str, as_of_utc: datetime) -> DataQualityReport:
    report = assess_symbol_data(data, symbol, as_of_utc)
    issues = list(report.errors)
    if report.missing_sessions:
        issues.append(
            "missing XNYS sessions: "
            + ", ".join(day.isoformat() for day in report.missing_sessions)
        )
    if issues:
        raise PatternCacheError("; ".join(issues))
    return report


def refresh_cache_entry(
    symbol: str,
    quote_context: QuoteContext,
    *,
    cache_root: str | Path = DEFAULT_CACHE_ROOT,
    as_of_utc: datetime,
    ret_ok: int = 0,
    ktype: Any = "K_DAY",
    autype: Any = "QFQ",
    sleep: Callable[[float], None] | None = None,
) -> CacheEntry:
    normalized = symbol.strip().upper()
    code = futu_code(normalized)
    destination = cache_path(cache_root, normalized)
    end = latest_complete_xnys_session(as_of_utc)
    if destination.exists():
        existing, _ = load_standardized_csv(destination)
        last_session = pd.to_datetime(existing["timestamp_utc"], utc=True).dt.date.iloc[-1]
        start = last_session - timedelta(days=10)
    else:
        start = end - timedelta(days=550)

    quality: DataQualityReport | None = None

    def validate_before_replace(data: pd.DataFrame) -> None:
        nonlocal quality
        quality = _quality_gate(data, normalized, as_of_utc)

    update_kwargs: dict[str, Any] = {
        "ret_ok": ret_ok,
        "ktype": ktype,
        "autype": autype,
        "allowed_tickers": {normalized},
        "before_replace": validate_before_replace,
    }
    if sleep is not None:
        update_kwargs["sleep"] = sleep

    update = update_futu_csv(
        destination,
        code,
        start,
        end,
        quote_context,
        **update_kwargs,
    )
    if quality is None:
        raise PatternCacheError("data quality gate did not run")
    return CacheEntry(
        symbol=normalized,
        path=update.path,
        rows=update.total_rows,
        new_rows=update.new_rows,
        updated_rows=update.updated_rows,
        quality=quality,
    )


def cache_status_rows(
    cache_root: str | Path = DEFAULT_CACHE_ROOT,
    as_of_utc: datetime | None = None,
) -> tuple[dict[str, object], ...]:
    if as_of_utc is None:
        raise ValueError("as_of_utc is required")

    rows: list[dict[str, object]] = []
    for symbol in PILOT_SYMBOLS:
        try:
            entry = load_cache_entry(
                symbol,
                cache_root=cache_root,
                as_of_utc=as_of_utc,
            )
        except (DataQualityError, ValueError) as error:
            rows.append(
                {
                    "Symbol": symbol,
                    "Cache": "Present",
                    "Rows": 0,
                    "First Session": None,
                    "Last Session": None,
                    "Expected Session": latest_complete_xnys_session(as_of_utc).isoformat(),
                    "Data Quality": "FAIL",
                    "Issues": str(error),
                    "Adjustment": "QFQ",
                }
            )
            continue

        if entry is None:
            rows.append(
                {
                    "Symbol": symbol,
                    "Cache": "Missing",
                    "Rows": 0,
                    "First Session": None,
                    "Last Session": None,
                    "Expected Session": latest_complete_xnys_session(as_of_utc).isoformat(),
                    "Data Quality": "MISSING",
                    "Issues": "Run an explicit Futu refresh",
                    "Adjustment": "QFQ",
                }
            )
            continue

        report = entry.quality
        issues = list(report.errors)
        if report.missing_sessions:
            issues.append(f"{len(report.missing_sessions)} missing XNYS session(s)")
        rows.append(
            {
                "Symbol": symbol,
                "Cache": "Present",
                "Rows": entry.rows,
                "First Session": report.first_session.isoformat() if report.first_session else None,
                "Last Session": report.last_session.isoformat() if report.last_session else None,
                "Expected Session": report.expected_latest_session.isoformat(),
                "Data Quality": "PASS" if report.passed else "FAIL",
                "Issues": "; ".join(issues),
                "Adjustment": "QFQ",
            }
        )
    return tuple(rows)


def _flat_base_fields(result: FlatBaseResult | None) -> dict[str, object]:
    if result is None:
        return {
            "Flat Base": "NO",
            "Base Length": None,
            "Base Start": None,
            "Base End": None,
            "Base Depth": None,
            "Bottom Tests": None,
            "Bottom Tolerance": None,
            "Normalized Slope": None,
            "Support": None,
            "Resistance": None,
            "Resistance Raw": None,
            "Resistance Upper Quantile": None,
            "Resistance Spike Adjusted": None,
            "ATR14 T0": None,
            "Detector Version": None,
        }
    selected = result.selected
    return {
        "Flat Base": "YES" if result.pattern_flat_base else "NO",
        "Base Length": selected.base_length,
        "Base Start": selected.base_start.date().isoformat(),
        "Base End": selected.base_end.date().isoformat(),
        "Base Depth": selected.base_depth_pct,
        "Bottom Tests": selected.bottom_test_count,
        "Bottom Tolerance": selected.bottom_tolerance_pct,
        "Normalized Slope": selected.normalized_slope,
        "Support": selected.support_level,
        "Resistance": selected.resistance_level,
        "Resistance Raw": selected.resistance_raw,
        "Resistance Upper Quantile": selected.resistance_upper_quantile,
        "Resistance Spike Adjusted": selected.resistance_spike_adjusted,
        "ATR14 T0": selected.atr14_t0,
        "Detector Version": result.detector_version,
    }


def flat_base_scan_rows(
    cache_root: str | Path = DEFAULT_CACHE_ROOT,
    as_of_utc: datetime | None = None,
) -> tuple[dict[str, object], ...]:
    """Scan the fixed pilot cache without refreshing or writing any data."""
    if as_of_utc is None:
        raise ValueError("as_of_utc is required")

    rows: list[dict[str, object]] = []
    for symbol in PILOT_SYMBOLS:
        try:
            entry = load_cache_entry(
                symbol,
                cache_root=cache_root,
                as_of_utc=as_of_utc,
            )
        except (DataQualityError, ValueError) as error:
            rows.append(
                {
                    "Symbol": symbol,
                    "Cache": "Present",
                    **_flat_base_fields(None),
                    "Rows": 0,
                    "Data Quality": "FAIL",
                    "Issues": str(error),
                    "Adjustment": "QFQ",
                }
            )
            continue

        if entry is None:
            rows.append(
                {
                    "Symbol": symbol,
                    "Cache": "Missing",
                    **_flat_base_fields(None),
                    "Rows": 0,
                    "Data Quality": "MISSING",
                    "Issues": "Run an explicit Futu refresh",
                    "Adjustment": "QFQ",
                }
            )
            continue

        report = entry.quality
        issues = list(report.errors)
        if report.missing_sessions:
            issues.append(f"{len(report.missing_sessions)} missing XNYS session(s)")
        result: FlatBaseResult | None = None
        quality_status = "PASS" if report.passed else "FAIL"
        if report.passed:
            try:
                data, _ = load_standardized_csv(entry.path)
                result = detect_flat_base(data)
            except (DataQualityError, ValueError) as error:
                quality_status = "FAIL"
                issues.append(str(error))

        rows.append(
            {
                "Symbol": symbol,
                "Cache": "Present",
                **_flat_base_fields(result),
                "Rows": entry.rows,
                "Data Quality": quality_status,
                "Issues": "; ".join(issues),
                "Adjustment": "QFQ",
            }
        )
    return tuple(rows)
