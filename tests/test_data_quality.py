import pandas as pd
import pytest

from tv_quant.data_quality import DataQualityError, validate_ohlcv


def make_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp_utc": pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC"),
            "ticker": ["SPY"] * 3,
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "volume": [1000, 1100, 1200],
        }
    )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda frame: frame.iloc[0:0], "empty"),
        (lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True), "duplicate"),
        (lambda frame: frame.assign(close=[100.5, None, 102.5]), "missing"),
        (lambda frame: frame.iloc[[1, 0, 2]].reset_index(drop=True), "sorted"),
        (lambda frame: frame.assign(open=[100.0, -1.0, 102.0]), "positive"),
        (lambda frame: frame.assign(volume=[1000, -1, 1200]), "volume"),
        (lambda frame: frame.assign(low=[99.0, 103.0, 101.0]), "low"),
    ],
)
def test_validate_ohlcv_rejects_invalid_data(mutator, message):
    with pytest.raises(DataQualityError, match=message):
        validate_ohlcv(mutator(make_frame()))


def test_validate_ohlcv_returns_large_price_move_warning():
    frame = make_frame().assign(close=[100.0, 160.0, 161.0], high=[101.0, 161.0, 162.0])

    warnings = validate_ohlcv(frame)

    assert len(warnings) == 1
    assert "50%" in warnings[0]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda frame: frame.assign(close=[100.5, float("inf"), 102.5]), "finite"),
        (lambda frame: frame.assign(volume=[1000, float("inf"), 1200]), "finite"),
        (
            lambda frame: frame.assign(
                timestamp_utc=[
                    pd.Timestamp("2024-01-01", tz="UTC"),
                    pd.Timestamp("2024-01-02 13:00", tz="UTC"),
                    pd.Timestamp("2024-01-03", tz="UTC"),
                ]
            ),
            "midnight",
        ),
    ],
)
def test_validate_ohlcv_rejects_non_standard_finite_daily_values(mutator, message):
    with pytest.raises(DataQualityError, match=message):
        validate_ohlcv(mutator(make_frame()))
