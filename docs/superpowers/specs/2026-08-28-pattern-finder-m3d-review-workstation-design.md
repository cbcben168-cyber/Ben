# Pattern Finder M3D — Persisted Scan Batch and Review Workstation Design

**Date:** 2026-08-28

**Status:** DESIGN READY FOR USER REVIEW

**Scope:** current M3D scan persistence plus queue-based Chart Review UX

## 1. Outcome

Replace the current cache-symbol dropdown workflow with a deterministic review
workstation. It first supports an explicitly provisional local-cache queue so
the current migrated research can continue; once a formal Universe Snapshot is
available, the same UI consumes a persisted Scan Batch. A reviewer must always
know which case is open, what remains, and what action will happen next. Saving
a review must not require reopening the symbol selector, reconnecting to Futu,
or rerunning the market scan.

This design operationalizes the Open Review Queue and Fast Review requirements
already frozen in Product Blueprint V3. It does not change the Flat Base
detector or the human-label schema.

## 2. Context and observed failure

The current `app/pages/2_Chart_Review.py` cache path:

1. enumerates cached symbols into one `selectbox`;
2. loads and detects only the selected symbol;
3. appends a review after form submission;
4. leaves the user on the same symbol;
5. has no explicit queue position, next action, durable cursor, or pending view.

This is usable for a pilot but fails operationally at hundreds of cases. A long
dropdown does not answer “what should I review next?” and does not preserve an
auditable review path.

## 3. Relationship to adjacent work

This work is one bounded subsystem in a larger scale program:

- **Quota correction, before M3D:** remove the project-only 25-new-code daily
  ceiling and 200-code rolling ceiling. Use Futu's returned seven-day
  `used_quota`, `remain_quota`, and `detail_list` as authority. This change gets
  its own focused tests and commit.
- **This design:** persist scan results and provide an efficient queue-based
  reviewer for those results.
- **Immediate compatibility stage:** expose the current cache set through a
  clearly labeled provisional queue. This stage improves review efficiency but
  cannot claim formal Scan Batch provenance.
- **Full-market acquisition, after this design:** create the Universe Snapshot
  gateway and bulk daily-data provider boundary. It may produce thousands of
  scan inputs, but the review workstation remains unchanged.
- **Pattern-instance dedup and cross-batch priority:** remain a later subsystem.
  M3D v1 reviews one explicitly selected Scan Batch. It must not pretend to
  deduplicate continuing instances across batches.

## 4. Scope

### 4.1 Included

- append-only persistence of completed Flat Base Scan Batches;
- persistence of every reviewable machine result, including YES and NO;
- deterministic queue construction for one selected Scan Batch;
- reviewed, unreviewed, skipped, snoozed, and data-failure visibility;
- durable current-position restoration;
- previous, next, save, save-and-next, skip, and snooze actions;
- symbol search and direct queue-row selection;
- existing append-only JSONL validation history as the canonical human record;
- current Profile, Snapshot, detector version, scan date, and data provenance
  bindings;
- fixture mode remaining available and isolated from the persisted queue;
- a provisional cache-backed queue used only while no formal Scan Batch exists.

### 4.2 Excluded

- changing Flat Base thresholds or math;
- Rounded Base, Compression, READY, scores, ML, or trading;
- future-return labels and 5D/10D/20D outcomes;
- historical T0 replay;
- cross-batch Pattern Instance dedup;
- a daily review target, quota, streak, or productivity score;
- keyboard shortcuts implemented with unstable custom JavaScript;
- downloading data or contacting Futu while navigating the review queue;
- replacing the canonical JSONL review history in this milestone.

## 5. Source-of-truth boundaries

| Concern | Authority |
|---|---|
| Universe membership | persisted formal Universe Snapshot |
| Machine result | persisted Scan Batch and candidate row |
| OHLCV chart | local validated QFQ cache bound to the scan input |
| Human judgment | append-only `pattern_validation.jsonl` |
| Latest human state | projection of the latest matching validation record |
| Queue cursor/actions | SQLite mutable workflow state |

The UI is not allowed to reconstruct or label a formal Scan Batch from whatever
CSV files happen to exist at render time. A provisional cache queue is a
separate source type with a visible `LOCAL CACHE · NOT A FORMAL SCAN BATCH`
label and no Snapshot, Profile, or formal result-hash claims.

## 6. Scan Batch contract

A completed Scan Batch is immutable and binds:

- `scan_batch_id`;
- formal `snapshot_id` and Profile version through that Snapshot;
- `pattern_type` and detector version;
- scan as-of session and completion time;
- canonical input/config/result hashes;
- ordered input count, data-quality pass/fail counts, YES count, and NO count;
- code and data provenance needed to reproduce the run.

The existing `scan_batches` table remains the batch header. M3D extends its
repository contract through a versioned migration rather than allowing UI SQL.
A companion `scan_batch_manifests` row stores the missing immutable fields:
scan as-of session, ordered input count, quality pass/fail counts, YES/NO
counts, code commit, ordered-input hash, and provenance JSON.

Every input security produces one persisted machine row. Data-quality-passing
rows carry detector YES or NO. Data-quality failures carry
`computer_decision=NOT_EVALUATED`, the Scan Batch as-of date as their signal
date, and exact quality reasons. They may never disappear from counts. Tests
must prove that total input equals evaluated YES + evaluated NO + data blocked.

The existing `pattern_candidates` name is retained for schema compatibility;
in M3D it means “reviewable machine result,” not “positive trade candidate.”

The service constructs and validates the complete header, manifest, and result
set before opening one database transaction. That transaction inserts the
already-completed batch and every machine row, verifies count/hash
reconciliation, then commits. A failure rolls back the whole batch, so no
partial batch is selectable. Schema v2 triggers reject update or delete of a
completed header, its manifest, and its result rows. Reappending the same
canonical ID and hashes is a no-op; the same ID with different content is a
conflict.

## 7. Review identity

The machine-row identity is its immutable `candidate_id`, bound to one Scan
Batch. The canonical human-history lookup remains:

```text
(symbol, pattern_type, detector_version, scan_as_of_date)
```

Saving a second judgment for the same key appends another validation record.
It never updates or deletes the prior record. The queue displays the latest
record and the complete history count.

The future Pattern Instance ID is deliberately not invented in this milestone.

## 8. Queue states and actions

The queue read model exposes:

- `UNREVIEWED` — no matching human validation;
- `REVIEWED` — at least one matching human validation;
- `SKIPPED` — explicitly passed over in the current batch;
- `SNOOZED` — deferred persistently until manually restored;
- `DATA_BLOCKED` — chart/detector input did not pass quality requirements.

`SKIPPED` and `SNOOZED` are workflow annotations, not human labels and not
validation outcomes. They cannot create a row in `pattern_validation.jsonl`.

SQLite receives append-only queue actions and a mutable cursor projection. A
new schema migration adds the minimum dedicated workflow tables; queue state is
not encoded into free-form notes or detector features. Both workflow tables use
an explicit source identity:

```text
(source_kind, source_id, item_id, pattern_type)
```

`source_kind` is either `PROVISIONAL_CACHE` or `SCAN_BATCH`. Formal `item_id`
values are existing candidate IDs and must resolve through the repository;
provisional item IDs are canonical hashes of the cache-file identity. This
polymorphic workflow key deliberately has no direct foreign key into
`pattern_candidates`; application validation must reject a missing formal
candidate. Provisional identities may never be inserted into `scan_batches` or
`pattern_candidates`.

State precedence is deterministic: `DATA_BLOCKED`, then `REVIEWED`, then an
active `SNOOZED`, then the latest `SKIPPED`, then `UNREVIEWED`. Restore removes
the active snooze/skip projection; if a human record exists the row remains
`REVIEWED`, otherwise it returns to `UNREVIEWED`.

## 9. Default ordering and bias controls

The default view is **unreviewed first in deterministic source order**.
Reviewed rows remain searchable and selectable. The default must include both
computer YES and computer NO so the workflow can observe false positives and
false negatives. Save and Next advances only through unreviewed visible rows;
when none remain it stops rather than silently cycling into reviewed history.

Supported filters:

- queue state;
- computer YES / NO;
- data-quality PASS / FAIL;
- human label;
- validation result;
- exact symbol search.

Computer YES-only review is an optional filter, never the default. Any filtered
queue displays its scope so the user cannot mistake it for full-sample review.

The provisional adapter has no persisted full-batch machine projection. Its
default queue therefore includes every cached symbol in deterministic order,
evaluates only the opened symbol from local data, and disables computer-result
and data-quality filters with an explanation. It must not run a hidden
whole-cache detection pass merely to populate those filters.

## 10. Page layout

### 10.1 Header and navigation bar

Display compact neutral counts, not a productivity score:

- selected Pattern and Scan Batch;
- current symbol and queue position, for example `AAPL · 12 / 300`;
- reviewed count, unreviewed count, snoozed count, and data-blocked count;
- Previous and Next buttons;
- exact symbol search;
- queue filters.

Do not display “today's target,” a daily quota, a streak, or percentage-complete
language. Counts and position are navigation facts, not a demand to finish the
batch.

### 10.2 Main workspace

Use a wide two-column layout:

- **Left:** large candlestick chart, volume, highlighted review window,
  support/resistance, and detector explanation.
- **Right:** current status, diagnostics, existing review history, human label,
  reason tags, note, and action buttons.

The right column keeps review controls visible without requiring a round trip
to a dropdown. A compact selectable queue table appears below the actions or in
an adjacent container and shows symbol, machine decision, queue state, and
latest human label.

### 10.3 Primary actions

- **Save and Next** — validate, append exactly one review, clear form state,
  select the next item in the current filtered queue, persist cursor, rerun.
- **Save Only** — append exactly one review and remain on the current item.
- **Previous / Next** — move without writing a human review.
- **Skip** — record a skip action and advance.
- **Snooze** — record a durable defer action, remove the item from the default
  unreviewed queue, and advance.
- **Restore** — return a snoozed item to the unreviewed queue.

When the filtered queue has no next item, show a neutral end-of-queue message
and allow filter changes or return to reviewed items.

Every explicit Save action receives a fresh submission ID. That ID is stored as
backward-compatible metadata in the appended validation record. Retrying the
same UI action is idempotent; a deliberate later revision receives a new ID and
appends a new record. The write order is validation append first, then cursor
advance. This preserves the canonical human record if SQLite cursor persistence
fails.

## 11. Resume behavior

The current cursor is scoped by user-local single-user runtime, source identity,
pattern type, and stored filter state. Formal source identity is the Scan Batch
ID; provisional source identity is a hash of ordered cache names and file
identities. On page reopen or service restart:

1. restore the cursor if that candidate still exists in the active scope;
2. otherwise open the first unreviewed candidate in deterministic order;
3. otherwise open the first visible row;
4. otherwise display an empty-scope explanation.

The cursor is convenience state. Human records and machine results remain the
authoritative research evidence.

## 12. Performance contract

Changing rows must:

- make zero Futu/OpenD calls;
- download zero market data;
- run zero whole-Universe scans;
- run zero whole-batch detectors;
- read only the selected local OHLCV frame and persisted result/validation
  projections;
- reuse cached queue and frame projections where safe;
- expose benchmark timings before a hard latency SLA is frozen.

Queue construction is an application service outside the Streamlit page. The
page never imports `sqlite3` and never owns query semantics.

## 13. Failure behavior

- Missing or corrupt Scan Batch: explicit blocker; no fallback to live cache.
- Missing selected cache: mark/display `DATA_BLOCKED`; do not fabricate a chart.
- Stale or failed data: show the precise quality reason and disable human-form
  submission for that machine result.
- Invalid validation JSONL: stop review writes and show the exact error.
- Append failure: remain on the current item; never advance.
- Cursor persistence failure: preserve the saved review, report cursor failure,
  and do not claim full Save-and-Next success.
- A failed submission never changes cursor or queue action state.

## 14. Application components

Create or extend focused units:

- `scan_persistence` — canonical batch/result construction and hashes;
- `ScanRepository` — append/get/list completed batches and ordered results;
- `ReviewQueueRepository` — append queue actions and store/load cursor;
- `review_queue` application service — pure ordering, filtering, counts, and
  next/previous selection;
- `CacheQueueSource` — explicitly provisional adapter over ordered local cache
  identities and existing validation history;
- `ScanBatchQueueSource` — formal adapter over immutable persisted results;
- `2_Chart_Review.py` — rendering and user events only;
- existing `validation.py` — unchanged append-only human evidence contract.

`validation.py` gains only optional submission-ID metadata and idempotent append
handling. Existing records without that field remain valid; the human labels,
review key, latest-record projection, and append-only semantics do not change.

Exact filenames may follow repository conventions, but these ownership
boundaries are mandatory.

## 15. Migration and compatibility

- Add a checksum-verified schema v2 migration; never edit migration v1.
- Add source-aware queue-action and cursor tables that support both provisional
  and formal sources without weakening formal Scan Batch validation.
- Existing database, Profiles, Snapshots, cache CSVs, and validation JSONL are
  preserved.
- Existing five migrated validation records remain readable and are not
  rewritten.
- The existing `manual_reviews` table remains reserved; M3D does not dual-write
  it and create a second human-review authority.
- Fixture mode continues to use the current simple selector and does not create
  Scan Batches or queue actions.
- Until a formal Universe Snapshot and Scan Batch exist, cache mode uses the
  provisional queue with the persistent
  `LOCAL CACHE · NOT A FORMAL SCAN BATCH` warning.
- The provisional adapter never populates formal Scan Batch tables, never
  claims Profile or Snapshot provenance, and cannot use formal batch export.
- Once a formal Scan Batch exists, the page defaults to the formal adapter. The
  provisional adapter remains an explicitly selected compatibility view for
  legacy cache research.

## 16. Verification

### 16.1 Repository and migration tests

- migration v2 applies once, records checksum, and rolls back atomically;
- foreign keys and immutable batch constraints hold;
- append of the same canonical batch is idempotent;
- same ID with different content is a conflict;
- all eligible YES and NO rows persist in deterministic order;
- input reconciliation proves no silent row loss;
- queue actions and cursor round-trip exactly;
- provisional identities cannot enter formal batch/result repositories or
  formal exports;
- a `SCAN_BATCH` workflow identity with a missing candidate is rejected.

### 16.2 Queue service tests

- default includes YES and NO and puts unreviewed first;
- filters never mutate source rows;
- next/previous are deterministic at boundaries;
- reviewed, skipped, snoozed, restored, and blocked states project correctly;
- reviewed rows remain directly searchable;
- cursor restoration follows the fallback order;
- multiple human records select the latest and preserve history count.

### 16.3 Streamlit tests

- header shows symbol and queue position;
- Save and Next appends once and advances once;
- retrying one submission ID does not append or advance twice, while a new
  submission ID creates a deliberate revision;
- validation failure does not append or advance;
- Save Only remains on the item;
- Skip and Snooze advance without writing a human validation;
- direct queue-row selection changes only the selected chart;
- page rerun and simulated service restart restore the cursor;
- navigation makes no OpenD call and does not invoke a batch detector;
- data-blocked items explain the reason and disable review submission;
- legacy fixture tests continue to pass.

### 16.4 Final regression

Run focused persistence, review, validation, and page tests; the complete Pattern
Finder suite; full repository tests; `compileall`; and `git diff --check`.

## 17. Acceptance criteria

The milestone is accepted only when:

1. a completed, formal Scan Batch can be reopened without recomputation;
2. every eligible machine YES and NO result is accounted for;
3. the user always sees current symbol and queue position;
4. Save and Next writes exactly once and advances exactly once;
5. Previous, Next, Skip, Snooze, Restore, search, and filters are deterministic;
6. closing and reopening the local app restores a valid review position;
7. switching cases performs no network request or whole-batch recomputation;
8. human history remains append-only and old records remain intact;
9. the UI contains no daily target or misleading productivity completion score;
10. failures remain visible and cannot be misread as human or machine NO.

### 17.1 Immediate compatibility gate

Before a formal Snapshot exists, the provisional cache queue may ship when it
provides deterministic position, Previous, Next, Save and Next, search, state
filters, and restart resume while continuously displaying its provisional
warning. Passing this gate improves the current 33-symbol workflow, but it does
not satisfy acceptance criterion 1, cannot be described as M3D formal Scan
Batch completion, and cannot enable formal export.
