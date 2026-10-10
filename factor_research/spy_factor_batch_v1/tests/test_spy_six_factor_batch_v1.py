import ast
import contextlib
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace

from quant_workflow.factor_research.progress_dashboard.db import canonical_strategy_hash


STRATEGY = Path(__file__).resolve().parents[1] / "SPY_SIX_FACTOR_BATCH_V1.py"


def load_strategy():
    source = STRATEGY.read_text(encoding="utf-8")
    platform = {"clock": datetime(2026, 10, 6, 9, 35, tzinfo=timezone(timedelta(hours=-4)))}

    def device_time(zone):
        if zone == "UTC":
            return platform["clock"].astimezone(timezone.utc).replace(tzinfo=None)
        return platform["clock"].replace(tzinfo=None)

    def completed_close(select):
        minute_index = (platform["clock"].hour * 60 + platform["clock"].minute - 575) / 5.0
        return 100.0 + minute_index * 0.10 - (select - 2) * 0.05

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
        "bar_high": lambda **kwargs: completed_close(kwargs["select"]) + 0.01,
        "bar_low": lambda **kwargs: completed_close(kwargs["select"]) - 0.09,
        "ema": lambda **kwargs: completed_close(kwargs["select"]) - 0.02,
    }
    exec(compile(source, str(STRATEGY), "exec"), env)
    return env["Strategy"], platform, source


def parse_records(output):
    records = []
    for line in output.splitlines():
        marker = "FUTU_FACTOR_BATCH_V1|"
        if marker in line:
            records.append(json.loads(line.split(marker, 1)[1]))
    return records


def test_strategy_is_copyable_and_contains_no_trade_or_volume_api():
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
    ):
        assert forbidden not in source
    assert canonical_strategy_hash(STRATEGY) == "5446da28047d127d74f84c544e3726827bbcc3aa4d01bf912c30b4a9731d849c"


def test_one_day_emits_65_complete_six_factor_events():
    strategy_type, platform, _ = load_strategy()
    buffer = StringIO()

    with contextlib.redirect_stdout(buffer):
        strategy = strategy_type()
        strategy.initialize()
        strategy.study_start = 20261006
        strategy.study_end = 20261006
        strategy.expected_days = 1
        for minute in range(575, 956, 5):
            platform["clock"] = datetime(
                2026,
                10,
                6,
                minute // 60,
                minute % 60,
                tzinfo=timezone(timedelta(hours=-4)),
            )
            strategy.handle_data()

    records = parse_records(buffer.getvalue())
    starts = [item for item in records if item["event_type"] == "RUN_START"]
    events = [item for item in records if item["event_type"] == "FACTOR_EVENT"]
    days = [item for item in records if item["event_type"] == "DAY_END"]
    ends = [item for item in records if item["event_type"] == "RUN_END"]

    assert len(starts) == 1
    assert len(events) == 65
    assert len(days) == 1
    assert len(ends) == 1
    assert days[0]["status"] == "COMPLETE"
    assert ends[0]["status"] == "COMPLETE"
    assert events[0]["signal_time_et"].startswith("2026-10-06T09:35")
    assert events[-1]["signal_time_et"].startswith("2026-10-06T14:55")
    assert events[-1]["target_12_et"].startswith("2026-10-06T15:55")
    assert {events[0][f"f{number:03d}_state"] for number in range(1, 7)} <= {
        "PASS",
        "FAIL",
    }
    assert events[0]["r3"] == "0.0030000000"
    assert events[0]["r6"] == "0.0060000000"
    assert events[0]["r12"] == "0.0120000000"
