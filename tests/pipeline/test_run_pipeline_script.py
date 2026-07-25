from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "quant" / "run_pipeline.ps1"


def test_script_has_required_switches_and_no_install_or_order_path():
    text = SCRIPT.read_text(encoding="utf-8")
    for token in ("$StrategyConfig", "$AuditOnly", "$SkipDataRefresh"):
        assert token in text
    assert "$Quick" not in text
    assert "--quick" not in text
    assert "pip install" not in text.lower()
    assert "submit_order" not in text.lower()
    assert "place_order" not in text.lower()
    assert "OpenQuoteContext" not in text
