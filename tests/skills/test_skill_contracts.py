from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / ".agents" / "skills"
EXPECTED = {
    "m3c-futu-quota-refresh",
    "m3c-model-routing",
    "m3c-runtime-recovery",
    "quant-strategy-spec",
    "quant-research-pipeline",
    "quant-backtest-audit",
}


def read_frontmatter(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---"
    closing = lines[1:].index("---") + 1
    result = yaml.safe_load("\n".join(lines[1:closing]))
    assert isinstance(result, dict)
    return result


def test_project_skills_are_discoverable_and_unique():
    paths = sorted(SKILL_ROOT.glob("*/SKILL.md"))
    assert {path.parent.name for path in paths} == EXPECTED
    frontmatters = [read_frontmatter(path) for path in paths]
    names = [item["name"] for item in frontmatters]
    assert names == sorted(EXPECTED)
    assert len(names) == len(set(names))
    assert all(item["description"].strip() for item in frontmatters)


def test_skill_documents_do_not_add_execution_or_global_dependencies():
    for path in sorted(SKILL_ROOT.glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8").lower()
        assert "submit_order" not in text
        assert "place_order" not in text
        assert "alphagbm" not in text
        assert "c:\\users\\" not in text
