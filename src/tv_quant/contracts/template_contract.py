"""Deterministic read-only template registry contract for V2.1."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import re


_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SEMANTIC_VERSION = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)
_ELIGIBLE_AUDIT_RESULTS = frozenset({"PASS", "CONDITIONAL_PASS"})


def _non_empty_string(value: object, field_name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{field_name}: non-empty string required")
    return value


def _sha256(value: object, field_name: str) -> str:
    digest = _non_empty_string(value, field_name)
    if not _SHA256_HEX.fullmatch(digest):
        raise ValueError(f"{field_name}: lowercase SHA-256 hex required")
    return digest


def _semantic_version(value: object) -> tuple[int, int, int, tuple[object, ...]]:
    version = _non_empty_string(value, "immutable_version")
    match = _SEMANTIC_VERSION.fullmatch(version)
    if match is None:
        raise ValueError("immutable_version: semantic version required")
    prerelease: tuple[object, ...] = ()
    if match.group(4) is not None:
        parts: list[object] = []
        for identifier in match.group(4).split("."):
            if identifier.isdigit():
                if len(identifier) > 1 and identifier.startswith("0"):
                    raise ValueError(
                        "immutable_version: invalid numeric prerelease identifier"
                    )
                parts.append((0, int(identifier)))
            else:
                parts.append((1, identifier))
        prerelease = tuple(parts)
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        ((1,),) if not prerelease else ((0,), *prerelease),
    )


@dataclass(frozen=True, slots=True)
class TemplateLookupKey:
    strategy_family: str
    symbol: str
    timeframe: str
    schema_version: str
    dependency_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "strategy_family",
            "symbol",
            "timeframe",
            "schema_version",
        ):
            _non_empty_string(getattr(self, field_name), field_name)
        _sha256(self.dependency_hash, "dependency_hash")


@dataclass(frozen=True, slots=True)
class TemplateRecord:
    template_id: str
    immutable_version: str
    strategy_family: str
    symbol: str
    timeframe: str
    schema_version: str
    dependency_hash: str
    config_hash: str
    plugin_hash: str | None
    audit_eligibility: str
    created_at: str
    supersedes: str | None
    active_version: bool
    invalidation_reason: str | None

    def __post_init__(self) -> None:
        for field_name in (
            "template_id",
            "strategy_family",
            "symbol",
            "timeframe",
            "schema_version",
            "audit_eligibility",
            "created_at",
        ):
            _non_empty_string(getattr(self, field_name), field_name)
        _semantic_version(self.immutable_version)
        _sha256(self.dependency_hash, "dependency_hash")
        _sha256(self.config_hash, "config_hash")
        if self.plugin_hash is not None:
            _sha256(self.plugin_hash, "plugin_hash")
        if self.supersedes is not None:
            _non_empty_string(self.supersedes, "supersedes")
        if type(self.active_version) is not bool:
            raise ValueError("active_version: bool required")
        if self.invalidation_reason is not None:
            _non_empty_string(self.invalidation_reason, "invalidation_reason")

    @property
    def lookup_key(self) -> TemplateLookupKey:
        return TemplateLookupKey(
            strategy_family=self.strategy_family,
            symbol=self.symbol,
            timeframe=self.timeframe,
            schema_version=self.schema_version,
            dependency_hash=self.dependency_hash,
        )


@dataclass(frozen=True, slots=True)
class TemplateEligibility:
    record: TemplateRecord
    eligible: bool
    reason: str | None


def _eligibility(record: TemplateRecord) -> TemplateEligibility:
    if record.invalidation_reason is not None:
        return TemplateEligibility(record, False, "INVALIDATED")
    if record.audit_eligibility not in _ELIGIBLE_AUDIT_RESULTS:
        return TemplateEligibility(record, False, record.audit_eligibility)
    return TemplateEligibility(record, True, None)


class TemplateRegistry:
    """Validate and query injected immutable records without writing registry data."""

    def __init__(
        self,
        registry_path: Path,
        records: Iterable[TemplateRecord] = (),
    ) -> None:
        if not isinstance(registry_path, Path):
            raise ValueError("registry_path: Path required")
        self.registry_path = registry_path
        self._records = tuple(records)
        self._validate_integrity()

    @staticmethod
    def validate_record(
        record: TemplateRecord,
        key: TemplateLookupKey,
    ) -> None:
        if type(record) is not TemplateRecord:
            raise ValueError("TemplateRecord required")
        if type(key) is not TemplateLookupKey:
            raise ValueError("TemplateLookupKey required")
        _sha256(record.dependency_hash, "dependency_hash")
        _sha256(record.config_hash, "config_hash")
        if record.plugin_hash is not None:
            _sha256(record.plugin_hash, "plugin_hash")
        if record.lookup_key != key:
            raise ValueError("record fields do not match lookup key")

    def _validate_integrity(self) -> None:
        by_id: dict[str, TemplateRecord] = {}
        active_keys: set[TemplateLookupKey] = set()
        precedence_hashes: set[tuple[TemplateLookupKey, tuple[object, ...], str]] = (
            set()
        )
        for record in self._records:
            if type(record) is not TemplateRecord:
                raise ValueError("records: TemplateRecord entries required")
            if record.template_id in by_id:
                raise ValueError("template_id: duplicate record")
            by_id[record.template_id] = record
            precedence_hash = (
                record.lookup_key,
                _semantic_version(record.immutable_version),
                record.config_hash,
            )
            if precedence_hash in precedence_hashes:
                raise ValueError(
                    "ambiguous semantic version and config_hash for lookup key"
                )
            precedence_hashes.add(precedence_hash)
            if record.invalidation_reason is not None and record.active_version:
                raise ValueError("invalidated record cannot be active")
            if record.active_version:
                if record.lookup_key in active_keys:
                    raise ValueError("only one active version is permitted per key")
                active_keys.add(record.lookup_key)

        for record in self._records:
            if record.supersedes is None:
                continue
            target = by_id.get(record.supersedes)
            if target is None:
                raise ValueError("supersedes must identify an existing record")
            if target.lookup_key != record.lookup_key:
                raise ValueError("supersedes must identify a record with the same key")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(template_id: str) -> None:
            if template_id in visiting:
                raise ValueError("supersedes cycle detected")
            if template_id in visited:
                return
            visiting.add(template_id)
            supersedes = by_id[template_id].supersedes
            if supersedes is not None:
                visit(supersedes)
            visiting.remove(template_id)
            visited.add(template_id)

        for template_id in by_id:
            visit(template_id)

        for record in self._records:
            if record.supersedes is None:
                continue
            target = by_id[record.supersedes]
            if _semantic_version(record.immutable_version) <= _semantic_version(
                target.immutable_version
            ):
                raise ValueError("supersedes must identify an older semantic version")

    def _matching(self, key: TemplateLookupKey) -> tuple[TemplateRecord, ...]:
        if type(key) is not TemplateLookupKey:
            raise ValueError("TemplateLookupKey required")
        matches = tuple(record for record in self._records if record.lookup_key == key)
        return tuple(
            sorted(
                matches,
                key=lambda record: (
                    _semantic_version(record.immutable_version),
                    record.config_hash,
                ),
                reverse=True,
            )
        )

    def lookup_latest(self, key: TemplateLookupKey) -> TemplateRecord | None:
        matches = self._matching(key)
        return matches[0] if matches else None

    def save(self, record: TemplateRecord) -> str:
        if type(record) is not TemplateRecord:
            raise ValueError("TemplateRecord required")
        return "NOT_IMPLEMENTED"


def find_latest_eligible(
    registry: TemplateRegistry,
    key: TemplateLookupKey,
) -> TemplateEligibility | None:
    if type(registry) is not TemplateRegistry:
        raise ValueError("TemplateRegistry required")
    for record in registry._matching(key):
        eligibility = _eligibility(record)
        if eligibility.eligible:
            return eligibility
    return None


__all__ = (
    "TemplateEligibility",
    "TemplateLookupKey",
    "TemplateRecord",
    "TemplateRegistry",
    "find_latest_eligible",
)
