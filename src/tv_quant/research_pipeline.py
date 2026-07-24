"""Fixed Stage 0-7 orchestration for deterministic Phase 1 research."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
from typing import Callable, Mapping

import pandas as pd

from .backtest_audit import AuditContext, audit_backtest
from .data_quality import DataQualityError, load_standardized_csv
from .metrics import buy_and_hold_return, calculate_metrics
from .pipeline_models import (
    AuditReport,
    CapabilityResult,
    StrategySpec,
)
from .reporting import write_reports
from .run_manifest import (
    build_manifest,
    canonical_hash,
    sha256_file,
    write_manifest,
)
from .strategy import BacktestResult, run_backtest
from .strategy_spec import check_capabilities, load_strategy_spec


@dataclass(frozen=True)
class PipelineOptions:
    data_root: Path = Path("data/raw")
    report_root: Path = Path("reports/runs")
    run_directory: Path | None = None
    quick: bool = False
    audit_only: bool = False
    skip_data_refresh: bool = False
    allow_smoke_test_data: bool = False


@dataclass(frozen=True)
class PipelineResult:
    status: str
    run_directory: Path | None
    audit_report: AuditReport | None
    warnings: tuple[str, ...]


RefreshData = Callable[[StrategySpec, Path], None]


def current_git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _build_summary(
    spec: StrategySpec,
    metrics: Mapping[str, object],
    benchmark: float,
    warnings: list[str],
    source_label: str,
) -> dict[str, object]:
    strategy_minus_buy_hold = float(metrics["total_return"]) - benchmark
    return {
        "ticker": spec.symbol,
        "data_start_utc": spec.start_date.isoformat(),
        "data_end_utc": spec.end_date.isoformat(),
        "parameters": {
            "ema_fast": 50,
            "ema_slow": 200,
            "initial_cash": spec.initial_capital,
            "commission_bps": spec.commission_bps,
            "slippage_bps": spec.slippage_bps,
            "fill_timing": spec.fill_timing,
            "optimization_allowed": spec.optimization_allowed,
        },
        **metrics,
        "buy_and_hold_return": benchmark,
        "strategy_minus_buy_hold": strategy_minus_buy_hold,
        "buy_and_hold_comparison": (
            "BEAT_BUY_HOLD"
            if strategy_minus_buy_hold > 0
            else "UNDERPERFORM_BUY_HOLD"
        ),
        "validation_warnings": list(warnings),
        "provider": source_label,
        "report_language": spec.report_language,
    }


def _build_audit_context(
    spec: StrategySpec,
    capability: CapabilityResult,
    data: pd.DataFrame,
    backtest: BacktestResult,
    metrics: Mapping[str, object],
    benchmark: float,
    manifest: Mapping[str, object],
    paths: Mapping[str, Path],
    manifest_path: Path,
) -> AuditContext:
    audit_path = paths["summary"].parent / "audit.json"
    artifact_paths = {
        **paths,
        "manifest": manifest_path,
        "audit": audit_path,
    }
    return AuditContext(
        spec=spec,
        capability=capability,
        data=data,
        equity=backtest.equity,
        trades=backtest.trades,
        strategy_metrics=metrics,
        benchmark_return=benchmark,
        manifest=manifest,
        artifact_paths=artifact_paths,
    )


def _audit_payload(audit: AuditReport) -> dict[str, object]:
    return {
        "status": audit.status.value,
        "checks": dict(audit.checks),
        "issues": [asdict(issue) for issue in audit.issues],
        "warnings": list(audit.warnings),
    }


def _write_audit(path: Path, audit: AuditReport) -> None:
    path.write_text(
        json.dumps(
            _audit_payload(audit),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_audit_and_update_summary(
    summary_path: Path,
    audit_path: Path,
    audit: AuditReport,
) -> None:
    _write_audit(audit_path, audit)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update(
        {
            "audit_status": audit.status.value,
            "audit_checks": dict(audit.checks),
            "audit_issues": [asdict(issue) for issue in audit.issues],
            "audit_warnings": list(audit.warnings),
        }
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _filter_complete_data(
    spec: StrategySpec,
    data: pd.DataFrame,
) -> pd.DataFrame:
    if set(data["ticker"].astype(str).unique()) != {spec.symbol}:
        raise DataQualityError("ticker does not match strategy symbol")
    start = pd.Timestamp(spec.start_date, tz="UTC")
    end = pd.Timestamp(spec.end_date, tz="UTC")
    if data["timestamp_utc"].min() > start or data["timestamp_utc"].max() < end:
        raise DataQualityError("local cache does not cover configured date range")
    return data.loc[data["timestamp_utc"].between(start, end)].copy()


def _select_data(
    spec: StrategySpec,
    options: PipelineOptions,
    refresh_data: RefreshData | None,
):
    data_path = options.data_root / f"{spec.symbol}_daily.csv"

    def load_if_complete():
        try:
            data, warnings = load_standardized_csv(data_path)
            data = _filter_complete_data(spec, data)
        except (DataQualityError, OSError, pd.errors.ParserError) as error:
            return None, [str(error)]
        return data, warnings

    if data_path.is_file():
        data, warnings = load_if_complete()
        if data is not None:
            return data, data_path, "Futu_LOCAL_CACHE", warnings
    if options.skip_data_refresh or refresh_data is None:
        return PipelineResult(
            "DATA_CAPABILITY_BLOCKER",
            None,
            None,
            ("validated local cache unavailable",),
        )
    refresh_data(spec, data_path)
    data, warnings = load_if_complete()
    if data is None:
        return PipelineResult(
            "DATA_CAPABILITY_BLOCKER",
            None,
            None,
            tuple(warnings),
        )
    is_smoke_data = (
        options.allow_smoke_test_data and spec.data_source == "yfinance"
    )
    source = "SMOKE_TEST_DATA_ONLY" if is_smoke_data else "Futu_LOCAL_CACHE"
    return data, data_path, source, warnings


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def _audit_only(
    config_path: Path,
    options: PipelineOptions,
) -> PipelineResult:
    if options.run_directory is None:
        raise ValueError("run_directory is required for audit_only")

    run_directory = Path(options.run_directory)
    required_paths = {
        "summary": run_directory / "summary.json",
        "equity": run_directory / "equity.csv",
        "trades": run_directory / "trades.csv",
        "manifest": run_directory / "run_manifest.json",
        "audit": run_directory / "audit.json",
    }
    missing = tuple(
        f"missing audit artifact: {path.name}"
        for path in required_paths.values()
        if not path.is_file()
    )
    if missing:
        return PipelineResult("FAIL", run_directory, None, missing)

    spec = load_strategy_spec(config_path)
    capability = check_capabilities(
        spec,
        allow_smoke_test_data=options.allow_smoke_test_data,
    )
    if capability.status.value != "SUPPORTED":
        return PipelineResult(
            capability.status.value,
            run_directory,
            None,
            capability.reasons,
        )

    summary = _load_json(required_paths["summary"])
    manifest = _load_json(required_paths["manifest"])
    _load_json(required_paths["audit"])

    if canonical_hash(spec.raw) != manifest.get("strategy_config_hash"):
        return PipelineResult(
            "STRATEGY_CAPABILITY_BLOCKER",
            run_directory,
            None,
            ("strategy config hash differs from run manifest",),
        )

    try:
        data_path = Path(str(manifest["data_path"]))
        if not data_path.is_file():
            raise OSError("manifest data_path does not exist")
        if sha256_file(data_path) != manifest.get("data_hash"):
            raise OSError("manifest data hash does not match")
        data, data_warnings = load_standardized_csv(data_path)
        data = _filter_complete_data(spec, data)
    except (
        DataQualityError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        pd.errors.ParserError,
    ) as error:
        return PipelineResult(
            "DATA_CAPABILITY_BLOCKER",
            run_directory,
            None,
            (str(error),),
        )

    equity = pd.read_csv(required_paths["equity"])
    trades = pd.read_csv(required_paths["trades"])
    metric_names = (
        "total_return",
        "cagr",
        "max_drawdown",
        "sharpe_ratio",
        "trade_count",
        "win_rate",
    )
    metrics = {name: summary.get(name) for name in metric_names}
    context = AuditContext(
        spec=spec,
        capability=capability,
        data=data,
        equity=equity,
        trades=trades,
        strategy_metrics=metrics,
        benchmark_return=float(summary["buy_and_hold_return"]),
        manifest=manifest,
        artifact_paths=required_paths,
    )
    audit = audit_backtest(context)
    _write_audit(required_paths["audit"], audit)
    return PipelineResult(
        audit.status.value,
        run_directory,
        audit,
        tuple(data_warnings),
    )


def run_pipeline(
    config_path: Path,
    options: PipelineOptions,
    refresh_data: RefreshData | None = None,
) -> PipelineResult:
    if options.audit_only:
        return _audit_only(config_path, options)

    spec = load_strategy_spec(config_path)
    capability = check_capabilities(
        spec,
        allow_smoke_test_data=options.allow_smoke_test_data,
    )
    if capability.status.value != "SUPPORTED":
        return PipelineResult(
            capability.status.value,
            None,
            None,
            capability.reasons,
        )

    data_result = _select_data(spec, options, refresh_data)
    if isinstance(data_result, PipelineResult):
        return data_result
    data, data_path, source_label, data_warnings = data_result

    backtest = run_backtest(
        data,
        initial_cash=spec.initial_capital,
        commission_bps=spec.commission_bps,
        slippage_bps=spec.slippage_bps,
    )
    metrics = calculate_metrics(
        backtest.equity,
        backtest.trades,
        spec.initial_capital,
    )
    benchmark = buy_and_hold_return(
        data,
        spec.initial_capital,
        spec.commission_bps,
        spec.slippage_bps,
    )
    summary = _build_summary(
        spec,
        metrics,
        benchmark,
        data_warnings + backtest.warnings,
        source_label,
    )
    paths = write_reports(
        options.report_root,
        summary,
        backtest.equity,
        backtest.trades,
    )
    run_directory = paths["summary"].parent
    manifest_path = run_directory / "run_manifest.json"
    audit_path = run_directory / "audit.json"
    audit_path.write_text('{"status": "PENDING"}\n', encoding="utf-8")
    artifact_paths = {
        **paths,
        "manifest": manifest_path,
        "audit": audit_path,
    }
    code_commit = current_git_revision()
    smoke_test_marker = (
        "SMOKE_TEST_DATA_ONLY"
        if source_label == "SMOKE_TEST_DATA_ONLY"
        else None
    )
    manifest = build_manifest(
        spec,
        data_path,
        source_label,
        artifact_paths,
        code_commit,
        smoke_test_marker,
    )
    write_manifest(manifest_path, manifest)
    context = _build_audit_context(
        spec,
        capability,
        data,
        backtest,
        metrics,
        benchmark,
        manifest,
        paths,
        manifest_path,
    )
    audit = audit_backtest(context)
    _write_audit_and_update_summary(
        paths["summary"],
        audit_path,
        audit,
    )
    return PipelineResult(
        audit.status.value,
        run_directory,
        audit,
        tuple(data_warnings),
    )
