from __future__ import annotations

from typing import Any


HORIZONS = (15, 30, 60)

FACTOR_NAMES_ZH = {
    "SPY_F001_CLOSE_GT_EMA20": "收盘价高于 EMA20",
    "SPY_F002_EMA20_RISING_3": "EMA20 三根周期上升",
    "SPY_F003_CLOSE_CROSS_ABOVE_EMA20": "收盘价上穿 EMA20",
    "SPY_F004_CLOSE_BREAKS_PRIOR_5_HIGH": "突破前五根高点",
    "SPY_F005_THREE_CLOSE_MOMENTUM": "连续三根收盘走高",
    "SPY_F006_STRONG_BULL_BODY": "强阳线实体",
}

STATUS_ZH = {
    "SPECIFIED": "已定义",
    "PLATFORM_VALIDATED": "功能验证完成",
    "HISTORICAL_RUN": "长期训练回测完成",
    "CODE_READY": "代码已就绪",
    "VALIDATION": "Validation 完成",
    "OOS": "OOS 完成",
    "REJECTED": "已否决",
    "PASS": "通过",
    "FAIL": "失败",
    "INDETERMINATE": "尚未确定",
    "NOT_TESTED": "未测试",
    "VALIDATED": "完整有效",
    "INCOMPLETE": "数据不完整",
    "INVALID": "无效",
    "PARSE_FAILED": "解析失败",
    "FUNCTIONAL_VALIDATION_PASS": "功能验证通过",
    "TRAIN_DATA_VALIDATED": "TRAIN 数据通过校验",
    "VALIDATION_DATA_VALIDATED": "Validation 数据通过校验",
    "OOS_DATA_VALIDATED": "OOS 数据通过校验",
    "INSUFFICIENT_EVIDENCE": "证据不足",
    "VALIDATION_FAILED": "验证失败",
    "OOS_SUPPORTED": "OOS 支持",
    "INDEPENDENT_VALIDATION_SUPPORTED": "独立验证支持",
    "NOT_ASSESSED": "尚未评估",
    "PENDING": "等待验证",
    "OPEN": "待处理",
    "RESOLVED": "已解决",
    "INFO": "提示",
    "WARNING": "警告",
    "ERROR": "错误",
    "DUPLICATE": "重复文件",
    "IGNORED": "已忽略",
}

COMPARISON_REASON_ZH = {
    "PLAN_CATALOG_INCOMPLETE": "C1 计划目录尚未完整接入",
    "FEWER_THAN_TWO_FACTORS": "少于两个因子，无法形成排行榜",
    "MISSING_ELIGIBLE_RUN": "部分因子在所选窗口没有完整有效数据",
    "DATA_GATE_NOT_PASS": "部分因子的数据资格尚未通过",
    "COMPARISON_SCOPE_MISMATCH": "标的、周期、日期范围、研究分区或收益口径不一致",
}

IMPORT_ERROR_ZH = {
    "INVALID": (
        "CSV 未通过已登记的因子版本或数据合同校验。",
        "请检查高级资料中的异常记录，并核对因子目录、策略哈希和参数版本。",
    ),
    "INCOMPLETE": (
        "CSV 已识别，但跑次或标签不完整，不能作为正式比较证据。",
        "请检查缺失标签、DAY_STATUS、ERROR 事件和唯一 RUN_END 后重新导出。",
    ),
    "PARSE_FAILED": (
        "CSV 无法按当前日志合同完整解析。",
        "请检查文件编码、CSV 引号、日志标记和批次格式。",
    ),
    "UNSUPPORTED_MARKER_VERSION": (
        "CSV 使用了看板尚不支持的日志版本。",
        "请使用已登记的 FUTU_FACTOR_V1 或 FUTU_FACTOR_BATCH_V1 合同重新导出。",
    ),
    "FIXTURE_NOT_ALLOWED_IN_PRODUCTION_DB": (
        "测试夹具不能导入正式研究数据库。",
        "请导入真实回测导出的 CSV；测试数据只能用于隔离测试库。",
    ),
    "INVALID_STRATEGY_HASH": (
        "策略哈希格式无效。",
        "请重新导出包含完整 64 位 SHA256 的日志，不要手工改写 CSV。",
    ),
    "PAYLOAD_NOT_OBJECT": (
        "日志事件不是有效的 JSON 对象。",
        "请检查 CSV 引号、编码和日志导出是否完整。",
    ),
}


def status_zh(value: Any) -> str:
    raw = str(value or "PENDING")
    return STATUS_ZH.get(raw, raw)


def factor_name_zh(factor_id: str) -> str:
    return FACTOR_NAMES_ZH.get(factor_id, "中文名称待 C1 因子目录确认")


def conclusion_zh(factor: dict[str, Any]) -> str:
    edge_status = str(factor.get("edge_status") or "NOT_TESTED")
    stage = str(factor.get("development_stage") or "SPECIFIED")
    verdict = str(factor.get("latest_verdict") or "NOT_ASSESSED")
    valid_runs = int(factor.get("valid_run_count") or 0)
    if edge_status in {"OOS_SUPPORTED", "INDEPENDENT_VALIDATION_SUPPORTED"}:
        return "独立验证支持"
    if edge_status in {"VALIDATION_FAILED", "REJECTED"} or stage == "REJECTED":
        return "验证失败"
    if verdict in {"TRAIN_DATA_VALIDATED", "VALIDATION_DATA_VALIDATED"}:
        return "值得继续验证"
    if valid_runs or verdict == "FUNCTIONAL_VALIDATION_PASS":
        return "证据不足"
    return "未测试"


def import_error_zh(error: Any) -> dict[str, str]:
    raw = str(error or "UNKNOWN_IMPORT_ERROR")
    if raw.startswith("RUN_START_COUNT:"):
        message, action = (
            "单因子合同必须且只能包含一个 RUN_START；当前文件像是拼接日志。",
            "六因子回测请使用 FUTU_FACTOR_BATCH_V1，不要把多个独立跑次直接拼在一起。",
        )
    elif raw.startswith("BATCH_RUN_START_COUNT:"):
        message, action = (
            "六因子批次必须且只能包含一个 RUN_START。",
            "请重新导出完整的单次 FUTU_BATCH_FACTORS_V1 回测日志。",
        )
    elif raw in {
        "BATCH_FACTOR_CATALOG_MISMATCH",
        "BATCH_DEFINITION_HASH_MISMATCH",
        "BATCH_FACTOR_SET_MISMATCH",
    }:
        message, action = (
            "CSV 中的六因子目录或定义哈希与冻结的 C1 合同不一致，已整批拒绝。",
            "请使用仓库中的 SPY_SIX_FACTOR_BATCH_V1.py 原样重跑，不要手工改 CSV。",
        )
    elif raw == "PARTIAL_BATCH_STATE":
        message, action = (
            "数据库检测到同一批次只有部分逻辑跑次，已阻止不完整排行。",
            "请保留数据库和源 CSV，交由 Codex 审核事务状态。",
        )
    elif raw.startswith(("TRAIN_CONTRACT_MISMATCH:", "BATCH_PARTITION_VERSION_MISMATCH")):
        message, action = (
            "TRAIN 日期、版本或预注册参数与冻结合同不一致，已整批拒绝。",
            "请使用 SPY_SIX_FACTOR_BATCH_TRAIN_V1.py 原样运行，并核对富途参数表。",
        )
    elif raw.startswith(
        (
            "TRAIN_SESSION_",
            "TRAIN_EVENT_",
            "TRAIN_LABEL_",
            "TRAIN_INTRADAY_",
            "TRAIN_WARMUP_",
            "INVALID_TRAIN_WARMUP_",
        )
    ):
        message, action = (
            "TRAIN 日志未达到187个交易日、12,083个事件、36,249个标签或预热审计要求。",
            "不要拼接或修改CSV；保留原文件并检查回测起点、提前收市日和日志是否被截断。",
        )
    elif raw.startswith("IDENTITY_MISMATCH:"):
        field = raw.partition(":")[2]
        message, action = (
            f"同一跑次中的 {field} 不一致，文件可能混入多个因子或版本。",
            "按独立跑次重新导出，或使用经批准的 C1 批次格式。",
        )
    elif raw.startswith("VERSION_MISMATCH"):
        message, action = (
            "因子版本、策略哈希或参数版本尚未登记。",
            "先核对 C1 因子目录和冻结版本，再重新导入。",
        )
    else:
        message, action = IMPORT_ERROR_ZH.get(
            raw,
            (
                "CSV 未通过完整性或数据合同校验。",
                "请在高级资料查看原始错误码，并核对日志版本、编码和导出完整性。",
            ),
        )
    return {"message_zh": message, "next_action_zh": action, "raw_error": raw}


def decorate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    for factor in snapshot.get("factors", []):
        factor["display_name_zh"] = factor_name_zh(factor["factor_id"])
        factor["development_stage_zh"] = status_zh(factor.get("development_stage"))
        factor["data_gate_zh"] = status_zh(factor.get("data_gate"))
        factor["edge_status_zh"] = status_zh(factor.get("edge_status"))
        factor["latest_verdict_zh"] = status_zh(factor.get("latest_verdict"))
        factor["conclusion_zh"] = conclusion_zh(factor)
    factors = {item["factor_id"]: item for item in snapshot.get("factors", [])}
    for row in snapshot.get("comparison", {}).get("rows", []):
        factor = factors.get(row["factor_id"], {})
        row["display_name_zh"] = factor.get("display_name_zh", factor_name_zh(row["factor_id"]))
        row["conclusion_zh"] = factor.get("conclusion_zh", "未测试")
    comparison = snapshot.get("comparison", {})
    comparison["reason_messages_zh"] = [
        COMPARISON_REASON_ZH.get(code, code) for code in comparison.get("reason_codes", [])
    ]
    for run in snapshot.get("runs", []):
        run["run_status_zh"] = status_zh(run.get("run_status"))
        run["research_verdict_zh"] = status_zh(run.get("research_verdict"))
    for issue in snapshot.get("issues", []):
        issue["severity_zh"] = status_zh(issue.get("severity"))
        issue["status_zh"] = status_zh(issue.get("status"))
    return snapshot
