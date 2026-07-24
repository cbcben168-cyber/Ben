from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _readable_routing_section() -> str:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    start = "### Readable Routing Rules"
    end = "### Preserved Legacy Routing Block"
    return text.split(start, 1)[1].split(end, 1)[0]


def test_agents_routes_quant_research_to_pipeline():
    section = _readable_routing_section()
    for token in (
        "quant-research-pipeline",
        "optimization_allowed=false",
        "fill_timing=next_bar",
        "Buy and Hold",
        "validated local cache",
        "yfinance",
        "SMOKE_TEST_DATA_ONLY",
        "STRATEGY_CAPABILITY_BLOCKER",
        "DATA_CAPABILITY_BLOCKER",
        "quant-backtest-audit",
        "accounts, brokers, orders, TradingView Webhook, options, and Phase 2",
    ):
        assert token in section


def test_pipeline_skill_points_back_to_agents_entry():
    text = (ROOT / ".agents" / "skills" / "quant-research-pipeline" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "AGENTS.md" in text
    assert "Quant Research Pipeline Entry" in text
