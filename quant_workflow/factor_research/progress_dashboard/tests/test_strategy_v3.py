from datetime import datetime, timedelta, timezone
from pathlib import Path
import csv
import json

import pytest

from quant_workflow.factor_research.progress_dashboard.db import Database, canonical_strategy_hash
from quant_workflow.factor_research.progress_dashboard.ingest import Importer, parse_runlog
from quant_workflow.factor_research.progress_dashboard.presentation import import_error_zh
from quant_workflow.factor_research.progress_dashboard.stats import compute_strategy_metrics


ROOT = Path(__file__).resolve().parents[4]
STRATEGY = ROOT / "factor_research" / "spy_factor_batch_v1" / "SPY_C1_STRATEGY_BATCH_TRAIN_V3.py"
TESTS = (
    ("CANDIDATE_SCREEN", "CANDIDATE", 30),
    ("STRATEGY_BASELINE", "L1", 6),
    ("REGIME_INCREMENT", "L2_REGIME", 12),
    ("TIME_INCREMENT", "L2_TIME", 18),
    ("REGIME_TIME_INTERACTION", "L3", 6),
    ("F001_F006_FILTER_INCREMENT", "L4", 36),
)


def _write_fixture(path: Path, *, break_entry: bool = False, drop_end: bool = False) -> Path:
    et = timezone(timedelta(hours=-4))
    signal_time = datetime(2026, 6, 30, 10, 0, tzinfo=et)
    entry_time = signal_time + timedelta(minutes=10 if break_entry else 5)
    common = {
        "contract_version": "3.0", "batch_id": "TEST_STRATEGY_V3",
        "run_id": "TEST_STRATEGY_V3", "strategy_version": "FUTU_C1_STRATEGY_BATCH_TRAIN_V3",
        "strategy_hash": canonical_strategy_hash(STRATEGY),
        "parameter_version": "C1-STRATEGY-FIRST-TRAIN-V3", "symbol": "US.SPY",
        "timeframe": "5m", "bar_type": "K_5M", "select": 2, "session": "RTH",
        "timezone": "America/New_York",
    }
    records = [{
        **common, "event_type": "RUN_START", "study_partition": "TRAIN",
        "system_start_et": "2025-07-01", "study_start_et": "2026-06-30",
        "study_end_et": "2026-06-30", "expected_sessions": 1,
        "candidate_ids": "F007,F008,F009,F010,F011,F012",
        "strategy_ids": "S01,S02,S03",
        "definition_hash": "c7a45d9da3ccfb0cc11c65e0f9edee005837d650e741dc894970982c12a73ec5",
        "parameter_attempt": 1,
        "fixture": True,
    }]
    records.extend({
        **common, "event_type": "TEST_REGISTRY", "test_id": test_id,
        "family": test_id, "layer": layer, "family_size": family_size,
        "adjustment": "MAX_T_PLUS_HOLM", "cluster_unit": "TRADING_DAY",
    } for test_id, layer, family_size in TESTS)
    signal = {
        **common, "event_type": "SIGNAL_EVENT", "signal_id": "20260630_1000_F011_LONG",
        "candidate_id": "F011", "direction": "LONG", "event_unit": "OPENING_EVENT",
        "signal_time_et": signal_time.isoformat(), "signal_time_utc": signal_time.astimezone(timezone.utc).isoformat(),
        "signal_price": 100.0, "time_bucket": "09:35-10:30", "preopen_regime": "BULL",
        "prior_day_context": "NORMAL|UP|HIGH", "dynamic_regime": "BULL",
        "vol_regime": "NORMAL", "day_position": "HIGH", "r15": 0.001,
        "r30": 0.002, "r60": 0.003,
    }
    trade = {
        **common, "event_type": "TRADE_EVENT", "trade_id": "S02_TEST_LONG",
        "signal_id": signal["signal_id"], "strategy_id": "S02", "direction": "LONG",
        "trade_date_et": "2026-06-30", "signal_time_et": signal_time.isoformat(),
        "entry_time_et": entry_time.isoformat(), "exit_time_et": (entry_time + timedelta(minutes=5)).isoformat(),
        "entry_price": 100.0, "exit_price": 99.0, "stop": 99.0, "target": 101.5,
        "gross_return": -0.01, "cost_bps_per_side": 2.0, "net_return": -0.0104,
        "net_return_cost_1bp": -0.0102, "net_return_cost_3bp": -0.0106,
        "mfe": 0.015, "mae": 0.01, "exit_reason": "STOP", "ambiguous": True,
        "primary_path": "STOP_FIRST", "target_first_net_return": 0.0146,
        "time_bucket": "09:35-10:30", "factor_filters": "101010",
    }
    records.extend((signal, trade, {
        **common, "event_type": "DAY_END", "session_date_et": "2026-06-30",
        "status": "COMPLETE", "signal_count": 1, "trade_count": 1,
        "pending_labels": 0, "pending_entries": 0, "active_trades": 0, "error_count": 0,
    }))
    if not drop_end:
        records.append({
            **common, "event_type": "RUN_END", "status": "COMPLETE",
            "completed_days": 1, "expected_sessions": 1, "signal_count": 1,
            "trade_count": 1, "error_count": 0,
        })
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("time", "message"))
        for index, record in enumerate(records):
            writer.writerow((index, "FUTU_FACTOR_STRATEGY_V3|" + json.dumps(record, separators=(",", ":"))))
    return path


def test_strategy_v3_source_is_copyable_and_contains_no_execution_or_volume_api():
    source = STRATEGY.read_text(encoding="utf-8")
    assert "class Strategy(StrategyBase)" in source
    assert "def handle_data(self)" in source
    assert canonical_strategy_hash(STRATEGY) in source
    for forbidden in ("place_order", "buy(", "sell(", "get_position", "account_", "bar_volume", "vwap"):
        assert forbidden not in source.lower()
    assert "NEXT_5M_BAR_OPEN" in source
    assert "2025-11-28,2025-12-24" in source


def test_strategy_v3_time_buckets_and_half_day_cutoffs_are_frozen():
    namespace = {"StrategyBase": object}
    exec(compile(STRATEGY.read_text(encoding="utf-8"), str(STRATEGY), "exec"), namespace)
    strategy = namespace["Strategy"]()
    strategy.early_close_days = {20251128: True, 20251224: True}
    assert strategy.time_bucket(575) == "09:35-10:30"
    assert strategy.time_bucket(630) == "10:30-12:00"
    assert strategy.time_bucket(840) == "14:00-15:55"
    assert strategy.latest_signal_minute("S01", 20251128) == 740
    assert strategy.latest_signal_minute("S02", 20251128) == 710
    assert strategy.latest_signal_minute("S03", 20251001) == 920


def test_strategy_v3_same_bar_stop_target_uses_stop_first_and_keeps_sensitivity():
    namespace = {"StrategyBase": object}
    exec(compile(STRATEGY.read_text(encoding="utf-8"), str(STRATEGY), "exec"), namespace)
    strategy = namespace["Strategy"]()
    strategy.current_day_text = "2026-06-30"
    strategy.day_trades = 0
    strategy.total_trades = 0
    strategy.active_trades = [{
        "trade_id": "T", "strategy_id": "S02", "signal_id": "S", "direction": "LONG",
        "signal_time_et": "2026-06-30T10:00:00-04:00", "entry_time_et": "2026-06-30T10:05:00-04:00",
        "entry_time_utc": "2026-06-30T14:05:00Z", "entry_price": 100.0,
        "stop": 99.0, "target": 101.5, "max_bars": 12, "bars_held": 0,
        "mfe": 0.0, "mae": 0.0,
    }]
    emitted = []
    strategy.emit = lambda event_type, fields: emitted.append((event_type, fields))
    strategy.resolve_trades(
        {"open": 100.0, "high": 102.0, "low": 98.0, "close": 100.5},
        "2026-06-30T10:10:00-04:00", "2026-06-30T14:10:00Z",
    )
    event_type, row = emitted[0]
    assert event_type == "TRADE_EVENT"
    assert row["ambiguous"] is True
    assert row["primary_path"] == "STOP_FIRST"
    assert row["exit_price"] == pytest.approx(99.0)
    assert row["net_return"] == pytest.approx(-0.0104)
    assert row["target_first_net_return"] == pytest.approx(0.0146)
    assert row["mfe"] == pytest.approx(0.02)
    assert row["mae"] == pytest.approx(0.02)


def test_strategy_metrics_include_cost_path_risk_pf_drawdown_and_cluster_ci():
    trades = [
        {"strategy_id": "S01", "direction": "LONG", "trade_date_et": "2026-01-02", "entry_time_et": "x", "net_return": 0.01, "mfe": 0.02, "mae": 0.003, "ambiguous": False, "exit_reason": "TARGET"},
        {"strategy_id": "S01", "direction": "LONG", "trade_date_et": "2026-01-05", "entry_time_et": "y", "net_return": -0.004, "mfe": 0.002, "mae": 0.006, "ambiguous": True, "exit_reason": "STOP"},
    ]
    row = compute_strategy_metrics(trades, bootstrap_replicates=200, seed_key="fixed")[0]
    assert row["net_mean"] == pytest.approx(0.003)
    assert row["profit_factor"] == pytest.approx(2.5)
    assert row["max_drawdown"] == pytest.approx(0.004)
    assert row["mfe_mean"] == pytest.approx(0.011)
    assert row["mae_mean"] == pytest.approx(0.0045)
    assert row["ambiguous_count"] == 1
    assert row["path_uncertain_exit_count"] == 2
    assert row["same_bar_ambiguous_count"] == 1
    assert row["mfe_mae_scope"] == "FULL_EXIT_BAR_RANGE_UPPER_BOUND"
    assert row["mfe_mae_path_status"] == "EXIT_BAR_SEQUENCE_UNKNOWN"
    assert row["cluster_ci_low"] is not None and row["cluster_ci_high"] is not None


def test_strategy_v3_import_is_atomic_deduplicated_and_visible(tmp_path):
    db = Database(tmp_path / "factor.sqlite3")
    db.initialize()
    path = _write_fixture(tmp_path / "RunLog_TEST_STRATEGY_V3.csv")
    importer = Importer(db, allow_fixtures=True)
    first = importer.import_file(path)
    second = importer.import_file(path)
    assert first["status"] == "VALIDATED"
    assert second["status"] == "DUPLICATE"
    snapshot = db.dashboard_snapshot()
    research = snapshot["strategy_research"]
    assert research["status"] == "VALIDATED"
    assert research["metrics"][0]["strategy_id"] == "S02"
    assert research["metrics"][0]["ambiguous_count"] == 1
    assert [row["horizon_minutes"] for row in research["candidate_metrics"]] == [15, 30, 60]
    assert {row["candidate_id"] for row in research["candidate_metrics"]} == {"F011"}
    assert research["event_units"] == [{"event_unit": "OPENING_EVENT", "signal_count": 1, "trading_days": 1}]
    assert len(research["tests"]) == 6
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM strategy_batches").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM strategy_trades").fetchone()[0] == 1


@pytest.mark.parametrize("break_entry,drop_end,error", [
    (True, False, "NEXT_BAR_ENTRY_CONTRACT_FAILED"),
    (False, True, "STRATEGY_V3_BOUNDARY_COUNT"),
])
def test_strategy_v3_rejects_bad_chronology_or_partial_batch(tmp_path, break_entry, drop_end, error):
    db = Database(tmp_path / "factor.sqlite3")
    db.initialize()
    path = _write_fixture(tmp_path / "RunLog_BAD.csv", break_entry=break_entry, drop_end=drop_end)
    parsed = parse_runlog(path, allow_fixtures=True)
    assert parsed.run is None
    assert error in parsed.error
    result = Importer(db, allow_fixtures=True).import_file(path)
    assert result["status"] in {"INVALID", "PARSE_FAILED"}
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM strategy_batches").fetchone()[0] == 0


def test_strategy_v3_import_error_has_chinese_guidance():
    info = import_error_zh("NEXT_BAR_ENTRY_CONTRACT_FAILED")
    assert "整批拒绝" in info["message_zh"]
    assert "保留原始 CSV" in info["next_action_zh"]


def test_dashboard_template_separates_strategy_research_from_factor_ranking():
    template = Path(__file__).resolve().parents[1] / "templates" / "index.html"
    content = template.read_text(encoding="utf-8")
    assert "C1 Strategy-First V3" in content
    assert "不同事件单位不可直接排行" in content or "事件单位分开显示" in content
    assert "TRAIN 不等于 Edge" in content
    assert "范围型 MFE / MAE" in content
    assert "固定机会集描述；未重演持仓释放" in content
