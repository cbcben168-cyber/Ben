from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[2]


def _load(relative_path: str) -> AppTest:
    return AppTest.from_file(ROOT / relative_path, default_timeout=10).run()


def _visible_text(app: AppTest) -> str:
    element_types = ("title", "header", "subheader", "caption", "markdown", "info")
    values: list[str] = []
    for element_type in element_types:
        values.extend(str(element.value) for element in app.get(element_type))
    return "\n".join(values)


def test_home_page_loads_as_fixture_only_shell() -> None:
    app = _load("app/Home.py")

    assert not app.exception
    assert app.title[0].value == "Pattern Finder"
    assert "local fixture" in _visible_text(app).lower()


def test_today_scan_page_loads_all_three_fixture_rows() -> None:
    app = _load("app/pages/1_Today_Scan.py")

    assert not app.exception
    assert app.title[0].value == "Today Scan"
    assert len(app.dataframe) == 1
    table = app.dataframe[0].value
    assert tuple(table["Symbol"]) == ("TEST_FLAT", "TEST_ROUNDED", "TEST_READY")
    assert tuple(table.columns) == (
        "Symbol",
        "Pattern",
        "Bars",
        "Base Start",
        "Base End",
        "Support",
        "Resistance",
    )


def test_chart_review_loads_chart_and_can_switch_fixture() -> None:
    app = _load("app/pages/2_Chart_Review.py")

    assert not app.exception
    assert app.title[0].value == "Chart Review"
    assert tuple(app.selectbox[0].options) == ("TEST_FLAT", "TEST_ROUNDED", "TEST_READY")
    assert len(app.get("plotly_chart")) == 1

    app.selectbox[0].select("TEST_READY").run()
    assert not app.exception
    assert app.selectbox[0].value == "TEST_READY"
    assert "Resistance: 105.50" in _visible_text(app)


def test_rendered_pages_do_not_expose_later_phase_fields() -> None:
    rendered = "\n".join(
        _visible_text(_load(path))
        for path in (
            "app/Home.py",
            "app/pages/1_Today_Scan.py",
            "app/pages/2_Chart_Review.py",
        )
    ).lower()

    for forbidden in (
        "human score",
        "rule score",
        "shape score",
        "outcome score",
        "future 5d",
        "future 10d",
        "future 20d",
        "machine learning",
        "ml score",
    ):
        assert forbidden not in rendered
