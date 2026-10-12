from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import HORIZONS, TRAIN_END, TRAIN_START


PRICE_COLUMNS = ("open", "high", "low", "close")


def _apply_forward_adjustments(frame: pd.DataFrame, rehab_path: Path) -> pd.DataFrame:
    result = frame.copy()
    for column in PRICE_COLUMNS:
        result[f"px_{column}"] = result[column].astype(float)
    rehab = pd.read_csv(rehab_path).sort_values("ex_div_date")
    for row in rehab.itertuples(index=False):
        mask = result["session_date"] < str(row.ex_div_date)
        for column in PRICE_COLUMNS:
            key = f"px_{column}"
            result.loc[mask, key] = (
                float(row.forward_adj_factor_a) * result.loc[mask, key]
                + float(row.forward_adj_factor_b)
            )
    return result


def _time_bucket(value: str) -> str:
    minute = int(value[:2]) * 60 + int(value[3:])
    if minute < 10 * 60 + 30:
        return "09:35-10:30"
    if minute < 12 * 60:
        return "10:30-12:00"
    if minute < 14 * 60:
        return "12:00-14:00"
    return "14:00-15:55"


def build_features(frame: pd.DataFrame, rehab_path: Path) -> pd.DataFrame:
    data = _apply_forward_adjustments(frame, rehab_path)
    close = data["px_close"]
    high = data["px_high"]
    low = data["px_low"]
    open_ = data["px_open"]
    previous_close = close.shift(1)
    data["tr"] = np.maximum.reduce(
        [(high - low).to_numpy(), (high - previous_close).abs().to_numpy(), (low - previous_close).abs().to_numpy()]
    )
    data.loc[0, "tr"] = high.iloc[0] - low.iloc[0]
    data["atr12"] = data["tr"].rolling(12, min_periods=12).mean()
    data["atr20"] = data["tr"].rolling(20, min_periods=20).mean()
    data["atr50"] = data["tr"].rolling(50, min_periods=50).mean()
    data["ema20"] = close.ewm(span=20, adjust=False).mean()
    data["ema50"] = close.ewm(span=50, adjust=False).mean()
    data["sma20"] = close.rolling(20, min_periods=20).mean()
    data["std20"] = close.rolling(20, min_periods=20).std(ddof=0)
    data["median_tr20"] = data["tr"].shift(1).rolling(20, min_periods=20).median()
    data["median_atr50"] = data["atr12"].shift(1).rolling(50, min_periods=50).median()
    data["clock"] = data["time_et"].dt.strftime("%H:%M")
    data["time_bucket"] = data["clock"].map(_time_bucket)
    grouped = data.groupby("session_date", sort=False)
    data["session_open"] = grouped["px_open"].transform("first")
    data["session_high"] = grouped["px_high"].cummax()
    data["session_low"] = grouped["px_low"].cummin()
    session_range = data["session_high"] - data["session_low"]
    data["session_position"] = np.where(
        session_range > 0, (close - data["session_low"]) / session_range, 0.5
    )
    data["bar_in_session"] = grouped.cumcount()

    daily = grouped.agg(
        day_open=("px_open", "first"),
        day_high=("px_high", "max"),
        day_low=("px_low", "min"),
        day_close=("px_close", "last"),
        day_ema20=("ema20", "last"),
        day_ema50=("ema50", "last"),
    )
    daily["day_range"] = daily["day_high"] - daily["day_low"]
    daily["day_return"] = daily["day_close"] / daily["day_open"] - 1.0
    daily["day_clv"] = np.where(
        daily["day_range"] > 0,
        (daily["day_close"] - daily["day_low"]) / daily["day_range"],
        0.5,
    )
    daily["range_median20"] = daily["day_range"].shift(1).rolling(20, min_periods=20).median()
    previous = daily.shift(1).add_prefix("prev_")
    data = data.join(previous, on="session_date")
    data["gap_return"] = data["session_open"] / data["prev_day_close"] - 1.0

    same_clock = data.groupby("clock", sort=False)["atr12"]
    data["same_clock_atr_median20"] = same_clock.transform(
        lambda values: values.shift(1).rolling(20, min_periods=20).median()
    )
    data["same_clock_vol_ratio"] = data["atr12"] / data["same_clock_atr_median20"]
    data["f012_state"] = np.select(
        [data["same_clock_vol_ratio"] < 0.8, data["same_clock_vol_ratio"] > 1.2],
        ["LOW", "HIGH"],
        default="NORMAL",
    )
    data.loc[data["same_clock_atr_median20"].isna(), "f012_state"] = "NOT_AVAILABLE"

    data["premarket_trend"] = np.select(
        [
            (data["prev_day_close"] > data["prev_day_ema20"]) & (data["prev_day_ema20"] > data["prev_day_ema50"]),
            (data["prev_day_close"] < data["prev_day_ema20"]) & (data["prev_day_ema20"] < data["prev_day_ema50"]),
        ],
        ["BULL", "BEAR"],
        default="NEUTRAL",
    )
    data["premarket_vol"] = np.select(
        [
            data["prev_day_range"] < 0.8 * data["prev_range_median20"],
            data["prev_day_range"] > 1.2 * data["prev_range_median20"],
        ],
        ["LOW", "HIGH"],
        default="NORMAL",
    )
    data["premarket_direction"] = np.select(
        [data["prev_day_return"] > 0.005, data["prev_day_return"] < -0.005],
        ["UP", "DOWN"],
        default="FLAT",
    )
    data["premarket_clv"] = np.select(
        [data["prev_day_clv"] <= 0.3, data["prev_day_clv"] >= 0.7],
        ["LOW", "HIGH"],
        default="MID",
    )
    data["dynamic_trend"] = np.select(
        [
            (close > data["ema20"]) & (data["ema20"] > data["ema50"]),
            (close < data["ema20"]) & (data["ema20"] < data["ema50"]),
        ],
        ["BULL", "BEAR"],
        default="NEUTRAL",
    )
    data["dynamic_gap"] = np.select(
        [data["gap_return"] >= 0.003, data["gap_return"] <= -0.003],
        ["GAP_UP", "GAP_DOWN"],
        default="NO_GAP",
    )
    data["dynamic_range_position"] = np.select(
        [data["session_position"] <= 0.25, data["session_position"] >= 0.75],
        ["LOW", "HIGH"],
        default="MID",
    )
    for horizon in HORIZONS:
        future = grouped["px_close"].shift(-horizon)
        data[f"return_h{horizon}"] = future / close - 1.0
    data["is_train"] = data["session_date"].between(TRAIN_START, TRAIN_END)
    return data


def _directions(condition_long: pd.Series, condition_short: pd.Series | None = None) -> np.ndarray:
    short = pd.Series(False, index=condition_long.index) if condition_short is None else condition_short
    return np.select([condition_long.fillna(False), short.fillna(False)], [1, -1], default=0)


def _first_per_day(mask: pd.Series, data: pd.DataFrame) -> pd.Series:
    return mask & (mask.groupby(data["session_date"]).cumsum() == 1)


def compute_factor_matrix(data: pd.DataFrame) -> pd.DataFrame:
    c, o, h, l = (data[f"px_{key}"] for key in ("close", "open", "high", "low"))
    atr = data["atr20"]
    candle_range = h - l
    clv = np.where(candle_range > 0, (c - l) / candle_range, 0.5)
    body = (c - o).abs()
    prior5_high = h.shift(1).rolling(5, min_periods=5).max()
    prior12_high = h.shift(1).rolling(12, min_periods=12).max()
    prior12_low = l.shift(1).rolling(12, min_periods=12).min()
    prior20_high = h.shift(1).rolling(20, min_periods=20).max()
    prior20_low = l.shift(1).rolling(20, min_periods=20).min()
    prior6_high = data.groupby(data["session_date"])["px_high"].transform(
        lambda values: values.shift(1).rolling(6, min_periods=6).max()
    )
    prior6_low = data.groupby(data["session_date"])["px_low"].transform(
        lambda values: values.shift(1).rolling(6, min_periods=6).min()
    )
    range6 = prior6_high - prior6_low
    median_range6 = range6.shift(1).rolling(20, min_periods=20).median()
    z_ema = (c - data["ema20"]) / atr
    z_sma = (c - data["sma20"]) / data["std20"]
    return3 = c / c.shift(3) - 1.0
    return12 = c / c.shift(12) - 1.0
    path = c.diff().abs().rolling(12, min_periods=12).sum()
    efficiency = (c - c.shift(12)).abs() / path
    acceleration = (data["ema20"] - data["ema20"].shift(3)) - (
        data["ema20"].shift(3) - data["ema20"].shift(6)
    )
    vol_ratio = data["atr12"] / data["atr50"]
    session = data["session_date"]
    first_bar = data["bar_in_session"] == 0
    first_hour = data["bar_in_session"] < 12
    gap_up = data["gap_return"] >= 0.004
    gap_down = data["gap_return"] <= -0.004
    opening_range_high = data.groupby(session)["px_high"].transform(lambda values: values.iloc[:6].max())
    opening_range_low = data.groupby(session)["px_low"].transform(lambda values: values.iloc[:6].min())
    after_or = data["bar_in_session"] >= 6

    matrix = pd.DataFrame(index=data.index)
    matrix["F001"] = _directions(c > data["ema20"])
    matrix["F002"] = _directions(data["ema20"] > data["ema20"].shift(3))
    matrix["F003"] = _directions((c.shift(1) <= data["ema20"].shift(1)) & (c > data["ema20"]))
    matrix["F004"] = _directions(c > prior5_high)
    matrix["F005"] = _directions((c.shift(2) < c.shift(1)) & (c.shift(1) < c))
    matrix["F006"] = _directions((c > o) & (candle_range > 0) & ((c - o) / candle_range > 0.60))
    f007_base = (range6 <= 0.60 * median_range6) & (data["tr"] >= 1.50 * data["median_tr20"])
    matrix["F007"] = _directions(f007_base & (c > prior6_high), f007_base & (c < prior6_low))
    f008_values = np.zeros(len(data), dtype=np.int8)
    armed = {1: True, -1: True}
    active_day = None
    last_candidate_minute = -999
    for index, row in data.iterrows():
        if row.session_date != active_day:
            active_day = row.session_date
            last_candidate_minute = -999
        minute_value = int(row.clock[:2]) * 60 + int(row.clock[3:])
        strategy_end = 740 if row.session_date in {"2025-07-03", "2025-11-28", "2025-12-24"} else 920
        if not row.is_train or minute_value > strategy_end:
            continue
        z_value = z_ema.at[index]
        if not np.isfinite(z_value):
            continue
        if abs(z_value) < 1.0:
            armed = {1: True, -1: True}
        candidate = 1 if minute_value >= 605 and z_value <= -2.0 and armed[1] else -1 if minute_value >= 605 and z_value >= 2.0 and armed[-1] else 0
        if candidate:
            armed[candidate] = False
            if minute_value - last_candidate_minute >= 30:
                f008_values[index] = candidate
                last_candidate_minute = minute_value
    matrix["F008"] = f008_values
    matrix["F009"] = _directions(first_bar & gap_down & (c > data["session_open"]), first_bar & gap_up & (c < data["session_open"]))
    false_down = (l < prior12_low - 0.10 * atr) & (c >= prior12_low)
    false_up = (h > prior12_high + 0.10 * atr) & (c <= prior12_high)
    matrix["F010"] = _directions(false_down, false_up)
    f011_values = np.zeros(len(data), dtype=np.int8)
    for _, indexes in data.groupby("session_date", sort=False).groups.items():
        for index in indexes:
            if not after_or.at[index]:
                continue
            if c.at[index] > opening_range_high.at[index] + 0.10 * atr.at[index]:
                f011_values[index] = 1
                break
            if c.at[index] < opening_range_low.at[index] - 0.10 * atr.at[index]:
                f011_values[index] = -1
                break
    matrix["F011"] = f011_values
    matrix["F012"] = np.select([data["f012_state"] == "HIGH", data["f012_state"] == "LOW"], [1, -1], default=0)
    matrix["F013"] = _directions(return3 >= 0.0025, return3 <= -0.0025)
    matrix["F014"] = _directions(data["ema20"] - data["ema50"] >= 0.25 * atr, data["ema50"] - data["ema20"] >= 0.25 * atr)
    matrix["F015"] = _directions((efficiency >= 0.55) & (c > c.shift(12)), (efficiency >= 0.55) & (c < c.shift(12)))
    matrix["F016"] = _directions(acceleration >= 0.05 * atr, acceleration <= -0.05 * atr)
    matrix["F017"] = _directions(z_sma <= -1.5, z_sma >= 1.5)
    matrix["F018"] = _directions(return3 <= -0.005, return3 >= 0.005)
    rising3 = (c.shift(2) < c.shift(1)) & (c.shift(1) < c)
    falling3 = (c.shift(2) > c.shift(1)) & (c.shift(1) > c)
    range_shock = data["tr"] >= 1.5 * data["median_tr20"]
    matrix["F019"] = _directions(falling3 & range_shock, rising3 & range_shock)
    outside = (h > h.shift(1)) & (l < l.shift(1))
    prior_mid = (h.shift(1) + l.shift(1)) / 2.0
    matrix["F020"] = _directions(outside & (c > prior_mid) & (c > o), outside & (c < prior_mid) & (c < o))
    matrix["F021"] = np.where(data["atr12"] / data["median_atr50"] <= 0.75, 1, 0)
    matrix["F022"] = np.where(data["atr12"] / data["median_atr50"] >= 1.35, 1, 0)
    matrix["F023"] = _directions((data["tr"] >= 2 * data["median_tr20"]) & (clv >= 0.8), (data["tr"] >= 2 * data["median_tr20"]) & (clv <= 0.2))
    matrix["F024"] = np.select([(vol_ratio >= 1.2) & (vol_ratio.shift(1) < 1.2), (vol_ratio <= 0.8) & (vol_ratio.shift(1) > 0.8)], [1, -1], default=0)
    matrix["F025"] = _directions(c > prior20_high, c < prior20_low)
    matrix["F026"] = _directions((c > prior12_high) & (c.shift(1) > prior12_high.shift(1)), (c < prior12_low) & (c.shift(1) < prior12_low.shift(1)))
    matrix["F027"] = _directions((c.shift(1) < prior20_low.shift(1)) & (c >= prior20_low), (c.shift(1) > prior20_high.shift(1)) & (c <= prior20_high))
    inside = (h.shift(1) < h.shift(2)) & (l.shift(1) > l.shift(2))
    matrix["F028"] = _directions(inside & (c > h.shift(1)), inside & (c < l.shift(1)))
    matrix["F029"] = _directions(first_bar & (data["gap_return"] >= 0.003) & (c > data["session_open"]) & (clv >= 0.7), first_bar & (data["gap_return"] <= -0.003) & (c < data["session_open"]) & (clv <= 0.3))
    fill_up = _first_per_day(first_hour & gap_down & (c >= data["prev_day_close"]), data)
    fill_down = _first_per_day(first_hour & gap_up & (c <= data["prev_day_close"]), data)
    matrix["F030"] = _directions(fill_up, fill_down)
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)
    matrix["F031"] = _directions((lower_wick >= 2 * body) & (clv > 0.5), (upper_wick >= 2 * body) & (clv < 0.5))
    matrix["F032"] = _directions(pd.Series(clv, index=data.index) >= 0.8, pd.Series(clv, index=data.index) <= 0.2)
    matrix["F033"] = _directions((c.shift(3) < c.shift(2)) & (c.shift(2) < c.shift(1)) & (c.shift(1) < c), (c.shift(3) > c.shift(2)) & (c.shift(2) > c.shift(1)) & (c.shift(1) > c))
    matrix["F034"] = _directions(data["session_position"] >= 0.8, data["session_position"] <= 0.2)
    long_pullback = (c > data["ema20"]) & (data["ema20"] > data["ema50"]) & ((data["session_high"] - c) / atr).between(0.5, 1.5)
    short_pullback = (c < data["ema20"]) & (data["ema20"] < data["ema50"]) & ((c - data["session_low"]) / atr).between(0.5, 1.5)
    matrix["F035"] = _directions(long_pullback, short_pullback)
    matrix["F036"] = _directions((c > data["ema20"]) & (data["ema20"] > data["ema50"]) & (return12 > 0), (c < data["ema20"]) & (data["ema20"] < data["ema50"]) & (return12 < 0))
    matrix = matrix.fillna(0).astype("int8")
    return matrix


def build_factor_events(data: pd.DataFrame, matrix: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    base_columns = [
        "bar_index", "session_date", "time_et", "clock", "time_bucket", "px_close",
        "premarket_trend", "premarket_vol", "premarket_direction", "premarket_clv",
        "dynamic_trend", "dynamic_gap", "f012_state", "dynamic_range_position",
        "return_h3", "return_h6", "return_h12",
    ]
    eligible = data["is_train"]
    for factor_id in matrix.columns:
        active = eligible & (matrix[factor_id] != 0)
        if not active.any():
            continue
        part = data.loc[active, base_columns].copy()
        part.insert(0, "factor_id", factor_id)
        part.insert(2, "direction", matrix.loc[active, factor_id].astype(int).to_numpy())
        rows.append(part)
    events = pd.concat(rows, ignore_index=True)
    events.rename(columns={"px_close": "signal_close"}, inplace=True)
    events["time_et"] = events["time_et"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    return events
