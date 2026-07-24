"""Deterministic evidence checks for Phase 1 backtest outputs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .data_quality import DataQualityError, validate_ohlcv
from .pipeline_models import (
    AuditIssue,
    AuditReport,
    AuditStatus,
    CapabilityResult,
    CapabilityStatus,
    StrategySpec,
)


@dataclass(frozen=True)
class AuditContext:
    spec: StrategySpec
    capability: CapabilityResult
    data: pd.DataFrame
    equity: pd.DataFrame
    trades: pd.DataFrame
    strategy_metrics: Mapping[str, Any]
    benchmark_return: float
    manifest: Mapping[str, Any]
    artifact_paths: Mapping[str, Path]


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a deterministic input artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_backtest(context: AuditContext) -> AuditReport:
    if context.capability.status is not CapabilityStatus.SUPPORTED:
        return AuditReport(
            status=AuditStatus(context.capability.status.value),
            checks={},
            issues=tuple(
                AuditIssue("CAPABILITY_BLOCKER", "ERROR", reason)
                for reason in context.capability.reasons
            ),
            warnings=(),
        )

    checks: dict[str, bool] = {}
    issues: list[AuditIssue] = []
    warnings: list[str] = []
    try:
        warnings.extend(validate_ohlcv(context.data))
        checks["data_quality"] = True
    except DataQualityError as error:
        checks["data_quality"] = False
        issues.append(AuditIssue("DATA_QUALITY_FAILURE", "ERROR", str(error)))

    for name, checker in (
        ("next_bar_fill", _check_next_bar_fill),
        ("costs", _check_costs),
        ("benchmark", _check_benchmark),
        ("optimization", _check_optimization),
        ("manifest", _check_manifest),
        ("artifacts", _check_artifacts),
        ("oos_boundary", _check_oos_boundary),
        ("sample_and_concentration", _check_sample_and_concentration),
        ("reproducibility", _check_reproducibility),
    ):
        passed, new_issues, new_warnings = checker(context)
        checks[name] = passed
        issues.extend(new_issues)
        warnings.extend(new_warnings)

    status = AuditStatus.FAIL if any(issue.severity == "ERROR" for issue in issues) else (
        AuditStatus.CONDITIONAL_PASS if issues or warnings else AuditStatus.PASS
    )
    return AuditReport(status, checks, tuple(issues), tuple(warnings))


def _check_next_bar_fill(context: AuditContext) -> tuple[bool, list[AuditIssue], list[str]]:
    if context.spec.fill_timing != "next_bar" or context.manifest.get("fill_timing") != "next_bar":
        return False, [AuditIssue(
            "SAME_BAR_SIGNAL_FILL", "ERROR", "strategy and manifest must declare next_bar fills"
        )], []
    if context.trades.empty:
        return True, [], []
    required = ("timestamp_utc", "signal_timestamp_utc")
    if any(column not in context.trades for column in required):
        return False, [AuditIssue(
            "SAME_BAR_SIGNAL_FILL", "ERROR", "trades are missing signal or fill timestamps"
        )], []
    fills = pd.to_datetime(context.trades["timestamp_utc"], utc=True, errors="coerce")
    signals = pd.to_datetime(
        context.trades["signal_timestamp_utc"], utc=True, errors="coerce"
    )
    if fills.isna().any() or signals.isna().any() or not (fills > signals).all():
        return False, [AuditIssue(
            "SAME_BAR_SIGNAL_FILL", "ERROR", "every fill must be strictly after its signal"
        )], []
    return True, [], []


def _check_costs(context: AuditContext) -> tuple[bool, list[AuditIssue], list[str]]:
    if context.trades.empty:
        return True, [], []
    required = (
        "side", "shares", "market_open", "execution_price", "gross_notional",
        "commission", "slippage_bps",
    )
    if any(column not in context.trades for column in required):
        return False, [AuditIssue(
            "COST_MISMATCH", "ERROR", "trades are missing execution-price or cost evidence"
        )], []
    try:
        for _, trade in context.trades.iterrows():
            side = str(trade["side"]).upper()
            market_open = float(trade["market_open"])
            execution_price = float(trade["execution_price"])
            shares = abs(float(trade["shares"]))
            if side not in {"BUY", "SELL"} or not all(
                math.isfinite(value) for value in (market_open, execution_price, shares)
            ):
                raise ValueError("invalid fill evidence")
            direction = 1 if side == "BUY" else -1
            expected_execution = market_open * (
                1 + direction * context.spec.slippage_bps / 10_000
            )
            expected_notional = shares * execution_price
            expected_commission = expected_notional * context.spec.commission_bps / 10_000
            if not math.isclose(
                execution_price, expected_execution, rel_tol=1e-9, abs_tol=1e-9
            ) or not math.isclose(
                float(trade["gross_notional"]), expected_notional, rel_tol=1e-9, abs_tol=1e-9
            ) or not math.isclose(
                float(trade["commission"]), expected_commission, rel_tol=1e-9, abs_tol=1e-9
            ) or not math.isclose(
                float(trade["slippage_bps"]), context.spec.slippage_bps, rel_tol=1e-9, abs_tol=1e-9
            ):
                raise ValueError("configured costs do not match trade evidence")
    except (TypeError, ValueError, OverflowError):
        return False, [AuditIssue(
            "COST_MISMATCH", "ERROR", "configured costs do not match trade evidence"
        )], []
    return True, [], []


def _check_benchmark(context: AuditContext) -> tuple[bool, list[AuditIssue], list[str]]:
    manifest = context.manifest
    expected = {
        "benchmark": context.spec.benchmark,
        "symbol": context.spec.symbol,
        "timeframe": context.spec.timeframe,
        "start_date": context.spec.start_date.isoformat(),
        "end_date": context.spec.end_date.isoformat(),
        "commission_bps": context.spec.commission_bps,
        "slippage_bps": context.spec.slippage_bps,
    }
    matches = all(manifest.get(field) == value for field, value in expected.items())
    try:
        has_return = context.benchmark_return is not None and math.isfinite(float(context.benchmark_return))
    except (TypeError, ValueError, OverflowError):
        has_return = False
    if not matches or not has_return:
        return False, [AuditIssue(
            "BENCHMARK_MISMATCH", "ERROR", "benchmark evidence must use the strategy symbol, dates, and costs"
        )], []
    return True, [], []


def _check_optimization(context: AuditContext) -> tuple[bool, list[AuditIssue], list[str]]:
    if context.spec.optimization_allowed or context.manifest.get("optimization_allowed") is not False:
        return False, [AuditIssue(
            "OPTIMIZATION_ENABLED", "ERROR", "optimization must be disabled for both spec and manifest"
        )], []
    return True, [], []


def _check_manifest(context: AuditContext) -> tuple[bool, list[AuditIssue], list[str]]:
    required = (
        "strategy_config_hash", "data_hash", "code_commit", "fill_timing",
        "commission_bps", "slippage_bps", "generated_at_utc",
    )
    missing = [field for field in required if not _is_present(context.manifest.get(field))]
    if missing:
        return False, [AuditIssue(
            "MISSING_MANIFEST_FIELD", "ERROR", f"missing manifest fields: {', '.join(missing)}"
        )], []
    return True, [], []


def _check_artifacts(context: AuditContext) -> tuple[bool, list[AuditIssue], list[str]]:
    required = {"summary", "equity", "trades", "manifest", "audit"}
    missing = sorted(
        name for name in required
        if name not in context.artifact_paths
        or context.artifact_paths[name] is None
        or not Path(context.artifact_paths[name]).is_file()
    )
    if missing:
        return False, [AuditIssue(
            "MISSING_ARTIFACT", "ERROR", f"missing artifacts: {', '.join(sorted(missing))}"
        )], []
    return True, [], []


def _check_oos_boundary(context: AuditContext) -> tuple[bool, list[AuditIssue], list[str]]:
    in_sample = context.spec.in_sample_period
    out_of_sample = context.spec.out_of_sample_period
    if in_sample is None and out_of_sample is None:
        return False, [AuditIssue(
            "OOS_BOUNDARY_UNVERIFIED", "WARNING",
            "OOS boundary is not configured; no out-of-sample pass claim is allowed",
        )], []
    if in_sample is None or out_of_sample is None:
        return False, [AuditIssue(
            "OOS_BOUNDARY_FAILURE", "ERROR",
            "both in-sample and locked OOS periods are required when either is supplied",
        )], []
    try:
        train_start, train_end = in_sample
        oos_start, oos_end = out_of_sample
        ordered = (
            context.spec.start_date <= train_start <= train_end < oos_start <= oos_end
            <= context.spec.end_date
        )
    except (TypeError, ValueError):
        ordered = False
    if not ordered:
        return False, [AuditIssue(
            "OOS_BOUNDARY_FAILURE", "ERROR",
            "train and locked OOS periods must be ordered, non-overlapping, and within the strategy range",
        )], []

    manifest = context.manifest
    if (
        manifest.get("oos_locked") is not True
        or manifest.get("locked_oos_start") != oos_start.isoformat()
        or manifest.get("locked_oos_end") != oos_end.isoformat()
    ):
        return False, [AuditIssue(
            "OOS_BOUNDARY_FAILURE", "ERROR",
            "manifest must preserve the configured locked OOS boundary",
        )], []

    for name, frame, columns in (
        ("data", context.data, ("timestamp_utc",)),
        ("equity", context.equity, ("timestamp_utc",)),
        ("trades", context.trades, ("timestamp_utc", "signal_timestamp_utc")),
    ):
        present_columns = [column for column in columns if column in frame]
        for column in present_columns:
            timestamps = pd.to_datetime(frame[column], utc=True, errors="coerce")
            dates = timestamps.dt.date
            if timestamps.isna().any() or not dates.between(train_start, oos_end).all():
                return False, [AuditIssue(
                    "OOS_BOUNDARY_FAILURE", "ERROR",
                    f"{name} {column} evidence extends outside the locked train/OOS boundary",
                )], []
    return True, [], []


def _check_sample_and_concentration(
    context: AuditContext,
) -> tuple[bool, list[AuditIssue], list[str]]:
    if context.trades.empty:
        return False, [AuditIssue("NO_TRADES", "WARNING", "backtest produced no fills")], []

    issues: list[AuditIssue] = []
    closed_pnls = _closed_trade_pnls(context.trades)
    absolute_pnl = sum(abs(pnl) for pnl in closed_pnls)
    if closed_pnls and absolute_pnl > 0 and max(abs(pnl) for pnl in closed_pnls) / absolute_pnl >= 0.80:
        issues.append(AuditIssue(
            "SINGLE_TRADE_DOMINANCE", "WARNING", "one closed trade contributes at least 80% of absolute PnL"
        ))

    positive_growth = _annual_positive_growth(context.equity)
    total_growth = sum(positive_growth.values())
    if total_growth > 0 and max(positive_growth.values()) / total_growth >= 0.80:
        issues.append(AuditIssue(
            "ANNUAL_RETURN_CONCENTRATION", "WARNING",
            "one calendar year contributes at least 80% of positive equity growth",
        ))
    return not issues, issues, []


def _check_reproducibility(context: AuditContext) -> tuple[bool, list[AuditIssue], list[str]]:
    manifest = context.manifest
    hashes = ("strategy_config_hash", "data_hash")
    if any(not _is_present(manifest.get(field)) for field in hashes):
        return False, [AuditIssue(
            "MISSING_MANIFEST_FIELD", "ERROR", "reproducibility requires non-empty input hashes"
        )], []
    data_path = manifest.get("data_path")
    if data_path is None:
        return True, [], []
    try:
        actual_hash = sha256_file(Path(data_path))
    except (OSError, TypeError, ValueError):
        return False, [AuditIssue(
            "HASH_MISMATCH", "ERROR", "manifest data_path cannot be hashed"
        )], []
    if actual_hash != manifest["data_hash"]:
        return False, [AuditIssue(
            "HASH_MISMATCH", "ERROR", "current data hash differs from manifest"
        )], []
    return True, [], []


def _closed_trade_pnls(trades: pd.DataFrame) -> list[float]:
    if not {"side", "net_cash_flow"}.issubset(trades.columns):
        return []
    entry_cost: float | None = None
    outcomes: list[float] = []
    for _, trade in trades.iterrows():
        if trade["side"] == "BUY":
            entry_cost = -float(trade["net_cash_flow"])
        elif trade["side"] == "SELL" and entry_cost is not None:
            outcomes.append(float(trade["net_cash_flow"]) - entry_cost)
            entry_cost = None
    return outcomes


def _annual_positive_growth(equity: pd.DataFrame) -> dict[int, float]:
    if not {"timestamp_utc", "equity"}.issubset(equity.columns) or equity.empty:
        return {}
    timestamps = pd.to_datetime(equity["timestamp_utc"], utc=True, errors="coerce")
    values = pd.to_numeric(equity["equity"], errors="coerce")
    if timestamps.isna().any() or values.isna().any():
        return {}
    growth = values.diff().fillna(0.0).clip(lower=0.0)
    return {
        int(year): float(amount)
        for year, amount in growth.groupby(timestamps.dt.year).sum().items()
    }


def _is_present(value: Any) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))
