"""Transactional, versioned SQLite owner."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import sqlite3
from typing import Iterator, Sequence

from .migrations import MIGRATION_1_STATEMENTS


class MigrationError(RuntimeError):
    """A schema migration failed and was rolled back."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    migration_id: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        return hashlib.sha256("\0".join(self.statements).encode("utf-8")).hexdigest()


DEFAULT_MIGRATIONS = (Migration(1, "0001_pattern_finder_foundation", MIGRATION_1_STATEMENTS),)


class SqliteDatabase:
    def __init__(self, path: str | Path, *, migrations: Sequence[Migration] = DEFAULT_MIGRATIONS) -> None:
        self.path = Path(path).resolve()
        self.migrations = tuple(migrations)
        versions = tuple(item.version for item in self.migrations)
        if versions != tuple(range(1, len(versions) + 1)):
            raise ValueError("migrations must be contiguous from version 1")

    @property
    def latest_version(self) -> int:
        return len(self.migrations)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

    def current_version(self) -> int:
        if not self.path.exists():
            return 0
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            if not exists:
                return 0
            row = connection.execute("SELECT coalesce(max(version), 0) FROM schema_migrations").fetchone()
            return int(row[0])

    def validate_schema(self) -> int:
        """Validate the complete migration ledger without changing the database."""
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            if not exists:
                raise MigrationError("database schema is not initialized")
            rows = connection.execute(
                "SELECT version, migration_id, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
        if len(rows) > len(self.migrations):
            raise MigrationError("database schema is newer than this application")
        for index, row in enumerate(rows):
            expected = self.migrations[index]
            if row["version"] != expected.version or row["migration_id"] != expected.migration_id:
                raise MigrationError(f"migration ledger mismatch at version {expected.version}")
            if row["checksum"] != expected.checksum:
                raise MigrationError(f"migration checksum mismatch at version {expected.version}")
        if len(rows) != len(self.migrations):
            raise MigrationError("database schema version is not current")
        return len(rows)

    def migrate(self) -> int:
        with self.connect() as connection:
            rows: list[sqlite3.Row] = []
            try:
                connection.execute("BEGIN IMMEDIATE")
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
                ).fetchone()
                rows = [] if not exists else connection.execute(
                    "SELECT version, migration_id, checksum FROM schema_migrations ORDER BY version"
                ).fetchall()
                if len(rows) > len(self.migrations):
                    raise MigrationError("database schema is newer than this application")
                for index, row in enumerate(rows):
                    expected = self.migrations[index]
                    if row["version"] != expected.version or row["migration_id"] != expected.migration_id:
                        raise MigrationError(f"migration ledger mismatch at version {expected.version}")
                    if row["checksum"] != expected.checksum:
                        raise MigrationError(f"migration checksum mismatch at version {expected.version}")
                for migration in self.migrations[len(rows):]:
                    for statement in migration.statements:
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO schema_migrations(version,migration_id,checksum,applied_at_utc) VALUES(?,?,?,?)",
                        (migration.version, migration.migration_id, migration.checksum, datetime.now(UTC).isoformat()),
                    )
                connection.execute("COMMIT")
            except (sqlite3.Error, MigrationError) as error:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                if isinstance(error, MigrationError):
                    raise
                version = self.migrations[len(rows)].version if len(rows) < len(self.migrations) else "validation"
                raise MigrationError(f"migration {version} failed: {error}") from error
        return self.latest_version
