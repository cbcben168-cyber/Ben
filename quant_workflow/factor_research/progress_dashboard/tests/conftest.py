import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_workflow.factor_research.progress_dashboard.db import canonical_strategy_hash


HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "fixtures" / "RunLog_TEST_FIXTURE_F001.csv"
STRATEGY = HERE.parents[3] / "factor_research" / "spy_factor_v1" / "SPY_FACTOR_RESEARCH_V1.py"


@pytest.fixture
def runlog_fixture(tmp_path):
    content = TEMPLATE.read_text(encoding="utf-8")
    content = content.replace(
        "a4189f867d94a34a8852aead81c6f122ecb3258704407b45d6201d643863cba2",
        canonical_strategy_hash(STRATEGY),
    )
    path = tmp_path / "RunLog_TEST_FIXTURE_F001.csv"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def legacy_runlog_fixture(tmp_path):
    path = tmp_path / "RunLog_TEST_LEGACY_F001.csv"
    et = timezone(timedelta(hours=-4))
    dates = (
        "2026-09-28",
        "2026-09-29",
        "2026-09-30",
        "2026-10-01",
        "2026-10-02",
        "2026-10-05",
        "2026-10-06",
    )
    messages = [
        "SPY_FACTOR_V1|record=START|version=1|run_phase=FUNCTIONAL_VALIDATION|"
        "date_start_et=2026-09-28|date_end_et=2026-10-06|bar_type=K_5M|"
        "select=2|session=RTH|factor=CLOSE_GT_EMA20|horizons_bars=3,6,12|"
        "orders_enabled=False|volume_enabled=False|edge_claim=PROHIBITED"
    ]
    for date_text in dates:
        day = datetime.fromisoformat(date_text).replace(tzinfo=et)
        for minute in range(575, 896, 5):
            signal_et = day.replace(hour=minute // 60, minute=minute % 60)
            signal_utc = signal_et.astimezone(timezone.utc)
            event_id = signal_et.strftime("%Y%m%d_%H%M")
            signal_close = 100.0 + minute / 10000.0
            ema20 = signal_close - 0.5
            messages.append(
                "SPY_FACTOR_V1|record=EVENT|event_id={event_id}|session_date_et={date}|"
                "trigger_et={signal_et}|trigger_utc={signal_utc}|symbol=US.SPY|"
                "bar_type=K_5M|select=2|session=RTH|close={close:.10f}|"
                "ema20={ema:.10f}|factor_state=PASS|horizons_bars=3,6,12".format(
                    event_id=event_id,
                    date=date_text,
                    signal_et=signal_et.isoformat(),
                    signal_utc=signal_utc.isoformat(),
                    close=signal_close,
                    ema=ema20,
                )
            )
            for horizon, horizon_minutes in ((3, 15), (6, 30), (12, 60)):
                outcome_et = signal_et + timedelta(minutes=horizon_minutes)
                outcome_utc = outcome_et.astimezone(timezone.utc)
                future_close = signal_close * (1.0 + horizon / 10000.0)
                forward_return = future_close / signal_close - 1.0
                messages.append(
                    "SPY_FACTOR_V1|record=OUTCOME|event_id={event_id}|"
                    "signal_et={signal_et}|signal_utc={signal_utc}|"
                    "outcome_et={outcome_et}|outcome_utc={outcome_utc}|symbol=US.SPY|"
                    "bar_type=K_5M|select=2|session=RTH|factor_state=PASS|"
                    "horizon_bars={horizon}|horizon_minutes={minutes}|"
                    "signal_close={signal_close:.10f}|future_close={future_close:.10f}|"
                    "return={forward_return:.10f}".format(
                        event_id=event_id,
                        signal_et=signal_et.isoformat(),
                        signal_utc=signal_utc.isoformat(),
                        outcome_et=outcome_et.isoformat(),
                        outcome_utc=outcome_utc.isoformat(),
                        horizon=horizon,
                        minutes=horizon_minutes,
                        signal_close=signal_close,
                        future_close=future_close,
                        forward_return=forward_return,
                    )
                )
        messages.append(
            "SPY_FACTOR_V1|record=DAY_STATUS|session_date_et={date}|status=COMPLETE|"
            "event_count=65|outcomes_h3=65|outcomes_h6=65|outcomes_h12=65|"
            "pending_count=0|error_count=0".format(date=date_text)
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("time", "message"))
        for index, message in enumerate(messages):
            writer.writerow((index, message))
    return path
