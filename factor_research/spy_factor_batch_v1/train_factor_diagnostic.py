from __future__ import annotations

import argparse
import csv
import hashlib
from io import StringIO
import json
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from factor_research.spy_factor_batch_v1.train_ema_supplement_audit import (
    EXPECTED_FACTOR_EVENTS,
    EXPECTED_LABELS,
    EXPECTED_SHA256,
    extract_events,
    sha256_bytes,
    sha256_file,
)
from quant_workflow.factor_research.progress_dashboard.db import BATCH_FACTOR_CATALOG
from quant_workflow.factor_research.progress_dashboard.ingest import (
    BATCH_FACTORS,
    TRAIN_EARLY_CLOSE_DAYS,
    TRAIN_END,
    TRAIN_EXPECTED_SESSIONS,
    TRAIN_START,
    expected_train_sessions,
)
from quant_workflow.factor_research.progress_dashboard.stats import (
    compute_distribution_statistics,
    compute_signal_redundancy,
    compute_statistics,
    compute_train_analysis,
)


CONTRACT = "C1_TRAIN_FACTOR_DIAGNOSTIC_V1"
EXPECTED_AUDIT_MANIFEST_SHA256 = (
    "f1f750867dd4a32eaf74d4d776dcf47002f0aa7f5b123db4177e57c4a1a266da"
)
HORIZONS = ((15, "r3"), (30, "r6"), (60, "r12"))
FACTOR_NAMES = {
    "SPY_F001_CLOSE_GT_EMA20": "收盘价高于EMA20",
    "SPY_F002_EMA20_RISING_3": "EMA20较三根K线前上升",
    "SPY_F003_CLOSE_CROSS_ABOVE_EMA20": "收盘价向上穿越EMA20",
    "SPY_F004_CLOSE_BREAKS_PRIOR_5_HIGH": "收盘价突破前五根最高价",
    "SPY_F005_THREE_CLOSE_MOMENTUM": "连续三根收盘价走高",
    "SPY_F006_STRONG_BULL_BODY": "强阳线实体超过振幅60%",
}
FACTOR_DEFINITIONS = {factor_id: definition for factor_id, definition, _ in BATCH_FACTOR_CATALOG}


def _fail(code: str) -> None:
    raise ValueError(code)


def verify_inputs(
    runlog: Path,
    audit_dir: Path,
    *,
    expected_raw_sha256: str = EXPECTED_SHA256,
    expected_manifest_sha256: str = EXPECTED_AUDIT_MANIFEST_SHA256,
) -> tuple[bytes, list[dict[str, Any]], dict[str, Any]]:
    raw = runlog.read_bytes()
    if sha256_bytes(raw) != expected_raw_sha256:
        _fail("RUNLOG_SHA256_MISMATCH")
    manifest_path = audit_dir / "manifest.json"
    if sha256_file(manifest_path) != expected_manifest_sha256:
        _fail("AUDIT_MANIFEST_SHA256_MISMATCH")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("raw_run_sha256") != expected_raw_sha256:
        _fail("AUDIT_RAW_SHA256_MISMATCH")
    if manifest.get("raw_run_status_preserved") != "INCOMPLETE":
        _fail("AUDIT_RAW_STATUS_NOT_INCOMPLETE")
    if manifest.get("dashboard_validation_upgrade") != "PROHIBITED":
        _fail("AUDIT_DASHBOARD_BOUNDARY_MISMATCH")
    if manifest.get("edge_claim") != "PROHIBITED":
        _fail("AUDIT_EDGE_BOUNDARY_MISMATCH")
    for name, metadata in manifest.get("artifacts", {}).items():
        path = audit_dir / name
        if not path.is_file() or sha256_file(path) != metadata.get("sha256"):
            _fail("AUDIT_ARTIFACT_SHA256_MISMATCH:" + name)
        if path.stat().st_size != metadata.get("bytes"):
            _fail("AUDIT_ARTIFACT_SIZE_MISMATCH:" + name)
    summary = json.loads((audit_dir / "audit_summary.json").read_text(encoding="utf-8"))
    if summary.get("status") != "SUPPORTED":
        _fail("EMA_SUPPLEMENT_NOT_SUPPORTED")
    if summary.get("raw_run_status_preserved") != "INCOMPLETE":
        _fail("EMA_SUPPLEMENT_RAW_STATUS_MISMATCH")
    if summary.get("raw_run_sha256") != expected_raw_sha256:
        _fail("EMA_SUPPLEMENT_RAW_SHA256_MISMATCH")
    events = extract_events(raw)
    return raw, events, {"manifest": manifest, "summary": summary}


def validate_real_train_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    factor_events = [item for item in events if item.get("event_type") == "FACTOR_EVENT"]
    run_ends = [item for item in events if item.get("event_type") == "RUN_END"]
    warmups = [item for item in events if item.get("event_type") == "WARMUP_AUDIT"]
    if len(run_ends) != 1 or run_ends[0].get("status") != "INCOMPLETE":
        _fail("RAW_RUN_END_NOT_INCOMPLETE")
    if len(warmups) != 1 or warmups[0].get("status") != "INCOMPLETE":
        _fail("RAW_WARMUP_AUDIT_NOT_INCOMPLETE")
    if len(factor_events) != EXPECTED_FACTOR_EVENTS:
        _fail("FACTOR_EVENT_COUNT_MISMATCH")
    signal_ids = [str(item.get("signal_id")) for item in factor_events]
    if len(set(signal_ids)) != len(signal_ids):
        _fail("DUPLICATE_SIGNAL_ID")
    dates = {str(item.get("session_date_et")) for item in factor_events}
    if dates != expected_train_sessions() or len(dates) != TRAIN_EXPECTED_SESSIONS:
        _fail("TRAIN_SESSION_SET_MISMATCH")
    counts: dict[str, int] = {}
    for item in factor_events:
        day = str(item["session_date_et"])
        counts[day] = counts.get(day, 0) + 1
    for day, count in counts.items():
        expected = 29 if day in TRAIN_EARLY_CLOSE_DAYS else 65
        if count != expected:
            _fail("SESSION_EVENT_COUNT_MISMATCH:" + day)
    if min(dates) != TRAIN_START or max(dates) != TRAIN_END:
        _fail("TRAIN_DATE_RANGE_MISMATCH")
    if len(factor_events) * len(HORIZONS) != EXPECTED_LABELS:
        _fail("LABEL_COUNT_MISMATCH")
    return sorted(factor_events, key=lambda item: str(item["signal_time_et"]))


def build_factor_inputs(
    factor_events: list[dict[str, Any]],
) -> tuple[dict[str, tuple[list[dict], list[dict]]], dict[str, dict[str, str]]]:
    result: dict[str, tuple[list[dict], list[dict]]] = {}
    states_by_factor: dict[str, dict[str, str]] = {}
    for factor_id, prefix, _ in BATCH_FACTORS:
        signals: list[dict] = []
        labels: list[dict] = []
        states: dict[str, str] = {}
        for event in factor_events:
            signal_id = str(event["signal_id"])
            state = str(event[prefix + "_state"])
            if state not in {"PASS", "FAIL"}:
                _fail("INVALID_FACTOR_STATE:" + factor_id)
            if signal_id in states:
                _fail("DUPLICATE_FACTOR_SIGNAL_ID:" + signal_id)
            states[signal_id] = state
            signals.append(
                {
                    "signal_id": signal_id,
                    "signal_time_et": str(event["signal_time_et"]),
                    "factor_value": state,
                }
            )
            for horizon, return_key in HORIZONS:
                labels.append(
                    {
                        "signal_id": signal_id,
                        "horizon_minutes": horizon,
                        "forward_return": float(event[return_key]),
                    }
                )
        result[factor_id] = (signals, labels)
        states_by_factor[factor_id] = states
    return result, states_by_factor


def _safe_mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _combo_status(row: dict[str, Any]) -> str:
    if row["robust_train_support"] and row["familywise_support"]:
        return "值得继续验证（18项同时区间仍支持）"
    if row["robust_train_support"]:
        return "值得继续验证（未通过18项同时区间）"
    if (
        row["cluster_ci_high_bps"] is not None
        and row["cluster_ci_high_bps"] < 0
        and row["time_matched_diff_bps"] is not None
        and row["time_matched_diff_bps"] < 0
    ):
        return "TRAIN方向不利"
    return "证据不足"


def analyze_factor_events(
    factor_events: list[dict[str, Any]],
    *,
    seed_key: str,
    bootstrap_replicates: int = 5000,
) -> dict[str, Any]:
    factor_inputs, states_by_factor = build_factor_inputs(factor_events)
    summary_rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    monthly_rows: list[dict[str, Any]] = []
    phase_rows: list[dict[str, Any]] = []
    time_rows: list[dict[str, Any]] = []
    factor_decisions: list[dict[str, Any]] = []

    for factor_id, _, _ in BATCH_FACTORS:
        signals, labels = factor_inputs[factor_id]
        descriptive = {
            (item["horizon_minutes"], item["cohort"]): item
            for item in compute_statistics(signals, labels)
        }
        distributions = {
            (item["horizon_minutes"], item["cohort"]): item
            for item in compute_distribution_statistics(signals, labels)
        }
        analyses = compute_train_analysis(
            signals,
            labels,
            seed_key=seed_key + "|" + factor_id,
            bootstrap_replicates=bootstrap_replicates,
            multiple_testing_family_size=18,
        )
        robust_count = 0
        familywise_count = 0
        adverse_count = 0
        for analysis in analyses:
            horizon = analysis["horizon_minutes"]
            baseline = descriptive[(horizon, "ALL")]
            passed = descriptive[(horizon, "PASS")]
            failed = descriptive[(horizon, "FAIL")]
            pass_distribution = distributions[(horizon, "PASS")]
            fail_distribution = distributions[(horizon, "FAIL")]
            raw_diff_bps = (
                (passed["mean_return"] - failed["mean_return"]) * 10000
                if passed["mean_return"] is not None and failed["mean_return"] is not None
                else None
            )
            phase_diffs = [
                item["pass_fail_diff_bps"]
                for item in analysis["non_overlap_phases"]
                if item["pass_fail_diff_bps"] is not None
            ]
            bootstrap = analysis["cluster_bootstrap"]
            matched = analysis["same_day_time_bucket"]
            stability = analysis["stability"]
            robust = bool(
                bootstrap["ci_low_bps"] is not None
                and bootstrap["ci_low_bps"] > 0
                and matched["fixed_effect_diff_bps"] is not None
                and matched["fixed_effect_diff_bps"] > 0
                and stability["positive_months"] > stability["negative_months"]
                and sum(value > 0 for value in phase_diffs) > sum(value < 0 for value in phase_diffs)
            )
            familywise = bool(
                robust
                and bootstrap["bonferroni_ci_low_bps"] is not None
                and bootstrap["bonferroni_ci_low_bps"] > 0
            )
            row = {
                "factor_id": factor_id,
                "factor_name_cn": FACTOR_NAMES[factor_id],
                "horizon_minutes": horizon,
                "baseline_n": baseline["n"],
                "baseline_mean_return": baseline["mean_return"],
                "baseline_median_return": baseline["median_return"],
                "baseline_positive_rate": baseline["positive_rate"],
                "pass_n": passed["n"],
                "pass_mean_return": passed["mean_return"],
                "pass_median_return": passed["median_return"],
                "pass_positive_rate": passed["positive_rate"],
                "pass_stddev": pass_distribution["stddev"],
                "pass_p05": pass_distribution["p05"],
                "pass_p25": pass_distribution["p25"],
                "pass_p75": pass_distribution["p75"],
                "pass_p95": pass_distribution["p95"],
                "fail_n": failed["n"],
                "fail_mean_return": failed["mean_return"],
                "fail_median_return": failed["median_return"],
                "fail_positive_rate": failed["positive_rate"],
                "fail_stddev": fail_distribution["stddev"],
                "fail_p05": fail_distribution["p05"],
                "fail_p25": fail_distribution["p25"],
                "fail_p75": fail_distribution["p75"],
                "fail_p95": fail_distribution["p95"],
                "raw_pass_fail_diff_bps": raw_diff_bps,
                "paired_days": stability["paired_days"],
                "better_days": stability["better_days"],
                "worse_days": stability["worse_days"],
                "mean_daily_diff_bps": _safe_mean(
                    [
                        item["pass_fail_diff_bps"]
                        for item in analysis["daily"]
                        if item["pass_fail_diff_bps"] is not None
                    ]
                ),
                "positive_months": stability["positive_months"],
                "negative_months": stability["negative_months"],
                "time_matched_strata": matched["strata_matched"],
                "time_matched_diff_bps": matched["fixed_effect_diff_bps"],
                "positive_phases": sum(value > 0 for value in phase_diffs),
                "negative_phases": sum(value < 0 for value in phase_diffs),
                "phase_count": len(phase_diffs),
                "cluster_ci_low_bps": bootstrap["ci_low_bps"],
                "cluster_ci_high_bps": bootstrap["ci_high_bps"],
                "bonferroni_ci_low_bps": bootstrap["bonferroni_ci_low_bps"],
                "bonferroni_ci_high_bps": bootstrap["bonferroni_ci_high_bps"],
                "robust_train_support": robust,
                "familywise_support": familywise,
            }
            row["conclusion_cn"] = _combo_status(row)
            summary_rows.append(row)
            robust_count += robust
            familywise_count += familywise
            adverse_count += row["conclusion_cn"] == "TRAIN方向不利"

            for item in analysis["daily"]:
                daily_rows.append(_flatten_period(factor_id, horizon, "day", item))
            for item in analysis["monthly"]:
                monthly_rows.append(_flatten_period(factor_id, horizon, "month", item))
            for item in analysis["non_overlap_phases"]:
                phase_rows.append(_flatten_phase(factor_id, horizon, item))
            for item in analysis["time_bucket_matched"]:
                time_rows.append(_flatten_time_bucket(factor_id, horizon, item))

        if robust_count >= 2 and adverse_count == 0:
            conclusion = "值得继续验证"
        elif adverse_count == 3:
            conclusion = "TRAIN整体方向不利"
        else:
            conclusion = "暂不晋级：证据不足"
        factor_decisions.append(
            {
                "factor_id": factor_id,
                "factor_name_cn": FACTOR_NAMES[factor_id],
                "definition": FACTOR_DEFINITIONS[factor_id],
                "robust_horizons": robust_count,
                "familywise_horizons": familywise_count,
                "adverse_horizons": adverse_count,
                "conclusion_cn": conclusion,
            }
        )

    redundancy = compute_signal_redundancy(states_by_factor)
    return {
        "contract": CONTRACT,
        "bootstrap_replicates": bootstrap_replicates,
        "multiple_testing_family_size": 18,
        "summary_rows": summary_rows,
        "factor_decisions": factor_decisions,
        "daily_rows": daily_rows,
        "monthly_rows": monthly_rows,
        "phase_rows": phase_rows,
        "time_rows": time_rows,
        "redundancy_rows": redundancy,
    }


def _flatten_period(factor_id: str, horizon: int, key: str, item: dict[str, Any]) -> dict:
    return {
        "factor_id": factor_id,
        "horizon_minutes": horizon,
        key: item[key],
        "baseline_n": item["baseline"]["n"],
        "baseline_mean_return": item["baseline"]["mean"],
        "pass_n": item["pass"]["n"],
        "pass_mean_return": item["pass"]["mean"],
        "fail_n": item["fail"]["n"],
        "fail_mean_return": item["fail"]["mean"],
        "pass_fail_diff_bps": item["pass_fail_diff_bps"],
    }


def _flatten_phase(factor_id: str, horizon: int, item: dict[str, Any]) -> dict:
    row = _flatten_period(factor_id, horizon, "phase", item)
    row["horizon_bars"] = item["horizon_bars"]
    return row


def _flatten_time_bucket(factor_id: str, horizon: int, item: dict[str, Any]) -> dict:
    row = _flatten_period(factor_id, horizon, "day", item)
    row["bucket"] = item["bucket"]
    row["bucket_label"] = item["bucket_label"]
    row["fixed_effect_weight"] = item["fixed_effect_weight"]
    return row


def _bps(value: float | None) -> str:
    return "—" if value is None else f"{value:+.3f}"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.3f}%"


def render_report(result: dict[str, Any], raw_sha256: str, audit_manifest_sha256: str) -> str:
    decisions = result["factor_decisions"]
    candidates = [item for item in decisions if item["conclusion_cn"] == "值得继续验证"]
    highly_redundant = [
        item
        for item in result["redundancy_rows"]
        if (item["phi"] is not None and abs(item["phi"]) >= 0.80)
        or (item["agreement_rate"] is not None and item["agreement_rate"] >= 0.90)
    ]
    lines = [
        "# C1 TRAIN 六因子综合诊断",
        "",
        "> **补充审计支持、原始运行未正式验收。** 本报告不改变 Dashboard Gate，不是 Validation/OOS，也不是交易策略收益报告。",
        "",
        "## 证据边界",
        "",
        f"- 原始CSV SHA256：`{raw_sha256}`",
        f"- EMA审计manifest SHA256：`{audit_manifest_sha256}`",
        "- 原始 `RUN_END=INCOMPLETE`：保持不变",
        "- EMA补充审计：`SUPPORTED`，仅供独立研究诊断",
        "- Dashboard Gate：不升级；正式排名：不启用",
        "- Validation/OOS：未运行；Edge：不得认定",
        "- 收益口径：信号收盘到未来收盘的毛收益；没有入场规则、手续费、滑点或成交约束",
        "",
        "## 10秒结论",
        "",
    ]
    if candidates:
        labels = "、".join(item["factor_id"].split("_")[1] for item in candidates)
        lines.append(f"TRAIN稳健性规则下，{labels}具备继续独立验证的理由；它们仍不是可交易Edge。")
    else:
        lines.append("六个因子均未同时满足预先声明的TRAIN稳健性条件，当前全部暂不晋级，也没有足够证据转成可执行策略候选。")
    lines.extend(
        [
            "",
            "## 因子级决策",
            "",
            "| 因子 | 通俗名称 | 稳健窗口/3 | 18项同时区间支持/3 | 当前决定 |",
            "|---|---|---:|---:|---|",
        ]
    )
    for item in decisions:
        lines.append(
            f"| {item['factor_id'].split('_')[1]} | {item['factor_name_cn']} | "
            f"{item['robust_horizons']} | {item['familywise_horizons']} | {item['conclusion_cn']} |"
        )
    lines.extend(
        [
            "",
            "判定规则在查看结果前固定：交易日聚类95%区间下限大于0、同日固定30分钟时段匹配差异为正、正向月份多于负向月份、全部非重叠相位中正向相位占多数。至少两个未来窗口满足且没有方向不利窗口，才列为“值得继续验证”。Bonferroni同时区间单独展示，不用最大均值挑赢家。",
            "",
            "## 18个因子×窗口对比",
            "",
            "所有收益均以bp表示（1bp=0.01%）。`时段匹配`为同一交易日、同一固定30分钟区间内PASS减FAIL，并按每层PASS/FAIL有效样本量加权（等价于日×时段固定效应比较）。",
            "",
            "| 因子 | 分钟 | PASS n | FAIL n | PASS均值 | FAIL均值 | 差异 | 市场基准 | 同日差异 | 时段匹配 | 日聚类95%CI | 18项同时CI | 日+/- | 月+/- | 相位+/- | 结论 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|---|---|",
        ]
    )
    for row in result["summary_rows"]:
        lines.append(
            f"| {row['factor_id'].split('_')[1]} | {row['horizon_minutes']} | {row['pass_n']} | {row['fail_n']} | "
            f"{_bps(row['pass_mean_return'] * 10000)} | {_bps(row['fail_mean_return'] * 10000)} | "
            f"{_bps(row['raw_pass_fail_diff_bps'])} | {_bps(row['baseline_mean_return'] * 10000)} | "
            f"{_bps(row['mean_daily_diff_bps'])} | {_bps(row['time_matched_diff_bps'])} | "
            f"[{_bps(row['cluster_ci_low_bps'])}, {_bps(row['cluster_ci_high_bps'])}] | "
            f"[{_bps(row['bonferroni_ci_low_bps'])}, {_bps(row['bonferroni_ci_high_bps'])}] | "
            f"{row['better_days']}/{row['worse_days']} | {row['positive_months']}/{row['negative_months']} | "
            f"{row['positive_phases']}/{row['negative_phases']} | {row['conclusion_cn']} |"
        )
    lines.extend(
        [
            "",
            "## 中位数、上涨概率与分布",
            "",
            "| 因子 | 分钟 | PASS中位数 | FAIL中位数 | PASS上涨率 | FAIL上涨率 | PASS 5%-95% | FAIL 5%-95% |",
            "|---|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in result["summary_rows"]:
        lines.append(
            f"| {row['factor_id'].split('_')[1]} | {row['horizon_minutes']} | "
            f"{_bps(row['pass_median_return'] * 10000)} | {_bps(row['fail_median_return'] * 10000)} | "
            f"{_pct(row['pass_positive_rate'])} | {_pct(row['fail_positive_rate'])} | "
            f"[{_bps(row['pass_p05'] * 10000)}, {_bps(row['pass_p95'] * 10000)}] | "
            f"[{_bps(row['fail_p05'] * 10000)}, {_bps(row['fail_p95'] * 10000)}] |"
        )
    lines.extend(
        [
            "",
            "完整标准差及25/75分位数见 `factor_window_summary.csv`；逐日、逐月、全部相位和全部时段层分别保存在对应CSV，未挑选有利相位。",
            "",
            "## 市场趋势与日内时段影响",
            "",
        ]
    )
    weakened = [
        row for row in result["summary_rows"]
        if row["raw_pass_fail_diff_bps"] is not None
        and row["time_matched_diff_bps"] is not None
        and row["raw_pass_fail_diff_bps"] * row["time_matched_diff_bps"] <= 0
    ]
    if weakened:
        labels = "、".join(
            f"{row['factor_id'].split('_')[1]}-{row['horizon_minutes']}m" for row in weakened
        )
        lines.append(f"以下组合在固定日内时段匹配后方向翻转或归零，原始差异可能受开盘/收盘时段结构影响：{labels}。")
    else:
        lines.append("18个组合的原始PASS/FAIL差异与固定时段匹配差异方向一致；这减少了日内时段解释，但不能排除市场趋势或其他共同状态。")
    lines.append("同日PASS/FAIL差异、逐月结果和无条件市场基准均已单独输出；日内相关事件仍重叠，因此没有把12,083条事件当成独立样本。")
    lines.extend(["", "## 信号重复度", ""])
    if highly_redundant:
        for item in highly_redundant:
            lines.append(
                f"- {item['factor_a'].split('_')[1]} 与 {item['factor_b'].split('_')[1]}："
                f"phi={item['phi']:.3f}，一致率={item['agreement_rate']:.1%}，PASS Jaccard={item['pass_jaccard']:.3f}。"
            )
    else:
        lines.append("没有因子对达到预声明的高度重复阈值（|phi|≥0.80或一致率≥90%）。完整15对结果见 `signal_redundancy.csv`。")
    lines.extend(
        [
            "",
            "## 因子定义与限制",
            "",
        ]
    )
    for item in decisions:
        note = "；开盘附近的前五根K线按冻结定义可引用前一交易日" if item["factor_id"].startswith("SPY_F004") else ""
        lines.append(f"- {item['factor_id'].split('_')[1]}：{item['factor_name_cn']}，`{item['definition']}`{note}。")
    lines.extend(
        [
            "",
            "本研究只评估条件未来收益的预测差异。它没有定义下一根K线成交、持仓冲突、仓位、成本、滑点和最大回撤，因此即使某因子值得继续验证，也不能直接转成可执行策略或净收益结论。",
            "",
            "## 下一项最值得执行的研究任务",
            "",
        ]
    )
    if candidates:
        labels = "、".join(item["factor_id"].split("_")[1] for item in candidates)
        lines.append(
            f"冻结{labels}及本报告判定规则，准备一份完全隔离的Validation方案，同时预注册next-bar成交、手续费、滑点、信号冲突和持仓规则；本阶段不运行Validation。"
        )
    else:
        lines.append(
            "预注册第二批与现有趋势/蜡烛形态更正交的候选：波动率收缩后扩张、隔夜缺口回归、相对成交活跃度替代指标、以及大盘内日均值回归；先定义因果时序、样本资格和多重检验族，不立即开发或运行。"
        )
    return "\n".join(lines) + "\n"


def _csv_text(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="")
    temporary.replace(path)


def write_outputs(
    output_dir: Path,
    result: dict[str, Any],
    *,
    raw_sha256: str,
    audit_manifest_sha256: str,
    script_path: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "REPORT_CN.md": render_report(result, raw_sha256, audit_manifest_sha256),
        "factor_window_summary.csv": _csv_text(result["summary_rows"]),
        "daily_stability.csv": _csv_text(result["daily_rows"]),
        "monthly_stability.csv": _csv_text(result["monthly_rows"]),
        "non_overlap_phases.csv": _csv_text(result["phase_rows"]),
        "time_bucket_matched.csv": _csv_text(result["time_rows"]),
        "signal_redundancy.csv": _csv_text(result["redundancy_rows"]),
        "diagnostic_summary.json": json.dumps(
            {
                "contract": result["contract"],
                "raw_run_status": "INCOMPLETE",
                "supplemental_audit_status": "SUPPORTED",
                "dashboard_gate_upgrade": "PROHIBITED",
                "validation_oos": "NOT_RUN",
                "executable_strategy_net_return": "NOT_TESTED",
                "edge_claim": "PROHIBITED",
                "bootstrap_replicates": result["bootstrap_replicates"],
                "multiple_testing_family_size": result["multiple_testing_family_size"],
                "factor_decisions": result["factor_decisions"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    }
    for name, content in outputs.items():
        _atomic_write(output_dir / name, content)
    manifest = {
        "contract": CONTRACT,
        "inputs": {
            "raw_run_sha256": raw_sha256,
            "ema_audit_manifest_sha256": audit_manifest_sha256,
            "analysis_script_sha256": sha256_file(script_path),
        },
        "boundaries": {
            "raw_run_status": "INCOMPLETE",
            "supplemental_audit_status": "SUPPORTED",
            "dashboard_gate_upgrade": "PROHIBITED",
            "validation_oos": "NOT_RUN",
            "executable_strategy_net_return": "NOT_TESTED",
            "edge_claim": "PROHIBITED",
        },
        "outputs": {
            name: {"sha256": sha256_file(output_dir / name), "bytes": (output_dir / name).stat().st_size}
            for name in outputs
        },
    }
    _atomic_write(output_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return manifest


def run(
    *,
    runlog: Path,
    audit_dir: Path,
    output_dir: Path,
    bootstrap_replicates: int = 5000,
) -> dict[str, Any]:
    raw, events, _ = verify_inputs(runlog, audit_dir)
    factor_events = validate_real_train_events(events)
    result = analyze_factor_events(
        factor_events,
        seed_key=sha256_bytes(raw),
        bootstrap_replicates=bootstrap_replicates,
    )
    write_outputs(
        output_dir,
        result,
        raw_sha256=sha256_bytes(raw),
        audit_manifest_sha256=sha256_file(audit_dir / "manifest.json"),
        script_path=Path(__file__),
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="C1 TRAIN六因子综合诊断（只读输入）")
    parser.add_argument("--runlog", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=5000)
    args = parser.parse_args()
    result = run(
        runlog=args.runlog,
        audit_dir=args.audit_dir,
        output_dir=args.output_dir,
        bootstrap_replicates=args.bootstrap_replicates,
    )
    print(
        json.dumps(
            {
                "status": "DIAGNOSTIC_COMPLETE",
                "factor_decisions": result["factor_decisions"],
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
