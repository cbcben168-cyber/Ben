"""Append-only storage for published universe profiles and availability events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping

from tv_quant.run_manifest import canonical_hash

from .profiles import (
    Exchange,
    ProfileKind,
    RecordState,
    SecurityClass,
    UniverseDraft,
    UniverseFilters,
    UniverseProfile,
    canonical_filter_payload,
    draft_content_sha256,
)


_FILTER_FIELDS = frozenset(
    {
        "exchanges",
        "allowed_security_classes",
        "min_price_usd",
        "max_price_usd",
        "min_market_cap_usd",
        "max_market_cap_usd",
        "liquidity_metric_id",
        "liquidity_evidence_version",
        "min_avg_dollar_volume_20d_usd",
        "min_avg_volume_20d_shares",
        "listing_history_metric_id",
        "listing_history_evidence_version",
        "min_listed_days",
        "sectors",
        "industries",
        "sector_mapping_version",
        "include_etf",
        "include_adr",
        "include_otc",
        "include_preferred",
        "include_warrant",
        "include_unit",
        "active_only",
    }
)
_PROFILE_FIELDS = frozenset(
    {
        "profile_family_id",
        "profile_version",
        "profile_version_id",
        "profile_kind",
        "display_name",
        "schema_version",
        "record_state",
        "parent_profile_version_id",
        "created_at_utc",
        "published_at_utc",
        "change_note",
        "filters",
        "content_sha256",
        "filter_content_sha256",
    }
)
_DRAFT_FIELDS = frozenset(
    {
        "draft_id",
        "profile_family_id",
        "profile_kind",
        "display_name",
        "parent_profile_version_id",
        "created_at_utc",
        "change_note",
        "filters",
        "draft_content_sha256",
    }
)
_AVAILABILITY_FIELDS = frozenset(
    {"profile_version_id", "action", "occurred_at_utc", "reason"}
)


class ProfileAvailabilityAction(str, Enum):
    ACTIVATED = "ACTIVATED"
    RETIRED = "RETIRED"


@dataclass(frozen=True, slots=True)
class ProfileAvailabilityEvent:
    profile_version_id: str
    action: ProfileAvailabilityAction
    occurred_at_utc: datetime
    reason: str

    def __post_init__(self) -> None:
        _non_empty_string(self.profile_version_id, "profile_version_id")
        if type(self.action) is not ProfileAvailabilityAction:
            raise ValueError("action: ProfileAvailabilityAction required")
        _utc_datetime(self.occurred_at_utc, "occurred_at_utc")
        _non_empty_string(self.reason, "reason")


class ProfileRegistry:
    """Path-bound registry with explicit CORE bootstrap and no publication API."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._published_path = self._root / "published.jsonl"
        self._availability_path = self._root / "availability.jsonl"
        self._drafts_root = self._root / "drafts"
        self._preview_evidence_root = self._root / "preview_evidence"
        self._drafts_root.mkdir(parents=True, exist_ok=True)

    @property
    def preview_evidence_root(self) -> Path:
        return self._preview_evidence_root

    def bootstrap(self, profile: UniverseProfile) -> None:
        if type(profile) is not UniverseProfile or profile.record_state is not RecordState.PUBLISHED:
            raise ValueError("bootstrap: published UniverseProfile required")
        if (
            profile.profile_family_id != "CORE"
            or profile.profile_version != 1
            or profile.profile_version_id != "CORE:v1"
            or profile.profile_kind is not ProfileKind.CORE
            or profile.parent_profile_version_id is not None
        ):
            raise ValueError("bootstrap: CORE:v1 profile required")
        published = self._read_published()
        existing = next(
            (item for item in published if item.profile_version_id == profile.profile_version_id),
            None,
        )
        if existing is not None:
            if existing.content_sha256 == profile.content_sha256:
                return
            raise ValueError("conflicting published profile for CORE:v1")
        self._append_json_line(self._published_path, _profile_payload(profile))

    def create_draft(
        self,
        *,
        draft_id: str,
        family_id: str,
        profile_kind: ProfileKind,
        display_name: str,
        change_note: str,
        source_profile_version_id: str | None,
        created_at_utc: datetime,
    ) -> UniverseDraft:
        if source_profile_version_id is None:
            filters = _blank_filters()
            parent_profile_version_id = None
        else:
            source = self.get_published(source_profile_version_id)
            if source.profile_family_id != family_id or source.profile_kind is not profile_kind:
                raise ValueError("source profile family and kind must match draft")
            filters = source.filters
            parent_profile_version_id = source.profile_version_id
        values: dict[str, object] = {
            "draft_id": draft_id,
            "profile_family_id": family_id,
            "profile_kind": profile_kind,
            "display_name": display_name,
            "parent_profile_version_id": parent_profile_version_id,
            "created_at_utc": created_at_utc,
            "change_note": change_note,
            "filters": filters,
        }
        prototype = object.__new__(UniverseDraft)
        for name, value in values.items():
            object.__setattr__(prototype, name, value)
        draft = UniverseDraft(
            **values,
            draft_content_sha256=draft_content_sha256(prototype),
        )
        self.save_draft(draft)
        return draft

    def save_draft(self, draft: UniverseDraft) -> None:
        if type(draft) is not UniverseDraft:
            raise ValueError("save_draft: UniverseDraft required")
        _atomic_write(self._draft_path(draft.draft_id), _draft_payload(draft))

    def get_draft(self, draft_id: str) -> UniverseDraft:
        _non_empty_string(draft_id, "draft_id")
        path = self._draft_path(draft_id)
        try:
            payload = _load_json_object(path)
            draft = _draft_from_payload(payload)
        except FileNotFoundError as exc:
            raise KeyError(draft_id) from exc
        except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("corrupt draft registry") from exc
        if draft.draft_id != draft_id:
            raise ValueError("corrupt draft registry")
        return draft

    def close_draft(self, draft_id: str) -> None:
        _non_empty_string(draft_id, "draft_id")
        try:
            self._draft_path(draft_id).unlink()
        except FileNotFoundError as exc:
            raise KeyError(draft_id) from exc

    def get_published(self, profile_version_id: str) -> UniverseProfile:
        _non_empty_string(profile_version_id, "profile_version_id")
        for profile in self._read_published():
            if profile.profile_version_id == profile_version_id:
                return profile
        raise KeyError(profile_version_id)

    def list_published(self, family_id: str | None = None) -> tuple[UniverseProfile, ...]:
        if family_id is not None:
            _non_empty_string(family_id, "family_id")
        profiles = self._read_published()
        if family_id is not None:
            profiles = [item for item in profiles if item.profile_family_id == family_id]
        return tuple(sorted(profiles, key=lambda item: (item.profile_family_id, item.profile_version)))

    def record_availability(self, event: ProfileAvailabilityEvent) -> None:
        if type(event) is not ProfileAvailabilityEvent:
            raise ValueError("record_availability: ProfileAvailabilityEvent required")
        self._read_availability()
        self._append_json_line(self._availability_path, _availability_payload(event))

    def latest_availability(
        self, profile_version_id: str
    ) -> ProfileAvailabilityEvent | None:
        _non_empty_string(profile_version_id, "profile_version_id")
        latest = None
        for event in self._read_availability():
            if event.profile_version_id == profile_version_id:
                latest = event
        return latest

    def _draft_path(self, draft_id: str) -> Path:
        digest = canonical_hash({"draft_id": draft_id})
        return self._drafts_root / f"{digest}.json"

    def _read_published(self) -> list[UniverseProfile]:
        try:
            profiles = [_profile_from_payload(payload) for payload in _read_json_lines(self._published_path)]
            ids = [profile.profile_version_id for profile in profiles]
            if len(ids) != len(set(ids)):
                raise ValueError
            return profiles
        except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("corrupt published registry") from exc

    def _read_availability(self) -> list[ProfileAvailabilityEvent]:
        try:
            return [
                _availability_from_payload(payload)
                for payload in _read_json_lines(self._availability_path)
            ]
        except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("corrupt availability registry") from exc

    @staticmethod
    def _append_json_line(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())


def _non_empty_string(value: object, path: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{path}: non-empty string required")
    return value


def _utc_datetime(value: object, path: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != timezone.utc.utcoffset(value)
    ):
        raise ValueError(f"{path}: UTC datetime required")
    return value


def _parse_utc(value: object, path: str) -> datetime:
    if type(value) is not str:
        raise ValueError(f"{path}: UTC timestamp required")
    parsed = datetime.fromisoformat(value)
    return _utc_datetime(parsed, path)


def _decimal(value: object, path: str) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError(f"{path}: decimal string required")
    try:
        return Decimal(value)
    except Exception as exc:
        raise ValueError(f"{path}: decimal string required") from exc


def _enum_set(value: object, enum_type: type[Enum], path: str) -> frozenset[Enum]:
    if type(value) is not list:
        raise ValueError(f"{path}: enum list required")
    return frozenset(enum_type(item) for item in value)


def _all_or_names(value: object, path: str) -> str | frozenset[str]:
    if value == "ALL":
        return "ALL"
    if type(value) is not list:
        raise ValueError(f"{path}: ALL or name list required")
    return frozenset(value)


def _filters_from_payload(payload: object) -> UniverseFilters:
    if type(payload) is not dict or set(payload) != _FILTER_FIELDS:
        raise ValueError("filters: exact fields required")
    return UniverseFilters(
        exchanges=_enum_set(payload["exchanges"], Exchange, "exchanges"),
        allowed_security_classes=_enum_set(
            payload["allowed_security_classes"], SecurityClass, "allowed_security_classes"
        ),
        min_price_usd=_decimal(payload["min_price_usd"], "min_price_usd"),
        max_price_usd=_decimal(payload["max_price_usd"], "max_price_usd"),
        min_market_cap_usd=_decimal(payload["min_market_cap_usd"], "min_market_cap_usd"),
        max_market_cap_usd=_decimal(payload["max_market_cap_usd"], "max_market_cap_usd"),
        liquidity_metric_id=payload["liquidity_metric_id"],
        liquidity_evidence_version=payload["liquidity_evidence_version"],
        min_avg_dollar_volume_20d_usd=_decimal(
            payload["min_avg_dollar_volume_20d_usd"], "min_avg_dollar_volume_20d_usd"
        ),
        min_avg_volume_20d_shares=_decimal(
            payload["min_avg_volume_20d_shares"], "min_avg_volume_20d_shares"
        ),
        listing_history_metric_id=payload["listing_history_metric_id"],
        listing_history_evidence_version=payload["listing_history_evidence_version"],
        min_listed_days=payload["min_listed_days"],
        sectors=_all_or_names(payload["sectors"], "sectors"),
        industries=_all_or_names(payload["industries"], "industries"),
        sector_mapping_version=payload["sector_mapping_version"],
        include_etf=payload["include_etf"],
        include_adr=payload["include_adr"],
        include_otc=payload["include_otc"],
        include_preferred=payload["include_preferred"],
        include_warrant=payload["include_warrant"],
        include_unit=payload["include_unit"],
        active_only=payload["active_only"],
    )


def _profile_payload(profile: UniverseProfile) -> dict[str, object]:
    return {
        "profile_family_id": profile.profile_family_id,
        "profile_version": profile.profile_version,
        "profile_version_id": profile.profile_version_id,
        "profile_kind": profile.profile_kind.value,
        "display_name": profile.display_name,
        "schema_version": profile.schema_version,
        "record_state": profile.record_state.value,
        "parent_profile_version_id": profile.parent_profile_version_id,
        "created_at_utc": profile.created_at_utc.isoformat(),
        "published_at_utc": (
            None if profile.published_at_utc is None else profile.published_at_utc.isoformat()
        ),
        "change_note": profile.change_note,
        "filters": canonical_filter_payload(profile.filters),
        "content_sha256": profile.content_sha256,
        "filter_content_sha256": profile.filter_content_sha256,
    }


def _profile_from_payload(payload: object) -> UniverseProfile:
    if type(payload) is not dict or set(payload) != _PROFILE_FIELDS:
        raise ValueError("profile: exact fields required")
    published_at = payload["published_at_utc"]
    return UniverseProfile(
        profile_family_id=payload["profile_family_id"],
        profile_version=payload["profile_version"],
        profile_version_id=payload["profile_version_id"],
        profile_kind=ProfileKind(payload["profile_kind"]),
        display_name=payload["display_name"],
        schema_version=payload["schema_version"],
        record_state=RecordState(payload["record_state"]),
        parent_profile_version_id=payload["parent_profile_version_id"],
        created_at_utc=_parse_utc(payload["created_at_utc"], "created_at_utc"),
        published_at_utc=(
            None if published_at is None else _parse_utc(published_at, "published_at_utc")
        ),
        change_note=payload["change_note"],
        filters=_filters_from_payload(payload["filters"]),
        content_sha256=payload["content_sha256"],
        filter_content_sha256=payload["filter_content_sha256"],
    )


def _draft_payload(draft: UniverseDraft) -> dict[str, object]:
    return {
        "draft_id": draft.draft_id,
        "profile_family_id": draft.profile_family_id,
        "profile_kind": draft.profile_kind.value,
        "display_name": draft.display_name,
        "parent_profile_version_id": draft.parent_profile_version_id,
        "created_at_utc": draft.created_at_utc.isoformat(),
        "change_note": draft.change_note,
        "filters": canonical_filter_payload(draft.filters),
        "draft_content_sha256": draft.draft_content_sha256,
    }


def _draft_from_payload(payload: object) -> UniverseDraft:
    if type(payload) is not dict or set(payload) != _DRAFT_FIELDS:
        raise ValueError("draft: exact fields required")
    return UniverseDraft(
        draft_id=payload["draft_id"],
        profile_family_id=payload["profile_family_id"],
        profile_kind=ProfileKind(payload["profile_kind"]),
        display_name=payload["display_name"],
        parent_profile_version_id=payload["parent_profile_version_id"],
        created_at_utc=_parse_utc(payload["created_at_utc"], "created_at_utc"),
        change_note=payload["change_note"],
        filters=_filters_from_payload(payload["filters"]),
        draft_content_sha256=payload["draft_content_sha256"],
    )


def _availability_payload(event: ProfileAvailabilityEvent) -> dict[str, object]:
    return {
        "profile_version_id": event.profile_version_id,
        "action": event.action.value,
        "occurred_at_utc": event.occurred_at_utc.isoformat(),
        "reason": event.reason,
    }


def _availability_from_payload(payload: object) -> ProfileAvailabilityEvent:
    if type(payload) is not dict or set(payload) != _AVAILABILITY_FIELDS:
        raise ValueError("availability: exact fields required")
    return ProfileAvailabilityEvent(
        profile_version_id=payload["profile_version_id"],
        action=ProfileAvailabilityAction(payload["action"]),
        occurred_at_utc=_parse_utc(payload["occurred_at_utc"], "occurred_at_utc"),
        reason=payload["reason"],
    )


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("duplicate JSON field")
        payload[key] = value
    return payload


def _read_json_lines(path: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    payloads: list[dict[str, object]] = []
    for line in lines:
        if not line:
            raise ValueError("blank JSONL record")
        payload = json.loads(line, object_pairs_hook=_reject_duplicate_fields)
        if type(payload) is not dict:
            raise ValueError("JSON object required")
        payloads.append(payload)
    return payloads


def _load_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_fields)
    if type(payload) is not dict:
        raise ValueError("JSON object required")
    return payload


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(path, flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _blank_filters() -> UniverseFilters:
    return UniverseFilters(
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


__all__ = (
    "ProfileAvailabilityAction",
    "ProfileAvailabilityEvent",
    "ProfileRegistry",
)
