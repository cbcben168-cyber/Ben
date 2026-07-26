"""Deterministic status metadata for the V2 pipeline contract."""

from dataclasses import dataclass
from enum import Enum

from tv_quant.run_manifest import canonical_hash


class PipelineStatus(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"
    STRATEGY_CAPABILITY_BLOCKER = "STRATEGY_CAPABILITY_BLOCKER"
    DATA_CAPABILITY_BLOCKER = "DATA_CAPABILITY_BLOCKER"


class BlockerCode(str, Enum):
    STRATEGY_CAPABILITY_BLOCKER = "STRATEGY_CAPABILITY_BLOCKER"
    DATA_CAPABILITY_BLOCKER = "DATA_CAPABILITY_BLOCKER"


@dataclass(frozen=True)
class StatusDefinition:
    status: str
    recoverable: bool
    retryable: bool
    terminal: bool
    user_action: str
    pipeline_stage: str
    formal_result_eligible: bool


STATUS_DEFINITIONS = (
    StatusDefinition("PASS", False, False, True, "none", "audit", True),
    StatusDefinition(
        "CONDITIONAL_PASS", True, False, True, "review_warnings", "audit", False
    ),
    StatusDefinition("FAIL", True, False, True, "fix_and_rerun", "audit", False),
    StatusDefinition(
        "STRATEGY_CAPABILITY_BLOCKER",
        True,
        False,
        True,
        "revise_strategy_request",
        "capability_check",
        False,
    ),
    StatusDefinition(
        "DATA_CAPABILITY_BLOCKER",
        True,
        True,
        True,
        "provide_validated_local_cache",
        "data_preflight",
        False,
    ),
)

_STATUS_BY_CODE = {definition.status: definition for definition in STATUS_DEFINITIONS}


def status_definition(code: PipelineStatus | BlockerCode | str) -> StatusDefinition:
    """Return immutable metadata for a pipeline status or blocker code."""
    value = code.value if isinstance(code, Enum) else code
    return _STATUS_BY_CODE[value]


def status_snapshot_hash() -> str:
    """Return a canonical digest of the complete status registry."""
    return canonical_hash(
        {
            "statuses": [
                {
                    "status": definition.status,
                    "recoverable": definition.recoverable,
                    "retryable": definition.retryable,
                    "terminal": definition.terminal,
                    "user_action": definition.user_action,
                    "pipeline_stage": definition.pipeline_stage,
                    "formal_result_eligible": definition.formal_result_eligible,
                }
                for definition in STATUS_DEFINITIONS
            ]
        }
    )
