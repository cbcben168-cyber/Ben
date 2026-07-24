"""Load and validate the versioned strategy configuration contract."""

from datetime import date
from math import isfinite
from numbers import Real
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
ALLOWED_FIELDS = frozenset(
    (*REQUIRED_FIELDS, *DEFAULTS, "in_sample_period", "out_of_sample_period")
)
SUPPORTED_POSITION_SIZING = {"type": "cash_limited_long_only"}


def _parse_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO date") from error


def _finite_number(value: Any, field: str, *, positive: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{field} must be a finite number") from error
    if not isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    if positive and number <= 0:
        raise ValueError(f"{field} must be positive")
    if not positive and number < 0:
        raise ValueError(f"{field} must use non-negative basis points")
    return number


def _validate_unparsed_period(data: Mapping[str, Any], field: str) -> None:
    if data.get(field) is not None:
        raise ValueError(f"{field} is not supported until period parsing is available")


def _validate_optimization_allowed(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("optimization_allowed must be a boolean")
    return value


def _basis_points(mapping: Any, field: str) -> float:
    if not isinstance(mapping, Mapping) or mapping.get("type") != "basis_points":
        raise ValueError(f"{field} must use non-negative basis points")
    try:
        value = _finite_number(mapping["value"], field, positive=False)
    except KeyError as error:
        raise ValueError(f"{field} must use non-negative basis points") from error
    return value


def validate_strategy_mapping(payload: Mapping[str, Any]) -> StrategySpec:
    if not isinstance(payload, Mapping):
        raise ValueError("strategy config must be a YAML mapping")

    unknown_fields = set(payload) - ALLOWED_FIELDS
    if unknown_fields:
        raise ValueError(
            "unknown top-level configuration field(s): "
            + ", ".join(sorted(map(str, unknown_fields)))
        )

    data = dict(DEFAULTS)
    data.update(payload)
    for field in REQUIRED_FIELDS:
        if field not in data:
            raise ValueError(f"missing required field: {field}")

    start_date = _parse_date(data["start_date"], "start_date")
    end_date = _parse_date(data["end_date"], "end_date")
    if start_date >= end_date:
        raise ValueError("start_date must precede end_date")

    initial_capital = _finite_number(
        data["initial_capital"], "initial_capital", positive=True
    )

    if not isinstance(data["entry_rules"], list) or not data["entry_rules"]:
        raise ValueError("entry_rules must be a non-empty list")
    if not isinstance(data["exit_rules"], list) or not data["exit_rules"]:
        raise ValueError("exit_rules must be a non-empty list")
    if data["position_sizing"] != SUPPORTED_POSITION_SIZING:
        raise ValueError(
            "position_sizing must be exactly {'type': 'cash_limited_long_only'}"
        )

    commission_bps = _basis_points(data["commission_model"], "commission_model")
    slippage_bps = _basis_points(data["slippage_model"], "slippage_model")
    _validate_unparsed_period(data, "in_sample_period")
    _validate_unparsed_period(data, "out_of_sample_period")
    optimization_allowed = _validate_optimization_allowed(data["optimization_allowed"])

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
        optimization_allowed=optimization_allowed,
        report_language=str(data["report_language"]),
        raw=data,
    )


def load_strategy_spec(path: Path) -> StrategySpec:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("strategy config must be a YAML mapping")
    return validate_strategy_mapping(payload)


def check_capabilities(spec: StrategySpec) -> CapabilityResult:
    """Check whether a spec stays within the fixed Phase 1 engine boundary."""
    supported_entry = ({"type": "ema_crossover", "fast_period": 50, "slow_period": 200},)
    supported_exit = ({"type": "ema_crossunder"},)
    reasons: list[str] = []
    data_reasons: list[str] = []
    if spec.asset_class != "equity":
        reasons.append(f"Phase 1 supports asset_class 'equity' only (received {spec.asset_class!r})")
    if spec.symbol not in {"SPY", "QQQ"}:
        reasons.append(f"Phase 1 supports symbols SPY and QQQ only (received {spec.symbol!r})")
    if spec.timeframe != "1d":
        reasons.append(f"Phase 1 supports timeframe '1d' only (received {spec.timeframe!r})")
    if spec.benchmark != "buy_and_hold":
        reasons.append(
            f"Phase 1 supports benchmark 'buy_and_hold' only (received {spec.benchmark!r})"
        )
    if spec.fill_timing != "next_bar":
        reasons.append(f"Phase 1 supports fill_timing 'next_bar' only (received {spec.fill_timing!r})")
    if spec.optimization_allowed is not False:
        reasons.append("Phase 1 requires optimization_allowed to be false")
    if spec.report_language != "zh-CN":
        reasons.append(f"Phase 1 supports report_language 'zh-CN' only (received {spec.report_language!r})")
    if spec.data_source != "validated_local_cache_first":
        data_reasons.append(
            "Phase 1 requires data_source 'validated_local_cache_first' "
            f"(received {spec.data_source!r})"
        )
    if spec.entry_rules != supported_entry:
        reasons.append("only fixed EMA50/EMA200 crossover is supported")
    if spec.exit_rules != supported_exit:
        reasons.append("only fixed EMA crossunder exit is supported")
    if spec.position_sizing != SUPPORTED_POSITION_SIZING:
        reasons.append("position sizing is not supported")
    if reasons or data_reasons:
        return CapabilityResult(
            (
                CapabilityStatus.DATA_CAPABILITY_BLOCKER
                if data_reasons and not reasons
                else CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER
            ),
            tuple(reasons + data_reasons),
            ("daily OHLCV",),
            ("fixed EMA50/EMA200",),
        )
    return CapabilityResult(
        CapabilityStatus.SUPPORTED,
        (),
        ("validated standardized daily OHLCV",),
        ("tv_quant.strategy.run_backtest",),
    )
