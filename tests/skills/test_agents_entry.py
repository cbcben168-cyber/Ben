from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_agents_routes_quant_research_to_pipeline():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "quant-research-pipeline" in text
    assert "optimization_allowed" in text
    assert "STRATEGY_CAPABILITY_BLOCKER" in text
    assert "Buy and Hold" in text
    assert "DATA_CAPABILITY_BLOCKER" in text
    assert "quant-backtest-audit" in text


def test_pipeline_skill_points_back_to_agents_entry():
    text = (ROOT / ".agents" / "skills" / "quant-research-pipeline" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "AGENTS.md" in text
    assert "Quant Research Pipeline Entry" in text
