from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest

from tv_quant.pattern_finder.application.review_queue import (
    QueueAction,
    QueueActionType,
    QueueCursor,
    QueueFilters,
    QueueSourceKind,
    QueueState,
)
from tv_quant.pattern_finder.persistence.database import SqliteDatabase
from tv_quant.pattern_finder.persistence.review_queue_repository import (
    ReviewQueueRepository,
    ReviewQueueRepositoryError,
)


SOURCE_KIND = QueueSourceKind.PROVISIONAL_CACHE
SOURCE_ID = "cache-source"
PATTERN_TYPE = "flat_base"
CREATED_AT = datetime(2026, 8, 29, 10, 30, tzinfo=UTC)


@pytest.fixture
def database(tmp_path: Path) -> SqliteDatabase:
    result = SqliteDatabase(tmp_path / "pattern-finder.db")
    result.migrate()
    return result


@pytest.fixture
def repository(database: SqliteDatabase) -> ReviewQueueRepository:
    return ReviewQueueRepository(database)


class _TraceDatabase:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database
        self.statements: list[str] = []

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self.database.connect() as connection:
            connection.set_trace_callback(self.statements.append)
            yield connection


def _action(
    action_id: str,
    action_type: QueueActionType,
    *,
    item_id: str = "AAPL-id",
    source_kind: QueueSourceKind = SOURCE_KIND,
    source_id: str = SOURCE_ID,
    created_at_utc: datetime = CREATED_AT,
) -> QueueAction:
    return QueueAction(
        action_id=action_id,
        source_kind=source_kind,
        source_id=source_id,
        item_id=item_id,
        pattern_type=PATTERN_TYPE,
        action_type=action_type,
        created_at_utc=created_at_utc,
    )


def _cursor(
    *,
    item_id: str,
    filters: QueueFilters | None = None,
    updated_at_utc: datetime = CREATED_AT,
) -> QueueCursor:
    return QueueCursor(
        source_kind=SOURCE_KIND,
        source_id=SOURCE_ID,
        pattern_type=PATTERN_TYPE,
        item_id=item_id,
        filters=filters or QueueFilters(),
        updated_at_utc=updated_at_utc,
    )


def _insert_formal_candidate(
    database: SqliteDatabase,
    *,
    scan_batch_id: str = "batch-1",
    candidate_id: str = "candidate-1",
) -> None:
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO universe_snapshots(
                snapshot_id,profile_version_id,draft_id,snapshot_kind,completeness,
                schema_version,as_of_date,created_at_utc,total_count,member_count,
                fail_count,quarantine_count,mapping_hash,prerequisites_hash,members_hash,
                content_hash,record_hash,provenance_json,payload_json
            ) VALUES(?,NULL,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "snapshot-1",
                "FORMAL",
                "COMPLETE",
                "v1",
                "2026-08-27",
                CREATED_AT.isoformat(),
                1,
                1,
                0,
                0,
                "mapping",
                "prerequisites",
                "members",
                "content",
                "record",
                "{}",
                "{}",
            ),
        )
        connection.execute(
            """INSERT INTO scan_batches(
                scan_batch_id,snapshot_id,pattern_type,pattern_version,started_at_utc,
                completed_at_utc,status,input_hash,config_hash,result_hash
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                scan_batch_id,
                "snapshot-1",
                PATTERN_TYPE,
                "phase1-v1",
                CREATED_AT.isoformat(),
                CREATED_AT.isoformat(),
                "COMPLETED",
                "input",
                "config",
                "result",
            ),
        )
        connection.execute(
            """INSERT INTO pattern_candidates(
                candidate_id,scan_batch_id,stock_id,pattern_type,pattern_version,
                signal_date,computer_decision,computer_score,features_json,
                reason_codes_json,created_at_utc
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                candidate_id,
                scan_batch_id,
                "US:AAPL",
                PATTERN_TYPE,
                "phase1-v1",
                "2026-08-27",
                "YES",
                None,
                "{}",
                "[]",
                CREATED_AT.isoformat(),
            ),
        )


def test_provisional_action_and_cursor_round_trip(
    repository: ReviewQueueRepository,
) -> None:
    action = _action("a1", QueueActionType.SNOOZE)
    cursor = _cursor(
        item_id="AAPL-id",
        filters=QueueFilters(
            state=QueueState.SNOOZED,
            symbol_query="AAPL",
        ),
    )

    repository.append_action(action)
    repository.save_cursor(cursor)

    assert repository.latest_actions(
        SOURCE_KIND,
        SOURCE_ID,
        PATTERN_TYPE,
    ) == {"AAPL-id": action}
    assert repository.load_cursor(SOURCE_KIND, SOURCE_ID, PATTERN_TYPE) == cursor


def test_same_action_id_is_idempotent_but_conflicting_payload_fails(
    repository: ReviewQueueRepository,
) -> None:
    action = _action("a1", QueueActionType.SKIP)

    repository.append_action(action)
    repository.append_action(action)

    with pytest.raises(sqlite3.IntegrityError, match="queue action conflict"):
        repository.append_action(replace(action, item_id="other"))

    assert repository.latest_actions(SOURCE_KIND, SOURCE_ID, PATTERN_TYPE) == {
        "AAPL-id": action,
    }


def test_append_action_begins_with_an_immediate_transaction(
    database: SqliteDatabase,
) -> None:
    traced_database = _TraceDatabase(database)
    repository = ReviewQueueRepository(traced_database)  # type: ignore[arg-type]

    repository.append_action(_action("a1", QueueActionType.SKIP))

    assert traced_database.statements[0] == "BEGIN IMMEDIATE"


def test_formal_action_rejects_missing_or_wrong_batch_candidate(
    database: SqliteDatabase,
    repository: ReviewQueueRepository,
) -> None:
    _insert_formal_candidate(database)

    with pytest.raises(ValueError, match="formal candidate does not exist"):
        repository.append_action(
            _action(
                "missing",
                QueueActionType.SKIP,
                item_id="missing",
                source_kind=QueueSourceKind.SCAN_BATCH,
                source_id="batch-1",
            )
        )
    with pytest.raises(ValueError, match="formal candidate does not exist"):
        repository.append_action(
            _action(
                "wrong-batch",
                QueueActionType.SKIP,
                item_id="candidate-1",
                source_kind=QueueSourceKind.SCAN_BATCH,
                source_id="batch-2",
            )
        )

    assert repository.latest_actions(
        QueueSourceKind.SCAN_BATCH,
        "batch-1",
        PATTERN_TYPE,
    ) == {}


def test_formal_action_accepts_candidate_from_its_scan_batch(
    database: SqliteDatabase,
    repository: ReviewQueueRepository,
) -> None:
    _insert_formal_candidate(database)
    action = _action(
        "formal-a1",
        QueueActionType.SNOOZE,
        item_id="candidate-1",
        source_kind=QueueSourceKind.SCAN_BATCH,
        source_id="batch-1",
    )

    repository.append_action(action)

    assert repository.latest_actions(
        QueueSourceKind.SCAN_BATCH,
        "batch-1",
        PATTERN_TYPE,
    ) == {"candidate-1": action}


def test_latest_actions_uses_timestamp_then_action_id_deterministically(
    repository: ReviewQueueRepository,
) -> None:
    later = _action(
        "a0",
        QueueActionType.SNOOZE,
        created_at_utc=CREATED_AT + timedelta(seconds=1),
    )
    earlier = _action("z9", QueueActionType.SKIP)
    same_time_lower_id = _action("a1", QueueActionType.SKIP, item_id="MSFT-id")
    same_time_higher_id = _action("z1", QueueActionType.RESTORE, item_id="MSFT-id")

    for action in (later, same_time_higher_id, earlier, same_time_lower_id):
        repository.append_action(action)

    assert repository.latest_actions(SOURCE_KIND, SOURCE_ID, PATTERN_TYPE) == {
        "AAPL-id": later,
        "MSFT-id": same_time_higher_id,
    }


def test_latest_actions_normalizes_offset_aware_timestamps_to_utc_before_ordering(
    repository: ReviewQueueRepository,
) -> None:
    earlier_in_absolute_time = _action(
        "earlier",
        QueueActionType.SKIP,
        created_at_utc=datetime(
            2026,
            8,
            29,
            5,
            30,
            tzinfo=timezone(timedelta(hours=5)),
        ),
    )
    later_in_absolute_time = _action(
        "later",
        QueueActionType.SNOOZE,
        created_at_utc=datetime(2026, 8, 29, 1, 0, tzinfo=UTC),
    )

    repository.append_action(later_in_absolute_time)
    repository.append_action(earlier_in_absolute_time)

    assert repository.latest_actions(SOURCE_KIND, SOURCE_ID, PATTERN_TYPE) == {
        "AAPL-id": later_in_absolute_time,
    }


def test_append_action_rejects_naive_created_timestamp(
    repository: ReviewQueueRepository,
) -> None:
    naive_action = _action(
        "naive",
        QueueActionType.SKIP,
        created_at_utc=datetime(2026, 8, 29, 1, 0),
    )

    with pytest.raises(ValueError, match="created_at_utc must be timezone-aware"):
        repository.append_action(naive_action)


def test_save_cursor_normalizes_offset_aware_timestamp_to_utc(
    repository: ReviewQueueRepository,
) -> None:
    offset_cursor = _cursor(
        item_id="AAPL-id",
        updated_at_utc=datetime(
            2026,
            8,
            29,
            5,
            30,
            tzinfo=timezone(timedelta(hours=5)),
        ),
    )

    repository.save_cursor(offset_cursor)

    assert repository.load_cursor(SOURCE_KIND, SOURCE_ID, PATTERN_TYPE) == replace(
        offset_cursor,
        updated_at_utc=datetime(2026, 8, 29, 0, 30, tzinfo=UTC),
    )


def test_save_cursor_upserts_only_its_scope_and_missing_scope_returns_none(
    repository: ReviewQueueRepository,
) -> None:
    first = _cursor(item_id="AAPL-id")
    updated = _cursor(
        item_id="MSFT-id",
        filters=QueueFilters(state=QueueState.UNREVIEWED, symbol_query="MSFT"),
        updated_at_utc=CREATED_AT + timedelta(minutes=1),
    )

    repository.save_cursor(first)
    repository.save_cursor(updated)

    assert repository.load_cursor(SOURCE_KIND, SOURCE_ID, PATTERN_TYPE) == updated
    assert repository.load_cursor(SOURCE_KIND, "other-source", PATTERN_TYPE) is None


@pytest.mark.parametrize(
    "filters_json",
    (
        "not-json",
        '{"state":"UNKNOWN","symbol_query":"AAPL"}',
        '{"state":null,"symbol_query":42}',
        "[]",
    ),
)
def test_load_cursor_rejects_corrupt_filter_state(
    database: SqliteDatabase,
    repository: ReviewQueueRepository,
    filters_json: str,
) -> None:
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO review_cursors(
                source_kind,source_id,pattern_type,item_id,filters_json,updated_at_utc
            ) VALUES(?,?,?,?,?,?)""",
            (
                SOURCE_KIND.value,
                SOURCE_ID,
                PATTERN_TYPE,
                "AAPL-id",
                filters_json,
                CREATED_AT.isoformat(),
            ),
        )

    with pytest.raises(ReviewQueueRepositoryError, match="corrupt review cursor"):
        repository.load_cursor(SOURCE_KIND, SOURCE_ID, PATTERN_TYPE)
