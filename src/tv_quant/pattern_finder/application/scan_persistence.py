"""Pure construction of immutable, completed Flat Base scan batches."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from tv_quant.data_quality import DataQualityError, load_standardized_csv
from tv_quant.pattern_finder.data_quality import assess_symbol_data
from tv_quant.pattern_finder.flat_base import (
    MIN_HISTORY,
    PATTERN_DETECTOR_VERSION,
    FlatBaseResult,
    detect_flat_base,
)
from tv_quant.pattern_finder.universe_foundation import (
    Completeness,
    SnapshotKind,
    UniverseSnapshot,
)


JSONScalar: TypeAlias = str | int | float | bool | None
PATTERN_TYPE = "flat_base"
SCAN_STATUS = "COMPLETED"
SCAN_PROVENANCE_VERSION = "formal-flat-base-scan/v1"


class MachineDecision(str, Enum):
    YES = "YES"
    NO = "NO"
    NOT_EVALUATED = "NOT_EVALUATED"


def _non_empty(value: str, field_name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name}: non-empty string required")


def _utc(value: datetime, field_name: str) -> None:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
    ):
        raise ValueError(f"{field_name}: timezone-aware UTC required")


def _sha256(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name}: lowercase SHA-256 required")


def _freeze_scalars(
    value: Mapping[str, JSONScalar], field_name: str
) -> Mapping[str, JSONScalar]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ValueError(f"{field_name}: string-keyed mapping required")
    frozen: dict[str, JSONScalar] = {}
    for key, item in value.items():
        if type(item) not in (str, int, float, bool, type(None)):
            raise ValueError(f"{field_name}: JSON scalar values required")
        if type(item) is float and (
            item != item or item in (float("inf"), float("-inf"))
        ):
            raise ValueError(f"{field_name}: finite float values required")
        frozen[key] = item
    return MappingProxyType(dict(sorted(frozen.items())))


def _canonical_json(value: object) -> bytes:
    def encode(item: object) -> object:
        if isinstance(item, Enum):
            return item.value
        if type(item) is datetime:
            _utc(item, "canonical datetime")
            return item.isoformat().replace("+00:00", "Z")
        if type(item) is date:
            return item.isoformat()
        if isinstance(item, Mapping):
            return {str(key): encode(child) for key, child in sorted(item.items())}
        if isinstance(item, (tuple, list)):
            return [encode(child) for child in item]
        return item

    return json.dumps(
        encode(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _formal_cache_path(cache_root: str | Path, symbol: str) -> Path:
    normalized = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9.-]+", normalized):
        raise ValueError(f"snapshot member has unsafe symbol: {symbol!r}")
    return Path(cache_root) / f"{normalized}_daily.csv"


@dataclass(frozen=True, slots=True)
class ScanResult:
    candidate_id: str
    scan_batch_id: str
    source_rank: int
    stock_id: str
    symbol: str
    pattern_type: str
    pattern_version: str
    signal_date: str
    computer_decision: MachineDecision
    features: Mapping[str, JSONScalar]
    reason_codes: tuple[str, ...]
    created_at_utc: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_id",
            "scan_batch_id",
            "stock_id",
            "symbol",
            "pattern_type",
            "pattern_version",
            "signal_date",
        ):
            _non_empty(getattr(self, field_name), field_name)
        if type(self.source_rank) is not int or self.source_rank < 0:
            raise ValueError("source_rank: non-negative integer required")
        if type(self.computer_decision) is not MachineDecision:
            raise ValueError("computer_decision: MachineDecision required")
        try:
            date.fromisoformat(self.signal_date)
        except ValueError as error:
            raise ValueError("signal_date: ISO date required") from error
        reasons = tuple(self.reason_codes)
        if any(type(reason) is not str or not reason for reason in reasons):
            raise ValueError("reason_codes: non-empty strings required")
        if len(reasons) != len(set(reasons)):
            raise ValueError("reason_codes: duplicates forbidden")
        if self.computer_decision is MachineDecision.NOT_EVALUATED and not reasons:
            raise ValueError("NOT_EVALUATED requires reason_codes")
        if self.computer_decision is not MachineDecision.NOT_EVALUATED and reasons:
            raise ValueError("evaluated results cannot carry reason_codes")
        _utc(self.created_at_utc, "created_at_utc")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "features", _freeze_scalars(self.features, "features"))


@dataclass(frozen=True, slots=True)
class ScanManifest:
    scan_as_of_date: str
    ordered_input_count: int
    quality_pass_count: int
    quality_fail_count: int
    yes_count: int
    no_count: int
    code_commit: str
    ordered_input_hash: str
    provenance: Mapping[str, JSONScalar]

    def __post_init__(self) -> None:
        try:
            date.fromisoformat(self.scan_as_of_date)
        except ValueError as error:
            raise ValueError("scan_as_of_date: ISO date required") from error
        for field_name in (
            "ordered_input_count",
            "quality_pass_count",
            "quality_fail_count",
            "yes_count",
            "no_count",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name}: non-negative integer required")
        _non_empty(self.code_commit, "code_commit")
        _sha256(self.ordered_input_hash, "ordered_input_hash")
        if (
            self.ordered_input_count
            != self.quality_pass_count + self.quality_fail_count
            or self.quality_pass_count != self.yes_count + self.no_count
        ):
            raise ValueError("manifest reconciliation mismatch")
        object.__setattr__(
            self, "provenance", _freeze_scalars(self.provenance, "provenance")
        )


@dataclass(frozen=True, slots=True)
class CompletedScanBatch:
    scan_batch_id: str
    snapshot_id: str
    profile_version_id: str
    pattern_type: str
    pattern_version: str
    started_at_utc: datetime
    completed_at_utc: datetime
    status: str
    input_hash: str
    config_hash: str
    result_hash: str
    manifest: ScanManifest
    results: tuple[ScanResult, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "scan_batch_id",
            "snapshot_id",
            "profile_version_id",
            "pattern_type",
            "pattern_version",
        ):
            _non_empty(getattr(self, field_name), field_name)
        if self.status != SCAN_STATUS:
            raise ValueError(f"status: {SCAN_STATUS} required")
        _utc(self.started_at_utc, "started_at_utc")
        _utc(self.completed_at_utc, "completed_at_utc")
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("completed_at_utc: cannot precede started_at_utc")
        for field_name in ("input_hash", "config_hash", "result_hash"):
            _sha256(getattr(self, field_name), field_name)
        if type(self.manifest) is not ScanManifest:
            raise ValueError("manifest: ScanManifest required")
        if self.input_hash != self.manifest.ordered_input_hash:
            raise ValueError("input hash binding mismatch")
        results = tuple(self.results)
        if any(type(result) is not ScanResult for result in results):
            raise ValueError("results: ScanResult values required")
        ranks = tuple(result.source_rank for result in results)
        if ranks != tuple(range(len(results))):
            raise ValueError("results: contiguous source_rank required")
        if len({result.stock_id for result in results}) != len(results):
            raise ValueError("results: unique stock_id required")
        if len({result.candidate_id for result in results}) != len(results):
            raise ValueError("results: unique candidate_id required")
        if any(
            result.scan_batch_id != self.scan_batch_id
            or result.pattern_type != self.pattern_type
            or result.pattern_version != self.pattern_version
            or result.signal_date != self.manifest.scan_as_of_date
            for result in results
        ):
            raise ValueError("results: batch binding mismatch")
        quality_fail_count = sum(
            result.computer_decision is MachineDecision.NOT_EVALUATED
            for result in results
        )
        yes_count = sum(
            result.computer_decision is MachineDecision.YES for result in results
        )
        no_count = sum(
            result.computer_decision is MachineDecision.NO for result in results
        )
        if (
            self.manifest.ordered_input_count != len(results)
            or self.manifest.quality_fail_count != quality_fail_count
            or self.manifest.quality_pass_count != yes_count + no_count
            or self.manifest.yes_count != yes_count
            or self.manifest.no_count != no_count
        ):
            raise ValueError("manifest reconciliation mismatch")
        object.__setattr__(self, "results", results)


def _quality_reason_codes(errors: tuple[str, ...], missing_sessions: int) -> tuple[str, ...]:
    reasons: list[str] = []
    for error in errors:
        if error.startswith("stale data"):
            reasons.append("STALE_CACHE")
        elif error.startswith("symbol mismatch"):
            reasons.append("SYMBOL_MISMATCH")
        elif error.startswith("non-XNYS session"):
            reasons.append("NON_XNYS_SESSION")
        elif error.startswith("data extends beyond"):
            reasons.append("FUTURE_CACHE")
        else:
            reasons.append("INVALID_CACHE")
    if missing_sessions:
        reasons.append("MISSING_SESSIONS")
    return tuple(dict.fromkeys(reasons)) or ("INVALID_CACHE",)


def _detector_features(result: FlatBaseResult, cache_sha256: str) -> dict[str, JSONScalar]:
    selected = result.selected
    return {
        "adjustment": "QFQ",
        "atr14_t0": selected.atr14_t0,
        "base_depth_pct": selected.base_depth_pct,
        "base_end": selected.base_end.date().isoformat(),
        "base_length": selected.base_length,
        "base_start": selected.base_start.date().isoformat(),
        "bottom_test_count": selected.bottom_test_count,
        "bottom_tolerance_pct": selected.bottom_tolerance_pct,
        "cache_sha256": cache_sha256,
        "normalized_slope": selected.normalized_slope,
        "resistance_level": selected.resistance_level,
        "resistance_raw": selected.resistance_raw,
        "resistance_spike_adjusted": selected.resistance_spike_adjusted,
        "resistance_upper_quantile": selected.resistance_upper_quantile,
        "support_level": selected.support_level,
        "window_id": selected.window_id,
    }


def build_flat_base_scan(
    snapshot: UniverseSnapshot,
    *,
    cache_root: str | Path,
    completed_at_utc: datetime,
    code_commit: str,
) -> CompletedScanBatch:
    """Build one deterministic formal batch without SQL, network, or cache writes."""
    if type(snapshot) is not UniverseSnapshot:
        raise TypeError("snapshot: UniverseSnapshot required")
    header = snapshot.header
    if (
        header.snapshot_kind is not SnapshotKind.FORMAL
        or header.completeness is not Completeness.COMPLETE
        or header.profile_version_id is None
        or header.profile_content_sha256 is None
    ):
        raise ValueError("formal complete Universe Snapshot required")
    _utc(completed_at_utc, "completed_at_utc")
    _non_empty(code_commit, "code_commit")

    members = tuple(row for row in snapshot.rows if row.is_member)
    if members != tuple(sorted(members, key=lambda row: (row.stock_id, row.futu_code))):
        raise ValueError("snapshot members must use deterministic composite-key order")
    as_of_utc = datetime.combine(header.as_of_session, time(23, 59), tzinfo=UTC)
    evidence: list[dict[str, object]] = []
    pending: list[dict[str, object]] = []

    for source_rank, member in enumerate(members):
        path = _formal_cache_path(cache_root, member.symbol)
        cache_exists = path.exists()
        cache_read_error = False
        try:
            cache_bytes = path.read_bytes() if cache_exists else None
        except OSError:
            cache_bytes = None
            cache_read_error = True
        cache_sha256 = (
            hashlib.sha256(cache_bytes).hexdigest()
            if cache_bytes is not None
            else _hash_json(
                {
                    "kind": (
                        "UNREADABLE_CACHE" if cache_read_error else "MISSING_CACHE"
                    ),
                    "stock_id": member.stock_id,
                    "futu_code": member.futu_code,
                    "symbol": member.symbol,
                }
            )
        )
        evidence.append(
            {
                "source_rank": source_rank,
                "stock_id": member.stock_id,
                "futu_code": member.futu_code,
                "symbol": member.symbol,
                "cache_sha256": cache_sha256,
                "cache_present": cache_exists,
                "cache_readable": not cache_read_error,
            }
        )
        decision = MachineDecision.NOT_EVALUATED
        reason_codes: tuple[str, ...] = (
            ("INVALID_CACHE",) if cache_read_error else ("MISSING_CACHE",)
        )
        features: dict[str, JSONScalar] = {
            "adjustment": "QFQ",
            "cache_sha256": cache_sha256,
        }
        if cache_bytes is not None:
            try:
                frame, _ = load_standardized_csv(path)
                quality = assess_symbol_data(frame, member.symbol, as_of_utc)
                if not quality.passed:
                    reason_codes = _quality_reason_codes(
                        quality.errors, len(quality.missing_sessions)
                    )
                    features["quality_issues"] = "; ".join(
                        (*quality.errors, *map(str, quality.missing_sessions))
                    )
                else:
                    if len(frame) < MIN_HISTORY:
                        reason_codes = ("INSUFFICIENT_HISTORY",)
                    else:
                        detected = detect_flat_base(frame)
                        decision = (
                            MachineDecision.YES
                            if detected.pattern_flat_base
                            else MachineDecision.NO
                        )
                        reason_codes = ()
                        features = _detector_features(detected, cache_sha256)
            except (DataQualityError, OSError, ValueError):
                reason_codes = ("INVALID_CACHE",)
        pending.append(
            {
                "source_rank": source_rank,
                "stock_id": member.stock_id,
                "symbol": member.symbol,
                "decision": decision,
                "reason_codes": reason_codes,
                "features": features,
            }
        )

    input_hash = _hash_json(evidence)
    config_payload = {
        "pattern_type": PATTERN_TYPE,
        "pattern_version": PATTERN_DETECTOR_VERSION,
        "profile_version_id": header.profile_version_id,
        "profile_content_sha256": header.profile_content_sha256,
        "adjustment": "QFQ",
        "provenance_version": SCAN_PROVENANCE_VERSION,
    }
    config_hash = _hash_json(config_payload)
    batch_identity = {
        "snapshot_id": str(header.universe_snapshot_id),
        "snapshot_sha256": header.snapshot_sha256,
        "completed_at_utc": completed_at_utc,
        "code_commit": code_commit,
        "input_hash": input_hash,
        "config_hash": config_hash,
    }
    scan_batch_id = "scan-" + _hash_json(batch_identity)
    results = tuple(
        ScanResult(
            candidate_id="candidate-"
            + _hash_json(
                {
                    "scan_batch_id": scan_batch_id,
                    "source_rank": item["source_rank"],
                    "stock_id": item["stock_id"],
                    "pattern_type": PATTERN_TYPE,
                    "signal_date": header.as_of_session,
                }
            ),
            scan_batch_id=scan_batch_id,
            source_rank=int(item["source_rank"]),
            stock_id=str(item["stock_id"]),
            symbol=str(item["symbol"]),
            pattern_type=PATTERN_TYPE,
            pattern_version=PATTERN_DETECTOR_VERSION,
            signal_date=header.as_of_session.isoformat(),
            computer_decision=item["decision"],  # type: ignore[arg-type]
            features=item["features"],  # type: ignore[arg-type]
            reason_codes=item["reason_codes"],  # type: ignore[arg-type]
            created_at_utc=completed_at_utc,
        )
        for item in pending
    )
    result_hash = _hash_json(
        tuple(
            {
                "candidate_id": result.candidate_id,
                "scan_batch_id": result.scan_batch_id,
                "source_rank": result.source_rank,
                "stock_id": result.stock_id,
                "symbol": result.symbol,
                "pattern_type": result.pattern_type,
                "pattern_version": result.pattern_version,
                "signal_date": result.signal_date,
                "decision": result.computer_decision,
                "features": result.features,
                "reason_codes": result.reason_codes,
                "created_at_utc": result.created_at_utc,
            }
            for result in results
        )
    )
    yes_count = sum(result.computer_decision is MachineDecision.YES for result in results)
    no_count = sum(result.computer_decision is MachineDecision.NO for result in results)
    quality_fail_count = sum(
        result.computer_decision is MachineDecision.NOT_EVALUATED for result in results
    )
    manifest = ScanManifest(
        scan_as_of_date=header.as_of_session.isoformat(),
        ordered_input_count=len(results),
        quality_pass_count=yes_count + no_count,
        quality_fail_count=quality_fail_count,
        yes_count=yes_count,
        no_count=no_count,
        code_commit=code_commit,
        ordered_input_hash=input_hash,
        provenance={
            "adjustment": "QFQ",
            "builder_version": SCAN_PROVENANCE_VERSION,
            "profile_content_sha256": header.profile_content_sha256,
            "snapshot_sha256": header.snapshot_sha256,
        },
    )
    return CompletedScanBatch(
        scan_batch_id=scan_batch_id,
        snapshot_id=str(header.universe_snapshot_id),
        profile_version_id=header.profile_version_id,
        pattern_type=PATTERN_TYPE,
        pattern_version=PATTERN_DETECTOR_VERSION,
        started_at_utc=completed_at_utc,
        completed_at_utc=completed_at_utc,
        status=SCAN_STATUS,
        input_hash=input_hash,
        config_hash=config_hash,
        result_hash=result_hash,
        manifest=manifest,
        results=results,
    )


__all__ = (
    "CompletedScanBatch",
    "MachineDecision",
    "ScanManifest",
    "ScanResult",
    "build_flat_base_scan",
)
