import json
from pathlib import Path

import pandas as pd
import pytest

from tv_quant.pipeline_models import AuditIssue, AuditReport, AuditStatus
from tv_quant.research_pipeline import PipelineOptions, run_pipeline
from tv_quant.run_manifest import canonical_hash, sha256_file

from tests.pipeline.helpers import (
    write_ema_config,
    write_invalid_csv,
    write_rsi_config,
    write_valid_spy_csv,
)


def failed_audit():
    return AuditReport(
        status=AuditStatus.FAIL,
        checks={"forced_failure": False},
        issues=(AuditIssue("FORCED_FAILURE", "ERROR", "test failure"),),
        warnings=(),
    )


def covered_ema_config(root: Path) -> Path:
    return ema_config_ending(root, "2020-10-09")


def ema_config_ending(root: Path, end_date: str) -> Path:
    path = write_ema_config(root)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "end_date: '2020-10-15'", f"end_date: '{end_date}'"
        ),
        encoding="utf-8",
    )
    return path


def yfinance_smoke_config(root: Path) -> Path:
    path = covered_ema_config(root)
    path.write_text(
        path.read_text(encoding="utf-8") + "data_source: yfinance\n",
        encoding="utf-8",
    )
    return path


def test_capability_blocker_prevents_refresh_and_backtest(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        "tv_quant.research_pipeline.run_backtest",
        lambda *a, **k: calls.append("backtest"),
    )
    result = run_pipeline(
        write_rsi_config(tmp_path),
        PipelineOptions(data_root=tmp_path),
        refresh_data=lambda *a: calls.append("refresh"),
    )
    assert result.status == "STRATEGY_CAPABILITY_BLOCKER"
    assert calls == []


def test_existing_valid_cache_is_not_refreshed(tmp_path):
    calls = []
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")
    result = run_pipeline(
        covered_ema_config(tmp_path),
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
        refresh_data=lambda *a: calls.append("refresh"),
    )
    assert calls == []
    assert result.status in {"PASS", "CONDITIONAL_PASS"}


def test_existing_yfinance_smoke_cache_preserves_smoke_provenance(tmp_path):
    calls = []
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")

    result = run_pipeline(
        yfinance_smoke_config(tmp_path),
        PipelineOptions(
            data_root=tmp_path,
            report_root=tmp_path / "reports",
            allow_smoke_test_data=True,
        ),
        refresh_data=lambda *args: calls.append("refresh"),
    )

    assert calls == []
    assert result.run_directory is not None
    summary = json.loads(
        (result.run_directory / "summary.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (result.run_directory / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert summary["provider"] == "SMOKE_TEST_DATA_ONLY"
    assert manifest["provider"] == "SMOKE_TEST_DATA_ONLY"
    assert manifest["smoke_test_marker"] == "SMOKE_TEST_DATA_ONLY"


def test_malformed_existing_cache_blocks_without_refresh_or_backtest(
    monkeypatch,
    tmp_path,
):
    write_invalid_csv(tmp_path / "SPY_daily.csv")
    calls = []
    monkeypatch.setattr(
        "tv_quant.research_pipeline.run_backtest",
        lambda *a, **k: calls.append("backtest"),
    )
    result = run_pipeline(
        write_ema_config(tmp_path),
        PipelineOptions(data_root=tmp_path),
        refresh_data=lambda *a: calls.append("refresh"),
    )

    assert result.status == "DATA_CAPABILITY_BLOCKER"
    assert calls == []


def test_insufficient_existing_cache_may_use_explicit_refresh(tmp_path):
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")
    calls = []

    result = run_pipeline(
        write_ema_config(tmp_path),
        PipelineOptions(data_root=tmp_path),
        refresh_data=lambda *args: calls.append("refresh"),
    )

    assert calls == ["refresh"]
    assert result.status == "DATA_CAPABILITY_BLOCKER"


def test_absent_cache_may_use_explicit_refresh(tmp_path):
    calls = []

    def refresh(spec, path):
        calls.append((spec.symbol, path))
        write_valid_spy_csv(path)

    result = run_pipeline(
        covered_ema_config(tmp_path),
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
        refresh_data=refresh,
    )

    assert calls == [("SPY", tmp_path / "SPY_daily.csv")]
    assert result.status in {"PASS", "CONDITIONAL_PASS"}


def test_audit_runs_before_final_report(monkeypatch, tmp_path):
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")
    calls = []

    from tv_quant import research_pipeline

    real_audit = research_pipeline.audit_backtest
    real_write_reports = research_pipeline.write_reports

    def record_audit(context):
        calls.append("audit")
        return real_audit(context)

    def record_report(output_parent, summary, equity, trades):
        assert "audit_status" in summary
        calls.append("report")
        return real_write_reports(output_parent, summary, equity, trades)

    monkeypatch.setattr(research_pipeline, "audit_backtest", record_audit)
    monkeypatch.setattr(research_pipeline, "write_reports", record_report)

    result = run_pipeline(
        covered_ema_config(tmp_path),
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
    )

    assert result.status in {"PASS", "CONDITIONAL_PASS"}
    assert calls == ["audit", "report"]


def test_audit_failure_stops_final_report_stage(monkeypatch, tmp_path):
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")
    report_calls = []
    monkeypatch.setattr(
        "tv_quant.research_pipeline.audit_backtest",
        lambda context: failed_audit(),
    )
    monkeypatch.setattr(
        "tv_quant.research_pipeline.write_reports",
        lambda *args, **kwargs: report_calls.append("report"),
    )
    result = run_pipeline(
        covered_ema_config(tmp_path),
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
        refresh_data=lambda *a: None,
    )

    assert result.status == "FAIL"
    assert result.run_directory is None
    assert report_calls == []


def test_run_writes_required_summary_manifest_and_audit(tmp_path):
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")

    result = run_pipeline(
        covered_ema_config(tmp_path),
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
    )

    assert result.run_directory is not None
    summary = json.loads(
        (result.run_directory / "summary.json").read_text(encoding="utf-8")
    )
    required_summary_keys = {
        "ticker",
        "data_start_utc",
        "data_end_utc",
        "parameters",
        "total_return",
        "cagr",
        "max_drawdown",
        "sharpe_ratio",
        "trade_count",
        "win_rate",
        "buy_and_hold_return",
        "strategy_minus_buy_hold",
        "buy_and_hold_comparison",
        "validation_warnings",
    }
    assert required_summary_keys <= summary.keys()
    manifest_path = result.run_directory / "run_manifest.json"
    audit_path = result.run_directory / "audit.json"
    assert manifest_path.is_file()
    assert audit_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name in ("summary", "equity", "trades"):
        artifact_path = result.run_directory / f"{name}.{'json' if name == 'summary' else 'csv'}"
        assert manifest["artifact_hashes"][name] == sha256_file(artifact_path)

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["manifest_hash"] == sha256_file(manifest_path)
    audit_payload_hash = audit.pop("audit_payload_hash")
    assert audit_payload_hash == canonical_hash(audit)


def test_audit_only_skips_refresh_and_all_calculations(monkeypatch, tmp_path):
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")
    config_path = covered_ema_config(tmp_path)
    initial = run_pipeline(
        config_path,
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
    )
    assert initial.run_directory is not None

    def calculation_forbidden(*args, **kwargs):
        raise AssertionError("audit-only must not calculate or refresh")

    for name in (
        "run_backtest",
        "calculate_metrics",
        "buy_and_hold_return",
    ):
        monkeypatch.setattr(f"tv_quant.research_pipeline.{name}", calculation_forbidden)

    audit_calls = []

    def audit_once(context):
        audit_calls.append(context)
        return failed_audit()

    monkeypatch.setattr("tv_quant.research_pipeline.audit_backtest", audit_once)
    result = run_pipeline(
        config_path,
        PipelineOptions(
            data_root=tmp_path,
            run_directory=initial.run_directory,
            audit_only=True,
        ),
        refresh_data=calculation_forbidden,
    )

    assert len(audit_calls) == 1
    assert result.status == "FAIL"
    assert result.run_directory == initial.run_directory
    audit_payload = json.loads(
        (initial.run_directory / "audit.json").read_text(encoding="utf-8")
    )
    assert audit_payload["status"] == "FAIL"


def test_audit_only_requires_run_directory(tmp_path):
    with pytest.raises(ValueError, match="run_directory"):
        run_pipeline(
            write_ema_config(tmp_path),
            PipelineOptions(audit_only=True),
        )


def test_audit_only_rejects_changed_source_data(tmp_path):
    data_path = tmp_path / "SPY_daily.csv"
    write_valid_spy_csv(data_path)
    config_path = covered_ema_config(tmp_path)
    initial = run_pipeline(
        config_path,
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
    )
    assert initial.run_directory is not None

    data = pd.read_csv(data_path)
    data.loc[0, "close"] = float(data.loc[0, "close"]) + 1.0
    data.to_csv(data_path, index=False)

    result = run_pipeline(
        config_path,
        PipelineOptions(
            run_directory=initial.run_directory,
            audit_only=True,
        ),
    )

    assert result.status == "DATA_CAPABILITY_BLOCKER"
    audit_payload = json.loads(
        (initial.run_directory / "audit.json").read_text(encoding="utf-8")
    )
    assert audit_payload["status"] == "DATA_CAPABILITY_BLOCKER"
    assert any(
        issue["code"] == "DATA_HASH_MISMATCH"
        for issue in audit_payload["issues"]
    )


@pytest.mark.parametrize(
    ("artifact_name", "file_name"),
    (
        ("summary", "summary.json"),
        ("equity", "equity.csv"),
        ("trades", "trades.csv"),
    ),
)
def test_audit_only_rejects_changed_output_artifact_before_trusting_it(
    artifact_name,
    file_name,
    monkeypatch,
    tmp_path,
):
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")
    config_path = covered_ema_config(tmp_path)
    initial = run_pipeline(
        config_path,
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
    )
    assert initial.run_directory is not None
    artifact_path = initial.run_directory / file_name
    artifact_path.write_bytes(artifact_path.read_bytes() + b"\n")
    monkeypatch.setattr(
        "tv_quant.research_pipeline.audit_backtest",
        lambda context: pytest.fail("tampered artifact must block before audit"),
    )

    result = run_pipeline(
        config_path,
        PipelineOptions(
            run_directory=initial.run_directory,
            audit_only=True,
        ),
    )

    assert result.status == "FAIL"
    audit_payload = json.loads(
        (initial.run_directory / "audit.json").read_text(encoding="utf-8")
    )
    assert audit_payload["status"] == "FAIL"
    assert any(
        issue["code"] == "ARTIFACT_HASH_MISMATCH"
        and artifact_name in issue["message"]
        for issue in audit_payload["issues"]
    )


def test_audit_only_rejects_changed_manifest_before_trusting_it(
    monkeypatch,
    tmp_path,
):
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")
    config_path = covered_ema_config(tmp_path)
    initial = run_pipeline(
        config_path,
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
    )
    assert initial.run_directory is not None
    manifest_path = initial.run_directory / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provider"] = "tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        "tv_quant.research_pipeline.audit_backtest",
        lambda context: pytest.fail("tampered manifest must block before audit"),
    )

    result = run_pipeline(
        config_path,
        PipelineOptions(
            run_directory=initial.run_directory,
            audit_only=True,
        ),
    )

    assert result.status == "FAIL"
    audit_payload = json.loads(
        (initial.run_directory / "audit.json").read_text(encoding="utf-8")
    )
    assert any(
        issue["code"] == "MANIFEST_HASH_MISMATCH"
        for issue in audit_payload["issues"]
    )


def test_audit_only_rejects_changed_audit_evidence_before_reaudit(
    monkeypatch,
    tmp_path,
):
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")
    config_path = covered_ema_config(tmp_path)
    initial = run_pipeline(
        config_path,
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
    )
    assert initial.run_directory is not None
    audit_path = initial.run_directory / "audit.json"
    audit_payload = json.loads(audit_path.read_text(encoding="utf-8"))
    audit_payload["status"] = "PASS"
    audit_path.write_text(json.dumps(audit_payload), encoding="utf-8")
    monkeypatch.setattr(
        "tv_quant.research_pipeline.audit_backtest",
        lambda context: pytest.fail("tampered audit evidence must block reaudit"),
    )

    result = run_pipeline(
        config_path,
        PipelineOptions(
            run_directory=initial.run_directory,
            audit_only=True,
        ),
    )

    assert result.status == "FAIL"
    rewritten = json.loads(audit_path.read_text(encoding="utf-8"))
    assert any(
        issue["code"] == "AUDIT_HASH_MISMATCH"
        for issue in rewritten["issues"]
    )


def test_audit_only_reuses_the_configured_data_range(monkeypatch, tmp_path):
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")
    config_path = ema_config_ending(tmp_path, "2020-10-01")
    initial = run_pipeline(
        config_path,
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
    )
    assert initial.run_directory is not None

    audited_data_ends = []

    def record_audit_range(context):
        audited_data_ends.append(context.data["timestamp_utc"].max())
        return failed_audit()

    monkeypatch.setattr(
        "tv_quant.research_pipeline.audit_backtest",
        record_audit_range,
    )
    run_pipeline(
        config_path,
        PipelineOptions(
            run_directory=initial.run_directory,
            audit_only=True,
        ),
    )

    assert audited_data_ends == [pd.Timestamp("2020-10-01", tz="UTC")]
