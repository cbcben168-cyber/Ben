# Pattern Finder Milestone 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic Futu OpenD QFQ daily-data path, per-symbol incremental cache, XNYS/data-quality checks, and real candlestick review for an eight-symbol pilot universe while preserving Milestone 1 fixture mode.

**Architecture:** Keep live I/O behind small Pattern Finder services and reuse the existing paginated, atomic Futu CSV updater. Store one ignored CSV per pilot symbol under a QFQ-specific directory, derive expected sessions from `exchange_calendars` XNYS, and let Streamlit read cache by default; only an explicit Futu refresh button may contact OpenD.

**Tech Stack:** Python 3.14.2, pandas 3.0.3, exchange-calendars 4.13.2, futu-api 10.9.x, Streamlit 1.59.1, Plotly 6.9.0, pytest 9.1.1.

## Global Constraints

- Pilot universe is exactly `AAPL`, `MSFT`, `NVDA`, `AMZN`, `META`, `GOOGL`, `JPM`, and `XOM`.
- Daily Futu requests use `KLType.K_DAY`, `AuType.QFQ`, and regular sessions only.
- Cache root is `data/raw/pattern_finder/qfq`; one CSV is stored per symbol and remains ignored by Git.
- Existing SPY/QQQ downloader behavior remains the default for callers outside Pattern Finder.
- XNYS sessions are authoritative; never forward-fill missing sessions.
- Streamlit keeps Fixture mode and adds Cache/Futu behavior without automatic network calls on page load.
- Do not implement Flat/Rounded/Compression/READY detectors, Candidate Scanner, scoring, ML, future outcomes, IBKR, options, brokers, orders, webhooks, or full-universe scanning.
- Every production behavior starts with a test observed failing for the expected reason.

---

### Task 1: Pilot universe and compatible Futu boundary

**Files:**
- Create: `src/tv_quant/pattern_finder/universe.py`
- Modify: `src/tv_quant/futu_downloader.py`
- Create: `tests/pattern_finder/test_universe.py`
- Modify: `tests/test_futu_downloader.py`

**Interfaces:**
- Produces: `PILOT_SYMBOLS: tuple[str, ...]` and `futu_code(symbol: str) -> str`.
- Extends: `futu_to_standardized`, `download_futu_daily`, and `update_futu_csv` with keyword-only `allowed_tickers: AbstractSet[str] | None = None`; `None` preserves the legacy `SPY/QQQ` allowlist.

- [ ] **Step 1: Write failing universe and downloader tests**

Require exact pilot order, reject non-pilot symbols, prove `US.AAPL` converts when `allowed_tickers={"AAPL"}`, prove symbol mismatch still fails, and prove calls without the new argument still reject AAPL.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
py -3.14 -m pytest tests/pattern_finder/test_universe.py tests/test_futu_downloader.py -q -p no:cacheprovider
```

Expected: FAIL because the pilot module and opt-in allowlist do not exist.

- [ ] **Step 3: Implement the minimal boundary**

Normalize all allowlist entries to uppercase, require exactly the requested ticker after conversion, and pass the allowlist through pagination/update without changing default callers.

- [ ] **Step 4: Verify GREEN**

Run the Task 1 pytest command again. Expected: all selected tests pass.

### Task 2: XNYS-aware data quality

**Files:**
- Create: `src/tv_quant/pattern_finder/data_quality.py`
- Create: `tests/pattern_finder/test_data_quality.py`

**Interfaces:**
- Produces: frozen `DataQualityReport(symbol, expected_latest_session, first_session, last_session, missing_sessions, warnings)` with `passed` derived from no missing/stale sessions.
- Produces: `latest_complete_xnys_session(as_of_utc: datetime) -> date`.
- Produces: `assess_symbol_data(data: pd.DataFrame, symbol: str, as_of_utc: datetime) -> DataQualityReport`.

- [ ] **Step 1: Write failing calendar and quality tests**

Use literal XNYS expectations around the 2026-07-03 Independence Day closure. Require a pre-close timestamp to use the prior session, a post-close timestamp to use the current session, and reports to expose missing, stale, symbol-mismatch, duplicate, unsorted, invalid OHLC, and negative-volume failures without forward filling.

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.14 -m pytest tests/pattern_finder/test_data_quality.py -q -p no:cacheprovider
```

Expected: collection FAIL because the module does not exist.

- [ ] **Step 3: Implement minimal XNYS assessment**

Call the existing strict `validate_ohlcv` first, compare normalized bar dates to `XNYS.sessions_in_range`, and make staleness/missing sessions visible. Do not modify or fill source data.

- [ ] **Step 4: Verify GREEN**

Run the Task 2 pytest command again. Expected: all selected tests pass.

### Task 3: Per-symbol incremental QFQ cache

**Files:**
- Create: `src/tv_quant/pattern_finder/cache.py`
- Create: `tests/pattern_finder/test_cache.py`

**Interfaces:**
- Produces: `DEFAULT_CACHE_ROOT`, frozen `CacheEntry`, `cache_path`, `load_cache_entry`, `refresh_cache_entry`, and `cache_status_rows`.
- `refresh_cache_entry` accepts a quote context plus explicit Futu enum values; first load requests 550 calendar days, subsequent loads overlap 10 calendar days from the last cached session, and end at the latest complete XNYS session.

- [ ] **Step 1: Write failing cache tests**

Require one path per symbol under `qfq`, exact initial/incremental ranges, QFQ/K_DAY propagation, deterministic merge with incoming correction winning, atomic preservation on download/quality failure, and status rows for missing/pass/fail caches.

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.14 -m pytest tests/pattern_finder/test_cache.py -q -p no:cacheprovider
```

Expected: collection FAIL because the cache module does not exist.

- [ ] **Step 3: Implement the smallest cache service**

Delegate pagination and atomic replacement to `update_futu_csv`; validate the merged frame in `before_replace`; return row counts and quality status. Do not write cache metadata or any detector output.

- [ ] **Step 4: Verify GREEN**

Run the Task 3 pytest command again. Expected: all selected tests pass.

### Task 4: Explicit OpenD pilot refresh service

**Files:**
- Create: `src/tv_quant/pattern_finder/futu_service.py`
- Create: `tests/pattern_finder/test_futu_service.py`

**Interfaces:**
- Produces: `refresh_pilot_universe(cache_root, as_of_utc, host="127.0.0.1", port=11111) -> tuple[CacheEntry, ...]`.
- Uses quote-only `OpenQuoteContext`, validates logged-in READY state, checks historical quota before each symbol, closes the context in `finally`, and never imports a trade context.

- [ ] **Step 1: Write failing service tests**

With a complete fake quote context, require all eight symbols in fixed order, context close on success/failure, explicit unavailable errors, quota-policy propagation, and literal K_DAY/QFQ values passed to the cache layer.

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.14 -m pytest tests/pattern_finder/test_futu_service.py -q -p no:cacheprovider
```

Expected: collection FAIL because the service module does not exist.

- [ ] **Step 3: Implement explicit refresh only**

Import the Futu SDK lazily, direct SDK logs to ignored `logs/futu_sdk_appdata`, open only the quote connection, and produce actionable Chinese errors for OpenD/login/quota failures.

- [ ] **Step 4: Verify GREEN**

Run the Task 4 pytest command again. Expected: all selected tests pass.

### Task 5: Real-series charts and Streamlit modes

**Files:**
- Modify: `src/tv_quant/pattern_finder/models.py`
- Modify: `src/tv_quant/pattern_finder/charts.py`
- Modify: `app/Home.py`
- Modify: `app/pages/1_Today_Scan.py`
- Modify: `app/pages/2_Chart_Review.py`
- Modify: `tests/pattern_finder/test_models.py`
- Modify: `tests/pattern_finder/test_charts.py`
- Modify: `tests/pattern_finder/test_pages.py`

**Interfaces:**
- Produces: frozen `ChartSeries(symbol, label, bars)` and `chart_series_from_frame`.
- `build_candlestick_figure` accepts either a fixture or real series; real series renders only daily OHLC and volume, while fixture overlays remain unchanged.
- Pages expose `Fixture` and `Cache / Futu` source choices. Cache view never contacts OpenD; an explicit refresh button does.

- [ ] **Step 1: Write failing model/chart/page tests**

Require literal cached AAPL OHLCV in the chart, fixture overlays unchanged, no overlays invented for real data, eight-symbol cache status table, cache-empty guidance, a refresh button, and no forbidden detector/scanner/score/future/ML labels.

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.14 -m pytest tests/pattern_finder/test_models.py tests/pattern_finder/test_charts.py tests/pattern_finder/test_pages.py -q -p no:cacheprovider
```

Expected: FAIL because real chart series and source modes do not exist.

- [ ] **Step 3: Implement minimal UI behavior**

Use `st.segmented_control`, bounded `st.cache_data` for cache reads, an explicit button plus spinner/status for Futu refresh, `st.dataframe(..., hide_index=True, width="stretch")`, and the existing Plotly candlestick/volume rendering. Do not automatically connect on rerun.

- [ ] **Step 4: Verify GREEN**

Run the Task 5 pytest command again. Expected: all selected tests pass without Streamlit exceptions.

### Task 6: Verification and delivery

**Files:**
- Modify only Milestone 2 files if verification reveals a scoped defect.

**Interfaces:**
- Produces: focused/full test evidence, clean diff evidence, optional live OpenD smoke evidence, commits, pushed branch, and a Draft PR.

- [ ] **Step 1: Run focused and full automated verification**

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$env:PYTHONDONTWRITEBYTECODE = '1'
py -3.14 -m pytest tests/pattern_finder tests/test_futu_downloader.py tests/test_futu_quota.py -q -p no:cacheprovider
py -3.14 -m pytest tests -q -p no:cacheprovider
py -3.14 -m pip check
git diff --check
```

If the known untracked Streamlit skill causes the only workspace failure, repeat full pytest from a clean `git archive HEAD` snapshot and report both results without deleting the user's directory.

- [ ] **Step 2: Run Streamlit smoke test**

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
py -3.14 -m streamlit run app/Home.py --server.headless=true --server.port=8501
```

Expected: server starts, Fixture works, Cache/Futu mode loads without automatic OpenD access, and Chart Review can render cached real bars.

- [ ] **Step 3: Attempt live OpenD smoke test**

If `127.0.0.1:11111` is reachable and logged in, refresh the pilot cache and verify at least one symbol against Futu response and XNYS quality. Otherwise record an explicit manual-test blocker; do not weaken tests.

- [ ] **Step 4: Review scope, commit, push, and open Draft PR**

Confirm no prohibited implementation or cache data is tracked. Push `codex/phase1-pattern-finder-m2`, create a Draft PR targeting `codex/v2-2a-data-foundation-impl`, and stop at `MILESTONE_2_READY_FOR_MANUAL_TEST`.
