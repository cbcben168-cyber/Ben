"""Read-only projection for the initialized universe profile page."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import streamlit as st

from .profiles import RecordState, UniverseProfile
from .registry import ProfileRegistry


@dataclass(frozen=True, slots=True)
class ProfileConditionRow:
    """One immutable, display-ready frozen profile condition."""

    label: str
    value: str


@dataclass(frozen=True, slots=True)
class ProfileUiState:
    """Display-only state for a single initialized published profile."""

    profile_version_id: str
    display_name: str
    record_state: str
    published_at_utc: datetime
    change_note: str
    content_sha256: str
    filter_content_sha256: str
    conditions: tuple[ProfileConditionRow, ...]


def _text(value: Decimal | int | str | None) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _condition_rows(profile: UniverseProfile) -> tuple[ProfileConditionRow, ...]:
    filters = profile.filters
    return (
        ProfileConditionRow("Exchanges", ", ".join(sorted(item.value for item in filters.exchanges))),
        ProfileConditionRow(
            "Allowed security classes",
            ", ".join(sorted(item.value for item in filters.allowed_security_classes)),
        ),
        ProfileConditionRow("Minimum price (USD)", _text(filters.min_price_usd)),
        ProfileConditionRow("Maximum price (USD)", _text(filters.max_price_usd)),
        ProfileConditionRow("Minimum market cap (USD)", _text(filters.min_market_cap_usd)),
        ProfileConditionRow("Maximum market cap (USD)", _text(filters.max_market_cap_usd)),
        ProfileConditionRow("Liquidity metric", filters.liquidity_metric_id),
        ProfileConditionRow("Liquidity evidence version", filters.liquidity_evidence_version),
        ProfileConditionRow(
            "Minimum average dollar volume, 20D (USD)",
            _text(filters.min_avg_dollar_volume_20d_usd),
        ),
        ProfileConditionRow(
            "Minimum average volume, 20D (shares)",
            _text(filters.min_avg_volume_20d_shares),
        ),
        ProfileConditionRow("Listing history metric", filters.listing_history_metric_id),
        ProfileConditionRow(
            "Listing history evidence version", filters.listing_history_evidence_version
        ),
        ProfileConditionRow("Minimum listed days", _text(filters.min_listed_days)),
        ProfileConditionRow("Sectors", _text(filters.sectors)),
        ProfileConditionRow("Industries", _text(filters.industries)),
        ProfileConditionRow("Sector mapping version", _text(filters.sector_mapping_version)),
        ProfileConditionRow("Include ETF", _text(filters.include_etf)),
        ProfileConditionRow("Include ADR", _text(filters.include_adr)),
        ProfileConditionRow("Include OTC", _text(filters.include_otc)),
        ProfileConditionRow("Include preferred", _text(filters.include_preferred)),
        ProfileConditionRow("Include warrant", _text(filters.include_warrant)),
        ProfileConditionRow("Include unit", _text(filters.include_unit)),
        ProfileConditionRow("Active only", _text(filters.active_only)),
    )


def load_profile_ui_state(
    registry: ProfileRegistry, profile_version_id: str
) -> ProfileUiState:
    """Project an already initialized published profile without evaluating membership."""

    try:
        profile = registry.get_published(profile_version_id)
    except KeyError as exc:
        raise RuntimeError(
            f"published profile not initialized: {profile_version_id}"
        ) from exc
    if profile.record_state is not RecordState.PUBLISHED:
        raise RuntimeError(f"no current published profile: {profile_version_id}")
    if profile.published_at_utc is None:
        raise RuntimeError(f"published profile is incomplete: {profile_version_id}")
    if profile.content_sha256 is None or profile.filter_content_sha256 is None:
        raise RuntimeError(f"published profile is incomplete: {profile_version_id}")
    return ProfileUiState(
        profile_version_id=profile.profile_version_id,
        display_name=profile.display_name,
        record_state=profile.record_state.value,
        published_at_utc=profile.published_at_utc,
        change_note=profile.change_note,
        content_sha256=profile.content_sha256,
        filter_content_sha256=profile.filter_content_sha256,
        conditions=_condition_rows(profile),
    )


def render_profile_status(
    *, registry: ProfileRegistry, profile_version_id: str
) -> None:
    """Render the published profile fields and frozen conditions only."""

    state = load_profile_ui_state(registry, profile_version_id)
    st.header("当前正式版本")
    st.subheader(state.display_name)
    st.markdown(f"**Profile version:** {state.profile_version_id}")
    st.markdown(f"**Record state:** {state.record_state}")
    st.markdown(f"**Published at (UTC):** {state.published_at_utc.isoformat()}")
    st.markdown(f"**Change note:** {state.change_note}")
    st.subheader("冻结条件")
    for row in state.conditions:
        st.markdown(f"- **{row.label}:** {row.value}")
    st.subheader("Content hashes")
    st.markdown(f"**Profile content SHA-256:** {state.content_sha256}")
    st.markdown(f"**Filter content SHA-256:** {state.filter_content_sha256}")
