from datetime import UTC, datetime
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd
from streamlit.testing.v1 import AppTest

from tv_quant.pattern_finder.review import (
    COMPUTER_FILTERS,
    HUMAN_FILTERS,
    VALIDATION_FILTERS,
)
from tv_quant.pattern_finder import flat_base as flat_base_module
from tv_quant.pattern_finder import futu_service
from tv_quant.pattern_finder.pattern_registry import FLAT_BASE_REASON_TAGS
from tv_quant.pattern_finder.persistence.review_queue_repository import (
    ReviewQueueRepository,
)
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
    assert app.title[0].value == "形态发现器"
    assert "本地" in _visible_text(app)
    assert tuple(page.title for page in app.get("page_link")) == ()


def test_codex_model_router_page_is_read_only_by_default() -> None:
    app = _load("app/pages/6_Codex_Model_Router.py")

    assert not app.exception
    assert app.title[0].value == "Codex 模型路由"
    assert "不会自动切换当前 Codex 会话" in _visible_text(app)


def test_today_scan_page_loads_all_three_fixture_rows() -> None:
    app = _load("app/pages/1_Today_Scan.py")

    assert not app.exception
    assert app.title[0].value == "今日扫描"
    pattern = next(box for box in app.selectbox if box.label == "当前查看形态")
    assert tuple(pattern.options) == ("平底形态",)
    assert len(app.dataframe) == 1
    table = app.dataframe[0].value
    assert tuple(table["股票代码"]) == ("TEST_FLAT", "TEST_ROUNDED", "TEST_READY")
    assert tuple(table.columns) == (
        "股票代码",
        "样例名称",
        "K线数量",
        "平底形态",
        "底部周期",
        "底部深度",
        "底部测试次数",
        "标准化斜率",
        "支撑位",
        "阻力位",
    )
    assert tuple(table["平底形态"]) == ("是", "是", "是")
    assert table.loc[table["股票代码"] == "TEST_FLAT", "底部测试次数"].iloc[0] >= 2
    assert "Today Scan" not in _visible_text(app)


def test_chart_review_loads_chart_and_can_switch_fixture() -> None:
    app = _load("app/pages/2_Chart_Review.py")

    assert not app.exception
    assert app.title[0].value == "图表复核"
    assert tuple(app.selectbox[0].options) == ("平底形态",)
    assert tuple(app.selectbox[1].options) == ("TEST_FLAT", "TEST_ROUNDED", "TEST_READY")
    assert len(app.get("plotly_chart")) == 1
    assert "当前评价形态：平底形态" in _visible_text(app)
    assert "这段价格结构是否像一个平底形态？" in _visible_text(app)
    assert "底部测试次数：" in _visible_text(app)
    assert "标准化斜率：" in _visible_text(app)

    app.selectbox[1].select("TEST_READY").run()
    assert not app.exception
    assert app.selectbox[1].value == "TEST_READY"
    assert "检测器版本：phase1-v1" in _visible_text(app)


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


def _load_cache_review(
    tmp_path: Path,
    monkeypatch,
    *,
    too_deep: bool,
) -> AppTest:
    return _load_cache_review_with_symbols(
        tmp_path,
        monkeypatch,
        (("AAPL", too_deep),),
    )


def _load_cache_review_with_symbols(
    tmp_path: Path,
    monkeypatch,
    symbols: tuple[tuple[str, bool], ...],
    *,
    blocked_symbols: tuple[str, ...] = (),
) -> AppTest:
    cache_root = tmp_path / "qfq"
    for symbol, too_deep in symbols:
        _write_cached_symbol(cache_root, symbol, too_deep=too_deep)
        if symbol in blocked_symbols:
            path = cache_root / f"{symbol}_daily.csv"
            frame = pd.read_csv(path)
            frame.drop(index=10).to_csv(path, index=False)
    monkeypatch.setenv("PATTERN_FINDER_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PATTERN_FINDER_AS_OF_UTC", "2026-08-10T04:00:00+00:00")
    monkeypatch.setenv(
        "PATTERN_FINDER_VALIDATION_PATH", str(tmp_path / "pattern_validation.jsonl")
    )
    monkeypatch.setenv(
        "PATTERN_FINDER_LEGACY_VALIDATION_PATH",
        str(tmp_path / "flat_base_validation.jsonl"),
    )
    monkeypatch.setenv(
        "PATTERN_FINDER_MIGRATION_LEDGER_PATH",
        str(tmp_path / "pattern_validation_migration_ledger.jsonl"),
    )
    monkeypatch.setenv("PATTERN_FINDER_REPOSITORY_ROOT", str(ROOT))
    monkeypatch.setenv("PATTERN_FINDER_DB_PATH", str(tmp_path / "pattern_finder.db"))
    app = _load("app/pages/2_Chart_Review.py")
    app.segmented_control[0].set_value("缓存 / Futu").run()
    return app


def _button(app: AppTest, label: str):
    return next(button for button in app.button if button.label == label)


def _state_filter(app: AppTest):
    return next(box for box in app.selectbox if box.label == "状态筛选")


def _symbol_search(app: AppTest):
    return next(item for item in app.text_input if item.label == "精确股票代码")


def _human_label_control(app: AppTest):
    return next(
        control
        for control in app.segmented_control
        if "人工判断" in control.label
    )


def _fill_like_review(app: AppTest) -> None:
    _human_label_control(app).set_value("像").run()


def test_cache_review_shows_provisional_position_and_next_without_dropdown(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _load_cache_review_with_symbols(
        tmp_path,
        monkeypatch,
        (("AAPL", False), ("MSFT", False)),
    )

    assert "LOCAL CACHE · NOT A FORMAL SCAN BATCH" in _visible_text(app)
    assert "AAPL · 1 / 2" in _visible_text(app)
    assert not any(box.label == "缓存股票" for box in app.selectbox)

    _button(app, "下一只").click().run()

    assert "MSFT · 2 / 2" in _visible_text(app)


def test_save_and_next_appends_once_and_advances_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    validation_path = tmp_path / "pattern_validation.jsonl"
    app = _load_cache_review_with_symbols(
        tmp_path,
        monkeypatch,
        (("AAPL", False), ("MSFT", False)),
    )
    _fill_like_review(app)

    _button(app, "保存并下一只").click().run()

    history = read_validation_history(validation_path)
    assert len(history) == 1
    assert history[0].symbol == "AAPL"
    assert "MSFT · 1 / 2" in _visible_text(app)


def test_next_position_is_restored_after_page_restart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _load_cache_review_with_symbols(
        tmp_path,
        monkeypatch,
        (("AAPL", False), ("MSFT", False)),
    )
    _button(app, "下一只").click().run()

    restarted = _load("app/pages/2_Chart_Review.py")
    restarted.segmented_control[0].set_value("缓存 / Futu").run()

    assert "MSFT · 2 / 2" in _visible_text(restarted)


def test_save_only_keeps_selected_review_visible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    validation_path = tmp_path / "pattern_validation.jsonl"
    app = _load_cache_review_with_symbols(
        tmp_path,
        monkeypatch,
        (("AAPL", False), ("MSFT", False)),
    )
    _fill_like_review(app)

    _button(app, "仅保存").click().run()

    assert len(read_validation_history(validation_path)) == 1
    assert "AAPL · 2 / 2" in _visible_text(app)


def test_skip_snooze_restore_and_state_filter_are_persisted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _load_cache_review_with_symbols(
        tmp_path,
        monkeypatch,
        (("AAPL", False),),
    )

    _button(app, "跳过").click().run()
    assert "已跳过 1" in _visible_text(app)

    _state_filter(app).select("已跳过").run()
    _button(app, "恢复").click().run()
    assert "未复核 1" in _visible_text(app)

    _state_filter(app).select("全部").run()
    _button(app, "稍后处理").click().run()
    assert "稍后处理 1" in _visible_text(app)

    restarted = _load("app/pages/2_Chart_Review.py")
    restarted.segmented_control[0].set_value("缓存 / Futu").run()
    assert "稍后处理 1" in _visible_text(restarted)


def test_exact_symbol_search_is_case_insensitive_and_not_partial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _load_cache_review_with_symbols(
        tmp_path,
        monkeypatch,
        (("AAPL", False), ("MSFT", False)),
    )

    _symbol_search(app).input("msft").run()
    assert "MSFT · 1 / 1" in _visible_text(app)

    _symbol_search(app).input("ms").run()
    assert "当前筛选条件下没有可复核股票" in _visible_text(app)


def test_invalid_validation_store_disables_review_writes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    validation_path = tmp_path / "pattern_validation.jsonl"
    validation_path.write_text("not-json\n", encoding="utf-8")

    app = _load_cache_review_with_symbols(
        tmp_path,
        monkeypatch,
        (("AAPL", False),),
    )

    assert "验证历史无效" in _visible_text(app)
    assert _button(app, "仅保存").disabled is True
    assert _button(app, "保存并下一只").disabled is True


def test_cursor_failure_after_append_preserves_validation_and_position(
    tmp_path: Path,
    monkeypatch,
) -> None:
    validation_path = tmp_path / "pattern_validation.jsonl"
    original = ReviewQueueRepository.save_cursor
    calls = 0

    def fail_second_save(self, cursor):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise RuntimeError("cursor unavailable")
        return original(self, cursor)

    monkeypatch.setattr(ReviewQueueRepository, "save_cursor", fail_second_save)
    app = _load_cache_review_with_symbols(
        tmp_path,
        monkeypatch,
        (("AAPL", False), ("MSFT", False)),
    )
    _fill_like_review(app)

    _button(app, "保存并下一只").click().run()

    assert len(read_validation_history(validation_path)) == 1
    assert "人工复核已保存，但队列位置未更新" in _visible_text(app)
    assert "AAPL · 1 / 2" in _visible_text(app)


def test_data_blocked_item_has_no_review_submit_buttons(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _load_cache_review_with_symbols(
        tmp_path,
        monkeypatch,
        (("AAPL", False),),
        blocked_symbols=("AAPL",),
    )

    assert "数据阻塞 1" in _visible_text(app)
    assert not any(
        button.label in {"仅保存", "保存并下一只"}
        for button in app.button
    )


def test_failed_workflow_action_is_reported_without_moving(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _load_cache_review_with_symbols(
        tmp_path,
        monkeypatch,
        (("AAPL", False), ("MSFT", False)),
    )
    monkeypatch.setattr(
        ReviewQueueRepository,
        "append_action",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("action unavailable")
        ),
    )

    _button(app, "跳过").click().run()

    assert "队列操作未保存" in _visible_text(app)
    assert "AAPL · 1 / 2" in _visible_text(app)


def test_navigation_never_calls_futu_or_refreshes_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    detected_symbols: list[str] = []
    original_detector = flat_base_module.detect_flat_base

    def track_selected_detector(frame):
        detected_symbols.append(str(frame["ticker"].iloc[0]))
        return original_detector(frame)

    monkeypatch.setattr(flat_base_module, "detect_flat_base", track_selected_detector)
    monkeypatch.setattr(
        futu_service,
        "_load_futu_sdk",
        lambda: (_ for _ in ()).throw(AssertionError("OpenD called")),
    )
    monkeypatch.setattr(
        futu_service,
        "refresh_cache_entry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cache refreshed")
        ),
    )
    app = _load_cache_review_with_symbols(
        tmp_path,
        monkeypatch,
        (("AAPL", False), ("MSFT", False)),
    )

    _button(app, "下一只").click().run()

    assert not app.exception
    assert "MSFT · 2 / 2" in _visible_text(app)
    assert detected_symbols[-2:] == ["AAPL", "MSFT"]
    assert detected_symbols.count("AAPL") == 1
    assert detected_symbols.count("MSFT") == 1


def test_chart_review_states_current_pattern_and_yes_question(
    tmp_path: Path, monkeypatch
) -> None:
    app = _load_cache_review(tmp_path, monkeypatch, too_deep=False)
    text = _visible_text(app)

    assert app.title[0].value == "图表复核"
    assert "当前评价形态：平底形态" in text
    assert "这段价格结构是否像一个平底形态？" in text
    assert "不要考虑未来涨跌" in text


def test_chart_review_no_asks_for_missed_flat_base(
    tmp_path: Path, monkeypatch
) -> None:
    app = _load_cache_review(tmp_path, monkeypatch, too_deep=True)

    assert "是否存在电脑漏掉的明显平底形态？" in _visible_text(app)


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
    legacy_path = tmp_path / "flat_base_validation.jsonl"
    validation_path = tmp_path / "pattern_validation.jsonl"
    ledger_path = tmp_path / "pattern_validation_migration_ledger.jsonl"
    _write_review_history(legacy_path)
    monkeypatch.setenv("PATTERN_FINDER_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PATTERN_FINDER_AS_OF_UTC", "2026-08-10T04:00:00+00:00")
    monkeypatch.setenv("PATTERN_FINDER_VALIDATION_PATH", str(validation_path))
    monkeypatch.setenv("PATTERN_FINDER_LEGACY_VALIDATION_PATH", str(legacy_path))
    monkeypatch.setenv("PATTERN_FINDER_MIGRATION_LEDGER_PATH", str(ledger_path))
    monkeypatch.setenv("PATTERN_FINDER_REPOSITORY_ROOT", str(tmp_path))
    app = _load("app/pages/1_Today_Scan.py")

    app.segmented_control[0].set_value("缓存 / Futu").run()

    assert not app.exception
    selectors = {box.label: box for box in app.selectbox}
    assert tuple(selectors["当前查看形态"].options) == ("平底形态",)
    assert tuple(selectors["电脑判断"].options) == COMPUTER_FILTERS
    assert tuple(selectors["人工复核"].options) == HUMAN_FILTERS
    assert tuple(selectors["验证结论"].options) == VALIDATION_FILTERS
    table = app.dataframe[0].value
    assert tuple(table["股票代码"]) == ("AAPL", "MSFT", "JPM", "XOM")
    assert table.loc[table["股票代码"] == "AAPL", "人工形态判断"].iloc[0] == "像"
    assert {"底部周期", "检测器版本", "原因标签", "验证结论"} <= set(table.columns)
    assert any(button.label == "从 Futu OpenD 刷新试点数据" for button in app.button)

    selectors["电脑判断"].select("否").run()
    next(box for box in app.selectbox if box.label == "人工复核").select("勉强像").run()
    next(box for box in app.selectbox if box.label == "验证结论").select("边界案例").run()
    assert tuple(app.dataframe[0].value["股票代码"]) == ("JPM",)


def test_today_scan_refreshes_only_stale_cached_symbols_after_explicit_click(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache_root = tmp_path / "qfq"
    _write_cached_symbol(cache_root, "AAPL")
    calls: list[tuple[tuple[str, ...], Path]] = []

    monkeypatch.setenv("PATTERN_FINDER_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PATTERN_FINDER_AS_OF_UTC", "2026-08-10T04:00:00+00:00")
    monkeypatch.setattr(
        futu_service,
        "stale_cached_symbols",
        lambda **_kwargs: ("BAC", "WFC"),
    )

    def refresh(symbols, *, cache_root, **_kwargs):
        calls.append((tuple(symbols), Path(cache_root)))
        return (object(), object())

    monkeypatch.setattr(futu_service, "refresh_symbols", refresh)
    app = _load("app/pages/1_Today_Scan.py")
    app.segmented_control[0].set_value("缓存 / Futu").run()

    assert calls == []
    button = next(
        item for item in app.button if item.label == "刷新 2 只过期缓存"
    )
    button.click().run()

    assert calls == [(('BAC', 'WFC'), cache_root)]
    assert "已更新 2 只过期缓存" in _visible_text(app)


def test_chart_review_cache_mode_renders_real_qfq_bars(
    tmp_path: Path, monkeypatch
) -> None:
    cache_root = tmp_path / "qfq"
    _write_cached_aapl(cache_root)
    monkeypatch.setenv("PATTERN_FINDER_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PATTERN_FINDER_AS_OF_UTC", "2026-08-10T04:00:00+00:00")
    app = _load("app/pages/2_Chart_Review.py")

    app.segmented_control[0].set_value("缓存 / Futu").run()

    assert not app.exception
    assert "AAPL · 1 / 1" in _visible_text(app)
    assert not any(box.label == "缓存股票" for box in app.selectbox)
    assert len(app.get("plotly_chart")) == 1
    assert "Futu 前复权" in _visible_text(app)
    assert "检测器版本：phase1-v1" in _visible_text(app)
    assert tuple(app.segmented_control[1].options) == HUMAN_LABELS


def test_chart_review_appends_validation_only_when_form_is_submitted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    validation_path = tmp_path / "pattern_validation.jsonl"
    app = _load_cache_review(tmp_path, monkeypatch, too_deep=False)

    assert not validation_path.exists()
    app.run()
    assert not validation_path.exists()

    app.segmented_control[1].set_value("不像").run()
    app.pills[0].set_value(["整体仍明显向下", "阻力区域不清晰"])
    app.text_area[0].input("  下降趋势仍明显  ")
    save = next(button for button in app.button if button.label == "仅保存")
    save.click().run()

    assert not app.exception
    history = read_validation_history(validation_path)
    assert len(history) == 1
    assert history[0].symbol == "AAPL"
    assert history[0].detector_version == "phase1-v1"
    assert history[0].pattern_type == "flat_base"
    assert history[0].computer_result == "YES"
    assert history[0].human_label == "不像"
    assert history[0].reason_tags == ("整体仍明显向下", "阻力区域不清晰")
    assert history[0].note == "下降趋势仍明显"
    assert "人工复核已保存：疑似误报" in _visible_text(app)

    app.run()
    assert len(read_validation_history(validation_path)) == 1


def test_chart_review_like_disables_reason_tags(tmp_path: Path, monkeypatch) -> None:
    app = _load_cache_review(tmp_path, monkeypatch, too_deep=False)

    app.segmented_control[1].set_value("像").run()

    assert app.pills[0].disabled is True


def _review_app(tmp_path: Path, monkeypatch) -> tuple[AppTest, Path]:
    validation_path = tmp_path / "pattern_validation.jsonl"
    return _load_cache_review(tmp_path, monkeypatch, too_deep=False), validation_path


def _save_button(app: AppTest):
    return next(button for button in app.button if button.label == "仅保存")


def test_reason_options_come_only_from_current_profile(
    tmp_path: Path, monkeypatch
) -> None:
    app, validation_path = _review_app(tmp_path, monkeypatch)

    assert tuple(app.pills[0].options) == FLAT_BASE_REASON_TAGS
    assert "低点不稳定" not in app.pills[0].options
    app.segmented_control[1].set_value("不像").run()
    _save_button(app).click().run()

    assert not validation_path.exists()
    assert "至少选择 1 个原因标签" in _visible_text(app)


def test_other_requires_nonblank_note(tmp_path: Path, monkeypatch) -> None:
    app, validation_path = _review_app(tmp_path, monkeypatch)
    app.segmented_control[1].set_value("勉强像").run()
    app.pills[0].set_value(["其他"])
    _save_button(app).click().run()

    assert not validation_path.exists()
    assert "其他" in _visible_text(app) and "备注" in _visible_text(app)


def test_valid_other_reason_appends_exactly_once(tmp_path: Path, monkeypatch) -> None:
    app, validation_path = _review_app(tmp_path, monkeypatch)
    app.segmented_control[1].set_value("勉强像").run()
    app.pills[0].set_value(["其他"])
    app.text_area[0].input("需要进一步复核")
    _save_button(app).click().run()

    history = read_validation_history(validation_path)
    assert len(history) == 1
    assert history[0].reason_tags == ("其他",)
    assert history[0].note == "需要进一步复核"
