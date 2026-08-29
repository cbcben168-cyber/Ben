# Provisional Cache Review Workstation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cache-symbol dropdown with a durable queue workstation that shows position, preserves progress, and supports Save and Next without network calls or whole-cache detector runs.

**Architecture:** A source-neutral queue domain projects items, latest human history, and append-only workflow actions into deterministic states. A schema-v2 repository stores queue actions and cursors, while `CacheQueueSource` builds an explicitly provisional source from local cache identities. The Streamlit page renders the selected item only; navigation never calls OpenD and never detects the whole cache.

**Tech Stack:** Python 3.14, dataclasses/enums, SQLite, Streamlit/AppTest, pandas, pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-pattern-finder-m3d-review-workstation-design.md`

## Global Constraints

- Always display `LOCAL CACHE · NOT A FORMAL SCAN BATCH` in provisional cache mode.
- Provisional identities never enter `scan_batches`, `scan_batch_manifests`, or `pattern_candidates`.
- Default order is unreviewed first in deterministic cache order and includes every cached symbol.
- Cache mode does not expose computer-result filters because it has no persisted whole-batch result projection.
- Navigation makes zero Futu/OpenD calls, downloads zero data, and runs no whole-cache detector pass.
- Human history remains append-only `pattern_validation.jsonl`; existing records remain readable.
- Skip and Snooze are workflow states, not human judgments.
- No daily target, streak, or misleading productivity-completion percentage may appear.
- Fixture mode remains isolated and retains its current selector behavior.
- Every verified task is committed; the completed plan branch is pushed to
  GitHub and its remote commit is verified before handoff.

---

## File structure

- Modify `src/tv_quant/pattern_finder/persistence/migrations.py`: schema-v2 tables and immutability triggers.
- Modify `src/tv_quant/pattern_finder/persistence/database.py`: register migration 2.
- Create `src/tv_quant/pattern_finder/application/review_queue.py`: queue types, state projection, filtering, navigation.
- Create `src/tv_quant/pattern_finder/application/review_sources.py`: provisional cache adapter.
- Create `src/tv_quant/pattern_finder/persistence/review_queue_repository.py`: action/cursor persistence.
- Modify `src/tv_quant/pattern_finder/validation.py`: optional submission ID and idempotent append.
- Modify `app/pages/2_Chart_Review.py`: queue workstation UI.
- Modify `tests/pattern_finder/test_sqlite_persistence.py`: migration contract.
- Create `tests/pattern_finder/test_review_queue.py`: pure queue behavior.
- Create `tests/pattern_finder/test_review_queue_persistence.py`: repository behavior.
- Create `tests/pattern_finder/test_review_sources.py`: provisional adapter behavior.
- Modify `tests/pattern_finder/test_validation.py`: submission idempotency.
- Modify `tests/pattern_finder/test_pages.py`: workstation acceptance.

### Task 1: Add schema v2 without changing migration v1

**Files:**
- Modify: `src/tv_quant/pattern_finder/persistence/migrations.py`
- Modify: `src/tv_quant/pattern_finder/persistence/database.py`
- Test: `tests/pattern_finder/test_sqlite_persistence.py`

**Interfaces:**
- Produces: `MIGRATION_2_STATEMENTS: tuple[str, ...]`.
- Produces: two contiguous migrations named `0001_pattern_finder_foundation` and `0002_scan_review_workflow`.

- [ ] **Step 1: Write failing migration tests**

```python
def test_schema_v2_adds_manifest_queue_actions_and_cursors(tmp_path):
    database = SqliteDatabase(tmp_path / "v2.db")
    assert database.migrate() == 2
    with database.connect() as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        triggers = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )}
    assert {"scan_batch_manifests", "review_queue_actions", "review_cursors"} <= tables
    assert {"scan_batches_immutable_update", "pattern_candidates_immutable_delete"} <= triggers


def test_schema_v2_reconciliation_checks_reject_bad_manifest(tmp_path):
    database, scan_batch_id = _database_with_complete_snapshot_and_scan_header(tmp_path)
    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        connection.execute(
            """INSERT INTO scan_batch_manifests(
                   scan_batch_id,scan_as_of_date,ordered_input_count,
                   quality_pass_count,quality_fail_count,yes_count,no_count,
                   code_commit,ordered_input_hash,provenance_json
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (scan_batch_id, "2026-08-27", 10, 8, 1, 4, 4,
             "abc1234", "0" * 64, "{}"),
        )
```

Update the existing default-version assertions from 1 to 2; keep custom one-migration tests unchanged.

- [ ] **Step 2: Run migration tests and verify failure**

Run: `pytest tests/pattern_finder/test_sqlite_persistence.py -q`

Expected: FAIL because schema v2 is absent.

- [ ] **Step 3: Add exact schema-v2 statements**

```sql
CREATE TABLE scan_batch_manifests (
  scan_batch_id TEXT PRIMARY KEY REFERENCES scan_batches(scan_batch_id),
  scan_as_of_date TEXT NOT NULL,
  ordered_input_count INTEGER NOT NULL CHECK(ordered_input_count >= 0),
  quality_pass_count INTEGER NOT NULL CHECK(quality_pass_count >= 0),
  quality_fail_count INTEGER NOT NULL CHECK(quality_fail_count >= 0),
  yes_count INTEGER NOT NULL CHECK(yes_count >= 0),
  no_count INTEGER NOT NULL CHECK(no_count >= 0),
  code_commit TEXT NOT NULL,
  ordered_input_hash TEXT NOT NULL,
  provenance_json TEXT NOT NULL,
  CHECK(ordered_input_count = quality_pass_count + quality_fail_count),
  CHECK(quality_pass_count = yes_count + no_count)
)
```

```sql
CREATE TABLE review_queue_actions (
  action_id TEXT PRIMARY KEY,
  source_kind TEXT NOT NULL CHECK(source_kind IN ('PROVISIONAL_CACHE','SCAN_BATCH')),
  source_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  pattern_type TEXT NOT NULL,
  action_type TEXT NOT NULL CHECK(action_type IN ('SKIP','SNOOZE','RESTORE')),
  created_at_utc TEXT NOT NULL
)
```

```sql
CREATE TABLE review_cursors (
  source_kind TEXT NOT NULL CHECK(source_kind IN ('PROVISIONAL_CACHE','SCAN_BATCH')),
  source_id TEXT NOT NULL,
  pattern_type TEXT NOT NULL,
  item_id TEXT NOT NULL,
  filters_json TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL,
  PRIMARY KEY(source_kind, source_id, pattern_type)
)
```

Add indexes on action scope/time and cursor scope. Add update/delete triggers for completed `scan_batches`, all `scan_batch_manifests`, and all `pattern_candidates`. Do not edit `MIGRATION_1_STATEMENTS`.

- [ ] **Step 4: Register migration 2 and run tests**

```python
DEFAULT_MIGRATIONS = (
    Migration(1, "0001_pattern_finder_foundation", MIGRATION_1_STATEMENTS),
    Migration(2, "0002_scan_review_workflow", MIGRATION_2_STATEMENTS),
)
```

Run: `pytest tests/pattern_finder/test_sqlite_persistence.py -q`

Expected: PASS, including checksum, rollback, concurrency, and old-v1 upgrade coverage.

- [ ] **Step 5: Commit schema v2**

```bash
git add src/tv_quant/pattern_finder/persistence/migrations.py src/tv_quant/pattern_finder/persistence/database.py tests/pattern_finder/test_sqlite_persistence.py
git commit -m "feat: add review workflow schema"
```

### Task 2: Implement the pure review-queue domain

**Files:**
- Create: `src/tv_quant/pattern_finder/application/review_queue.py`
- Create: `tests/pattern_finder/test_review_queue.py`

**Interfaces:**
- Produces enums: `QueueSourceKind`, `QueueState`, `QueueActionType`.
- Produces dataclasses: `QueueItem`, `QueueAction`, `QueueFilters`, `QueueCounts`, `QueueView`.
- Produces: `project_state(item: QueueItem, latest_action: QueueActionType | None) -> QueueState`.
- Produces: `project_queue(items, latest_actions, filters, selected_item_id) -> QueueView`.
- Produces: `move_visible(view: QueueView, current_item_id: str, offset: int) -> str`.
- Produces: `next_unreviewed(view: QueueView, current_item_id: str) -> str | None`.

- [ ] **Step 1: Write failing state/order/navigation tests**

```python
def test_state_precedence_and_unreviewed_first_order():
    items = (_item("AAPL", reviewed=True), _item("MSFT"), _item("NVDA", blocked=True))
    view = project_queue(items, latest_actions={}, filters=QueueFilters(), selected_item_id="MSFT")
    assert tuple(row.symbol for row in view.rows) == ("MSFT", "AAPL", "NVDA")
    assert view.counts == QueueCounts(reviewed=1, unreviewed=1, skipped=0, snoozed=0, data_blocked=1)


def test_snooze_restore_and_review_precedence():
    reviewed = _item("AAPL", reviewed=True)
    assert project_state(reviewed, QueueActionType.SNOOZE) is QueueState.REVIEWED
    fresh = _item("MSFT")
    assert project_state(fresh, QueueActionType.SNOOZE) is QueueState.SNOOZED
    assert project_state(fresh, QueueActionType.RESTORE) is QueueState.UNREVIEWED


def test_next_unreviewed_never_moves_into_reviewed_history():
    view = project_queue(items, latest_actions={}, filters=QueueFilters(), selected_item_id="AAPL-id")
    reviewed_view = project_queue(all_reviewed, latest_actions={}, filters=QueueFilters(), selected_item_id="AAPL-id")
    assert next_unreviewed(view, current_item_id="AAPL-id") == "MSFT-id"
    assert next_unreviewed(reviewed_view, current_item_id="AAPL-id") is None
```

Add boundary tests for Previous/Next, exact case-insensitive symbol search, state filter composition, missing cursor fallback, and deterministic source rank.

- [ ] **Step 2: Run tests and verify import failure**

Run: `pytest tests/pattern_finder/test_review_queue.py -q`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement immutable queue types**

```python
class QueueSourceKind(str, Enum):
    PROVISIONAL_CACHE = "PROVISIONAL_CACHE"
    SCAN_BATCH = "SCAN_BATCH"


class QueueState(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    REVIEWED = "REVIEWED"
    SKIPPED = "SKIPPED"
    SNOOZED = "SNOOZED"
    DATA_BLOCKED = "DATA_BLOCKED"


class QueueActionType(str, Enum):
    SKIP = "SKIP"
    SNOOZE = "SNOOZE"
    RESTORE = "RESTORE"


@dataclass(frozen=True, slots=True)
class QueueItem:
    source_kind: QueueSourceKind
    source_id: str
    item_id: str
    source_rank: int
    symbol: str
    pattern_type: str
    detector_version: str
    scan_as_of_date: str
    computer_decision: str | None
    data_quality_passed: bool
    quality_reason: str | None
    human_label: str | None
    validation_result: str | None
    history_count: int


@dataclass(frozen=True, slots=True)
class QueueFilters:
    state: QueueState | None = None
    symbol_query: str = ""


@dataclass(frozen=True, slots=True)
class QueueAction:
    action_id: str
    source_kind: QueueSourceKind
    source_id: str
    item_id: str
    pattern_type: str
    action_type: QueueActionType
    created_at_utc: datetime


@dataclass(frozen=True, slots=True)
class QueueCursor:
    source_kind: QueueSourceKind
    source_id: str
    pattern_type: str
    item_id: str
    filters: QueueFilters
    updated_at_utc: datetime


@dataclass(frozen=True, slots=True)
class QueueCounts:
    reviewed: int
    unreviewed: int
    skipped: int
    snoozed: int
    data_blocked: int


@dataclass(frozen=True, slots=True)
class QueueView:
    rows: tuple[QueueItem, ...]
    states: Mapping[str, QueueState]
    counts: QueueCounts
    selected_item_id: str | None
```

Implement state precedence exactly as the spec: blocked, reviewed, active snooze, latest skip, unreviewed. Sort by `(state is not UNREVIEWED, source_rank)` while keeping blocked visible. `move_visible` clamps at boundaries; `next_unreviewed` returns only an unreviewed row and returns `None` when none remain.

- [ ] **Step 4: Run queue tests**

Run: `pytest tests/pattern_finder/test_review_queue.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the queue domain**

```bash
git add src/tv_quant/pattern_finder/application/review_queue.py tests/pattern_finder/test_review_queue.py
git commit -m "feat: add deterministic review queue"
```

### Task 3: Persist source-aware actions and cursors

**Files:**
- Create: `src/tv_quant/pattern_finder/persistence/review_queue_repository.py`
- Create: `tests/pattern_finder/test_review_queue_persistence.py`
- Modify: `src/tv_quant/pattern_finder/persistence/__init__.py`

**Interfaces:**
- Consumes: Task 2 `QueueAction`, `QueueActionType`, `QueueSourceKind`.
- Produces: `QueueCursor` and `ReviewQueueRepository` methods `append_action`, `latest_actions`, `save_cursor`, `load_cursor`.

- [ ] **Step 1: Write failing repository tests**

```python
def test_provisional_action_and_cursor_round_trip(database):
    repository = ReviewQueueRepository(database)
    repository.append_action(_action("a1", QueueActionType.SNOOZE))
    repository.save_cursor(_cursor(item_id="AAPL-id"))
    assert repository.latest_actions(SOURCE_KIND, SOURCE_ID, "flat_base")["AAPL-id"].action_type is QueueActionType.SNOOZE
    assert repository.load_cursor(SOURCE_KIND, SOURCE_ID, "flat_base").item_id == "AAPL-id"


def test_same_action_id_is_idempotent_but_conflicting_payload_fails(database):
    repository.append_action(action)
    repository.append_action(action)
    with pytest.raises(sqlite3.IntegrityError, match="queue action conflict"):
        repository.append_action(replace(action, item_id="other"))


def test_formal_action_rejects_missing_candidate(database):
    with pytest.raises(ValueError, match="formal candidate does not exist"):
        repository.append_action(_formal_action(candidate_id="missing"))
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/pattern_finder/test_review_queue_persistence.py -q`

Expected: FAIL because the repository does not exist.

- [ ] **Step 3: Implement transactional repository methods**

`append_action()` starts `BEGIN IMMEDIATE`, validates a `SCAN_BATCH` item with:

```sql
SELECT 1 FROM pattern_candidates pc
JOIN scan_batches sb ON sb.scan_batch_id = pc.scan_batch_id
WHERE pc.candidate_id = ? AND sb.scan_batch_id = ?
```

It then compares an existing `action_id` payload before insert. `latest_actions()` orders by `created_at_utc, action_id` and keeps the final action per item. `save_cursor()` uses `INSERT ... ON CONFLICT ... DO UPDATE`; `load_cursor()` validates JSON into `QueueFilters` and raises an explicit repository error for corrupt state.

- [ ] **Step 4: Run repository and migration tests**

Run: `pytest tests/pattern_finder/test_review_queue_persistence.py tests/pattern_finder/test_sqlite_persistence.py -q`

Expected: PASS.

- [ ] **Step 5: Commit workflow persistence**

```bash
git add src/tv_quant/pattern_finder/persistence/review_queue_repository.py src/tv_quant/pattern_finder/persistence/__init__.py tests/pattern_finder/test_review_queue_persistence.py
git commit -m "feat: persist review actions and cursor"
```

### Task 4: Make validation submissions retry-idempotent

**Files:**
- Modify: `src/tv_quant/pattern_finder/validation.py`
- Modify: `tests/pattern_finder/test_validation.py`

**Interfaces:**
- Produces: optional `PatternValidation.submission_id: str | None = None`.
- Changes: `append_validation(path, record) -> bool`, returning `True` for append and `False` for an identical retry.
- Changes: `build_pattern_validation` accepts optional keyword-only `submission_id: str | None = None`.
- Preserves: legacy and migrated records without `submission_id`.

- [ ] **Step 1: Write failing round-trip/idempotency tests**

```python
def test_submission_id_is_optional_and_round_trips():
    old_payload = _build_new_pattern_validation().to_dict()
    old_payload.pop("submission_id", None)
    assert PatternValidation.from_dict(old_payload).submission_id is None
    record = replace(_build_new_pattern_validation(), submission_id=str(uuid4()))
    assert PatternValidation.from_dict(record.to_dict()) == record


def test_same_submission_is_appended_once_but_new_submission_is_revision(tmp_path):
    path = tmp_path / "pattern_validation.jsonl"
    first = replace(_build_new_pattern_validation(), submission_id=str(uuid4()))
    assert append_validation(path, first) is True
    assert append_validation(path, first) is False
    second = replace(first, submission_id=str(uuid4()), recorded_at_utc=RECORDED_2)
    assert append_validation(path, second) is True
    assert len(read_validation_history(path)) == 2
```

Add a conflict test: same submission ID with different record content raises `ValidationStoreError`.

- [ ] **Step 2: Run validation tests and verify failure**

Run: `pytest tests/pattern_finder/test_validation.py tests/pattern_finder/test_validation_migration.py -q`

Expected: FAIL because submission metadata and idempotent append are absent.

- [ ] **Step 3: Implement backward-compatible metadata**

Validate non-null submission IDs with `UUID(value)` and store the canonical string. `to_dict()` includes `submission_id`; `from_dict()` uses `value.get("submission_id")`. Before append, scan existing `PatternValidation` records with the same non-null submission ID: identical payload returns `False`, different payload raises `ValidationStoreError`. Records with `None` preserve current append behavior.

- [ ] **Step 4: Run validation regression**

Run: `pytest tests/pattern_finder/test_validation.py tests/pattern_finder/test_validation_migration.py tests/pattern_finder/test_pattern_review_regression.py -q`

Expected: PASS and migrated five-record history remains unchanged.

- [ ] **Step 5: Commit idempotent validation writes**

```bash
git add src/tv_quant/pattern_finder/validation.py tests/pattern_finder/test_validation.py
git commit -m "fix: make review submissions idempotent"
```

### Task 5: Build the explicitly provisional cache source

**Files:**
- Create: `src/tv_quant/pattern_finder/application/review_sources.py`
- Create: `tests/pattern_finder/test_review_sources.py`

**Interfaces:**
- Consumes: `cached_symbols`, `load_cache_entry`, `PATTERN_DETECTOR_VERSION`, validation history, Task 2 `QueueItem`.
- Produces: `QueueSource(source_kind, source_id, label, items)`.
- Produces: `build_cache_queue_source(cache_root, as_of_utc, pattern_type, history) -> QueueSource`.

- [ ] **Step 1: Write failing source tests**

```python
def test_cache_source_is_deterministic_provisional_and_never_runs_detector(tmp_path, monkeypatch):
    _write_cache(tmp_path, "AAPL", current=True)
    _write_cache(tmp_path, "BAC", current=False)
    monkeypatch.setattr(flat_base, "detect_flat_base", lambda *_: pytest.fail("whole-cache detector ran"))
    source = build_cache_queue_source(tmp_path, AS_OF, "flat_base", history=())
    assert source.source_kind is QueueSourceKind.PROVISIONAL_CACHE
    assert source.label == "LOCAL CACHE · NOT A FORMAL SCAN BATCH"
    assert tuple(item.symbol for item in source.items) == ("AAPL", "BAC")
    assert source.items[0].computer_decision is None
    assert source.items[1].data_quality_passed is False


def test_cache_identity_changes_when_a_file_changes(tmp_path):
    first = build_cache_queue_source(tmp_path, AS_OF, "flat_base", history=())
    _rewrite_last_bar(tmp_path / "AAPL_daily.csv")
    second = build_cache_queue_source(tmp_path, AS_OF, "flat_base", history=())
    assert first.source_id != second.source_id
```

Add tests that current matching human history marks an item reviewed, old scan dates do not, and duplicate symbols cannot occur.

- [ ] **Step 2: Run source tests and verify failure**

Run: `pytest tests/pattern_finder/test_review_sources.py -q`

Expected: FAIL because the adapter does not exist.

- [ ] **Step 3: Implement the cache adapter without detection**

```python
@dataclass(frozen=True, slots=True)
class QueueSource:
    source_kind: QueueSourceKind
    source_id: str
    label: str
    items: tuple[QueueItem, ...]
```

For each ordered cache file, hash `symbol`, file size, and `st_mtime_ns` into an item ID; hash the ordered item identities into `source_id`. Call `load_cache_entry()` only for quality and final session. Build the validation key with `PATTERN_DETECTOR_VERSION` and that final session, then attach latest label/result/history count. Never call `detect_flat_base()` here.

- [ ] **Step 4: Run source and queue tests**

Run: `pytest tests/pattern_finder/test_review_sources.py tests/pattern_finder/test_review_queue.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the provisional source**

```bash
git add src/tv_quant/pattern_finder/application/review_sources.py tests/pattern_finder/test_review_sources.py
git commit -m "feat: add provisional cache review source"
```

### Task 6: Replace the cache dropdown with the workstation UI

**Files:**
- Modify: `app/pages/2_Chart_Review.py`
- Modify: `tests/pattern_finder/test_pages.py`

**Interfaces:**
- Consumes: Tasks 2–5 plus `st.session_state["runtime_config"]` or `RuntimeConfig.from_environment()`.
- Produces visible controls: `上一只`, `下一只`, `保存并下一只`, `仅保存`, `跳过`, `稍后处理`, `恢复`.

- [ ] **Step 1: Write failing AppTest acceptance tests**

```python
def test_cache_review_shows_provisional_position_and_next_without_dropdown(tmp_path, monkeypatch):
    app = _load_cache_review_with_symbols(tmp_path, monkeypatch, ("AAPL", "MSFT"))
    assert "LOCAL CACHE · NOT A FORMAL SCAN BATCH" in _visible_text(app)
    assert "AAPL · 1 / 2" in _visible_text(app)
    assert not any(box.label == "缓存股票" for box in app.selectbox)
    next(item for item in app.button if item.label == "下一只").click().run()
    assert "MSFT · 2 / 2" in _visible_text(app)


def test_save_and_next_appends_once_advances_once_and_restores_after_restart(tmp_path, monkeypatch):
    validation_path = tmp_path / "pattern_validation.jsonl"
    app = _load_cache_review_with_symbols(tmp_path, monkeypatch, ("AAPL", "MSFT"))
    _fill_like_review(app)
    next(button for button in app.button if button.label == "保存并下一只").click().run()
    assert len(read_validation_history(validation_path)) == 1
    assert "MSFT · 1 / 2" in _visible_text(app)  # unreviewed-first projection
    restarted = _load("app/pages/2_Chart_Review.py")
    restarted.segmented_control[0].set_value("缓存 / Futu").run()
    assert "MSFT" in _visible_text(restarted)
```

Add tests for Save Only, skip, snooze, restore, state filter, exact symbol search, invalid validation store, cursor-write failure after successful append, data-blocked form disabled, and zero calls to `_load_futu_sdk`/`refresh_cache_entry` during navigation.

- [ ] **Step 2: Run Chart Review tests and verify failure**

Run: `pytest tests/pattern_finder/test_pages.py -q`

Expected: FAIL because the page still exposes one long cache `selectbox` and has no persisted navigation.

- [ ] **Step 3: Render the queue header and two-column workspace**

In cache mode:

1. build the provisional source and repository;
2. load actions/cursor;
3. project queue with stored filters;
4. select the restored/fallback item;
5. render warning, neutral counts, position, search, state filter, Previous/Next;
6. load and detect only the selected local frame;
7. render chart left and history/form/actions right;
8. render a compact selectable queue table below.

Do not show formal Scan Batch, Profile, or Snapshot claims in this mode. Do not show computer/data-quality filters.

- [ ] **Step 4: Implement event ordering**

For Save and Next:

```python
submission_id = st.session_state.setdefault(submission_key, str(uuid4()))
record = build_pattern_validation(
    recorded_at_utc=datetime.now(UTC),
    symbol=selected_item.symbol,
    pattern_type=selected_item.pattern_type,
    detector_version=review_input.detector_version,
    scan_as_of_date=review_input.scan_as_of_date,
    computer_result=review_input.computer_result,
    human_label=human_label,
    reason_tags=tuple(reason_tags),
    note=note,
    review_window_start=review_input.review_window_start,
    review_window_end=review_input.review_window_end,
    diagnostics=review_input.diagnostics,
    submission_id=submission_id,
)
append_validation(validation_path, record)
next_id = next_unreviewed(projected_queue, selected_item.item_id)
repository.save_cursor(replace(cursor, item_id=next_id or selected_item.item_id))
st.session_state[submission_key] = str(uuid4())
st.rerun()
```

If append fails, do not move. If append succeeds but cursor save fails, remain on the item and report that the human record is safe but Save-and-Next was incomplete. Previous/Next only save cursor. Skip/Snooze append a queue action then move. Restore appends `RESTORE` and reprojects.

- [ ] **Step 5: Run page and focused service tests**

Run: `pytest tests/pattern_finder/test_pages.py tests/pattern_finder/test_review_queue.py tests/pattern_finder/test_review_queue_persistence.py tests/pattern_finder/test_review_sources.py tests/pattern_finder/test_validation.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the workstation page**

```bash
git add app/pages/2_Chart_Review.py tests/pattern_finder/test_pages.py
git commit -m "feat: add provisional review workstation"
```

### Task 7: Full regression and performance proof

**Files:**
- No production file changes expected.

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: a test-backed compatibility-stage acceptance record.

- [ ] **Step 1: Run the complete Pattern Finder suite**

Run: `pytest tests/pattern_finder -q`

Expected: all tests PASS.

- [ ] **Step 2: Run full repository regression**

Run: `pytest -q`

Expected: all tests PASS or only a separately documented pre-existing failure unrelated to this plan.

- [ ] **Step 3: Run static safety checks**

Run: `python -m compileall -q src app && git diff --check`

Expected: no syntax or whitespace errors.

- [ ] **Step 4: Record navigation call counts and timing**

With a 100-item synthetic cache source, instrument one Next action and assert: zero OpenD calls, zero downloads, exactly one selected-frame load, exactly one selected detector run, and no whole-source detector call. Record median navigation time over 20 moves as evidence; do not freeze a hard SLA from one machine.

- [ ] **Step 5: Windows acceptance**

Apply the commits, restart from the desktop launcher, open Chart Review, and verify: warning visible; current/total visible; Save and Next reaches the next unreviewed stock; service restart restores it; Skip/Snooze persist; no OpenD request appears in quota logs during navigation.

- [ ] **Step 6: Push and verify the GitHub branch**

Run: `git push origin codex/pattern-finder-m3c-bcd-local-runtime`

Verify: `git ls-remote --heads origin codex/pattern-finder-m3c-bcd-local-runtime`
returns the same commit as `git rev-parse HEAD`.
