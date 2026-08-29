"""Pure, source-neutral projection for the Pattern Finder review queue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping


class QueueSourceKind(str, Enum):
    """Kinds of source that can contribute reviewable queue items."""

    PROVISIONAL_CACHE = "PROVISIONAL_CACHE"
    SCAN_BATCH = "SCAN_BATCH"


class QueueState(str, Enum):
    """The projected workflow state of an individual review item."""

    UNREVIEWED = "UNREVIEWED"
    REVIEWED = "REVIEWED"
    SKIPPED = "SKIPPED"
    SNOOZED = "SNOOZED"
    DATA_BLOCKED = "DATA_BLOCKED"


class QueueActionType(str, Enum):
    """Append-only workflow actions that do not change human validation history."""

    SKIP = "SKIP"
    SNOOZE = "SNOOZE"
    RESTORE = "RESTORE"


@dataclass(frozen=True, slots=True)
class QueueItem:
    source_kind: QueueSourceKind
    source_id: str
    item_id: str
    source_rank: int
    symbol: str
    pattern_type: str
    detector_version: str
    scan_as_of_date: str
    computer_decision: str | None
    data_quality_passed: bool
    quality_reason: str | None
    human_label: str | None
    validation_result: str | None
    history_count: int


@dataclass(frozen=True, slots=True)
class QueueAction:
    action_id: str
    source_kind: QueueSourceKind
    source_id: str
    item_id: str
    pattern_type: str
    action_type: QueueActionType
    created_at_utc: datetime


@dataclass(frozen=True, slots=True)
class QueueFilters:
    state: QueueState | None = None
    symbol_query: str = ""


@dataclass(frozen=True, slots=True)
class QueueCursor:
    source_kind: QueueSourceKind
    source_id: str
    pattern_type: str
    item_id: str
    filters: QueueFilters
    updated_at_utc: datetime


@dataclass(frozen=True, slots=True)
class QueueCounts:
    reviewed: int
    unreviewed: int
    skipped: int
    snoozed: int
    data_blocked: int


@dataclass(frozen=True, slots=True)
class QueueView:
    rows: tuple[QueueItem, ...]
    states: Mapping[str, QueueState]
    counts: QueueCounts
    selected_item_id: str | None


def project_state(
    item: QueueItem,
    latest_action: QueueActionType | None,
) -> QueueState:
    """Project a queue state using the fixed review-workflow precedence."""

    if not item.data_quality_passed:
        return QueueState.DATA_BLOCKED
    if item.history_count > 0:
        return QueueState.REVIEWED
    if latest_action is QueueActionType.SNOOZE:
        return QueueState.SNOOZED
    if latest_action is QueueActionType.SKIP:
        return QueueState.SKIPPED
    return QueueState.UNREVIEWED


def project_queue(
    items: tuple[QueueItem, ...] | list[QueueItem],
    latest_actions: Mapping[str, QueueActionType | QueueAction],
    filters: QueueFilters,
    selected_item_id: str | None,
) -> QueueView:
    """Filter and order items without changing their source or workflow state."""

    item_rows = tuple(items)
    states = {
        item.item_id: project_state(item, _action_type(latest_actions.get(item.item_id)))
        for item in item_rows
    }
    counts = _counts(states.values())
    visible = tuple(
        item
        for item in item_rows
        if _matches_filters(item, states[item.item_id], filters)
    )
    rows = tuple(
        sorted(
            visible,
            key=lambda item: (
                states[item.item_id] is not QueueState.UNREVIEWED,
                item.source_rank,
                item.item_id,
            ),
        )
    )
    visible_item_ids = {item.item_id for item in rows}
    selected = selected_item_id if selected_item_id in visible_item_ids else None
    if selected is None and rows:
        selected = rows[0].item_id
    return QueueView(
        rows=rows,
        states=MappingProxyType(states),
        counts=counts,
        selected_item_id=selected,
    )


def move_visible(view: QueueView, current_item_id: str, offset: int) -> str:
    """Move within visible rows while clamping at the beginning and end."""

    if not view.rows:
        return current_item_id
    positions = {item.item_id: index for index, item in enumerate(view.rows)}
    position = positions.get(current_item_id)
    if position is None:
        return view.selected_item_id or view.rows[0].item_id
    destination = min(max(position + offset, 0), len(view.rows) - 1)
    return view.rows[destination].item_id


def next_unreviewed(view: QueueView, current_item_id: str) -> str | None:
    """Return the next visible unreviewed item in deterministic source order."""

    current_item = next(
        (item for item in view.rows if item.item_id == current_item_id),
        None,
    )
    current_source_key = (
        (current_item.source_rank, current_item.item_id)
        if current_item is not None
        else None
    )
    next_item = min(
        (
            item
            for item in view.rows
            if view.states[item.item_id] is QueueState.UNREVIEWED
            and (
                current_source_key is None
                or (item.source_rank, item.item_id) > current_source_key
            )
        ),
        key=lambda item: (item.source_rank, item.item_id),
        default=None,
    )
    return None if next_item is None else next_item.item_id


def _action_type(action: QueueActionType | QueueAction | None) -> QueueActionType | None:
    if isinstance(action, QueueAction):
        return action.action_type
    return action


def _counts(states: Iterable[QueueState]) -> QueueCounts:
    values = tuple(states)
    return QueueCounts(
        reviewed=values.count(QueueState.REVIEWED),
        unreviewed=values.count(QueueState.UNREVIEWED),
        skipped=values.count(QueueState.SKIPPED),
        snoozed=values.count(QueueState.SNOOZED),
        data_blocked=values.count(QueueState.DATA_BLOCKED),
    )


def _matches_filters(item: QueueItem, state: QueueState, filters: QueueFilters) -> bool:
    query = filters.symbol_query.strip()
    return (
        (filters.state is None or state is filters.state)
        and (not query or item.symbol.casefold() == query.casefold())
    )
