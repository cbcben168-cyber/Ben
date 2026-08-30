"""SQLite persistence boundary for Pattern Finder."""

from .database import Migration, MigrationError, SqliteDatabase
from .review_queue_repository import (
    ReviewQueueRepository,
    ReviewQueueRepositoryError,
)
from .scan_repository import (
    ScanConflictError,
    ScanCorruptError,
    ScanNotFoundError,
    ScanPersistenceError,
    ScanRepository,
)
from .repositories import (
    BacktestRepository,
    ProfileRepository,
    ReviewRepository,
    SnapshotRepository,
    SystemRepository,
)

__all__ = (
    "BacktestRepository",
    "Migration",
    "MigrationError",
    "ProfileRepository",
    "ReviewRepository",
    "ReviewQueueRepository",
    "ReviewQueueRepositoryError",
    "ScanConflictError",
    "ScanCorruptError",
    "ScanNotFoundError",
    "ScanPersistenceError",
    "ScanRepository",
    "SnapshotRepository",
    "SqliteDatabase",
    "SystemRepository",
)
