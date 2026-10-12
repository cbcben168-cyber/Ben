import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quant_workflow.factor_research.progress_dashboard.db import canonical_strategy_hash
from quant_workflow.factor_research.progress_dashboard.ingest import expected_train_sessions


HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "fixtures" / "RunLog_TEST_FIXTURE_F001.csv"
STRATEGY = HERE.parents[3] / "factor_research" / "spy_factor_v1" / "SPY_FACTOR_RESEARCH_V1.py"
BATCH_STRATEGY = (
    HERE.parents[3]
    / "factor_research"
    / "spy_factor_batch_v1"
    / "SPY_SIX_FACTOR_BATCH_V1.py"
)
BATCH_TRAIN_STRATEGY = (
    HERE.parents[3]
    / "factor_research"
    / "spy_factor_batch_v1"
    / "SPY_SIX_FACTOR_BATCH_TRAIN_V1.py"
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
def raw_batch_runlog_fixture(tmp_path, batch_runlog_fixture):
    rows = list(csv.reader(batch_runlog_fixture.read_text(encoding="utf-8").splitlines()))
    messages = [row[1] for row in rows[1:]]
    lines = ["2026/07/10 12:00:00 (北京时间),INFO,系统,启动"]
    lines.extend(
        "2026/10/06 22:%02d:00 (北京时间),INFO,打印消息,%s" % (index * 5, message)
        for index, message in enumerate(messages)
    )
    lines.append("2026/10/10 11:59:59 (北京时间),INFO,系统,停止回测")
    path = tmp_path / "RunLog_TEST_C1_BATCH_RAW_FUTU.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


@pytest.fixture(scope="session")
def train_batch_runlog_fixture(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("train_batch")
    batch_id = "TEST_C1_BATCH_TRAIN_001"
    common = {
        "contract_version": "2.0",
        "batch_id": batch_id,
        "run_id": batch_id,
        "strategy_version": "FUTU_BATCH_FACTORS_TRAIN_V1",
        "strategy_hash": canonical_strategy_hash(BATCH_TRAIN_STRATEGY),
        "parameter_version": "C1-SIX-FACTOR-TRAIN-20251001-20260630-V1",
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
            "study_partition": "TRAIN",
            "system_start_target_et": "2025-07-01",
            "sensitivity_start_et": "2025-09-02",
            "study_start_et": "2025-10-01",
            "study_end_et": "2026-06-30",
            "early_close_dates_et": "2025-11-28,2025-12-24",
            "expected_sessions": 187,
            "expected_factor_events": 12083,
            "expected_labels": 36249,
            "expected_warmup_bars": 4956,
            "warmup_audit": "DUAL_RECURSIVE_EMA20_V1",
            "factor_ids": BATCH_FACTOR_IDS,
            "definition_hash": BATCH_DEFINITION_HASH,
            "fixture": True,
        },
        {
            **common,
            "event_type": "WARMUP_AUDIT",
            "record": "WARMUP_AUDIT",
            "status": "COMPLETE",
            "system_start_target_et": "2025-07-01",
            "first_observation_et": "2025-07-01T09:35:00",
            "study_start_et": "2025-10-01",
            "sensitivity_start_et": "2025-09-02",
            "warmup_bars_before_train": 4956,
            "expected_warmup_bars": 4956,
            "platform_ema20": "99.9000000000",
            "system_start_ema20": "99.9000000000",
            "sensitivity_start_ema20": "99.9000000000",
        },
    ]
    et = ZoneInfo("America/New_York")
    event_index = 0
    for day_text in sorted(expected_train_sessions()):
        day = datetime.fromisoformat(day_text).replace(tzinfo=et)
        signal_end = 715 if day_text in {"2025-11-28", "2025-12-24"} else 895
        day_count = 0
        for minute in range(575, signal_end + 1, 5):
            signal_et = day.replace(hour=minute // 60, minute=minute % 60)
            signal_close = 100.0 + event_index / 100000.0
            f001_pass = event_index % 2 == 0
            f002_pass = event_index % 3 != 0
            f003_pass = f001_pass and event_index % 4 == 0
            ema0 = signal_close - 0.1 if f001_pass else signal_close + 0.1
            ema3 = ema0 - 0.01 if f002_pass else ema0 + 0.01
            ema1 = signal_close - 0.01
            close1 = signal_close - 0.02 if f003_pass else signal_close + 0.02
            event = {
                **common,
                "event_type": "FACTOR_EVENT",
                "record": "FACTOR_EVENT",
                "signal_id": signal_et.strftime("%Y%m%d_%H%M"),
                "event_id": signal_et.strftime("%Y%m%d_%H%M"),
                "session_date_et": day_text,
                "signal_time_et": signal_et.isoformat(),
                "signal_time_utc": signal_et.astimezone(timezone.utc).isoformat(),
                "signal_close": f"{signal_close:.10f}",
                "factor_ids": BATCH_FACTOR_IDS,
                "definition_hash": BATCH_DEFINITION_HASH,
                "ema20_platform_0": f"{ema0:.10f}",
                "ema20_platform_1": f"{ema1:.10f}",
                "ema20_platform_3": f"{ema3:.10f}",
                "ema20_system_start_0": f"{ema0:.10f}",
                "ema20_sensitivity_start_0": f"{ema0:.10f}",
                "close_1": f"{close1:.10f}",
            }
            platform_states = {
                "f001": "PASS" if f001_pass else "FAIL",
                "f002": "PASS" if f002_pass else "FAIL",
                "f003": "PASS" if f003_pass else "FAIL",
            }
            for factor_number in range(1, 7):
                prefix = f"f{factor_number:03d}"
                state = platform_states.get(
                    prefix, "PASS" if (factor_number + event_index) % 2 else "FAIL"
                )
                event[prefix + "_state"] = state
                event[prefix + "_value"] = f"{factor_number / 100.0:.10f}"
                if factor_number <= 3:
                    event[prefix + "_system_state"] = state
                    event[prefix + "_sensitivity_state"] = state
            for horizon, minutes in ((3, 15), (6, 30), (12, 60)):
                target_et = signal_et + timedelta(minutes=minutes)
                forward_return = (
                    (0.0001 if f001_pass else -0.00005)
                    + horizon / 1000000.0
                    + (event_index % 7) / 10000000.0
                )
                target_close = signal_close * (1.0 + forward_return)
                suffix = str(horizon)
                event["r" + suffix] = f"{forward_return:.10f}"
                event["target_" + suffix + "_et"] = target_et.isoformat()
                event["target_" + suffix + "_utc"] = target_et.astimezone(timezone.utc).isoformat()
                event["target_" + suffix + "_close"] = f"{target_close:.10f}"
            records.append(event)
            event_index += 1
            day_count += 1
        records.append(
            {
                **common,
                "event_type": "DAY_END",
                "record": "DAY_END",
                "session_date_et": day_text,
                "status": "COMPLETE",
                "signal_count": day_count,
                "factor_event_count": day_count,
                "pending_count": 0,
                "error_count": 0,
                "expected_events": day_count,
            }
        )
    assert event_index == 12083
    records.append(
        {
            **common,
            "event_type": "RUN_END",
            "record": "RUN_END",
            "status": "COMPLETE",
            "completed_days": 187,
            "expected_sessions": 187,
            "incomplete_days": 0,
            "signal_count": 12083,
            "factor_event_count": 12083,
            "expected_factor_events": 12083,
            "label_count": 36249,
            "expected_labels": 36249,
            "error_count": 0,
            "warmup_audit_status": "COMPLETE",
            "f001_platform_system_mismatches": 0,
            "f002_platform_system_mismatches": 0,
            "f003_platform_system_mismatches": 0,
            "f001_system_sensitivity_mismatches": 0,
            "f002_system_sensitivity_mismatches": 0,
            "f003_system_sensitivity_mismatches": 0,
        }
    )
    path = tmp_path / "RunLog_TEST_C1_BATCH_TRAIN.csv"
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
