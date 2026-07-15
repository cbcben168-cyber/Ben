"""EMA crossover strategy with next-bar-open execution."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


TRADE_COLUMNS = (
    "timestamp_utc", "side", "shares", "signal_timestamp_utc", "market_open",
    "execution_price", "slippage_bps", "gross_notional", "commission", "net_cash_flow",
)


@dataclass
class BacktestResult:
    equity: pd.DataFrame
    trades: pd.DataFrame
    warnings: list[str]


def run_backtest(
    data: pd.DataFrame,
    initial_cash: float = 100_000.0,
    commission_bps: float = 5.0,
    slippage_bps: float = 5.0,
) -> BacktestResult:
    """Run the fixed EMA50/EMA200 long-only strategy without look-ahead bias."""
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if commission_bps < 0 or slippage_bps < 0:
        raise ValueError("commission_bps and slippage_bps must be non-negative")

    bars = data.copy().reset_index(drop=True)
    bars["ema_fast"] = bars["close"].ewm(span=50, adjust=False, min_periods=200).mean()
    bars["ema_slow"] = bars["close"].ewm(span=200, adjust=False, min_periods=200).mean()

    commission_rate = commission_bps / 10_000
    slippage_rate = slippage_bps / 10_000
    cash = float(initial_cash)
    shares = 0
    pending_side: str | None = None
    pending_signal_timestamp = None
    trade_rows: list[dict[str, object]] = []
    equity_rows: list[dict[str, object]] = []
    warnings: list[str] = []

    for index, bar in bars.iterrows():
        if pending_side == "BUY" and shares == 0:
            market_open = float(bar["open"])
            execution_price = market_open * (1 + slippage_rate)
            bought = int(cash // (execution_price * (1 + commission_rate)))
            if bought > 0:
                gross_notional = bought * execution_price
                commission = gross_notional * commission_rate
                net_cash_flow = -(gross_notional + commission)
                cash += net_cash_flow
                shares = bought
                trade_rows.append(
                    _trade_row(bar, "BUY", bought, pending_signal_timestamp, market_open,
                               execution_price, slippage_bps, gross_notional, commission, net_cash_flow)
                )
        elif pending_side == "SELL" and shares > 0:
            market_open = float(bar["open"])
            execution_price = market_open * (1 - slippage_rate)
            gross_notional = shares * execution_price
            commission = gross_notional * commission_rate
            net_cash_flow = gross_notional - commission
            trade_rows.append(
                _trade_row(bar, "SELL", shares, pending_signal_timestamp, market_open,
                           execution_price, slippage_bps, gross_notional, commission, net_cash_flow)
            )
            cash += net_cash_flow
            shares = 0
        pending_side = None
        pending_signal_timestamp = None

        close = float(bar["close"])
        equity = cash + shares * close
        prior_equity = equity_rows[-1]["equity"] if equity_rows else None
        daily_return = 0.0 if prior_equity is None else equity / float(prior_equity) - 1
        peak = max(initial_cash, *(float(row["equity"]) for row in equity_rows), equity)
        equity_rows.append(
            {
                "timestamp_utc": bar["timestamp_utc"],
                "cash": cash,
                "shares": shares,
                "close": close,
                "position_value": shares * close,
                "equity": equity,
                "daily_return": daily_return,
                "drawdown": equity / peak - 1,
            }
        )

        if index == 0 or index + 1 >= len(bars):
            continue
        previous = bars.iloc[index - 1]
        if pd.isna(previous["ema_fast"]) or pd.isna(previous["ema_slow"]):
            continue
        if pd.isna(bar["ema_fast"]) or pd.isna(bar["ema_slow"]):
            continue
        if previous["ema_fast"] <= previous["ema_slow"] and bar["ema_fast"] > bar["ema_slow"]:
            pending_side = "BUY"
            pending_signal_timestamp = bar["timestamp_utc"]
        elif previous["ema_fast"] >= previous["ema_slow"] and bar["ema_fast"] < bar["ema_slow"]:
            pending_side = "SELL"
            pending_signal_timestamp = bar["timestamp_utc"]

    if len(bars) > 1:
        last = bars.iloc[-1]
        previous = bars.iloc[-2]
        if not any(pd.isna(value) for value in (previous["ema_fast"], previous["ema_slow"], last["ema_fast"], last["ema_slow"])):
            if (previous["ema_fast"] <= previous["ema_slow"] < last["ema_fast"]) or (
                previous["ema_fast"] >= previous["ema_slow"] > last["ema_fast"]
            ):
                warnings.append("final-bar signal ignored because no next-bar open exists")

    return BacktestResult(
        equity=pd.DataFrame(equity_rows),
        trades=pd.DataFrame(trade_rows, columns=TRADE_COLUMNS),
        warnings=warnings,
    )


def _trade_row(
    bar: pd.Series,
    side: str,
    shares: int,
    signal_timestamp: object,
    market_open: float,
    execution_price: float,
    slippage_bps: float,
    gross_notional: float,
    commission: float,
    net_cash_flow: float,
) -> dict[str, object]:
    return {
        "timestamp_utc": bar["timestamp_utc"],
        "side": side,
        "shares": shares,
        "signal_timestamp_utc": signal_timestamp,
        "market_open": market_open,
        "execution_price": execution_price,
        "slippage_bps": slippage_bps,
        "gross_notional": gross_notional,
        "commission": commission,
        "net_cash_flow": net_cash_flow,
    }
