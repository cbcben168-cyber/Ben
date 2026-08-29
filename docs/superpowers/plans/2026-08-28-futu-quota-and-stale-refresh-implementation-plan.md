# Futu Quota Authority and Stale-Cache Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the incorrect local 25/200/100 quota blockers with provider-returned rolling-seven-day quota authority and add a safe UI action that refreshes exactly the stale cached symbols.

**Architecture:** `futu_quota.py` becomes a small provider-quota decision module: known codes are always reusable and a new code is blocked only when provider `remain_quota` is zero. `futu_service.py` owns one generic ordered-symbol refresh operation plus stale-cache discovery; the Today Scan page calls it only after an explicit button click. Existing JSONL quota logs remain append-only audit evidence but no longer authorize or deny downloads.

**Tech Stack:** Python 3.14, dataclasses, Futu OpenAPI SDK, pandas, Streamlit, pytest, Streamlit AppTest.

**Spec:** `docs/superpowers/specs/2026-08-28-pattern-finder-m3d-review-workstation-design.md` section 3, plus the verified Futu historical-candlestick quota contract linked in project discussion.

## Global Constraints

- Never hard-code 300 as the account quota; `used_quota`, `remain_quota`, and `detail_list` returned by OpenD are authoritative.
- A code already present in `detail_list` remains refreshable even when `remain_quota == 0`.
- A code absent from `detail_list` is blocked only when `remain_quota <= 0`.
- Quota history is audit evidence only; it must not impose daily or local rolling limits.
- Only an explicit UI action may contact Futu OpenD.
- Refresh order is deterministic and input order is preserved.
- No change may weaken QFQ, K_DAY, cache-quality, or OpenD login validation.
- Every verified task is committed; the completed plan branch is pushed to
  GitHub and its remote commit is verified before handoff.

---

## File structure

- Modify `src/tv_quant/futu_quota.py`: provider-authoritative quota decision and audit record fields.
- Modify `src/tv_quant/pattern_finder/futu_service.py`: generic symbol refresh and stale-cache discovery.
- Modify `app/pages/1_Today_Scan.py`: explicit stale-cache refresh control and outcome text.
- Modify `tests/test_futu_quota.py`: exact provider-authority contract.
- Modify `tests/pattern_finder/test_futu_service.py`: generic/stale refresh and OpenD lifecycle tests.
- Modify `tests/pattern_finder/test_pages.py`: page button scope and no-implicit-network tests.

### Task 1: Make OpenD quota the only blocking authority

**Files:**
- Modify: `src/tv_quant/futu_quota.py`
- Test: `tests/test_futu_quota.py`

**Interfaces:**
- Consumes: `QuotaSnapshot(used_quota: int, remain_quota: int, detail_list: list[dict[str, Any]])`.
- Produces: `check_quota(snapshot: QuotaSnapshot, code: str) -> QuotaDecision`.
- Produces: `QuotaDecision(is_new_code: bool, known_code_count: int, server_used_quota: int, server_remain_quota: int)`.

- [ ] **Step 1: Replace local-limit tests with the provider contract**

```python
def test_known_code_is_allowed_when_provider_has_no_new_slots():
    decision = check_quota(quota(0, ("US.SPY",)), "us.spy")
    assert decision.is_new_code is False
    assert decision.server_remain_quota == 0


def test_new_code_is_allowed_with_one_provider_slot():
    decision = check_quota(quota(1, ("US.AAPL",)), "US.SPY")
    assert decision.is_new_code is True
    assert decision.known_code_count == 1


def test_new_code_is_blocked_only_when_provider_has_no_slots():
    with pytest.raises(QuotaPolicyError, match="no remaining historical-K-line quota"):
        check_quota(quota(0), "US.SPY")
```

- [ ] **Step 2: Run the focused test and verify the old policy fails**

Run: `pytest tests/test_futu_quota.py -q`

Expected: FAIL because `check_quota` still requires `now/history`, permits the wrong data model, and blocks below 100 rather than at zero.

- [ ] **Step 3: Implement the minimal provider-authoritative decision**

```python
@dataclass(frozen=True, slots=True)
class QuotaDecision:
    is_new_code: bool
    known_code_count: int
    server_used_quota: int
    server_remain_quota: int


def check_quota(snapshot: QuotaSnapshot, code: str) -> QuotaDecision:
    normalized = code.strip().upper()
    if not normalized:
        raise ValueError("code must be non-empty")
    known = {
        str(item.get("code", "")).strip().upper()
        for item in snapshot.detail_list
        if str(item.get("code", "")).strip()
    }
    is_new = normalized not in known
    if is_new and snapshot.remain_quota <= 0:
        raise QuotaPolicyError("no remaining historical-K-line quota for a new code")
    return QuotaDecision(
        is_new_code=is_new,
        known_code_count=len(known),
        server_used_quota=snapshot.used_quota,
        server_remain_quota=snapshot.remain_quota,
    )
```

Update `write_quota_log()` to store those four decision fields. Keep `read_quota_history()` so old audit files remain readable, but remove `_when()` and all policy use of local timestamps.

- [ ] **Step 4: Run quota tests**

Run: `pytest tests/test_futu_quota.py -q`

Expected: all tests PASS; no test mentions daily 25, rolling 200, or floor 100.

- [ ] **Step 5: Commit the quota policy**

```bash
git add src/tv_quant/futu_quota.py tests/test_futu_quota.py
git commit -m "fix: trust provider historical quota"
```

### Task 2: Add one generic exact-symbol refresh service

**Files:**
- Modify: `src/tv_quant/pattern_finder/futu_service.py`
- Test: `tests/pattern_finder/test_futu_service.py`

**Interfaces:**
- Consumes: Task 1 `check_quota(snapshot, code)`.
- Produces: `refresh_symbols(symbols: Iterable[str], *, cache_root, as_of_utc, host, port, log_path, sdk, sleep) -> tuple[CacheEntry, ...]`.
- Produces: `stale_cached_symbols(*, cache_root: str | Path, as_of_utc: datetime) -> tuple[str, ...]`.
- Preserves: `refresh_pilot_universe` with its existing keyword parameters as a wrapper over `PILOT_SYMBOLS`.

- [ ] **Step 1: Write failing service tests**

```python
def test_refresh_symbols_preserves_exact_order_and_allows_low_positive_quota(tmp_path):
    context = Context(remain_quota=1)
    entries = refresh_symbols(
        ("BAC", "WFC"),
        cache_root=tmp_path / "cache",
        as_of_utc=AS_OF,
        log_path=tmp_path / "quota.jsonl",
        sdk=Sdk(context),
        sleep=lambda _: None,
    )
    assert tuple(entry.symbol for entry in entries) == ("BAC", "WFC")
    assert tuple(request["code"] for request in context.requests) == ("US.BAC", "US.WFC")
    assert context.closed is True


def test_refresh_symbols_blocks_new_code_at_zero_and_closes_context(tmp_path):
    context = Context(remain_quota=0)
    with pytest.raises(QuotaPolicyError, match="no remaining"):
        refresh_symbols(("BAC",), cache_root=tmp_path / "cache", as_of_utc=AS_OF,
                        log_path=tmp_path / "quota.jsonl", sdk=Sdk(context), sleep=lambda _: None)
    assert context.requests == []
    assert context.closed is True


def test_stale_cached_symbols_returns_only_failed_quality_in_cache_order(tmp_path):
    for symbol, end in (("BAC", "2026-08-07"), ("WFC", "2026-08-27")):
        sessions = xcals.get_calendar("XNYS").sessions_window(end, -379)
        pd.DataFrame({
            "timestamp_utc": sessions,
            "ticker": symbol,
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1_000_000,
        }).to_csv(tmp_path / f"{symbol}_daily.csv", index=False)
    assert stale_cached_symbols(cache_root=tmp_path, as_of_utc=AS_OF) == ("BAC",)
```

- [ ] **Step 2: Run the focused service tests and verify failure**

Run: `pytest tests/pattern_finder/test_futu_service.py -q`

Expected: FAIL because the generic refresh and stale discovery functions do not exist and old call sites still pass local history into `check_quota`.

- [ ] **Step 3: Implement exact refresh and make the pilot a wrapper**

```python
def refresh_symbols(symbols: Iterable[str], **kwargs: object) -> tuple[CacheEntry, ...]:
    ordered = tuple(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols))
    if any(not symbol for symbol in ordered):
        raise ValueError("symbols must be normalized non-empty tickers")
    # Open one quote context, validate once, run pre-check/log/download/post-log
    # for each ordered symbol, and close in finally.


def refresh_pilot_universe(**kwargs: object) -> tuple[CacheEntry, ...]:
    return refresh_symbols(PILOT_SYMBOLS, **kwargs)


def stale_cached_symbols(*, cache_root: str | Path, as_of_utc: datetime) -> tuple[str, ...]:
    stale: list[str] = []
    for symbol in cached_symbols(cache_root):
        entry = load_cache_entry(symbol, cache_root=cache_root, as_of_utc=as_of_utc)
        if entry is None or not entry.quality.passed:
            stale.append(symbol)
    return tuple(stale)
```

Use the existing `_quota_snapshot`, `refresh_cache_entry`, `write_quota_log`, QFQ/K_DAY constants, error types, and `finally: context.close()` logic. Remove `read_quota_history` from service authorization paths.

- [ ] **Step 4: Run all Futu/cache tests**

Run: `pytest tests/test_futu_quota.py tests/pattern_finder/test_futu_service.py tests/pattern_finder/test_cache.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the reusable refresh service**

```bash
git add src/tv_quant/pattern_finder/futu_service.py tests/pattern_finder/test_futu_service.py
git commit -m "feat: refresh exact stale cache symbols"
```

### Task 3: Replace the pilot-only page action with stale-only refresh

**Files:**
- Modify: `app/pages/1_Today_Scan.py`
- Modify: `tests/pattern_finder/test_pages.py`

**Interfaces:**
- Consumes: Task 2 `stale_cached_symbols()` and `refresh_symbols()`.
- Produces: one explicit button labeled `从 Futu OpenD 刷新过期缓存（N）`.

- [ ] **Step 1: Write failing page tests**

```python
def test_today_scan_offers_exact_stale_refresh_without_implicit_network(tmp_path, monkeypatch):
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(futu_service, "refresh_symbols", lambda symbols, **_: calls.append(tuple(symbols)) or ())
    app = _load_today_scan_with_one_current_and_one_stale_cache(tmp_path, monkeypatch)
    assert calls == []
    button = next(item for item in app.button if item.label == "从 Futu OpenD 刷新过期缓存（1）")
    button.click().run()
    assert calls == [("BAC",)]
```

Also update the existing assertion that looks for `从 Futu OpenD 刷新试点数据`.

- [ ] **Step 2: Run the page test and verify failure**

Run: `pytest tests/pattern_finder/test_pages.py -q`

Expected: FAIL because the page still refreshes the fixed eight-stock pilot.

- [ ] **Step 3: Implement the explicit stale-only action**

Resolve `as_of` and `cache_root`, compute
`stale = stale_cached_symbols(cache_root=cache_root, as_of_utc=as_of)`, render
the count in the label, disable the button when empty, and call:

```python
entries = refresh_symbols(
    stale,
    cache_root=cache_root,
    as_of_utc=datetime.now(UTC),
)
```

On success clear Streamlit data caches and report both refreshed and remaining counts. On failure preserve the existing explicit error message and never claim partial completion without the returned entries.

- [ ] **Step 4: Run page and quota regression**

Run: `pytest tests/pattern_finder/test_pages.py tests/pattern_finder/test_futu_service.py tests/test_futu_quota.py -q`

Expected: PASS and the page test proves zero network calls before click.

- [ ] **Step 5: Commit the UI action**

```bash
git add app/pages/1_Today_Scan.py tests/pattern_finder/test_pages.py
git commit -m "feat: refresh stale Pattern Finder caches"
```

### Task 4: Full verification and Windows handoff

**Files:**
- No production file changes expected.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: verified patch/commit sequence and one Windows acceptance command path.

- [ ] **Step 1: Run the complete Pattern Finder suite**

Run: `pytest tests/pattern_finder tests/test_futu_quota.py -q`

Expected: all tests PASS.

- [ ] **Step 2: Run repository safety checks**

Run: `python -m compileall -q src app && git diff --check && git status --short`

Expected: compilation and diff checks succeed; only known user-owned runtime/progress files may remain untracked or modified.

- [ ] **Step 3: Apply on Windows and refresh the exact remaining set**

After the tested commits are applied to the Windows repository, start OpenD, open Today Scan, and click the single `刷新过期缓存（8）` action once. Verify the page reports zero remaining stale symbols and `get_history_kl_quota()` reports the provider values rather than a local daily limit.

- [ ] **Step 4: Record live evidence**

Capture: refreshed symbols `BAC,WFC,C,GS,MS,BLK,SCHW,AXP`; last session `2026-08-27`; data quality `PASS`; provider `used_quota/remain_quota`; no `daily 25`, `rolling 200`, or `below 100` blocker text.

- [ ] **Step 5: Push and verify the GitHub branch**

Run: `git push -u origin codex/pattern-finder-m3c-bcd-local-runtime`

Verify: `git ls-remote --heads origin codex/pattern-finder-m3c-bcd-local-runtime`
returns the same commit as `git rev-parse HEAD`.
