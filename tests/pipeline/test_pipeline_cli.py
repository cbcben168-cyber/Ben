import json
from datetime import date
from types import SimpleNamespace

import pytest

from tests.pipeline.helpers import (
    write_ema_config,
    write_rsi_config,
    write_valid_spy_csv,
)
from tv_quant import pipeline_cli
from tv_quant.pipeline_cli import _refresh_data, exit_code_for_status
from tv_quant.research_pipeline import PipelineOptions, run_pipeline


def refresh_spec():
    return SimpleNamespace(
        symbol="SPY",
        data_source="validated_local_cache_first",
        start_date=date(2020, 1, 1),
        end_date=date(2020, 10, 9),
    )


def test_success_statuses_return_zero():
    assert exit_code_for_status("PASS") == 0
    assert exit_code_for_status("CONDITIONAL_PASS") == 0


def test_blockers_and_failures_return_nonzero():
    assert exit_code_for_status("STRATEGY_CAPABILITY_BLOCKER") == 3
    assert exit_code_for_status("DATA_CAPABILITY_BLOCKER") == 4
    assert exit_code_for_status("FAIL") == 5


def test_refresh_uses_target_parent_for_path_with_spaces(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        pipeline_cli.legacy_cli,
        "main",
        lambda argv: calls.append(argv) or 0,
    )
    target_path = tmp_path / "daily data" / "SPY_daily.csv"

    _refresh_data(refresh_spec(), target_path)

    assert len(calls) == 1
    argv = calls[0]
    out_dir = argv[argv.index("--out-dir") + 1]
    assert out_dir == str(target_path.parent)
    assert target_path.name not in type(target_path)(out_dir).parts


def test_main_passes_flags_and_skips_config_preload_when_refresh_disabled(
    monkeypatch,
    tmp_path,
    capsys,
):
    config_path = tmp_path / "strategy config.yaml"
    run_directory = tmp_path / "existing run"
    captured = {}

    monkeypatch.setattr(
        pipeline_cli,
        "load_strategy_spec",
        lambda path: pytest.fail("refresh-disabled main must not preload config"),
    )

    def fake_run_pipeline(path, options, refresh_data):
        captured.update(
            path=path,
            options=options,
            refresh_data=refresh_data,
        )
        return SimpleNamespace(
            status="CONDITIONAL_PASS",
            run_directory=run_directory,
        )

    monkeypatch.setattr(pipeline_cli, "run_pipeline", fake_run_pipeline)

    exit_code = pipeline_cli.main(
        [
            "--strategy-config", str(config_path),
            "--data-root", str(tmp_path / "data root"),
            "--report-root", str(tmp_path / "report root"),
            "--run-directory", str(run_directory),
            "--audit-only",
            "--skip-data-refresh",
            "--smoke-test-data",
        ]
    )

    assert exit_code == 0
    assert captured["path"] == config_path
    assert captured["refresh_data"] is None
    assert captured["options"] == PipelineOptions(
        data_root=tmp_path / "data root",
        report_root=tmp_path / "report root",
        run_directory=run_directory,
        audit_only=True,
        skip_data_refresh=True,
        allow_smoke_test_data=True,
    )
    output = capsys.readouterr().out
    assert "status=CONDITIONAL_PASS" in output
    assert f"report_directory={run_directory}" in output


def test_main_maps_refresh_delegation_runtime_error_to_data_blocker(
    monkeypatch,
    tmp_path,
    capsys,
):
    spec = refresh_spec()
    config_path = tmp_path / "strategy.yaml"
    target_path = tmp_path / "data root" / "SPY_daily.csv"
    legacy_calls = []
    monkeypatch.setattr(
        pipeline_cli,
        "load_strategy_spec",
        lambda path: spec,
    )
    monkeypatch.setattr(
        pipeline_cli.legacy_cli,
        "main",
        lambda argv: legacy_calls.append(argv) or 9,
    )

    def invoke_refresh(path, options, refresh_data):
        assert refresh_data is not None
        refresh_data(spec, target_path)
        pytest.fail("refresh failure must stop the pipeline")

    monkeypatch.setattr(pipeline_cli, "run_pipeline", invoke_refresh)

    exit_code = pipeline_cli.main(
        [
            "--strategy-config", str(config_path),
            "--data-root", str(target_path.parent),
        ]
    )

    assert exit_code == 4
    assert len(legacy_calls) == 1
    output = capsys.readouterr().out
    assert output == "data_refresh_error=data refresh failed with exit code 9\n"


def test_main_does_not_rewrite_unrelated_pipeline_runtime_error(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        pipeline_cli,
        "load_strategy_spec",
        lambda path: refresh_spec(),
    )

    def fail_pipeline(*args, **kwargs):
        raise RuntimeError("pipeline implementation failure")

    monkeypatch.setattr(pipeline_cli, "run_pipeline", fail_pipeline)

    with pytest.raises(RuntimeError, match="pipeline implementation failure"):
        pipeline_cli.main(
            [
                "--strategy-config", str(tmp_path / "strategy.yaml"),
            ]
        )


def test_audit_only_malformed_config_returns_strategy_blocker_and_writes_audit(
    tmp_path,
    capsys,
):
    data_root = tmp_path / "data root"
    data_root.mkdir()
    write_valid_spy_csv(data_root / "SPY_daily.csv")
    config_path = write_ema_config(tmp_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "end_date: '2020-10-15'",
            "end_date: '2020-10-09'",
        ),
        encoding="utf-8",
    )
    initial = run_pipeline(
        config_path,
        PipelineOptions(
            data_root=data_root,
            report_root=tmp_path / "reports",
        ),
    )
    assert initial.run_directory is not None
    config_path.write_text("strategy: [\n", encoding="utf-8")

    exit_code = pipeline_cli.main(
        [
            "--strategy-config", str(config_path),
            "--run-directory", str(initial.run_directory),
            "--audit-only",
        ]
    )

    assert exit_code == 3
    output = capsys.readouterr().out
    assert "status=STRATEGY_CAPABILITY_BLOCKER" in output
    assert "configuration_error=" not in output
    audit = json.loads(
        (initial.run_directory / "audit.json").read_text(encoding="utf-8")
    )
    assert audit["status"] == "STRATEGY_CAPABILITY_BLOCKER"
    assert any(
        issue["code"] == "STRATEGY_CONFIG_INVALID"
        for issue in audit["issues"]
    )


def test_non_audit_invalid_config_returns_strategy_blocker_and_record(
    tmp_path,
    capsys,
):
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text("strategy_name: ema_baseline\n", encoding="utf-8")
    report_root = tmp_path / "reports"

    exit_code = pipeline_cli.main(
        [
            "--strategy-config", str(config_path),
            "--report-root", str(report_root),
            "--skip-data-refresh",
        ]
    )

    assert exit_code == 3
    output = capsys.readouterr().out
    assert "status=STRATEGY_CAPABILITY_BLOCKER" in output
    assert "configuration_error=" not in output
    records = list(report_root.glob("failure_*.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text(encoding="utf-8"))["failed_stage"] == 0


def test_non_audit_capability_blocker_returns_exit_3_and_record(
    tmp_path,
    capsys,
):
    config_path = write_rsi_config(tmp_path)
    report_root = tmp_path / "reports"

    exit_code = pipeline_cli.main(
        [
            "--strategy-config", str(config_path),
            "--report-root", str(report_root),
            "--skip-data-refresh",
        ]
    )

    assert exit_code == 3
    assert "status=STRATEGY_CAPABILITY_BLOCKER" in capsys.readouterr().out
    records = list(report_root.glob("failure_*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text(encoding="utf-8"))
    assert record["failed_stage"] == 1
    assert record["error_code"] == "CAPABILITY_BLOCKER"
