from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from decimal import Decimal
import json
import os

import pytest

from tv_quant.pattern_finder.universe_foundation import ProfileRegistry
from tv_quant.pattern_finder.universe_foundation import (
    Exchange,
    ProfileAvailabilityAction,
    ProfileAvailabilityEvent,
    ProfileKind,
    RecordState,
    SecurityClass,
    UniverseDraft,
    UniverseFilters,
    UniverseProfile,
    canonical_filter_payload,
    core_v1,
)
from tv_quant.run_manifest import canonical_hash


_CREATED_AT = datetime(2026, 8, 12, tzinfo=timezone.utc)


def _profile_with_filters(filters: UniverseFilters) -> UniverseProfile:
    content_hash = canonical_hash(
        {
            "schema_version": "universe-profile/v1",
            "profile_family_id": "CORE",
            "profile_version": 1,
            "parent_profile_version_id": None,
            "filters": canonical_filter_payload(filters),
        }
    )
    return UniverseProfile(
        profile_family_id="CORE",
        profile_version=1,
        profile_version_id="CORE:v1",
        profile_kind=ProfileKind.CORE,
        display_name="CORE v1 conflict",
        schema_version="universe-profile/v1",
        record_state=RecordState.PUBLISHED,
        parent_profile_version_id=None,
        created_at_utc=_CREATED_AT,
        published_at_utc=_CREATED_AT,
        change_note="Conflicting content for the same version ID.",
        filters=filters,
        content_sha256=content_hash,
        filter_content_sha256=canonical_hash(canonical_filter_payload(filters)),
    )


def _draft(*, change_note: str) -> UniverseDraft:
    filters = core_v1().filters
    values = {
        "draft_id": "draft-atomic",
        "profile_family_id": "CORE",
        "profile_kind": ProfileKind.CORE,
        "display_name": "CORE v2",
        "parent_profile_version_id": "CORE:v1",
        "created_at_utc": _CREATED_AT,
        "change_note": change_note,
        "filters": filters,
    }
    digest = canonical_hash(
        {
            **{key: value for key, value in values.items() if key != "filters"},
            "profile_kind": ProfileKind.CORE.value,
            "created_at_utc": _CREATED_AT.isoformat(),
            "filters": canonical_filter_payload(filters),
        }
    )
    return UniverseDraft(**values, draft_content_sha256=digest)


def test_empty_registry_has_no_implicit_profiles_or_availability(tmp_path) -> None:
    registry = ProfileRegistry(tmp_path)

    assert registry.preview_evidence_root == tmp_path / "preview_evidence"
    assert registry.list_published() == ()
    assert registry.list_published("CORE") == ()
    assert registry.latest_availability("CORE:v1") is None
    with pytest.raises(KeyError):
        registry.get_published("CORE:v1")
    with pytest.raises(KeyError):
        registry.get_draft("missing")


def test_bootstrap_is_explicit_idempotent_by_hash_and_rejects_conflict(tmp_path) -> None:
    registry = ProfileRegistry(tmp_path)
    core = core_v1()

    registry.bootstrap(core)
    registry.bootstrap(core)

    assert registry.get_published("CORE:v1") == core
    assert registry.list_published() == (core,)
    assert len((tmp_path / "published.jsonl").read_text(encoding="utf-8").splitlines()) == 1

    conflict = _profile_with_filters(
        replace(core.filters, min_price_usd=Decimal("6.00"))
    )
    with pytest.raises(ValueError, match="conflicting published profile"):
        registry.bootstrap(conflict)
    assert registry.get_published("CORE:v1") == core


def test_create_draft_clones_source_with_direct_constructor_and_recomputed_hash(tmp_path) -> None:
    registry = ProfileRegistry(tmp_path)
    source = core_v1()
    registry.bootstrap(source)

    draft = registry.create_draft(
        draft_id="draft-clone",
        family_id="CORE",
        profile_kind=ProfileKind.CORE,
        display_name="CORE v2",
        change_note="Raise the liquidity floor.",
        source_profile_version_id="CORE:v1",
        created_at_utc=_CREATED_AT,
    )

    assert type(draft) is UniverseDraft
    assert draft.parent_profile_version_id == source.profile_version_id
    assert draft.filters == source.filters
    assert draft.draft_content_sha256 == canonical_hash(
        {
            "draft_id": "draft-clone",
            "profile_family_id": "CORE",
            "profile_kind": "CORE",
            "display_name": "CORE v2",
            "parent_profile_version_id": "CORE:v1",
            "created_at_utc": "2026-08-12T00:00:00+00:00",
            "change_note": "Raise the liquidity floor.",
            "filters": canonical_filter_payload(source.filters),
        }
    )
    assert registry.get_draft("draft-clone") == draft


def test_create_blank_draft_uses_validated_task_1_defaults(tmp_path) -> None:
    registry = ProfileRegistry(tmp_path)

    draft = registry.create_draft(
        draft_id="draft-blank",
        family_id="CUSTOM-1",
        profile_kind=ProfileKind.CUSTOM,
        display_name="Custom universe",
        change_note="Start a custom universe.",
        source_profile_version_id=None,
        created_at_utc=_CREATED_AT,
    )

    assert draft.parent_profile_version_id is None
    assert draft.filters == UniverseFilters(
        exchanges=frozenset({Exchange.NYSE, Exchange.NASDAQ, Exchange.AMEX}),
        allowed_security_classes=frozenset({SecurityClass.COMMON_STOCK}),
        min_price_usd=None,
        max_price_usd=None,
        min_market_cap_usd=None,
        max_market_cap_usd=None,
        liquidity_metric_id="FUTU_AVG_TURNOVER_20D",
        liquidity_evidence_version="futu-screening-liquidity/v1",
        min_avg_dollar_volume_20d_usd=None,
        min_avg_volume_20d_shares=None,
        listing_history_metric_id="FUTU_LISTED_DAYS",
        listing_history_evidence_version="futu-screening-listing-history/v1",
        min_listed_days=None,
        sectors="ALL",
        industries="ALL",
        sector_mapping_version=None,
        include_etf=False,
        include_adr=False,
        include_otc=False,
        include_preferred=False,
        include_warrant=False,
        include_unit=False,
        active_only=True,
    )
    assert registry.get_draft("draft-blank") == draft


def test_save_draft_is_atomic_and_close_removes_only_the_draft(tmp_path, monkeypatch) -> None:
    registry = ProfileRegistry(tmp_path)
    original = _draft(change_note="Original note.")
    replacement = _draft(change_note="Replacement note.")
    registry.save_draft(original)

    def fail_replace(_source: object, _target: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        registry.save_draft(replacement)

    assert registry.get_draft(original.draft_id) == original
    assert list((tmp_path / "drafts").glob("*.tmp")) == []
    registry.close_draft(original.draft_id)
    with pytest.raises(KeyError):
        registry.get_draft(original.draft_id)


def test_corrupt_jsonl_records_fail_closed_instead_of_being_skipped(tmp_path) -> None:
    published_registry = ProfileRegistry(tmp_path / "published")
    published_registry.bootstrap(core_v1())
    with (tmp_path / "published" / "published.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not-json}\n")

    with pytest.raises(ValueError, match="corrupt published registry"):
        published_registry.list_published()

    availability_registry = ProfileRegistry(tmp_path / "availability")
    (tmp_path / "availability" / "availability.jsonl").write_text(
        json.dumps({"unexpected": True}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="corrupt availability registry"):
        availability_registry.latest_availability("CORE:v1")


def test_availability_events_are_immutable_and_append_only(tmp_path) -> None:
    registry = ProfileRegistry(tmp_path)
    activated = ProfileAvailabilityEvent(
        profile_version_id="CORE:v1",
        action=ProfileAvailabilityAction.ACTIVATED,
        occurred_at_utc=datetime(2026, 8, 12, tzinfo=timezone.utc),
        reason="Initial activation.",
    )
    retired = ProfileAvailabilityEvent(
        profile_version_id="CORE:v1",
        action=ProfileAvailabilityAction.RETIRED,
        occurred_at_utc=datetime(2026, 8, 13, tzinfo=timezone.utc),
        reason="Replaced by a later version.",
    )

    registry.record_availability(activated)
    registry.record_availability(retired)

    assert registry.latest_availability("CORE:v1") == retired
    assert len((tmp_path / "availability.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    with pytest.raises(FrozenInstanceError):
        retired.reason = "changed"  # type: ignore[misc]


def test_registry_exposes_no_incomplete_published_append_path(tmp_path) -> None:
    registry = ProfileRegistry(tmp_path)

    assert not hasattr(registry, "publish")
    assert not hasattr(registry, "append_published")
    assert not hasattr(registry, "save_published")
