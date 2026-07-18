# Forward Factor Signal System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, read-only Futu option scanner that evaluates exactly 100 high-liquidity US underlyings, persists auditable FF signals locally, and prepares manual-trading notifications without ever creating broker orders.

**Architecture:** DuckDB is the local source of truth. Pure domain functions calculate tenors, liquidity, forward volatility, FF, signal status, and deterministic IDs; provider adapters fetch Futu/yfinance data; orchestration commits one scan transaction before notification and synchronization outboxes are consumed. A local FastAPI application records user-entered positions, while Gmail, Windows, Codex, Sites, and Obsidian remain one-way consumers.

**Tech Stack:** Python 3.12+, argparse, dataclasses, DuckDB, pandas, futu-api, yfinance, FastAPI, Jinja2, exchange-calendars, winotify, pytest; Sites dashboard with TypeScript, Cloudflare Workers, D1, and the Sites runtime.

## Global Constraints

- Never import, instantiate, or call a Futu trading context; only `OpenQuoteContext` is permitted.
- Never submit, modify, cancel, or infer a real order or fill.
- All internal timestamps are timezone-aware UTC; UI output also renders `America/New_York` and `Asia/Shanghai`.
- A candidate requires complete data, no earnings from scan time through T2 inclusive, both liquidity layers, and strict `FF > 0.20`; equality is not a signal.
- Select T1 in 55–65 DTE nearest 60 and T2 in 85–95 DTE nearest 90; ties choose the earlier date.
- Underlying liquidity is a strict 20-valid-session mean greater than 10,000 total option contracts; gaps and warmup fail closed.
- Every planned leg requires `bid > 0`, `ask > bid`, `mid > 0`, relative spread at most 0.15, open interest at least 500, and volume at least 50.
- The default recommendation is 4% of manually configured net liquidation value, configurable from 2% to 8% with a hard 8% cap; V1 always records `KELLY_UNAVAILABLE_INSUFFICIENT_SAMPLE`.
- Secrets are read only from `.env` or the system credential store, never logged or persisted.
- Writes to DuckDB are transactional and append-only for raw snapshots; correction records use `supersedes_id`.
- Sites and Obsidian are one-way replicas and cannot update DuckDB.
- Each implementation PR must run `python -m pytest tests -q -p no:cacheprovider` without deleting tests or weakening assertions.
- First Gmail delivery, first Obsidian write, Sites deployment, Task Scheduler registration, and any external publication require separate explicit approval.

## File Map

- `src/tv_quant/ff/models.py`: immutable domain records, enums, IDs, and serialized payload contracts.
- `src/tv_quant/ff/math.py`: IV normalization, tenor selection, forward variance, FF, and stable ranking.
- `src/tv_quant/ff/liquidity.py`: 20-session underlying gate and per-leg execution gate.
- `src/tv_quant/ff/database.py`: DuckDB migrations, transactions, repositories, outboxes, and active-run lock.
- `src/tv_quant/ff/futu_provider.py`: read-only option quote adapter and bounded retry metrics.
- `src/tv_quant/ff/earnings.py`: replaceable earnings provider and fail-closed classification.
- `src/tv_quant/ff/universe.py`: versioned 100-member registry and daily liquidity observations.
- `src/tv_quant/ff/scanner.py`: one-ticker evaluator and 100-symbol scan orchestration.
- `src/tv_quant/ff/reports.py`: dry-run and committed JSON/CSV/email/Codex artifacts.
- `src/tv_quant/ff/positions.py`: manual position state machine and exit reminders.
- `src/tv_quant/ff/web.py`: local FastAPI pages and manual position endpoints.
- `src/tv_quant/ff/notifications.py`: notification outbox consumers and fake providers.
- `src/tv_quant/ff/sync.py`: Sites and Obsidian sync consumers with independent checkpoints.
- `src/tv_quant/ff/scheduler.py`: NYSE calendar guard, health checks, and scheduler command generation.
- `src/tv_quant/cli.py`: add `scan`, `serve`, `sync`, and `health` commands while preserving existing commands.
- `src/tv_quant/ff/schema.sql`: complete local DuckDB schema and uniqueness constraints.
- `sites/ff-dashboard/`: owner-only Sites UI, protected `/api/sync`, and D1 migration.
- `tests/ff/`: pure unit and integration tests using fixed fixtures and fake providers.
- `tests/fixtures/ff/`: sanitized, immutable Futu and earnings fixtures.
- `scripts/register_ff_task.ps1`: idempotent Task Scheduler registration command, executed only after approval.

---

## PR 1 — Deterministic core, DuckDB, and read-only Futu provider

### Task 1: Domain contracts, deterministic IDs, tenor selection, and FF math

**Files:**
- Create: `src/tv_quant/ff/__init__.py`
- Create: `src/tv_quant/ff/models.py`
- Create: `src/tv_quant/ff/math.py`
- Test: `tests/ff/test_math.py`
- Test: `tests/ff/test_models.py`

**Interfaces:**
- Produces: `OptionLeg`, `TenorPair`, `FFResult`, `ScanStatus`, `make_signal_id(...)`, `normalize_iv(...)`, `select_tenors(...)`, `calculate_ff(...)`, and `rank_candidates(...)`.
- Consumes: only Python standard-library values; no provider or database types.

- [ ] **Step 1: Write failing domain and math tests**

```python
from datetime import date
from math import inf, sqrt

import pytest

from tv_quant.ff.math import calculate_ff, normalize_iv, rank_candidates, select_tenors
from tv_quant.ff.models import ScanStatus, make_signal_id


def test_select_tenors_uses_nearest_target_then_earlier_tie():
    expiries = [(date(2026, 9, 11), 55), (date(2026, 9, 21), 65),
                (date(2026, 10, 12), 86), (date(2026, 10, 20), 94)]
    pair = select_tenors(expiries)
    assert (pair.dte1, pair.dte2) == (55, 86)


@pytest.mark.parametrize("raw,unit,expected", [(14.794, "percent", 0.14794), (0.14794, "decimal", 0.14794)])
def test_normalize_iv_has_explicit_unit(raw, unit, expected):
    assert normalize_iv(raw, unit) == pytest.approx(expected)


def test_ff_threshold_is_strict_and_invalid_values_fail_closed():
    threshold = calculate_ff(0.30, sqrt(97 / 1200), 60, 90)
    assert threshold.ff == pytest.approx(0.20, abs=1e-10)
    assert threshold.status == ScanStatus.SCANNED
    assert calculate_ff(0.30, 0.20, 90, 60).status == ScanStatus.HOLD_INVALID_TENOR_ORDER
    assert calculate_ff(inf, 0.20, 60, 90).status == ScanStatus.HOLD_IV_UNIT_OR_RANGE_ERROR


def test_signal_id_and_ranking_are_deterministic():
    value = make_signal_id("ff-v1", date(2026, 7, 17), "SPY", date(2026, 9, 18), date(2026, 10, 16))
    assert value == make_signal_id("ff-v1", date(2026, 7, 17), "SPY", date(2026, 9, 18), date(2026, 10, 16))
    rows = [{"ticker": "QQQ", "ff": 0.3, "relative_spread": 0.1},
            {"ticker": "SPY", "ff": 0.3, "relative_spread": 0.1}]
    assert [row["ticker"] for row in rank_candidates(rows)] == ["QQQ", "SPY"]
```

- [ ] **Step 2: Verify the tests fail because the FF package does not exist**

Run: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests/ff/test_math.py tests/ff/test_models.py -q -p no:cacheprovider`

Expected: collection fails with `ModuleNotFoundError: No module named 'tv_quant.ff'`.

- [ ] **Step 3: Implement immutable contracts and pure functions**

Define `ScanStatus` with every stable status from the spec, dataclasses with `slots=True, frozen=True`, SHA-256 IDs over pipe-delimited canonical values, explicit IV units (`percent` or `decimal`), and this exact FF branch order:

```python
def calculate_ff(sigma_1: float, sigma_2: float, dte1: int, dte2: int) -> FFResult:
    if not all(math.isfinite(v) and v > 0 for v in (sigma_1, sigma_2)):
        return FFResult(None, None, None, ScanStatus.HOLD_IV_UNIT_OR_RANGE_ERROR)
    t1, t2 = dte1 / 365.0, dte2 / 365.0
    if t2 <= t1:
        return FFResult(None, None, None, ScanStatus.HOLD_INVALID_TENOR_ORDER)
    variance = ((sigma_2**2 * t2) - (sigma_1**2 * t1)) / (t2 - t1)
    if not math.isfinite(variance) or variance <= 0:
        return FFResult(variance, None, None, ScanStatus.HOLD_INVALID_FORWARD_VARIANCE)
    sigma_forward = math.sqrt(variance)
    if not math.isfinite(sigma_forward) or sigma_forward <= 0:
        return FFResult(variance, sigma_forward, None, ScanStatus.HOLD_INVALID_FORWARD_VOLATILITY)
    ff = (sigma_1 - sigma_forward) / sigma_forward
    status = ScanStatus.BUY_CANDIDATE if ff > 0.20 else ScanStatus.SCANNED
    return FFResult(variance, sigma_forward, ff, status)
```

- [ ] **Step 4: Run focused and full tests**

Run: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests/ff/test_math.py tests/ff/test_models.py -q -p no:cacheprovider`

Expected: all new tests pass.

Run: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`

Expected: existing 27 tests and all new tests pass.

- [ ] **Step 5: Commit the pure domain slice**

```powershell
git add src/tv_quant/ff/__init__.py src/tv_quant/ff/models.py src/tv_quant/ff/math.py tests/ff/test_math.py tests/ff/test_models.py
git commit -m "feat: add forward factor domain math"
```

### Task 2: Liquidity gates and structure construction

**Files:**
- Create: `src/tv_quant/ff/liquidity.py`
- Create: `src/tv_quant/ff/structures.py`
- Test: `tests/ff/test_liquidity.py`
- Test: `tests/ff/test_structures.py`

**Interfaces:**
- Consumes: `OptionLeg` and `ScanStatus` from Task 1.
- Produces: `check_underlying_liquidity(observations)`, `check_leg_liquidity(leg)`, `build_atm_call_calendar(...)`, and `build_double_calendar(...)`.

- [ ] **Step 1: Write boundary tests**

```python
def test_underlying_gate_requires_20_complete_sessions_and_strict_mean():
    assert check_underlying_liquidity([10_001] * 19).status == ScanStatus.HOLD_LIQUIDITY_WARMUP
    assert check_underlying_liquidity([10_000] * 20).passed is False
    assert check_underlying_liquidity([10_001] * 20).passed is True
    assert check_underlying_liquidity([10_001] * 10 + [None] + [10_001] * 9).status == ScanStatus.HOLD_LIQUIDITY_HISTORY_GAP


def test_leg_gate_checks_every_exact_threshold():
    leg = option_leg(bid=0.93, ask=1.07, open_interest=500, volume=50)
    assert check_leg_liquidity(leg).passed is True
    assert check_leg_liquidity(replace(leg, ask=1.09)).failed_fields == ("relative_spread",)


def test_double_calendar_never_substitutes_neighbor_delta():
    result = build_double_calendar(fixture_chain(missing_t2_put_same_strike=True))
    assert result.structure is None
    assert result.failed_fields == ("t2_put_same_strike",)
```

- [ ] **Step 2: Run focused tests and confirm missing symbols**

Run: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests/ff/test_liquidity.py tests/ff/test_structures.py -q -p no:cacheprovider`

Expected: collection fails on missing `tv_quant.ff.liquidity` and `tv_quant.ff.structures`.

- [ ] **Step 3: Implement both gates and exact structure rules**

Compute `mid = (bid + ask) / 2` and `relative_spread = (ask - bid) / mid`; return all failed field names in stable lexical order. Select ATM by absolute spot distance then lower strike. Select T1 deltas by absolute distance to `+0.35` or `-0.35`, then lower strike, and require T2 to use the exact selected strikes.

- [ ] **Step 4: Run focused and full tests**

Run the two test files, then the global pytest command. Expected: all pass.

- [ ] **Step 5: Commit liquidity and structure rules**

```powershell
git add src/tv_quant/ff/liquidity.py src/tv_quant/ff/structures.py tests/ff/test_liquidity.py tests/ff/test_structures.py
git commit -m "feat: enforce FF liquidity and structure rules"
```

### Task 3: DuckDB schema, transactional repository, and idempotent outboxes

**Files:**
- Create: `src/tv_quant/ff/schema.sql`
- Create: `src/tv_quant/ff/database.py`
- Test: `tests/ff/test_database.py`

**Interfaces:**
- Consumes: serialized Task 1 domain records.
- Produces: `FFDatabase(path)`, `migrate()`, `scan_transaction()`, `claim_scan()`, `commit_scan()`, `enqueue_notification()`, `enqueue_sync()`, and repository query methods.

- [ ] **Step 1: Write rollback and idempotency integration tests**

```python
def test_scan_transaction_rolls_back_every_business_and_outbox_row(tmp_path):
    db = FFDatabase(tmp_path / "ff.duckdb")
    db.migrate()
    with pytest.raises(RuntimeError):
        with db.scan_transaction() as tx:
            tx.insert_scan_run(scan_run("run-1"))
            tx.insert_signal(signal("sig-1"))
            tx.enqueue_notification(notification("mail-1", "sig-1"))
            raise RuntimeError("abort")
    assert db.count("scan_runs") == 0
    assert db.count("signals") == 0
    assert db.count("notifications") == 0


def test_deterministic_keys_prevent_duplicate_signal_and_outbox(tmp_path):
    db = migrated_database(tmp_path)
    persist_complete_scan(db, signal_id="sig-1", idempotency_key="mail:sig-1")
    persist_complete_scan(db, signal_id="sig-1", idempotency_key="mail:sig-1")
    assert db.count("signals") == 1
    assert db.count("notifications") == 1
```

- [ ] **Step 2: Verify tests fail on missing database module**

Run the focused file. Expected: missing `FFDatabase`.

- [ ] **Step 3: Create the complete schema and repository**

Create all 14 required tables: `strategy_versions`, `universe_versions`, `universe_members`, `option_liquidity_daily`, `option_snapshots`, `earnings_events`, `scan_runs`, `scan_results`, `signals`, `positions`, `position_legs`, `notifications`, `sync_outbox`, and `audit_events`. Use primary keys on immutable record IDs; unique keys on `(strategy_version, scan_date, ticker, t1_expiry, t2_expiry)`, notification `idempotency_key`, and sync `(target, record_id, updated_at_utc)`. Store decimals as `DOUBLE` and timestamps as `TIMESTAMPTZ`; prohibit string sentinels by repository validation.

- [ ] **Step 4: Add active-run takeover tests and implementation**

Test that a second active run for the same logical US session is rejected, while an expired lease is taken over with an `audit_events` row. Implement compare-and-set semantics inside a DuckDB transaction.

- [ ] **Step 5: Run focused and full tests**

Run the database test file, then the global pytest command. Expected: all pass.

- [ ] **Step 6: Commit storage core**

```powershell
git add src/tv_quant/ff/schema.sql src/tv_quant/ff/database.py tests/ff/test_database.py
git commit -m "feat: add transactional FF storage"
```

### Task 4: Read-only Futu provider and quota telemetry

**Files:**
- Create: `src/tv_quant/ff/futu_provider.py`
- Create: `tests/fixtures/ff/futu_option_chain.json`
- Test: `tests/ff/test_futu_option_provider.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: Futu SDK objects only behind injected `quote_context_factory`.
- Produces: `FutuOptionProvider`, `ProviderMetrics`, `get_expiries(ticker)`, `get_option_snapshot(ticker, expiry)`, and `get_underlying_option_volume(ticker)`.

- [ ] **Step 1: Write fake-context tests proving read-only behavior**

```python
def test_provider_uses_only_quote_context_and_normalizes_iv():
    fake = FakeQuoteContext.from_fixture("tests/fixtures/ff/futu_option_chain.json")
    provider = FutuOptionProvider(quote_context_factory=lambda: fake, sleep=lambda _: None)
    rows = provider.get_option_snapshot("SPY", date(2026, 9, 18))
    assert rows[0].iv == pytest.approx(0.14794)
    assert fake.called_methods <= {"get_global_state", "get_option_expiration_date", "get_option_chain", "get_market_snapshot"}


def test_timeout_retries_are_bounded_and_counted():
    provider = provider_with_failures([TimeoutError(), TimeoutError(), fixture_rows()])
    assert provider.get_option_snapshot("SPY", date(2026, 9, 18))
    assert provider.metrics.request_count == 3
    assert provider.metrics.retry_count == 2
```

- [ ] **Step 2: Verify the focused tests fail**

Expected: missing provider class.

- [ ] **Step 3: Implement an injected quote-only adapter**

Import only `OpenQuoteContext`, `RET_OK`, and quote enums inside the factory. Reject OpenD unless `qot_logined` is true and status is `READY`. Normalize each known Futu IV field using its explicitly declared source unit, preserve `raw_iv` and `raw_iv_unit`, use exponential delays `0.5, 1.0, 2.0` seconds plus injected jitter, and cap attempts at four.

- [ ] **Step 4: Add a static safety test**

```python
def test_ff_package_contains_no_trade_context_names():
    source = Path("src/tv_quant/ff/futu_provider.py").read_text(encoding="utf-8")
    assert "OpenSecTradeContext" not in source
    assert "OpenUSTradeContext" not in source
    assert "place_order" not in source
```

- [ ] **Step 5: Run focused and full tests, then commit PR 1**

Run all tests. Expected: all pass. Commit the provider and fixture, then open PR 1 with a design-spec link, test count, and explicit statement that no live notification or external write is enabled.

---

## PR 2 — Universe, earnings, scan orchestration, and dry-run reports

### Task 5: Versioned 100-symbol universe and earnings gate

**Files:**
- Create: `src/tv_quant/ff/universe.py`
- Create: `src/tv_quant/ff/earnings.py`
- Create: `tests/fixtures/ff/earnings.json`
- Test: `tests/ff/test_universe.py`
- Test: `tests/ff/test_earnings.py`

**Interfaces:**
- Consumes: database repositories and injected Futu/yfinance adapters.
- Produces: `UniverseService.active_members()`, `record_liquidity_day(...)`, `rank_weekly_candidates(...)`, and `classify_earnings(...)`.

- [ ] **Step 1: Write tests for exact cardinality, immutable versions, and fail-closed earnings**

```python
def test_active_universe_requires_exactly_100_unique_enabled_members():
    service = universe_service(member_count=99)
    with pytest.raises(UniverseConfigurationError, match="exactly 100"):
        service.active_members()


@pytest.mark.parametrize("event_day", [date(2026, 7, 17), date(2026, 10, 16)])
def test_earnings_interval_is_inclusive(event_day):
    result = classify_earnings(False, date(2026, 7, 17), date(2026, 10, 16), [event_day])
    assert result.status == ScanStatus.HOLD_EARNINGS_BEFORE_T2


def test_etf_and_unknown_stock_are_distinct():
    assert classify_earnings(True, SCAN_DAY, T2, None).status == ScanStatus.EARNINGS_NOT_APPLICABLE
    assert classify_earnings(False, SCAN_DAY, T2, None).status == ScanStatus.HOLD_EARNINGS_UNKNOWN
```

- [ ] **Step 2: Run and confirm missing implementations**

- [ ] **Step 3: Implement versioned membership and provider provenance**

Require exactly 100 unique tickers in a published version. A weekly rerank creates a draft version and CSV review artifact; activation is a separate CLI action and never mutates the previous version. Persist earnings source, fetched UTC time, raw value, normalized date, and classification.

- [ ] **Step 4: Run focused and full tests, then commit**

### Task 6: Scanner orchestration, stable reports, and CLI dry-run

**Files:**
- Create: `src/tv_quant/ff/scanner.py`
- Create: `src/tv_quant/ff/reports.py`
- Modify: `src/tv_quant/cli.py`
- Test: `tests/ff/test_scanner.py`
- Test: `tests/ff/test_reports.py`
- Test: `tests/ff/test_cli_scan.py`

**Interfaces:**
- Consumes: PR 1 core plus Task 5 providers.
- Produces: `evaluate_ticker(...) -> ScanResult`, `run_scan(...) -> ScanSummary`, `write_scan_reports(...)`, and CLI `scan --dry-run|--live-notifications`.

- [ ] **Step 1: Write a 100-result integration test**

```python
def test_scan_accounts_for_exactly_100_members_and_commits_before_outbox(tmp_path):
    scanner = fixed_scanner(tmp_path, candidate_count=3, hold_count=96, failure_count=1)
    summary = scanner.run(logical_date=date(2026, 7, 17), dry_run=False)
    assert (summary.candidate_count, summary.hold_count, summary.failure_count) == (3, 96, 1)
    assert summary.total_count == 100
    assert scanner.database.commit_sequence == ["scan", "notification_outbox", "sync_outbox"]


def test_duplicate_run_has_same_signal_ids_and_no_duplicate_outbox(tmp_path):
    scanner = fixed_scanner(tmp_path, candidate_count=1, hold_count=99, failure_count=0)
    first = scanner.run(logical_date=SCAN_DAY, dry_run=False)
    second = scanner.run(logical_date=SCAN_DAY, dry_run=False)
    assert first.signal_ids == second.signal_ids
    assert scanner.database.notification_count() == 1
```

- [ ] **Step 2: Verify the scanner and command are absent**

Run focused tests. Expected: missing scanner module and argparse rejects `scan`.

- [ ] **Step 3: Implement fail-closed ticker evaluation in this exact order**

Evaluate provider completeness, tenor availability, earnings, underlying liquidity, ATM IV, FF validity, structure A liquidity, then structure B liquidity. Preserve the first terminal `HOLD_*` status and a machine-readable tuple of failed fields. Never catch an unclassified exception as a successful `HOLD`; mark the ticker as `FAILED_UNCLASSIFIED` and include only exception class plus correlation ID.

- [ ] **Step 4: Implement reports and CLI flags**

`scan --dry-run` writes a unique UTC run directory with `summary.json`, `statuses.csv`, `candidates.json`, `gmail-preview.html`, `sync-manifest.json`, and `quota-report.json`, but writes neither DuckDB business rows nor external messages. `scan --live-notifications` requires committed results and enables only already-configured outbox consumers. Add `--db`, `--reports-dir`, `--logical-date`, and `--strategy-version` arguments.

- [ ] **Step 5: Test exact stable ranking**

Assert candidates sort by FF descending, relative spread ascending, ticker ascending. Assert candidate + hold + failure equals 100 and report values match database values byte-for-byte after canonical JSON serialization.

- [ ] **Step 6: Run all tests and commit PR 2**

Open PR 2 only after all tests pass. The PR live evidence may use fixed fixtures; do not connect to Futu during pytest.

---

## PR 3 — Local manual-position UI and exit lifecycle

### Task 7: Manual positions and NYSE-aware exit reminders

**Files:**
- Create: `src/tv_quant/ff/positions.py`
- Create: `src/tv_quant/ff/web.py`
- Create: `src/tv_quant/ff/templates/index.html`
- Create: `src/tv_quant/ff/templates/position_form.html`
- Modify: `src/tv_quant/cli.py`
- Modify: `requirements.txt`
- Test: `tests/ff/test_positions.py`
- Test: `tests/ff/test_web.py`

**Interfaces:**
- Produces: `open_position(...)`, `close_position(...)`, `mark_exit_due(...)`, FastAPI routes `GET /`, `POST /positions`, `POST /positions/{id}/close`, and CLI `serve`.

- [ ] **Step 1: Write state-machine tests**

```python
def test_only_open_positions_receive_exit_reminders():
    positions = [position("open", "OPEN"), position("closed", "CLOSED")]
    reminders = mark_exit_due(positions, logical_date=T1_EXPIRY)
    assert [item.position_id for item in reminders] == ["open"]


def test_close_requires_price_and_timezone_aware_time():
    with pytest.raises(PositionValidationError):
        close_position(open_position_fixture(), price=None, filled_at=datetime.now())
```

- [ ] **Step 2: Write web tests with FastAPI TestClient**

Test CSRF token validation, local-only host binding default `127.0.0.1`, leg directions, positive quantity, finite price, timezone-aware time, and that no endpoint name or source contains order submission verbs.

- [ ] **Step 3: Implement `OPEN -> EXIT_DUE -> CLOSED` only**

Reject every other transition. Determine previous US trading day with `exchange_calendars.get_calendar("XNYS")`; enqueue pre-expiry and final reminders once each using deterministic keys. Do not infer position state from quotes.

- [ ] **Step 4: Implement local pages and CLI**

Render signals, positions, exit due rows, local time conversions, and forms. Bind to loopback by default; a non-loopback `--host` requires an explicit `--allow-network` flag and must still expose no secret values.

- [ ] **Step 5: Run all tests and commit PR 3**

---

## PR 4 — Notification outbox: Gmail, Windows, and Codex

### Task 8: Idempotent notification workers and previews

**Files:**
- Create: `src/tv_quant/ff/notifications.py`
- Create: `src/tv_quant/ff/templates/email.html`
- Modify: `src/tv_quant/cli.py`
- Test: `tests/ff/test_notifications.py`

**Interfaces:**
- Produces: `NotificationWorker`, `GmailSmtpProvider`, `WindowsToastProvider`, `CodexSummaryProvider`, and `process_notification_outbox(...)`.

- [ ] **Step 1: Write fake-provider tests**

```python
def test_retry_reuses_idempotency_key_and_records_provider_id(tmp_path):
    provider = FakeNotificationProvider(failures=1, message_id="gmail-123")
    worker = notification_worker(tmp_path, provider)
    worker.run_once()
    worker.run_once()
    assert provider.keys == ["gmail:sig-1", "gmail:sig-1"]
    assert worker.database.notification("gmail:sig-1").provider_message_id == "gmail-123"


def test_email_copy_is_manual_review_only():
    html = render_candidate_email(candidate_fixture())
    assert "非订单、需人工复核" in html
    assert "place_order" not in html
```

- [ ] **Step 2: Implement providers behind one protocol**

`send(message, idempotency_key) -> provider_message_id` is the only provider interface. Gmail reads sender, recipient, username, and app password from environment at send time and redacts them from exceptions. Windows toast contains ticker, rounded FF, count, and loopback URL only. Codex writes atomic `reports/latest_codex_summary.json` and performs no network call.

- [ ] **Step 3: Implement retry states**

Use `PENDING`, `IN_FLIGHT`, `SENT`, `RETRY`, and `DEAD_LETTER`; exponential retry at 1, 5, 15, 60 minutes, maximum four attempts. One channel failure does not roll back committed scan results or successful channels. Gmail failure creates Windows/Codex warnings without recursive Gmail jobs.

- [ ] **Step 4: Test candidate, no-candidate, failure, position, and exit summaries**

Use fake providers exclusively. Assert credentials never appear in database rows, logs, rendered messages, or exception strings.

- [ ] **Step 5: Run all tests and commit PR 4**

Do not send a real email in this PR. The first Gmail message is a separately approved post-merge operational test.

---

## PR 5 — Sites replica and Obsidian one-way export

### Task 9: Target-independent sync outbox and Obsidian manifest/export

**Files:**
- Create: `src/tv_quant/ff/sync.py`
- Modify: `src/tv_quant/cli.py`
- Test: `tests/ff/test_sync.py`

**Interfaces:**
- Produces: `SyncWorker`, `SitesSyncTarget`, `ObsidianSyncTarget`, `build_obsidian_manifest(...)`, and CLI `sync --target sites|obsidian|all --dry-run`.

- [ ] **Step 1: Write containment and atomic-write tests**

```python
def test_obsidian_target_cannot_escape_ff_system(tmp_path):
    target = ObsidianSyncTarget(tmp_path / "FF-System")
    with pytest.raises(SyncPathError):
        target.write("../outside.md", "forbidden")


def test_target_failures_have_independent_checkpoints(tmp_path):
    worker = sync_worker(tmp_path, sites=FailingTarget(), obsidian=RecordingTarget())
    worker.run_once()
    assert worker.checkpoint("sites").status == "RETRY"
    assert worker.checkpoint("obsidian").status == "SYNCED"
```

- [ ] **Step 2: Implement canonical sync envelopes**

Use immutable `record_id`, `record_type`, `updated_at_utc`, `schema_version`, and redacted `payload`. Exclude Gmail/Futu credentials, account value, and free-text notes from Sites. Obsidian writes only `Daily/YYYY-MM-DD.md`, `Signals/<id>.md`, `Positions/<id>.md`, and `System/Sync-Health.md` under the resolved `FF-System` root using same-directory temporary files and `Path.replace`.

- [ ] **Step 3: Implement dry-run manifest before external writes**

`sync --target obsidian --dry-run` prints and writes a manifest containing resolved absolute target paths and SHA-256 content hashes without touching `C:\Users\cbcbe\OneDrive\Documents\TradingCodex\FF-System`. The first real write is blocked until the user separately approves that exact manifest.

- [ ] **Step 4: Run all tests and commit the local sync slice**

### Task 10: Owner-only Sites dashboard and protected D1 sync API

**Files:**
- Create: `sites/ff-dashboard/package.json`
- Create: `sites/ff-dashboard/wrangler.jsonc`
- Create: `sites/ff-dashboard/src/index.ts`
- Create: `sites/ff-dashboard/src/schema.ts`
- Create: `sites/ff-dashboard/migrations/0001_init.sql`
- Create: `sites/ff-dashboard/test/sync.test.ts`
- Create: `sites/ff-dashboard/test/dashboard.test.ts`
- Modify: `src/tv_quant/ff/sync.py`
- Test: `tests/ff/test_sites_sync.py`

**Interfaces:**
- Consumes: canonical sync envelopes from Task 9.
- Produces: authenticated `POST /api/sync`, owner-only dashboard queries, and local `SitesSyncTarget.send(envelope)`.

- [ ] **Step 1: Load and follow `sites:sites-building` before creating Sites code**

Use the Sites skill at implementation time. Keep local emulator and test data separate from production deployment.

- [ ] **Step 2: Write API contract tests**

Test missing/invalid bearer returns 401, invalid schema returns 400, repeated idempotency key returns the original result, older `updated_at_utc` cannot overwrite newer data, and payloads containing forbidden fields are rejected.

- [ ] **Step 3: Implement D1 query replica**

Create tables for scan summaries, scan results, signals, positions, notification summaries, sync receipts, and schema versions. Use `(record_id, updated_at_utc)` as receipt identity and only advance the projected row when the incoming timestamp is newer. Dashboard routes show today ranking, hold reasons, positions, exit calendar, notification state, and sync health.

- [ ] **Step 4: Test local worker-to-Sites binding**

Use an injected HTTP client and local test endpoint. Assert bearer secret is sent only in the Authorization header and is redacted from errors.

- [ ] **Step 5: Run Python and Sites tests, then commit PR 5**

Run global pytest plus the exact package test command defined in `package.json`. Do not deploy; deployment and owner-access configuration require separate approval.

---

## PR 6 — Scheduling, health checks, and first live dry-run

### Task 11: NYSE calendar guard, health report, and Windows task script

**Files:**
- Create: `src/tv_quant/ff/scheduler.py`
- Create: `scripts/register_ff_task.ps1`
- Modify: `src/tv_quant/cli.py`
- Test: `tests/ff/test_scheduler.py`
- Test: `tests/ff/test_health.py`

**Interfaces:**
- Produces: `logical_scan_date(now_utc)`, `health_report(...)`, CLI `health`, and an idempotent Task Scheduler script targeting 08:00 `Asia/Shanghai` weekdays.

- [ ] **Step 1: Write calendar and health tests**

Test weekends, NYSE holidays, daylight-saving transitions, OpenD stopped, quote login false, non-READY status, wrong universe cardinality, stale database migration, outbox backlog, and missing environment names without revealing values.

- [ ] **Step 2: Implement deterministic calendar behavior**

At 08:00 Beijing, choose the most recently completed XNYS session. Return `SKIPPED_NON_TRADING_DAY` when no new logical session is available. Store the last completed logical session in DuckDB and use the active-run lease from PR 1.

- [ ] **Step 3: Implement scheduler script generation**

The script resolves the repository, `.venv` Python, database, report, and log paths to absolute paths; registers one task with restart-on-failure and no stored plaintext password; and exits without changing an existing mismatched task unless `-Replace` is explicitly provided.

- [ ] **Step 4: Run all tests and commit scheduler code**

Do not execute the registration script until separately approved.

### Task 12: Staged first live dry-run and acceptance report

**Files:**
- Create: `docs/runbooks/ff-first-live-dry-run.md`
- Create at runtime: `reports/ff/<run_id>/summary.json`
- Create at runtime: `reports/ff/<run_id>/statuses.csv`
- Create at runtime: `reports/ff/<run_id>/candidates.json`
- Create at runtime: `reports/ff/<run_id>/gmail-preview.html`
- Create at runtime: `reports/ff/<run_id>/sync-manifest.json`
- Create at runtime: `reports/ff/<run_id>/quota-report.json`

**Interfaces:**
- Consumes: all previous PRs and the approved 100-member universe.
- Produces: an evidence bundle proving all 100 symbols were classified without external delivery.

- [ ] **Step 1: Run preflight without external side effects**

Run: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m tv_quant.cli health --db data/ff/ff.duckdb`

Expected: Python environment, schema, 100-member universe, NYSE calendar, Futu OpenD quote login, and writable local report paths are healthy; notification and sync destinations report `configured` or `disabled`, never a secret value.

- [ ] **Step 2: Run the complete test suite**

Run: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`

Expected: every test passes.

- [ ] **Step 3: Execute exactly one read-only 100-symbol dry-run**

Run: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m tv_quant.cli scan --dry-run --db data/ff/ff.duckdb --reports-dir reports/ff`

Expected: exactly 100 rows; candidate + hold + failure equals 100; no Gmail, Sites, Obsidian, broker, or scheduler side effect; quota report includes request count, retries, runtime, subscription use, and historical-quota use.

- [ ] **Step 4: Review failure-closed evidence**

Reject acceptance if any ticker silently disappears, any missing value becomes zero, any unknown earnings row becomes eligible, any invalid variance produces a candidate, any report disagrees with DuckDB, or any secret appears in artifacts.

- [ ] **Step 5: Request separate operational approvals**

Present the Gmail preview, Obsidian target manifest, Sites local preview, and Task Scheduler command. Request distinct approval before first Gmail delivery, first Obsidian write, Sites deployment/access configuration, and task registration.

- [ ] **Step 6: Commit runbook and open PR 6**

```powershell
git add docs/runbooks/ff-first-live-dry-run.md
git commit -m "docs: add FF live dry-run runbook"
```

## Self-Review Results

- **Spec coverage:** All 17 specification sections map to PRs 1–6. The strict FF formula, DTE rules, dual liquidity gates, earnings interval, structure A/B behavior, default sizing/Kelly guard, lifecycle, DuckDB authority, notification outbox, Sites/Obsidian replicas, scheduling, error codes, and first live dry-run each have an implementation and test task.
- **Scope split:** The six PR boundaries exactly follow the approved specification; each produces independently testable software and keeps external deployment or delivery outside code-merge approval.
- **Placeholder scan:** The plan contains no deferred implementation markers. Every task names concrete files, interfaces, failure behavior, commands, and expected results.
- **Type consistency:** `ScanStatus`, immutable IDs, canonical sync envelopes, outbox idempotency keys, UTC timestamps, and provider interfaces originate once and are consumed consistently by later tasks.
- **Current-project compatibility:** Existing `download` and `backtest` commands remain intact; new commands extend the current argparse entry point. Existing reporting behavior remains unchanged rather than being repurposed.
