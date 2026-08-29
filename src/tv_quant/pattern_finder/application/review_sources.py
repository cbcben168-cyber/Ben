"""Source adapters for review-queue items.

The local cache adapter deliberately does not represent a formal scan batch:
it projects cache and validation metadata only, without invoking a detector.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import Path
from typing import Iterable

from tv_quant.pattern_finder.cache import cache_path, cached_symbols, load_cache_entry
from tv_quant.pattern_finder.data_quality import DataQualityReport
from tv_quant.pattern_finder.flat_base import PATTERN_DETECTOR_VERSION
from tv_quant.pattern_finder.validation import PatternValidation, latest_validations

from .review_queue import QueueItem, QueueSourceKind


PROVISIONAL_CACHE_LABEL = "LOCAL CACHE · NOT A FORMAL SCAN BATCH"


@dataclass(frozen=True, slots=True)
class QueueSource:
    """An immutable, ordered group of queue items from one source."""

    source_kind: QueueSourceKind
    source_id: str
    label: str
    items: tuple[QueueItem, ...]


def build_cache_queue_source(
    cache_root: str | Path,
    as_of_utc: datetime,
    pattern_type: str,
    history: Iterable[PatternValidation],
) -> QueueSource:
    """Build a provisional queue source from the deterministic local cache order."""

    symbols = cached_symbols(cache_root)
    if len(set(symbols)) != len(symbols):
        raise ValueError("duplicate cached symbol")

    records = tuple(record for record in history if record.pattern_type == pattern_type)
    latest = latest_validations(records)
    counts = Counter(record.key for record in records)
    items: list[QueueItem] = []

    for source_rank, symbol in enumerate(symbols):
        entry = load_cache_entry(symbol, cache_root=cache_root, as_of_utc=as_of_utc)
        if entry is None:
            raise ValueError(f"cached symbol disappeared while loading: {symbol}")
        final_session = entry.quality.last_session
        if final_session is None:
            raise ValueError(f"cached symbol has no final session: {symbol}")

        stat = cache_path(cache_root, symbol).stat()
        item_id = _hash_identity(symbol, stat.st_size, stat.st_mtime_ns)
        validation_key = (
            symbol,
            pattern_type,
            PATTERN_DETECTOR_VERSION,
            final_session.isoformat(),
        )
        validation = latest.get(validation_key)
        items.append(
            QueueItem(
                source_kind=QueueSourceKind.PROVISIONAL_CACHE,
                source_id="",
                item_id=item_id,
                source_rank=source_rank,
                symbol=symbol,
                pattern_type=pattern_type,
                detector_version=PATTERN_DETECTOR_VERSION,
                scan_as_of_date=final_session.isoformat(),
                computer_decision=None,
                data_quality_passed=entry.quality.passed,
                quality_reason=_quality_reason(entry.quality),
                human_label=validation.human_label if validation else None,
                validation_result=validation.validation_result if validation else None,
                history_count=counts[validation_key],
            )
        )

    source_id = _hash_source(tuple(item.item_id for item in items))
    finalized_items = tuple(
        QueueItem(
            source_kind=item.source_kind,
            source_id=source_id,
            item_id=item.item_id,
            source_rank=item.source_rank,
            symbol=item.symbol,
            pattern_type=item.pattern_type,
            detector_version=item.detector_version,
            scan_as_of_date=item.scan_as_of_date,
            computer_decision=item.computer_decision,
            data_quality_passed=item.data_quality_passed,
            quality_reason=item.quality_reason,
            human_label=item.human_label,
            validation_result=item.validation_result,
            history_count=item.history_count,
        )
        for item in items
    )
    return QueueSource(
        source_kind=QueueSourceKind.PROVISIONAL_CACHE,
        source_id=source_id,
        label=PROVISIONAL_CACHE_LABEL,
        items=finalized_items,
    )


def _hash_identity(symbol: str, size: int, mtime_ns: int) -> str:
    return hashlib.sha256(f"{symbol}\0{size}\0{mtime_ns}".encode()).hexdigest()


def _hash_source(item_ids: tuple[str, ...]) -> str:
    return hashlib.sha256("\0".join(item_ids).encode()).hexdigest()


def _quality_reason(quality: DataQualityReport) -> str | None:
    issues = [*quality.errors]
    if quality.missing_sessions:
        issues.append(
            "missing XNYS sessions: "
            + ", ".join(session.isoformat() for session in quality.missing_sessions)
        )
    return "; ".join(issues) if issues else None
