from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".agents" / "skills" / "quant-strategy-spec" / "SKILL.md"


def test_skill_declares_non_execution_boundary():
    text = SKILL.read_text(encoding="utf-8")
    assert "YAML" in text
    assert "capability" in text.lower()
    assert "不下载数据" in text
    assert "不运行回测" in text
    assert "不发送订单" in text
    assert "references/config-schema.md" in text
    assert "references/capability-matrix.md" in text


def test_skill_references_ema_and_rsi_examples():
    text = (SKILL.parent / "references" / "input-output.md").read_text(encoding="utf-8")
    assert "ema_crossover" in text
    assert "RSI" in text
    assert "STRATEGY_CAPABILITY_BLOCKER" in text
    assert "optimization_allowed: false" in text
