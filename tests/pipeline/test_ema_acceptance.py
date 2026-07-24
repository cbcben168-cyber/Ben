import json

from tv_quant.research_pipeline import PipelineOptions, run_pipeline

from tests.pipeline.helpers import (
    write_crossover_csv,
    write_ema_config,
    write_rsi_config,
)


def test_ema_pipeline_writes_report_and_audit(tmp_path):
    write_crossover_csv(tmp_path / "SPY_daily.csv")
    config = write_ema_config(tmp_path)
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "end_date: '2020-10-15'", "end_date: '2020-10-09'"
        ),
        encoding="utf-8",
    )
    result = run_pipeline(
        config,
        PipelineOptions(
            data_root=tmp_path,
            report_root=tmp_path / "reports",
            skip_data_refresh=True,
        ),
    )
    assert result.status in {"PASS", "CONDITIONAL_PASS"}
    assert (result.run_directory / "summary.json").is_file()
    assert (result.run_directory / "equity.csv").is_file()
    assert (result.run_directory / "trades.csv").is_file()
    assert (result.run_directory / "run_manifest.json").is_file()
    assert (result.run_directory / "audit.json").is_file()
    summary = json.loads(
        (result.run_directory / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["buy_and_hold_return"] is not None
    assert summary["parameters"]["ema_fast"] == 50
    assert summary["parameters"]["ema_slow"] == 200
    assert summary["audit_status"] in {"PASS", "CONDITIONAL_PASS"}


def test_rsi_blocker_does_not_refresh_or_backtest(tmp_path, monkeypatch):
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
