import json
from pathlib import Path

import pandas as pd
import pytest

from tv_quant import pipeline_cli
from tv_quant.pipeline_models import AuditIssue, AuditReport, AuditStatus
from tv_quant.research_pipeline import (
    PipelineOptions,
    data_provenance_pending_path,
    data_provenance_path,
    run_pipeline,
)
from tv_quant.run_manifest import canonical_hash, sha256_file
from tv_quant.strategy_spec import load_strategy_spec

from tests.pipeline.helpers import (
    write_ema_config,
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


def test_yfinance_refresh_provenance_blocks_later_formal_cache_use(
    monkeypatch,
    tmp_path,
):
    data_path = tmp_path / "SPY_daily.csv"
    smoke_spec = load_strategy_spec(yfinance_smoke_config(tmp_path))
    legacy_calls = []

    def offline_yfinance_refresh(argv):
        legacy_calls.append(argv)
        write_valid_spy_csv(data_path)
        return 0

    monkeypatch.setattr(
        pipeline_cli.legacy_cli,
        "main",
        offline_yfinance_refresh,
    )
    pipeline_cli._refresh_data(smoke_spec, data_path)
    assert not data_provenance_pending_path(data_path).exists()
    formal_config = covered_ema_config(tmp_path)

    blocked = run_pipeline(
        formal_config,
        PipelineOptions(data_root=tmp_path),
        refresh_data=lambda *args: pytest.fail("existing cache must not refresh"),
    )

    assert len(legacy_calls) == 1
    assert blocked.status == "DATA_CAPABILITY_BLOCKER"
    assert "yfinance" in blocked.warnings[0]

    explicit_smoke = run_pipeline(
        formal_config,
        PipelineOptions(
            data_root=tmp_path,
            report_root=tmp_path / "reports",
            allow_smoke_test_data=True,
        ),
    )

    assert explicit_smoke.run_directory is not None
    manifest = json.loads(
        (explicit_smoke.run_directory / "run_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["provider"] == "SMOKE_TEST_DATA_ONLY"
    assert manifest["smoke_test_marker"] == "SMOKE_TEST_DATA_ONLY"


def test_failed_yfinance_provenance_publication_leaves_pending_and_blocks_formal(
    monkeypatch,
    tmp_path,
):
    data_path = tmp_path / "SPY_daily.csv"
    smoke_spec = load_strategy_spec(yfinance_smoke_config(tmp_path))
    refresh_calls = []

    def offline_yfinance_refresh(argv):
        refresh_calls.append(argv)
        write_valid_spy_csv(data_path)
        return 0

    def fail_provenance_write(*args):
        raise OSError("simulated write failure")

    monkeypatch.setattr(
        pipeline_cli.legacy_cli,
        "main",
        offline_yfinance_refresh,
    )
    monkeypatch.setattr(
        pipeline_cli,
        "write_data_provenance",
        fail_provenance_write,
    )

    with pytest.raises(RuntimeError, match="provenance publication failed"):
        pipeline_cli._refresh_data(smoke_spec, data_path)

    pending_path = data_provenance_pending_path(data_path)
    assert pending_path.is_file()
    assert not data_provenance_path(data_path).exists()

    formal = run_pipeline(
        covered_ema_config(tmp_path),
        PipelineOptions(data_root=tmp_path),
        refresh_data=lambda *args: pytest.fail(
            "pending yfinance refresh must not fall back to Futu"
        ),
    )

    assert len(refresh_calls) == 1
    assert formal.status == "DATA_CAPABILITY_BLOCKER"
    assert "pending" in formal.warnings[0]
    assert pending_path.is_file()


def test_invalid_data_provenance_sidecar_is_a_data_blocker(tmp_path):
    data_path = tmp_path / "SPY_daily.csv"
    write_valid_spy_csv(data_path)
    data_provenance_path(data_path).write_text("{}", encoding="utf-8")

    result = run_pipeline(
        covered_ema_config(tmp_path),
        PipelineOptions(data_root=tmp_path),
    )

    assert result.status == "DATA_CAPABILITY_BLOCKER"
    assert "provenance" in result.warnings[0]


@pytest.mark.parametrize(
    "failure_kind",
    ("malformed", "duplicate", "missing", "unsorted", "invalid"),
)
def test_invalid_existing_cache_fails_without_refresh_or_backtest(
    failure_kind,
    monkeypatch,
    tmp_path,
):
    data_path = tmp_path / "SPY_daily.csv"
    write_valid_spy_csv(data_path)
    if failure_kind == "malformed":
        data_path.write_text("not,ohlcv\n1,2\n", encoding="utf-8")
    else:
        data = pd.read_csv(data_path)
        if failure_kind == "duplicate":
            data.loc[1, "timestamp_utc"] = data.loc[0, "timestamp_utc"]
        elif failure_kind == "missing":
            data.loc[10, "close"] = None
        elif failure_kind == "unsorted":
            data = data.iloc[[1, 0, *range(2, len(data))]]
        else:
            data.loc[10, "high"] = float(data.loc[10, "close"]) - 1.0
        data.to_csv(data_path, index=False)
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

    assert result.status == "FAIL"
    assert result.audit_report is not None
    assert any(
        issue.code == "DATA_QUALITY_FAILURE"
        for issue in result.audit_report.issues
    )
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


def test_refresh_that_does_not_create_cache_remains_data_blocker(tmp_path):
    result = run_pipeline(
        covered_ema_config(tmp_path),
        PipelineOptions(data_root=tmp_path),
        refresh_data=lambda *args: None,
    )

    assert result.status == "DATA_CAPABILITY_BLOCKER"
    assert result.audit_report is None
    assert "unavailable" in result.warnings[0]


def test_audit_runs_before_final_report(monkeypatch, tmp_path):
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")
    calls = []

    from tv_quant import research_pipeline

    real_audit = research_pipeline.audit_backtest
    real_write_reports = research_pipeline.write_reports

    def record_audit(context):
        if context.require_artifact_files:
            assert all(path.is_file() for path in context.artifact_paths.values())
            calls.append("final_artifact_audit")
        else:
            calls.append("preliminary_audit")
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
    assert calls == ["preliminary_audit", "report", "final_artifact_audit"]


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
    config_path = covered_ema_config(tmp_path)

    result = run_pipeline(
        config_path,
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
    report_zh_path = result.run_directory / "report_zh.md"
    strategy_config_path = result.run_directory / "strategy_config.yaml"
    assert manifest_path.is_file()
    assert audit_path.is_file()
    assert report_zh_path.is_file()
    assert strategy_config_path.read_bytes() == config_path.read_bytes()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_files = {
        "summary": result.run_directory / "summary.json",
        "equity": result.run_directory / "equity.csv",
        "trades": result.run_directory / "trades.csv",
        "report_zh": report_zh_path,
        "strategy_config": strategy_config_path,
    }
    for name, artifact_path in artifact_files.items():
        assert Path(manifest["artifact_paths"][name]).resolve() == artifact_path.resolve()
        assert manifest["artifact_hashes"][name] == sha256_file(artifact_path)
    assert (
        Path(manifest["strategy_config_path"]).resolve()
        == strategy_config_path.resolve()
    )
    assert manifest["strategy_config_file_hash"] == sha256_file(
        strategy_config_path
    )

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["checks"]["artifacts"] is True
    assert audit["manifest_hash"] == sha256_file(manifest_path)
    audit_payload_hash = audit.pop("audit_payload_hash")
    assert audit_payload_hash == canonical_hash(audit)


def test_final_audit_failure_is_persisted_in_reports(monkeypatch, tmp_path):
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")

    from tv_quant import research_pipeline

    real_audit = research_pipeline.audit_backtest
    audit_calls = []

    def fail_final_artifact_audit(context):
        audit_calls.append(context.require_artifact_files)
        if context.require_artifact_files:
            return failed_audit()
        return real_audit(context)

    monkeypatch.setattr(
        research_pipeline,
        "audit_backtest",
        fail_final_artifact_audit,
    )

    result = run_pipeline(
        covered_ema_config(tmp_path),
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
    )

    assert audit_calls == [False, True]
    assert result.status == "FAIL"
    assert result.run_directory is not None
    summary = json.loads(
        (result.run_directory / "summary.json").read_text(encoding="utf-8")
    )
    audit = json.loads(
        (result.run_directory / "audit.json").read_text(encoding="utf-8")
    )
    assert summary["audit_status"] == "FAIL"
    assert audit["status"] == "FAIL"


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


def test_audit_only_accepts_equivalent_resolved_strategy_config_path(tmp_path):
    write_valid_spy_csv(tmp_path / "SPY_daily.csv")
    config_path = covered_ema_config(tmp_path)
    initial = run_pipeline(
        config_path,
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
    )
    assert initial.run_directory is not None

    manifest_path = initial.run_directory / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["strategy_config_path"] = str(
        initial.run_directory
        / "unused"
        / ".."
        / "strategy_config.yaml"
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    audit_path = initial.run_directory / "audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["manifest_hash"] = sha256_file(manifest_path)
    audit.pop("audit_payload_hash")
    audit["audit_payload_hash"] = canonical_hash(audit)
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    result = run_pipeline(
        config_path,
        PipelineOptions(
            run_directory=initial.run_directory,
            audit_only=True,
        ),
    )

    assert result.status in {"PASS", "CONDITIONAL_PASS"}


def test_audit_only_malformed_config_rewrites_stale_pass_without_side_effects(
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
    stale_audit = json.loads(audit_path.read_text(encoding="utf-8"))
    stale_audit["status"] = "PASS"
    stale_audit["audit_payload_hash"] = canonical_hash(
        {key: value for key, value in stale_audit.items() if key != "audit_payload_hash"}
    )
    audit_path.write_text(json.dumps(stale_audit), encoding="utf-8")
    artifact_bytes = {
        name: (initial.run_directory / filename).read_bytes()
        for name, filename in (
            ("summary", "summary.json"),
            ("equity", "equity.csv"),
            ("trades", "trades.csv"),
            ("manifest", "run_manifest.json"),
        )
    }

    def side_effect_forbidden(*args, **kwargs):
        pytest.fail("malformed audit-only config must block before side effects")

    for name in (
        "run_backtest",
        "calculate_metrics",
        "buy_and_hold_return",
        "write_reports",
    ):
        monkeypatch.setattr(f"tv_quant.research_pipeline.{name}", side_effect_forbidden)
    config_path.write_text("strategy: [\n", encoding="utf-8")

    result = run_pipeline(
        config_path,
        PipelineOptions(run_directory=initial.run_directory, audit_only=True),
        refresh_data=side_effect_forbidden,
    )

    assert result.status == "STRATEGY_CAPABILITY_BLOCKER"
    rewritten_audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert rewritten_audit["status"] == "STRATEGY_CAPABILITY_BLOCKER"
    assert any(
        issue["code"] == "STRATEGY_CONFIG_INVALID"
        for issue in rewritten_audit["issues"]
    )
    assert {
        name: (initial.run_directory / filename).read_bytes()
        for name, filename in (
            ("summary", "summary.json"),
            ("equity", "equity.csv"),
            ("trades", "trades.csv"),
            ("manifest", "run_manifest.json"),
        )
    } == artifact_bytes


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


def test_audit_only_classifies_invalid_source_data_as_fail(tmp_path):
    data_path = tmp_path / "SPY_daily.csv"
    write_valid_spy_csv(data_path)
    config_path = covered_ema_config(tmp_path)
    initial = run_pipeline(
        config_path,
        PipelineOptions(data_root=tmp_path, report_root=tmp_path / "reports"),
    )
    assert initial.run_directory is not None

    data = pd.read_csv(data_path)
    data.loc[1, "timestamp_utc"] = data.loc[0, "timestamp_utc"]
    data.to_csv(data_path, index=False)

    manifest_path = initial.run_directory / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["data_hash"] = sha256_file(data_path)
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    audit_path = initial.run_directory / "audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["manifest_hash"] = sha256_file(manifest_path)
    audit.pop("audit_payload_hash")
    audit["audit_payload_hash"] = canonical_hash(audit)
    audit_path.write_text(
        json.dumps(
            audit,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_pipeline(
        config_path,
        PipelineOptions(
            run_directory=initial.run_directory,
            audit_only=True,
        ),
    )

    assert result.status == "FAIL"
    audit_payload = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit_payload["status"] == "FAIL"
    assert any(
        issue["code"] == "DATA_QUALITY_FAILURE"
        for issue in audit_payload["issues"]
    )


@pytest.mark.parametrize(
    ("artifact_name", "file_name"),
    (
        ("summary", "summary.json"),
        ("equity", "equity.csv"),
        ("trades", "trades.csv"),
        ("report_zh", "report_zh.md"),
        ("strategy_config", "strategy_config.yaml"),
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
