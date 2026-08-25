"""Non-destructive import of validated legacy Snapshot files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from tv_quant.pattern_finder.universe_foundation.snapshots import UniverseSnapshotStore

from .repositories import SnapshotRepository


@dataclass(frozen=True, slots=True)
class MigrationReport:
    discovered: int
    validated: int
    imported: int
    skipped: int
    conflicts: int
    errors: tuple[str, ...]


def migrate_snapshot_store(
    source: UniverseSnapshotStore,
    target: SnapshotRepository,
    *,
    dry_run: bool,
) -> MigrationReport:
    root = Path(source._root)  # Store owns validation; importer only enumerates IDs.
    paths = tuple(sorted(root.glob("*.json"))) if root.exists() else ()
    validated = imported = skipped = conflicts = 0
    errors: list[str] = []
    for path in paths:
        try:
            snapshot_id = UUID(path.stem)
            snapshot = source.get(snapshot_id)
            validated += 1
            if dry_run:
                continue
            try:
                existing = target.get(snapshot_id)
            except Exception as error:
                if "not found" not in str(error).lower():
                    raise
            else:
                if existing.header.snapshot_record_sha256 == snapshot.header.snapshot_record_sha256:
                    skipped += 1
                    continue
                conflicts += 1
                continue
            loaded = target.append(snapshot)
            if (
                len(loaded.rows) != len(snapshot.rows)
                or loaded.header.members_sha256 != snapshot.header.members_sha256
                or loaded.header.snapshot_content_sha256 != snapshot.header.snapshot_content_sha256
                or loaded.header.snapshot_record_sha256 != snapshot.header.snapshot_record_sha256
            ):
                conflicts += 1
                continue
            imported += 1
        except Exception as error:
            errors.append(f"{path.name}: {error}")
    return MigrationReport(len(paths), validated, imported, skipped, conflicts, tuple(errors))
