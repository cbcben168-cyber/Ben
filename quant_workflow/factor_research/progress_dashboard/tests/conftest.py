import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from quant_workflow.factor_research.progress_dashboard.db import canonical_strategy_hash


HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "fixtures" / "RunLog_TEST_FIXTURE_F001.csv"
STRATEGY = HERE.parents[3] / "factor_research" / "spy_factor_v1" / "SPY_FACTOR_RESEARCH_V1.py"
BATCH_STRATEGY = (
    HERE.parents[3]
    / "factor_research"
    / "spy_factor_batch_v1"
    / "SPY_SIX_FACTOR_BATCH_V1.py"
)
BATCH_FACTOR_IDS = ",".join(
    (
        "SPY_F001_CLOSE_GT_EMA20",
        "SPY_F002_EMA20_RISING_3",
        "SPY_F003_CLOSE_CROSS_ABOVE_EMA20",
        "SPY_F004_CLOSE_BREAKS_PRIOR_5_HIGH",
        "SPY_F005_THREE_CLOSE_MOMENTUM",
        "SPY_F006_STRONG_BULL_BODY",
    )
)
BATCH_DEFINITION_HASH = "370c846144bf3e184642acd4a55c97976c75c377073a74f43aa001fef758be23"


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
def batch_runlog_fixture(tmp_path):
    et = timezone(timedelta(hours=-4))
    batch_id = "TEST_C1_BATCH_001"
    common = {
        "contract_version": "2.0",
        "batch_id": batch_id,
        "run_id": batch_id,
        "strategy_version": "FUTU_BATCH_FACTORS_V1",
        "strategy_hash": canonical_strategy_hash(BATCH_STRATEGY),
        "parameter_version": "C1-SIX-FACTOR-S0-V1",
        "symbol": "US.SPY",
        "timeframe": "5m",
        "bar_type": "K_5M",
        "select": 2,
        "session": "RTH",
        "timezone": "America/New_York",
    }
    records = [
        {
            **common,
            "event_type": "RUN_START",
            "record": "START",
            "study_partition": "FUNCTIONAL_VALIDATION",
            "study_start_et": "2026-10-06",
            "study_end_et": "2026-10-06",
            "factor_ids": BATCH_FACTOR_IDS,
            "definition_hash": BATCH_DEFINITION_HASH,
            "fixture": True,
        }
    ]
    for index, minute in enumerate((600, 605)):
        signal_et = datetime(2026, 10, 6, minute // 60, minute % 60, tzinfo=et)
        signal_close = 100.0 + index
        event = {
            **common,
            "event_type": "FACTOR_EVENT",
            "record": "FACTOR_EVENT",
            "signal_id": signal_et.strftime("%Y%m%d_%H%M"),
            "event_id": signal_et.strftime("%Y%m%d_%H%M"),
            "session_date_et": "2026-10-06",
            "signal_time_et": signal_et.isoformat(),
            "signal_time_utc": signal_et.astimezone(timezone.utc).isoformat(),
            "signal_close": f"{signal_close:.10f}",
            "factor_ids": BATCH_FACTOR_IDS,
            "definition_hash": BATCH_DEFINITION_HASH,
        }
        for factor_number in range(1, 7):
            prefix = f"f{factor_number:03d}"
            event[prefix + "_state"] = "PASS" if (factor_number + index) % 2 else "FAIL"
            event[prefix + "_value"] = f"{factor_number / 100.0:.10f}"
        for horizon, minutes in ((3, 15), (6, 30), (12, 60)):
            target_et = signal_et + timedelta(minutes=minutes)
            forward_return = (1 if index == 0 else -1) * horizon / 1000.0
            target_close = signal_close * (1.0 + forward_return)
            suffix = str(horizon)
            event["r" + suffix] = f"{forward_return:.10f}"
            event["target_" + suffix + "_et"] = target_et.isoformat()
            event["target_" + suffix + "_utc"] = target_et.astimezone(timezone.utc).isoformat()
            event["target_" + suffix + "_close"] = f"{target_close:.10f}"
        records.append(event)
    records.extend(
        (
            {
                **common,
                "event_type": "DAY_END",
                "record": "DAY_END",
                "session_date_et": "2026-10-06",
                "status": "COMPLETE",
                "signal_count": 2,
                "factor_event_count": 2,
                "pending_count": 0,
                "error_count": 0,
                "expected_events": 2,
            },
            {
                **common,
                "event_type": "RUN_END",
                "record": "RUN_END",
                "status": "COMPLETE",
                "signal_count": 2,
                "factor_event_count": 2,
                "error_count": 0,
            },
        )
    )
    path = tmp_path / "RunLog_TEST_C1_BATCH.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("time", "message"))
        for index, record in enumerate(records):
            writer.writerow(
                (
                    index,
                    "FUTU_FACTOR_BATCH_V1|"
                    + json.dumps(record, ensure_ascii=False, separators=(",", ":")),
                )
            )
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
