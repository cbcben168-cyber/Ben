import inspect

from tv_quant.contracts.status_codes import (
    BlockerCode,
    PipelineStatus,
    STATUS_DEFINITIONS,
    status_definition,
    status_snapshot_hash,
)


EXPECTED_PIPELINE_STATUSES = {
    "SUCCESS",
    "CONDITIONAL_SUCCESS",
    "BLOCKED",
    "FAILED",
    "NOT_IMPLEMENTED",
}

EXPECTED_BLOCKER_CODES = {
    "CONFIG_VALIDATION_BLOCKER",
    "SCHEMA_VERSION_BLOCKER",
    "SCHEMA_COMPATIBILITY_BLOCKER",
    "INITIAL_CAPITAL_POLICY_BLOCKER",
    "POSITION_SIZING_INPUT_BLOCKER",
    "RELATIVE_STRENGTH_BENCHMARK_BLOCKER",
    "STRATEGY_CAPABILITY_BLOCKER",
    "DATA_CAPABILITY_BLOCKER",
    "DATA_VALIDATION_BLOCKER",
    "CORPORATE_ACTION_DATA_BLOCKER",
    "LIQUIDITY_CAPABILITY_BLOCKER",
    "FUTU_OPEND_START_BLOCKER",
    "FUTU_LOGIN_BLOCKER",
    "FUTU_MARKET_PERMISSION_BLOCKER",
    "FUTU_QUOTA_BLOCKER",
    "PLUGIN_REQUIRED",
    "PLUGIN_LOGIC_CHANGE_REQUIRED",
    "PLUGIN_PARAMETER_VALIDATION_BLOCKER",
    "PLUGIN_VALIDATION_BLOCKER",
    "ENGINE_CAPABILITY_BLOCKER",
    "FILTER_DATA_CAPABILITY_BLOCKER",
    "INTRADAY_TIME_SEMANTICS_BLOCKER",
    "BENCHMARK_FAIRNESS_BLOCKER",
    "COST_PROFILE_CAPABILITY_BLOCKER",
    "CONFIRMATION_REQUIRED",
    "CONFIRMATION_EXPIRED",
    "CONFIRMATION_HASH_MISMATCH",
    "CONFIRMATION_ALREADY_USED",
    "CONFIRMATION_INVALID",
    "CONFIRMATION_STORAGE_BLOCKER",
    "EXECUTION_CAPABILITY_NOT_IMPLEMENTED",
    "AST_COMPLEXITY_BLOCKER",
    "NUMERIC_CANONICALIZATION_BLOCKER",
}


def test_all_required_v2_blocker_codes_have_metadata():
    assert {status.value for status in PipelineStatus} == EXPECTED_PIPELINE_STATUSES
    assert {code.value for code in BlockerCode} == EXPECTED_BLOCKER_CODES
    assert {definition.code.value for definition in STATUS_DEFINITIONS} == EXPECTED_BLOCKER_CODES
    assert len(STATUS_DEFINITIONS) == len(EXPECTED_BLOCKER_CODES)
    assert len({definition.code.value for definition in STATUS_DEFINITIONS}) == len(
        STATUS_DEFINITIONS
    )


def test_recoverable_retryable_terminal_semantics_are_consistent():
    for definition in STATUS_DEFINITIONS:
        assert definition.code.value in EXPECTED_BLOCKER_CODES
        assert definition.status in PipelineStatus
        assert isinstance(definition.recoverable, bool)
        assert isinstance(definition.retryable, bool)
        assert isinstance(definition.terminal, bool)
        assert definition.user_action
        assert definition.pipeline_stage
        assert not definition.retryable or definition.recoverable
        assert definition.terminal
        assert definition.formal_result_eligible is False


def test_confirmation_expiry_and_reuse_require_new_request():
    for code in (
        BlockerCode.CONFIRMATION_EXPIRED,
        BlockerCode.CONFIRMATION_ALREADY_USED,
    ):
        definition = status_definition(code)

        assert definition.status is PipelineStatus.BLOCKED
        assert definition.recoverable is True
        assert definition.retryable is False
        assert definition.terminal is True
        assert definition.user_action == "prepare a new confirmation request"
        assert definition.pipeline_stage == "Gate"
        assert definition.formal_result_eligible is False


def test_status_snapshot_hash_is_stable():
    assert status_snapshot_hash() == (
        "3932992ce89d1eace86e13b8331aecc873dfa14ebbbb0e3009c4fc11934d0d9f"
    )


def test_status_snapshot_hash_uses_existing_canonical_hash_owner():
    source = inspect.getsource(inspect.getmodule(status_snapshot_hash))

    assert "canonical_hash(" in source
    assert "hashlib" not in source


def test_package_imports_are_available():
    from tv_quant import adapters, contracts

    assert adapters.__name__ == "tv_quant.adapters"
    assert contracts.__name__ == "tv_quant.contracts"
    assert status_definition(BlockerCode.CONFIG_VALIDATION_BLOCKER).status is (
        PipelineStatus.BLOCKED
    )
