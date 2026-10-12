from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


ENGINE_VERSION = "C1_PHASE3_EDGE_ENGINE_V1"
TRAIN_START = "2025-10-01"
TRAIN_END = "2026-06-30"
EXPECTED_BARS = 19_470
EXPECTED_SESSIONS = 251
EXPECTED_TRAIN_SESSIONS = 187
EXPECTED_DATA_SHA256 = "e5e3ab7cfa981be022388b7a54952a6f8fa29e2dc0043672edf4e84997940e2f"
EXPECTED_AUDIT_MANIFEST_SHA256 = "f1f750867dd4a32eaf74d4d776dcf47002f0aa7f5b123db4177e57c4a1a266da"
EARLY_CLOSES = {"2025-07-03", "2025-11-28", "2025-12-24"}
REHAB_DATES = {"2025-09-19", "2025-12-19", "2026-03-20", "2026-06-18"}
HORIZONS = (3, 6, 12)
HORIZON_MINUTES = {3: 15, 6: 30, 12: 60}
COST_SCENARIOS_BPS = (2.0, 4.0, 6.0)
BOOTSTRAP_ITERATIONS = 2_000
BOOTSTRAP_SEED = 31_415_926


@dataclass(frozen=True)
class FactorSpec:
    factor_id: str
    name_en: str
    name_zh: str
    category: str
    mechanism: str
    formula: str
    parameters: str
    as_of: str
    direction: str
    event_unit: str
    data_requirements: str
    independent_unit: str
    strategy_role: str
    eligibility: str
    attempt_version: str


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    variant_id: str
    name_zh: str
    setup: str
    trigger: str
    direction: str
    entry: str
    stop: str
    target: str
    time_exit_bars: int
    filter_factor: str
    cost_round_trip_bps: float
    status: str
    attempt_version: str


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_factor_registry(path: Path) -> list[FactorSpec]:
    rows = [FactorSpec(**row) for row in _read_csv(path)]
    ids = [row.factor_id for row in rows]
    if not 30 <= len(rows) <= 50:
        raise ValueError(f"FACTOR_COUNT_OUT_OF_RANGE:{len(rows)}")
    if len(ids) != len(set(ids)):
        raise ValueError("DUPLICATE_FACTOR_ID")
    expected = [f"F{number:03d}" for number in range(1, len(rows) + 1)]
    if ids != expected:
        raise ValueError("FACTOR_IDS_NOT_CONTIGUOUS")
    if any(row.data_requirements != "OHLC" for row in rows):
        raise ValueError("INELIGIBLE_DATA_REQUIREMENT")
    return rows


def load_strategy_registry(path: Path) -> list[StrategySpec]:
    rows: list[StrategySpec] = []
    for raw in _read_csv(path):
        raw["time_exit_bars"] = int(raw["time_exit_bars"])
        raw["cost_round_trip_bps"] = float(raw["cost_round_trip_bps"])
        rows.append(StrategySpec(**raw))
    variants = [row.variant_id for row in rows]
    if len(variants) != len(set(variants)):
        raise ValueError("DUPLICATE_STRATEGY_VARIANT")
    if {row.strategy_id for row in rows} != {"S01", "S02", "S03"}:
        raise ValueError("FROZEN_STRATEGY_SET_MISMATCH")
    return rows
