"""V2.1 artifact ownership, provisional evidence, and formal-result gates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re

from tv_quant.run_manifest import (
    bind_artifact_hashes,
    canonical_hash,
    sha256_bytes,
    sha256_file,
)

from .path_safety import _validated_relative_path, resolve_under_root


_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PATH_COMPONENT = re.compile(r"[A-Za-z0-9._:-]+\Z")


def _non_empty_string(value: object, field_name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{field_name}: non-empty string required")
    return value


def _sha256(value: object, field_name: str) -> str:
    digest = _non_empty_string(value, field_name)
    if not _SHA256_HEX.fullmatch(digest):
        raise ValueError(f"{field_name}: lowercase SHA-256 hex required")
    return digest


def _path_component(value: object, field_name: str) -> str:
    component = _non_empty_string(value, field_name)
    if (
        not _PATH_COMPONENT.fullmatch(component)
        or component in {".", ".."}
        or "/" in component
        or "\\" in component
    ):
        raise ValueError(f"{field_name}: single safe path component required")
    return component


@dataclass(frozen=True, slots=True)
class ArtifactOwner:
    artifact_kind: str
    owner_module: str
    owner_function: str
    required: bool

    def __post_init__(self) -> None:
        _non_empty_string(self.artifact_kind, "artifact_kind")
        _non_empty_string(self.owner_module, "owner_module")
        _non_empty_string(self.owner_function, "owner_function")
        if type(self.required) is not bool:
            raise ValueError("required: bool required")


ARTIFACT_OWNERS = (
    ArtifactOwner("canonical_hash", "tv_quant.run_manifest", "canonical_hash", True),
    ArtifactOwner("file_hash", "tv_quant.run_manifest", "sha256_file", True),
    ArtifactOwner("bytes_hash", "tv_quant.run_manifest", "sha256_bytes", True),
    ArtifactOwner(
        "artifact_hash_binding",
        "tv_quant.run_manifest",
        "bind_artifact_hashes",
        True,
    ),
    ArtifactOwner(
        "data_provenance",
        "tv_quant.research_pipeline",
        "write_data_provenance",
        True,
    ),
    ArtifactOwner(
        "backtest_audit",
        "tv_quant.backtest_audit",
        "audit_backtest",
        True,
    ),
    ArtifactOwner("formal_report", "tv_quant.reporting", "write_reports", True),
)


@dataclass(frozen=True, slots=True)
class ProvisionalEvidence:
    run_id: str
    evidence_kind: str
    paths: tuple[str, ...]
    config_hash: str
    data_plan_hash: str
    capability_snapshot_hash: str
    status: str
    formal_result_published: bool

    def __post_init__(self) -> None:
        _path_component(self.run_id, "run_id")
        _path_component(self.evidence_kind, "evidence_kind")
        if type(self.paths) is not tuple or not self.paths:
            raise ValueError("paths: non-empty tuple required")
        for relative_path in self.paths:
            _validated_relative_path(relative_path)
        _sha256(self.config_hash, "config_hash")
        _sha256(self.data_plan_hash, "data_plan_hash")
        _sha256(self.capability_snapshot_hash, "capability_snapshot_hash")
        _non_empty_string(self.status, "status")
        if self.formal_result_published is not False:
            raise ValueError("formal_result_published: V2.1 requires false")

    def resolved_paths(self, root: Path) -> tuple[Path, ...]:
        """Return all evidence paths after filesystem-aware root containment."""
        return tuple(resolve_under_root(root, path) for path in self.paths)


@dataclass(frozen=True, slots=True)
class DependencyFingerprint:
    schema_version: str
    validator_version: str
    normalizer_version: str
    compiler_version: str
    capability_snapshot_hash: str
    status_registry_hash: str
    cost_profile_id: str
    cost_profile_hash: str
    corporate_action_profile_id: str
    corporate_action_profile_hash: str
    benchmark_protocol_version: str
    engine_id: str
    engine_version: str
    data_contract_version: str
    plugin_name: str | None
    plugin_version: str | None
    plugin_hash: str | None

    def __post_init__(self) -> None:
        if self.schema_version != "v2.1":
            raise ValueError("schema_version: must equal v2.1")
        for field_name in (
            "validator_version",
            "normalizer_version",
            "compiler_version",
            "cost_profile_id",
            "corporate_action_profile_id",
            "benchmark_protocol_version",
            "data_contract_version",
        ):
            _non_empty_string(getattr(self, field_name), field_name)
        for field_name in (
            "capability_snapshot_hash",
            "status_registry_hash",
            "cost_profile_hash",
            "corporate_action_profile_hash",
        ):
            _sha256(getattr(self, field_name), field_name)
        if self.engine_id != "NOT_IMPLEMENTED" or self.engine_version != "NOT_IMPLEMENTED":
            raise ValueError("engine_id and engine_version: V2.1 requires NOT_IMPLEMENTED")
        if (self.plugin_name, self.plugin_version, self.plugin_hash) != (None, None, None):
            raise ValueError("plugin fields: V2.1 requires null")


def dependency_hash(fingerprint: DependencyFingerprint) -> str:
    """Hash the complete frozen dependency payload with the Phase 1 owner."""
    if type(fingerprint) is not DependencyFingerprint:
        raise ValueError("DependencyFingerprint required")
    return canonical_hash(asdict(fingerprint))


@dataclass(frozen=True, slots=True)
class FormalResultContract:
    execution_complete: bool
    final_audit_acceptable: bool
    artifact_hashes_complete: bool
    blocking_status_absent: bool
    atomic_publish_complete: bool
    dependency_hash: str


def formal_eligibility(contract: FormalResultContract) -> bool:
    """Return whether the future formal-publication contract is complete."""
    if type(contract) is not FormalResultContract:
        return False
    conditions = (
        contract.execution_complete,
        contract.final_audit_acceptable,
        contract.artifact_hashes_complete,
        contract.blocking_status_absent,
        contract.atomic_publish_complete,
    )
    return (
        all(type(condition) is bool and condition for condition in conditions)
        and type(contract.dependency_hash) is str
        and bool(_SHA256_HEX.fullmatch(contract.dependency_hash))
    )


__all__ = (
    "ARTIFACT_OWNERS",
    "ArtifactOwner",
    "DependencyFingerprint",
    "FormalResultContract",
    "ProvisionalEvidence",
    "dependency_hash",
    "formal_eligibility",
)
