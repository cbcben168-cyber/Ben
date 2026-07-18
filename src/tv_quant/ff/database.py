"""DuckDB persistence for forward-factor records and transactional outboxes."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any

import duckdb


TABLES = frozenset(
    {
        "strategy_versions",
        "universe_versions",
        "universe_members",
        "option_liquidity_daily",
        "option_snapshots",
        "earnings_events",
        "scan_runs",
        "scan_results",
        "signals",
        "positions",
        "position_legs",
        "notifications",
        "sync_outbox",
        "audit_events",
    }
)

_DOUBLE_TYPES = {"DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC"}
_INTEGER_TYPES = {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UBIGINT"}


class DatabaseRecord(dict[str, Any]):
    """A query row that supports both mapping and attribute access."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class ActiveScanError(RuntimeError):
    """Raised when a logical session still has a live scan lease."""


class FFDatabase:
    """Own short-lived DuckDB connections and expose storage operations."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> duckdb.DuckDBPyConnection:
        connection = duckdb.connect(str(self.path))
        connection.execute("SET TimeZone = 'UTC'")
        return connection

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self._connect() as connection:
            connection.execute(schema)

    @contextmanager
    def scan_transaction(self) -> Iterator[FFTransaction]:
        connection = self._connect()
        connection.execute("BEGIN TRANSACTION")
        transaction = FFTransaction(connection)
        try:
            yield transaction
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")
        finally:
            connection.close()

    def table_names(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            ).fetchall()
        return [row[0] for row in rows]

    def count(self, table: str) -> int:
        _require_table(table)
        with self._connect() as connection:
            return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])

    def fetch_all(self, table: str, **filters: object) -> list[DatabaseRecord]:
        _require_table(table)
        with self._connect() as connection:
            columns = _column_types(connection, table)
            unknown = set(filters).difference(columns)
            if unknown:
                raise ValueError(f"unknown {table} columns: {sorted(unknown)}")
            where = ""
            values: list[object] = []
            if filters:
                where = " WHERE " + " AND ".join(f'"{name}" = ?' for name in filters)
                values = list(filters.values())
            cursor = connection.execute(f'SELECT * FROM "{table}"{where}', values)
            names = [item[0] for item in cursor.description]
            return [DatabaseRecord(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def fetch_one(self, table: str, **filters: object) -> DatabaseRecord | None:
        rows = self.fetch_all(table, **filters)
        return rows[0] if rows else None

    def notification(self, idempotency_key: str) -> DatabaseRecord | None:
        return self.fetch_one("notifications", idempotency_key=idempotency_key)

    def notification_count(self) -> int:
        return self.count("notifications")

    def session_timezone(self) -> str:
        with self._connect() as connection:
            return str(connection.execute("SELECT current_setting('TimeZone')").fetchone()[0])

    def enqueue_notification(self, record: Mapping[str, object]) -> None:
        with self.scan_transaction() as transaction:
            transaction.enqueue_notification(record)

    def enqueue_sync(self, record: Mapping[str, object]) -> None:
        with self.scan_transaction() as transaction:
            transaction.enqueue_sync(record)

    def claim_scan(
        self,
        record: Mapping[str, object],
        *,
        now_utc: datetime | None = None,
    ) -> str:
        now = _as_utc(now_utc or datetime.now(timezone.utc), "now_utc")
        with self.scan_transaction() as transaction:
            return transaction.claim_scan(record, now_utc=now)

    def commit_scan(
        self,
        scan_run_id: str,
        *,
        owner_id: str,
        completed_at_utc: datetime,
        now_utc: datetime | None = None,
    ) -> bool:
        with self.scan_transaction() as transaction:
            return transaction.commit_scan(
                scan_run_id,
                owner_id=owner_id,
                completed_at_utc=completed_at_utc,
                now_utc=now_utc or datetime.now(timezone.utc),
            )


class FFTransaction:
    """Repository bound to one caller-controlled DuckDB transaction."""

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    def insert(self, table: str, record: Mapping[str, object]) -> bool:
        _require_table(table)
        normalized = _normalize_record(self._connection, table, record)
        names = list(normalized)
        quoted = ", ".join(f'"{name}"' for name in names)
        placeholders = ", ".join("?" for _ in names)
        result = self._connection.execute(
            f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders}) '
            "ON CONFLICT DO NOTHING RETURNING 1",
            list(normalized.values()),
        ).fetchone()
        return result is not None

    def insert_strategy_version(self, record: Mapping[str, object]) -> bool:
        return self.insert("strategy_versions", record)

    def insert_universe_version(self, record: Mapping[str, object]) -> bool:
        return self.insert("universe_versions", record)

    def insert_universe_member(self, record: Mapping[str, object]) -> bool:
        return self.insert("universe_members", record)

    def insert_option_liquidity_daily(self, record: Mapping[str, object]) -> bool:
        return self.insert("option_liquidity_daily", record)

    def insert_option_snapshot(self, record: Mapping[str, object]) -> bool:
        return self.insert("option_snapshots", record)

    def insert_earnings_event(self, record: Mapping[str, object]) -> bool:
        return self.insert("earnings_events", record)

    def insert_scan_run(self, record: Mapping[str, object]) -> bool:
        return self.insert("scan_runs", record)

    def insert_scan_result(self, record: Mapping[str, object]) -> bool:
        return self.insert("scan_results", record)

    def insert_signal(self, record: Mapping[str, object]) -> bool:
        return self.insert("signals", record)

    def insert_position(self, record: Mapping[str, object]) -> bool:
        return self.insert("positions", record)

    def insert_position_leg(self, record: Mapping[str, object]) -> bool:
        return self.insert("position_legs", record)

    def enqueue_notification(self, record: Mapping[str, object]) -> bool:
        return self.insert("notifications", record)

    def enqueue_sync(self, record: Mapping[str, object]) -> bool:
        return self.insert("sync_outbox", record)

    def insert_audit_event(self, record: Mapping[str, object]) -> bool:
        return self.insert("audit_events", record)

    def claim_scan(self, record: Mapping[str, object], *, now_utc: datetime) -> str:
        normalized = _normalize_record(self._connection, "scan_runs", record)
        required = {
            "scan_run_id",
            "strategy_version",
            "logical_session_date",
            "status",
            "owner_id",
            "claimed_at_utc",
            "lease_expires_at_utc",
        }
        missing = required.difference(normalized)
        if missing:
            raise ValueError(f"missing scan claim fields: {sorted(missing)}")
        if normalized["status"] != "ACTIVE":
            raise ValueError("scan claim status must be ACTIVE")
        lease_expires = normalized["lease_expires_at_utc"]
        if not isinstance(lease_expires, datetime) or lease_expires <= now_utc:
            raise ValueError("scan lease must expire after now_utc")

        existing = self._connection.execute(
            """
            SELECT scan_run_id, status, owner_id, lease_expires_at_utc
            FROM scan_runs
            WHERE strategy_version = ? AND logical_session_date = ?
            """,
            [normalized["strategy_version"], normalized["logical_session_date"]],
        ).fetchone()
        if existing is None:
            if not self.insert_scan_run(normalized):
                raise ActiveScanError("logical session claim lost to another active scan")
            return str(normalized["scan_run_id"])

        existing_run_id, status, previous_owner, previous_expiry = existing
        if status == "ACTIVE" and previous_expiry is not None and previous_expiry > now_utc:
            raise ActiveScanError(
                f"scan {existing_run_id} is already active for this logical session"
            )
        if status != "ACTIVE":
            raise ActiveScanError(
                f"logical session already has terminal scan {existing_run_id} with status {status}"
            )

        updated = self._connection.execute(
            """
            UPDATE scan_runs
            SET universe_version = ?, owner_id = ?, claimed_at_utc = ?,
                lease_expires_at_utc = ?, completed_at_utc = NULL, status = 'ACTIVE'
            WHERE scan_run_id = ? AND status = 'ACTIVE' AND lease_expires_at_utc = ?
            RETURNING scan_run_id
            """,
            [
                normalized.get("universe_version"),
                normalized["owner_id"],
                normalized["claimed_at_utc"],
                lease_expires,
                existing_run_id,
                previous_expiry,
            ],
        ).fetchone()
        if updated is None:
            raise ActiveScanError("expired scan lease was changed before takeover")

        audit_id = sha256(
            (
                f"SCAN_LEASE_TAKEN_OVER|{existing_run_id}|{previous_owner}|"
                f"{normalized['owner_id']}|{now_utc.isoformat()}"
            ).encode("utf-8")
        ).hexdigest()
        self.insert_audit_event(
            {
                "audit_event_id": audit_id,
                "event_type": "SCAN_LEASE_TAKEN_OVER",
                "record_type": "scan_run",
                "record_id": existing_run_id,
                "actor_id": normalized["owner_id"],
                "details_json": {
                    "previous_owner_id": previous_owner,
                    "new_owner_id": normalized["owner_id"],
                    "previous_lease_expires_at_utc": previous_expiry.isoformat(),
                },
                "created_at_utc": now_utc,
            }
        )
        return str(existing_run_id)

    def commit_scan(
        self,
        scan_run_id: str,
        *,
        owner_id: str,
        completed_at_utc: datetime,
        now_utc: datetime,
    ) -> bool:
        completed = _as_utc(completed_at_utc, "completed_at_utc")
        now = _as_utc(now_utc, "now_utc")
        row = self._connection.execute(
            """
            UPDATE scan_runs
            SET status = 'COMMITTED', completed_at_utc = ?, lease_expires_at_utc = NULL
            WHERE scan_run_id = ? AND owner_id = ? AND status = 'ACTIVE'
              AND lease_expires_at_utc > ?
            RETURNING scan_run_id
            """,
            [completed, scan_run_id, owner_id, now],
        ).fetchone()
        return row is not None


def _require_table(table: str) -> None:
    if table not in TABLES:
        raise ValueError(f"unknown table: {table}")


def _as_utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _column_types(connection: duckdb.DuckDBPyConnection, table: str) -> dict[str, str]:
    rows = connection.execute(f"PRAGMA table_info('{table}')").fetchall()
    return {row[1]: row[2].upper() for row in rows}


def _normalize_record(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    record: Mapping[str, object],
) -> dict[str, object]:
    if not record:
        raise ValueError(f"{table} record must not be empty")
    columns = _column_types(connection, table)
    unknown = set(record).difference(columns)
    if unknown:
        raise ValueError(f"unknown {table} columns: {sorted(unknown)}")

    normalized: dict[str, object] = {}
    for name, value in record.items():
        column_type = columns[name]
        if value is None:
            normalized[name] = None
        elif column_type in _DOUBLE_TYPES or column_type.startswith("DECIMAL"):
            if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
                raise ValueError(f"{table}.{name} must be numeric")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"{table}.{name} must be finite")
            normalized[name] = number
        elif column_type in _INTEGER_TYPES:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{table}.{name} must be an integer")
            normalized[name] = value
        elif column_type == "TIMESTAMP WITH TIME ZONE":
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{table}.{name} must be timezone-aware")
            normalized[name] = value.astimezone(timezone.utc)
        elif column_type == "DATE":
            if not isinstance(value, date) or isinstance(value, datetime):
                raise ValueError(f"{table}.{name} must be a date")
            normalized[name] = value
        elif column_type == "JSON" and not isinstance(value, str):
            normalized[name] = json.dumps(value, sort_keys=True, separators=(",", ":"))
        else:
            normalized[name] = value
    return normalized
