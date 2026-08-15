"""Security Master evidence port and append-only classification ledger."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Protocol

from .evidence import EvidenceReference, SecurityClassificationEvidence


class SecurityMasterProvider(Protocol):
    def classification_evidence(
        self,
        stock_id: str,
        futu_code: str,
        as_of_utc: datetime,
    ) -> tuple[SecurityClassificationEvidence, ...]: ...


def _non_empty_string(value: object, field_id: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_id}: non-empty string required")
    return value


def _utc_datetime(value: object, field_id: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != timezone.utc.utcoffset(value)
    ):
        raise ValueError(f"{field_id}: UTC datetime required")
    return value


def _reference_payload(reference: EvidenceReference | None) -> dict[str, str] | None:
    if reference is None:
        return None
    return {
        "source_id": reference.source_id,
        "source_locator": reference.source_locator,
        "source_record_sha256": reference.source_record_sha256,
    }


def _evidence_payload(evidence: SecurityClassificationEvidence) -> dict[str, object]:
    return {
        "normalized_class": evidence.normalized_class,
        "provider": evidence.provider,
        "provider_value": evidence.provider_value,
        "observed_at_utc": evidence.observed_at_utc.isoformat(),
        "source_version": evidence.source_version,
        "source_record_sha256": evidence.source_record_sha256,
        "confidence": evidence.confidence,
        "notes": evidence.notes,
        "reference": _reference_payload(evidence.reference),
        "verified_by": evidence.verified_by,
    }


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _exact_keys(payload: dict[str, object], expected: set[str], field_id: str) -> None:
    if set(payload) != expected:
        raise ValueError(f"{field_id}: invalid fields")


def _parse_datetime(value: object, field_id: str) -> datetime:
    if type(value) is not str:
        raise ValueError(f"{field_id}: UTC datetime string required")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_id}: invalid datetime") from error
    return _utc_datetime(parsed, field_id)


def _parse_reference(value: object) -> EvidenceReference | None:
    if value is None:
        return None
    if type(value) is not dict:
        raise ValueError("reference: object or null required")
    _exact_keys(
        value,
        {"source_id", "source_locator", "source_record_sha256"},
        "reference",
    )
    return EvidenceReference(
        source_id=value["source_id"],  # type: ignore[arg-type]
        source_locator=value["source_locator"],  # type: ignore[arg-type]
        source_record_sha256=value["source_record_sha256"],  # type: ignore[arg-type]
    )


def _parse_evidence(value: object) -> SecurityClassificationEvidence:
    if type(value) is not dict:
        raise ValueError("evidence: object required")
    _exact_keys(
        value,
        {
            "normalized_class",
            "provider",
            "provider_value",
            "observed_at_utc",
            "source_version",
            "source_record_sha256",
            "confidence",
            "notes",
            "reference",
            "verified_by",
        },
        "evidence",
    )
    return SecurityClassificationEvidence(
        normalized_class=value["normalized_class"],  # type: ignore[arg-type]
        provider=value["provider"],  # type: ignore[arg-type]
        provider_value=value["provider_value"],  # type: ignore[arg-type]
        observed_at_utc=_parse_datetime(value["observed_at_utc"], "observed_at_utc"),
        source_version=value["source_version"],  # type: ignore[arg-type]
        source_record_sha256=value["source_record_sha256"],  # type: ignore[arg-type]
        confidence=value["confidence"],  # type: ignore[arg-type]
        notes=value["notes"],  # type: ignore[arg-type]
        reference=_parse_reference(value["reference"]),
        verified_by=value["verified_by"],  # type: ignore[arg-type]
    )


class AppendOnlyClassificationLedger:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._path = self._root / "classification.jsonl"

    def append(
        self,
        stock_id: str,
        evidence: SecurityClassificationEvidence,
    ) -> None:
        _non_empty_string(stock_id, "stock_id")
        if type(evidence) is not SecurityClassificationEvidence:
            raise ValueError("evidence: SecurityClassificationEvidence required")
        payload = {"stock_id": stock_id, "evidence": _evidence_payload(evidence)}
        self._root.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())

    def get(
        self,
        stock_id: str,
        *,
        as_of_utc: datetime,
    ) -> tuple[SecurityClassificationEvidence, ...]:
        _non_empty_string(stock_id, "stock_id")
        _utc_datetime(as_of_utc, "as_of_utc")
        if not self._path.exists():
            return ()

        result: list[SecurityClassificationEvidence] = []
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        raise ValueError("blank record")
                    payload = json.loads(line, object_pairs_hook=_reject_duplicate_fields)
                    if type(payload) is not dict:
                        raise ValueError("record must be an object")
                    _exact_keys(payload, {"stock_id", "evidence"}, "record")
                    record_stock_id = _non_empty_string(payload["stock_id"], "stock_id")
                    evidence = _parse_evidence(payload["evidence"])
                    if record_stock_id == stock_id and evidence.observed_at_utc <= as_of_utc:
                        result.append(evidence)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise ValueError("classification ledger: invalid record") from error
        return tuple(result)
