from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from tv_quant.pattern_finder.universe import PILOT_SYMBOLS


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
        "candidate scanner",
    ):
        assert forbidden not in rendered


def _write_cached_aapl(cache_root: Path) -> None:
    cache_root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(
                ["2026-08-05", "2026-08-06", "2026-08-07"], utc=True
            ),
            "ticker": ["AAPL"] * 3,
            "open": [201.0, 202.0, 203.0],
            "high": [203.0, 204.0, 205.0],
            "low": [200.0, 201.0, 202.0],
            "close": [202.0, 203.0, 204.0],
            "volume": [1_000_001, 1_000_002, 1_000_003],
        }
    ).to_csv(cache_root / "AAPL_daily.csv", index=False)


def test_today_scan_cache_mode_lists_pilot_and_requires_explicit_refresh(
    tmp_path: Path, monkeypatch
) -> None:
    cache_root = tmp_path / "qfq"
    _write_cached_aapl(cache_root)
    monkeypatch.setenv("PATTERN_FINDER_CACHE_ROOT", str(cache_root))
    app = _load("app/pages/1_Today_Scan.py")

    app.segmented_control[0].set_value("Cache / Futu").run()

    assert not app.exception
    table = app.dataframe[0].value
    assert tuple(table["Symbol"]) == PILOT_SYMBOLS
    assert table.loc[table["Symbol"] == "AAPL", "Cache"].iloc[0] == "Present"
    assert any(button.label == "Refresh pilot from Futu OpenD" for button in app.button)


def test_chart_review_cache_mode_renders_real_qfq_bars(
    tmp_path: Path, monkeypatch
) -> None:
    cache_root = tmp_path / "qfq"
    _write_cached_aapl(cache_root)
    monkeypatch.setenv("PATTERN_FINDER_CACHE_ROOT", str(cache_root))
    app = _load("app/pages/2_Chart_Review.py")

    app.segmented_control[0].set_value("Cache / Futu").run()

    assert not app.exception
    assert tuple(app.selectbox[0].options) == PILOT_SYMBOLS
    assert app.selectbox[0].value == "AAPL"
    assert len(app.get("plotly_chart")) == 1
    assert "Futu QFQ" in _visible_text(app)
