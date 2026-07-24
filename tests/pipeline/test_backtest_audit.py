from dataclasses import replace
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


def valid_context():
    spec = validate_strategy_mapping(valid_payload())
    data = pd.DataFrame({
        "timestamp_utc": pd.date_range("2020-01-01", periods=2, tz="UTC"),
        "ticker": ["SPY", "SPY"],
        "open": [100.0, 101.0], "high": [101.0, 102.0],
        "low": [99.0, 100.0], "close": [100.0, 101.0], "volume": [1000, 1000],
    })
    equity = pd.DataFrame({
        "timestamp_utc": data["timestamp_utc"],
        "equity": [100000.0, 100100.0],
        "daily_return": [0.0, 0.001],
    })
    trades = pd.DataFrame([{
        "timestamp_utc": data.loc[1, "timestamp_utc"], "side": "BUY", "shares": 1,
        "signal_timestamp_utc": data.loc[0, "timestamp_utc"], "market_open": 101.0,
        "execution_price": 101.0505, "slippage_bps": 5.0, "gross_notional": 101.0505,
        "commission": 0.05052525, "net_cash_flow": -101.10102525,
    }])
    manifest = {
        "strategy_config_hash": "config-hash", "data_hash": "data-hash", "code_commit": "abc",
        "provider": "Futu_LOCAL_CACHE", "symbol": "SPY", "timeframe": "1d",
        "start_date": "2020-01-01", "end_date": "2024-12-31", "fill_timing": "next_bar",
        "commission_bps": 5.0, "slippage_bps": 5.0, "optimization_allowed": False,
        "benchmark": "buy_and_hold", "generated_at_utc": "2024-01-01T00:00:00+00:00",
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
        artifact_paths={},
    )


def test_next_bar_fill_passes_for_existing_trade_shape():
    report = audit_backtest(valid_context())
    assert report.status is AuditStatus.PASS
    assert report.checks["next_bar_fill"] is True


def test_same_bar_fill_is_fail():
    context = replace(
        valid_context(),
        trades=valid_context().trades.assign(
            signal_timestamp_utc=valid_context().trades["timestamp_utc"]
        ),
    )
    report = audit_backtest(context)
    assert report.status is AuditStatus.FAIL
    assert any(issue.code == "SAME_BAR_SIGNAL_FILL" for issue in report.issues)


def test_cost_mismatch_is_fail():
    context = replace(
        valid_context(),
        trades=valid_context().trades.assign(commission=0.0, slippage_bps=0.0),
    )
    report = audit_backtest(context)
    assert report.status is AuditStatus.FAIL
    assert any(issue.code == "COST_MISMATCH" for issue in report.issues)


def test_empty_trades_are_conditional():
    report = audit_backtest(replace(valid_context(), trades=empty_trades()))
    assert report.status is AuditStatus.CONDITIONAL_PASS
    assert any(issue.code == "NO_TRADES" for issue in report.issues)


def test_missing_artifact_is_fail():
    context = replace(valid_context(), artifact_paths={"summary": Path("missing-summary.json")})
    assert audit_backtest(context).status is AuditStatus.FAIL


def test_capability_blocker_is_returned():
    capability = CapabilityResult(
        CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER,
        ("RSI is unsupported",),
        ("daily OHLCV",),
        ("fixed EMA50/EMA200",),
    )
    report = audit_backtest(replace(valid_context(), capability=capability))
    assert report.status is AuditStatus.STRATEGY_CAPABILITY_BLOCKER
