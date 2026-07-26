import inspect

from tv_quant.contracts.status_codes import (
    BlockerCode,
    PipelineStatus,
    STATUS_DEFINITIONS,
    status_definition,
    status_snapshot_hash,
)


def test_all_required_v2_blocker_codes_have_metadata():
    assert set(BlockerCode) == {
        BlockerCode.STRATEGY_CAPABILITY_BLOCKER,
        BlockerCode.DATA_CAPABILITY_BLOCKER,
    }
    assert {definition.status for definition in STATUS_DEFINITIONS} == {
        status.value for status in PipelineStatus
    }
    assert len({definition.status for definition in STATUS_DEFINITIONS}) == len(
        STATUS_DEFINITIONS
    )


def test_recoverable_retryable_terminal_semantics_are_consistent():
    for definition in STATUS_DEFINITIONS:
        assert definition.status
        assert definition.user_action
        assert definition.pipeline_stage
        assert not definition.retryable or definition.recoverable
        assert definition.terminal
        assert not definition.formal_result_eligible or definition.status == "PASS"


def test_status_snapshot_hash_is_stable():
    assert status_snapshot_hash() == status_snapshot_hash()
    assert len(status_snapshot_hash()) == 64


def test_status_snapshot_hash_uses_existing_canonical_hash_owner():
    source = inspect.getsource(inspect.getmodule(status_snapshot_hash))

    assert "canonical_hash(" in source
    assert "hashlib" not in source


def test_package_imports_are_available():
    from tv_quant import adapters, contracts

    assert adapters.__name__ == "tv_quant.adapters"
    assert contracts.__name__ == "tv_quant.contracts"
    assert status_definition(PipelineStatus.PASS).formal_result_eligible is True
