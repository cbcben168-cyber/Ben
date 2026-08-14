from pathlib import Path
import json

from streamlit.testing.v1 import AppTest

from tv_quant.pattern_finder.universe_foundation import ProfileRegistry, core_v1


ROOT = Path(__file__).resolve().parents[2]


def _visible_text(app: AppTest) -> str:
    element_types = (
        "title",
        "header",
        "subheader",
        "caption",
        "markdown",
        "info",
        "success",
        "warning",
        "error",
    )
    return "\n".join(
        str(element.value)
        for element_type in element_types
        for element in app.get(element_type)
    )


def _registry_containing_only_draft_core_v1(tmp_path) -> ProfileRegistry:
    registry = ProfileRegistry(tmp_path)
    registry.bootstrap(core_v1())
    published_path = tmp_path / "published.jsonl"
    payload = json.loads(published_path.read_text(encoding="utf-8"))
    payload["record_state"] = "DRAFT"
    published_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return registry


def test_universe_settings_renders_initialized_core_profile_only(tmp_path) -> None:
    registry = ProfileRegistry(tmp_path)
    registry.bootstrap(core_v1())
    app = AppTest.from_file(ROOT / "app/pages/3_Universe_Settings.py")
    app.session_state["universe_profile_registry"] = registry
    app.run()

    visible = _visible_text(app)

    assert not app.exception
    assert app.title[0].value == "股票池设置"
    for expected in (
        "CORE:v1",
        "CORE v1",
        "PUBLISHED",
        "Frozen default US common-stock universe.",
        "AMEX, NASDAQ, NYSE",
        "COMMON_STOCK",
        "FUTU_AVG_TURNOVER_20D",
        "FUTU_LISTED_DAYS",
        core_v1().content_sha256,
        core_v1().filter_content_sha256,
    ):
        assert expected in visible
    for forbidden in ("PASS", "FAIL", "UNKNOWN", "Quarantine", "member count"):
        assert forbidden not in visible


def test_universe_settings_surfaces_non_published_profile_failure(tmp_path) -> None:
    app = AppTest.from_file(ROOT / "app/pages/3_Universe_Settings.py")
    app.session_state["universe_profile_registry"] = _registry_containing_only_draft_core_v1(
        tmp_path
    )
    app.run()

    visible = _visible_text(app)

    assert not app.exception
    assert "no current published profile: CORE:v1" in visible
    for official_profile_content in (
        "当前正式版本",
        "CORE v1",
        "PUBLISHED",
        core_v1().content_sha256,
        core_v1().filter_content_sha256,
    ):
        assert official_profile_content not in visible
