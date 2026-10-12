from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd

from .contracts import EARLY_CLOSES, StrategySpec


def build_strategy_signals(data: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    close = data["px_close"]
    ema20 = data["ema20"]
    ema50 = data["ema50"]
    atr = data["atr20"]
    minute = data["clock"].str.replace(":", "").astype(int)
    early = data["session_date"].isin(EARLY_CLOSES)
    s01_limit = np.where(early, 1220, 1520)
    s02_limit = np.where(early, 1150, 1450)
    in_train = data["is_train"]
    filter_context = factors.copy()
    filter_context["F029"] = (
        factors["F029"].replace(0, np.nan).groupby(data["session_date"]).ffill().fillna(0).astype("int8")
    )

    long_s01 = (
        (close > ema20) & (ema20 > ema50) & (ema20 > ema20.shift(3))
        & (data["px_low"] <= ema20) & (close > ema20)
    )
    short_s01 = (
        (close < ema20) & (ema20 < ema50) & (ema20 < ema20.shift(3))
        & (data["px_high"] >= ema20) & (close < ema20)
    )
    rows: list[dict] = []
    for index in data.index[in_train & (minute <= s01_limit) & (long_s01 | short_s01)]:
        direction = 1 if long_s01.at[index] else -1
        stop = data.at[index, "px_low"] - 0.25 * atr.at[index] if direction == 1 else data.at[index, "px_high"] + 0.25 * atr.at[index]
        rows.append(_signal_row(data, index, "S01", direction, stop, np.nan, filter_context))

    f011 = factors["F011"]
    for index in data.index[in_train & (minute <= s02_limit) & (f011 != 0)]:
        day = data["session_date"] == data.at[index, "session_date"]
        opening = data.loc[day].iloc[:6]
        or_high = float(opening["px_high"].max())
        or_low = float(opening["px_low"].min())
        width = or_high - or_low
        direction = int(f011.at[index])
        stop = or_high - 0.5 * width if direction == 1 else or_low + 0.5 * width
        row = _signal_row(data, index, "S02", direction, stop, np.nan, filter_context)
        row["opening_range_high"] = or_high
        row["opening_range_low"] = or_low
        rows.append(row)

    f008 = factors["F008"]
    s03 = in_train & (minute <= s01_limit) & (f008 != 0) & ((ema20 - ema50).abs() <= 0.5 * atr)
    for index in data.index[s03]:
        direction = int(f008.at[index])
        stop = data.at[index, "px_low"] - atr.at[index] if direction == 1 else data.at[index, "px_high"] + atr.at[index]
        rows.append(_signal_row(data, index, "S03", direction, stop, float(ema20.at[index]), filter_context))
    return pd.DataFrame(rows).sort_values(["strategy_id", "bar_index", "direction"]).reset_index(drop=True)


def _signal_row(data: pd.DataFrame, index: int, strategy_id: str, direction: int, stop: float, target: float, factors: pd.DataFrame) -> dict:
    row = data.loc[index]
    return {
        "signal_id": f"{strategy_id}-{int(row.bar_index):05d}-{direction:+d}",
        "strategy_id": strategy_id,
        "bar_index": int(row.bar_index),
        "session_date": row.session_date,
        "signal_time_et": row.time_et,
        "direction": direction,
        "signal_close": float(row.px_close),
        "signal_high": float(row.px_high),
        "signal_low": float(row.px_low),
        "atr20": float(row.atr20),
        "ema20": float(row.ema20),
        "stop_anchor": float(stop),
        "target_anchor": float(target) if np.isfinite(target) else np.nan,
        "time_bucket": row.time_bucket,
        "premarket_trend": row.premarket_trend,
        "premarket_vol": row.premarket_vol,
        "dynamic_trend": row.dynamic_trend,
        "f012_state": row.f012_state,
        "dynamic_gap": row.dynamic_gap,
        "factor_snapshot": {key: int(factors.at[index, key]) for key in factors.columns},
    }


def _filter_pass(signal: dict, spec: StrategySpec) -> bool:
    if spec.filter_factor == "NONE":
        return True
    value = signal["factor_snapshot"][spec.filter_factor]
    if spec.filter_factor in {"F021", "F022", "F024"}:
        return value != 0
    if spec.strategy_id == "S03" and spec.filter_factor == "F034":
        return value == -signal["direction"]
    return value == signal["direction"]


def _simulate_one(data_by_index: pd.DataFrame, signal: dict, spec: StrategySpec) -> tuple[dict | None, str, int | None]:
    signal_index = signal["bar_index"]
    entry_index = signal_index + 1
    if entry_index not in data_by_index.index:
        return None, "NO_NEXT_BAR", None
    entry_bar = data_by_index.loc[entry_index]
    if entry_bar.session_date != signal["session_date"]:
        return None, "NO_NEXT_SESSION_ENTRY", None
    direction = signal["direction"]
    entry = float(entry_bar.px_open)
    stop = float(signal["stop_anchor"])
    if (direction == 1 and entry <= stop) or (direction == -1 and entry >= stop):
        return None, "STOP_CROSSED_BEFORE_ENTRY", None
    risk = direction * (entry - stop)
    if not np.isfinite(risk) or risk <= 0:
        return None, "INVALID_INITIAL_RISK", None
    if signal["strategy_id"] in {"S01", "S02"}:
        target = entry + direction * 1.5 * risk
    else:
        target = float(signal["target_anchor"])
        if (direction == 1 and target <= entry) or (direction == -1 and target >= entry):
            return None, "TARGET_CROSSED_BEFORE_ENTRY", None

    same_day = data_by_index[data_by_index["session_date"] == signal["session_date"]]
    eligible = same_day.loc[entry_index:].iloc[: spec.time_exit_bars]
    if eligible.empty:
        return None, "NO_HOLDING_BARS", None
    mfe = 0.0
    mae = 0.0
    ambiguous = False
    path_uncertain = False
    exit_price = float(eligible.iloc[-1].px_close)
    exit_index = int(eligible.iloc[-1].bar_index)
    exit_reason = "TIME"
    target_first_price = exit_price
    for bar in eligible.itertuples():
        bar_index = int(bar.bar_index)
        open_price = float(bar.px_open)
        if (direction == 1 and open_price <= stop) or (direction == -1 and open_price >= stop):
            exit_price = open_price
            target_first_price = open_price
            exit_index = bar_index
            exit_reason = "GAP_STOP"
            path_uncertain = True
            mfe = max(mfe, direction * (open_price - entry) / entry)
            mae = min(mae, direction * (open_price - entry) / entry)
            break
        stop_hit = float(bar.px_low) <= stop if direction == 1 else float(bar.px_high) >= stop
        target_hit = float(bar.px_high) >= target if direction == 1 else float(bar.px_low) <= target
        if stop_hit or target_hit:
            ambiguous = stop_hit and target_hit
            path_uncertain = True
            exit_price = stop if stop_hit else target
            target_first_price = target if target_hit else stop
            exit_index = bar_index
            exit_reason = "AMBIGUOUS_STOP_FIRST" if ambiguous else "STOP" if stop_hit else "TARGET"
            mfe = max(mfe, direction * (exit_price - entry) / entry)
            mae = min(mae, direction * (exit_price - entry) / entry)
            break
        mfe = max(mfe, direction * (float(bar.px_high if direction == 1 else bar.px_low) - entry) / entry)
        mae = min(mae, direction * (float(bar.px_low if direction == 1 else bar.px_high) - entry) / entry)
    gross = direction * (exit_price - entry) / entry
    net = gross - spec.cost_round_trip_bps / 10_000.0
    target_first_net = direction * (target_first_price - entry) / entry - spec.cost_round_trip_bps / 10_000.0
    exit_bar = data_by_index.loc[exit_index]
    trade = {
        "variant_id": spec.variant_id,
        "strategy_id": spec.strategy_id,
        "signal_id": signal["signal_id"],
        "session_date": signal["session_date"],
        "direction": "LONG" if direction == 1 else "SHORT",
        "signal_time_et": signal["signal_time_et"],
        "entry_time_et": signal["signal_time_et"],
        "entry_observed_at_et": entry_bar.time_et,
        "entry_price": entry,
        "stop_price": stop,
        "target_price": target,
        "actual_initial_risk": risk,
        "reward_to_risk": direction * (target - entry) / risk,
        "exit_time_et": exit_bar.time_et,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "gross_return": gross,
        "cost_bps": spec.cost_round_trip_bps,
        "net_return": net,
        "target_first_net_return": target_first_net,
        "mfe": mfe,
        "mae": mae,
        "ambiguous_path": ambiguous,
        "path_uncertain": path_uncertain,
        "position_conflict": False,
        "time_bucket": signal["time_bucket"],
        "premarket_trend": signal["premarket_trend"],
        "premarket_vol": signal["premarket_vol"],
        "dynamic_trend": signal["dynamic_trend"],
        "f012_state": signal["f012_state"],
        "dynamic_gap": signal["dynamic_gap"],
        "filter_factor": spec.filter_factor,
    }
    return trade, "TRADED", exit_index


def replay_strategies(data: pd.DataFrame, signals: pd.DataFrame, specs: list[StrategySpec]) -> tuple[pd.DataFrame, pd.DataFrame]:
    indexed = data.set_index("bar_index", drop=False)
    trades: list[dict] = []
    audit: list[dict] = []
    for spec in specs:
        relevant = signals[signals["strategy_id"] == spec.strategy_id].sort_values("bar_index")
        busy_until = -1
        for raw in relevant.to_dict("records"):
            audit_row = {
                "variant_id": spec.variant_id,
                "strategy_id": spec.strategy_id,
                "signal_id": raw["signal_id"],
                "session_date": raw["session_date"],
                "signal_time_et": raw["signal_time_et"],
                "direction": "LONG" if raw["direction"] == 1 else "SHORT",
                "filter_factor": spec.filter_factor,
            }
            if not _filter_pass(raw, spec):
                audit.append({**audit_row, "decision": "FILTERED_OUT"})
                continue
            if raw["bar_index"] < busy_until:
                audit.append({**audit_row, "decision": "POSITION_BUSY"})
                continue
            trade, decision, exit_index = _simulate_one(indexed, raw, spec)
            audit.append({**audit_row, "decision": decision})
            if trade is not None:
                trades.append(trade)
                busy_until = int(exit_index)
    trade_frame = pd.DataFrame(trades)
    audit_frame = pd.DataFrame(audit)
    for column in ("signal_time_et", "entry_time_et", "entry_observed_at_et", "exit_time_et"):
        if column in trade_frame:
            trade_frame[column] = pd.to_datetime(trade_frame[column]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    if "signal_time_et" in audit_frame:
        audit_frame["signal_time_et"] = pd.to_datetime(audit_frame["signal_time_et"]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    return trade_frame, audit_frame
