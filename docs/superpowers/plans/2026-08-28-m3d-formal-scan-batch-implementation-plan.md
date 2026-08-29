# M3D Formal Scan Batch and Review Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist an immutable, fully reconciled Flat Base Scan Batch from one formal Universe Snapshot and let the review workstation reopen it without recomputation.

**Architecture:** A pure scan builder consumes one formal complete Snapshot plus local cache evidence and produces a canonical completed batch in memory. `ScanRepository` writes header, manifest, and every YES/NO/NOT_EVALUATED row in one transaction, then serves immutable batches to `ScanBatchQueueSource`. Streamlit only invokes batch creation after an explicit action and otherwise reads persisted results.

**Tech Stack:** Python 3.14, dataclasses/enums, SHA-256 canonical JSON, SQLite schema v2, pandas, Streamlit/AppTest, pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-pattern-finder-m3d-review-workstation-design.md`

## Global Constraints

- A formal Scan Batch requires `SnapshotKind.FORMAL`, `Completeness.COMPLETE`, a published Profile binding, and a persisted Snapshot row.
- Every formal Snapshot member produces exactly one machine row.
- Quality-pass rows are YES or NO; missing/stale/invalid inputs are `NOT_EVALUATED` with exact reasons.
- `input_count == quality_pass_count + quality_fail_count` and `quality_pass_count == yes_count + no_count`.
- Header, manifest, and all result rows commit atomically; partial batches are never selectable.
- Completed batches and their results are immutable and idempotent by canonical ID/content.
- Review navigation reads persisted results and selected local OHLCV only; it never reruns a whole batch.
- Provisional cache identities cannot be exported or promoted into formal tables.
- Human evidence remains canonical append-only JSONL; `manual_reviews` is not dual-written.
- Every verified task is committed; the completed plan branch is pushed to
  GitHub and its remote commit is verified before handoff.

---

## File structure

- Create `src/tv_quant/pattern_finder/application/scan_persistence.py`: immutable scan models, canonical hashes, and formal builder.
- Create `src/tv_quant/pattern_finder/persistence/scan_repository.py`: atomic append/read/list operations.
- Modify `src/tv_quant/pattern_finder/application/review_sources.py`: formal Scan Batch adapter.
- Modify `src/tv_quant/pattern_finder/persistence/repositories.py`: remove the old read-only `ScanRepository` stub.
- Modify `src/tv_quant/pattern_finder/persistence/__init__.py`: export formal scan repository.
- Modify `src/tv_quant/pattern_finder/application/system_dashboard.py`: use the formal repository.
- Modify `app/pages/1_Today_Scan.py`: explicit formal batch creation action and blockers.
- Modify `app/pages/2_Chart_Review.py`: formal source/batch selection with latest formal default.
- Create `tests/pattern_finder/test_scan_persistence.py`: builder/reconciliation/hash tests.
- Create `tests/pattern_finder/test_scan_repository.py`: transaction/idempotency/immutability tests.
- Modify `tests/pattern_finder/test_review_sources.py`: formal adapter tests.
- Modify `tests/pattern_finder/test_pages.py`: formal page behavior.
- Modify `tests/pattern_finder/test_system_dashboard.py`: latest batch/count projections.

### Task 1: Define canonical completed-scan models and builder

**Files:**
- Create: `src/tv_quant/pattern_finder/application/scan_persistence.py`
- Create: `tests/pattern_finder/test_scan_persistence.py`

**Interfaces:**
- Produces: `MachineDecision(YES, NO, NOT_EVALUATED)`.
- Produces: `ScanResult`, `ScanManifest`, `CompletedScanBatch` frozen dataclasses.
- Produces: `build_flat_base_scan(snapshot, *, cache_root, completed_at_utc, code_commit) -> CompletedScanBatch`.

- [ ] **Step 1: Write failing builder tests**

```python
def test_formal_builder_accounts_for_yes_no_and_blocked_members(tmp_path):
    snapshot = _formal_snapshot_with_members(("AAPL", "MSFT", "BAC"))
    _write_current_cache(tmp_path, "AAPL", detected=True)
    _write_current_cache(tmp_path, "MSFT", detected=False)
    # BAC is intentionally missing.
    batch = build_flat_base_scan(snapshot, cache_root=tmp_path,
                                 completed_at_utc=COMPLETED, code_commit="abc1234")
    assert tuple(row.computer_decision for row in batch.results) == (
        MachineDecision.YES, MachineDecision.NO, MachineDecision.NOT_EVALUATED,
    )
    assert batch.manifest.ordered_input_count == 3
    assert batch.manifest.quality_pass_count == 2
    assert batch.manifest.quality_fail_count == 1
    assert batch.manifest.yes_count == 1
    assert batch.manifest.no_count == 1
    assert batch.results[2].reason_codes == ("MISSING_CACHE",)


def test_builder_rejects_preview_or_incomplete_snapshot(tmp_path):
    with pytest.raises(ValueError, match="formal complete Universe Snapshot required"):
        build_flat_base_scan(_preview_snapshot(), cache_root=tmp_path,
                             completed_at_utc=COMPLETED, code_commit="abc1234")


def test_canonical_batch_is_repeatable_and_changes_with_input(tmp_path):
    first = build_flat_base_scan(snapshot, cache_root=tmp_path, completed_at_utc=COMPLETED, code_commit="abc1234")
    second = build_flat_base_scan(snapshot, cache_root=tmp_path, completed_at_utc=COMPLETED, code_commit="abc1234")
    assert first == second
    _change_one_close(tmp_path / "AAPL_daily.csv")
    changed = build_flat_base_scan(snapshot, cache_root=tmp_path, completed_at_utc=COMPLETED, code_commit="abc1234")
    assert changed.scan_batch_id != first.scan_batch_id
    assert changed.input_hash != first.input_hash
```

Also test deterministic Snapshot-member order, stale/corrupt quality reasons, QFQ provenance, and rejection of a mismatched manifest count.

- [ ] **Step 2: Run builder tests and verify import failure**

Run: `pytest tests/pattern_finder/test_scan_persistence.py -q`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement frozen models with strict validation**

```python
class MachineDecision(str, Enum):
    YES = "YES"
    NO = "NO"
    NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True, slots=True)
class ScanResult:
    candidate_id: str
    scan_batch_id: str
    source_rank: int
    stock_id: str
    symbol: str
    pattern_type: str
    pattern_version: str
    signal_date: str
    computer_decision: MachineDecision
    features: Mapping[str, JSONScalar]
    reason_codes: tuple[str, ...]
    created_at_utc: datetime
```

`ScanManifest` carries all schema-v2 manifest fields; `CompletedScanBatch` carries the existing header fields, manifest, and ordered results. `__post_init__` validates UTC, non-empty bindings, contiguous `source_rank`, unique stock/candidate IDs, manifest reconciliation, and hashes.

- [ ] **Step 4: Implement canonical construction**

Use Snapshot member order `(stock_id, futu_code)`. For every member:

1. hash the exact cache bytes or a canonical missing sentinel into ordered input evidence;
2. call `load_cache_entry()` at Snapshot as-of session;
3. persist exact quality failures as `NOT_EVALUATED` without detector execution;
4. run `detect_flat_base()` only for quality-pass frames;
5. serialize the detector diagnostics into `features`;
6. derive candidate ID, result hash, and batch ID from canonical JSON bytes.

The builder performs no SQL and no OpenD call.

- [ ] **Step 5: Run builder tests**

Run: `pytest tests/pattern_finder/test_scan_persistence.py tests/pattern_finder/test_flat_base.py tests/pattern_finder/test_cache.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the formal builder**

```bash
git add src/tv_quant/pattern_finder/application/scan_persistence.py tests/pattern_finder/test_scan_persistence.py
git commit -m "feat: build canonical Flat Base scan batches"
```

### Task 2: Atomically persist and reopen completed batches

**Files:**
- Create: `src/tv_quant/pattern_finder/persistence/scan_repository.py`
- Create: `tests/pattern_finder/test_scan_repository.py`
- Modify: `src/tv_quant/pattern_finder/persistence/repositories.py`
- Modify: `src/tv_quant/pattern_finder/persistence/__init__.py`

**Interfaces:**
- Consumes: Task 1 `CompletedScanBatch`.
- Produces: `ScanRepository.append_completed(batch)`, `get(scan_batch_id)`, `list_completed()`, `latest()`, `candidate_count()`.

- [ ] **Step 1: Write failing transaction/idempotency tests**

```python
def test_completed_batch_round_trips_and_is_idempotent(database, batch):
    repository = ScanRepository(database)
    repository.append_completed(batch)
    repository.append_completed(batch)
    assert repository.get(batch.scan_batch_id) == batch
    assert repository.candidate_count() == batch.manifest.ordered_input_count


def test_same_batch_id_with_different_content_is_conflict(database, batch):
    repository.append_completed(batch)
    with pytest.raises(ScanConflictError, match="scan batch conflict"):
        repository.append_completed(replace(batch, result_hash="f" * 64))


def test_any_result_insert_failure_rolls_back_header_manifest_and_rows(database, batch, monkeypatch):
    broken = _batch_with_duplicate_candidate_id(batch)
    with pytest.raises(sqlite3.IntegrityError):
        repository.append_completed(broken)
    assert repository.list_completed() == ()
    assert repository.candidate_count() == 0
```

Add tests for missing Snapshot FK, manifest/result tampering on read, immutable update/delete triggers, and ordered result restoration.

- [ ] **Step 2: Run repository tests and verify failure**

Run: `pytest tests/pattern_finder/test_scan_repository.py -q`

Expected: FAIL because the formal repository does not exist.

- [ ] **Step 3: Implement one-transaction append**

`append_completed()` must:

1. `BEGIN IMMEDIATE`;
2. verify the Snapshot exists and is formal/complete through `SnapshotRepository.get()` before or within the transaction-safe boundary;
3. compare an existing batch by all canonical header/manifest/result content;
4. insert completed `scan_batches` header;
5. insert `scan_batch_manifests`;
6. insert every `pattern_candidates` row in `source_rank` order, storing rank and symbol in `features_json` because v1 has no dedicated columns;
7. query counts and hashes back;
8. commit only after reconciliation.

Any exception rolls back. `get()` reconstructs strict Task 1 dataclasses and therefore detects tampering.

- [ ] **Step 4: Replace the old repository stub**

Remove `ScanRepository` from `persistence/repositories.py`, export the new class from `persistence/__init__.py`, and update imports without changing Profile/Snapshot/System repositories.

- [ ] **Step 5: Run persistence tests**

Run: `pytest tests/pattern_finder/test_scan_repository.py tests/pattern_finder/test_sqlite_persistence.py -q`

Expected: PASS.

- [ ] **Step 6: Commit formal persistence**

```bash
git add src/tv_quant/pattern_finder/persistence/scan_repository.py src/tv_quant/pattern_finder/persistence/repositories.py src/tv_quant/pattern_finder/persistence/__init__.py tests/pattern_finder/test_scan_repository.py
git commit -m "feat: persist immutable scan batches"
```

### Task 3: Adapt formal batches into the review queue

**Files:**
- Modify: `src/tv_quant/pattern_finder/application/review_sources.py`
- Modify: `tests/pattern_finder/test_review_sources.py`

**Interfaces:**
- Consumes: Task 2 `CompletedScanBatch`, existing validation history, queue `QueueItem`.
- Produces: `build_scan_batch_queue_source(batch, history) -> QueueSource`.

- [ ] **Step 1: Write failing formal-source tests**

```python
def test_formal_source_preserves_batch_order_results_and_review_projection(batch, history):
    source = build_scan_batch_queue_source(batch, history)
    assert source.source_kind is QueueSourceKind.SCAN_BATCH
    assert source.source_id == batch.scan_batch_id
    assert tuple(item.source_rank for item in source.items) == tuple(range(len(batch.results)))
    assert tuple(item.computer_decision for item in source.items) == ("YES", "NO", "NOT_EVALUATED")
    assert source.items[2].data_quality_passed is False
    assert source.items[0].human_label == "像"
```

Add a test proving a `NOT_EVALUATED` row becomes `DATA_BLOCKED`, never machine NO.

- [ ] **Step 2: Run source tests and verify failure**

Run: `pytest tests/pattern_finder/test_review_sources.py -q`

Expected: FAIL because only provisional cache sources are supported.

- [ ] **Step 3: Implement the formal adapter**

Map each persisted result directly; do not load OHLCV and do not call the detector while constructing the queue. Match human history by `(symbol, pattern_type, pattern_version, signal_date)`. Expose computer and data-quality filters for this source because the full projection is persisted.

- [ ] **Step 4: Run source/queue tests**

Run: `pytest tests/pattern_finder/test_review_sources.py tests/pattern_finder/test_review_queue.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the formal adapter**

```bash
git add src/tv_quant/pattern_finder/application/review_sources.py tests/pattern_finder/test_review_sources.py
git commit -m "feat: adapt scan batches to review queue"
```

### Task 4: Add explicit formal batch creation to Today Scan

**Files:**
- Modify: `app/pages/1_Today_Scan.py`
- Modify: `tests/pattern_finder/test_pages.py`

**Interfaces:**
- Consumes: RuntimeConfig, SnapshotRepository, Tasks 1–2.
- Produces: button `保存正式扫描批次` only when a formal complete Snapshot is available.

- [ ] **Step 1: Write failing page tests**

```python
def test_today_scan_blocks_formal_persistence_without_snapshot(tmp_path, monkeypatch):
    app = _load_today_scan_with_database(tmp_path, monkeypatch, snapshot=None)
    assert "需要正式且完整的 Universe Snapshot" in _visible_text(app)
    assert not any(button.label == "保存正式扫描批次" and not button.disabled for button in app.button)


def test_formal_scan_is_built_only_after_explicit_click(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(scan_persistence, "build_flat_base_scan", lambda *args, **kwargs: calls.append(args) or batch)
    app = _load_today_scan_with_database(tmp_path, monkeypatch, snapshot=formal_snapshot)
    assert calls == []
    next(button for button in app.button if button.label == "保存正式扫描批次").click().run()
    assert len(calls) == 1
    assert ScanRepository(database).latest()["scan_batch_id"] == batch.scan_batch_id
```

- [ ] **Step 2: Run page tests and verify failure**

Run: `pytest tests/pattern_finder/test_pages.py -q`

Expected: FAIL because the page has no persisted batch action.

- [ ] **Step 3: Implement read-only blocker and explicit write**

Load the latest Snapshot summary through `SnapshotRepository`; retrieve and validate the Snapshot only after the formal action path is rendered. On click, call the pure builder with local cache, current UTC completion time, and current Git commit, then `ScanRepository.append_completed()`. Display the batch ID and reconciliation counts. Missing/stale caches remain visible as blocked rows; they do not abort the batch.

- [ ] **Step 4: Run Today Scan tests**

Run: `pytest tests/pattern_finder/test_pages.py tests/pattern_finder/test_scan_persistence.py tests/pattern_finder/test_scan_repository.py -q`

Expected: PASS and no builder/repository call before click.

- [ ] **Step 5: Commit formal scan creation**

```bash
git add app/pages/1_Today_Scan.py tests/pattern_finder/test_pages.py
git commit -m "feat: persist formal scans from Today Scan"
```

### Task 5: Make formal Scan Batch the default review source

**Files:**
- Modify: `app/pages/2_Chart_Review.py`
- Modify: `tests/pattern_finder/test_pages.py`
- Modify: `src/tv_quant/pattern_finder/application/system_dashboard.py`
- Modify: `tests/pattern_finder/test_system_dashboard.py`

**Interfaces:**
- Consumes: ScanRepository list/get and Task 3 adapter.
- Produces: latest completed formal batch as default, explicit legacy cache compatibility selection.

- [ ] **Step 1: Write failing UI/dashboard tests**

```python
def test_chart_review_defaults_to_latest_formal_batch_and_does_not_recompute(tmp_path, monkeypatch):
    _persist_two_batches(database, older, latest)
    monkeypatch.setattr(flat_base, "detect_flat_base", lambda *_: pytest.fail("batch recomputed"))
    app = _load_chart_review(tmp_path, monkeypatch)
    assert latest.scan_batch_id in _visible_text(app)
    assert "LOCAL CACHE · NOT A FORMAL SCAN BATCH" not in _visible_text(app)
    assert "AAPL · 1 / 3" in _visible_text(app)


def test_dashboard_uses_persisted_batch_counts(database, latest):
    state = build_dashboard_state(config)
    assert latest.scan_batch_id in state.last_scan
    assert state.candidate_count == latest.manifest.ordered_input_count
```

Add formal batch selector, computer/data-quality filters, blocked submission, batch reopening after restart, and explicit switch back to provisional cache tests.

- [ ] **Step 2: Run page/dashboard tests and verify failure**

Run: `pytest tests/pattern_finder/test_pages.py tests/pattern_finder/test_system_dashboard.py -q`

Expected: FAIL because the page knows only fixture/cache sources and Dashboard imports the old stub.

- [ ] **Step 3: Implement formal default selection**

When completed batches exist, source options are `正式扫描批次`, `缓存兼容`, and `本地样例`, with formal selected by default. Load only the selected batch and build its queue source. Render batch ID, Snapshot ID, Profile binding, detector version, scan date, and immutable counts. Enable persisted computer/data-quality filters. When the selected item is data-blocked, explain exact reasons and disable human submission.

- [ ] **Step 4: Update Dashboard repository import and projections**

Use the new `ScanRepository`. Candidate and pending-review counts must represent the selected latest formal batch, not global historical rows; add repository methods `candidate_count(scan_batch_id)` and queue-derived pending count rather than relying on `manual_reviews`.

- [ ] **Step 5: Run UI/dashboard regression**

Run: `pytest tests/pattern_finder/test_pages.py tests/pattern_finder/test_system_dashboard.py tests/pattern_finder/test_review_sources.py -q`

Expected: PASS and navigation invokes neither builder nor detector.

- [ ] **Step 6: Commit formal review integration**

```bash
git add app/pages/2_Chart_Review.py src/tv_quant/pattern_finder/application/system_dashboard.py tests/pattern_finder/test_pages.py tests/pattern_finder/test_system_dashboard.py
git commit -m "feat: review persisted formal scan batches"
```

### Task 6: Complete regression and milestone acceptance

**Files:**
- Modify only if a real regression is found; add its focused test before fixing.

**Interfaces:**
- Consumes: Tasks 1–5 and the provisional-workstation plan.
- Produces: formal M3D acceptance evidence.

- [ ] **Step 1: Run focused M3D suites**

Run: `pytest tests/pattern_finder/test_scan_persistence.py tests/pattern_finder/test_scan_repository.py tests/pattern_finder/test_review_queue.py tests/pattern_finder/test_review_queue_persistence.py tests/pattern_finder/test_review_sources.py tests/pattern_finder/test_pages.py -q`

Expected: PASS.

- [ ] **Step 2: Run all Pattern Finder tests**

Run: `pytest tests/pattern_finder -q`

Expected: PASS.

- [ ] **Step 3: Run full repository and static checks**

Run: `pytest -q && python -m compileall -q src app && git diff --check`

Expected: PASS.

- [ ] **Step 4: Prove immutable reopen behavior**

Create one formal fixture batch, close all database connections, instantiate fresh repositories/services, reopen the batch, navigate three items, and compare canonical header/manifest/result hashes byte-for-byte. Assert zero builder, detector, downloader, and OpenD calls during reopen/navigation.

- [ ] **Step 5: Windows acceptance after a real formal Snapshot exists**

From Today Scan, save one formal batch. Restart via desktop launcher. Confirm Dashboard latest scan/counts, open Chart Review, verify the same batch ID and position, Save and Next once, restart again, and verify the cursor and append-only human history. A provisional queue pass does not substitute for this formal acceptance.

- [ ] **Step 6: Push and verify the GitHub branch**

Run: `git push origin codex/pattern-finder-m3c-bcd-local-runtime`

Verify: `git ls-remote --heads origin codex/pattern-finder-m3c-bcd-local-runtime`
returns the same commit as `git rev-parse HEAD`.
