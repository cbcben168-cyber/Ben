# Pattern Review Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 M3B 的 Flat Base 专用人工复核层升级为 Pattern Registry 驱动的通用多形态复核框架，同时当前只启用 `flat_base / 平底形态 / phase1-v1`。

**Architecture:** `pattern_registry.py` 只保存人工复核配置，Detector 继续只负责数学结果。`validation.py` 提供通用 `PatternValidation`、确定性验证结论、append-only store 与逐行幂等 legacy migration；`review.py` 提供通用关联和筛选。Streamlit 页面从当前 Profile 读取中文文案、诊断字段和原因标签。

**Tech Stack:** Python 3.14、dataclasses、JSONL、SHA-256、pytest、Streamlit 1.59、pandas、Plotly。

## Global Constraints

- 每个 Task 必须先执行 RED 测试、再做最小 GREEN 实现并独立提交。
- 生产 Registry 只注册并启用 `flat_base`；不得注册或实现 Rounded Base、Compression、READY。
- 不得修改 `src/tv_quant/pattern_finder/flat_base.py`；冻结 SHA-256 是 `ee2c4f45026266b95a2e8759ed609a4523b713aa9bd9905447493ba8dbdd0a34`。
- 不得修改 `phase1-v1` 参数、算法、窗口选择或输出语义。
- 不得修改 `data/raw/pattern_finder/qfq/`；必须保持 33 个 CSV，规范化聚合 SHA-256 是 `e25e78772eef37020741867bcc862512724971a8244c340227569aa28950b46c`。
- 不实现 Candidate Scanner、Score、Outcome、ML、Webhook、券商或订单功能。
- 新记录必须满足完整 schema；只有有效 legacy provenance 才允许不可推导字段为 `null` 并豁免新 reason-tag 规则。
- 旧 reason tags 原样保留；Validation 和 migration ledger 均只追加，不按业务 key 去重。
- UI 主要文案全部中文；`QFQ`、`ATR14`、`OHLC`、股票代码和 `phase1-v1` 可作为技术标识保留。
- `PATTERN_FINDER_VALIDATION_PATH` 继续作为新通用 store 的可选覆盖；新增 `PATTERN_FINDER_LEGACY_VALIDATION_PATH` 和 `PATTERN_FINDER_MIGRATION_LEDGER_PATH` 仅覆盖迁移源与账本。不得把新 schema 追加回 legacy 文件。
- 保持现有 Streamlit 直接脚本、`st.form`、有界 `st.cache_data` 与 `width="stretch"`；不做无关重构。
- 每个 Task 只暂存列出的文件，不得暂存 `.agents/skills/developing-with-streamlit` 等无关内容。

## File Map

- Create `src/tv_quant/pattern_finder/pattern_registry.py`: Profile、Flat Base V1 配置和查询。
- Modify `src/tv_quant/pattern_finder/validation.py`: 通用模型、自动结论、store 和 legacy migration。
- Modify `src/tv_quant/pattern_finder/review.py`: pattern-aware key、关联和三组筛选。
- Modify `app/Home.py`, `app/pages/1_Today_Scan.py`, `app/pages/2_Chart_Review.py`: 中文 UI 和当前形态入口。
- Modify `src/tv_quant/pattern_finder/charts.py`: 只中文化可见图例和覆盖层标签。
- Modify/Create tests under `tests/pattern_finder/`: 每项行为的 RED/GREEN 与冻结回归门禁。
- Create `docs/superpowers/validation/2026-08-10-pattern-review-framework-manual-acceptance.md`: 实际验收证据。

---

### Task 1: Pattern Registry / Pattern Profile

**Files:**
- Create: `src/tv_quant/pattern_finder/pattern_registry.py`
- Create: `tests/pattern_finder/test_pattern_registry.py`

**Interfaces:**
- Produces: `DiagnosticField(key, source_column, display_name_zh, format_spec)`.
- Produces: `PatternProfile(pattern_type: str, display_name_zh: str, display_name_en: str, review_question_yes: str, review_question_no: str, review_help: str, reason_tags: tuple[str, ...], diagnostic_fields: tuple[DiagnosticField, ...], overlay_capabilities: frozenset[str], enabled: bool)`.
- Produces: `get_pattern_profile(pattern_type: str, *, require_enabled: bool = True) -> PatternProfile`.
- Produces: `enabled_pattern_profiles(registry: Mapping[str, PatternProfile] = PATTERN_REGISTRY) -> tuple[PatternProfile, ...]`.

- [ ] **Step 1: RED — write Registry contract tests**

```python
def test_flat_base_is_the_only_enabled_profile() -> None:
    profile = get_pattern_profile("flat_base")
    assert profile.display_name_zh == "平底形态"
    assert profile.reason_tags == FLAT_BASE_REASON_TAGS
    assert tuple(field.key for field in profile.diagnostic_fields) == (
        "base_length", "base_depth", "bottom_tests", "normalized_slope",
        "support", "resistance",
    )
    assert tuple(item.pattern_type for item in enabled_pattern_profiles()) == ("flat_base",)


def test_unknown_and_disabled_profiles_are_not_selectable() -> None:
    with pytest.raises(KeyError, match="未注册形态"):
        get_pattern_profile("missing")
    disabled = replace(get_pattern_profile("flat_base"), pattern_type="test_only", enabled=False)
    assert enabled_pattern_profiles({"test_only": disabled}) == ()
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/pattern_finder/test_pattern_registry.py -q`

Expected: FAIL because the Registry module does not exist.

- [ ] **Step 3: GREEN — implement only Flat Base Profile**

```python
FLAT_BASE_REASON_TAGS = (
    "底部区间太深", "底部持续时间太短", "低点区域不集中", "横盘稳定性不足",
    "整体仍明显向上", "整体仍明显向下", "波动区间过宽", "阻力区域不清晰",
    "底部测试次数不足", "结构不像平底", "其他",
)
PATTERN_REGISTRY = MappingProxyType({"flat_base": FLAT_BASE_PROFILE})

def get_pattern_profile(pattern_type: str, *, require_enabled: bool = True) -> PatternProfile:
    try:
        profile = PATTERN_REGISTRY[pattern_type]
    except KeyError as error:
        raise KeyError(f"未注册形态: {pattern_type}") from error
    if require_enabled and not profile.enabled:
        raise ValueError(f"形态尚未启用: {pattern_type}")
    return profile
```

`review_question_yes/no`、`review_help`、11 个 reason tags、6 个 diagnostics 和 overlay capabilities 必须逐字来自 Spec；不创建未来 Profile。

- [ ] **Step 4: Run GREEN and commit**

Run: `pytest tests/pattern_finder/test_pattern_registry.py -q`

Expected: PASS.

```powershell
git add -- src/tv_quant/pattern_finder/pattern_registry.py tests/pattern_finder/test_pattern_registry.py
git commit -m "feat: add pattern review registry"
```

### Task 2: 通用 PatternValidation 数据模型

**Files:**
- Modify: `src/tv_quant/pattern_finder/validation.py`
- Modify: `tests/pattern_finder/test_validation.py`

**Interfaces:**
- Consumes: `get_pattern_profile()`.
- Produces: `JSONScalar = str | int | float | bool | None`.
- Produces: `MigrationProvenance` and `PatternValidation`.
- Produces: four-part `PatternValidation.key` ordered as symbol, pattern_type, detector_version, scan_as_of_date.
- Produces: `to_dict()` / `from_dict()` with nested diagnostics and nullable migration provenance.

- [ ] **Step 1: RED — replace Flat Base-only round-trip expectation**

```python
def test_pattern_validation_round_trips_generic_schema() -> None:
    record = PatternValidation(
        recorded_at_utc=RECORDED_1, symbol="AAPL", pattern_type="flat_base",
        pattern_display_name="平底形态", detector_version="phase1-v1",
        scan_as_of_date="2026-08-07", computer_result="YES", human_label="像",
        validation_result="true_positive_like", reason_tags=(), note="",
        review_window_start="2026-07-06", review_window_end="2026-08-07",
        diagnostics={"base_length": 25, "base_depth": 0.14, "bottom_tests": 2,
                     "normalized_slope": 0.0, "support": 99.0, "resistance": 102.0},
        migration_provenance=None,
    )
    assert record.key == ("AAPL", "flat_base", "phase1-v1", "2026-08-07")
    assert PatternValidation.from_dict(record.to_dict()) == record
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/pattern_finder/test_validation.py::test_pattern_validation_round_trips_generic_schema -q`

Expected: FAIL because `PatternValidation` is absent.

- [ ] **Step 3: GREEN — implement model and structural validation**

```python
JSONScalar = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class MigrationProvenance:
    source_path: str
    source_line_number: int
    source_line_content_sha256: str
    migration_fingerprint: str


@dataclass(frozen=True, slots=True)
class PatternValidation:
    recorded_at_utc: datetime
    symbol: str
    pattern_type: str
    pattern_display_name: str
    detector_version: str
    scan_as_of_date: str
    computer_result: str
    human_label: str
    validation_result: str
    reason_tags: tuple[str, ...]
    note: str
    review_window_start: str | None
    review_window_end: str | None
    diagnostics: dict[str, JSONScalar]
    migration_provenance: MigrationProvenance | None
```

Enforce UTC, normalized symbol, ISO dates, ordered non-null windows for new records, JSON-compatible diagnostics and all-or-nothing provenance. A normal record cannot use null windows or non-null provenance.

- [ ] **Step 4: Run GREEN and commit**

Run: `pytest tests/pattern_finder/test_validation.py -q`

Expected: PASS after replacing Flat Base-only model tests.

```powershell
git add -- src/tv_quant/pattern_finder/validation.py tests/pattern_finder/test_validation.py
git commit -m "refactor: generalize pattern validation model"
```

### Task 3: validation_result 与新记录质量规则

**Files:**
- Modify: `src/tv_quant/pattern_finder/validation.py`
- Modify: `tests/pattern_finder/test_validation.py`

**Interfaces:**
- Produces: `derive_validation_result(computer_result: str, human_label: str) -> str`.
- Produces: `VALIDATION_RESULT_LABELS: Mapping[str, str]`.
- Produces: `build_pattern_validation(*, recorded_at_utc: datetime, symbol: str, pattern_type: str, detector_version: str, scan_as_of_date: date, computer_result: str, human_label: str, reason_tags: Iterable[str], note: str, review_window_start: date, review_window_end: date, diagnostics: Mapping[str, JSONScalar]) -> PatternValidation`.
- Caller cannot supply `pattern_display_name`, `validation_result` or `migration_provenance` to the new-record builder.

- [ ] **Step 1: RED — add full result matrix and quality tests**

```python
@pytest.mark.parametrize(("computer", "human", "expected"), [
    ("YES", "像", "true_positive_like"), ("NO", "不像", "true_negative_unlike"),
    ("YES", "不像", "possible_false_positive"), ("NO", "像", "possible_false_negative"),
    ("YES", "勉强像", "borderline"), ("NO", "勉强像", "borderline"),
])
def test_validation_result_matrix(computer: str, human: str, expected: str) -> None:
    assert derive_validation_result(computer, human) == expected


def test_new_record_reason_quality_rules_are_strict() -> None:
    with pytest.raises(ValueError, match="至少选择 1 个原因标签"):
        _build_new(human_label="不像", reason_tags=())
    with pytest.raises(ValueError, match="其他.*备注"):
        _build_new(human_label="勉强像", reason_tags=("其他",), note="   ")
    assert _build_new(human_label="像", reason_tags=()).reason_tags == ()
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/pattern_finder/test_validation.py -q`

Expected: FAIL because deterministic result derivation and generic builder are absent.

- [ ] **Step 3: GREEN — implement fixed matrix and Profile validation**

```python
_VALIDATION_MATRIX = {
    ("YES", "像"): "true_positive_like", ("NO", "不像"): "true_negative_unlike",
    ("YES", "不像"): "possible_false_positive", ("NO", "像"): "possible_false_negative",
    ("YES", "勉强像"): "borderline", ("NO", "勉强像"): "borderline",
}
VALIDATION_RESULT_LABELS = MappingProxyType({
    "true_positive_like": "一致命中", "true_negative_unlike": "一致排除",
    "possible_false_positive": "疑似误报", "possible_false_negative": "疑似漏报",
    "borderline": "边界案例",
})
```

Builder loads Profile, derives display name/result, requires Profile diagnostics, deduplicates tags, requires one tag for `勉强像/不像`, and requires trimmed note for `其他`. `像` may have no tag; supplied tags must still be Profile tags.

- [ ] **Step 4: Run GREEN and commit**

Run: `pytest tests/pattern_finder/test_validation.py -q`

Expected: PASS.

```powershell
git add -- src/tv_quant/pattern_finder/validation.py tests/pattern_finder/test_validation.py
git commit -m "feat: derive pattern validation outcomes"
```

### Task 4: append-only pattern_validation.jsonl Store

**Files:**
- Modify: `src/tv_quant/pattern_finder/validation.py`
- Modify: `tests/pattern_finder/test_validation.py`

**Interfaces:**
- Produces: `DEFAULT_VALIDATION_PATH = Path("data/processed/pattern_finder/manual_validation/pattern_validation.jsonl")`.
- Produces: generic `append_validation()`, `read_validation_history()` and `latest_validations()`.

- [ ] **Step 1: RED — test append-only history and pattern-aware latest key**

```python
def test_generic_store_appends_and_keeps_pattern_type_in_latest_key(tmp_path: Path) -> None:
    path = tmp_path / "pattern_validation.jsonl"
    first = _build_new(recorded_at_utc=RECORDED_1)
    second = _build_new(recorded_at_utc=RECORDED_2, human_label="不像",
                        reason_tags=("结构不像平底",))
    append_validation(path, first)
    append_validation(path, second)
    assert read_validation_history(path) == (first, second)
    assert latest_validations((first, second))[first.key] == second
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/pattern_finder/test_validation.py::test_generic_store_appends_and_keeps_pattern_type_in_latest_key -q`

Expected: FAIL while store code still assumes a three-part Flat Base key.

- [ ] **Step 3: GREEN — update store without any rewrite path**

Keep `open("a", encoding="utf-8")`. Do not add compaction, in-place update or business-key deduplication. Reader errors must retain exact JSONL line numbers through `ValidationStoreError`.

- [ ] **Step 4: Run GREEN and commit**

Run: `pytest tests/pattern_finder/test_validation.py -q`

Expected: PASS.

```powershell
git add -- src/tv_quant/pattern_finder/validation.py tests/pattern_finder/test_validation.py
git commit -m "feat: add generic pattern validation store"
```

### Task 5: legacy flat_base_validation 逐记录迁移与 ledger

**Files:**
- Modify: `src/tv_quant/pattern_finder/validation.py`
- Create: `tests/pattern_finder/test_validation_migration.py`

**Interfaces:**
- Produces: `LEGACY_VALIDATION_PATH`, `DEFAULT_MIGRATION_LEDGER_PATH`.
- Produces: `MigrationSummary(scanned, migrated, already_migrated, ledger_repaired)`.
- Produces: `migrate_legacy_validations(legacy_path, target_path, ledger_path, *, repository_root) -> MigrationSummary`.

- [ ] **Step 1: RED — test preservation, nulls and idempotency**

```python
def test_migration_preserves_every_line_and_legacy_tags(tmp_path: Path) -> None:
    legacy = _write_legacy_lines(tmp_path, tags=("低点不稳定",), count=2)
    summary = migrate_legacy_validations(
        legacy, tmp_path / "pattern_validation.jsonl", tmp_path / "ledger.jsonl",
        repository_root=tmp_path,
    )
    records = read_validation_history(tmp_path / "pattern_validation.jsonl")
    assert summary.migrated == 2
    assert len(records) == 2
    assert records[0].pattern_type == "flat_base"
    assert records[0].pattern_display_name == "平底形态"
    assert records[0].reason_tags == ("低点不稳定",)
    assert records[0].review_window_start is None
    assert records[0].review_window_end is None
    assert records[0].validation_result == "possible_false_positive"


def test_rerun_repairs_missing_ledger_without_duplicate_target(tmp_path: Path) -> None:
    legacy, target, ledger = _migration_paths(tmp_path)
    migrate_legacy_validations(legacy, target, ledger, repository_root=tmp_path)
    ledger.unlink()
    summary = migrate_legacy_validations(legacy, target, ledger, repository_root=tmp_path)
    assert summary.migrated == 0
    assert summary.ledger_repaired == 1
    assert len(read_validation_history(target)) == 1
```

Also test: later appended source line migrates once; same source path/line with changed content raises; malformed JSON stops; source bytes remain unchanged; duplicate business keys remain separate records.

Define `_write_legacy_lines(tmp_path: Path, *, tags: tuple[str, ...], count: int) -> Path` and `_migration_paths(tmp_path: Path) -> tuple[Path, Path, Path]` as local test helpers in `test_validation_migration.py`; they write only under `tmp_path`.

- [ ] **Step 2: Run RED**

Run: `pytest tests/pattern_finder/test_validation_migration.py -q`

Expected: FAIL because migration contracts do not exist.

- [ ] **Step 3: GREEN — implement canonical per-line fingerprint and recovery**

```python
def migration_fingerprint(source_path: str, line_number: int, line_bytes: bytes) -> tuple[str, str]:
    line_sha256 = sha256(line_bytes).hexdigest()
    canonical = f"{source_path}\n{line_number}\n{line_sha256}".encode("utf-8")
    return line_sha256, sha256(canonical).hexdigest()
```

Normalize source path to repository-relative POSIX form. Preserve old fields/tags/time, derive `pattern_type`, display name, computer result and validation result, move exactly four old diagnostics, and set unavailable windows to null. Append target first and ledger second. Scan target provenance plus ledger on rerun; repair a missing ledger entry without duplicating target. A ledger path+line hash mismatch is a hard error.

- [ ] **Step 4: Run GREEN and commit**

Run: `pytest tests/pattern_finder/test_validation_migration.py tests/pattern_finder/test_validation.py -q`

Expected: PASS using only `tmp_path` files.

```powershell
git add -- src/tv_quant/pattern_finder/validation.py tests/pattern_finder/test_validation_migration.py
git commit -m "feat: migrate legacy pattern reviews idempotently"
```

### Task 6: review.py 改为 pattern-aware

**Files:**
- Modify: `src/tv_quant/pattern_finder/review.py`
- Modify: `tests/pattern_finder/test_review.py`

**Interfaces:**
- Consumes: four-part validation key and `VALIDATION_RESULT_LABELS`.
- Produces: `attach_latest_validations(rows, history, *, pattern_type: str, computer_result_field: str, scan_date_field: str)`; common logic never hardcodes `Flat Base` or `Base End`.
- Produces: `filter_review_rows(rows, *, computer_filter, human_filter, validation_filter)`.
- Produces: `COMPUTER_FILTERS`, `HUMAN_FILTERS`, `VALIDATION_FILTERS` in Chinese.

- [ ] **Step 1: RED — add pattern isolation and composed-filter tests**

```python
def test_attach_latest_isolated_by_pattern_and_exposes_result_label() -> None:
    rows = attach_latest_validations(
        SCAN_ROWS, HISTORY, pattern_type="flat_base",
        computer_result_field="Flat Base", scan_date_field="Base End",
    )
    aapl = next(row for row in rows if row["Symbol"] == "AAPL")
    assert aapl["Pattern Type"] == "flat_base"
    assert aapl["Validation Result"] == "一致命中"


def test_three_filters_compose() -> None:
    rows = filter_review_rows(ENRICHED_ROWS, computer_filter="否",
                              human_filter="勉强像", validation_filter="边界案例")
    assert tuple(row["Symbol"] for row in rows) == ("JPM",)
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/pattern_finder/test_review.py -q`

Expected: FAIL because keying and filters remain Flat Base-specific.

- [ ] **Step 3: GREEN — include current pattern in lookup and apply three filters**

Resolve the source column names from function arguments, then add generic `Pattern Type`, `Computer Result` and `Scan As Of Date` keys. Never attach history from another `pattern_type`. Add Chinese validation result to enriched rows but retain detector-specific scan-row keys until the UI display boundary. Validate every filter value before filtering.

- [ ] **Step 4: Run GREEN and commit**

Run: `pytest tests/pattern_finder/test_review.py -q`

Expected: PASS.

```powershell
git add -- src/tv_quant/pattern_finder/review.py tests/pattern_finder/test_review.py
git commit -m "refactor: make pattern reviews pattern-aware"
```

### Task 7: 首页与 Today Scan 中文化及当前形态入口

**Files:**
- Modify: `app/Home.py`
- Modify: `app/pages/1_Today_Scan.py`
- Modify: `tests/pattern_finder/test_pages.py`

**Interfaces:**
- Consumes: enabled Profiles, migration/store API and three review filters.
- Produces: a current-pattern selector whose only option is `平底形态`.

- [ ] **Step 1: RED — assert Chinese page, selector, columns and filters**

```python
def test_today_scan_is_chinese_and_has_only_flat_base_profile() -> None:
    app = _load("app/pages/1_Today_Scan.py")
    assert app.title[0].value == "今日扫描"
    pattern = next(box for box in app.selectbox if box.label == "当前查看形态")
    assert tuple(pattern.options) == ("平底形态",)
    table = app.dataframe[0].value
    assert {"股票代码", "平底形态", "底部周期", "人工形态判断", "验证结论"} <= set(table.columns)
    assert "Today Scan" not in _visible_text(app)
```

Update Home assertions to Chinese title/captions and cache-mode tests to expect separate 电脑判断、人工复核、验证结论 selectors.

- [ ] **Step 2: Run RED**

Run: `pytest tests/pattern_finder/test_pages.py -q`

Expected: FAIL on current English page copy and combined filter.

- [ ] **Step 3: GREEN — localize only the display boundary**

Resolve the selected Profile from enabled Profiles. Call the Task 6 adapter with current Flat Base source-column names; future integrations can supply different names without changing common review logic. Keep internal DataFrame keys English, rename only immediately before `st.dataframe`, and retain numeric formatting with `column_config`. In cache mode run idempotent migration before reading generic history. Read target/source/ledger overrides from their three distinct environment variables. Keep Futu access behind the existing explicit refresh button.

- [ ] **Step 4: Run GREEN and commit**

Run: `pytest tests/pattern_finder/test_pages.py tests/pattern_finder/test_review.py -q`

Expected: PASS.

```powershell
git add -- app/Home.py app/pages/1_Today_Scan.py tests/pattern_finder/test_pages.py
git commit -m "feat: localize today pattern scan"
```

### Task 8: Chart Review 中文化与动态判断文案

**Files:**
- Modify: `app/pages/2_Chart_Review.py`
- Modify: `src/tv_quant/pattern_finder/charts.py`
- Modify: `tests/pattern_finder/test_pages.py`
- Modify: `tests/pattern_finder/test_charts.py`

**Interfaces:**
- Consumes: selected Profile, `build_pattern_validation()` and migration/store API.
- Produces: dynamic YES/NO question, Chinese diagnostics, generic save flow and Chinese chart labels.
- Test helper: add `_load_cache_review(tmp_path: Path, monkeypatch, *, too_deep: bool) -> AppTest` in `test_pages.py` using the existing `_write_cached_symbol()` fixture writer.

- [ ] **Step 1: RED — test current object, YES/NO copy and chart labels**

```python
def test_chart_review_states_current_pattern_and_yes_question(tmp_path: Path, monkeypatch) -> None:
    app = _load_cache_review(tmp_path, monkeypatch, too_deep=False)
    text = _visible_text(app)
    assert app.title[0].value == "图表复核"
    assert "当前评价形态：平底形态" in text
    assert "这段价格结构是否像一个平底形态？" in text
    assert "不要考虑未来涨跌" in text


def test_chart_review_no_asks_for_missed_flat_base(tmp_path: Path, monkeypatch) -> None:
    app = _load_cache_review(tmp_path, monkeypatch, too_deep=True)
    assert "是否存在电脑漏掉的明显平底形态？" in _visible_text(app)


def test_chart_labels_are_chinese() -> None:
    figure = build_candlestick_figure(load_fixture("TEST_FLAT"))
    assert tuple(trace.name for trace in figure.data) == ("日K（OHLC）", "成交量")
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/pattern_finder/test_pages.py tests/pattern_finder/test_charts.py -q`

Expected: FAIL on current English UI/chart labels and fixed question.

- [ ] **Step 3: GREEN — render Profile-driven review and diagnostics**

Add only `平底形态` to current-pattern selector. Render the matching Profile question and help. Iterate `profile.diagnostic_fields`; build generic diagnostics from `FlatBaseResult.selected`; pass explicit window start/end to the builder. Rename chart trace/annotation labels only, never values or overlay calculations.

Run idempotent legacy migration before reading history on this page as well, so direct navigation to Chart Review preserves old records. Translate the chart title and every user-visible legend/annotation while preserving ticker and technical abbreviations.

- [ ] **Step 4: Run GREEN and commit**

Run: `pytest tests/pattern_finder/test_pages.py tests/pattern_finder/test_charts.py -q`

Expected: PASS.

```powershell
git add -- app/pages/2_Chart_Review.py src/tv_quant/pattern_finder/charts.py tests/pattern_finder/test_pages.py tests/pattern_finder/test_charts.py
git commit -m "feat: localize pattern chart review"
```

### Task 9: 当前形态专属 Reason Tags

**Files:**
- Modify: `app/pages/2_Chart_Review.py`
- Modify: `tests/pattern_finder/test_pages.py`

**Interfaces:**
- Consumes: `profile.reason_tags` and Task 3 builder validation.
- Produces: no legacy/future tag leakage into new Flat Base records.
- Test helpers: define `_review_app(tmp_path: Path, monkeypatch) -> tuple[AppTest, Path]` and `_save_button(app: AppTest)` in `test_pages.py` by reusing the Task 8 cache-review helper.

- [ ] **Step 1: RED — test Profile options and invalid submissions**

```python
def test_reason_options_come_only_from_current_profile(tmp_path: Path, monkeypatch) -> None:
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
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/pattern_finder/test_pages.py -q`

Expected: FAIL while page imports global `REASON_TAGS` and does not enforce both rules.

- [ ] **Step 3: GREEN — use Profile tags and builder as source of truth**

Remove global `REASON_TAGS` imports. Pass `profile.reason_tags` to `st.pills`. On builder `ValueError`, show the Chinese data-quality message and do not append. Add a valid `其他` plus nonblank note test proving exactly one append.

- [ ] **Step 4: Run GREEN and commit**

Run: `pytest tests/pattern_finder/test_pages.py tests/pattern_finder/test_validation.py -q`

Expected: PASS.

```powershell
git add -- app/pages/2_Chart_Review.py tests/pattern_finder/test_pages.py
git commit -m "test: enforce profile-specific review reasons"
```

### Task 10: Detector 输出适配与 33 只 cache 冻结回归

**Files:**
- Modify: `src/tv_quant/pattern_finder/review.py`
- Modify: `app/pages/2_Chart_Review.py`
- Create: `tests/pattern_finder/test_pattern_review_regression.py`

**Interfaces:**
- Consumes: `FlatBaseResult` without modifying Detector code.
- Produces: `PatternReviewInput(computer_result, detector_version, scan_as_of_date, review_window_start, review_window_end, diagnostics)`.
- Produces: `flat_base_review_input(result: FlatBaseResult) -> PatternReviewInput` as the Flat Base integration boundary used by Chart Review.

- [ ] **Step 1: RED — test that the missing adapter preserves every Detector output used by review**

```python
def test_flat_base_review_input_preserves_detector_result() -> None:
    result = detect_flat_base(_frame())
    review_input = flat_base_review_input(result)
    selected = result.selected
    assert review_input.computer_result == ("YES" if result.pattern_flat_base else "NO")
    assert review_input.detector_version == result.detector_version
    assert review_input.scan_as_of_date == selected.base_end.date()
    assert review_input.review_window_start == selected.base_start.date()
    assert review_input.review_window_end == selected.base_end.date()
    assert review_input.diagnostics == {
        "base_length": selected.base_length,
        "base_depth": selected.base_depth_pct,
        "bottom_tests": selected.bottom_test_count,
        "normalized_slope": selected.normalized_slope,
        "support": selected.support_level,
        "resistance": selected.resistance_level,
    }
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/pattern_finder/test_pattern_review_regression.py -q`

Expected: FAIL because `flat_base_review_input` does not exist.

- [ ] **Step 3: GREEN — implement the minimal adapter and use it in Chart Review**

```python
def flat_base_review_input(result: FlatBaseResult) -> PatternReviewInput:
    selected = result.selected
    return PatternReviewInput(
        computer_result="YES" if result.pattern_flat_base else "NO",
        detector_version=result.detector_version,
        scan_as_of_date=selected.base_end.date(),
        review_window_start=selected.base_start.date(),
        review_window_end=selected.base_end.date(),
        diagnostics={
            "base_length": selected.base_length,
            "base_depth": selected.base_depth_pct,
            "bottom_tests": selected.bottom_test_count,
            "normalized_slope": selected.normalized_slope,
            "support": selected.support_level,
            "resistance": selected.resistance_level,
        },
    )
```

Refactor only Chart Review record construction to consume this adapter. The production change that makes this test fail is a wrong or omitted Detector-to-review field mapping; the Detector remains untouched.

- [ ] **Step 4: Run GREEN and cache gate**

Run: `pytest tests/pattern_finder/test_pattern_review_regression.py tests/pattern_finder/test_flat_base.py tests/pattern_finder/test_pages.py -q`

Expected: PASS.

Run this read-only PowerShell gate:

```powershell
$files = Get-ChildItem -LiteralPath 'data/raw/pattern_finder/qfq' -File -Filter '*_daily.csv' | Sort-Object Name
if ($files.Count -ne 33) { throw "Expected 33 cache files, found $($files.Count)" }
$rows = $files | ForEach-Object { "$($_.Name) $((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant())" }
$bytes = [Text.Encoding]::UTF8.GetBytes(($rows -join "`n"))
$sha = [Security.Cryptography.SHA256]::Create()
$actual = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()
if ($actual -ne 'e25e78772eef37020741867bcc862512724971a8244c340227569aa28950b46c') { throw "Cache hash changed: $actual" }
```

Expected: no output and exit code 0.

Also run `(Get-FileHash -LiteralPath 'src/tv_quant/pattern_finder/flat_base.py' -Algorithm SHA256).Hash.ToLowerInvariant()` and require `ee2c4f45026266b95a2e8759ed609a4523b713aa9bd9905447493ba8dbdd0a34` as a review gate, not as a unit test.

- [ ] **Step 5: Commit Task 10**

```powershell
git add -- src/tv_quant/pattern_finder/review.py app/pages/2_Chart_Review.py tests/pattern_finder/test_pattern_review_regression.py
git commit -m "test: freeze M3B detector review boundary"
```

### Task 11: 全量回归与 Streamlit 实际人工验收

**Files:**
- Create: `docs/superpowers/validation/2026-08-10-pattern-review-framework-manual-acceptance.md`

**Interfaces:**
- Consumes: completed Tasks 1–10.
- Produces: repeatable automated/manual evidence without production-code changes.

- [ ] **Step 1: RED — create a pre-run report**

Set report status to `RED — 尚未执行`. Record current commit, Detector/cache hashes, validation backup paths, and unchecked rows for Today Scan, Chart Review YES, Chart Review NO, valid save, invalid reasons, legacy migration, history count and prohibited capabilities.

- [ ] **Step 2: Run complete automated tests**

Run: `pytest tests/pattern_finder -q`

Expected: PASS; record exact pass count and timestamp.

Run: `pytest -q`

Expected: PASS; record exact pass count and timestamp.

- [ ] **Step 3: Run Streamlit and complete the real workflow**

Run: `python -m streamlit run app/Home.py --server.headless=true --server.port=8501`

Verify and record:

1. 首页、今日扫描、图表复核主要文字为中文。
2. 两个形态选择器都只有“平底形态”。
3. YES 明确评价识别区间；NO 明确寻找漏报。
4. “像 / 勉强像 / 不像”明确针对平底形态。
5. 只有 Flat Base V1 的 11 个新标签可选。
6. 缺少必要标签或“其他”备注时不能保存。
7. 合法保存自动显示正确中文验证结论且只追加一行。
8. 三条现有 legacy 记录全部迁移、旧标签原样、重复运行不重复导入。
9. 页面不存在 Rounded Base、Compression、READY Detector 或 Score/Outcome/ML。

- [ ] **Step 4: GREEN — complete evidence and rerun immutability gates**

Only after every row has actual evidence, set report to `GREEN — PASS`. Re-run the Detector SHA-256 and cache aggregate commands from Task 10. Run `git status --short` and confirm it contains no Detector/cache modifications.

- [ ] **Step 5: Prepare the mandatory 用户交付说明**

Before the final response, prepare a `# 用户交付说明` section using exactly these seven headings:

1. `## 1. 这次改了什么` — explain in ordinary Chinese what changed, why it changed, and the practical difference; do not substitute filenames, functions or commits for the explanation.
2. `## 2. 我怎么使用` — include the Windows command `python -m streamlit run app/Home.py --server.headless=true --server.port=8501`, the page to enter, the control to click, what to select, and the complete action order.
3. `## 3. 我怎么人工测试` — provide at most 10 checklist items in ordinary user-operation language. Organize them in this order: what to open; where to click; what to select; what should normally appear; what incorrect action to try deliberately; how the system should warn or block it. A user who does not understand code must be able to follow every step. Commit inspection, diff inspection, TODO/TBD searches, function names, code files and internal test structure belong only under development verification and must not replace user manual testing.
4. `## 4. 如果失败代表什么` — distinguish environment, data, code and Detector failures, including page startup, missing data, Data Quality FAIL and abnormal UI behavior where applicable.
5. `## 5. 给 ChatGPT 的改良材料` — specify screenshots and provide a copy-ready summary. For Pattern Detector work the summary includes `pattern_type`, `detector_version`, sample count, Computer YES/NO, Human 像/勉强像/不像, 一致命中, 一致排除, 疑似误报, 疑似漏报, 边界案例 and the most common reason tags. Write `样本不足` for every unavailable sample or category.
6. `## 6. 最值得 ChatGPT 分析的案例` — select the most typical correct case, clearest false positive, clearest false negative, representative borderline case and threshold-near case. For non-Detector work, select the cases most likely to expose the changed function. State when a category has no case.
7. `## 7. 最终状态` — report `BLOCKER`, `HIGH`, `AUTOMATED_TEST`, `MANUAL_TEST_REQUIRED`, and, when manual testing is required, `READY_FOR_USER_TEST`.

Do not state final PASS before the user completes required manual testing. Record only automated status, known risks and readiness for user testing.

- [ ] **Step 6: Commit Task 11 evidence**

```powershell
git add -- docs/superpowers/validation/2026-08-10-pattern-review-framework-manual-acceptance.md
git commit -m "docs: record pattern review acceptance"
```

## Final Implementation Gate

Run and record these commands separately:

- `pytest tests/pattern_finder -q`
- `pytest -q`
- `git diff --check`
- `git status --short`

Implementation is ready for review only when all tests pass, Detector/cache hashes match, `flat_base.py` and cache are absent from the implementation diff, old `flat_base_validation.jsonl` is byte-identical, migrated count equals the nonblank legacy line count, rerun migration adds zero target records, no future Detector/Profile exists, and manual Streamlit acceptance is GREEN.

The final delivery is incomplete unless the response contains the mandatory `# 用户交付说明` with all seven fixed sections from Task 11 Step 5. The final section must include `BLOCKER`, `HIGH`, `AUTOMATED_TEST`, `MANUAL_TEST_REQUIRED`, and `READY_FOR_USER_TEST` whenever manual testing is required. Missing sections, missing copy-ready Pattern Detector statistics, omitted `样本不足` declarations, or claiming final PASS before the user completes required manual testing all fail this gate.

The manual-test section also fails this gate if it is written primarily as developer verification. It must use ordinary user-operation language and follow the sequence: open, click, select, expected visible result, deliberate incorrect action, expected warning or prevention. Commit/diff inspection, TODO/TBD searches, function names, code files and internal test structure may appear only under development verification.
