"""Registration tests for the V2.2A data-foundation boundary."""

from __future__ import annotations

from pathlib import Path

import tv_quant.data_foundation as data_foundation

from tv_quant.contracts.capability_registry import load_capability_registry
from tv_quant.contracts.status_codes import BlockerCode


REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "capability-registry-v2.1.json"
)


def test_v22a_data_foundation_package_is_registered() -> None:
    assert data_foundation.__package__ == "tv_quant.data_foundation"


def test_v22a_capabilities_start_blocked_and_existing_v21_records_coexist() -> None:
    registry = load_capability_registry(REGISTRY_PATH)
    record = registry.require("market-data.local-csv.daily", "v2.2a")

    assert record.implementation_status == "not_implemented"
    assert record.blocker_code is BlockerCode.DATA_CAPABILITY_BLOCKER
    assert (
        registry.require("phase1.ema.daily.golden", "v2.1").formal_status
        == "formal_verified"
    )
