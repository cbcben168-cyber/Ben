"""Repository implementations; the sole application-facing SQL boundary."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
import json
import sqlite3
from typing import Any
from uuid import UUID, uuid4

from tv_quant.pattern_finder.universe_foundation.profiles import (
    RecordState,
    UniverseProfile,
    canonical_filter_payload,
)
from tv_quant.pattern_finder.universe_foundation.registry import (
    _profile_from_payload,
    _profile_payload,
)
from tv_quant.pattern_finder.universe_foundation.snapshots import (
    SnapshotConflictError,
    SnapshotNotFoundError,
    UniverseSnapshot,
    _canonical_json_bytes,
    _snapshot_from_payload,
)

from .database import SqliteDatabase


def _json(value: object) -> str:
    def default(item: object) -> object:
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, (Decimal, UUID)):
            return str(item)
        if hasattr(item, "isoformat"):
            return item.isoformat()  # type: ignore[no-any-return]
        if hasattr(item, "__dataclass_fields__"):
            return asdict(item)  # type: ignore[arg-type]
        return str(item)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=default)


class ProfileRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def put_published(self, profile: UniverseProfile) -> None:
        if profile.record_state is not RecordState.PUBLISHED:
            raise ValueError("published profile required")
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT content_sha256 FROM profile_versions WHERE profile_version_id=?",
                    (profile.profile_version_id,),
                ).fetchone()
                if existing:
                    if existing[0] != profile.content_sha256:
                        raise sqlite3.IntegrityError("published profile version conflict")
                    connection.execute("ROLLBACK")
                    return
                connection.execute(
                    "INSERT OR IGNORE INTO profiles(profile_id,profile_kind,display_name,created_at_utc) VALUES(?,?,?,?)",
                    (profile.profile_family_id, profile.profile_kind.value, profile.display_name, profile.created_at_utc.isoformat()),
                )
                connection.execute(
                    """INSERT INTO profile_versions(
                        profile_version_id,profile_id,version,status,parent_profile_version_id,
                        created_at_utc,published_at_utc,change_note,schema_version,profile_payload_json,
                        content_sha256,filter_content_sha256
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        profile.profile_version_id, profile.profile_family_id, profile.profile_version,
                        profile.record_state.value, profile.parent_profile_version_id,
                        profile.created_at_utc.isoformat(), profile.published_at_utc.isoformat(),
                        profile.change_note, profile.schema_version, _json(_profile_payload(profile)),
                        profile.content_sha256, profile.filter_content_sha256,
                    ),
                )
                connection.execute(
                    "INSERT INTO profile_rules(profile_version_id,rules_json) VALUES(?,?)",
                    (profile.profile_version_id, _json(canonical_filter_payload(profile.filters))),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def get_published(self, profile_version_id: str) -> UniverseProfile | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT pv.profile_payload_json, pv.content_sha256,
                          pv.filter_content_sha256, pr.rules_json
                   FROM profile_versions pv JOIN profiles p ON p.profile_id=pv.profile_id
                   JOIN profile_rules pr ON pr.profile_version_id=pv.profile_version_id
                   WHERE pv.profile_version_id=? AND pv.status='PUBLISHED'""",
                (profile_version_id,),
            ).fetchone()
        if row is None:
            return None
        profile = _profile_from_payload(json.loads(row["profile_payload_json"]))
        if profile.content_sha256 != row["content_sha256"]:
            raise ValueError("profile content hash column mismatch")
        if profile.filter_content_sha256 != row["filter_content_sha256"]:
            raise ValueError("profile filter hash column mismatch")
        if json.loads(row["rules_json"]) != canonical_filter_payload(profile.filters):
            raise ValueError("profile rules payload mismatch")
        return profile

    def active(self) -> dict[str, object] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT pv.*, p.display_name FROM profile_versions pv
                   JOIN profiles p ON p.profile_id=pv.profile_id
                   WHERE pv.status='PUBLISHED' ORDER BY pv.published_at_utc DESC LIMIT 1"""
            ).fetchone()
        return None if row is None else dict(row)


class SnapshotRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def append(self, snapshot: UniverseSnapshot) -> UniverseSnapshot:
        snapshot = UniverseSnapshot(snapshot.header, snapshot.rows, snapshot.funnel)
        snapshot_id = str(snapshot.header.universe_snapshot_id)
        payload = _canonical_json_bytes(snapshot).decode("utf-8")
        header = snapshot.header
        fail_count = header.candidate_count - header.member_count - header.quarantine_count
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT record_hash FROM universe_snapshots WHERE snapshot_id=?", (snapshot_id,)
                ).fetchone()
                if existing:
                    if existing[0] != header.snapshot_record_sha256:
                        raise SnapshotConflictError(f"snapshot ID already exists: {snapshot_id}")
                    connection.execute("ROLLBACK")
                    return self.get(header.universe_snapshot_id)
                connection.execute(
                    """INSERT INTO universe_snapshots(
                        snapshot_id,profile_version_id,draft_id,snapshot_kind,completeness,schema_version,
                        as_of_date,created_at_utc,total_count,member_count,fail_count,quarantine_count,
                        mapping_hash,prerequisites_hash,members_hash,content_hash,record_hash,
                        provenance_json,payload_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        snapshot_id, header.profile_version_id, header.draft_id, header.snapshot_kind.value,
                        header.completeness.value, header.snapshot_schema_version, header.as_of_session.isoformat(),
                        header.created_at_utc.isoformat(), header.candidate_count, header.member_count,
                        fail_count, header.quarantine_count, header.active_status_mapping_sha256,
                        header.prerequisites_sha256, header.members_sha256, header.snapshot_content_sha256,
                        header.snapshot_record_sha256,
                        _json({"gateway_attempt_id": header.gateway_attempt_id,
                               "gateway_attempt_sha256": header.gateway_attempt_sha256,
                               "provider": header.provider,
                               "provider_sdk_version": header.provider_sdk_version,
                               "opend_server_version": header.opend_server_version}),
                        payload,
                    ),
                )
                for row in snapshot.rows:
                    status = "QUARANTINE" if row.is_quarantined else "MEMBER" if row.is_member else "FAIL"
                    connection.execute(
                        """INSERT INTO snapshot_securities(
                            snapshot_id,stock_id,futu_code,symbol,name,exchange,security_type,industry_raw,
                            price,market_cap,adv20,listing_days,final_status,first_exit_stage,row_json
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            snapshot_id, row.stock_id, row.futu_code, row.symbol, row.name,
                            row.exchange_normalized, row.security_class_normalized, row.raw_industry.raw_value,
                            None if row.price_usd is None else str(row.price_usd),
                            None if row.market_cap_usd is None else str(row.market_cap_usd),
                            None if row.avg_turnover_20d_usd is None else str(row.avg_turnover_20d_usd),
                            row.listed_days, status, row.first_exit_stage, _json(row),
                        ),
                    )
                    decisions: list[tuple[int, str, str, str, object, object, object]] = [
                        (0, "S0", "S0_DISCOVERED_US_CASH_SECURITIES", "PASS", "DISCOVERED_US_CASH_SECURITY", None, ()),
                    ]
                    decisions.extend(
                        (
                            index, f"S{index}", decision.field_id, decision.decision.value,
                            decision.reason_code, decision.raw_value, decision.threshold,
                        )
                        for index, decision in enumerate(row.field_decisions, start=1)
                    )
                    s10_decision = "UNKNOWN" if row.is_quarantined else "PASS" if row.is_member else "FAIL"
                    s10_reason = "CORE_MEMBER" if row.is_member else row.first_exit_reason_code or "CORE_NOT_MEMBER"
                    decisions.append((10, "S10", "S10_CORE_UNIVERSE", s10_decision, s10_reason, status, None))
                    for order, stage, stage_id, decision, reason, observed, threshold in decisions:
                        source = () if order in (0, 10) else row.field_decisions[order - 1].evidence_references
                        connection.execute(
                            """INSERT INTO snapshot_security_decisions(
                                snapshot_id,stock_id,futu_code,stage,stage_order,stage_id,decision,
                                reason_code,observed_value_json,threshold_json,evidence_json
                            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (snapshot_id, row.stock_id, row.futu_code, stage, order, stage_id, decision,
                             str(reason), _json(observed), _json(threshold), _json(source)),
                        )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return self.get(header.universe_snapshot_id)

    def get(self, snapshot_id: UUID) -> UniverseSnapshot:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM universe_snapshots WHERE snapshot_id=?", (str(snapshot_id),)
            ).fetchone()
        if row is None:
            raise SnapshotNotFoundError(f"snapshot not found: {snapshot_id}")
        snapshot = _snapshot_from_payload(json.loads(row[0]))
        if snapshot.header.universe_snapshot_id != snapshot_id:
            raise SnapshotConflictError("snapshot ID/payload binding mismatch")
        return snapshot

    def latest_summary(self) -> dict[str, object] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM universe_snapshots ORDER BY created_at_utc DESC LIMIT 1"
            ).fetchone()
        return None if row is None else dict(row)


class SystemRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def start_app_run(
        self,
        run_id: str,
        pid: int,
        port: int,
        *,
        app_version: str | None = None,
        git_commit: str | None = None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO app_runs(
                    run_id,started_at_utc,status,pid,port,app_version,git_commit
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    run_id, datetime.now(UTC).isoformat(), "RUNNING", pid, port,
                    app_version, git_commit,
                ),
            )

    def finish_app_run(self, run_id: str, status: str, error: str | None) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE app_runs SET stopped_at_utc=?,status=?,error_summary=? WHERE run_id=?",
                (datetime.now(UTC).isoformat(), status, error, run_id),
            )

    def latest_run(self) -> dict[str, object] | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM app_runs ORDER BY started_at_utc DESC LIMIT 1").fetchone()
        return None if row is None else dict(row)

    def latest_migration(self) -> dict[str, object] | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM schema_migrations ORDER BY version DESC LIMIT 1").fetchone()
        return None if row is None else dict(row)


class ScanRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def latest(self) -> dict[str, object] | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM scan_batches ORDER BY coalesce(completed_at_utc,started_at_utc) DESC LIMIT 1").fetchone()
        return None if row is None else dict(row)

    def candidate_count(self) -> int:
        with self.database.connect() as connection:
            return int(connection.execute("SELECT count(*) FROM pattern_candidates").fetchone()[0])


class ReviewRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def pending_count(self) -> int:
        with self.database.connect() as connection:
            return int(connection.execute(
                """SELECT count(*) FROM pattern_candidates pc
                   WHERE NOT EXISTS (SELECT 1 FROM manual_reviews mr WHERE mr.candidate_id=pc.candidate_id)"""
            ).fetchone()[0])


class BacktestRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def latest(self) -> dict[str, object] | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM backtest_runs ORDER BY created_at_utc DESC LIMIT 1").fetchone()
        return None if row is None else dict(row)
