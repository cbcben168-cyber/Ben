from datetime import UTC, datetime
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd
from streamlit.testing.v1 import AppTest

from tv_quant.pattern_finder.review import SCAN_FILTERS
from tv_quant.pattern_finder.validation import (
    FlatBaseValidation,
    HUMAN_LABELS,
    append_validation,
    read_validation_history,
)
from tv_quant.pattern_finder.universe import PILOT_SYMBOLS


ROOT = Path(__file__).resolve().parents[2]


def _load(relative_path: str) -> AppTest:
    return AppTest.from_file(ROOT / relative_path, default_timeout=10).run()


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
        "Flat Base",
        "Base Length",
        "Base Depth",
        "Bottom Tests",
        "Normalized Slope",
        "Support",
        "Resistance",
    )
    assert tuple(table["Flat Base"]) == ("YES", "YES", "YES")
    assert table.loc[table["Symbol"] == "TEST_FLAT", "Bottom Tests"].iloc[0] >= 2


def test_chart_review_loads_chart_and_can_switch_fixture() -> None:
    app = _load("app/pages/2_Chart_Review.py")

    assert not app.exception
    assert app.title[0].value == "Chart Review"
    assert tuple(app.selectbox[0].options) == ("TEST_FLAT", "TEST_ROUNDED", "TEST_READY")
    assert len(app.get("plotly_chart")) == 1
    assert "Flat Base: YES" in _visible_text(app)
    assert "Bottom Tests:" in _visible_text(app)
    assert "Normalized Slope:" in _visible_text(app)
    assert "Resistance Spike Adjusted:" in _visible_text(app)

    app.selectbox[0].select("TEST_READY").run()
    assert not app.exception
    assert app.selectbox[0].value == "TEST_READY"
    assert "Detector Version: phase1-v1" in _visible_text(app)


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


def _write_cached_symbol(
    cache_root: Path,
    symbol: str,
    *,
    too_deep: bool = False,
) -> None:
    cache_root.mkdir(parents=True, exist_ok=True)
    days = [
        session.date().isoformat()
        for session in xcals.get_calendar("XNYS").sessions_in_range(
            "2026-01-02", "2026-08-07"
        )
    ]
    base_start = len(days) - 30
    rows: list[dict[str, object]] = []
    for index, day in enumerate(days):
        if index < base_start:
            close = 120.0 - 0.12 * index
            high = close + 1.0
            low = close - 1.0
        else:
            offset = index - base_start
            close = 101.0
            high = 102.0
            low = 101.0 - 0.1 * offset if offset < 5 else 100.5
            if offset in (5, 20):
                low = (
                    82.0 + 0.5 * (offset == 20)
                    if too_deep
                    else 99.0 + 0.5 * (offset == 20)
                )
        rows.append(
            {
                "timestamp_utc": pd.Timestamp(day, tz="UTC"),
                "ticker": symbol,
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1_000_000,
            }
        )
    pd.DataFrame(rows).to_csv(cache_root / f"{symbol}_daily.csv", index=False)


def _write_cached_aapl(cache_root: Path) -> None:
    _write_cached_symbol(cache_root, "AAPL")


def _write_review_history(path: Path) -> None:
    records = (
        FlatBaseValidation(
            datetime(2026, 8, 10, 4, 0, tzinfo=UTC),
            "AAPL",
            "phase1-v1",
            "2026-08-07",
            "YES",
            30,
            0.03,
            2,
            0.0,
            "像",
            (),
            "looks flat",
        ),
        FlatBaseValidation(
            datetime(2026, 8, 10, 4, 1, tzinfo=UTC),
            "MSFT",
            "phase1-v1",
            "2026-08-07",
            "NO",
            30,
            0.25,
            2,
            0.0,
            "不像",
            ("底部太深",),
            "too deep",
        ),
        FlatBaseValidation(
            datetime(2026, 8, 10, 4, 2, tzinfo=UTC),
            "JPM",
            "phase1-v1",
            "2026-08-07",
            "NO",
            30,
            0.25,
            2,
            0.0,
            "勉强像",
            ("宽幅震荡",),
            "borderline",
        ),
    )
    for record in records:
        append_validation(path, record)


def test_today_scan_cache_mode_filters_computer_and_human_states(
    tmp_path: Path, monkeypatch
) -> None:
    cache_root = tmp_path / "qfq"
    for symbol, too_deep in (
        ("AAPL", False),
        ("MSFT", True),
        ("JPM", True),
        ("XOM", False),
    ):
        _write_cached_symbol(cache_root, symbol, too_deep=too_deep)
    validation_path = tmp_path / "flat_base_validation.jsonl"
    _write_review_history(validation_path)
    monkeypatch.setenv("PATTERN_FINDER_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PATTERN_FINDER_VALIDATION_PATH", str(validation_path))
    app = _load("app/pages/1_Today_Scan.py")

    app.segmented_control[0].set_value("Cache / Futu").run()

    assert not app.exception
    assert tuple(app.selectbox[0].options) == SCAN_FILTERS
    table = app.dataframe[0].value
    assert tuple(table["Symbol"]) == ("AAPL", "MSFT", "JPM", "XOM")
    assert table.loc[table["Symbol"] == "AAPL", "Cache"].iloc[0] == "Present"
    assert table.loc[table["Symbol"] == "AAPL", "Human Label"].iloc[0] == "像"
    assert {"Base Length", "Detector Version", "Reason Tags"} <= set(table.columns)
    assert any(button.label == "Refresh pilot from Futu OpenD" for button in app.button)

    expected = {
        "Flat Base YES": ("AAPL", "XOM"),
        "Flat Base NO": ("MSFT", "JPM"),
        "未人工验证": ("XOM",),
        "像": ("AAPL",),
        "勉强像": ("JPM",),
        "不像": ("MSFT",),
    }
    for selected_filter, symbols in expected.items():
        app.selectbox[0].select(selected_filter).run()
        assert tuple(app.dataframe[0].value["Symbol"]) == symbols


def test_chart_review_cache_mode_renders_real_qfq_bars(
    tmp_path: Path, monkeypatch
) -> None:
    cache_root = tmp_path / "qfq"
    _write_cached_aapl(cache_root)
    monkeypatch.setenv("PATTERN_FINDER_CACHE_ROOT", str(cache_root))
    app = _load("app/pages/2_Chart_Review.py")

    app.segmented_control[0].set_value("Cache / Futu").run()

    assert not app.exception
    assert tuple(app.selectbox[0].options) == ("AAPL",)
    assert app.selectbox[0].value == "AAPL"
    assert len(app.get("plotly_chart")) == 1
    assert "Futu QFQ" in _visible_text(app)
    assert "Detector Version: phase1-v1" in _visible_text(app)
    assert tuple(app.segmented_control[1].options) == HUMAN_LABELS


def test_chart_review_appends_validation_only_when_form_is_submitted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_root = tmp_path / "qfq"
    validation_path = tmp_path / "flat_base_validation.jsonl"
    _write_cached_aapl(cache_root)
    monkeypatch.setenv("PATTERN_FINDER_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PATTERN_FINDER_VALIDATION_PATH", str(validation_path))
    app = _load("app/pages/2_Chart_Review.py")
    app.segmented_control[0].set_value("Cache / Futu").run()

    assert not validation_path.exists()
    app.run()
    assert not validation_path.exists()

    app.segmented_control[1].set_value("不像").run()
    app.pills[0].set_value(["整体仍在下降", "阻力不清楚"])
    app.text_area[0].input("  下降趋势仍明显  ")
    save = next(button for button in app.button if button.label == "Save validation")
    save.click().run()

    assert not app.exception
    history = read_validation_history(validation_path)
    assert len(history) == 1
    assert history[0].symbol == "AAPL"
    assert history[0].detector_version == "phase1-v1"
    assert history[0].computer_flat_base == "YES"
    assert history[0].human_label == "不像"
    assert history[0].reason_tags == ("整体仍在下降", "阻力不清楚")
    assert history[0].note == "下降趋势仍明显"
    assert "Validation saved" in _visible_text(app)

    app.run()
    assert len(read_validation_history(validation_path)) == 1


def test_chart_review_like_disables_reason_tags(tmp_path: Path, monkeypatch) -> None:
    cache_root = tmp_path / "qfq"
    _write_cached_aapl(cache_root)
    monkeypatch.setenv("PATTERN_FINDER_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv(
        "PATTERN_FINDER_VALIDATION_PATH",
        str(tmp_path / "flat_base_validation.jsonl"),
    )
    app = _load("app/pages/2_Chart_Review.py")
    app.segmented_control[0].set_value("Cache / Futu").run()

    app.segmented_control[1].set_value("像").run()

    assert app.pills[0].disabled is True
