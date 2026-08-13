"""Immutable versioned universe profile value objects."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import re
from typing import Iterable

from tv_quant.run_manifest import canonical_hash


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ALL = "ALL"


class ProfileKind(str, Enum):
    CORE = "CORE"
    CUSTOM = "CUSTOM"


class RecordState(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class Exchange(str, Enum):
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"
    AMEX = "AMEX"


class SecurityClass(str, Enum):
    COMMON_STOCK = "COMMON_STOCK"


def _non_empty_string(value: object, path: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{path}: non-empty string required")
    return value


def _utc_datetime(value: object, path: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{path}: UTC datetime required")
    return value


def _decimal(value: object, path: str) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{path}: finite Decimal required")
    return value


def _non_negative_decimal(value: object, path: str) -> Decimal | None:
    decimal = _decimal(value, path)
    if decimal is not None and decimal < 0:
        raise ValueError(f"{path}: non-negative Decimal required")
    return decimal


def _enum_set(value: object, enum_type: type[Enum], path: str) -> frozenset[Enum]:
    if not isinstance(value, (set, frozenset, tuple, list)):
        raise ValueError(f"{path}: non-empty enum set required")
    frozen = frozenset(value)
    if not frozen or any(type(item) is not enum_type for item in frozen):
        raise ValueError(f"{path}: non-empty enum set required")
    return frozen


def _all_or_names(value: object, path: str) -> str | frozenset[str]:
    if value == _ALL:
        return _ALL
    if not isinstance(value, (set, frozenset, tuple, list)):
        raise ValueError(f"{path}: ALL or non-empty name set required")
    names = frozenset(value)
    if not names or any(type(name) is not str or not name.strip() for name in names) or _ALL in names:
        raise ValueError(f"{path}: ALL cannot be mixed with names")
    return names


def _hash(value: object, path: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ValueError(f"{path}: lowercase SHA-256 required")
    return value


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _ordered(values: Iterable[Enum | str]) -> list[str]:
    return sorted(item.value if isinstance(item, Enum) else item for item in values)


@dataclass(frozen=True, slots=True)
class UniverseFilters:
    exchanges: frozenset[Exchange]
    allowed_security_classes: frozenset[SecurityClass]
    min_price_usd: Decimal | None
    max_price_usd: Decimal | None
    min_market_cap_usd: Decimal | None
    max_market_cap_usd: Decimal | None
    liquidity_metric_id: str
    liquidity_evidence_version: str
    min_avg_dollar_volume_20d_usd: Decimal | None
    min_avg_volume_20d_shares: Decimal | None
    listing_history_metric_id: str
    listing_history_evidence_version: str
    min_listed_days: int | None
    sectors: str | frozenset[str]
    industries: str | frozenset[str]
    sector_mapping_version: str | None
    include_etf: bool
    include_adr: bool
    include_otc: bool
    include_preferred: bool
    include_warrant: bool
    include_unit: bool
    active_only: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "exchanges", _enum_set(self.exchanges, Exchange, "exchanges"))
        object.__setattr__(self, "allowed_security_classes", _enum_set(self.allowed_security_classes, SecurityClass, "allowed_security_classes"))
        for name in ("min_price_usd", "max_price_usd", "min_market_cap_usd", "max_market_cap_usd", "min_avg_dollar_volume_20d_usd", "min_avg_volume_20d_shares"):
            object.__setattr__(self, name, _non_negative_decimal(getattr(self, name), name))
        for minimum, maximum in (("min_price_usd", "max_price_usd"), ("min_market_cap_usd", "max_market_cap_usd")):
            if (lower := getattr(self, minimum)) is not None and (upper := getattr(self, maximum)) is not None and lower > upper:
                raise ValueError(f"{minimum}: cannot exceed {maximum}")
        for name in ("liquidity_metric_id", "liquidity_evidence_version", "listing_history_metric_id", "listing_history_evidence_version"):
            _non_empty_string(getattr(self, name), name)
        if self.min_listed_days is not None and (type(self.min_listed_days) is not int or self.min_listed_days < 0):
            raise ValueError("min_listed_days: non-negative integer required")
        object.__setattr__(self, "sectors", _all_or_names(self.sectors, "sectors"))
        object.__setattr__(self, "industries", _all_or_names(self.industries, "industries"))
        if self.sector_mapping_version is not None:
            _non_empty_string(self.sector_mapping_version, "sector_mapping_version")
        for name in ("include_etf", "include_adr", "include_otc", "include_preferred", "include_warrant", "include_unit", "active_only"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name}: boolean required")


def canonical_filter_payload(filters: UniverseFilters) -> dict[str, object]:
    if not isinstance(filters, UniverseFilters):
        raise ValueError("UniverseFilters required")
    return {
        "exchanges": _ordered(filters.exchanges),
        "allowed_security_classes": _ordered(filters.allowed_security_classes),
        "min_price_usd": _decimal_text(filters.min_price_usd),
        "max_price_usd": _decimal_text(filters.max_price_usd),
        "min_market_cap_usd": _decimal_text(filters.min_market_cap_usd),
        "max_market_cap_usd": _decimal_text(filters.max_market_cap_usd),
        "liquidity_metric_id": filters.liquidity_metric_id,
        "liquidity_evidence_version": filters.liquidity_evidence_version,
        "min_avg_dollar_volume_20d_usd": _decimal_text(filters.min_avg_dollar_volume_20d_usd),
        "min_avg_volume_20d_shares": _decimal_text(filters.min_avg_volume_20d_shares),
        "listing_history_metric_id": filters.listing_history_metric_id,
        "listing_history_evidence_version": filters.listing_history_evidence_version,
        "min_listed_days": filters.min_listed_days,
        "sectors": filters.sectors if filters.sectors == _ALL else _ordered(filters.sectors),
        "industries": filters.industries if filters.industries == _ALL else _ordered(filters.industries),
        "sector_mapping_version": filters.sector_mapping_version,
        "include_etf": filters.include_etf,
        "include_adr": filters.include_adr,
        "include_otc": filters.include_otc,
        "include_preferred": filters.include_preferred,
        "include_warrant": filters.include_warrant,
        "include_unit": filters.include_unit,
        "active_only": filters.active_only,
    }


def filter_content_sha256(filters: UniverseFilters) -> str:
    return canonical_hash(canonical_filter_payload(filters))


@dataclass(frozen=True, slots=True)
class UniverseProfile:
    profile_family_id: str
    profile_version: int
    profile_version_id: str
    profile_kind: ProfileKind
    display_name: str
    schema_version: str
    record_state: RecordState
    parent_profile_version_id: str | None
    created_at_utc: datetime
    published_at_utc: datetime | None
    change_note: str
    filters: UniverseFilters
    content_sha256: str | None
    filter_content_sha256: str | None

    def __post_init__(self) -> None:
        for name in ("profile_family_id", "profile_version_id", "display_name", "schema_version", "change_note"):
            _non_empty_string(getattr(self, name), name)
        if type(self.profile_version) is not int or self.profile_version < 1:
            raise ValueError("profile_version: positive integer required")
        if self.profile_version_id != f"{self.profile_family_id}:v{self.profile_version}":
            raise ValueError("profile_version_id: canonical family/version ID required")
        if type(self.profile_kind) is not ProfileKind or type(self.record_state) is not RecordState:
            raise ValueError("profile kind and record state enums required")
        if self.parent_profile_version_id is not None:
            _non_empty_string(self.parent_profile_version_id, "parent_profile_version_id")
        _utc_datetime(self.created_at_utc, "created_at_utc")
        if self.published_at_utc is not None:
            _utc_datetime(self.published_at_utc, "published_at_utc")
        if not isinstance(self.filters, UniverseFilters):
            raise ValueError("filters: UniverseFilters required")
        _hash(self.content_sha256, "content_sha256", allow_none=True)
        _hash(self.filter_content_sha256, "filter_content_sha256", allow_none=True)
        if self.record_state is RecordState.PUBLISHED and (self.content_sha256 is None or self.filter_content_sha256 is None or self.published_at_utc is None):
            raise ValueError("published profile: timestamps and hashes required")


def profile_content_sha256(profile: UniverseProfile) -> str:
    if not isinstance(profile, UniverseProfile):
        raise ValueError("UniverseProfile required")
    return canonical_hash({
        "schema_version": profile.schema_version,
        "profile_family_id": profile.profile_family_id,
        "profile_version": profile.profile_version,
        "parent_profile_version_id": profile.parent_profile_version_id,
        "filters": canonical_filter_payload(profile.filters),
    })


@dataclass(frozen=True, slots=True)
class UniverseDraft:
    draft_id: str
    profile_family_id: str
    profile_kind: ProfileKind
    display_name: str
    parent_profile_version_id: str | None
    created_at_utc: datetime
    change_note: str
    filters: UniverseFilters
    draft_content_sha256: str

    def __post_init__(self) -> None:
        for name in ("draft_id", "profile_family_id", "display_name", "change_note"):
            _non_empty_string(getattr(self, name), name)
        if type(self.profile_kind) is not ProfileKind:
            raise ValueError("profile_kind: ProfileKind required")
        if self.parent_profile_version_id is not None:
            _non_empty_string(self.parent_profile_version_id, "parent_profile_version_id")
        _utc_datetime(self.created_at_utc, "created_at_utc")
        if not isinstance(self.filters, UniverseFilters):
            raise ValueError("filters: UniverseFilters required")
        _hash(self.draft_content_sha256, "draft_content_sha256")


def draft_content_sha256(draft: UniverseDraft) -> str:
    if not isinstance(draft, UniverseDraft):
        raise ValueError("UniverseDraft required")
    return canonical_hash({
        "draft_id": draft.draft_id,
        "profile_family_id": draft.profile_family_id,
        "profile_kind": draft.profile_kind.value,
        "display_name": draft.display_name,
        "parent_profile_version_id": draft.parent_profile_version_id,
        "created_at_utc": draft.created_at_utc.isoformat(),
        "change_note": draft.change_note,
        "filters": canonical_filter_payload(draft.filters),
    })


def core_v1() -> UniverseProfile:
    filters = UniverseFilters(
        exchanges=frozenset({Exchange.NYSE, Exchange.NASDAQ, Exchange.AMEX}),
        allowed_security_classes=frozenset({SecurityClass.COMMON_STOCK}),
        min_price_usd=Decimal("5.00"), max_price_usd=None,
        min_market_cap_usd=Decimal("1000000000.00"), max_market_cap_usd=None,
        liquidity_metric_id="FUTU_AVG_TURNOVER_20D", liquidity_evidence_version="futu-screening-liquidity/v1",
        min_avg_dollar_volume_20d_usd=Decimal("20000000.00"), min_avg_volume_20d_shares=None,
        listing_history_metric_id="FUTU_LISTED_DAYS", listing_history_evidence_version="futu-screening-listing-history/v1",
        min_listed_days=250, sectors=_ALL, industries=_ALL, sector_mapping_version=None,
        include_etf=False, include_adr=False, include_otc=False, include_preferred=False,
        include_warrant=False, include_unit=False, active_only=True,
    )
    created = datetime(2026, 8, 11, tzinfo=timezone.utc)
    profile = UniverseProfile("CORE", 1, "CORE:v1", ProfileKind.CORE, "CORE v1", "universe-profile/v1", RecordState.PUBLISHED, None, created, created, "Frozen default US common-stock universe.", filters, "0" * 64, "0" * 64)
    return replace(profile, content_sha256=profile_content_sha256(profile), filter_content_sha256=filter_content_sha256(filters))


__all__ = ("Exchange", "ProfileKind", "RecordState", "SecurityClass", "UniverseDraft", "UniverseFilters", "UniverseProfile", "canonical_filter_payload", "core_v1", "draft_content_sha256", "filter_content_sha256", "profile_content_sha256")
