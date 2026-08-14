from datetime import datetime, timezone

import pytest

from tv_quant.pattern_finder.universe_foundation import ProfileRegistry, core_v1
from tv_quant.pattern_finder.universe_foundation.ui_read_model import load_profile_ui_state


def test_load_profile_ui_state_projects_initialized_core_v1(tmp_path) -> None:
    registry = ProfileRegistry(tmp_path)
    registry.bootstrap(core_v1())

    state = load_profile_ui_state(registry, "CORE:v1")

    assert state.profile_version_id == "CORE:v1"
    assert state.display_name == "CORE v1"
    assert state.record_state == "PUBLISHED"
    assert state.published_at_utc == datetime(2026, 8, 11, tzinfo=timezone.utc)
    assert state.change_note == "Frozen default US common-stock universe."
    assert state.content_sha256 == core_v1().content_sha256
    assert state.filter_content_sha256 == core_v1().filter_content_sha256
    assert tuple((row.label, row.value) for row in state.conditions) == (
        ("Exchanges", "AMEX, NASDAQ, NYSE"),
        ("Allowed security classes", "COMMON_STOCK"),
        ("Minimum price (USD)", "5.00"),
        ("Maximum price (USD)", "None"),
        ("Minimum market cap (USD)", "1000000000.00"),
        ("Maximum market cap (USD)", "None"),
        ("Liquidity metric", "FUTU_AVG_TURNOVER_20D"),
        ("Liquidity evidence version", "futu-screening-liquidity/v1"),
        ("Minimum average dollar volume, 20D (USD)", "20000000.00"),
        ("Minimum average volume, 20D (shares)", "None"),
        ("Listing history metric", "FUTU_LISTED_DAYS"),
        ("Listing history evidence version", "futu-screening-listing-history/v1"),
        ("Minimum listed days", "250"),
        ("Sectors", "ALL"),
        ("Industries", "ALL"),
        ("Sector mapping version", "None"),
        ("Include ETF", "False"),
        ("Include ADR", "False"),
        ("Include OTC", "False"),
        ("Include preferred", "False"),
        ("Include warrant", "False"),
        ("Include unit", "False"),
        ("Active only", "True"),
    )


def test_load_profile_ui_state_rejects_empty_registry_without_bootstrap(tmp_path) -> None:
    registry = ProfileRegistry(tmp_path)

    with pytest.raises(RuntimeError, match="not initialized: CORE:v1"):
        load_profile_ui_state(registry, "CORE:v1")

    assert registry.list_published() == ()
