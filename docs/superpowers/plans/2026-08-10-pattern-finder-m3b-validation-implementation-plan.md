# Pattern Finder Phase 1 Milestone 3B Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the real-stock Flat Base sample safely and add append-only three-label manual validation without changing Detector Definition V1.

**Architecture:** Keep the frozen detector untouched. Add a static diversified universe registry, an append-only JSONL validation store, pure scan-row enrichment/filtering helpers, and a quota-gated expansion service with a small CLI. Streamlit pages remain thin renderers over these tested domain functions.

**Tech Stack:** Python 3.14.2, pandas 3.0.3, numpy 2.5.1, Streamlit 1.59.1, Plotly 6.9.0, pytest 9.1.1, Futu OpenD QFQ daily history.

## Global Constraints

- Do not modify `src/tv_quant/pattern_finder/flat_base.py`.
- `PATTERN_DETECTOR_VERSION` remains `phase1-v1`.
- Base Length remains 25–90; Base Depth `<= 0.18`; Bottom Tolerance `<= 0.04`; Bottom Tests `>= 2`; `abs(Normalized Slope) <= 0.0015`.
- Preserve Detector Definition V1 resistance, pivot-low, ATR14, and candidate preference rules.
- Human labels are exactly `像`, `勉强像`, and `不像`; no numeric human score.
- Real validation records append to JSONL and never overwrite history.
- Keep all real cache and validation files under ignored `data/` paths.
- Stop safely on Futu login, permission, quota, or data-quality failure.
- Do not implement Rounded Base, Compression, READY, Rule Score, Shape Model, Outcome Model, ML, future-return labels, Optuna, Image AI, IBKR, brokers, orders, webhooks, or automatic trading.
- Preserve the user's untracked `.agents/skills/developing-with-streamlit` item and never stage it.

## File Map

- Modify `src/tv_quant/pattern_finder/universe.py`: M3B universe metadata and symbol allowlist.
- Create `src/tv_quant/pattern_finder/validation.py`: validation record schema, JSONL persistence, latest-record lookup.
- Create `src/tv_quant/pattern_finder/review.py`: pure scan-row enrichment and seven-way filtering.
- Modify `src/tv_quant/pattern_finder/cache.py`: scan explicit symbol sequences and list cached symbols.
- Modify `src/tv_quant/pattern_finder/futu_service.py`: safe staged expansion with quota snapshots and partial-result reporting.
- Create `scripts/expand_m3b_universe.py`: command-line entry for targets 25, 50, and 100.
- Modify `app/pages/1_Today_Scan.py`: all-cache scan, validation join, filter, human columns.
- Modify `app/pages/2_Chart_Review.py`: cached-symbol review form and append-only save.
- Create `tests/pattern_finder/test_validation.py` and `test_review.py`.
- Modify `tests/pattern_finder/test_universe.py`, `test_cache.py`, `test_futu_service.py`, `test_pages.py`, and `test_flat_base.py`.

---

### Task 1: Freeze Detector Contract and Add Diversified Universe

**Files:**
- Modify: `tests/pattern_finder/test_flat_base.py:1-159`
- Modify: `tests/pattern_finder/test_universe.py:1-25`
- Modify: `src/tv_quant/pattern_finder/universe.py:1-20`

**Interfaces:**
- Produces `UniverseMember(symbol: str, sector: str, volatility_bucket: str)`.
- Produces `M3B_UNIVERSE: tuple[UniverseMember, ...]` and `M3B_SYMBOLS: tuple[str, ...]`.
- Keeps `PILOT_SYMBOLS` unchanged for compatibility.
- Extends `futu_code(symbol: str) -> str` to accept only `M3B_SYMBOLS`.

- [ ] **Step 1: Write failing frozen-contract and universe tests**

```python
from tv_quant.pattern_finder.flat_base import (
    BOTTOM_TOLERANCE_PCT,
    MAX_ABS_NORMALIZED_SLOPE,
    MAX_BASE_DEPTH_PCT,
    MAX_BASE_LENGTH,
    MIN_BASE_LENGTH,
    MIN_BOTTOM_TESTS,
    PATTERN_DETECTOR_VERSION,
)


def test_m3b_keeps_phase1_v1_detector_contract_frozen() -> None:
    assert PATTERN_DETECTOR_VERSION == "phase1-v1"
    assert (MIN_BASE_LENGTH, MAX_BASE_LENGTH) == (25, 90)
    assert MAX_BASE_DEPTH_PCT == 0.18
    assert BOTTOM_TOLERANCE_PCT == 0.04
    assert MIN_BOTTOM_TESTS == 2
    assert MAX_ABS_NORMALIZED_SLOPE == 0.0015


def test_m3b_universe_has_100_unique_diversified_common_stocks() -> None:
    assert len(M3B_UNIVERSE) == 100
    assert len(set(M3B_SYMBOLS)) == 100
    assert set(PILOT_SYMBOLS) <= set(M3B_SYMBOLS)
    assert {member.sector for member in M3B_UNIVERSE} >= {
        "Technology", "Semiconductor", "Financial", "Energy",
        "Health Care", "Consumer", "Industrial",
    }
    assert {member.volatility_bucket for member in M3B_UNIVERSE} == {
        "低", "中", "高"
    }
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$env:PYTHONDONTWRITEBYTECODE = '1'
py -3.14 -m pytest tests/pattern_finder/test_flat_base.py tests/pattern_finder/test_universe.py -q -p no:cacheprovider
```

Expected: frozen detector assertions pass; universe imports fail because `M3B_UNIVERSE` and `M3B_SYMBOLS` do not exist.

- [ ] **Step 3: Implement the literal universe registry**

Use this exact sector membership; generate `UniverseMember` values in the displayed sector order and member order:

```python
M3B_SECTOR_SYMBOLS = {
    "Technology": ("AAPL", "MSFT", "ORCL", "CRM", "ADBE", "NOW", "IBM", "INTU", "PANW", "CSCO"),
    "Semiconductor": ("NVDA", "AMD", "AVGO", "QCOM", "TXN", "MU", "AMAT", "LRCX", "KLAC", "INTC"),
    "Financial": ("JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "SCHW", "AXP", "COF", "USB", "PNC"),
    "Energy": ("XOM", "CVX", "COP", "SLB", "EOG", "OXY", "MPC", "PSX", "VLO", "HAL"),
    "Health Care": ("JNJ", "UNH", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "AMGN", "GILD", "CVS", "BMY"),
    "Consumer": ("AMZN", "WMT", "COST", "HD", "LOW", "TGT", "MCD", "SBUX", "NKE", "DIS", "PG", "KO", "PEP", "PM", "MO", "TSLA"),
    "Industrial": ("CAT", "DE", "HON", "GE", "RTX", "BA", "UPS", "FDX", "LMT", "NOC", "MMM", "ETN", "EMR", "CSX", "UNP"),
    "Communication": ("GOOGL", "META", "NFLX", "TMUS", "VZ", "T", "CMCSA"),
    "Utilities": ("NEE", "DUK", "SO", "AEP", "EXC"),
    "Real Estate": ("PLD", "AMT", "SPG"),
}

HIGH_VOLATILITY_SYMBOLS = frozenset({
    "NVDA", "AMD", "MU", "INTC", "TSLA", "META", "NFLX", "BA",
    "OXY", "COF", "PANW", "CRM", "ADBE", "AMZN", "NKE", "TGT",
    "HAL", "SLB", "LRCX", "AMAT",
})
LOW_VOLATILITY_SYMBOLS = frozenset({
    "JNJ", "PG", "KO", "PEP", "WMT", "COST", "VZ", "T", "IBM",
    "MRK", "PFE", "ABBV", "MCD", "MO", "PM", "NEE", "DUK", "SO",
    "AEP", "EXC",
})
```

Construct the tuple at import time with no network calls. In `UniverseMember.__post_init__`, reject blank symbols, sectors, and volatility values outside `{"低", "中", "高"}`. Update `futu_code` to validate against `M3B_SYMBOLS`, while tests continue asserting arbitrary codes are rejected.

- [ ] **Step 4: Verify GREEN and commit**

Run the Step 2 command. Expected: all selected tests pass.

```powershell
git add tests/pattern_finder/test_flat_base.py tests/pattern_finder/test_universe.py src/tv_quant/pattern_finder/universe.py
git commit -m "feat: add diversified M3B stock universe"
```

---

### Task 2: Append-Only Manual Validation Store

**Files:**
- Create: `tests/pattern_finder/test_validation.py`
- Create: `src/tv_quant/pattern_finder/validation.py`

**Interfaces:**
- Produces `FlatBaseValidation` frozen dataclass with the exact persisted fields from the design.
- Produces `build_validation(scan_row, scan_as_of_date, human_label, reason_tags, note, recorded_at_utc) -> FlatBaseValidation`.
- Produces `append_validation(path, record) -> None`.
- Produces `read_validation_history(path) -> tuple[FlatBaseValidation, ...]`.
- Produces `latest_validations(records) -> dict[tuple[str, str, str], FlatBaseValidation]` keyed by symbol, detector version, and scan date.

- [ ] **Step 1: Write failing schema and persistence tests**

```python
def test_validation_appends_history_and_selects_latest_record(tmp_path: Path) -> None:
    path = tmp_path / "flat_base_validation.jsonl"
    first = build_validation(SCAN_ROW, date(2026, 8, 7), "勉强像", ("宽幅震荡",), "first", RECORDED_1)
    second = build_validation(SCAN_ROW, date(2026, 8, 7), "不像", ("整体仍在下降",), "second", RECORDED_2)

    append_validation(path, first)
    append_validation(path, second)

    history = read_validation_history(path)
    assert history == (first, second)
    assert latest_validations(history)[("AAPL", "phase1-v1", "2026-08-07")] == second
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


@pytest.mark.parametrize("label", ["像", "勉强像", "不像"])
def test_only_three_human_labels_are_accepted(label: str) -> None:
    assert build_validation(SCAN_ROW, date(2026, 8, 7), label, (), "", RECORDED_1).human_label == label


def test_like_rejects_reason_tags_and_other_labels_reject_unknown_tags() -> None:
    with pytest.raises(ValueError, match="像.*原因"):
        build_validation(SCAN_ROW, date(2026, 8, 7), "像", ("底部太深",), "", RECORDED_1)
    with pytest.raises(ValueError, match="未知原因"):
        build_validation(SCAN_ROW, date(2026, 8, 7), "不像", ("参数需要优化",), "", RECORDED_1)
```

Also test all required diagnostics, trimmed note with maximum 280 characters, UTC `recorded_at_utc`, corrupted JSONL rejection with line number, and a missing file returning an empty tuple.

- [ ] **Step 2: Run test and verify RED**

```powershell
py -3.14 -m pytest tests/pattern_finder/test_validation.py -q -p no:cacheprovider
```

Expected: collection fails because `tv_quant.pattern_finder.validation` does not exist.

- [ ] **Step 3: Implement minimal validation domain and JSONL I/O**

Define these exact constants:

```python
DEFAULT_VALIDATION_PATH = Path(
    "data/processed/pattern_finder/manual_validation/flat_base_validation.jsonl"
)
HUMAN_LABELS = ("像", "勉强像", "不像")
REASON_TAGS = (
    "底部太深", "底部太短", "低点不稳定", "整体仍在下降", "整体斜率太大",
    "宽幅震荡", "阻力不清楚", "底部区间太宽", "其他",
)
MAX_NOTE_LENGTH = 280
```

`append_validation` must call `path.parent.mkdir(parents=True, exist_ok=True)` and open only with mode `"a"`, UTF-8, one JSON object plus newline. It must never read-modify-write the file. `read_validation_history` must raise `ValidationStoreError(f"invalid validation JSON at line {line_number}")` on malformed input.

- [ ] **Step 4: Verify GREEN and commit**

```powershell
py -3.14 -m pytest tests/pattern_finder/test_validation.py -q -p no:cacheprovider
git add tests/pattern_finder/test_validation.py src/tv_quant/pattern_finder/validation.py
git commit -m "feat: persist append-only Flat Base reviews"
```

---

### Task 3: Scan Cached M3B Symbols and Join Human Results

**Files:**
- Modify: `tests/pattern_finder/test_cache.py:143-260`
- Create: `tests/pattern_finder/test_review.py`
- Modify: `src/tv_quant/pattern_finder/cache.py:39-290`
- Create: `src/tv_quant/pattern_finder/review.py`

**Interfaces:**
- Produces `cached_symbols(cache_root, symbols=M3B_SYMBOLS) -> tuple[str, ...]` in universe order.
- Changes `flat_base_scan_rows(cache_root, as_of_utc, symbols=PILOT_SYMBOLS)` without changing the default eight-symbol behavior.
- Produces `attach_latest_validations(rows, history) -> tuple[dict[str, object], ...]`.
- Produces `filter_review_rows(rows, selected_filter) -> tuple[dict[str, object], ...]`.
- Produces `SCAN_FILTERS = ("全部", "Flat Base YES", "Flat Base NO", "未人工验证", "像", "勉强像", "不像")`.

- [ ] **Step 1: Write failing cache and review tests**

```python
def test_cached_symbols_returns_only_existing_m3b_files_in_universe_order(tmp_path: Path) -> None:
    for symbol in ("XOM", "AAPL", "JPM"):
        (tmp_path / f"{symbol}_daily.csv").write_text("placeholder", encoding="utf-8")
    assert cached_symbols(tmp_path) == ("AAPL", "JPM", "XOM")


def test_scan_accepts_explicit_symbol_subset_without_changing_pilot_default(tmp_path: Path) -> None:
    rows = flat_base_scan_rows(tmp_path, AS_OF, symbols=("AAPL", "XOM"))
    assert tuple(row["Symbol"] for row in rows) == ("AAPL", "XOM")
    assert len(flat_base_scan_rows(tmp_path, AS_OF)) == len(PILOT_SYMBOLS)


def test_review_filter_supports_all_required_states() -> None:
    enriched = attach_latest_validations(SCAN_ROWS, HISTORY)
    assert tuple(row["Symbol"] for row in filter_review_rows(enriched, "Flat Base YES")) == ("AAPL", "XOM")
    assert tuple(row["Symbol"] for row in filter_review_rows(enriched, "Flat Base NO")) == ("MSFT",)
    assert tuple(row["Symbol"] for row in filter_review_rows(enriched, "未人工验证")) == ("XOM",)
    assert tuple(row["Symbol"] for row in filter_review_rows(enriched, "像")) == ("AAPL",)
```

Also assert every enriched row has `Human Label`, `Reason Tags`, `Human Note`, and `Validation History Count`; invalid filter values raise `ValueError`.

- [ ] **Step 2: Run tests and verify RED**

```powershell
py -3.14 -m pytest tests/pattern_finder/test_cache.py tests/pattern_finder/test_review.py -q -p no:cacheprovider
```

Expected: imports/signatures fail because the new helpers do not exist.

- [ ] **Step 3: Implement pure symbol and review helpers**

`cached_symbols` checks only `cache_path(cache_root, symbol).exists()` and never parses or writes a CSV. `flat_base_scan_rows` iterates the supplied immutable tuple and retains the current data-quality gate and diagnostics.

`attach_latest_validations` derives the latest map from the supplied full history, then looks up `(Symbol, Detector Version, Base End)` because `Base End` is the scan/as-of date represented by the Detector-selected completed bar. For rows without a matching record, use `None`, empty tuple, empty note, and history count zero. Count all historical records for the same key so repeated reviews stay visible.

`filter_review_rows` uses exact equality and preserves input order; “全部” returns all rows.

- [ ] **Step 4: Verify GREEN and commit**

```powershell
py -3.14 -m pytest tests/pattern_finder/test_cache.py tests/pattern_finder/test_review.py -q -p no:cacheprovider
git add tests/pattern_finder/test_cache.py tests/pattern_finder/test_review.py src/tv_quant/pattern_finder/cache.py src/tv_quant/pattern_finder/review.py
git commit -m "feat: join and filter M3B review rows"
```

---

### Task 4: Quota-Gated Staged Universe Expansion

**Files:**
- Modify: `tests/pattern_finder/test_futu_service.py:1-135`
- Create: `tests/pattern_finder/test_expand_m3b_universe.py`
- Modify: `src/tv_quant/pattern_finder/futu_service.py:1-115`
- Create: `scripts/expand_m3b_universe.py`

**Interfaces:**
- Produces frozen `ExpansionResult(target_size, starting_count, completed_symbols, final_count, starting_quota, ending_quota, blocker)`.
- Produces `refresh_universe_to_target(target_size, cache_root, as_of_utc, ...) -> ExpansionResult`.
- CLI accepts only `--target-size 25|50|100`, optional `--cache-root`, host, and port.
- Keeps `refresh_pilot_universe` behavior and tests unchanged.

- [ ] **Step 1: Write failing staged-expansion tests**

```python
def test_expansion_downloads_only_missing_symbols_until_total_target(tmp_path: Path) -> None:
    seed_valid_cache(tmp_path, PILOT_SYMBOLS)
    result = refresh_universe_to_target(
        25,
        cache_root=tmp_path,
        as_of_utc=AS_OF,
        sdk=Sdk(quota_remaining=292),
        sleep=lambda _: None,
    )
    assert result.starting_count == 8
    assert len(result.completed_symbols) == 17
    assert result.final_count == 25
    assert result.blocker is None


def test_expansion_stops_at_daily_new_code_limit_and_reports_partial_success(tmp_path: Path) -> None:
    seed_valid_cache(tmp_path, PILOT_SYMBOLS)
    write_quota_history(tmp_path / "quota.jsonl", 24, AS_OF)
    result = refresh_universe_to_target(
        25,
        cache_root=tmp_path,
        as_of_utc=AS_OF,
        sdk=Sdk(quota_remaining=292),
        log_path=tmp_path / "quota.jsonl",
        sleep=lambda _: None,
    )
    assert len(result.completed_symbols) == 1
    assert result.final_count == 9
    assert result.blocker.startswith("FUTU_QUOTA_BLOCKER")
```

Also test targets outside `{25, 50, 100}`, remaining quota below 100, already-complete target causing zero downloads, post-download data-quality failure, context closure, pre/post quota capture, and CLI JSON output.

- [ ] **Step 2: Run tests and verify RED**

```powershell
py -3.14 -m pytest tests/pattern_finder/test_futu_service.py tests/pattern_finder/test_expand_m3b_universe.py -q -p no:cacheprovider
```

Expected: new expansion imports fail.

- [ ] **Step 3: Implement minimal safe expansion**

At startup, call `cached_symbols`; compute missing members in `M3B_SYMBOLS` order. Connect once and call `_validate_opend`. Before every new symbol, obtain `_quota_snapshot`, call existing `check_quota`, and append the existing pre log. After `refresh_cache_entry`, obtain the post snapshot and append success. Add a synthetic in-memory successful new-code record before planning the next symbol so the daily/rolling limits apply within the same process.

Catch only known login/quota/permission/data-quality exceptions, convert them to a visible blocker string, keep prior successful cache files, and stop the loop. Unexpected programmer errors must still raise.

The CLI prints one JSON object containing target, starting/final counts, completed symbols, starting/ending used and remaining quota, and blocker. It exits `0` only when `final_count >= target_size`; otherwise exit `2`.

- [ ] **Step 4: Verify GREEN and commit**

```powershell
py -3.14 -m pytest tests/pattern_finder/test_futu_service.py tests/pattern_finder/test_expand_m3b_universe.py -q -p no:cacheprovider
git add tests/pattern_finder/test_futu_service.py tests/pattern_finder/test_expand_m3b_universe.py src/tv_quant/pattern_finder/futu_service.py scripts/expand_m3b_universe.py
git commit -m "feat: add quota-safe M3B universe expansion"
```

---

### Task 5: Today Scan Human-Validation Filters

**Files:**
- Modify: `tests/pattern_finder/test_pages.py:1-155`
- Modify: `app/pages/1_Today_Scan.py:1-87`

**Interfaces:**
- Reads cache root from `PATTERN_FINDER_CACHE_ROOT`.
- Reads validation path from `PATTERN_FINDER_VALIDATION_PATH`, defaulting to `DEFAULT_VALIDATION_PATH`.
- Shows all existing cached M3B symbols and seven exact filter choices.

- [ ] **Step 1: Write failing Today Scan AppTest**

```python
def test_today_scan_filters_computer_and_human_states(tmp_path: Path, monkeypatch) -> None:
    seed_review_cache_and_jsonl(tmp_path, monkeypatch)
    app = _load("app/pages/1_Today_Scan.py")
    app.segmented_control[0].select("Cache / Futu").run()

    assert tuple(app.selectbox[0].options) == SCAN_FILTERS
    table = app.dataframe[0].value
    assert {"Human Label", "Reason Tags", "Detector Version"} <= set(table.columns)

    app.selectbox[0].select("未人工验证").run()
    assert tuple(app.dataframe[0].value["Symbol"]) == ("XOM",)
```

Also select YES, NO, 像, 勉强像, 不像; assert fixture mode is unchanged; assert no page text contains prohibited later-phase features.

- [ ] **Step 2: Run test and verify RED**

```powershell
py -3.14 -m pytest tests/pattern_finder/test_pages.py -q -p no:cacheprovider
```

Expected: filter and human columns are absent.

- [ ] **Step 3: Implement thin Today Scan rendering**

Cache only `flat_base_scan_rows` plus validation-history loading using bounded `st.cache_data`. Apply `attach_latest_validations` and `filter_review_rows` after cached loading. Use one `st.selectbox("Review filter", SCAN_FILTERS, key="today_scan_review_filter")`. Keep `st.dataframe(..., hide_index=True, width="stretch")` and add numeric `column_config` for depth and normalized slope only.

Keep the existing explicit pilot refresh button; do not expose 50/100 downloads through a browser click.

- [ ] **Step 4: Verify GREEN and commit**

```powershell
py -3.14 -m pytest tests/pattern_finder/test_pages.py -q -p no:cacheprovider
git add tests/pattern_finder/test_pages.py app/pages/1_Today_Scan.py
git commit -m "feat: filter Today Scan by M3B reviews"
```

---

### Task 6: Chart Review Three-Label Form

**Files:**
- Modify: `tests/pattern_finder/test_pages.py:1-220`
- Modify: `app/pages/2_Chart_Review.py:1-116`

**Interfaces:**
- Symbol selectbox uses `cached_symbols(cache_root)`.
- Form appends through `build_validation` and `append_validation` only on submit.
- Retains candlestick, volume, Base Window, Support, Resistance, and raw diagnostics.

- [ ] **Step 1: Write failing Chart Review AppTest**

```python
def test_chart_review_saves_only_three_label_validation_on_submit(tmp_path: Path, monkeypatch) -> None:
    cache_root, validation_path = seed_chart_review(tmp_path, monkeypatch)
    app = _load("app/pages/2_Chart_Review.py")
    app.segmented_control[0].select("Cache / Futu").run()

    assert tuple(app.segmented_control[1].options) == HUMAN_LABELS
    app.segmented_control[1].select("不像")
    app.pills[0].set_value(["整体仍在下降", "阻力不清楚"])
    app.text_area[0].input("下降趋势仍明显")
    app.button[0].click().run()

    history = read_validation_history(validation_path)
    assert len(history) == 1
    assert history[0].human_label == "不像"
    assert history[0].reason_tags == ("整体仍在下降", "阻力不清楚")
    assert "Validation saved" in _visible_text(app)
```

Also test: no label prevents write; “像” hides/rejects reasons; a normal rerun does not append; a second submit appends a second line; latest record and history count render; plot contains the existing three detector overlays and raw diagnostics.

- [ ] **Step 2: Run test and verify RED**

```powershell
py -3.14 -m pytest tests/pattern_finder/test_pages.py -q -p no:cacheprovider
```

Expected: human validation form widgets are absent.

- [ ] **Step 3: Implement the Streamlit form**

Use this widget shape:

```python
with st.form(f"flat_base_review_{selected_symbol}", clear_on_submit=True):
    human_label = st.segmented_control(
        "Human label",
        HUMAN_LABELS,
        default=None,
        required=True,
        key=f"human_label_{selected_symbol}",
    )
    reason_tags = st.pills(
        "Reason tags",
        REASON_TAGS,
        selection_mode="multi",
        disabled=human_label == "像",
        key=f"reason_tags_{selected_symbol}",
    )
    note = st.text_area(
        "Note",
        max_chars=MAX_NOTE_LENGTH,
        key=f"human_note_{selected_symbol}",
    )
    submitted = st.form_submit_button("Save validation", icon=":material/save:")
```

On submit, call `build_validation` with `flat_base.selected.base_end.date()` and `datetime.now(UTC)`, then `append_validation`. Clear only relevant Streamlit caches after successful append. Convert validation errors to `st.error`; never catch all exceptions around the write.

- [ ] **Step 4: Verify GREEN and commit**

```powershell
py -3.14 -m pytest tests/pattern_finder/test_pages.py -q -p no:cacheprovider
git add tests/pattern_finder/test_pages.py app/pages/2_Chart_Review.py
git commit -m "feat: add M3B Chart Review labels"
```

---

### Task 7: Real Futu Expansion, Evidence, and Delivery

**Files:**
- Do not modify Detector code.
- Generated ignored files: `data/raw/pattern_finder/qfq/*_daily.csv`
- Generated ignored logs: `logs/futu_quota.jsonl`
- Human records remain at `data/processed/pattern_finder/manual_validation/flat_base_validation.jsonl` when the user submits them.

**Interfaces:**
- Produces actual cache count, sector/volatility/environment distribution, YES/NO count, current quota, blocker status, and launch command.

- [ ] **Step 1: Verify tracked scope before real data access**

```powershell
git diff --name-only codex/phase1-pattern-finder-m3-flat-base...HEAD
git diff -- src/tv_quant/pattern_finder/flat_base.py
git status --short
```

Expected: no detector diff; `.agents/skills/developing-with-streamlit` remains untracked and unstaged.

- [ ] **Step 2: Run the first safe target**

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
py -3.14 scripts/expand_m3b_universe.py --target-size 25
```

Expected: JSON summary with final count at least 25, or exit 2 plus an explicit Futu blocker. Never retry a quota/permission blocker blindly.

- [ ] **Step 3: Re-query quota and conditionally attempt later targets**

Run `--target-size 50` only if the first result has no blocker and the service-calculated daily/rolling budget can reach 50. Run `--target-size 100` only under the same rule after 50. Otherwise stop at the safe actual count and report the blocker/limit.

- [ ] **Step 4: Generate deterministic sample evidence**

Run a read-only script using `cached_symbols`, `flat_base_scan_rows`, and `M3B_UNIVERSE` to print:

- actual symbol count;
- counts by sector and volatility bucket;
- market environment based on the latest 120 completed closes: return above `+10%` = 上涨, below `-10%` = 下跌, otherwise 横盘;
- Flat Base YES and NO totals;
- data-quality failures separately from NO.

This profiling never changes the Detector result.

- [ ] **Step 5: Run full verification**

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$env:PYTHONDONTWRITEBYTECODE = '1'
py -3.14 -m pytest tests/pattern_finder -q -p no:cacheprovider
py -3.14 -m pytest tests -q -p no:cacheprovider
py -3.14 -m pip check
git diff --check
```

Because the current checkout contains a user-owned untracked project skill, repeat the full suite in a clean temporary worktree when the local skill-contract test sees that item.

- [ ] **Step 6: Run Streamlit HTTP smoke**

```powershell
py -3.14 -m streamlit run app/Home.py --server.headless=true --server.port=8501
```

Verify HTTP 200, Today Scan filters, Chart Review real symbol selection, overlays, diagnostics, and append-only form save. Stop the smoke process after verification.

- [ ] **Step 7: Scope review and delivery commit**

```powershell
git status --short
git diff --stat codex/phase1-pattern-finder-m3-flat-base...HEAD
git log --oneline --decorate -8
```

Commit only tracked M3B code/tests/docs. Never stage `data/`, `logs/`, validation JSONL, or `.agents/skills/developing-with-streamlit`.

- [ ] **Step 8: Push with VPN-safe fallback and create Draft PR**

Try normal Git once. If the VPN route still blocks GitHub 443, use GitHub Git-data operations with remote parent `codex/phase1-pattern-finder-m3b-validation`, verify the exact changed-file list, and create a Draft PR targeting `codex/v2-2a-data-foundation-impl`.

The final report must include PR #5 merge status, M3B local and remote HEADs, current quota, actual universe size and distributions, YES/NO totals, launch command, validation path and workflow, all test results, BLOCKER/HIGH findings, and `MILESTONE_3B_READY_FOR_MANUAL_TEST`. Stop without starting Rounded Base.
