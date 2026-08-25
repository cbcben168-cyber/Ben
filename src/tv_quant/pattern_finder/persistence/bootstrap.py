"""Writeful local data-foundation bootstrap, owned by the runtime CLI."""

from __future__ import annotations

from tv_quant.pattern_finder.runtime.config import RuntimeConfig, profile_root, snapshot_root
from tv_quant.pattern_finder.universe_foundation import (
    ProfileRegistry,
    UniverseSnapshotStore,
    core_v1,
)

from .database import SqliteDatabase
from .legacy_import import migrate_snapshot_store
from .repositories import ProfileRepository, SnapshotRepository


def initialize_local_foundation(config: RuntimeConfig) -> SqliteDatabase:
    database = SqliteDatabase(config.database_path)
    database.migrate()
    profiles = ProfileRepository(database)
    registry = ProfileRegistry(profile_root(config))
    registry.bootstrap(core_v1())
    for profile in registry.list_published():
        profiles.put_published(profile)
    legacy_root = snapshot_root(config)
    if legacy_root.exists():
        report = migrate_snapshot_store(
            UniverseSnapshotStore(legacy_root), SnapshotRepository(database), dry_run=False
        )
        if report.conflicts or report.errors:
            raise RuntimeError(
                "legacy Snapshot migration failed: "
                f"conflicts={report.conflicts}, errors={'; '.join(report.errors)}"
            )
    return database
