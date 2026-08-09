# Pattern Finder Milestone 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally runnable Streamlit shell with Today Scan, Chart Review, three deterministic OHLCV fixtures, and an interactive Plotly candlestick/volume chart.

**Architecture:** Keep UI code under `app/` and put reusable, deterministic behavior under a small `tv_quant.pattern_finder` package. The pages read only in-memory fixture objects; they do not download, scan, cache, score, predict, or persist anything.

**Tech Stack:** Python 3.14.2, frozen dataclasses, pandas 3.0.3, Streamlit 1.59.1, Plotly 6.9.0, pytest 9.1.1.

## Global Constraints

- Product phase and scope follow Product Blueprint V2.1.
- Detector math follows Detector Definition V1, but Milestone 1 implements no detectors.
- Use only local deterministic fixtures named `TEST_FLAT`, `TEST_ROUNDED`, and `TEST_READY`.
- Display daily candlesticks, volume, dates, Base Window, Support, and Resistance.
- Do not implement Futu access, universe scanning, caches, detectors, scoring, future outcomes, machine learning, optimization, brokers, orders, scheduling, or Phase 2 work.
- Production models must contain no Human Score, Rule Score, Shape Score, Outcome, future-window, or ML fields.
- Every production behavior starts with a test that is observed failing for the expected missing behavior.
- Full acceptance requires the existing 536-test baseline plus all Milestone 1 tests to pass on Python 3.14.2.

---

### Task 1: Compatible UI dependencies

**Files:**
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: existing Python 3.14 requirements, including `pyarrow==25.0.0`.
- Produces: importable `streamlit==1.59.1` and `plotly==6.9.0` without changing existing pins.

- [ ] **Step 1: Record the resolver evidence**

Run:

```powershell
py -3.14 -m pip install --dry-run -r requirements.txt streamlit==1.59.1 plotly==6.9.0
```

Expected: exit 0; no `ResolutionImpossible`; existing `pyarrow==25.0.0` remains satisfied.

- [ ] **Step 2: Add only the two direct dependencies**

Add these exact sorted requirement lines:

```text
plotly==6.9.0
streamlit==1.59.1
```

- [ ] **Step 3: Install and check the environment**

Run:

```powershell
py -3.14 -m pip install -r requirements.txt
py -3.14 -m pip check
py -3.14 -c "import plotly, streamlit; print(plotly.__version__, streamlit.__version__)"
```

Expected: all commands exit 0 and print `6.9.0 1.59.1`.

### Task 2: Minimal immutable models

**Files:**
- Create: `src/tv_quant/pattern_finder/__init__.py`
- Create: `src/tv_quant/pattern_finder/models.py`
- Create: `tests/pattern_finder/test_models.py`

**Interfaces:**
- Produces: `DailyBar` and `ChartFixture` frozen dataclasses.
- `DailyBar` fields: `timestamp_utc`, `open`, `high`, `low`, `close`, `volume`.
- `ChartFixture` fields: `symbol`, `pattern_label`, `bars`, `base_start`, `base_end`, `support`, `resistance`.

- [ ] **Step 1: Write failing model tests**

Test real construction and validation: UTC timestamps, positive finite OHLC, valid high/low relationships, non-negative volume, uppercase fixture symbols, at least 120 sorted bars, contained Base Window, and `support < resistance`. Assert the two exact public field sets contain no score, outcome, future-window, or ML fields.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
py -3.14 -m pytest tests/pattern_finder/test_models.py -q -p no:cacheprovider
```

Expected: collection fails because `tv_quant.pattern_finder.models` does not exist.

- [ ] **Step 3: Implement the smallest validated frozen dataclasses**

Use `@dataclass(frozen=True, slots=True)` and `__post_init__`. Do not add detector metrics, persistence identifiers, scores, labels from later phases, or computed outcomes.

- [ ] **Step 4: Verify GREEN**

Run the Task 2 pytest command again. Expected: all Task 2 tests pass.

### Task 3: Deterministic local OHLCV fixtures

**Files:**
- Create: `src/tv_quant/pattern_finder/fixtures.py`
- Create: `tests/pattern_finder/test_fixtures.py`

**Interfaces:**
- Consumes: `DailyBar`, `ChartFixture`.
- Produces: `load_fixture(symbol: str) -> ChartFixture` and `load_fixtures() -> tuple[ChartFixture, ...]`.

- [ ] **Step 1: Write failing fixture tests**

Require exact symbols `TEST_FLAT`, `TEST_ROUNDED`, `TEST_READY`; 160 strictly increasing UTC daily-business timestamps per symbol; deterministic repeated loads; valid OHLCV; non-flat volume series; and valid Base Window/Support/Resistance metadata.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
py -3.14 -m pytest tests/pattern_finder/test_fixtures.py -q -p no:cacheprovider
```

Expected: collection fails because `tv_quant.pattern_finder.fixtures` does not exist.

- [ ] **Step 3: Implement deterministic in-memory fixtures**

Generate three visually distinct 160-bar series from fixed arithmetic formulas. Do not call network, Futu, yfinance, a scanner, a detector, a cache, or the filesystem.

- [ ] **Step 4: Verify GREEN**

Run the Task 3 pytest command again. Expected: all Task 3 tests pass.

### Task 4: Plotly candlestick and volume figure

**Files:**
- Create: `src/tv_quant/pattern_finder/charts.py`
- Create: `tests/pattern_finder/test_charts.py`

**Interfaces:**
- Consumes: one `ChartFixture`.
- Produces: `build_candlestick_figure(fixture: ChartFixture) -> plotly.graph_objects.Figure`.

- [ ] **Step 1: Write failing chart tests**

Require one candlestick trace with literal OHLC/date values, one volume bar trace with literal volume values, a shaded Base Window, horizontal Support and Resistance lines, two vertically stacked rows, and interactive zoom controls with no range slider.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
py -3.14 -m pytest tests/pattern_finder/test_charts.py -q -p no:cacheprovider
```

Expected: collection fails because `tv_quant.pattern_finder.charts` does not exist.

- [ ] **Step 3: Implement the minimal Plotly figure**

Use `make_subplots(rows=2, cols=1, shared_xaxes=True)`, `go.Candlestick`, and `go.Bar`. Add only Base Window, Support, and Resistance annotations required by Milestone 1.

- [ ] **Step 4: Verify GREEN**

Run the Task 4 pytest command again. Expected: all Task 4 tests pass.

### Task 5: Streamlit UI shell and two pages

**Files:**
- Create: `app/Home.py`
- Create: `app/pages/1_Today_Scan.py`
- Create: `app/pages/2_Chart_Review.py`
- Create: `tests/pattern_finder/test_pages.py`

**Interfaces:**
- Consumes: `load_fixtures`, `load_fixture`, `build_candlestick_figure`.
- Produces: standard Streamlit multipage app reachable from `app/Home.py`.

- [ ] **Step 1: Write failing page tests**

Use `streamlit.testing.v1.AppTest.from_file` against all three scripts. Require no uncaught exceptions; Today Scan shows all three symbols and local-fixture status; Chart Review has a symbol selector with all three symbols and renders the Plotly figure. Assert rendered page text contains none of the forbidden scoring, outcome, future-window, or ML labels.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
py -3.14 -m pytest tests/pattern_finder/test_pages.py -q -p no:cacheprovider
```

Expected: fails because the page files do not exist.

- [ ] **Step 3: Implement the minimal pages**

Home describes the fixture-only Milestone 1 shell. Today Scan displays a small table of fixture metadata. Chart Review provides one selectbox and one Plotly chart. Do not add database writes, scoring controls, detector controls, downloads, or scheduling.

- [ ] **Step 4: Verify GREEN**

Run the Task 5 pytest command again. Expected: all Task 5 tests pass without Streamlit exceptions.

### Task 6: Milestone verification and delivery

**Files:**
- Modify only files introduced by Tasks 1–5 if verification finds a scoped defect.

**Interfaces:**
- Produces: test evidence, runnable local app, commits, pushed branch, and Pull Request.

- [ ] **Step 1: Run focused and complete tests**

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
py -3.14 -m pytest tests/pattern_finder -q -p no:cacheprovider
py -3.14 -m pytest tests -q -p no:cacheprovider
py -3.14 -m pip check
git diff --check
```

Expected: all commands exit 0; complete count equals 536 plus the new tests.

- [ ] **Step 2: Run a local Streamlit smoke test**

Start:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src'); py -3.14 -m streamlit run app/Home.py
```

Expected: server starts on `http://localhost:8501`, both pages are discoverable, and no network market-data request occurs.

- [ ] **Step 3: Review scope and Git diff**

Confirm no detector, scanner, Futu, cache, score, outcome, ML, broker, order, or scheduling implementation was added.

- [ ] **Step 4: Commit, push, and create the Pull Request**

Use focused commits, push `codex/phase1-pattern-finder`, and create a PR targeting `codex/v2-2a-data-foundation-impl`. Do not merge it.
