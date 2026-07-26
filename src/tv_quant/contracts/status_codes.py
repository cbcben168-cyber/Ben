"""Deterministic V2 pipeline-status and blocker-code metadata."""

from dataclasses import dataclass
from enum import Enum

from tv_quant.run_manifest import canonical_hash


class PipelineStatus(str, Enum):
    SUCCESS = "SUCCESS"
    CONDITIONAL_SUCCESS = "CONDITIONAL_SUCCESS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class BlockerCode(str, Enum):
    CONFIG_VALIDATION_BLOCKER = "CONFIG_VALIDATION_BLOCKER"
    SCHEMA_VERSION_BLOCKER = "SCHEMA_VERSION_BLOCKER"
    SCHEMA_COMPATIBILITY_BLOCKER = "SCHEMA_COMPATIBILITY_BLOCKER"
    INITIAL_CAPITAL_POLICY_BLOCKER = "INITIAL_CAPITAL_POLICY_BLOCKER"
    POSITION_SIZING_INPUT_BLOCKER = "POSITION_SIZING_INPUT_BLOCKER"
    RELATIVE_STRENGTH_BENCHMARK_BLOCKER = "RELATIVE_STRENGTH_BENCHMARK_BLOCKER"
    STRATEGY_CAPABILITY_BLOCKER = "STRATEGY_CAPABILITY_BLOCKER"
    DATA_CAPABILITY_BLOCKER = "DATA_CAPABILITY_BLOCKER"
    DATA_VALIDATION_BLOCKER = "DATA_VALIDATION_BLOCKER"
    CORPORATE_ACTION_DATA_BLOCKER = "CORPORATE_ACTION_DATA_BLOCKER"
    LIQUIDITY_CAPABILITY_BLOCKER = "LIQUIDITY_CAPABILITY_BLOCKER"
    FUTU_OPEND_START_BLOCKER = "FUTU_OPEND_START_BLOCKER"
    FUTU_LOGIN_BLOCKER = "FUTU_LOGIN_BLOCKER"
    FUTU_MARKET_PERMISSION_BLOCKER = "FUTU_MARKET_PERMISSION_BLOCKER"
    FUTU_QUOTA_BLOCKER = "FUTU_QUOTA_BLOCKER"
    PLUGIN_REQUIRED = "PLUGIN_REQUIRED"
    PLUGIN_LOGIC_CHANGE_REQUIRED = "PLUGIN_LOGIC_CHANGE_REQUIRED"
    PLUGIN_PARAMETER_VALIDATION_BLOCKER = "PLUGIN_PARAMETER_VALIDATION_BLOCKER"
    PLUGIN_VALIDATION_BLOCKER = "PLUGIN_VALIDATION_BLOCKER"
    ENGINE_CAPABILITY_BLOCKER = "ENGINE_CAPABILITY_BLOCKER"
    FILTER_DATA_CAPABILITY_BLOCKER = "FILTER_DATA_CAPABILITY_BLOCKER"
    INTRADAY_TIME_SEMANTICS_BLOCKER = "INTRADAY_TIME_SEMANTICS_BLOCKER"
    BENCHMARK_FAIRNESS_BLOCKER = "BENCHMARK_FAIRNESS_BLOCKER"
    COST_PROFILE_CAPABILITY_BLOCKER = "COST_PROFILE_CAPABILITY_BLOCKER"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    CONFIRMATION_EXPIRED = "CONFIRMATION_EXPIRED"
    CONFIRMATION_HASH_MISMATCH = "CONFIRMATION_HASH_MISMATCH"
    CONFIRMATION_ALREADY_USED = "CONFIRMATION_ALREADY_USED"
    CONFIRMATION_INVALID = "CONFIRMATION_INVALID"
    CONFIRMATION_STORAGE_BLOCKER = "CONFIRMATION_STORAGE_BLOCKER"
    EXECUTION_CAPABILITY_NOT_IMPLEMENTED = "EXECUTION_CAPABILITY_NOT_IMPLEMENTED"
    AST_COMPLEXITY_BLOCKER = "AST_COMPLEXITY_BLOCKER"
    NUMERIC_CANONICALIZATION_BLOCKER = "NUMERIC_CANONICALIZATION_BLOCKER"


@dataclass(frozen=True)
class StatusDefinition:
    code: BlockerCode
    status: PipelineStatus
    recoverable: bool
    retryable: bool
    terminal: bool
    user_action: str
    pipeline_stage: str
    formal_result_eligible: bool


def _blocked(code: BlockerCode, user_action: str, pipeline_stage: str) -> StatusDefinition:
    return StatusDefinition(
        code=code,
        status=PipelineStatus.BLOCKED,
        recoverable=True,
        retryable=False,
        terminal=True,
        user_action=user_action,
        pipeline_stage=pipeline_stage,
        formal_result_eligible=False,
    )


STATUS_DEFINITIONS = (
    _blocked(BlockerCode.CONFIG_VALIDATION_BLOCKER, "edit named config paths", "Stage 0"),
    _blocked(BlockerCode.SCHEMA_VERSION_BLOCKER, "select a supported schema version", "Stage 0"),
    _blocked(BlockerCode.SCHEMA_COMPATIBILITY_BLOCKER, "use a compatible schema", "Stage 0"),
    _blocked(BlockerCode.INITIAL_CAPITAL_POLICY_BLOCKER, "set initial capital to the policy amount", "Stage 0"),
    _blocked(BlockerCode.POSITION_SIZING_INPUT_BLOCKER, "provide valid position sizing", "Stage 0"),
    _blocked(BlockerCode.RELATIVE_STRENGTH_BENCHMARK_BLOCKER, "provide a registered benchmark", "Stage 0"),
    _blocked(BlockerCode.STRATEGY_CAPABILITY_BLOCKER, "select registered capability", "Stage 1"),
    _blocked(BlockerCode.DATA_CAPABILITY_BLOCKER, "provide validated dataset", "Stage 2/3"),
    _blocked(BlockerCode.DATA_VALIDATION_BLOCKER, "repair validated dataset", "Stage 2/3"),
    _blocked(BlockerCode.CORPORATE_ACTION_DATA_BLOCKER, "provide corporate-action-adjusted data", "Stage 2/3"),
    _blocked(BlockerCode.LIQUIDITY_CAPABILITY_BLOCKER, "provide liquidity-capable dataset", "Stage 2/3"),
    _blocked(BlockerCode.FUTU_OPEND_START_BLOCKER, "start Futu OpenD", "Stage 2/3"),
    _blocked(BlockerCode.FUTU_LOGIN_BLOCKER, "complete Futu login", "Stage 2/3"),
    _blocked(BlockerCode.FUTU_MARKET_PERMISSION_BLOCKER, "obtain Futu market permission", "Stage 2/3"),
    _blocked(BlockerCode.FUTU_QUOTA_BLOCKER, "restore Futu quota", "Stage 2/3"),
    _blocked(BlockerCode.PLUGIN_REQUIRED, "provide required plugin", "Stage 1"),
    _blocked(BlockerCode.PLUGIN_LOGIC_CHANGE_REQUIRED, "revise plugin logic", "Stage 1"),
    _blocked(BlockerCode.PLUGIN_PARAMETER_VALIDATION_BLOCKER, "correct plugin parameters", "Stage 1"),
    _blocked(BlockerCode.PLUGIN_VALIDATION_BLOCKER, "register/validate in later plan", "Stage 1"),
    _blocked(BlockerCode.ENGINE_CAPABILITY_BLOCKER, "select supported engine", "Stage 1"),
    _blocked(BlockerCode.FILTER_DATA_CAPABILITY_BLOCKER, "provide filter dataset", "Stage 2/3"),
    _blocked(BlockerCode.INTRADAY_TIME_SEMANTICS_BLOCKER, "select supported intraday semantics", "Stage 1"),
    _blocked(BlockerCode.BENCHMARK_FAIRNESS_BLOCKER, "provide fair benchmark data", "Stage 2/3"),
    _blocked(BlockerCode.COST_PROFILE_CAPABILITY_BLOCKER, "provide supported cost profile", "Stage 1"),
    _blocked(BlockerCode.CONFIRMATION_REQUIRED, "complete confirmation flow", "Gate"),
    _blocked(BlockerCode.CONFIRMATION_EXPIRED, "prepare a new confirmation request", "Gate"),
    _blocked(BlockerCode.CONFIRMATION_HASH_MISMATCH, "prepare a new request for the changed configuration", "Gate"),
    _blocked(BlockerCode.CONFIRMATION_ALREADY_USED, "prepare a new confirmation request", "Gate"),
    _blocked(BlockerCode.CONFIRMATION_INVALID, "repair request/grant binding and create a new request", "Gate"),
    _blocked(BlockerCode.CONFIRMATION_STORAGE_BLOCKER, "use a supported lock backend or repair storage", "Gate"),
    StatusDefinition(
        code=BlockerCode.EXECUTION_CAPABILITY_NOT_IMPLEMENTED,
        status=PipelineStatus.NOT_IMPLEMENTED,
        recoverable=True,
        retryable=False,
        terminal=True,
        user_action="wait for V2.3 engine milestone",
        pipeline_stage="Execute",
        formal_result_eligible=False,
    ),
    _blocked(BlockerCode.AST_COMPLEXITY_BLOCKER, "simplify strategy AST", "Stage 0"),
    _blocked(BlockerCode.NUMERIC_CANONICALIZATION_BLOCKER, "correct numeric values", "Stage 0"),
)

_STATUS_BY_CODE = {definition.code.value: definition for definition in STATUS_DEFINITIONS}


def status_definition(code: BlockerCode | str) -> StatusDefinition:
    """Return immutable V2 metadata for a blocker code."""
    value = code.value if isinstance(code, BlockerCode) else code
    return _STATUS_BY_CODE[value]


def status_snapshot_hash() -> str:
    """Return the canonical digest of the complete frozen status registry."""
    return canonical_hash(
        {
            "statuses": [
                {
                    "code": definition.code.value,
                    "status": definition.status.value,
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
