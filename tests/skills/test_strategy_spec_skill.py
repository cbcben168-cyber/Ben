from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".agents" / "skills" / "quant-strategy-spec" / "SKILL.md"
REFERENCE = SKILL.parent / "references" / "input-output.md"


def test_skill_declares_non_execution_boundary():
    text = SKILL.read_text(encoding="utf-8")
    assert "YAML" in text
    assert "capability" in text.lower()
    assert "不下载数据" in text
    assert "不运行回测" in text
    assert "不发送订单" in text
    assert "references/config-schema.md" in text
    assert "references/capability-matrix.md" in text
    assert "validate_strategy_mapping" in text
    assert "load_strategy_spec" in text
    assert "check_capabilities" in text
    assert "阻断后必须停止所有下游数据访问、数据处理和回测工作" in text
    assert "严禁调用任何用户级 Skill（无论其是否 pinned、versioned、unpinned 或其他状态）" in text


def test_skill_references_ema_and_rsi_examples():
    text = REFERENCE.read_text(encoding="utf-8")
    assert "ema_crossover" in text
    assert "RSI" in text
    assert "STRATEGY_CAPABILITY_BLOCKER" in text
    assert "optimization_allowed: false" in text
    assert "validate_strategy_mapping" in text
    assert "load_strategy_spec" in text
    assert "check_capabilities" in text
