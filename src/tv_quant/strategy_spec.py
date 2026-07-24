"""Load and validate the versioned strategy configuration contract."""

from datetime import date
from pathlib import Path
from typing import Any, Mapping

import yaml

from .pipeline_models import CapabilityResult, CapabilityStatus, StrategySpec


DEFAULTS = {
    "benchmark": "buy_and_hold",
    "fill_timing": "next_bar",
    "optimization_allowed": False,
    "report_language": "zh-CN",
    "data_source": "validated_local_cache_first",
}
REQUIRED_FIELDS = (
    "strategy_name", "asset_class", "symbol", "timeframe",
    "start_date", "end_date", "initial_capital", "entry_rules",
    "exit_rules", "position_sizing", "commission_model", "slippage_model",
)


def _parse_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO date") from error


def _basis_points(mapping: Any, field: str) -> float:
    if not isinstance(mapping, Mapping) or mapping.get("type") != "basis_points":
        raise ValueError(f"{field} must use non-negative basis points")
    try:
        value = float(mapping["value"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{field} must use non-negative basis points") from error
    if value < 0:
        raise ValueError(f"{field} must use non-negative basis points")
    return value


def validate_strategy_mapping(payload: Mapping[str, Any]) -> StrategySpec:
    if not isinstance(payload, Mapping):
        raise ValueError("strategy config must be a YAML mapping")

    data = dict(DEFAULTS)
    data.update(payload)
    for field in REQUIRED_FIELDS:
        if field not in data:
            raise ValueError(f"missing required field: {field}")

    start_date = _parse_date(data["start_date"], "start_date")
    end_date = _parse_date(data["end_date"], "end_date")
    if start_date >= end_date:
        raise ValueError("start_date must precede end_date")

    try:
        initial_capital = float(data["initial_capital"])
    except (TypeError, ValueError) as error:
        raise ValueError("initial_capital must be positive") from error
    if initial_capital <= 0:
        raise ValueError("initial_capital must be positive")

    if not isinstance(data["entry_rules"], list) or not data["entry_rules"]:
        raise ValueError("entry_rules must be a non-empty list")
    if not isinstance(data["exit_rules"], list) or not data["exit_rules"]:
        raise ValueError("exit_rules must be a non-empty list")
    if not isinstance(data["position_sizing"], Mapping):
        raise ValueError("position_sizing must be a mapping")

    commission_bps = _basis_points(data["commission_model"], "commission_model")
    slippage_bps = _basis_points(data["slippage_model"], "slippage_model")

    return StrategySpec(
        strategy_name=str(data["strategy_name"]),
        asset_class=str(data["asset_class"]),
        symbol=str(data["symbol"]).upper(),
        benchmark=str(data["benchmark"]),
        timeframe=str(data["timeframe"]),
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        entry_rules=tuple(data["entry_rules"]),
        exit_rules=tuple(data["exit_rules"]),
        position_sizing=dict(data["position_sizing"]),
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        fill_timing=str(data["fill_timing"]),
        data_source=str(data["data_source"]),
        in_sample_period=None,
        out_of_sample_period=None,
        optimization_allowed=bool(data["optimization_allowed"]),
        report_language=str(data["report_language"]),
        raw=data,
    )


def load_strategy_spec(path: Path) -> StrategySpec:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("strategy config must be a YAML mapping")
    return validate_strategy_mapping(payload)


def check_capabilities(spec: StrategySpec) -> CapabilityResult:
    """Check whether the Task 1 fixed EMA engine can consume this spec."""
    supported_entry = ({"type": "ema_crossover", "fast_period": 50, "slow_period": 200},)
    supported_exit = ({"type": "ema_crossunder"},)
    reasons: list[str] = []
    if spec.entry_rules != supported_entry:
        reasons.append("only fixed EMA50/EMA200 crossover is supported")
    if spec.exit_rules != supported_exit:
        reasons.append("only fixed EMA crossunder exit is supported")
    if spec.position_sizing.get("type") != "cash_limited_long_only":
        reasons.append("position sizing is not supported")
    if reasons:
        return CapabilityResult(
            CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER,
            tuple(reasons),
            ("daily OHLCV",),
            ("fixed EMA50/EMA200",),
        )
    return CapabilityResult(
        CapabilityStatus.SUPPORTED,
        (),
        ("validated standardized daily OHLCV",),
        ("tv_quant.strategy.run_backtest",),
    )
