import ast
import contextlib
from datetime import date, datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace

from quant_workflow.factor_research.progress_dashboard.db import canonical_strategy_hash


STRATEGY = Path(__file__).resolve().parents[1] / "SPY_SIX_FACTOR_BATCH_TRAIN_V1.py"


def load_strategy():
    source = STRATEGY.read_text(encoding="utf-8")
    platform = {
        "clock": datetime(2025, 7, 1, 9, 35, tzinfo=timezone(timedelta(hours=-4))),
        "strategy": None,
    }

    def device_time(zone):
        if zone == "UTC":
            return platform["clock"].astimezone(timezone.utc).replace(tzinfo=None)
        return platform["clock"].replace(tzinfo=None)

    def completed_close(select):
        clock = platform["clock"]
        ordinal_component = (clock.date() - date(2025, 7, 1)).days * 0.02
        minute_component = (clock.hour * 60 + clock.minute - 575) * 0.001
        return 100.0 + ordinal_component + minute_component - (select - 2) * 0.005

    def ema_value(**kwargs):
        history = platform["strategy"].long_ema_history
        index = {2: -1, 3: -2, 5: -4}[kwargs["select"]]
        return history[index]

    env = {
        "StrategyBase": object,
        "AlgoStrategyType": SimpleNamespace(SECURITY="SECURITY"),
        "TimeZone": SimpleNamespace(ET="ET", UTC="UTC"),
        "BarType": SimpleNamespace(K_5M="K_5M"),
        "THType": SimpleNamespace(RTH="RTH"),
        "DataType": SimpleNamespace(CLOSE="CLOSE"),
        "declare_strategy_type": lambda value: None,
        "declare_trig_symbol": lambda: "TRIGGER",
        "get_symbol_code": lambda **kwargs: "US.SPY",
        "device_time": device_time,
        "bar_close": lambda **kwargs: completed_close(kwargs["select"]),
        "bar_open": lambda **kwargs: completed_close(kwargs["select"]) - 0.08,
        "bar_high": lambda **kwargs: completed_close(kwargs["select"]) + 0.02,
        "bar_low": lambda **kwargs: completed_close(kwargs["select"]) - 0.10,
        "ema": ema_value,
    }
    exec(compile(source, str(STRATEGY), "exec"), env)
    strategy = env["Strategy"]()
    with contextlib.redirect_stdout(StringIO()):
        strategy.initialize()
    platform["strategy"] = strategy
    return strategy, platform, source


def records(output):
    marker = "FUTU_FACTOR_BATCH_V1|"
    return [
        json.loads(line.split(marker, 1)[1])
        for line in output.splitlines()
        if marker in line
    ]


def warmup_sessions():
    current = date(2025, 7, 1)
    end = date(2025, 9, 30)
    holidays = {date(2025, 7, 4), date(2025, 9, 1)}
    while current <= end:
        if current.weekday() < 5 and current not in holidays:
            yield current
        current += timedelta(days=1)


def test_train_strategy_is_copyable_frozen_and_non_executable():
    _, _, source = load_strategy()
    tree = ast.parse(source)
    assert ast.get_docstring(tree) is None
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree))
    for forbidden in (
        "place_order",
        "modify_order",
        "cancel_order",
        "position_list",
        "account",
        "bar_volume",
        "get_acc_list",
        "unlock_trade",
    ):
        assert forbidden not in source
    assert "for select_value in (3, 4, 5, 6, 7)" in source
    assert "values[\"close_2\"] < values[\"close_1\"]" in source
    assert "values[\"body_ratio\"] > 0.60" in source
    assert canonical_strategy_hash(STRATEGY) == (
        "548a449d4811386adf90731e9ec3c753cf4ed5b74cae33ef35b3e60ea7871420"
    )


def test_train_contract_dates_counts_and_early_closes():
    strategy, _, _ = load_strategy()
    assert strategy.strategy_version == "FUTU_BATCH_FACTORS_TRAIN_V1"
    assert strategy.system_start_target == 20250701
    assert strategy.study_start == 20251001
    assert strategy.study_end == 20260630
    assert strategy.expected_session_count == 187
    assert strategy.expected_factor_event_count == 12083
    assert strategy.expected_label_count == 36249
    assert strategy.expected_events_for_day(20251001) == 65
    assert strategy.expected_events_for_day(20251128) == 29
    assert strategy.expected_events_for_day(20251224) == 29


def test_warmup_is_separate_and_emits_actual_ema_audit():
    strategy, platform, _ = load_strategy()
    buffer = StringIO()
    with contextlib.redirect_stdout(buffer):
        for session in warmup_sessions():
            last_minute = 780 if session == date(2025, 7, 3) else 960
            for minute in range(575, last_minute + 1, 5):
                platform["clock"] = datetime(
                    session.year,
                    session.month,
                    session.day,
                    minute // 60,
                    minute % 60,
                    tzinfo=timezone(timedelta(hours=-4)),
                )
                strategy.handle_data()
        assert strategy.long_bar_count == 4956
        platform["clock"] = datetime(
            2025, 10, 1, 9, 35, tzinfo=timezone(timedelta(hours=-4))
        )
        strategy.handle_data()

    output = records(buffer.getvalue())
    audits = [item for item in output if item["event_type"] == "WARMUP_AUDIT"]
    assert len(audits) == 1
    assert audits[0]["status"] == "COMPLETE"
    assert audits[0]["first_observation_et"].startswith("2025-07-01T09:35")
    assert audits[0]["warmup_bars_before_train"] == 4956
    assert not [item for item in output if item["event_type"] == "FACTOR_EVENT"]
    assert strategy.day_signal_count == 1
