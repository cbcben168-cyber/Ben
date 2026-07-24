from tv_quant.pipeline_cli import exit_code_for_status


def test_success_statuses_return_zero():
    assert exit_code_for_status("PASS") == 0
    assert exit_code_for_status("CONDITIONAL_PASS") == 0


def test_blockers_and_failures_return_nonzero():
    assert exit_code_for_status("STRATEGY_CAPABILITY_BLOCKER") == 3
    assert exit_code_for_status("DATA_CAPABILITY_BLOCKER") == 4
    assert exit_code_for_status("FAIL") == 5
