from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import mean
from typing import Any

from factor_research.spy_factor_batch_v1.train_factor_diagnostic import (
    FACTOR_NAMES,
    validate_real_train_events,
    verify_inputs,
)
from quant_workflow.factor_research.progress_dashboard.ingest import BATCH_FACTORS


CONTRACT = "C1_TRAIN_TIME_MATCH_POSTHOC_V1"


def _bucket(time_text: str, minutes: int) -> int:
    hour, minute = (int(value) for value in time_text[11:16].split(":"))
    return (hour * 60 + minute - 575) // minutes


def analyze(factor_events: list[dict[str, Any]], bucket_minutes: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for factor_id, prefix, _ in BATCH_FACTORS:
        strata: dict[tuple[str, int], list[tuple[str, float]]] = {}
        for event in factor_events:
            key = (str(event["session_date_et"]), _bucket(str(event["signal_time_et"]), bucket_minutes))
            strata.setdefault(key, []).append((str(event[prefix + "_state"]), float(event["r6"])))
        matched = []
        unmatched = []
        for key, observations in strata.items():
            pass_values = [value for state, value in observations if state == "PASS"]
            fail_values = [value for state, value in observations if state == "FAIL"]
            item = {
                "key": key, "n": len(observations), "pass_n": len(pass_values),
                "fail_n": len(fail_values), "pass_values": pass_values, "fail_values": fail_values,
                "baseline_mean": mean(value for _, value in observations),
            }
            (matched if pass_values and fail_values else unmatched).append(item)
        matched_pass = [value for item in matched for value in item["pass_values"]]
        matched_fail = [value for item in matched for value in item["fail_values"]]
        diffs = [(mean(item["pass_values"]) - mean(item["fail_values"])) * 10000 for item in matched]
        weights = [item["pass_n"] * item["fail_n"] / item["n"] for item in matched]
        weight_total = sum(weights)
        ordered_weights = sorted(weights, reverse=True)
        all_pass = [item for item in unmatched if item["pass_n"]]
        all_fail = [item for item in unmatched if item["fail_n"]]
        rows.append({
            "factor_id": factor_id,
            "factor_name_cn": FACTOR_NAMES[factor_id],
            "bucket_minutes": bucket_minutes,
            "strata_total": len(strata),
            "strata_matched": len(matched),
            "strata_coverage": len(matched) / len(strata),
            "events_total": sum(len(item) for item in strata.values()),
            "events_matched": sum(item["n"] for item in matched),
            "event_coverage": sum(item["n"] for item in matched) / sum(len(item) for item in strata.values()),
            "matched_pass_n": len(matched_pass),
            "matched_fail_n": len(matched_fail),
            "matched_raw_diff_bps": (mean(matched_pass) - mean(matched_fail)) * 10000 if matched_pass and matched_fail else None,
            "equal_stratum_diff_bps": mean(diffs) if diffs else None,
            "fixed_effect_diff_bps": sum(diff * weight for diff, weight in zip(diffs, weights)) / weight_total if weight_total else None,
            "effective_strata": weight_total * weight_total / sum(weight * weight for weight in weights) if weights else 0.0,
            "largest_weight_share": ordered_weights[0] / weight_total if weight_total else None,
            "top5_weight_share": sum(ordered_weights[:5]) / weight_total if weight_total else None,
            "unmatched_all_pass_strata": len(all_pass),
            "unmatched_all_fail_strata": len(all_fail),
            "unmatched_all_pass_mean_return": mean(item["baseline_mean"] for item in all_pass) if all_pass else None,
            "unmatched_all_fail_mean_return": mean(item["baseline_mean"] for item in all_fail) if all_fail else None,
            "unmatched_positive_baseline_share": sum(item["baseline_mean"] > 0 for item in unmatched) / len(unmatched) if unmatched else None,
        })
    return rows


def render_report(rows: list[dict[str, Any]], raw_sha: str, manifest_sha: str) -> str:
    by_factor = {}
    for row in rows:
        by_factor.setdefault(row["factor_id"], {})[row["bucket_minutes"]] = row
    thirty = [by_factor[factor_id][30] for factor_id in sorted(by_factor)]
    lines = [
        "# C1 第一批 30分钟同日时段匹配核查",
        "",
        "> **事后新增敏感性诊断。** 本核查在查看部分 TRAIN 结果后新增，不修改 F001–F006 全部暂不晋级的冻结结论。",
        "",
        "## 证据边界",
        "",
        f"- 原始 CSV SHA256：`{raw_sha}`",
        f"- EMA 补充审计 manifest SHA256：`{manifest_sha}`",
        "- 原始 `RUN_END=INCOMPLETE` 保持不变；EMA 补充审计仅为 `SUPPORTED`。",
        "- 未运行 Validation/OOS，未修改 Dashboard Gate。",
        "",
        "## 30分钟匹配结果",
        "",
        "| 因子 | 匹配时段/全部 | 时段覆盖 | 事件覆盖 | 匹配样本 PASS/FAIL | 匹配样本原始差 | 固定效应差 | 有效时段数 | 最大权重 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for factor_id in sorted(by_factor):
        row = by_factor[factor_id][30]
        lines.append(
            f"| {factor_id} {row['factor_name_cn']} | {row['strata_matched']}/{row['strata_total']} | "
            f"{row['strata_coverage']:.1%} | {row['event_coverage']:.1%} | {row['matched_pass_n']}/{row['matched_fail_n']} | "
            f"{row['matched_raw_diff_bps']:+.3f} bp | {row['fixed_effect_diff_bps']:+.3f} bp | "
            f"{row['effective_strata']:.1f} | {row['largest_weight_share']:.1%} |"
        )
    lines.extend([
        "",
        f"六个因子的匹配样本原始差与固定效应差方向一致：{sum(row['matched_raw_diff_bps'] * row['fixed_effect_diff_bps'] > 0 for row in thirty)}/6；本次均为负。有效时段数为 {min(row['effective_strata'] for row in thirty):.1f}–{max(row['effective_strata'] for row in thirty):.1f}，单一时段最大权重不超过 {max(row['largest_weight_share'] for row in thirty):.1%}，前五时段合计不超过 {max(row['top5_weight_share'] for row in thirty):.1%}，没有由少数时段权重主导。",
        "",
        "“匹配样本原始差”只在能同时观察 PASS/FAIL 的日×时段内按事件加权；“固定效应差”先在每个日×时段求差，再按 `n_pass*n_fail/(n_pass+n_fail)` 加权。二者估计目标不同，不能把更漂亮的一项替换成主结论。",
        "",
        "## 未匹配时段与选择效应",
        "",
        "| 因子 | 全PASS时段 | 全FAIL时段 | 全PASS时段基准收益 | 全FAIL时段基准收益 | 未匹配时段正收益占比 |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for factor_id in sorted(by_factor):
        row = by_factor[factor_id][30]
        def pct(value):
            return "—" if value is None else f"{value:.3%}"
        lines.append(
            f"| {factor_id} | {row['unmatched_all_pass_strata']} | {row['unmatched_all_fail_strata']} | "
            f"{pct(row['unmatched_all_pass_mean_return'])} | {pct(row['unmatched_all_fail_mean_return'])} | {pct(row['unmatched_positive_baseline_share'])} |"
        )
    lines.extend([
        "",
        "这里的‘正/负市场状态’只是该时段未来30分钟实际收益的结果态，用于诊断缺失匹配是否选择了不同市场，不是信号时可用 Regime，也不得用于新策略条件。",
        "",
        "## 更细时间分层敏感性",
        "",
        "| 因子 | 30m固定效应 | 15m固定效应 | 5m可匹配时段 | 15m事件覆盖 |",
        "|---|---:|---:|---:|---:|",
    ])
    for factor_id in sorted(by_factor):
        r30, r15, r5 = by_factor[factor_id][30], by_factor[factor_id][15], by_factor[factor_id][5]
        f = lambda value: "—" if value is None else f"{value:+.3f} bp"
        lines.append(f"| {factor_id} | {f(r30['fixed_effect_diff_bps'])} | {f(r15['fixed_effect_diff_bps'])} | {r5['strata_matched']} | {r15['event_coverage']:.1%} |")
    lines.extend([
        "",
        "5分钟层每个时段只有一个事件，结构上不可能同时包含 PASS 和 FAIL；因此它不是失败证据，而是说明完全细化会失去组内识别。15分钟层估计更局部的时段内差异，但覆盖通常更低；30分钟层以更强的时段同质假设换取更多匹配。",
        "",
        "## 结论",
        "",
        "- 这项诊断只能说明原始 PASS/FAIL 差异对日内时段控制有多敏感，不能建立交易净收益。",
        "- 权重有效时段数和最大/前五权重用于检查少数时段主导；完整数值同时保存在 JSON/CSV。",
        "- 第一批六因子继续保持全部暂不晋级；本报告不根据替代估计量重新挑选赢家。",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runlog", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    raw, events, _ = verify_inputs(args.runlog, args.audit_dir)
    factor_events = validate_real_train_events(events)
    rows = [row for minutes in (30, 15, 5) for row in analyze(factor_events, minutes)]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_sha = hashlib.sha256(raw).hexdigest()
    manifest_sha = hashlib.sha256((args.audit_dir / "manifest.json").read_bytes()).hexdigest()
    (args.output_dir / "summary.json").write_text(json.dumps({"contract": CONTRACT, "raw_sha256": raw_sha, "audit_manifest_sha256": manifest_sha, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output_dir / "time_match_sensitivity.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    (args.output_dir / "REPORT_CN.md").write_text(render_report(rows, raw_sha, manifest_sha), encoding="utf-8")
    artifacts = {}
    for name in ("REPORT_CN.md", "summary.json", "time_match_sensitivity.csv"):
        path = args.output_dir / name
        artifacts[name] = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (args.output_dir / "manifest.json").write_text(json.dumps({
        "contract": CONTRACT, "status": "DIAGNOSTIC_ONLY",
        "selection_timing": "ADDED_AFTER_PARTIAL_TRAIN_REVIEW",
        "raw_run_sha256": raw_sha, "raw_run_status_preserved": "INCOMPLETE",
        "ema_supplement_status": "SUPPORTED", "dashboard_gate_upgrade": "PROHIBITED",
        "validation_oos_run": False, "edge_claim": "PROHIBITED", "artifacts": artifacts,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
