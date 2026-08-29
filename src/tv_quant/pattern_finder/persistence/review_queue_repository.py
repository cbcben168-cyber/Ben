"""SQLite persistence for source-aware review queue workflow state."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import sqlite3

from tv_quant.pattern_finder.application.review_queue import (
    QueueAction,
    QueueActionType,
    QueueCursor,
    QueueFilters,
    QueueSourceKind,
    QueueState,
)

from .database import SqliteDatabase


class ReviewQueueRepositoryError(RuntimeError):
    """Persisted review workflow state is invalid or cannot be reconstructed."""


class ReviewQueueRepository:
    """Store append-only queue actions and the mutable cursor projection."""

    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def append_action(self, action: QueueAction) -> None:
        created_at_utc = _normalize_utc(action.created_at_utc, "created_at_utc")
        payload = (
            action.source_kind.value,
            action.source_id,
            action.item_id,
            action.pattern_type,
            action.action_type.value,
            created_at_utc.isoformat(),
        )
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if action.source_kind is QueueSourceKind.SCAN_BATCH:
                    candidate = connection.execute(
                        """SELECT 1 FROM pattern_candidates pc
                           JOIN scan_batches sb ON sb.scan_batch_id = pc.scan_batch_id
                           WHERE pc.candidate_id = ? AND sb.scan_batch_id = ?""",
                        (action.item_id, action.source_id),
                    ).fetchone()
                    if candidate is None:
                        raise ValueError("formal candidate does not exist in scan batch")

                existing = connection.execute(
                    """SELECT source_kind,source_id,item_id,pattern_type,
                              action_type,created_at_utc
                       FROM review_queue_actions WHERE action_id=?""",
                    (action.action_id,),
                ).fetchone()
                if existing is not None:
                    existing_payload = tuple(existing)
                    if existing_payload != payload:
                        raise sqlite3.IntegrityError(
                            f"queue action conflict: {action.action_id}"
                        )
                    connection.execute("ROLLBACK")
                    return

                connection.execute(
                    """INSERT INTO review_queue_actions(
                        action_id,source_kind,source_id,item_id,pattern_type,
                        action_type,created_at_utc
                    ) VALUES(?,?,?,?,?,?,?)""",
                    (action.action_id, *payload),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def latest_actions(
        self,
        source_kind: QueueSourceKind,
        source_id: str,
        pattern_type: str,
    ) -> dict[str, QueueAction]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT action_id,source_kind,source_id,item_id,pattern_type,
                          action_type,created_at_utc
                   FROM review_queue_actions
                   WHERE source_kind=? AND source_id=? AND pattern_type=?
                   ORDER BY created_at_utc, action_id""",
                (source_kind.value, source_id, pattern_type),
            ).fetchall()

        latest: dict[str, QueueAction] = {}
        for row in rows:
            action = QueueAction(
                action_id=row["action_id"],
                source_kind=QueueSourceKind(row["source_kind"]),
                source_id=row["source_id"],
                item_id=row["item_id"],
                pattern_type=row["pattern_type"],
                action_type=QueueActionType(row["action_type"]),
                created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
            )
            latest[action.item_id] = action
        return latest

    def save_cursor(self, cursor: QueueCursor) -> None:
        updated_at_utc = _normalize_utc(cursor.updated_at_utc, "updated_at_utc")
        filters_json = json.dumps(
            {
                "state": None if cursor.filters.state is None else cursor.filters.state.value,
                "symbol_query": cursor.filters.symbol_query,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """INSERT INTO review_cursors(
                        source_kind,source_id,pattern_type,item_id,filters_json,updated_at_utc
                    ) VALUES(?,?,?,?,?,?)
                    ON CONFLICT(source_kind,source_id,pattern_type) DO UPDATE SET
                        item_id=excluded.item_id,
                        filters_json=excluded.filters_json,
                        updated_at_utc=excluded.updated_at_utc""",
                    (
                        cursor.source_kind.value,
                        cursor.source_id,
                        cursor.pattern_type,
                        cursor.item_id,
                        filters_json,
                        updated_at_utc.isoformat(),
                    ),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def load_cursor(
        self,
        source_kind: QueueSourceKind,
        source_id: str,
        pattern_type: str,
    ) -> QueueCursor | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT source_kind,source_id,pattern_type,item_id,
                          filters_json,updated_at_utc
                   FROM review_cursors
                   WHERE source_kind=? AND source_id=? AND pattern_type=?""",
                (source_kind.value, source_id, pattern_type),
            ).fetchone()
        if row is None:
            return None

        try:
            payload = json.loads(row["filters_json"])
            if not isinstance(payload, dict):
                raise TypeError("filters must be a JSON object")
            if set(payload) - {"state", "symbol_query"}:
                raise ValueError("filters contain unsupported fields")
            state_value = payload.get("state")
            state = None if state_value is None else QueueState(state_value)
            symbol_query = payload.get("symbol_query", "")
            if not isinstance(symbol_query, str):
                raise TypeError("symbol_query must be a string")
            filters = QueueFilters(state=state, symbol_query=symbol_query)
            return QueueCursor(
                source_kind=QueueSourceKind(row["source_kind"]),
                source_id=row["source_id"],
                pattern_type=row["pattern_type"],
                item_id=row["item_id"],
                filters=filters,
                updated_at_utc=_normalize_utc(
                    datetime.fromisoformat(row["updated_at_utc"]),
                    "updated_at_utc",
                ),
            )
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise ReviewQueueRepositoryError(
                "corrupt review cursor "
                f"for {source_kind.value}:{source_id}:{pattern_type}"
            ) from error


def _normalize_utc(timestamp: datetime, field_name: str) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return timestamp.astimezone(UTC)
