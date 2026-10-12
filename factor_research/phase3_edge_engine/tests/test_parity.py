from __future__ import annotations

from factor_research.phase3_edge_engine.parity import audit_trade_parity
from factor_research.phase3_edge_engine.pipeline import DEFAULT_DATA, DEFAULT_RUNLOG


def test_frozen_v311_runlog_matches_every_signal_decision_and_trade(phase3_state):
    summary, detail = audit_trade_parity(
        DEFAULT_RUNLOG,
        DEFAULT_DATA.with_name("opend_rehab.csv"),
        phase3_state["signals"],
        phase3_state["trades"],
        phase3_state["audit"],
    )
    assert summary["status"] == "TRADE_PARITY_PASS"
    assert summary["errors"] == []
    assert summary["matched_signals"] == 1_593
    assert summary["matched_trades"] == 1_072
    assert summary["matched_rejections"] == 521
    assert summary["ambiguous_reason_normalizations"] == 8
    assert summary["max_abs_differences"]["signal_price"] == 0
    assert max(
        summary["max_abs_differences"][field]
        for field in ("entry_price", "exit_price", "stop_price", "target_price")
    ) <= summary["price_abs_tolerance"]
    assert summary["max_abs_differences"]["net_return"] <= summary["return_abs_tolerance"]
    assert set(detail["status"]) == {"MATCH"}
    assert detail["canonical_signal_id"].is_unique


def test_parity_fails_closed_on_wrong_runlog_identity(tmp_path, phase3_state):
    wrong = tmp_path / "wrong.csv"
    wrong.write_text("not the frozen runlog\n", encoding="utf-8")
    summary, detail = audit_trade_parity(
        wrong,
        DEFAULT_DATA.with_name("opend_rehab.csv"),
        phase3_state["signals"],
        phase3_state["trades"],
        phase3_state["audit"],
    )
    assert summary["status"] == "PARITY_FAIL"
    assert summary["errors"][0].startswith("RUNLOG_HASH_MISMATCH:")
    assert detail.empty
