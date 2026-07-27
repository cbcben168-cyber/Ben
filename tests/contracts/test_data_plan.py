"""Tests for declarative V2.1 data requirements without data access."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import sys

import pytest

from tv_quant.contracts.normalized_ir import normalize_strategy_spec
from tv_quant.contracts.strategy_v2 import validate_strategy_mapping_v2


class _Registry:
    def validate_strategy(self, _spec: object) -> tuple[object, ...]:
        return ()

    def __getattr__(self, _name: str) -> object:
        raise AssertionError("DataPlan must not inspect a provider or registry implementation")


def _payload() -> dict[str, object]:
    price = {"node_type": "price_ref", "field": "close", "unit": "USD"}
    ema = {
        "node_type": "indicator_ref",
        "name": "EMA",
        "parameters": {"period": 200},
        "output": "series",
        "unit": "USD",
    }
    return {
        "schema_version": "v2.1",
        "strategy_id": "ema-cross-aapl",
        "strategy_family": "ema_crossover",
        "strategy_name": "AAPL EMA crossover",
        "symbol": "AAPL",
        "market": "US_EQUITY",
        "timeframe": "1d",
        "session": {
            "timezone": "America/New_York",
            "regular_hours_only": True,
            "calendar_id": "XNYS",
        },
        "backtest_range": {"start": "2024-01-02", "end": "2024-12-31"},
        "initial_capital": {"amount": 100000, "currency": "USD"},
        "entry": {"node_type": "compare", "operator": "gt", "left": price, "right": ema},
        "exit": {"node_type": "compare", "operator": "lt", "left": price, "right": ema},
        "filters": [],
        "position_sizing": {"type": "fixed_fraction", "fraction": "1"},
        "stop": {"enabled": False},
        "target": {"enabled": False},
        "fill_timing": "next_bar_open",
        "data": {"source": "validated_local_cache_first", "cost_profile": "legacy_bps"},
        "benchmark": {"type": "buy_and_hold", "symbol": "same_as_strategy"},
        "plugin": None,
        "optimization_allowed": False,
        "report_language": "zh-CN",
    }


def _ir(payload: dict[str, object] | None = None):
    result = normalize_strategy_spec(
        validate_strategy_mapping_v2(payload or _payload()),
        capability_registry=_Registry(),
        source_config_hash="source-config-hash",
    )
    assert result.ir is not None
    return result.ir


def test_primary_dataset_contains_required_fields() -> None:
    """Dropping strategy identity or UTC OHLCV requirements makes a plan unusable."""
    from tv_quant.contracts.data_plan import build_data_plan

    plan = build_data_plan(_ir(), _Registry())

    assert plan.primary.symbol == "AAPL"
    assert plan.primary.market == "US_EQUITY"
    assert plan.primary.timeframe == "1d"
    assert plan.primary.timezone == "UTC"
    assert plan.primary.session["timezone"] == "America/New_York"
    assert (plan.primary.requested_start, plan.primary.requested_end) == ("2024-01-02", "2024-12-31")


def test_data_plan_declares_warmup_adjustment_actions_and_cost() -> None:
    """An EMA lookback or market-data policy omission must be visible before execution."""
    from tv_quant.contracts.data_plan import build_data_plan

    plan = build_data_plan(_ir(), _Registry())

    assert plan.primary.warmup_bars == 200
    assert plan.primary.adjustment_requirement == "adjusted_ohlcv"
    assert plan.primary.corporate_action_requirement == "corporate_actions_required"
    assert plan.primary.cost_profile_requirement == "legacy_bps"


def test_auxiliary_requirements_are_structural() -> None:
    """Auxiliary inputs must be declared, never fetched while the plan is built."""
    from tv_quant.contracts.data_plan import build_data_plan

    payload = _payload()
    payload["data"] = {
        "source": "validated_local_cache_first",
        "auxiliary": [{"dataset_role": "vix", "symbol": "^VIX", "timeframe": "1d"}],
    }
    plan = build_data_plan(_ir(payload), _Registry())

    assert len(plan.auxiliary) == 1
    assert plan.auxiliary[0].dataset_role == "vix"
    assert plan.auxiliary[0].symbol == "^VIX"
    assert "STRUCTURAL_ONLY" in plan.auxiliary[0].capability_requirements


def test_provider_preference_and_range_change_hash() -> None:
    """A provider-order or requested-range change must bind a distinct data plan."""
    from tv_quant.contracts.data_plan import build_data_plan, data_plan_hash

    baseline = build_data_plan(_ir(), _Registry())
    changed_payload = deepcopy(_payload())
    changed_payload["backtest_range"] = {"start": "2024-02-01", "end": "2024-12-31"}
    changed = build_data_plan(_ir(changed_payload), _Registry())

    assert baseline.primary.provider_preference == (
        "validated_local_cache_first",
        "futu_opend_incremental",
        "validated_csv_parquet_import",
        "yfinance_smoke_only",
    )
    assert data_plan_hash(baseline) == baseline.data_plan_hash
    assert baseline.data_plan_hash != changed.data_plan_hash


def test_public_data_plan_constructors_deep_freeze_mappings() -> None:
    """Mutating caller-owned nested mappings must not alter a declared plan or its hash."""
    from tv_quant.contracts.data_plan import DataPlan, DatasetRequirement

    session = {"timezone": "America/New_York", "nested": {"value": 1}}
    requested_range = {"start": "2024-01-02", "details": {"end": "2024-12-31"}}
    requirement = DatasetRequirement(
        dataset_role="primary",
        provider_preference=("validated_local_cache_first",),
        symbol="AAPL",
        market="US_EQUITY",
        timeframe="1d",
        session=session,
        timezone="UTC",
        requested_start="2024-01-02",
        requested_end="2024-12-31",
        warmup_bars=0,
        adjustment_requirement="adjusted_ohlcv",
        corporate_action_requirement="corporate_actions_required",
        cost_profile_requirement="cost_profile_required",
        capability_requirements=("daily_ohlcv_utc",),
    )
    plan = DataPlan(
        schema_version="v2.1",
        primary=requirement,
        auxiliary=(),
        requested_range=requested_range,
        data_plan_hash="stable-hash",
    )

    session["nested"]["value"] = 2
    requested_range["details"]["end"] = "2025-01-01"

    assert requirement.session["nested"]["value"] == 1
    assert plan.requested_range["details"]["end"] == "2024-12-31"
    with pytest.raises(TypeError):
        requirement.session["timezone"] = "UTC"  # type: ignore[index]


def test_data_plan_accepts_canonicalized_numeric_ir_metadata() -> None:
    """Valid Decimal input reaches DataPlan as canonical text, never as a mutable numeric object."""
    from tv_quant.contracts.data_plan import build_data_plan

    payload = _payload()
    payload["data"] = {
        "source": "validated_local_cache_first",
        "retention_days": Decimal("2.50"),
    }
    ir = _ir(payload)

    assert ir.data["retention_days"] == "2.5"
    assert build_data_plan(ir, _Registry()).primary.symbol == "AAPL"


def test_unimplemented_capability_does_not_call_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blocked future capability must remain a declaration, even when providers would crash."""
    from tv_quant.contracts.data_plan import build_data_plan

    monkeypatch.setitem(sys.modules, "tv_quant.futu_downloader", None)
    monkeypatch.setitem(sys.modules, "yfinance", None)
    plan = build_data_plan(_ir(), _Registry())

    assert "STRUCTURAL_ONLY" in plan.primary.capability_requirements
