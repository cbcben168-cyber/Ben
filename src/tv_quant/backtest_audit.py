"""Deterministic evidence checks for Phase 1 backtest outputs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .data_quality import DataQualityError, validate_ohlcv
from .contracts.numeric import canonical_decimal
from .pipeline_models import (
    AuditIssue,
    AuditReport,
    AuditStatus,
    CapabilityResult,
    CapabilityStatus,
    StrategySpec,
)
from .run_manifest import HASHED_ARTIFACT_NAMES, canonical_hash


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
    require_artifact_files: bool = True


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
        ("equity_cash_reconciliation", _check_equity_cash_reconciliation),
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
    if "timestamp_utc" not in context.data:
        return False, [AuditIssue(
            "SAME_BAR_SIGNAL_FILL", "ERROR",
            "source data is missing timestamps required for next-bar evidence",
        )], []
    data_timestamps = pd.to_datetime(
        context.data["timestamp_utc"], utc=True, errors="coerce"
    ).reset_index(drop=True)
    if (
        fills.isna().any()
        or signals.isna().any()
        or data_timestamps.isna().any()
        or data_timestamps.duplicated().any()
        or not data_timestamps.is_monotonic_increasing
    ):
        return False, [AuditIssue(
            "SAME_BAR_SIGNAL_FILL", "ERROR",
            "signal, fill, and source-data timestamps must be valid and ordered",
        )], []
    next_timestamp_by_signal = {
        data_timestamps.iloc[index]: data_timestamps.iloc[index + 1]
        for index in range(len(data_timestamps) - 1)
    }
    if any(
        next_timestamp_by_signal.get(signal) != fill
        for signal, fill in zip(signals, fills)
    ):
        return False, [AuditIssue(
            "SAME_BAR_SIGNAL_FILL", "ERROR",
            "every fill must equal the immediate next source-data timestamp after its signal",
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


def _check_equity_cash_reconciliation(
    context: AuditContext,
) -> tuple[bool, list[AuditIssue], list[str]]:
    required_equity = ("timestamp_utc", "cash", "shares", "close", "equity")
    if any(column not in context.equity for column in required_equity):
        return _reconciliation_failure(
            "equity rows are missing timestamp, cash, shares, close, or equity evidence"
        )
    try:
        equity_timestamps = pd.to_datetime(
            context.equity["timestamp_utc"],
            utc=True,
            errors="coerce",
        ).reset_index(drop=True)
        equity_values = {
            column: pd.to_numeric(
                context.equity[column],
                errors="coerce",
            ).reset_index(drop=True)
            for column in ("cash", "shares", "close", "equity")
        }
        if (
            equity_timestamps.empty
            or equity_timestamps.isna().any()
            or equity_timestamps.duplicated().any()
            or not equity_timestamps.is_monotonic_increasing
            or any(values.isna().any() for values in equity_values.values())
        ):
            raise ValueError("invalid equity evidence")
        for cash, shares, close, equity in zip(
            equity_values["cash"],
            equity_values["shares"],
            equity_values["close"],
            equity_values["equity"],
        ):
            numeric_values = (
                float(cash),
                float(shares),
                float(close),
                float(equity),
            )
            if not all(math.isfinite(value) for value in numeric_values):
                raise ValueError("non-finite equity evidence")
            if not math.isclose(
                numeric_values[3],
                numeric_values[0] + numeric_values[1] * numeric_values[2],
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                return _reconciliation_failure(
                    "each equity row must equal cash plus shares times close"
                )

        cash_flows: dict[pd.Timestamp, float] = {}
        if not context.trades.empty:
            required_trades = (
                "timestamp_utc",
                "side",
                "gross_notional",
                "commission",
                "net_cash_flow",
            )
            if any(column not in context.trades for column in required_trades):
                return _reconciliation_failure(
                    "trades are missing cash-flow evidence"
                )
            trade_timestamps = pd.to_datetime(
                context.trades["timestamp_utc"],
                utc=True,
                errors="coerce",
            )
            if trade_timestamps.isna().any():
                raise ValueError("invalid trade timestamp evidence")
            for position, (_, trade) in enumerate(context.trades.iterrows()):
                side = str(trade["side"]).upper()
                gross_notional = float(trade["gross_notional"])
                commission = float(trade["commission"])
                net_cash_flow = float(trade["net_cash_flow"])
                if side not in {"BUY", "SELL"} or not all(
                    math.isfinite(value)
                    for value in (gross_notional, commission, net_cash_flow)
                ):
                    raise ValueError("invalid trade cash-flow evidence")
                expected_flow = (
                    -(gross_notional + commission)
                    if side == "BUY"
                    else gross_notional - commission
                )
                if not math.isclose(
                    net_cash_flow,
                    expected_flow,
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                ):
                    return _reconciliation_failure(
                        "trade net_cash_flow must include gross notional and commission"
                    )
                timestamp = trade_timestamps.iloc[position]
                cash_flows[timestamp] = (
                    cash_flows.get(timestamp, 0.0) + net_cash_flow
                )

        previous_cash = float(context.spec.initial_capital)
        for timestamp, cash in zip(
            equity_timestamps,
            equity_values["cash"],
        ):
            actual_cash = float(cash)
            expected_cash = previous_cash + cash_flows.pop(timestamp, 0.0)
            if not math.isclose(
                actual_cash,
                expected_cash,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                return _reconciliation_failure(
                    "equity cash delta must reflect trade net_cash_flow at each fill timestamp"
                )
            previous_cash = actual_cash
        if cash_flows:
            return _reconciliation_failure(
                "every trade fill must have a matching equity cash row"
            )
    except (TypeError, ValueError, OverflowError):
        return _reconciliation_failure(
            "equity and trade cash-flow evidence is invalid"
        )
    return True, [], []


def _reconciliation_failure(
    message: str,
) -> tuple[bool, list[AuditIssue], list[str]]:
    return False, [
        AuditIssue(
            "EQUITY_CASH_RECONCILIATION_FAILURE",
            "ERROR",
            message,
        )
    ], []


def _check_benchmark(context: AuditContext) -> tuple[bool, list[AuditIssue], list[str]]:
    manifest = context.manifest
    expected = {
        "benchmark": context.spec.benchmark,
        "symbol": context.spec.symbol,
        "timeframe": context.spec.timeframe,
        "start_date": context.spec.start_date.isoformat(),
        "end_date": context.spec.end_date.isoformat(),
        "commission_bps": canonical_decimal(
            str(context.spec.commission_bps), "legacy basis points"
        ),
        "slippage_bps": canonical_decimal(
            str(context.spec.slippage_bps), "legacy basis points"
        ),
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
        "strategy_config_path", "strategy_config_file_hash",
    )
    missing = [field for field in required if not _is_present(context.manifest.get(field))]
    if missing:
        return False, [AuditIssue(
            "MISSING_MANIFEST_FIELD", "ERROR", f"missing manifest fields: {', '.join(missing)}"
        )], []
    return True, [], []


def _check_artifacts(context: AuditContext) -> tuple[bool, list[AuditIssue], list[str]]:
    if not context.require_artifact_files:
        return True, [], []
    required = {
        "summary",
        "equity",
        "trades",
        "manifest",
        "audit",
        "report_zh",
        "strategy_config",
    }
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
    recorded_paths = context.manifest.get("artifact_paths")
    recorded_hashes = context.manifest.get("artifact_hashes")
    if not isinstance(recorded_paths, Mapping) or not isinstance(
        recorded_hashes,
        Mapping,
    ):
        return False, [AuditIssue(
            "HASH_MISMATCH",
            "ERROR",
            "manifest artifact path or hash evidence is missing",
        )], []
    for name in HASHED_ARTIFACT_NAMES:
        actual_path = Path(context.artifact_paths[name])
        try:
            matches = (
                Path(str(recorded_paths.get(name))).resolve()
                == actual_path.resolve()
                and recorded_hashes.get(name) == sha256_file(actual_path)
            )
        except (OSError, TypeError, ValueError):
            matches = False
        if not matches:
            return False, [AuditIssue(
                "HASH_MISMATCH",
                "ERROR",
                f"{name} artifact path or hash differs from manifest",
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

    for name, frame in (
        ("data", context.data),
        ("equity", context.equity),
        ("trades", context.trades),
    ):
        if "timestamp_utc" not in frame:
            return False, [AuditIssue(
                "OOS_BOUNDARY_FAILURE", "ERROR",
                f"{name} is missing timestamp_utc evidence for the locked OOS interval",
            )], []
        timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
        if timestamps.empty or timestamps.isna().any():
            return False, [AuditIssue(
                "OOS_BOUNDARY_FAILURE", "ERROR",
                f"{name} timestamp evidence is empty or invalid for the locked OOS interval",
            )], []
        dates = timestamps.dt.date
        if not dates.between(train_start, oos_end).all():
            return False, [AuditIssue(
                "OOS_BOUNDARY_FAILURE", "ERROR",
                f"{name} timestamp evidence extends outside the locked train/OOS boundary",
            )], []
        if not dates.between(oos_start, oos_end).any():
            return False, [AuditIssue(
                "OOS_BOUNDARY_FAILURE", "ERROR",
                f"{name} has no timestamped observation in the locked OOS interval",
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
    hashes = (
        "strategy_config_hash",
        "strategy_config_file_hash",
        "data_hash",
    )
    if any(not _is_present(manifest.get(field)) for field in hashes):
        return False, [AuditIssue(
            "MISSING_MANIFEST_FIELD", "ERROR", "reproducibility requires non-empty input hashes"
        )], []
    if manifest["strategy_config_hash"] != canonical_hash(context.spec.raw):
        return False, [AuditIssue(
            "HASH_MISMATCH",
            "ERROR",
            "canonical strategy configuration differs from manifest",
        )], []
    strategy_config_path = manifest.get("strategy_config_path")
    try:
        config_hash = sha256_file(Path(strategy_config_path).resolve())
    except (OSError, TypeError, ValueError):
        return False, [AuditIssue(
            "HASH_MISMATCH",
            "ERROR",
            "manifest strategy_config_path cannot be hashed",
        )], []
    if config_hash != manifest["strategy_config_file_hash"]:
        return False, [AuditIssue(
            "HASH_MISMATCH",
            "ERROR",
            "copied strategy configuration hash differs from manifest",
        )], []
    data_path = manifest.get("data_path")
    if data_path is not None:
        try:
            actual_hash = sha256_file(Path(data_path).resolve())
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
