from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import MappingProxyType

import pytest

from tv_quant.pattern_finder.universe_foundation.profiles import (
    Exchange,
    ProfileKind,
    RecordState,
    SecurityClass,
    UniverseDraft,
    UniverseFilters,
    UniverseProfile,
    canonical_filter_payload,
    core_v1,
    draft_content_sha256,
    filter_content_sha256,
    profile_content_sha256,
)
from tv_quant.run_manifest import canonical_hash


def _filters(**changes: object) -> UniverseFilters:
    values: dict[str, object] = {
        "exchanges": {Exchange.NASDAQ, Exchange.NYSE},
        "allowed_security_classes": {SecurityClass.COMMON_STOCK},
        "min_price_usd": Decimal("5.00"),
        "max_price_usd": None,
        "min_market_cap_usd": Decimal("1000000000.00"),
        "max_market_cap_usd": None,
        "liquidity_metric_id": "FUTU_AVG_TURNOVER_20D",
        "liquidity_evidence_version": "futu-screening-liquidity/v1",
        "min_avg_dollar_volume_20d_usd": Decimal("20000000.00"),
        "min_avg_volume_20d_shares": None,
        "listing_history_metric_id": "FUTU_LISTED_DAYS",
        "listing_history_evidence_version": "futu-screening-listing-history/v1",
        "min_listed_days": 250,
        "sectors": "ALL",
        "industries": "ALL",
        "sector_mapping_version": None,
        "include_etf": False,
        "include_adr": False,
        "include_otc": False,
        "include_preferred": False,
        "include_warrant": False,
        "include_unit": False,
        "active_only": True,
    }
    values.update(changes)
    return UniverseFilters(**values)


def test_core_v1_freezes_every_frozen_design_field() -> None:
    profile = core_v1()

    assert profile.profile_family_id == "CORE"
    assert profile.profile_version == 1
    assert profile.profile_version_id == "CORE:v1"
    assert profile.profile_kind is ProfileKind.CORE
    assert profile.display_name == "CORE v1"
    assert profile.schema_version == "universe-profile/v1"
    assert profile.record_state is RecordState.PUBLISHED
    assert profile.parent_profile_version_id is None
    assert profile.created_at_utc == datetime(2026, 8, 11, tzinfo=timezone.utc)
    assert profile.published_at_utc == datetime(2026, 8, 11, tzinfo=timezone.utc)
    assert profile.change_note == "Frozen default US common-stock universe."
    assert profile.filters == _filters(exchanges={Exchange.NYSE, Exchange.NASDAQ, Exchange.AMEX})
    assert profile.content_sha256 == profile_content_sha256(profile)
    assert profile.filter_content_sha256 == filter_content_sha256(profile.filters)


def test_models_are_deeply_immutable_and_sets_are_stably_sorted_for_hashing() -> None:
    filters = _filters(sectors={"Technology", "Energy"}, industries={"Software", "Oil"})
    payload = canonical_filter_payload(filters)

    assert isinstance(filters.exchanges, frozenset)
    assert payload["exchanges"] == ["NASDAQ", "NYSE"]
    assert payload["sectors"] == ["Energy", "Technology"]
    assert payload["industries"] == ["Oil", "Software"]
    with pytest.raises((AttributeError, TypeError)):
        filters.exchanges.add(Exchange.AMEX)  # type: ignore[attr-defined]
    with pytest.raises(Exception):
        filters.min_price_usd = Decimal("6.00")  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_price_usd", 5.0),
        ("min_price_usd", Decimal("NaN")),
        ("min_price_usd", Decimal("Infinity")),
        ("liquidity_metric_id", ""),
        ("min_listed_days", True),
        ("exchanges", {""}),
    ],
)
def test_filter_rejects_noncanonical_numbers_booleans_and_blanks(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        _filters(**{field: value})


def test_filter_rejects_inverted_bounds_and_mixed_all_value_sets() -> None:
    with pytest.raises(ValueError, match="min_price_usd"):
        _filters(max_price_usd=Decimal("4.99"))
    with pytest.raises(ValueError, match="sectors"):
        _filters(sectors={"ALL", "Technology"})
    with pytest.raises(ValueError, match="industries"):
        _filters(industries={"ALL", "Software"})


def test_filter_and_profile_hashes_have_separate_identity_scopes() -> None:
    profile = core_v1()

    assert profile_content_sha256(profile) == profile.content_sha256
    assert profile.content_sha256 != profile.filter_content_sha256
    assert filter_content_sha256(profile.filters) == canonical_hash(canonical_filter_payload(profile.filters))


def test_draft_hash_binds_draft_identity_but_not_its_stored_hash_field() -> None:
    filters = _filters()
    draft = UniverseDraft(
        draft_id="draft-1",
        profile_family_id="CORE",
        profile_kind=ProfileKind.CORE,
        display_name="CORE v2",
        parent_profile_version_id="CORE:v1",
        created_at_utc=datetime(2026, 8, 12, tzinfo=timezone.utc),
        change_note="Raise liquidity threshold.",
        filters=filters,
        draft_content_sha256=_draft_hash(
            draft_id="draft-1",
            profile_family_id="CORE",
            profile_kind=ProfileKind.CORE,
            display_name="CORE v2",
            parent_profile_version_id="CORE:v1",
            created_at_utc=datetime(2026, 8, 12, tzinfo=timezone.utc),
            change_note="Raise liquidity threshold.",
            filters=filters,
        ),
    )
    assert draft_content_sha256(draft) == draft.draft_content_sha256
    with pytest.raises(ValueError, match="draft_content_sha256"):
        replace(draft, draft_content_sha256="f" * 64)


def _draft_hash(**values: object) -> str:
    draft = object.__new__(UniverseDraft)
    for name, value in values.items():
        object.__setattr__(draft, name, value)
    return draft_content_sha256(draft)


def test_published_profile_rejects_fabricated_content_or_filter_hash() -> None:
    profile = core_v1()

    with pytest.raises(ValueError, match="content_sha256"):
        replace(profile, content_sha256="0" * 64)
    with pytest.raises(ValueError, match="filter_content_sha256"):
        replace(profile, filter_content_sha256="0" * 64)


def test_draft_rejects_a_fabricated_content_hash() -> None:
    filters = _filters()

    with pytest.raises(ValueError, match="draft_content_sha256"):
        UniverseDraft(
            draft_id="draft-2",
            profile_family_id="CORE",
            profile_kind=ProfileKind.CORE,
            display_name="CORE v2",
            parent_profile_version_id="CORE:v1",
            created_at_utc=datetime(2026, 8, 12, tzinfo=timezone.utc),
            change_note="Raise liquidity threshold.",
            filters=filters,
            draft_content_sha256="0" * 64,
        )
