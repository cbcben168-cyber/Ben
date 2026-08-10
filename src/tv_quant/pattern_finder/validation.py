from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .pattern_registry import get_pattern_profile


DEFAULT_VALIDATION_PATH = Path(
    "data/processed/pattern_finder/manual_validation/flat_base_validation.jsonl"
)
HUMAN_LABELS = ("像", "勉强像", "不像")
REASON_TAGS = (
    "底部太深",
    "底部太短",
    "低点不稳定",
    "整体仍在下降",
    "整体斜率太大",
    "宽幅震荡",
    "阻力不清楚",
    "底部区间太宽",
    "其他",
)
MAX_NOTE_LENGTH = 280
JSONScalar = str | int | float | bool | None

_VALIDATION_MATRIX = {
    ("YES", "像"): "true_positive_like",
    ("NO", "不像"): "true_negative_unlike",
    ("YES", "不像"): "possible_false_positive",
    ("NO", "像"): "possible_false_negative",
    ("YES", "勉强像"): "borderline",
    ("NO", "勉强像"): "borderline",
}
VALIDATION_RESULT_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "true_positive_like": "一致命中",
        "true_negative_unlike": "一致排除",
        "possible_false_positive": "疑似误报",
        "possible_false_negative": "疑似漏报",
        "borderline": "边界案例",
    }
)


def derive_validation_result(computer_result: str, human_label: str) -> str:
    try:
        return _VALIDATION_MATRIX[(computer_result, human_label)]
    except KeyError as error:
        raise ValueError(
            "computer_result and human_label must form a supported validation pair"
        ) from error


class ValidationStoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MigrationProvenance:
    source_path: str
    source_line_number: int
    source_line_content_sha256: str
    migration_fingerprint: str

    def __post_init__(self) -> None:
        if not self.source_path or "\\" in self.source_path:
            raise ValueError("migration source_path must be a relative POSIX path")
        if self.source_line_number <= 0:
            raise ValueError("migration source_line_number must be positive")
        for name, value in (
            ("source_line_content_sha256", self.source_line_content_sha256),
            ("migration_fingerprint", self.migration_fingerprint),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{name} must be a lowercase SHA-256")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_path": self.source_path,
            "source_line_number": self.source_line_number,
            "source_line_content_sha256": self.source_line_content_sha256,
            "migration_fingerprint": self.migration_fingerprint,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> MigrationProvenance:
        required = (
            "source_path",
            "source_line_number",
            "source_line_content_sha256",
            "migration_fingerprint",
        )
        missing = tuple(key for key in required if key not in value)
        if missing:
            raise ValueError("missing migration provenance fields: " + ", ".join(missing))
        return cls(
            source_path=str(value["source_path"]),
            source_line_number=int(value["source_line_number"]),
            source_line_content_sha256=str(value["source_line_content_sha256"]),
            migration_fingerprint=str(value["migration_fingerprint"]),
        )


@dataclass(frozen=True, slots=True)
class PatternValidation:
    recorded_at_utc: datetime
    symbol: str
    pattern_type: str
    pattern_display_name: str
    detector_version: str
    scan_as_of_date: str
    computer_result: str
    human_label: str
    validation_result: str
    reason_tags: tuple[str, ...]
    note: str
    review_window_start: str | None
    review_window_end: str | None
    diagnostics: dict[str, JSONScalar]
    migration_provenance: MigrationProvenance | None

    def __post_init__(self) -> None:
        if self.recorded_at_utc.utcoffset() != timedelta(0):
            raise ValueError("recorded_at_utc must be UTC")
        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be a normalized ticker")
        profile = get_pattern_profile(self.pattern_type)
        if self.pattern_display_name != profile.display_name_zh:
            raise ValueError("pattern_display_name must match the Pattern Profile")
        try:
            date.fromisoformat(self.scan_as_of_date)
        except (TypeError, ValueError) as error:
            raise ValueError("scan_as_of_date must be an ISO date") from error
        if self.computer_result not in {"YES", "NO"}:
            raise ValueError("computer_result must be YES or NO")
        if self.human_label not in HUMAN_LABELS:
            raise ValueError(f"human_label must be one of {HUMAN_LABELS}")
        expected_result = derive_validation_result(
            self.computer_result,
            self.human_label,
        )
        if self.validation_result != expected_result:
            raise ValueError("validation_result must be derived from computer and human labels")
        if len(self.note) > MAX_NOTE_LENGTH:
            raise ValueError(f"note must not exceed {MAX_NOTE_LENGTH} characters")

        if self.migration_provenance is None:
            if self.review_window_start is None or self.review_window_end is None:
                raise ValueError("review window is required for new validation records")
        if (self.review_window_start is None) != (self.review_window_end is None):
            raise ValueError("review window dates must both be set or both be null")
        if self.review_window_start is not None and self.review_window_end is not None:
            try:
                start = date.fromisoformat(self.review_window_start)
                end = date.fromisoformat(self.review_window_end)
            except (TypeError, ValueError) as error:
                raise ValueError("review window dates must be ISO dates") from error
            if start > end:
                raise ValueError("review window start must not follow end")

        normalized_diagnostics: dict[str, JSONScalar] = {}
        for key, value in self.diagnostics.items():
            if not isinstance(key, str) or not key:
                raise ValueError("diagnostic keys must be non-empty strings")
            if value is not None and not isinstance(value, str | int | float | bool):
                raise ValueError("diagnostic values must be JSON scalars")
            normalized_diagnostics[key] = value
        object.__setattr__(self, "diagnostics", normalized_diagnostics)

        if self.migration_provenance is None:
            unknown = tuple(tag for tag in self.reason_tags if tag not in profile.reason_tags)
            if unknown:
                raise ValueError("未知原因标签: " + ", ".join(unknown))
            if self.human_label in {"勉强像", "不像"} and not self.reason_tags:
                raise ValueError("勉强像或不像必须至少选择 1 个原因标签")
            if "其他" in self.reason_tags and not self.note.strip():
                raise ValueError("选择其他原因标签时必须填写备注")
            required_diagnostics = {field.key for field in profile.diagnostic_fields}
            missing_diagnostics = tuple(
                sorted(required_diagnostics.difference(normalized_diagnostics))
            )
            if missing_diagnostics:
                raise ValueError(
                    "missing profile diagnostics: " + ", ".join(missing_diagnostics)
                )

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (
            self.symbol,
            self.pattern_type,
            self.detector_version,
            self.scan_as_of_date,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "recorded_at_utc": self.recorded_at_utc.isoformat(),
            "symbol": self.symbol,
            "pattern_type": self.pattern_type,
            "pattern_display_name": self.pattern_display_name,
            "detector_version": self.detector_version,
            "scan_as_of_date": self.scan_as_of_date,
            "computer_result": self.computer_result,
            "human_label": self.human_label,
            "validation_result": self.validation_result,
            "reason_tags": list(self.reason_tags),
            "note": self.note,
            "review_window_start": self.review_window_start,
            "review_window_end": self.review_window_end,
            "diagnostics": dict(self.diagnostics),
            "migration_provenance": (
                self.migration_provenance.to_dict()
                if self.migration_provenance is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PatternValidation:
        required = (
            "recorded_at_utc",
            "symbol",
            "pattern_type",
            "pattern_display_name",
            "detector_version",
            "scan_as_of_date",
            "computer_result",
            "human_label",
            "validation_result",
            "reason_tags",
            "note",
            "review_window_start",
            "review_window_end",
            "diagnostics",
            "migration_provenance",
        )
        missing = tuple(key for key in required if key not in value)
        if missing:
            raise ValueError("missing validation fields: " + ", ".join(missing))
        tags = value["reason_tags"]
        diagnostics = value["diagnostics"]
        provenance = value["migration_provenance"]
        if not isinstance(tags, list | tuple):
            raise ValueError("reason_tags must be a list")
        if not isinstance(diagnostics, Mapping):
            raise ValueError("diagnostics must be an object")
        if provenance is not None and not isinstance(provenance, Mapping):
            raise ValueError("migration_provenance must be an object or null")
        return cls(
            recorded_at_utc=datetime.fromisoformat(str(value["recorded_at_utc"])),
            symbol=str(value["symbol"]),
            pattern_type=str(value["pattern_type"]),
            pattern_display_name=str(value["pattern_display_name"]),
            detector_version=str(value["detector_version"]),
            scan_as_of_date=str(value["scan_as_of_date"]),
            computer_result=str(value["computer_result"]),
            human_label=str(value["human_label"]),
            validation_result=str(value["validation_result"]),
            reason_tags=tuple(str(tag) for tag in tags),
            note=str(value["note"]),
            review_window_start=(
                str(value["review_window_start"])
                if value["review_window_start"] is not None
                else None
            ),
            review_window_end=(
                str(value["review_window_end"])
                if value["review_window_end"] is not None
                else None
            ),
            diagnostics={str(key): item for key, item in diagnostics.items()},
            migration_provenance=(
                MigrationProvenance.from_dict(provenance)
                if isinstance(provenance, Mapping)
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class FlatBaseValidation:
    recorded_at_utc: datetime
    symbol: str
    detector_version: str
    scan_as_of_date: str
    computer_flat_base: str
    base_length: int
    base_depth: float
    bottom_tests: int
    normalized_slope: float
    human_label: str
    reason_tags: tuple[str, ...]
    note: str

    def __post_init__(self) -> None:
        if self.recorded_at_utc.utcoffset() != timedelta(0):
            raise ValueError("recorded_at_utc must be UTC")
        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be a normalized ticker")
        if self.detector_version != "phase1-v1":
            raise ValueError("detector_version must remain phase1-v1")
        try:
            date.fromisoformat(self.scan_as_of_date)
        except (TypeError, ValueError) as error:
            raise ValueError("scan_as_of_date must be an ISO date") from error
        if self.computer_flat_base not in {"YES", "NO"}:
            raise ValueError("computer_flat_base must be YES or NO")
        if self.base_length <= 0 or self.bottom_tests < 0:
            raise ValueError("detector diagnostics must be non-negative")
        if self.human_label not in HUMAN_LABELS:
            raise ValueError(f"human_label must be one of {HUMAN_LABELS}")
        unknown = tuple(tag for tag in self.reason_tags if tag not in REASON_TAGS)
        if unknown:
            raise ValueError("未知原因标签: " + ", ".join(unknown))
        if self.human_label == "像" and self.reason_tags:
            raise ValueError("像 不允许填写原因标签")
        if len(self.note) > MAX_NOTE_LENGTH:
            raise ValueError(f"note must not exceed {MAX_NOTE_LENGTH} characters")

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.symbol, self.detector_version, self.scan_as_of_date)

    def to_dict(self) -> dict[str, object]:
        return {
            "recorded_at_utc": self.recorded_at_utc.isoformat(),
            "symbol": self.symbol,
            "detector_version": self.detector_version,
            "scan_as_of_date": self.scan_as_of_date,
            "computer_flat_base": self.computer_flat_base,
            "base_length": self.base_length,
            "base_depth": self.base_depth,
            "bottom_tests": self.bottom_tests,
            "normalized_slope": self.normalized_slope,
            "human_label": self.human_label,
            "reason_tags": list(self.reason_tags),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FlatBaseValidation:
        required = (
            "recorded_at_utc",
            "symbol",
            "detector_version",
            "scan_as_of_date",
            "computer_flat_base",
            "base_length",
            "base_depth",
            "bottom_tests",
            "normalized_slope",
            "human_label",
            "reason_tags",
            "note",
        )
        missing = tuple(key for key in required if key not in value)
        if missing:
            raise ValueError("missing validation fields: " + ", ".join(missing))
        recorded = datetime.fromisoformat(str(value["recorded_at_utc"]))
        tags = value["reason_tags"]
        if not isinstance(tags, list | tuple):
            raise ValueError("reason_tags must be a list")
        return cls(
            recorded_at_utc=recorded,
            symbol=str(value["symbol"]),
            detector_version=str(value["detector_version"]),
            scan_as_of_date=str(value["scan_as_of_date"]),
            computer_flat_base=str(value["computer_flat_base"]),
            base_length=int(value["base_length"]),
            base_depth=float(value["base_depth"]),
            bottom_tests=int(value["bottom_tests"]),
            normalized_slope=float(value["normalized_slope"]),
            human_label=str(value["human_label"]),
            reason_tags=tuple(str(tag) for tag in tags),
            note=str(value["note"]),
        )


def build_pattern_validation(
    *,
    recorded_at_utc: datetime,
    symbol: str,
    pattern_type: str,
    detector_version: str,
    scan_as_of_date: date,
    computer_result: str,
    human_label: str,
    reason_tags: Iterable[str],
    note: str,
    review_window_start: date,
    review_window_end: date,
    diagnostics: Mapping[str, JSONScalar],
) -> PatternValidation:
    profile = get_pattern_profile(pattern_type)
    normalized_tags = tuple(
        dict.fromkeys(
            tag
            for raw_tag in reason_tags
            if (tag := str(raw_tag).strip())
        )
    )
    return PatternValidation(
        recorded_at_utc=(
            recorded_at_utc.astimezone(UTC)
            if recorded_at_utc.tzinfo is not None
            else recorded_at_utc
        ),
        symbol=symbol.strip().upper(),
        pattern_type=profile.pattern_type,
        pattern_display_name=profile.display_name_zh,
        detector_version=detector_version,
        scan_as_of_date=scan_as_of_date.isoformat(),
        computer_result=computer_result,
        human_label=human_label,
        validation_result=derive_validation_result(computer_result, human_label),
        reason_tags=normalized_tags,
        note=note.strip(),
        review_window_start=review_window_start.isoformat(),
        review_window_end=review_window_end.isoformat(),
        diagnostics=dict(diagnostics),
        migration_provenance=None,
    )


def build_validation(
    scan_row: Mapping[str, object],
    scan_as_of_date: date,
    human_label: str,
    reason_tags: Iterable[str],
    note: str,
    recorded_at_utc: datetime,
) -> FlatBaseValidation:
    fields = {
        "Symbol": "symbol",
        "Detector Version": "detector_version",
        "Flat Base": "computer_flat_base",
        "Base Length": "base_length",
        "Base Depth": "base_depth",
        "Bottom Tests": "bottom_tests",
        "Normalized Slope": "normalized_slope",
    }
    for source in fields:
        if source not in scan_row or scan_row[source] is None:
            raise ValueError(f"scan row requires {source}")

    normalized_tags = tuple(dict.fromkeys(str(tag).strip() for tag in reason_tags))
    return FlatBaseValidation(
        recorded_at_utc=recorded_at_utc.astimezone(UTC)
        if recorded_at_utc.tzinfo is not None
        else recorded_at_utc,
        symbol=str(scan_row["Symbol"]).strip().upper(),
        detector_version=str(scan_row["Detector Version"]),
        scan_as_of_date=scan_as_of_date.isoformat(),
        computer_flat_base=str(scan_row["Flat Base"]),
        base_length=int(scan_row["Base Length"]),
        base_depth=float(scan_row["Base Depth"]),
        bottom_tests=int(scan_row["Bottom Tests"]),
        normalized_slope=float(scan_row["Normalized Slope"]),
        human_label=human_label,
        reason_tags=normalized_tags,
        note=note.strip(),
    )


def append_validation(path: str | Path, record: FlatBaseValidation) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")


def read_validation_history(
    path: str | Path = DEFAULT_VALIDATION_PATH,
) -> tuple[FlatBaseValidation, ...]:
    target = Path(path)
    if not target.exists():
        return ()
    records: list[FlatBaseValidation] = []
    for line_number, line in enumerate(
        target.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("record must be a JSON object")
            records.append(FlatBaseValidation.from_dict(payload))
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise ValidationStoreError(
                f"invalid validation JSON at line {line_number}: {error}"
            ) from error
    return tuple(records)


def latest_validations(
    records: Iterable[FlatBaseValidation],
) -> dict[tuple[str, str, str], FlatBaseValidation]:
    latest: dict[tuple[str, str, str], FlatBaseValidation] = {}
    for record in records:
        previous = latest.get(record.key)
        if previous is None or record.recorded_at_utc > previous.recorded_at_utc:
            latest[record.key] = record
    return latest
