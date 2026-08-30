"""Atomic persistence for immutable completed Pattern Finder scan batches."""

from __future__ import annotations

from datetime import datetime
import json
import sqlite3
from uuid import UUID

from tv_quant.pattern_finder.application.scan_persistence import (
    CompletedScanBatch,
    MachineDecision,
    PATTERN_TYPE,
    SCAN_PROVENANCE_VERSION,
    ScanManifest,
    ScanResult,
    _hash_json,
)
from tv_quant.pattern_finder.universe_foundation import (
    Completeness,
    SnapshotKind,
)

from .database import SqliteDatabase
from .repositories import SnapshotRepository


class ScanPersistenceError(RuntimeError):
    """Base error for persisted formal scan batches."""


class ScanConflictError(ScanPersistenceError):
    """The canonical ID is already bound to different content."""


class ScanNotFoundError(ScanPersistenceError):
    """A requested completed scan batch does not exist."""


class ScanCorruptError(ScanPersistenceError):
    """Persisted scan content violates its canonical contract."""


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _computed_result_hash(results: tuple[ScanResult, ...]) -> str:
    return _hash_json(
        tuple(
            {
                "candidate_id": result.candidate_id,
                "scan_batch_id": result.scan_batch_id,
                "source_rank": result.source_rank,
                "stock_id": result.stock_id,
                "symbol": result.symbol,
                "pattern_type": result.pattern_type,
                "pattern_version": result.pattern_version,
                "signal_date": result.signal_date,
                "decision": result.computer_decision,
                "features": result.features,
                "reason_codes": result.reason_codes,
                "created_at_utc": result.created_at_utc,
            }
            for result in results
        )
    )


def _computed_config_hash(batch: CompletedScanBatch) -> str:
    provenance = batch.manifest.provenance
    return _hash_json(
        {
            "pattern_type": PATTERN_TYPE,
            "pattern_version": batch.pattern_version,
            "profile_version_id": batch.profile_version_id,
            "profile_content_sha256": provenance.get("profile_content_sha256"),
            "adjustment": provenance.get("adjustment"),
            "provenance_version": provenance.get("builder_version"),
        }
    )


def _computed_batch_id(batch: CompletedScanBatch) -> str:
    return "scan-" + _hash_json(
        {
            "snapshot_id": batch.snapshot_id,
            "snapshot_sha256": batch.manifest.provenance.get("snapshot_sha256"),
            "completed_at_utc": batch.completed_at_utc,
            "code_commit": batch.manifest.code_commit,
            "input_hash": batch.input_hash,
            "config_hash": batch.config_hash,
        }
    )


class ScanRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def append_completed(self, batch: CompletedScanBatch) -> CompletedScanBatch:
        if type(batch) is not CompletedScanBatch:
            raise TypeError("batch: CompletedScanBatch required")
        snapshot = SnapshotRepository(self.database).get(UUID(batch.snapshot_id))
        header = snapshot.header
        if (
            header.snapshot_kind is not SnapshotKind.FORMAL
            or header.completeness is not Completeness.COMPLETE
            or header.profile_version_id != batch.profile_version_id
        ):
            raise ValueError("formal complete Snapshot binding required")
        provenance = batch.manifest.provenance
        members = tuple(row for row in snapshot.rows if row.is_member)
        if (
            provenance.get("snapshot_sha256") != header.snapshot_sha256
            or provenance.get("profile_content_sha256")
            != header.profile_content_sha256
            or batch.manifest.scan_as_of_date != header.as_of_session.isoformat()
            or tuple((result.stock_id, result.symbol) for result in batch.results)
            != tuple((member.stock_id, member.symbol) for member in members)
        ):
            raise ValueError("Snapshot content binding mismatch")

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT 1 FROM scan_batches WHERE scan_batch_id=?",
                    (batch.scan_batch_id,),
                ).fetchone()
                if existing is not None:
                    persisted = self._get(connection, batch.scan_batch_id)
                    if persisted != batch:
                        raise ScanConflictError(
                            f"scan batch conflict: {batch.scan_batch_id}"
                        )
                    connection.execute("ROLLBACK")
                    return persisted

                connection.execute(
                    """INSERT INTO scan_batches(
                        scan_batch_id,snapshot_id,pattern_type,pattern_version,
                        started_at_utc,completed_at_utc,status,input_hash,config_hash,
                        result_hash
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        batch.scan_batch_id,
                        batch.snapshot_id,
                        batch.pattern_type,
                        batch.pattern_version,
                        batch.started_at_utc.isoformat(),
                        batch.completed_at_utc.isoformat(),
                        batch.status,
                        batch.input_hash,
                        batch.config_hash,
                        batch.result_hash,
                    ),
                )
                manifest = batch.manifest
                connection.execute(
                    """INSERT INTO scan_batch_manifests(
                        scan_batch_id,scan_as_of_date,ordered_input_count,
                        quality_pass_count,quality_fail_count,yes_count,no_count,
                        code_commit,ordered_input_hash,provenance_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        batch.scan_batch_id,
                        manifest.scan_as_of_date,
                        manifest.ordered_input_count,
                        manifest.quality_pass_count,
                        manifest.quality_fail_count,
                        manifest.yes_count,
                        manifest.no_count,
                        manifest.code_commit,
                        manifest.ordered_input_hash,
                        _json(dict(manifest.provenance)),
                    ),
                )
                for result in batch.results:
                    stored_features = dict(result.features)
                    if "source_rank" in stored_features or "symbol" in stored_features:
                        raise ValueError("reserved persisted feature key")
                    stored_features.update(
                        {"source_rank": result.source_rank, "symbol": result.symbol}
                    )
                    connection.execute(
                        """INSERT INTO pattern_candidates(
                            candidate_id,scan_batch_id,stock_id,pattern_type,
                            pattern_version,signal_date,computer_decision,
                            computer_score,features_json,reason_codes_json,
                            created_at_utc
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            result.candidate_id,
                            result.scan_batch_id,
                            result.stock_id,
                            result.pattern_type,
                            result.pattern_version,
                            result.signal_date,
                            result.computer_decision.value,
                            None,
                            _json(stored_features),
                            _json(result.reason_codes),
                            result.created_at_utc.isoformat(),
                        ),
                    )

                persisted = self._get(connection, batch.scan_batch_id)
                if persisted != batch:
                    raise ScanCorruptError("scan batch write-back mismatch")
                count = connection.execute(
                    "SELECT count(*) FROM pattern_candidates WHERE scan_batch_id=?",
                    (batch.scan_batch_id,),
                ).fetchone()[0]
                if count != batch.manifest.ordered_input_count:
                    raise ScanCorruptError("scan batch candidate count mismatch")
                connection.execute("COMMIT")
                return persisted
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def get(self, scan_batch_id: str) -> CompletedScanBatch:
        with self.database.connect() as connection:
            return self._get(connection, scan_batch_id)

    def list_completed(self) -> tuple[CompletedScanBatch, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT scan_batch_id FROM scan_batches
                   WHERE status='COMPLETED'
                   ORDER BY completed_at_utc DESC, scan_batch_id"""
            ).fetchall()
            return tuple(self._get(connection, row[0]) for row in rows)

    def latest(self) -> CompletedScanBatch | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT scan_batch_id FROM scan_batches
                   WHERE status='COMPLETED'
                   ORDER BY completed_at_utc DESC, scan_batch_id LIMIT 1"""
            ).fetchone()
            return None if row is None else self._get(connection, row[0])

    def candidate_count(self, scan_batch_id: str | None = None) -> int:
        with self.database.connect() as connection:
            if scan_batch_id is None:
                row = connection.execute(
                    "SELECT count(*) FROM pattern_candidates"
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT count(*) FROM pattern_candidates WHERE scan_batch_id=?",
                    (scan_batch_id,),
                ).fetchone()
        return int(row[0])

    def _get(
        self, connection: sqlite3.Connection, scan_batch_id: str
    ) -> CompletedScanBatch:
        header = connection.execute(
            """SELECT sb.*,us.profile_version_id
               FROM scan_batches sb
               JOIN universe_snapshots us ON us.snapshot_id=sb.snapshot_id
               WHERE sb.scan_batch_id=? AND sb.status='COMPLETED'""",
            (scan_batch_id,),
        ).fetchone()
        if header is None:
            raise ScanNotFoundError(f"scan batch not found: {scan_batch_id}")
        manifest_row = connection.execute(
            "SELECT * FROM scan_batch_manifests WHERE scan_batch_id=?",
            (scan_batch_id,),
        ).fetchone()
        if manifest_row is None:
            raise ScanCorruptError("scan batch manifest missing")
        candidate_rows = connection.execute(
            "SELECT * FROM pattern_candidates WHERE scan_batch_id=?",
            (scan_batch_id,),
        ).fetchall()
        try:
            manifest = ScanManifest(
                scan_as_of_date=manifest_row["scan_as_of_date"],
                ordered_input_count=manifest_row["ordered_input_count"],
                quality_pass_count=manifest_row["quality_pass_count"],
                quality_fail_count=manifest_row["quality_fail_count"],
                yes_count=manifest_row["yes_count"],
                no_count=manifest_row["no_count"],
                code_commit=manifest_row["code_commit"],
                ordered_input_hash=manifest_row["ordered_input_hash"],
                provenance=json.loads(manifest_row["provenance_json"]),
            )
            results: list[ScanResult] = []
            for row in candidate_rows:
                features = json.loads(row["features_json"])
                source_rank = features.pop("source_rank")
                symbol = features.pop("symbol")
                results.append(
                    ScanResult(
                        candidate_id=row["candidate_id"],
                        scan_batch_id=row["scan_batch_id"],
                        source_rank=source_rank,
                        stock_id=row["stock_id"],
                        symbol=symbol,
                        pattern_type=row["pattern_type"],
                        pattern_version=row["pattern_version"],
                        signal_date=row["signal_date"],
                        computer_decision=MachineDecision(row["computer_decision"]),
                        features=features,
                        reason_codes=tuple(json.loads(row["reason_codes_json"])),
                        created_at_utc=_parse_datetime(row["created_at_utc"]),
                    )
                )
            ordered_results = tuple(sorted(results, key=lambda result: result.source_rank))
            batch = CompletedScanBatch(
                scan_batch_id=header["scan_batch_id"],
                snapshot_id=header["snapshot_id"],
                profile_version_id=header["profile_version_id"],
                pattern_type=header["pattern_type"],
                pattern_version=header["pattern_version"],
                started_at_utc=_parse_datetime(header["started_at_utc"]),
                completed_at_utc=_parse_datetime(header["completed_at_utc"]),
                status=header["status"],
                input_hash=header["input_hash"],
                config_hash=header["config_hash"],
                result_hash=header["result_hash"],
                manifest=manifest,
                results=ordered_results,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ScanCorruptError(f"invalid persisted scan batch: {error}") from error
        if _computed_result_hash(batch.results) != batch.result_hash:
            raise ScanCorruptError("result hash mismatch")
        if batch.manifest.provenance.get("builder_version") != SCAN_PROVENANCE_VERSION:
            raise ScanCorruptError("builder provenance mismatch")
        if _computed_config_hash(batch) != batch.config_hash:
            raise ScanCorruptError("config hash mismatch")
        if _computed_batch_id(batch) != batch.scan_batch_id:
            raise ScanCorruptError("batch ID mismatch")
        return batch


__all__ = (
    "ScanConflictError",
    "ScanCorruptError",
    "ScanNotFoundError",
    "ScanPersistenceError",
    "ScanRepository",
)
