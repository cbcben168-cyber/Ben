# Pattern Finder Milestone 3A Flat Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, pure Flat Base detector and expose its raw diagnostics for the existing synthetic fixtures and eight-symbol Futu cache pilot.

**Architecture:** Keep detector math in a side-effect-free Pattern Finder module that consumes one validated OHLCV frame and returns an immutable result. A thin cache scanner enforces the existing XNYS/data-quality gate, while Today Scan and Chart Review only render detector output. Search every integer window from 25 through 90 days, then select one window with the frozen Flat Base preference order.

**Tech Stack:** Python 3.14.2, pandas 3.0.3, numpy 2.5.1, Streamlit 1.59.1, Plotly 6.9.0, pytest 9.1.1.

## Global Constraints

- `PATTERN_DETECTOR_VERSION = "phase1-v1"`.
- Candidate windows are every integer length from 25 through 90 trading days.
- Base depth is `(max(High) - min(Low)) / min(Low)` and must be at most `0.18`.
- Pivot lows use two bars on each side; bottom-zone tolerance is `0.04`; at least two bottom tests are required.
- Absolute close-regression slope divided by mean close must be at most `0.0015` per trading day.
- Resistance excludes T0 and uses the frozen 90th-percentile plus `1.5 * ATR14_T0` spike adjustment.
- ATR14 follows the repository's frozen Wilder convention: seed with the first 14 true ranges, then recurse.
- Candidate inclusion in Milestone 3A is data-quality PASS and Flat Base YES only.
- Do not implement Rounded Base, Compression, READY, breakout-like logic, scores, ML, future outcomes, brokers, orders, webhooks, or full-universe scanning.
- Every production behavior starts with a test observed failing for the expected reason.

---

### Task 1: Pure detector and synthetic fixtures

**Files:**
- Create: `src/tv_quant/pattern_finder/flat_base.py`
- Create: `tests/pattern_finder/test_flat_base.py`
- Modify: `src/tv_quant/pattern_finder/fixtures.py`

**Interfaces:**
- Produces frozen `FlatBaseWindow` raw diagnostics and frozen `FlatBaseResult` with the selected window plus all evaluated windows.
- Produces `detect_flat_base(data: pd.DataFrame) -> FlatBaseResult` with no I/O, clock, cache, or network dependency.

- [ ] **Step 1: Write failing detector tests**

Use literal synthetic OHLCV frames to require: clean positive, depth just above `0.18`, unstable lows, slope just above `0.0015`, resistance spike adjustment, deterministic multi-window selection, insufficient history rejection, source-frame immutability, and no future-bar dependence.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$env:PYTHONDONTWRITEBYTECODE = '1'
py -3.14 -m pytest tests/pattern_finder/test_flat_base.py -q -p no:cacheprovider
```

Expected: collection fails because `tv_quant.pattern_finder.flat_base` does not exist.

- [ ] **Step 3: Implement the minimal detector**

Validate standardized OHLCV without changing it; calculate Wilder ATR14; evaluate windows 25–90; find interior 2-left/2-right pivot lows; calculate depth, bottom zone, normalized slope, support, raw/quantile resistance and spike flag; apply the three hard gates; choose a deterministic selected window with bottom tests descending, depth ascending, absolute slope ascending, length descending, then encoded window id ascending.

- [ ] **Step 4: Verify GREEN**

Run the Task 1 pytest command again. Expected: all detector tests pass.

### Task 2: TEST_FLAT and eight-cache scanner

**Files:**
- Modify: `tests/pattern_finder/test_fixtures.py`
- Modify: `src/tv_quant/pattern_finder/cache.py`
- Modify: `tests/pattern_finder/test_cache.py`

**Interfaces:**
- Produces `flat_base_scan_rows(cache_root, as_of_utc) -> tuple[dict[str, object], ...]` in fixed `PILOT_SYMBOLS` order.
- Each row exposes Flat Base YES/NO, Base Length, Base Depth, Bottom Tests, Slope, support, resistance, detector version, and data-quality status.

- [ ] **Step 1: Write failing integration tests**

Require the production detector to classify `TEST_FLAT` as YES; prove labels do not control detection; require data-quality failures to produce NO without detector execution; and require fixed-order cache rows with literal detector columns.

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.14 -m pytest tests/pattern_finder/test_fixtures.py tests/pattern_finder/test_cache.py -q -p no:cacheprovider
```

Expected: new assertions fail because scanner integration does not exist.

- [ ] **Step 3: Implement minimal cache integration**

Reuse `load_cache_entry`, `load_standardized_csv`, and the existing quality report. Never refresh or write cache data during scanning.

- [ ] **Step 4: Verify GREEN**

Run the Task 2 pytest command again. Expected: all selected tests pass.

### Task 3: Today Scan and Chart Review

**Files:**
- Modify: `src/tv_quant/pattern_finder/charts.py`
- Modify: `app/pages/1_Today_Scan.py`
- Modify: `app/pages/2_Chart_Review.py`
- Modify: `tests/pattern_finder/test_charts.py`
- Modify: `tests/pattern_finder/test_pages.py`

**Interfaces:**
- `build_candlestick_figure` accepts an optional Flat Base result and draws overlays only when it is a YES candidate.
- Today Scan exposes `Flat Base`, `Base Length`, `Base Depth`, `Bottom Tests`, and `Slope` for fixture and cache modes.
- Chart Review displays selected Base Window, Support, Resistance, and raw diagnostics for Flat Base candidates.

- [ ] **Step 1: Write failing chart/page tests**

Require Flat Base overlays on `TEST_FLAT`, no detector overlays on non-candidates, exact Today Scan columns, literal diagnostic labels, eight cache rows, and absence of all prohibited later-phase fields.

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.14 -m pytest tests/pattern_finder/test_charts.py tests/pattern_finder/test_pages.py -q -p no:cacheprovider
```

Expected: new UI assertions fail because detector output is not rendered.

- [ ] **Step 3: Implement minimal rendering**

Keep the existing fixture/cache source control and explicit Futu refresh behavior. Add only raw Flat Base fields and overlays; do not add ranking or scores.

- [ ] **Step 4: Verify GREEN**

Run the Task 3 pytest command again. Expected: all selected tests pass without Streamlit exceptions.

### Task 4: Real-cache evidence and delivery

**Files:**
- Modify only Milestone 3A files if verification reveals a scoped defect.

**Interfaces:**
- Produces eight-symbol YES/NO evidence, focused/full test evidence, Streamlit manual-test instructions, a commit, pushed branch, and Draft PR.

- [ ] **Step 1: Scan the existing eight caches**

Run the pure detector through the quality-gated cache scanner and record every symbol's raw result. Do not contact Futu or modify cached CSVs.

- [ ] **Step 2: Run fresh verification**

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$env:PYTHONDONTWRITEBYTECODE = '1'
py -3.14 -m pytest tests/pattern_finder -q -p no:cacheprovider
py -3.14 -m pytest tests -q -p no:cacheprovider
py -3.14 -m pip check
git diff --check
```

- [ ] **Step 3: Run Streamlit smoke test**

```powershell
py -3.14 -m streamlit run app/Home.py --server.headless=true --server.port=8501
```

Verify Today Scan fixture/cache modes and Chart Review Flat Base overlays and raw diagnostics.

- [ ] **Step 4: Scope review, commit, push, Draft PR**

Confirm no prohibited implementation or cache CSV is tracked. Commit and push `codex/phase1-pattern-finder-m3-flat-base`, then open a Draft PR targeting `codex/v2-2a-data-foundation-impl` and stop at `MILESTONE_3A_READY_FOR_MANUAL_TEST`.
