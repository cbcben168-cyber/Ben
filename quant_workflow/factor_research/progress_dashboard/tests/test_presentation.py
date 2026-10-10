from quant_workflow.factor_research.progress_dashboard.presentation import (
    conclusion_zh,
    factor_name_zh,
    import_error_zh,
    status_zh,
)


def test_chinese_status_mapping_and_unknown_fallback():
    assert status_zh("INDETERMINATE") == "尚未确定"
    assert status_zh("OOS_SUPPORTED") == "OOS 支持"
    assert status_zh("FUTURE_STATUS") == "FUTURE_STATUS"
    assert factor_name_zh("SPY_F001_CLOSE_GT_EMA20") == "收盘价高于 EMA20"
    assert "待 C1" in factor_name_zh("SPY_F999_UNKNOWN")


def test_conclusion_depends_on_validation_evidence_not_mean_return():
    factor = {
        "edge_status": "INSUFFICIENT_EVIDENCE",
        "development_stage": "PLATFORM_VALIDATED",
        "latest_verdict": "FUNCTIONAL_VALIDATION_PASS",
        "valid_run_count": 1,
    }
    assert conclusion_zh(factor) == "证据不足"
    factor["latest_verdict"] = "TRAIN_DATA_VALIDATED"
    assert conclusion_zh(factor) == "值得继续验证"
    factor["edge_status"] = "OOS_SUPPORTED"
    assert conclusion_zh(factor) == "独立验证支持"


def test_import_error_mapping_keeps_raw_error():
    mapped = import_error_zh("IDENTITY_MISMATCH:factor_id")
    assert "factor_id" in mapped["message_zh"]
    assert mapped["raw_error"] == "IDENTITY_MISMATCH:factor_id"
    unknown = import_error_zh("NEW_ERROR")
    assert unknown["raw_error"] == "NEW_ERROR"
    assert "完整性" in unknown["message_zh"]
