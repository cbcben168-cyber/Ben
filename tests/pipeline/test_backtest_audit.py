from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd

from tv_quant.backtest_audit import AuditContext, audit_backtest
from tv_quant.pipeline_models import AuditStatus, CapabilityResult, CapabilityStatus
from tv_quant.strategy_spec import check_capabilities, validate_strategy_mapping

from tests.pipeline.helpers import valid_payload


def empty_trades():
    return pd.DataFrame(columns=[
        "timestamp_utc", "side", "shares", "signal_timestamp_utc", "market_open",
        "execution_price", "slippage_bps", "gross_notional", "commission", "net_cash_flow",
    ])


def artifact_paths(root: Path) -> dict[str, Path]:
    paths = {
        name: root / f"{name}.json"
        for name in ("summary", "equity", "trades", "manifest", "audit")
    }
    for path in paths.values():
        path.write_text("{}", encoding="utf-8")
    return paths


def valid_context(tmp_path: Path):
    spec = replace(
        validate_strategy_mapping(valid_payload()),
        in_sample_period=(date(2020, 1, 1), date(2020, 12, 31)),
        out_of_sample_period=(date(2021, 1, 1), date(2021, 12, 31)),
    )
    data = pd.DataFrame({
        "timestamp_utc": pd.to_datetime([
            "2020-01-01", "2020-01-02", "2021-01-01", "2021-01-02",
        ], utc=True),
        "ticker": ["SPY"] * 4,
        "open": [100.0, 101.0, 102.0, 103.0], "high": [101.0, 102.0, 103.0, 104.0],
        "low": [99.0, 100.0, 101.0, 102.0], "close": [100.0, 101.0, 102.0, 103.0],
        "volume": [1000] * 4,
    })
    equity = pd.DataFrame({
        "timestamp_utc": data["timestamp_utc"],
        "equity": [100000.0, 100100.0, 100100.0, 100200.0],
        "daily_return": [0.0, 0.001, 0.0, 0.001],
    })
    trades = pd.DataFrame([
        {
            "timestamp_utc": data.loc[1, "timestamp_utc"], "side": "BUY", "shares": 1,
            "signal_timestamp_utc": data.loc[0, "timestamp_utc"], "market_open": 101.0,
            "execution_price": 101.0505, "slippage_bps": 5.0, "gross_notional": 101.0505,
            "commission": 0.05052525, "net_cash_flow": -101.10102525,
        },
        {
            "timestamp_utc": data.loc[3, "timestamp_utc"], "side": "BUY", "shares": 1,
            "signal_timestamp_utc": data.loc[2, "timestamp_utc"], "market_open": 103.0,
            "execution_price": 103.0515, "slippage_bps": 5.0, "gross_notional": 103.0515,
            "commission": 0.05152575, "net_cash_flow": -103.10302575,
        },
    ])
    manifest = {
        "strategy_config_hash": "config-hash", "data_hash": "data-hash", "code_commit": "abc",
        "provider": "Futu_LOCAL_CACHE", "symbol": "SPY", "timeframe": "1d",
        "start_date": "2020-01-01", "end_date": "2024-12-31", "fill_timing": "next_bar",
        "commission_bps": 5.0, "slippage_bps": 5.0, "optimization_allowed": False,
        "benchmark": "buy_and_hold", "generated_at_utc": "2024-01-01T00:00:00+00:00",
        "oos_locked": True, "locked_oos_start": "2021-01-01", "locked_oos_end": "2021-12-31",
    }
    return AuditContext(
        spec=spec,
        capability=check_capabilities(spec),
        data=data,
        equity=equity,
        trades=trades,
        strategy_metrics={"total_return": 0.001},
        benchmark_return=0.001,
        manifest=manifest,
        artifact_paths=artifact_paths(tmp_path),
    )


def test_next_bar_fill_passes_for_existing_trade_shape(tmp_path):
    report = audit_backtest(valid_context(tmp_path))
    assert report.status is AuditStatus.PASS
    assert report.checks["next_bar_fill"] is True


def test_same_bar_fill_is_fail(tmp_path):
    context = valid_context(tmp_path)
    context = replace(
        context,
        trades=context.trades.assign(
            signal_timestamp_utc=context.trades["timestamp_utc"]
        ),
    )
    report = audit_backtest(context)
    assert report.status is AuditStatus.FAIL
    assert any(issue.code == "SAME_BAR_SIGNAL_FILL" for issue in report.issues)


def test_cost_mismatch_is_fail(tmp_path):
    context = valid_context(tmp_path)
    context = replace(
        context,
        trades=context.trades.assign(commission=0.0, slippage_bps=0.0),
    )
    report = audit_backtest(context)
    assert report.status is AuditStatus.FAIL
    assert any(issue.code == "COST_MISMATCH" for issue in report.issues)


def test_empty_trades_are_conditional(tmp_path):
    context = valid_context(tmp_path)
    report = audit_backtest(replace(
        context,
        trades=empty_trades(),
        spec=replace(context.spec, in_sample_period=None, out_of_sample_period=None),
    ))
    assert report.status is AuditStatus.CONDITIONAL_PASS
    assert any(issue.code == "NO_TRADES" for issue in report.issues)


def test_missing_artifact_is_fail(tmp_path):
    paths = artifact_paths(tmp_path)
    paths["summary"] = tmp_path / "missing-summary.json"
    context = replace(valid_context(tmp_path), artifact_paths=paths)
    assert audit_backtest(context).status is AuditStatus.FAIL


def test_capability_blocker_is_returned(tmp_path):
    capability = CapabilityResult(
        CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER,
        ("RSI is unsupported",),
        ("daily OHLCV",),
        ("fixed EMA50/EMA200",),
    )
    report = audit_backtest(replace(valid_context(tmp_path), capability=capability))
    assert report.status is AuditStatus.STRATEGY_CAPABILITY_BLOCKER


def test_missing_oos_partition_is_conditional_not_pass(tmp_path):
    context = valid_context(tmp_path)
    report = audit_backtest(replace(
        context,
        spec=replace(context.spec, in_sample_period=None, out_of_sample_period=None),
    ))
    assert report.status is AuditStatus.CONDITIONAL_PASS
    assert any(issue.code == "OOS_BOUNDARY_UNVERIFIED" for issue in report.issues)


def test_overlapping_oos_boundary_is_fail(tmp_path):
    context = valid_context(tmp_path)
    report = audit_backtest(replace(
        context,
        spec=replace(
            context.spec,
            in_sample_period=(date(2020, 1, 1), date(2021, 1, 1)),
            out_of_sample_period=(date(2021, 1, 1), date(2021, 12, 31)),
        ),
    ))
    assert report.status is AuditStatus.FAIL
    assert any(issue.code == "OOS_BOUNDARY_FAILURE" for issue in report.issues)


def test_timestamped_artifacts_outside_locked_oos_boundary_fail(tmp_path):
    context = valid_context(tmp_path)
    leaked_data = context.data.assign(
        timestamp_utc=pd.to_datetime([
            "2020-01-01", "2020-01-02", "2021-01-01", "2022-01-02",
        ], utc=True),
    )
    report = audit_backtest(replace(context, data=leaked_data))
    assert report.status is AuditStatus.FAIL
    assert any(issue.code == "OOS_BOUNDARY_FAILURE" for issue in report.issues)


def test_artifacts_without_locked_oos_observations_fail(tmp_path):
    context = valid_context(tmp_path)
    incomplete_contexts = {
        "data": replace(context, data=context.data.iloc[:2].copy()),
        "equity": replace(context, equity=context.equity.iloc[:2].copy()),
        "trades": replace(context, trades=context.trades.iloc[:1].copy()),
    }

    for artifact, incomplete_context in incomplete_contexts.items():
        report = audit_backtest(incomplete_context)
        assert report.status is AuditStatus.FAIL
        assert any(
            issue.code == "OOS_BOUNDARY_FAILURE"
            and f"{artifact} has no timestamped observation" in issue.message
            for issue in report.issues
        )


def test_missing_equity_timestamp_evidence_is_fail(tmp_path):
    context = valid_context(tmp_path)
    report = audit_backtest(replace(
        context,
        equity=context.equity.drop(columns="timestamp_utc"),
    ))
    assert report.status is AuditStatus.FAIL
    assert any(
        issue.code == "OOS_BOUNDARY_FAILURE"
        and "equity is missing timestamp_utc evidence" in issue.message
        for issue in report.issues
    )


def test_single_year_positive_growth_is_conditional(tmp_path):
    context = valid_context(tmp_path)
    equity = context.equity.iloc[:2].copy()
    report = audit_backtest(replace(
        context,
        equity=equity,
        spec=replace(context.spec, in_sample_period=None, out_of_sample_period=None),
    ))
    assert report.status is AuditStatus.CONDITIONAL_PASS
    assert any(issue.code == "ANNUAL_RETURN_CONCENTRATION" for issue in report.issues)


def test_raw_open_fill_with_declared_slippage_is_fail(tmp_path):
    context = valid_context(tmp_path)
    trades = context.trades.assign(
        execution_price=context.trades["market_open"],
        gross_notional=context.trades["market_open"],
        commission=context.trades["market_open"] * 0.0005,
    )
    report = audit_backtest(replace(context, trades=trades))
    assert report.status is AuditStatus.FAIL
    assert any(issue.code == "COST_MISMATCH" for issue in report.issues)


def test_sell_fill_uses_adverse_open_slippage(tmp_path):
    context = valid_context(tmp_path)
    trades = context.trades.assign(
        side="SELL",
        market_open=100.0,
        execution_price=99.95,
        gross_notional=99.95,
        commission=0.049975,
    )
    report = audit_backtest(replace(context, trades=trades))
    assert report.status is AuditStatus.PASS
    assert report.checks["costs"] is True
