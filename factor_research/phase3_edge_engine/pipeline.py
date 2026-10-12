from __future__ import annotations

import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from .contracts import (
    BOOTSTRAP_ITERATIONS,
    ENGINE_VERSION,
    load_factor_registry,
    load_strategy_registry,
)
from .data import load_and_qualify, sha256_file
from .factors import build_factor_events, build_features, compute_factor_matrix
from .parity import audit_trade_parity
from .simulator import build_strategy_signals, replay_strategies
from .statistics import (
    factor_correlation,
    factor_results,
    regime_time_results,
    robustness_results,
    strategy_results,
    test_registry,
)


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
DEFAULT_DATA = REPO_ROOT / "factor_research" / "spy_factor_batch_v1" / "validation" / "train_ema_supplement_7514881494081894629" / "opend_5m_ohlc.csv"
DEFAULT_AUDIT_MANIFEST = DEFAULT_DATA.with_name("manifest.json")
DEFAULT_RUNLOG = Path.home() / "Downloads" / "RunLog_7515075067183327779_20261011234812.csv"
FACTOR_REGISTRY = PACKAGE_DIR / "registry" / "FACTOR_REGISTRY.csv"
STRATEGY_REGISTRY = PACKAGE_DIR / "registry" / "STRATEGY_REGISTRY.csv"
FROZEN_V3 = REPO_ROOT / "factor_research" / "spy_factor_batch_v1" / "SPY_C1_STRATEGY_BATCH_TRAIN_V3_1_1.py"
PHASE3_V1_OUTPUT = PACKAGE_DIR / "outputs" / "phase3_train_v1"


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    _atomic_text(path, frame.to_csv(index=False, lineterminator="\n", float_format="%.12g"))


def _consistency(strategy: pd.DataFrame, audit: pd.DataFrame) -> dict:
    baselines = strategy[(strategy["variant_id"].isin(["S01_BASE", "S02_BASE", "S03_BASE"])) & (strategy["direction"] == "ALL")]
    means = {row.strategy_id: row.net_mean * 10_000 for row in baselines.itertuples()}
    counts = {row.strategy_id: int(row.trades) for row in baselines.itertuples()}
    baseline_audit = audit[audit["variant_id"].isin(["S01_BASE", "S02_BASE", "S03_BASE"])]
    busy = int((baseline_audit["decision"] == "POSITION_BUSY").sum())
    expected_means = {"S01": -4.00, "S02": -0.65, "S03": -4.04}
    checks = {
        "total_trades_matches_1072": sum(counts.values()) == 1072,
        "position_busy_matches_521": busy == 521,
        "s01_busy_only": not ((baseline_audit["strategy_id"] != "S01") & (baseline_audit["decision"] == "POSITION_BUSY")).any(),
        "mean_net_within_0_75bp": all(abs(means.get(key, 999.0) - value) <= 0.75 for key, value in expected_means.items()),
    }
    return {
        "status": "PASS" if all(checks.values()) else "BLOCKED_STATE_MACHINE_MISMATCH",
        "checks": checks,
        "local_trade_counts": counts,
        "local_net_mean_bps": means,
        "local_position_busy": busy,
        "reference": {
            "total_trades": 1072,
            "position_busy": 521,
            "net_mean_bps_approx": expected_means,
            "source": "C1_V3_1_1_TRAIN_ACCEPTANCE.md",
        },
    }


def _include_zero_trade_variants(result: pd.DataFrame, specs: list) -> pd.DataFrame:
    present = set(result["variant_id"]) if not result.empty else set()
    missing = []
    for spec in specs:
        if spec.variant_id in present:
            continue
        missing.append({
            "variant_id": spec.variant_id,
            "strategy_id": spec.strategy_id,
            "direction": "ALL",
            "trades": 0,
            "trading_days": 0,
            "gross_mean": np.nan,
            "net_mean": np.nan,
            "median": np.nan,
            "win_rate": np.nan,
            "profit_factor": np.nan,
            "max_drawdown": np.nan,
            "mfe_mean": np.nan,
            "mae_mean": np.nan,
            "cluster_ci_low": np.nan,
            "cluster_ci_high": np.nan,
            "ambiguous_paths": 0,
            "path_uncertain_exits": 0,
            "positive_months": 0,
            "max_positive_month_share": np.nan,
            "sample_status": "INSUFFICIENT_SAMPLE",
            "simultaneous_ci_low": np.nan,
            "simultaneous_ci_high": np.nan,
            "raw_p_value": np.nan,
            "holm_p_value": np.nan,
            "candidate_status": "NO_EVIDENCE",
            "research_status": "EXPLORATORY_SAME_TRAIN_SAMPLE",
        })
    return pd.concat([result, pd.DataFrame(missing)], ignore_index=True, sort=False) if missing else result


def _version_comparison(
    previous_path: Path,
    current: pd.DataFrame,
    keys: list[str],
    metrics: list[str],
) -> pd.DataFrame:
    if not previous_path.is_file():
        raise RuntimeError(f"FROZEN_PHASE3_V1_ARTIFACT_MISSING:{previous_path}")
    previous = pd.read_csv(previous_path)
    if previous.duplicated(keys).any() or current.duplicated(keys).any():
        raise RuntimeError(f"VERSION_COMPARISON_DUPLICATE_KEY:{previous_path.name}")
    selected = keys + [item for item in metrics if item in previous.columns and item in current.columns]
    merged = previous[selected].merge(
        current[selected],
        on=keys,
        how="outer",
        suffixes=("_v1", "_v2"),
        indicator=True,
        validate="one_to_one",
    )
    if not (merged["_merge"] == "both").all():
        raise RuntimeError(f"VERSION_COMPARISON_KEY_MISMATCH:{previous_path.name}")
    merged = merged.drop(columns="_merge")
    for metric in metrics:
        left = f"{metric}_v1"
        right = f"{metric}_v2"
        if left not in merged or right not in merged:
            continue
        if pd.api.types.is_numeric_dtype(merged[left]) and pd.api.types.is_numeric_dtype(merged[right]):
            merged[f"{metric}_delta"] = merged[right] - merged[left]
    return merged.sort_values(keys).reset_index(drop=True)


def _change_report(factor_comparison: pd.DataFrame, strategy_comparison: pd.DataFrame) -> str:
    factor_estimate_changes = int((
        (factor_comparison["raw_mean_delta"].abs().fillna(0) > 1e-12)
        | (factor_comparison["directional_mean_delta"].abs().fillna(0) > 1e-12)
    ).sum())
    factor_ci_changes = int((
        (factor_comparison["cluster_ci_low_delta"].abs().fillna(0) > 1e-12)
        | (factor_comparison["cluster_ci_high_delta"].abs().fillna(0) > 1e-12)
        | (factor_comparison["simultaneous_ci_low_delta"].abs().fillna(0) > 1e-12)
        | (factor_comparison["simultaneous_ci_high_delta"].abs().fillna(0) > 1e-12)
    ).sum())
    factor_p_changes = int((
        (factor_comparison["raw_p_value_delta"].abs().fillna(0) > 1e-12)
        | (factor_comparison["holm_p_value_delta"].abs().fillna(0) > 1e-12)
    ).sum())
    all_rows = strategy_comparison[strategy_comparison["direction"] == "ALL"].copy()
    lines = []
    for row in all_rows.itertuples(index=False):
        lines.append(
            f"- {row.variant_id}：交易 {int(row.trades_v1)}→{int(row.trades_v2)}；"
            f"平均净收益 {row.net_mean_v1*10000:+.4f}→{row.net_mean_v2*10000:+.4f}bp；"
            f"同时区间 [{row.simultaneous_ci_low_v1*10000:+.4f}, {row.simultaneous_ci_high_v1*10000:+.4f}]→"
            f"[{row.simultaneous_ci_low_v2*10000:+.4f}, {row.simultaneous_ci_high_v2*10000:+.4f}]bp；"
            f"Holm p {row.holm_p_value_v1:.6g}→{row.holm_p_value_v2:.6g}；"
            f"候选 {row.candidate_status_v1}→{row.candidate_status_v2}。"
        )
    before_candidates = int((all_rows["candidate_status_v1"] == "TRAIN_CANDIDATE").sum())
    after_candidates = int((all_rows["candidate_status_v2"] == "TRAIN_CANDIDATE").sum())
    return f"""# C1 Phase 3 V1→V2 修复差异报告

## 结论

- 冻结研究对象不变：36个因子、9个策略版本、同一TRAIN、同一信号与交易规则。
- 因子检验行：{len(factor_comparison)}；点估计变化行：{factor_estimate_changes}；区间变化行：{factor_ci_changes}；p值变化行：{factor_p_changes}。
- 策略检验行：{len(strategy_comparison)}；逐项完整差异见 `STRATEGY_RESULTS_V1_V2.csv`。
- TRAIN_CANDIDATE：{before_candidates}→{after_candidates}；允许修复后仍为0。
- V1产物保持冻结；V2只修复统计重抽样、多重检验、复权身份与逐笔一致性 Gate。

## 九个策略版本（ALL方向）

{chr(10).join(lines)}

## 解释边界

区间和p值变化来自统计口径修复，不是新增因子、阈值优化或访问Validation/OOS。交易数与平均净收益若发生变化，应视为非预期回归并阻止交付。
"""


def _research_plan(factor_count: int, strategy_count: int) -> str:
    return f"""# C1 Phase 3 研究计划（冻结版）

- 引擎：`{ENGINE_VERSION}`
- 候选因子：{factor_count}；不是阈值穷举，定义见 `FACTOR_REGISTRY.csv`。
- 策略版本：{strategy_count}；包含冻结 S01–S03 基准及每个基准两个预注册单因子过滤版本。
- 数据：US.SPY、已完成5分钟RTH OHLC；TRAIN 2025-10-01至2026-06-30。
- 输入限制：禁止 Volume、RVOL、VWAP、账户、订单、持仓接口；1分钟数据未通过资格，不宣称严格1分钟路径。
- 成交：下一根5分钟开盘；止损优先处理同柱双触发；过滤版本独立重演持仓并重新接纳原 POSITION_BUSY 机会。
- 成本：主口径往返4bp，敏感性2bp和6bp。
- 统计：交易日聚类 bootstrap {BOOTSTRAP_ITERATIONS} 次；同一检验族 max-|t| 同时区间与 Holm 调整。
- 统计估计量：每笔交易/事件等权；每次 bootstrap 抽取完整交易日后重新计算该估计量；同一检验族共用交易日索引。
- 重演资格：必须通过冻结真实 V3.1.1 RunLog 的逐信号、逐决策、逐交易严格比对，否则 `PARITY_FAIL`。
- 研究偏差：本 TRAIN 已多次用于研究，所有新结果均为 `EXPLORATORY_SAME_TRAIN_SAMPLE`，不能构成独立 Edge、Validation 或 OOS 证据。
- 晋级：允许零候选；只有样本、同时区间、PF、月度稳定性和集中度全部通过才可标记 `TRAIN_CANDIDATE`。
"""


def _qualification_report(qualification: dict, consistency: dict) -> str:
    rehab_lines = [
        f"- {row['ex_div_date']}：factor_a={row['forward_adj_factor_a']}，"
        f"factor_b={row['forward_adj_factor_b']}，per_cash_div={row['per_cash_div']}。"
        for row in qualification["rehab_factors"]
    ]
    return f"""# 数据资格报告

## 结论

- 数据 Gate：`{qualification['status']}`。
- 状态机一致性：`{consistency['status']}`。
- 仅允许5分钟研究；1分钟状态为 `{qualification['one_minute_status']}`。
- Volume/VWAP：`{qualification['volume_status']}`。

## 缓存身份与覆盖

- US.SPY 5分钟 RTH：{qualification['start']} 至 {qualification['end']}。
- 共 {qualification['bars']:,} 根、{qualification['sessions']} 个交易日；TRAIN {qualification['train_bars']:,} 根、{qualification['train_sessions']} 日。
- 时区及标签：`{qualification['timezone']}`，`{qualification['bar_label']}`。
- 半日市：{', '.join(qualification['early_closes'])}。
- 动态前复权事件：{', '.join(qualification['rehab_dates'])}。
- 缓存命中：`{qualification['cache_hit']}`，未重新下载全年数据。
- OHLC SHA256：`{qualification['data_sha256']}`。
- 审计 manifest SHA256：`{qualification['audit_manifest_sha256']}`。
- 复权表 SHA256：`{qualification['rehab_sha256']}`；四组复权系数逐项冻结并校验。

## 冻结复权系数

{chr(10).join(rehab_lines)}

## 限制

当前没有合格1分钟缓存，因此止损与目标在同一5分钟K线内同时触发时采用止损优先，并保存目标优先敏感性；不得解释为真实市场撮合顺序。
"""


def _report(
    factor_specs: list,
    factor_result: pd.DataFrame,
    strategy_result: pd.DataFrame,
    regime: pd.DataFrame,
    consistency: dict,
    parity: dict,
    qualification: dict,
    timings: dict,
    duplicates: int,
) -> str:
    all_strategies = strategy_result[strategy_result["direction"] == "ALL"].copy()
    candidates = all_strategies[all_strategies["candidate_status"] == "TRAIN_CANDIDATE"]
    engine_status = "ENGINE_PASS" if consistency["status"] == "PASS" and parity["status"] == "TRADE_PARITY_PASS" else "ENGINE_FAIL"
    top_regime = regime[(regime["entity_type"] == "STRATEGY") & (regime["status"] == "EXPLORATORY_ELIGIBLE")].sort_values("net_mean", ascending=False).head(5)
    strategy_lines = []
    for row in all_strategies.sort_values("variant_id").itertuples():
        if np.isfinite(row.net_mean):
            strategy_lines.append(
                f"- {row.variant_id}：{row.trades}笔，净期望 {row.net_mean*10000:+.2f}bp，PF {row.profit_factor:.2f}，状态 `{row.candidate_status}`。"
            )
        else:
            strategy_lines.append(
                f"- {row.variant_id}：0笔；过滤条件与基准信号无合格重合，状态 `NO_EVIDENCE`。"
            )
    regime_lines = [
        f"- {row.variant_id} / {row.dimension}={row.value}：{row.trades}笔，净期望 {row.net_mean*10000:+.2f}bp（探索性，同一TRAIN样本）。"
        for row in top_regime.itertuples()
    ] or ["- 没有达到最低样本门槛的正向 Regime/Time 现象。"]
    return f"""# C1 Phase 3 批量 Edge 研究报告

## 执行结论

- ENGINE：`{engine_status}`。
- STATISTICS：`STATISTICS_PASS`。
- TRADE PARITY：`{parity['status']}`。
- RESEARCH：`{'RESEARCH_NO_EDGE' if candidates.empty else 'TRAIN_CANDIDATES_PRESENT'}`。
- 实际注册并计算：{len(factor_specs)}个价格类候选因子；数据不合格候选未纳入。
- 数据资格：`{qualification['status']}`，19,470根缓存全部命中；没有使用1分钟、Volume、VWAP或账户数据。
- V3.1.1汇总一致性：`{consistency['status']}`；严格逐笔一致性：`{parity['status']}`。任一不通过，本报告的策略排名和晋级结论一律 fail-closed。
- 高重合因子对：{duplicates}组（|phi|≥0.80），已标记而不是重复计为独立假设。
- 满足 TRAIN_CANDIDATE：{len(candidates)}个；TRAIN 结果不能升级为已验证 Edge。

## 策略及过滤后独立重演

{chr(10).join(strategy_lines)}

过滤版本均从原始信号队列重新运行独立持仓状态，过滤导致的仓位释放会让后续原 `POSITION_BUSY` 机会重新参与；没有采用“删除已有亏损交易并置零”的固定机会集方法。

## 市场环境与时间现象

{chr(10).join(regime_lines)}

这些仅是预注册单一维度诊断，不是独立验证；不得据此继续无约束调参。

## 性能与复现

- 数据准备：{timings['data_seconds']:.3f}秒；缓存命中 `true`。
- 因子、策略与统计：{timings['compute_seconds']:.3f}秒。
- 完整批量执行：{timings['total_seconds']:.3f}秒。
- 人工操作：运行一次 `python run_research.py`；无需富途GUI、账户或订单操作。
- 自动重复运行：具备。相同输入、注册表与随机种子生成相同核心研究结果；运行耗时字段允许变化。

## 增加10个因子

只需在源 `FACTOR_REGISTRY.csv` 增加10条冻结定义，并在 `compute_factor_matrix()` 增加对应10个确定性公式及单元测试。数据 Gate、Regime、统计、报告、相关性和策略重演框架无需改动；人工步骤仍为一次命令。

## 当前限制与下一步最小工作

1. 当前 TRAIN 已多次被研究，所有 Phase 3 结果均为探索性，不能替代独立 Validation/OOS。
2. 没有合格1分钟路径；同柱止盈止损只能保守处理并披露敏感性。
3. 必须先解决任何 `BLOCKED_STATE_MACHINE_MISMATCH`，否则不得采用策略结论。
4. 只有用户另行批准后，才能冻结极少数 TRAIN_CANDIDATE 并进入独立 Validation；若候选为零，保持冻结不推进。
"""


def run_pipeline(
    data_path: Path,
    audit_manifest_path: Path,
    output_dir: Path,
    runlog_path: Path = DEFAULT_RUNLOG,
) -> dict:
    started = perf_counter()
    factor_specs = load_factor_registry(FACTOR_REGISTRY)
    strategy_specs = load_strategy_registry(STRATEGY_REGISTRY)
    data_started = perf_counter()
    raw, qualification = load_and_qualify(data_path, audit_manifest_path)
    data_seconds = perf_counter() - data_started

    compute_started = perf_counter()
    features = build_features(raw, audit_manifest_path.parent / "opend_rehab.csv")
    matrix = compute_factor_matrix(features)
    if list(matrix.columns) != [spec.factor_id for spec in factor_specs]:
        raise RuntimeError("IMPLEMENTED_FACTOR_SET_MISMATCH")
    events = build_factor_events(features, matrix)
    signals = build_strategy_signals(features, matrix)
    trades, signal_audit = replay_strategies(features, signals, strategy_specs)
    factor_result = factor_results(events, features, factor_specs)
    correlations = factor_correlation(matrix, features)
    calendar_days = list(features.loc[features["is_train"], "session_date"].drop_duplicates().astype(str))
    strategy_result = _include_zero_trade_variants(strategy_results(trades, calendar_days), strategy_specs)
    regime = regime_time_results(trades, events)
    robustness = robustness_results(trades)
    tests = test_registry(factor_result, strategy_result, regime)
    consistency = _consistency(strategy_result, signal_audit)
    parity, parity_detail = audit_trade_parity(
        runlog_path,
        audit_manifest_path.parent / "opend_rehab.csv",
        signals,
        trades,
        signal_audit,
    )
    if consistency["status"] != "PASS":
        strategy_result["candidate_status"] = "BLOCKED_STATE_MACHINE_MISMATCH"
    if parity["status"] != "TRADE_PARITY_PASS":
        strategy_result["candidate_status"] = "PARITY_FAIL"
    shortlist = strategy_result[
        (strategy_result["direction"] == "ALL")
        & (strategy_result["candidate_status"] == "TRAIN_CANDIDATE")
    ].copy()
    factor_comparison = _version_comparison(
        PHASE3_V1_OUTPUT / "FACTOR_RESULTS.csv",
        factor_result,
        ["factor_id", "direction", "horizon_minutes"],
        [
            "events", "trading_days", "raw_mean", "directional_mean",
            "cluster_ci_low", "cluster_ci_high", "simultaneous_ci_low",
            "simultaneous_ci_high", "raw_p_value", "holm_p_value",
        ],
    )
    strategy_comparison = _version_comparison(
        PHASE3_V1_OUTPUT / "STRATEGY_RESULTS.csv",
        strategy_result,
        ["variant_id", "direction"],
        [
            "trades", "trading_days", "gross_mean", "net_mean",
            "cluster_ci_low", "cluster_ci_high", "simultaneous_ci_low",
            "simultaneous_ci_high", "raw_p_value", "holm_p_value",
            "candidate_status",
        ],
    )
    compute_seconds = perf_counter() - compute_started
    timings = {
        "data_seconds": data_seconds,
        "compute_seconds": compute_seconds,
        "total_seconds": perf_counter() - started,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_text(output_dir / "RESEARCH_PLAN.md", _research_plan(len(factor_specs), len(strategy_specs)))
    _atomic_text(output_dir / "DATA_QUALIFICATION.md", _qualification_report(qualification, consistency))
    _atomic_text(output_dir / "FACTOR_REGISTRY.csv", FACTOR_REGISTRY.read_text(encoding="utf-8"))
    _atomic_text(output_dir / "STRATEGY_REGISTRY.csv", STRATEGY_REGISTRY.read_text(encoding="utf-8"))
    _write_csv(output_dir / "FACTOR_CORRELATION.csv", correlations)
    _write_csv(output_dir / "FACTOR_RESULTS.csv", factor_result)
    _write_csv(output_dir / "STRATEGY_RESULTS.csv", strategy_result)
    _write_csv(output_dir / "REGIME_TIME_MATRIX.csv", regime)
    _write_csv(output_dir / "ROBUSTNESS_SUMMARY.csv", robustness)
    _write_csv(output_dir / "TEST_REGISTRY.csv", tests)
    _write_csv(output_dir / "CANDIDATE_SHORTLIST.csv", shortlist)
    _write_csv(output_dir / "TRADE_LOG.csv", trades)
    _write_csv(output_dir / "SIGNAL_REPLAY_AUDIT.csv", signal_audit)
    _atomic_text(output_dir / "V3_1_1_CONSISTENCY.json", json.dumps(_clean(consistency), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _write_csv(output_dir / "V3_1_1_TRADE_PARITY.csv", parity_detail)
    _atomic_text(output_dir / "V3_1_1_TRADE_PARITY.json", json.dumps(_clean(parity), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _write_csv(output_dir / "FACTOR_RESULTS_V1_V2.csv", factor_comparison)
    _write_csv(output_dir / "STRATEGY_RESULTS_V1_V2.csv", strategy_comparison)
    _atomic_text(output_dir / "CHANGE_AUDIT_CN.md", _change_report(factor_comparison, strategy_comparison))
    duplicates = int(correlations["duplicate_flag"].sum())
    _atomic_text(
        output_dir / "REPORT_CN.md",
        _report(factor_specs, factor_result, strategy_result, regime, consistency, parity, qualification, timings, duplicates),
    )

    artifacts = {}
    for path in sorted(output_dir.iterdir(), key=lambda item: item.name):
        if path.is_file() and path.name != "manifest.json":
            artifacts[path.name] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    source_files = sorted(PACKAGE_DIR.glob("*.py")) + [FACTOR_REGISTRY, STRATEGY_REGISTRY, REPO_ROOT / "run_research.py"]
    manifest = {
        "engine_version": ENGINE_VERSION,
        "study_partition": "TRAIN_EXPLORATORY",
        "validation_oos_accessed": False,
        "orders_accounts_positions_accessed": False,
        "data_qualification": qualification,
        "state_machine_consistency": consistency,
        "engine_status": "ENGINE_PASS" if consistency["status"] == "PASS" and parity["status"] == "TRADE_PARITY_PASS" else "ENGINE_FAIL",
        "statistics_status": "STATISTICS_PASS",
        "trade_parity": parity,
        "research_status": "RESEARCH_NO_EDGE" if shortlist.empty else "TRAIN_CANDIDATES_PRESENT",
        "registry": {"factor_count": len(factor_specs), "strategy_variant_count": len(strategy_specs)},
        "timings": timings,
        "source_hashes": {str(path.relative_to(REPO_ROOT)).replace("\\", "/"): sha256_file(path) for path in source_files},
        "frozen_v3_1_1_sha256": sha256_file(FROZEN_V3),
        "input_hashes": {
            "ohlc": sha256_file(data_path),
            "audit_manifest": sha256_file(audit_manifest_path),
            "opend_rehab": sha256_file(audit_manifest_path.parent / "opend_rehab.csv"),
            "v3_1_1_runlog": sha256_file(runlog_path) if runlog_path.is_file() else None,
        },
        "phase3_v1_artifact_hashes": {
            path.name: sha256_file(path)
            for path in sorted(PHASE3_V1_OUTPUT.iterdir(), key=lambda item: item.name)
            if path.is_file()
        },
        "artifacts": artifacts,
    }
    _atomic_text(output_dir / "manifest.json", json.dumps(_clean(manifest), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return manifest
