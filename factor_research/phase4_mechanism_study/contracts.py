from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

FAMILY = ("P4_M01_ALL", "P4_M02_ALL", "P4_M06_ALL")
RULE_HASH_SHA256 = "dc9b4201cbd4d11d9f7273f5bff0d31effed977f4f15522b4a051fac43a894cb"
TRAIN_START = "2025-10-01"
TRAIN_END = "2026-06-30"
TRAIN_SESSIONS = 187
ADJUSTMENT_BASIS = "AS_OF_DYNAMIC_FORWARD_FROM_GET_REHAB"
PRIMARY_COST = 0.0004
SENSITIVITY_COST = 0.0002
ROBUSTNESS_COST = 0.0006
BOOTSTRAP_ITERATIONS = 2_000
BOOTSTRAP_SEED = 31_415_926


class Phase4ContractError(ValueError):
    """A fail-closed Phase 4 contract violation."""


class DataIncompleteError(Phase4ContractError):
    """The globally qualified OHLC grid is incomplete."""


@dataclass(frozen=True)
class SessionSpec:
    session_date: str
    close_time_et: str


def canonical_rules_hash(document: Mapping[str, Any]) -> str:
    payload = json.dumps(
        document["rules"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_and_verify_preregistration(path: Path | None = None) -> dict[str, Any]:
    source = path or Path(__file__).with_name("preregistration.json")
    document = json.loads(source.read_text(encoding="utf-8"))
    actual = canonical_rules_hash(document)
    if actual != document.get("rule_hash_sha256") or actual != RULE_HASH_SHA256:
        raise Phase4ContractError("RULE_HASH_MISMATCH")
    family = tuple(document["rules"]["family"]["hypotheses"])
    if family != FAMILY or document["rules"]["family"]["size"] != len(FAMILY):
        raise Phase4ContractError("INCOMPLETE_PRIMARY_FAMILY")
    return document


def assert_strict_past_window(start: int, end: int, current: int, expected_count: int) -> None:
    if start < 0 or end != current or end - start != expected_count:
        raise Phase4ContractError("LOOKAHEAD_OR_WINDOW_LENGTH_VIOLATION")


def assert_as_of_positions(positions: list[int] | tuple[int, ...], current: int) -> None:
    if any(position > current for position in positions):
        raise Phase4ContractError("FUTURE_DATA_ACCESS")
