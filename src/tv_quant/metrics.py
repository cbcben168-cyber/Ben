"""Performance metrics and a cost-consistent Buy-and-Hold benchmark."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def calculate_metrics(equity: pd.DataFrame, trades: pd.DataFrame, initial_cash: float) -> dict[str, float | int | None]:
    """Calculate deterministic summary metrics from daily equity and fill records."""
    final_equity = float(equity["equity"].iloc[-1])
    total_return = final_equity / initial_cash - 1
    timestamps = pd.to_datetime(equity["timestamp_utc"], utc=True)
    elapsed_days = (timestamps.iloc[-1] - timestamps.iloc[0]).total_seconds() / 86_400
    cagr = None if elapsed_days <= 0 else (final_equity / initial_cash) ** (365.25 / elapsed_days) - 1
    equity_values = equity["equity"].astype(float).to_numpy()
    peaks = np.maximum.accumulate(np.concatenate(([initial_cash], equity_values)))[1:]
    max_drawdown = float(np.min(equity_values / peaks - 1))
    returns = equity["daily_return"].iloc[1:]
    volatility = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    sharpe = None if volatility == 0 else float(returns.mean() / volatility * math.sqrt(252))
    _, win_rate = _closed_trade_stats(trades)
    return {
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe,
        "trade_count": int(len(trades)),
        "win_rate": win_rate,
    }


def buy_and_hold_return(data: pd.DataFrame, initial_cash: float, commission_bps: float, slippage_bps: float) -> float:
    """Return the cost-adjusted first-open-to-last-close benchmark return."""
    commission_rate = commission_bps / 10_000
    execution_price = float(data.iloc[0]["open"]) * (1 + slippage_bps / 10_000)
    shares = int(initial_cash // (execution_price * (1 + commission_rate)))
    spent = shares * execution_price * (1 + commission_rate)
    final_equity = initial_cash - spent + shares * float(data.iloc[-1]["close"])
    return final_equity / initial_cash - 1


def _closed_trade_stats(trades: pd.DataFrame) -> tuple[int, float | None]:
    entry_cost: float | None = None
    outcomes: list[float] = []
    for _, trade in trades.iterrows():
        if trade["side"] == "BUY":
            entry_cost = -float(trade["net_cash_flow"])
        elif trade["side"] == "SELL" and entry_cost is not None:
            outcomes.append(float(trade["net_cash_flow"]) - entry_cost)
            entry_cost = None
    if not outcomes:
        return 0, None
    return len(outcomes), float(np.mean([outcome > 0 for outcome in outcomes]))
