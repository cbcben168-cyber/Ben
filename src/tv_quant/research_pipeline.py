"""Fixed Stage 0-7 orchestration for deterministic Phase 1 research."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
import subprocess
from typing import Callable, Mapping

import pandas as pd
import yaml

from .backtest_audit import AuditContext, audit_backtest
from .data_quality import DataQualityError, load_standardized_csv
from .metrics import buy_and_hold_return, calculate_metrics
from .pipeline_models import (
    AuditIssue,
    AuditReport,
    AuditStatus,
    CapabilityResult,
    StrategySpec,
)
from .reporting import write_reports
from .run_manifest import (
    bind_artifact_hashes,
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
_PROVENANCE_SCHEMA_VERSION = 1
_PROVIDER_BY_SOURCE = {
    "futu": "Futu_LOCAL_CACHE",
    "yfinance": "SMOKE_TEST_DATA_ONLY",
}


class _DataProvenanceError(ValueError):
    pass


def data_provenance_path(data_path: Path) -> Path:
    return data_path.with_name(f"{data_path.name}.provenance.json")


def data_provenance_pending_path(data_path: Path) -> Path:
    return data_path.with_name(f"{data_path.name}.provenance.pending")


def mark_data_provenance_pending(data_path: Path) -> None:
    pending_path = data_provenance_pending_path(data_path)
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path.write_text("pending\n", encoding="utf-8")


def write_data_provenance(data_path: Path, source: str) -> None:
    try:
        provider = _PROVIDER_BY_SOURCE[source]
    except KeyError as error:
        raise ValueError(f"unsupported data provenance source: {source}") from error
    payload = {
        "schema_version": _PROVENANCE_SCHEMA_VERSION,
        "source": source,
        "provider": provider,
    }
    data_provenance_path(data_path).write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def clear_data_provenance_pending(data_path: Path, source: str) -> None:
    if not data_path.is_file():
        raise _DataProvenanceError(
            "cannot complete data provenance publication without data"
        )
    provenance = _read_data_provenance(data_path)
    if provenance is None or provenance["source"] != source:
        raise _DataProvenanceError(
            "cannot complete data provenance publication without valid metadata"
        )
    data_provenance_pending_path(data_path).unlink(missing_ok=True)


def _read_data_provenance(data_path: Path) -> Mapping[str, object] | None:
    provenance_path = data_provenance_path(data_path)
    if not provenance_path.is_file():
        return None
    try:
        payload = _load_json(provenance_path)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as error:
        raise _DataProvenanceError(
            f"invalid data provenance metadata: {error}"
        ) from error
    source = payload.get("source")
    provider = payload.get("provider")
    if (
        payload.get("schema_version") != _PROVENANCE_SCHEMA_VERSION
        or not isinstance(source, str)
        or not isinstance(provider, str)
        or _PROVIDER_BY_SOURCE.get(source) != provider
    ):
        raise _DataProvenanceError("invalid data provenance metadata contract")
    return payload


def _source_label(
    spec: StrategySpec,
    options: PipelineOptions,
    data_path: Path,
) -> str:
    if data_provenance_pending_path(data_path).is_file():
        raise _DataProvenanceError(
            "data provenance publication is pending"
        )
    provenance = _read_data_provenance(data_path)
    if provenance is None:
        return (
            "SMOKE_TEST_DATA_ONLY"
            if options.allow_smoke_test_data and spec.data_source == "yfinance"
            else "Futu_LOCAL_CACHE"
        )
    if (
        provenance["source"] == "yfinance"
        and not options.allow_smoke_test_data
    ):
        raise _DataProvenanceError(
            "recorded yfinance smoke-test data requires explicit smoke-test mode"
        )
    return str(provenance["provider"])


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
    artifact_paths: Mapping[str, Path],
    *,
    require_artifact_files: bool,
) -> AuditContext:
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
        require_artifact_files=require_artifact_files,
    )


def _audit_payload(
    audit: AuditReport,
    manifest_path: Path | None = None,
) -> dict[str, object]:
    payload = {
        "status": audit.status.value,
        "checks": dict(audit.checks),
        "issues": [asdict(issue) for issue in audit.issues],
        "warnings": list(audit.warnings),
    }
    if manifest_path is not None:
        payload["manifest_hash"] = sha256_file(manifest_path)
    payload["audit_payload_hash"] = canonical_hash(payload)
    return payload


def _write_audit(
    path: Path,
    audit: AuditReport,
    manifest_path: Path | None = None,
) -> None:
    path.write_text(
        json.dumps(
            _audit_payload(audit, manifest_path),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _summary_with_audit(
    summary: Mapping[str, object],
    audit: AuditReport,
    manifest: Mapping[str, object],
) -> dict[str, object]:
    result = dict(summary)
    result.update(
        {
            "audit_status": audit.status.value,
            "audit_checks": dict(audit.checks),
            "audit_issues": [asdict(issue) for issue in audit.issues],
            "audit_warnings": list(audit.warnings),
            "provider": manifest["provider"],
            "smoke_test_marker": manifest["smoke_test_marker"],
            "strategy_config_hash": manifest["strategy_config_hash"],
            "data_hash": manifest["data_hash"],
        }
    )
    return result


def _update_summary_audit_fields(
    path: Path,
    audit: AuditReport,
) -> dict[str, object]:
    summary = _load_json(path)
    summary.update(
        {
            "audit_status": audit.status.value,
            "audit_checks": dict(audit.checks),
            "audit_issues": [asdict(issue) for issue in audit.issues],
            "audit_warnings": list(audit.warnings),
        }
    )
    path.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    return summary


def _write_chinese_report(
    path: Path,
    summary: Mapping[str, object],
    audit: AuditReport,
) -> None:
    def percentage(name: str) -> str:
        return f"{float(summary[name]):.6%}"

    limitations = [
        "仅限第一阶段 SPY/QQQ 日线历史研究；不连接账户、券商或真实订单。",
        "信号在下一根 K 线成交，结果包含已配置的手续费和滑点。",
    ]
    limitations.extend(str(item) for item in summary["validation_warnings"])
    limitations.extend(issue.message for issue in audit.issues)
    limitations.extend(audit.warnings)
    lines = [
        "# 中文回测简报",
        "",
        f"- 状态：{audit.status.value}",
        f"- 标的：{summary['ticker']}",
        f"- 日期：{summary['data_start_utc']} 至 {summary['data_end_utc']}",
        f"- 数据提供方：{summary['provider']}",
        f"- 策略总收益：{percentage('total_return')}",
        f"- 买入并持有收益：{percentage('buy_and_hold_return')}",
        f"- 最大回撤：{percentage('max_drawdown')}",
        f"- 交易次数：{int(summary['trade_count'])}",
        f"- 相对买入并持有差异：{percentage('strategy_minus_buy_hold')}",
        "",
        "## 限制",
        "",
        *(f"- {item}" for item in limitations),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _data_quality_failure(error: Exception) -> PipelineResult:
    audit = AuditReport(
        status=AuditStatus.FAIL,
        checks={"data_quality": False},
        issues=(
            AuditIssue(
                "DATA_QUALITY_FAILURE",
                "ERROR",
                str(error),
            ),
        ),
        warnings=(),
    )
    return PipelineResult("FAIL", None, audit, (str(error),))


def _filter_complete_data(
    spec: StrategySpec,
    data: pd.DataFrame,
) -> pd.DataFrame:
    if set(data["ticker"].astype(str).unique()) != {spec.symbol}:
        raise DataQualityError("ticker does not match strategy symbol")
    start = pd.Timestamp(spec.start_date, tz="UTC")
    end = pd.Timestamp(spec.end_date, tz="UTC")
    if data["timestamp_utc"].min() > start or data["timestamp_utc"].max() < end:
        raise _InsufficientCoverage(
            "local cache does not cover configured date range"
        )
    return data.loc[data["timestamp_utc"].between(start, end)].copy()


class _InsufficientCoverage(DataQualityError):
    pass


def _select_data(
    spec: StrategySpec,
    options: PipelineOptions,
    refresh_data: RefreshData | None,
):
    data_path = options.data_root / f"{spec.symbol}_daily.csv"

    def load_validated():
        data, warnings = load_standardized_csv(data_path)
        return _filter_complete_data(spec, data), warnings

    if data_provenance_pending_path(data_path).is_file():
        return PipelineResult(
            "DATA_CAPABILITY_BLOCKER",
            None,
            None,
            ("data provenance publication is pending",),
        )
    if data_path.is_file():
        try:
            source = _source_label(spec, options, data_path)
            data, warnings = load_validated()
        except _DataProvenanceError as error:
            return PipelineResult(
                "DATA_CAPABILITY_BLOCKER",
                None,
                None,
                (str(error),),
            )
        except _InsufficientCoverage:
            pass
        except FileNotFoundError:
            return PipelineResult(
                "DATA_CAPABILITY_BLOCKER",
                None,
                None,
                ("validated local cache unavailable",),
            )
        except (
            DataQualityError,
            OSError,
            pd.errors.ParserError,
            UnicodeError,
        ) as error:
            return _data_quality_failure(error)
        else:
            return data, data_path, source, warnings
    if options.skip_data_refresh or refresh_data is None:
        return PipelineResult(
            "DATA_CAPABILITY_BLOCKER",
            None,
            None,
            ("validated local cache unavailable",),
        )
    refresh_data(spec, data_path)
    if not data_path.is_file():
        return PipelineResult(
            "DATA_CAPABILITY_BLOCKER",
            None,
            None,
            ("validated local cache unavailable after refresh",),
        )
    try:
        source = _source_label(spec, options, data_path)
        data, warnings = load_validated()
    except _DataProvenanceError as error:
        return PipelineResult(
            "DATA_CAPABILITY_BLOCKER",
            None,
            None,
            (str(error),),
        )
    except _InsufficientCoverage as error:
        return PipelineResult(
            "DATA_CAPABILITY_BLOCKER",
            None,
            None,
            (str(error),),
        )
    except FileNotFoundError:
        return PipelineResult(
            "DATA_CAPABILITY_BLOCKER",
            None,
            None,
            ("validated local cache unavailable after refresh",),
        )
    except (
        DataQualityError,
        OSError,
        pd.errors.ParserError,
        UnicodeError,
    ) as error:
        return _data_quality_failure(error)
    return data, data_path, source, warnings


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def _audit_preflight_failure(
    run_directory: Path,
    audit_path: Path,
    manifest_path: Path,
    status: AuditStatus,
    code: str,
    message: str,
) -> PipelineResult:
    audit = AuditReport(
        status=status,
        checks={"audit_preflight": False},
        issues=(AuditIssue(code, "ERROR", message),),
        warnings=(),
    )
    if run_directory.is_dir():
        _write_audit(
            audit_path,
            audit,
            manifest_path if manifest_path.is_file() else None,
        )
    return PipelineResult(
        status.value,
        run_directory,
        audit,
        (message,),
    )


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
        "report_zh": run_directory / "report_zh.md",
        "strategy_config": run_directory / "strategy_config.yaml",
    }
    manifest_path = required_paths["manifest"]
    audit_path = required_paths["audit"]
    missing = tuple(
        f"missing audit artifact: {path.name}"
        for path in required_paths.values()
        if not path.is_file()
    )
    if missing:
        return _audit_preflight_failure(
            run_directory,
            audit_path,
            manifest_path,
            AuditStatus.FAIL,
            "MISSING_AUDIT_ARTIFACT",
            "; ".join(missing),
        )

    try:
        spec = load_strategy_spec(config_path)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as error:
        return _audit_preflight_failure(
            run_directory,
            audit_path,
            manifest_path,
            AuditStatus.STRATEGY_CAPABILITY_BLOCKER,
            "STRATEGY_CONFIG_INVALID",
            str(error),
        )
    capability = check_capabilities(
        spec,
        allow_smoke_test_data=options.allow_smoke_test_data,
    )
    if capability.status.value != "SUPPORTED":
        return _audit_preflight_failure(
            run_directory,
            audit_path,
            manifest_path,
            AuditStatus(capability.status.value),
            "CAPABILITY_BLOCKER",
            "; ".join(capability.reasons),
        )

    try:
        previous_audit = _load_json(audit_path)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as error:
        return _audit_preflight_failure(
            run_directory,
            audit_path,
            manifest_path,
            AuditStatus.FAIL,
            "AUDIT_EVIDENCE_INVALID",
            str(error),
        )
    expected_audit_hash = previous_audit.pop("audit_payload_hash", None)
    if (
        not isinstance(expected_audit_hash, str)
        or canonical_hash(previous_audit) != expected_audit_hash
    ):
        return _audit_preflight_failure(
            run_directory,
            audit_path,
            manifest_path,
            AuditStatus.FAIL,
            "AUDIT_HASH_MISMATCH",
            "audit.json payload hash does not match",
        )
    try:
        manifest_hash_matches = (
            previous_audit.get("manifest_hash") == sha256_file(manifest_path)
        )
    except OSError:
        manifest_hash_matches = False
    if not manifest_hash_matches:
        return _audit_preflight_failure(
            run_directory,
            audit_path,
            manifest_path,
            AuditStatus.FAIL,
            "MANIFEST_HASH_MISMATCH",
            "run_manifest.json hash differs from audit evidence",
        )

    try:
        manifest = _load_json(manifest_path)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as error:
        return _audit_preflight_failure(
            run_directory,
            audit_path,
            manifest_path,
            AuditStatus.FAIL,
            "MANIFEST_INVALID",
            str(error),
        )
    if canonical_hash(spec.raw) != manifest.get("strategy_config_hash"):
        return _audit_preflight_failure(
            run_directory,
            audit_path,
            manifest_path,
            AuditStatus.STRATEGY_CAPABILITY_BLOCKER,
            "STRATEGY_CONFIG_HASH_MISMATCH",
            "strategy config hash differs from run manifest",
        )
    try:
        config_file_matches = (
            sha256_file(config_path)
            == manifest.get("strategy_config_file_hash")
        )
    except OSError:
        config_file_matches = False
    if not config_file_matches:
        return _audit_preflight_failure(
            run_directory,
            audit_path,
            manifest_path,
            AuditStatus.STRATEGY_CAPABILITY_BLOCKER,
            "STRATEGY_CONFIG_FILE_HASH_MISMATCH",
            "strategy config file hash differs from run manifest",
        )

    artifact_hashes = manifest.get("artifact_hashes")
    manifest_artifact_paths = manifest.get("artifact_paths")
    if not isinstance(artifact_hashes, Mapping) or not isinstance(
        manifest_artifact_paths,
        Mapping,
    ):
        return _audit_preflight_failure(
            run_directory,
            audit_path,
            manifest_path,
            AuditStatus.FAIL,
            "MISSING_ARTIFACT_HASH",
            "manifest must bind required artifact paths and hashes",
        )
    for name in (
        "summary",
        "equity",
        "trades",
        "report_zh",
        "strategy_config",
    ):
        recorded_path = manifest_artifact_paths.get(name)
        expected_hash = artifact_hashes.get(name)
        try:
            matches = (
                recorded_path is not None
                and Path(str(recorded_path)).resolve()
                == required_paths[name].resolve()
                and isinstance(expected_hash, str)
                and sha256_file(required_paths[name]) == expected_hash
            )
        except (OSError, TypeError, ValueError):
            matches = False
        if not matches:
            return _audit_preflight_failure(
                run_directory,
                audit_path,
                manifest_path,
                AuditStatus.FAIL,
                "ARTIFACT_HASH_MISMATCH",
                f"{name} artifact path or hash does not match manifest evidence",
            )
    recorded_strategy_config_path = manifest.get("strategy_config_path")
    try:
        strategy_config_path_matches = (
            recorded_strategy_config_path is not None
            and Path(str(recorded_strategy_config_path)).resolve()
            == required_paths["strategy_config"].resolve()
        )
    except (OSError, TypeError, ValueError):
        strategy_config_path_matches = False
    if (
        not strategy_config_path_matches
        or manifest.get("strategy_config_file_hash")
        != artifact_hashes.get("strategy_config")
    ):
        return _audit_preflight_failure(
            run_directory,
            audit_path,
            manifest_path,
            AuditStatus.FAIL,
            "ARTIFACT_HASH_MISMATCH",
            "strategy_config evidence does not match manifest fields",
        )

    try:
        data_path = Path(str(manifest["data_path"]))
        if not data_path.is_file():
            raise OSError("manifest data_path does not exist")
        if sha256_file(data_path) != manifest.get("data_hash"):
            return _audit_preflight_failure(
                run_directory,
                audit_path,
                manifest_path,
                AuditStatus.DATA_CAPABILITY_BLOCKER,
                "DATA_HASH_MISMATCH",
                "manifest data hash does not match",
            )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        return _audit_preflight_failure(
            run_directory,
            audit_path,
            manifest_path,
            AuditStatus.DATA_CAPABILITY_BLOCKER,
            "DATA_PREFLIGHT_BLOCKER",
            str(error),
        )
    try:
        data, data_warnings = load_standardized_csv(data_path)
        data = _filter_complete_data(spec, data)
    except _InsufficientCoverage as error:
        return _audit_preflight_failure(
            run_directory,
            audit_path,
            manifest_path,
            AuditStatus.DATA_CAPABILITY_BLOCKER,
            "DATA_PREFLIGHT_BLOCKER",
            str(error),
        )
    except (
        DataQualityError,
        UnicodeError,
        pd.errors.ParserError,
    ) as error:
        return _audit_preflight_failure(
            run_directory,
            audit_path,
            manifest_path,
            AuditStatus.FAIL,
            "DATA_QUALITY_FAILURE",
            str(error),
        )

    try:
        summary = _load_json(required_paths["summary"])
        equity = pd.read_csv(required_paths["equity"])
        trades = pd.read_csv(required_paths["trades"])
        benchmark_return = float(summary["buy_and_hold_return"])
    except (
        json.JSONDecodeError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        pd.errors.ParserError,
    ) as error:
        return _audit_preflight_failure(
            run_directory,
            audit_path,
            manifest_path,
            AuditStatus.FAIL,
            "ARTIFACT_PARSE_FAILURE",
            str(error),
        )
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
        benchmark_return=benchmark_return,
        manifest=manifest,
        artifact_paths=required_paths,
    )
    audit = audit_backtest(context)
    _write_audit(audit_path, audit, manifest_path)
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
        {},
        code_commit,
        smoke_test_marker,
        strategy_config_path=config_path,
    )
    context = _build_audit_context(
        spec,
        capability,
        data,
        backtest,
        metrics,
        benchmark,
        manifest,
        {},
        require_artifact_files=False,
    )
    preliminary_audit = audit_backtest(context)
    if preliminary_audit.status is AuditStatus.FAIL:
        return PipelineResult(
            preliminary_audit.status.value,
            None,
            preliminary_audit,
            tuple(data_warnings),
        )

    summary = _summary_with_audit(summary, preliminary_audit, manifest)
    paths = write_reports(
        options.report_root,
        summary,
        backtest.equity,
        backtest.trades,
    )
    run_directory = paths["summary"].parent
    manifest_path = run_directory / "run_manifest.json"
    audit_path = run_directory / "audit.json"
    report_zh_path = run_directory / "report_zh.md"
    strategy_config_path = run_directory / "strategy_config.yaml"
    shutil.copyfile(config_path, strategy_config_path)
    _write_chinese_report(report_zh_path, summary, preliminary_audit)
    artifact_paths = {
        **paths,
        "manifest": manifest_path,
        "audit": audit_path,
        "report_zh": report_zh_path,
        "strategy_config": strategy_config_path,
    }
    manifest = bind_artifact_hashes(manifest, artifact_paths)
    write_manifest(manifest_path, manifest)
    _write_audit(audit_path, preliminary_audit, manifest_path)
    final_context = _build_audit_context(
        spec,
        capability,
        data,
        backtest,
        metrics,
        benchmark,
        manifest,
        artifact_paths,
        require_artifact_files=True,
    )
    final_audit = audit_backtest(final_context)
    summary = _update_summary_audit_fields(paths["summary"], final_audit)
    _write_chinese_report(report_zh_path, summary, final_audit)
    manifest = bind_artifact_hashes(manifest, artifact_paths)
    write_manifest(manifest_path, manifest)
    _write_audit(audit_path, final_audit, manifest_path)
    return PipelineResult(
        final_audit.status.value,
        run_directory,
        final_audit,
        tuple(data_warnings),
    )
