from __future__ import annotations

from tv_quant.pattern_finder.application.review_queue import (
    QueueActionType,
    QueueCounts,
    QueueFilters,
    QueueItem,
    QueueSourceKind,
    QueueState,
    move_visible,
    next_unreviewed,
    project_queue,
    project_state,
)


def _item(
    symbol: str,
    *,
    source_rank: int = 0,
    reviewed: bool = False,
    blocked: bool = False,
) -> QueueItem:
    return QueueItem(
        source_kind=QueueSourceKind.PROVISIONAL_CACHE,
        source_id="cache-source",
        item_id=f"{symbol}-id",
        source_rank=source_rank,
        symbol=symbol,
        pattern_type="flat_base",
        detector_version="phase1-v1",
        scan_as_of_date="2026-08-27",
        computer_decision=None,
        data_quality_passed=not blocked,
        quality_reason="stale" if blocked else None,
        human_label="像" if reviewed else None,
        validation_result="true_positive_like" if reviewed else None,
        history_count=1 if reviewed else 0,
    )


def test_state_precedence_and_unreviewed_first_order() -> None:
    items = (
        _item("AAPL", source_rank=0, reviewed=True),
        _item("MSFT", source_rank=1),
        _item("NVDA", source_rank=2, blocked=True),
    )

    view = project_queue(
        items,
        latest_actions={},
        filters=QueueFilters(),
        selected_item_id="MSFT-id",
    )

    assert tuple(row.symbol for row in view.rows) == ("MSFT", "AAPL", "NVDA")
    assert view.counts == QueueCounts(
        reviewed=1,
        unreviewed=1,
        skipped=0,
        snoozed=0,
        data_blocked=1,
    )


def test_snooze_restore_and_review_precedence() -> None:
    reviewed = _item("AAPL", reviewed=True)
    fresh = _item("MSFT")
    blocked_reviewed = _item("NVDA", reviewed=True, blocked=True)

    assert project_state(reviewed, QueueActionType.SNOOZE) is QueueState.REVIEWED
    assert project_state(fresh, QueueActionType.SNOOZE) is QueueState.SNOOZED
    assert project_state(fresh, QueueActionType.RESTORE) is QueueState.UNREVIEWED
    assert project_state(blocked_reviewed, QueueActionType.SNOOZE) is QueueState.DATA_BLOCKED
    assert project_state(fresh, QueueActionType.SKIP) is QueueState.SKIPPED


def test_next_unreviewed_never_moves_into_reviewed_history() -> None:
    items = (
        _item("AAPL", source_rank=0, reviewed=True),
        _item("MSFT", source_rank=1),
    )
    all_reviewed = (
        _item("AAPL", source_rank=0, reviewed=True),
        _item("MSFT", source_rank=1, reviewed=True),
    )

    view = project_queue(
        items,
        latest_actions={},
        filters=QueueFilters(),
        selected_item_id="AAPL-id",
    )
    reviewed_view = project_queue(
        all_reviewed,
        latest_actions={},
        filters=QueueFilters(),
        selected_item_id="AAPL-id",
    )

    assert next_unreviewed(view, current_item_id="AAPL-id") == "MSFT-id"
    assert next_unreviewed(reviewed_view, current_item_id="AAPL-id") is None


def test_next_unreviewed_uses_full_visible_order_when_source_ranks_tie() -> None:
    view = project_queue(
        (
            _item("MSFT", source_rank=1),
            _item("AAPL", source_rank=1),
        ),
        latest_actions={},
        filters=QueueFilters(),
        selected_item_id="AAPL-id",
    )

    assert tuple(row.symbol for row in view.rows) == ("AAPL", "MSFT")
    assert next_unreviewed(view, current_item_id="AAPL-id") == "MSFT-id"


def test_previous_and_next_clamp_at_visible_boundaries() -> None:
    view = project_queue(
        (_item("AAPL", source_rank=0), _item("MSFT", source_rank=1)),
        latest_actions={},
        filters=QueueFilters(),
        selected_item_id="AAPL-id",
    )

    assert move_visible(view, "AAPL-id", -1) == "AAPL-id"
    assert move_visible(view, "AAPL-id", 1) == "MSFT-id"
    assert move_visible(view, "MSFT-id", 1) == "MSFT-id"


def test_symbol_search_is_exact_case_insensitive_and_composes_with_state_filter() -> None:
    items = (
        _item("AAPL", source_rank=0),
        _item("AA", source_rank=1),
        _item("MSFT", source_rank=2, reviewed=True),
    )

    searched = project_queue(
        items,
        latest_actions={},
        filters=QueueFilters(symbol_query="aapl"),
        selected_item_id=None,
    )
    reviewed = project_queue(
        items,
        latest_actions={},
        filters=QueueFilters(state=QueueState.REVIEWED, symbol_query="msft"),
        selected_item_id=None,
    )

    assert tuple(row.symbol for row in searched.rows) == ("AAPL",)
    assert tuple(row.symbol for row in reviewed.rows) == ("MSFT",)


def test_missing_cursor_falls_back_to_first_visible_unreviewed_item() -> None:
    view = project_queue(
        (
            _item("AAPL", source_rank=0, reviewed=True),
            _item("MSFT", source_rank=1),
            _item("NVDA", source_rank=2),
        ),
        latest_actions={},
        filters=QueueFilters(),
        selected_item_id="removed-item-id",
    )

    assert view.selected_item_id == "MSFT-id"


def test_cursor_fallback_keeps_visible_selection_or_uses_first_visible_or_none() -> None:
    retained = project_queue(
        (_item("AAPL", source_rank=0), _item("MSFT", source_rank=1)),
        latest_actions={},
        filters=QueueFilters(),
        selected_item_id="MSFT-id",
    )
    no_unreviewed = project_queue(
        (_item("AAPL", source_rank=0, reviewed=True),),
        latest_actions={},
        filters=QueueFilters(),
        selected_item_id="removed-item-id",
    )
    empty = project_queue(
        (),
        latest_actions={},
        filters=QueueFilters(),
        selected_item_id="removed-item-id",
    )

    assert retained.selected_item_id == "MSFT-id"
    assert no_unreviewed.selected_item_id == "AAPL-id"
    assert empty.selected_item_id is None


def test_source_rank_orders_items_deterministically_independent_of_input_order() -> None:
    view = project_queue(
        (
            _item("MSFT", source_rank=2),
            _item("AAPL", source_rank=0),
            _item("NVDA", source_rank=1),
        ),
        latest_actions={},
        filters=QueueFilters(),
        selected_item_id=None,
    )

    assert tuple(row.symbol for row in view.rows) == ("AAPL", "NVDA", "MSFT")
