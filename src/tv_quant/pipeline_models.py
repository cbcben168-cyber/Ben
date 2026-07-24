from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class CapabilityStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    STRATEGY_CAPABILITY_BLOCKER = "STRATEGY_CAPABILITY_BLOCKER"
    DATA_CAPABILITY_BLOCKER = "DATA_CAPABILITY_BLOCKER"


class AuditStatus(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"
    STRATEGY_CAPABILITY_BLOCKER = "STRATEGY_CAPABILITY_BLOCKER"
    DATA_CAPABILITY_BLOCKER = "DATA_CAPABILITY_BLOCKER"


@dataclass(frozen=True)
class StrategySpec:
    strategy_name: str
    asset_class: str
    symbol: str
    benchmark: str
    timeframe: str
    start_date: date
    end_date: date
    initial_capital: float
    entry_rules: tuple[Mapping[str, Any], ...]
    exit_rules: tuple[Mapping[str, Any], ...]
    position_sizing: Mapping[str, Any]
    commission_bps: float
    slippage_bps: float
    fill_timing: str
    data_source: str
    in_sample_period: tuple[date, date] | None
    out_of_sample_period: tuple[date, date] | None
    optimization_allowed: bool
    report_language: str
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class CapabilityResult:
    status: CapabilityStatus
    reasons: tuple[str, ...]
    required_data: tuple[str, ...]
    required_engine: tuple[str, ...]


@dataclass(frozen=True)
class AuditIssue:
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class AuditReport:
    status: AuditStatus
    checks: Mapping[str, bool]
    issues: tuple[AuditIssue, ...]
    warnings: tuple[str, ...]
