from pathlib import Path

import pandas as pd
import yaml


def valid_payload():
    return {
        "strategy_name": "ema_baseline",
        "asset_class": "equity",
        "symbol": "SPY",
        "benchmark": "buy_and_hold",
        "timeframe": "1d",
        "start_date": "2020-01-01",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "entry_rules": [{"type": "ema_crossover", "fast_period": 50, "slow_period": 200}],
        "exit_rules": [{"type": "ema_crossunder"}],
        "position_sizing": {"type": "cash_limited_long_only"},
        "commission_model": {"type": "basis_points", "value": 5},
        "slippage_model": {"type": "basis_points", "value": 5},
    }


def write_ema_config(root: Path, *, end_date: str = "2020-10-15") -> Path:
    payload = valid_payload()
    payload["end_date"] = end_date
    path = root / "ema.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def write_rsi_config(root: Path) -> Path:
    payload = valid_payload()
    payload["end_date"] = "2020-10-15"
    payload["entry_rules"] = [{"type": "rsi", "period": 2, "less_than": 10}]
    path = root / "rsi.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def write_crossover_csv(path: Path) -> None:
    dates = pd.date_range("2020-01-01", periods=203, freq="B", tz="UTC")
    close = [100.0] * 200 + [200.0, 200.0, 200.0]
    opens = [100.0] * 200 + [100.0, 150.0, 200.0]
    frame = pd.DataFrame({
        "timestamp_utc": dates,
        "ticker": ["SPY"] * len(dates),
        "open": opens,
        "high": [max(o, c) + 1 for o, c in zip(opens, close)],
        "low": [min(o, c) - 1 for o, c in zip(opens, close)],
        "close": close,
        "volume": [1_000_000] * len(dates),
    })
    frame.to_csv(path, index=False)


def write_valid_spy_csv(path: Path) -> None:
    write_crossover_csv(path)


def write_invalid_csv(path: Path) -> None:
    write_crossover_csv(path)
    frame = pd.read_csv(path)
    frame.loc[10, "close"] = None
    frame.to_csv(path, index=False)
