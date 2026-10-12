from __future__ import annotations

import run_research


def _manifest(statistics_status: str, acceptance_status: str) -> dict:
    return {
        "acceptance_status": acceptance_status,
        "data_qualification": {"status": "PASS_5M_ONLY"},
        "engine_status": "ENGINE_PASS",
        "statistics_status": statistics_status,
        "trade_parity": {"status": "TRADE_PARITY_PASS"},
        "research_status": "RESEARCH_NO_EDGE" if acceptance_status == "ACCEPTANCE_PASS" else "RESEARCH_BLOCKED_BY_ACCEPTANCE_GATE",
        "registry": {"factor_count": 36},
        "timings": {"total_seconds": 1.0},
    }


def test_cli_returns_nonzero_when_statistics_gate_fails(monkeypatch, tmp_path):
    target = tmp_path / "phase3_train_v3"
    monkeypatch.setattr(run_research, "PHASE3_V3_OUTPUT", target)
    monkeypatch.setattr(
        run_research,
        "run_pipeline",
        lambda *args, **kwargs: _manifest("STATISTICS_FAIL", "ACCEPTANCE_FAIL"),
    )
    assert run_research.main(["--output-dir", str(target)]) == 2


def test_cli_returns_zero_only_for_full_acceptance(monkeypatch, tmp_path):
    target = tmp_path / "phase3_train_v3"
    monkeypatch.setattr(run_research, "PHASE3_V3_OUTPUT", target)
    monkeypatch.setattr(
        run_research,
        "run_pipeline",
        lambda *args, **kwargs: _manifest("STATISTICS_PASS", "ACCEPTANCE_PASS"),
    )
    assert run_research.main(["--output-dir", str(target)]) == 0


def test_cli_rejects_non_v3_output_path_before_pipeline(monkeypatch, tmp_path):
    target = tmp_path / "phase3_train_v3"
    called = False

    def runner(*args, **kwargs):
        nonlocal called
        called = True
        return _manifest("STATISTICS_PASS", "ACCEPTANCE_PASS")

    monkeypatch.setattr(run_research, "PHASE3_V3_OUTPUT", target)
    monkeypatch.setattr(run_research, "run_pipeline", runner)
    assert run_research.main(["--output-dir", str(tmp_path / "wrong")]) == 2
    assert called is False
