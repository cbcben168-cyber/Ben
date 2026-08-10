from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


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


class ValidationStoreError(RuntimeError):
    pass


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
