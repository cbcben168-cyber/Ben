from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import csv
import json

import pytest

from quant_workflow.factor_research.progress_dashboard.db import Database, canonical_strategy_hash
from quant_workflow.factor_research.progress_dashboard.ingest import Importer, parse_runlog
from quant_workflow.factor_research.progress_dashboard.stats import compute_strategy_inference


ROOT = Path(__file__).resolve().parents[4]
STRATEGY = (
    ROOT
    / "factor_research"
    / "spy_factor_batch_v1"
    / "SPY_C1_STRATEGY_BATCH_TRAIN_V3_1.py"
)
COMPAT_STRATEGY = STRATEGY.with_name("SPY_C1_STRATEGY_BATCH_TRAIN_V3_1_1.py")
AUDIT = (
    ROOT
    / "factor_research"
    / "spy_factor_batch_v1"
    / "validation"
    / "train_ema_supplement_7514881494081894629"
)
REGISTRY = (
    ("CANDIDATE_SCREEN", "CANDIDATE", 30),
    ("STRATEGY_BASELINE", "L1", 6),
    ("REGIME_INCREMENT", "L2_REGIME", 12),
    ("TIME_INCREMENT", "L2_TIME", 24),
    ("REGIME_TIME_INTERACTION", "L3", 6),
    ("F001_F006_FILTER_INCREMENT", "L4", 36),
)


def _strategy(path: Path = STRATEGY):
    namespace = {"StrategyBase": object}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    strategy = namespace["Strategy"]()
    strategy.setup()
    return strategy


def _common(strategy_path: Path = STRATEGY) -> dict:
    compat = strategy_path == COMPAT_STRATEGY
    suffix = "V3_1_1" if compat else "V3_1"
    return {
        "contract_version": "3.1.1" if compat else "3.1",
        "batch_id": "TEST_STRATEGY_" + suffix,
        "run_id": "TEST_STRATEGY_" + suffix,
        "strategy_version": "FUTU_C1_STRATEGY_BATCH_TRAIN_" + suffix,
        "strategy_hash": canonical_strategy_hash(strategy_path),
        "parameter_version": "C1-STRATEGY-FIRST-TRAIN-V3.1.1" if compat else "C1-STRATEGY-FIRST-TRAIN-V3.1",
        "symbol": "US.SPY",
        "timeframe": "5m",
        "bar_type": "K_5M",
        "select": 2,
        "session": "RTH",
        "timezone": "America/New_York",
    }


def _write_fixture(
    path: Path, *, bad_entry_label: bool = False,
    strategy_path: Path = STRATEGY,
) -> Path:
    common = _common(strategy_path)
    compat = strategy_path == COMPAT_STRATEGY
    et = timezone(timedelta(hours=-4))
    signal_time = datetime(2026, 6, 30, 10, 0, tzinfo=et)
    observed_time = signal_time + timedelta(minutes=5)
    records = [
        {
            **common,
            "event_type": "RUN_START",
            "study_partition": "TRAIN",
            "system_start_et": "2025-07-01",
            "study_start_et": "2026-06-30",
            "study_end_et": "2026-06-30",
            "expected_sessions": 1,
            "candidate_ids": "F007,F008,F009,F010,F011,F012",
            "strategy_ids": "S01,S02,S03",
            "definition_hash": "0c73ae4ef39fda9aa472d59d2cf53cfebf7872595618319fb55bb557f4e4d562",
            "parameter_attempt": 3 if compat else 2,
            "entry_rule": "NEXT_5M_BAR_OPEN_RECONSTRUCTED_AT_BAR_END",
            "entry_time_contract": "SIGNAL_BAR_END_EQUALS_ENTRY_BAR_START;OBSERVED_AT_ENTRY_BAR_END",
            "final_bar_contract": "NEXT_SESSION_SELECT3_BY_EXPLICIT_BAR_ID",
            "adjustment_contract": "LOCKED_OPEND_REHAB_V1",
            "fixture": True,
        }
    ]
    records.extend(
        {
            **common,
            "event_type": "TEST_REGISTRY",
            "test_id": test_id,
            "family": test_id,
            "layer": layer,
            "family_size": size,
            "adjustment": "MAX_T_PLUS_HOLM",
            "cluster_unit": "TRADING_DAY",
            "registered_before_train": True,
        }
        for test_id, layer, size in REGISTRY
    )
    context = {
        "time_bucket": "09:35-10:30",
        "preopen_regime": "BULL",
        "prior_day_context": "NORMAL|UP|HIGH",
        "dynamic_regime": "BULL",
        "vol_regime": "NORMAL",
        "day_position": "HIGH",
        "gap_regime": "GAP_UP",
    }
    for candidate_id, direction, event_unit, signal_id in (
        ("F012", "NORMAL", "FIVE_MINUTE_STATE", "BASE"),
        ("F011", "LONG", "OPENING_EVENT", "CANDIDATE"),
    ):
        records.append(
            {
                **common,
                **context,
                "event_type": "SIGNAL_EVENT",
                "signal_id": signal_id,
                "candidate_id": candidate_id,
                "direction": direction,
                "event_unit": event_unit,
                "signal_time_et": signal_time.isoformat(),
                "signal_price": 100.0,
                "r15": 0.001,
                "r30": 0.002,
                "r60": 0.003,
            }
        )
    records.append(
        {
            **common,
            **context,
            "event_type": "STRATEGY_SIGNAL_EVENT",
            "signal_id": "EXECUTABLE",
            "strategy_id": "S02",
            "source_id": "F011",
            "direction": "LONG",
            "signal_time_et": signal_time.isoformat(),
            "signal_price": 100.0,
            "factor_filters": "101010",
        }
    )
    entry_time = observed_time if bad_entry_label else signal_time
    records.append(
        {
            **common,
            **context,
            "event_type": "TRADE_EVENT",
            "trade_id": "TRADE",
            "signal_id": "EXECUTABLE",
            "strategy_id": "S02",
            "direction": "LONG",
            "trade_date_et": "2026-06-30",
            "signal_time_et": signal_time.isoformat(),
            "entry_time_et": entry_time.isoformat(),
            "entry_time_utc": signal_time.astimezone(timezone.utc).isoformat(),
            "entry_observed_at_et": observed_time.isoformat(),
            "entry_observed_at_utc": observed_time.astimezone(timezone.utc).isoformat(),
            "entry_bar_end_et": observed_time.isoformat(),
            "entry_price": 100.0,
            "exit_time_et": (observed_time + timedelta(minutes=5)).isoformat(),
            "exit_bar_end_et": (observed_time + timedelta(minutes=5)).isoformat(),
            "exit_time_precision": "BAR_INTERVAL",
            "exit_price": 99.0,
            "stop": 99.0,
            "target": 101.5,
            "initial_risk": 1.0,
            "reward_to_risk": 1.5,
            "gross_return": -0.01,
            "cost_bps_per_side": 2.0,
            "net_return": -0.0104,
            "net_return_cost_1bp": -0.0102,
            "net_return_cost_3bp": -0.0106,
            "mfe": 0.003,
            "mae": 0.01,
            "exit_reason": "STOP",
            "ambiguous": False,
            "primary_path": "OBSERVED_SINGLE_HIT",
            "target_first_net_return": -0.0104,
            "factor_filters": "101010",
        }
    )
    records.extend(
        (
            {
                **common,
                "event_type": "DAY_END",
                "session_date_et": "2026-06-30",
                "status": "COMPLETE",
                "signal_count": 2,
                "strategy_signal_count": 1,
                "trade_count": 1,
                "rejected_entry_count": 0,
                "pending_labels": 0,
                "pending_entries": 0,
                "active_trades": 0,
                "error_count": 0,
            },
            {
                **common,
                "event_type": "RUN_END",
                "status": "COMPLETE",
                "completed_days": 1,
                "expected_sessions": 1,
                "signal_count": 2,
                "strategy_signal_count": 1,
                "trade_count": 1,
                "rejected_entry_count": 0,
                "final_bars_injected": 0,
                "basis_adjustments_applied": 0,
                "error_count": 0,
            },
        )
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("time", "message"))
        for index, record in enumerate(records):
            writer.writerow(
                (
                    index,
                    ("FUTU_FACTOR_STRATEGY_V3_1_1|" if compat else "FUTU_FACTOR_STRATEGY_V3_1|")
                    + json.dumps(record, separators=(",", ":")),
                )
            )
    return path


def test_v31_hash_copyability_and_frozen_v3_is_untouched():
    source = STRATEGY.read_text(encoding="utf-8")
    frozen = STRATEGY.with_name("SPY_C1_STRATEGY_BATCH_TRAIN_V3.py").read_text(
        encoding="utf-8"
    )
    assert canonical_strategy_hash(STRATEGY) in source
    assert "FUTU_FACTOR_STRATEGY_V3_1|" in source
    assert "NEXT_SESSION_SELECT3_BY_EXPLICIT_BAR_ID" in source
    assert 'abs(previous_bar["close"] - self.day_bars[-1]["close"])' not in source
    assert "FUTU_FACTOR_STRATEGY_V3_1|" not in frozen
    for forbidden in ("place_order", "buy(", "sell(", "get_position", "account_", "bar_volume", "vwap"):
        assert forbidden not in source.lower()


def test_next_bar_open_uses_bar_start_time_and_recomputes_s01_r():
    strategy = _strategy()
    strategy.current_day = 20260630
    strategy.pending_entries = [
        {
            "trade_id": "T",
            "strategy_id": "S01",
            "signal_id": "S",
            "direction": "LONG",
            "signal_time_et": "2026-06-30T10:00:00",
            "day_number": 20260630,
            "signal_minute": 600,
            "signal_price": 100.0,
            "stop": 99.0,
            "target": 101.5,
            "max_bars": 6,
        }
    ]
    strategy.activate_entries(
        {"open": 100.5, "high": 101.0, "low": 100.4, "close": 100.8},
        605,
        "2026-06-30T10:00:00",
        "2026-06-30T14:00:00Z",
        "2026-06-30T10:05:00",
        "2026-06-30T14:05:00Z",
    )
    row = strategy.active_trades[0]
    assert row["entry_time_et"] == row["signal_time_et"]
    assert row["entry_observed_at_et"] == "2026-06-30T10:05:00"
    assert row["target"] == pytest.approx(102.75)
    assert row["reward_to_risk"] == pytest.approx(1.5)


def test_entry_crossed_stop_is_rejected_and_gap_stop_fills_at_open():
    strategy = _strategy()
    strategy.current_day = 20260630
    strategy.current_day_text = "2026-06-30"
    emitted = []
    strategy.emit = lambda event_type, fields: emitted.append((event_type, fields))
    strategy.pending_entries = [
        {
            "trade_id": "T",
            "strategy_id": "S01",
            "signal_id": "S",
            "direction": "LONG",
            "signal_time_et": "2026-06-30T10:00:00",
            "day_number": 20260630,
            "signal_minute": 600,
            "signal_price": 100.0,
            "stop": 99.0,
            "target": 101.5,
            "max_bars": 6,
        }
    ]
    strategy.activate_entries(
        {"open": 98.0, "high": 98.5, "low": 97.5, "close": 98.2},
        605,
        "2026-06-30T10:00:00",
        "2026-06-30T14:00:00Z",
        "2026-06-30T10:05:00",
        "2026-06-30T14:05:00Z",
    )
    assert not strategy.active_trades
    assert emitted[0][0] == "ENTRY_REJECTED"
    assert emitted[0][1]["reason"] == "STOP_CROSSED_BEFORE_ENTRY"

    strategy.active_trades = [
        {
            "trade_id": "G",
            "strategy_id": "S01",
            "signal_id": "GS",
            "direction": "LONG",
            "entry_price": 100.0,
            "stop": 99.0,
            "target": 101.5,
            "max_bars": 6,
            "bars_held": 0,
            "mfe": 0.0,
            "mae": 0.0,
        }
    ]
    strategy.resolve_trades(
        {"open": 98.5, "high": 99.2, "low": 98.0, "close": 98.8},
        "2026-06-30T10:10:00",
        "2026-06-30T14:10:00Z",
    )
    trade = [item for event, item in emitted if event == "TRADE_EVENT"][0]
    assert trade["exit_reason"] == "GAP_STOP"
    assert trade["exit_price"] == pytest.approx(98.5)


def test_explicit_final_bar_identity_adds_equal_close_once():
    strategy = _strategy()
    bar = {
        "open": 655.0,
        "high": 655.4,
        "low": 654.8,
        "close": 655.24,
        "tr": 0.6,
        "minute": 955,
        "session_date_et": "2026-04-01",
    }
    strategy.current_day = 20260401
    strategy.current_day_text = "2026-04-01"
    strategy.bars = [bar]
    strategy.day_bars = [bar]
    strategy.ema20 = bar["close"]
    strategy.ema50 = bar["close"]
    strategy.ema20_history = [bar["close"]] * 4
    strategy.start_day(
        20260402,
        "2026-04-02",
        {"open": 655.24, "high": 655.3, "low": 655.1, "close": 655.24},
    )
    assert strategy.final_bars_injected == 1
    assert strategy.bars[-1]["minute"] == 960
    assert len(strategy.bars) == 2


def test_opend_evidence_covers_bar_identity_half_days_and_rehab():
    with (AUDIT / "audit_summary.json").open(encoding="utf-8") as handle:
        summary = json.load(handle)
    assert summary["metrics"]["opend_coverage"]["bars"] == 19470
    assert summary["metrics"]["select_identity"]["select2_current_0935_mismatch_gt_1e_8"] == 0
    assert summary["metrics"]["select_identity"]["select3_prior_session_final_mismatch_gt_1e_8"] == 0
    assert [item["ex_div_date"] for item in summary["rehab_events"]] == [
        "2025-09-19",
        "2025-12-19",
        "2026-03-20",
        "2026-06-18",
    ]
    with (AUDIT / "opend_5m_ohlc.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_day = {}
    for row in rows:
        by_day.setdefault(row["time_key"][:10], []).append(row)
    assert len(by_day["2025-07-03"]) == 42
    assert len(by_day["2025-11-28"]) == 42
    assert len(by_day["2025-12-24"]) == 42
    assert by_day["2026-04-01"][-1]["close"] == by_day["2026-04-01"][-2]["close"]


@pytest.mark.parametrize(
    "strategy_path", [STRATEGY, COMPAT_STRATEGY], ids=("v3.1", "v3.1.1")
)
def test_opend_replay_injects_each_final_bar_once_and_matches_independent_indicators(
    strategy_path: Path,
):
    with (AUDIT / "opend_5m_ohlc.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    with (AUDIT / "opend_rehab.csv").open(newline="", encoding="utf-8") as handle:
        adjustments = {
            row["ex_div_date"]: float(row["forward_adj_factor_a"])
            for row in csv.DictReader(handle)
        }
    by_day: dict[str, list[dict]] = {}
    for source in rows:
        day = source["time_key"][:10]
        by_day.setdefault(day, []).append(
            {
                "time_key": source["time_key"],
                **{field: float(source[field]) for field in ("open", "high", "low", "close")},
            }
        )

    def future_product(day: str) -> float:
        product = 1.0
        for ex_date, factor in adjustments.items():
            if ex_date > day:
                product *= factor
        return product

    strategy = _strategy(strategy_path)
    reference_ema20 = None
    reference_ema50 = None
    reference_bars = []
    processed_identities = []
    prior_day = None
    for day, day_rows in by_day.items():
        basis = future_product(day)
        previous_bar = (
            {
                field: by_day[prior_day][-1][field] / basis
                for field in ("open", "high", "low", "close")
            }
            if prior_day is not None
            else {field: day_rows[0][field] / basis for field in ("open", "high", "low", "close")}
        )
        strategy.start_day(int(day.replace("-", "")), day, previous_bar)
        if prior_day is not None:
            prior_final = by_day[prior_day][-1]
            previous_close = reference_bars[-1]["close"] if reference_bars else prior_final["close"]
            reference_bars.append(
                {
                    **prior_final,
                    "tr": max(
                        prior_final["high"] - prior_final["low"],
                        abs(prior_final["high"] - previous_close),
                        abs(prior_final["low"] - previous_close),
                    ),
                }
            )
            reference_ema20 = (
                prior_final["close"]
                if reference_ema20 is None
                else (2.0 / 21.0) * prior_final["close"] + (19.0 / 21.0) * reference_ema20
            )
            reference_ema50 = (
                prior_final["close"]
                if reference_ema50 is None
                else (2.0 / 51.0) * prior_final["close"] + (49.0 / 51.0) * reference_ema50
            )
            processed_identities.append(prior_final["time_key"])
        for source in day_rows[:-1]:
            hour = int(source["time_key"][11:13])
            minute = int(source["time_key"][14:16])
            dynamic_bar = {
                field: source[field] / basis for field in ("open", "high", "low", "close")
            }
            dynamic_bar.update({"minute": hour * 60 + minute, "session_date_et": day})
            strategy.update_indicators(dynamic_bar)
            strategy.day_bars.append(dynamic_bar)

            previous_close = reference_bars[-1]["close"] if reference_bars else source["close"]
            reference_bars.append(
                {
                    **source,
                    "tr": max(
                        source["high"] - source["low"],
                        abs(source["high"] - previous_close),
                        abs(source["low"] - previous_close),
                    ),
                }
            )
            reference_ema20 = (
                source["close"]
                if reference_ema20 is None
                else (2.0 / 21.0) * source["close"] + (19.0 / 21.0) * reference_ema20
            )
            reference_ema50 = (
                source["close"]
                if reference_ema50 is None
                else (2.0 / 51.0) * source["close"] + (49.0 / 51.0) * reference_ema50
            )
            processed_identities.append(source["time_key"])
            assert strategy.ema20 * basis == pytest.approx(reference_ema20, abs=1e-9)
            assert strategy.ema50 * basis == pytest.approx(reference_ema50, abs=1e-9)
            if len(reference_bars) >= 14:
                reference_atr14 = sum(item["tr"] for item in reference_bars[-14:]) / 14.0
                assert strategy.atr(14) * basis == pytest.approx(reference_atr14, abs=1e-9)
        prior_day = day

    assert len(processed_identities) == len(rows) - 1
    assert len(processed_identities) == len(set(processed_identities))
    assert strategy.final_bars_injected == len(by_day) - 1
    assert strategy.basis_adjustments_applied == len(adjustments)


def test_inference_executes_all_114_tests_and_records_insufficiency():
    signals = []
    trades = []
    for day_index in range(45):
        day = f"2026-01-{day_index % 28 + 1:02d}"
        for minute in range(65):
            signals.append(
                {
                    "candidate_id": "F012",
                    "direction": "NORMAL",
                    "signal_time_et": f"{day}T10:{minute % 60:02d}:00",
                    "r15": 0.001,
                    "r30": 0.002,
                    "r60": 0.003,
                }
            )
        for candidate in ("F007", "F008", "F009", "F010", "F011"):
            for direction in ("LONG", "SHORT"):
                signals.append(
                    {
                        "candidate_id": candidate,
                        "direction": direction,
                        "signal_time_et": f"{day}T11:00:00",
                        "r15": 0.002,
                        "r30": 0.003,
                        "r60": 0.004,
                    }
                )
        for strategy_id in ("S01", "S02", "S03"):
            for direction in ("LONG", "SHORT"):
                trades.append(
                    {
                        "strategy_id": strategy_id,
                        "direction": direction,
                        "trade_date_et": day,
                        "net_return": 0.001 if direction == "LONG" else -0.0002,
                        "preopen_regime": "BULL" if direction == "LONG" else "BEAR",
                        "vol_regime": "NORMAL",
                        "gap_regime": "GAP_UP" if direction == "LONG" else "GAP_DOWN",
                        "time_bucket": "09:35-10:30",
                        "factor_filters": "101010",
                    }
                )
    result = compute_strategy_inference(
        signals, trades, bootstrap_replicates=100, seed_key="fixed"
    )
    assert len(result["results"]) == 114
    assert {row["actual_tests"] for row in result["families"]} == {30, 6, 12, 24, 36}
    assert all(row["adjustment"] == "MAX_T_PLUS_HOLM" for row in result["families"])
    assert any(row["status"] == "INSUFFICIENT_SAMPLE" for row in result["results"])
    estimated = [row for row in result["results"] if row["status"] == "ESTIMATED"]
    assert estimated
    assert all("holm_p_value" in row and "simultaneous_ci_low" in row for row in estimated)


def test_v31_import_is_atomic_visible_and_rejects_wrong_entry_label(tmp_path):
    db = Database(tmp_path / "factor.sqlite3")
    db.initialize()
    good = _write_fixture(tmp_path / "RunLog_V31.csv")
    importer = Importer(db, allow_fixtures=True)
    first = importer.import_file(good)
    second = importer.import_file(good)
    assert first["status"] == "VALIDATED"
    assert second["status"] == "DUPLICATE"
    research = db.dashboard_snapshot()["strategy_research"]
    assert research["batches"][0]["strategy_version"] == "FUTU_C1_STRATEGY_BATCH_TRAIN_V3_1"
    assert len(research["inference_results"]) == 114
    assert len(research["inference_families"]) == 6

    bad = _write_fixture(tmp_path / "RunLog_V31_BAD.csv", bad_entry_label=True)
    parsed = parse_runlog(bad, allow_fixtures=True)
    assert parsed.run is None
    assert "NEXT_BAR_ENTRY_V3_1_CONTRACT_FAILED" in parsed.error


def test_v311_import_is_atomic_visible_and_keeps_v31_compatible(tmp_path):
    db = Database(tmp_path / "factor.sqlite3")
    db.initialize()
    importer = Importer(db, allow_fixtures=True)

    v31 = importer.import_file(_write_fixture(tmp_path / "RunLog_V31.csv"))
    v311 = importer.import_file(
        _write_fixture(
            tmp_path / "RunLog_V311.csv", strategy_path=COMPAT_STRATEGY
        )
    )
    duplicate = importer.import_file(tmp_path / "RunLog_V311.csv")

    assert v31["status"] == "VALIDATED"
    assert v311["status"] == "VALIDATED"
    assert duplicate["status"] == "DUPLICATE"
    research = db.dashboard_snapshot()["strategy_research"]
    assert research["batches"][0]["strategy_version"] == (
        "FUTU_C1_STRATEGY_BATCH_TRAIN_V3_1_1"
    )
    assert len(research["inference_results"]) == 114
    assert len(research["inference_families"]) == 6


def test_dashboard_waiting_state_points_to_v311_and_futu_code_check(tmp_path):
    db = Database(tmp_path / "factor.sqlite3")
    db.initialize()
    snapshot = db.dashboard_snapshot()
    assert "V3.1.1" in snapshot["strategy_research"]["warning"]
    assert "SPY_C1_STRATEGY_BATCH_TRAIN_V3_1_1.py" in snapshot["summary"]["next_action"]
    assert "先通过富途代码检查" in snapshot["summary"]["next_action"]
