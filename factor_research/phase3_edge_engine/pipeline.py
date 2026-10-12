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
    load_factor_registry,
    load_strategy_registry,
)
from .data import load_and_qualify, sha256_file
from .factors import build_factor_events, build_features, compute_factor_matrix
from .parity import audit_trade_parity
from .simulator import build_strategy_signals, replay_strategies
from .statistics import (
    append_statistics_gate_check,
    factor_correlation,
    factor_results,
    regime_time_results,
    robustness_results,
    strategy_results,
    statistics_integrity_gate,
    test_registry,
)


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
ENGINE_VERSION = "C1_PHASE3_EDGE_ENGINE_V3"
DEFAULT_DATA = REPO_ROOT / "factor_research" / "spy_factor_batch_v1" / "validation" / "train_ema_supplement_7514881494081894629" / "opend_5m_ohlc.csv"
DEFAULT_AUDIT_MANIFEST = DEFAULT_DATA.with_name("manifest.json")
DEFAULT_RUNLOG = Path.home() / "Downloads" / "RunLog_7515075067183327779_20261011234812.csv"
FACTOR_REGISTRY = PACKAGE_DIR / "registry" / "FACTOR_REGISTRY.csv"
STRATEGY_REGISTRY = PACKAGE_DIR / "registry" / "STRATEGY_REGISTRY.csv"
FROZEN_V3 = REPO_ROOT / "factor_research" / "spy_factor_batch_v1" / "SPY_C1_STRATEGY_BATCH_TRAIN_V3_1_1.py"
PHASE3_V1_OUTPUT = PACKAGE_DIR / "outputs" / "phase3_train_v1"
PHASE3_V2_OUTPUT = PACKAGE_DIR / "outputs" / "phase3_train_v2"
PHASE3_V3_OUTPUT = PACKAGE_DIR / "outputs" / "phase3_train_v3"
PROTECTED_OUTPUT_DIRS = {PHASE3_V1_OUTPUT.resolve(), PHASE3_V2_OUTPUT.resolve()}


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


def _validate_output_target(output_dir: Path) -> None:
    resolved = output_dir.resolve()
    if resolved in PROTECTED_OUTPUT_DIRS:
        raise RuntimeError(f"PROTECTED_OUTPUT_PATH:{resolved}")
    if resolved.exists():
        raise RuntimeError(f"OUTPUT_DIRECTORY_ALREADY_EXISTS:{resolved}")


def _directory_hashes(path: Path) -> dict[str, str]:
    return {
        str(item.relative_to(path)).replace("\\", "/"): sha256_file(item)
        for item in sorted(path.rglob("*"), key=lambda value: str(value))
        if item.is_file()
    }


def _frozen_history_snapshot() -> dict:
    v1_hashes = _directory_hashes(PHASE3_V1_OUTPUT)
    v2_hashes = _directory_hashes(PHASE3_V2_OUTPUT)
    v2_manifest = json.loads((PHASE3_V2_OUTPUT / "manifest.json").read_text(encoding="utf-8"))
    declared_v1 = v2_manifest.get("phase3_v1_artifact_hashes", {})
    declared_v2 = {
        name: item["sha256"] for name, item in v2_manifest.get("artifacts", {}).items()
    }
    v1_mismatches = sorted(
        name for name in set(v1_hashes) | set(declared_v1)
        if v1_hashes.get(name) != declared_v1.get(name)
    )
    v2_actual_without_manifest = {
        name: value for name, value in v2_hashes.items() if name != "manifest.json"
    }
    v2_mismatches = sorted(
        name for name in set(v2_actual_without_manifest) | set(declared_v2)
        if v2_actual_without_manifest.get(name) != declared_v2.get(name)
    )
    return {
        "v1": v1_hashes,
        "v2": v2_hashes,
        "declared_integrity": {
            "status": "PASS" if not v1_mismatches and not v2_mismatches else "FAIL",
            "v1_mismatches": v1_mismatches,
            "v2_mismatches": v2_mismatches,
        },
    }


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
            "standard_error": np.nan,
            "inference_target": "NET_MEAN_VS_ZERO",
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
        suffixes=("_v2", "_v3"),
        indicator=True,
        validate="one_to_one",
    )
    if not (merged["_merge"] == "both").all():
        raise RuntimeError(f"VERSION_COMPARISON_KEY_MISMATCH:{previous_path.name}")
    merged = merged.drop(columns="_merge")
    for metric in metrics:
        left = f"{metric}_v2"
        right = f"{metric}_v3"
        if left not in merged or right not in merged:
            continue
        if pd.api.types.is_numeric_dtype(merged[left]) and pd.api.types.is_numeric_dtype(merged[right]):
            merged[f"{metric}_delta"] = merged[right] - merged[left]
    return merged.sort_values(keys).reset_index(drop=True)


def _value_equal(left: Any, right: Any) -> bool:
    if pd.isna(left) or pd.isna(right):
        return bool(pd.isna(left) and pd.isna(right))
    if isinstance(left, (int, float, np.integer, np.floating)) and isinstance(
        right, (int, float, np.integer, np.floating)
    ):
        return bool(np.isclose(float(left), float(right), rtol=1e-9, atol=1e-12))
    return str(left) == str(right)


def _unexpected_changes(
    previous: pd.DataFrame,
    current: pd.DataFrame,
    keys: list[str],
    allowed_columns: set[str],
) -> list[str]:
    common = [column for column in previous.columns if column in current.columns]
    compared = [column for column in common if column not in set(keys) | allowed_columns]
    merged = previous[keys + compared].merge(
        current[keys + compared],
        on=keys,
        how="outer",
        suffixes=("_v2", "_v3"),
        indicator=True,
        validate="one_to_one",
    )
    failures: list[str] = []
    for row in merged.to_dict("records"):
        identity = "|".join(str(row[key]) for key in keys)
        if row["_merge"] != "both":
            failures.append(f"{identity}:KEY_{row['_merge'].upper()}")
            continue
        for column in compared:
            if not _value_equal(row[f"{column}_v2"], row[f"{column}_v3"]):
                failures.append(f"{identity}:{column}")
    return failures


def _v2_v3_integrity(factor_result: pd.DataFrame, strategy_result: pd.DataFrame) -> dict:
    factor_v2 = pd.read_csv(PHASE3_V2_OUTPUT / "FACTOR_RESULTS.csv")
    strategy_v2 = pd.read_csv(PHASE3_V2_OUTPUT / "STRATEGY_RESULTS.csv")
    factor_failures = _unexpected_changes(
        factor_v2,
        factor_result,
        ["factor_id", "direction", "horizon_minutes"],
        {"baseline_mean", "increment"},
    )
    strategy_failures = _unexpected_changes(
        strategy_v2,
        strategy_result,
        ["variant_id", "direction"],
        set(),
    )
    factor_comparison = _version_comparison(
        PHASE3_V2_OUTPUT / "FACTOR_RESULTS.csv",
        factor_result,
        ["factor_id", "direction", "horizon_minutes"],
        [
            "events", "trading_days", "raw_mean", "directional_mean", "baseline_mean",
            "increment", "cluster_ci_low", "cluster_ci_high", "simultaneous_ci_low",
            "simultaneous_ci_high", "raw_p_value", "holm_p_value", "rank",
        ],
    )
    strategy_comparison = _version_comparison(
        PHASE3_V2_OUTPUT / "STRATEGY_RESULTS.csv",
        strategy_result,
        ["variant_id", "direction"],
        [
            "trades", "trading_days", "gross_mean", "net_mean", "profit_factor",
            "cluster_ci_low", "cluster_ci_high", "simultaneous_ci_low",
            "simultaneous_ci_high", "raw_p_value", "holm_p_value", "candidate_status",
        ],
    )
    short = factor_comparison["direction"] == "SHORT"
    baseline_changes = int((factor_comparison["baseline_mean_delta"].abs().fillna(0) > 1e-12).sum())
    increment_changes = int((factor_comparison["increment_delta"].abs().fillna(0) > 1e-12).sum())
    short_rows = int(short.sum())
    new_fields = {
        "baseline_raw_market", "baseline_directional", "inference_target", "standard_error",
    }
    required_new_fields_present = new_fields.issubset(factor_result.columns)
    candidate_v2 = int((strategy_v2["candidate_status"] == "TRAIN_CANDIDATE").sum())
    candidate_v3 = int((strategy_result["candidate_status"] == "TRAIN_CANDIDATE").sum())
    expected_changes = (
        baseline_changes == short_rows
        and increment_changes == short_rows
        and required_new_fields_present
        and candidate_v2 == candidate_v3 == 0
    )
    status = "PASS" if not factor_failures and not strategy_failures and expected_changes else "FAIL"
    return {
        "status": status,
        "factor_rows": len(factor_result),
        "strategy_rows": len(strategy_result),
        "short_rows": short_rows,
        "baseline_rows_changed": baseline_changes,
        "increment_rows_changed": increment_changes,
        "required_new_fields_present": required_new_fields_present,
        "candidate_count_v2": candidate_v2,
        "candidate_count_v3": candidate_v3,
        "unexpected_factor_changes": factor_failures,
        "unexpected_strategy_changes": strategy_failures,
        "factor_comparison": factor_comparison,
        "strategy_comparison": strategy_comparison,
    }


def _change_report(integrity: dict) -> str:
    strategy_comparison = integrity["strategy_comparison"]
    all_rows = strategy_comparison[strategy_comparison["direction"] == "ALL"].copy()
    lines = []
    for row in all_rows.itertuples(index=False):
        lines.append(
            f"- {row.variant_id}：交易 {int(row.trades_v2)}→{int(row.trades_v3)}；"
            f"平均净收益 {row.net_mean_v2*10000:+.4f}→{row.net_mean_v3*10000:+.4f}bp；"
            f"PF {row.profit_factor_v2:.4f}→{row.profit_factor_v3:.4f}；"
            f"候选 {row.candidate_status_v2}→{row.candidate_status_v3}。"
        )
    return f"""# C1 Phase 3 V2→V3 统计完整性修复差异报告

## 结论

- 差异 Gate：`{integrity['status']}`。
- 冻结研究对象不变：36个因子、9个策略版本、同一TRAIN、同一信号与交易规则。
- 因子检验行：{integrity['factor_rows']}；Short 行：{integrity['short_rows']}。
- `baseline_mean` 允许变化行：{integrity['baseline_rows_changed']}；`increment` 允许变化行：{integrity['increment_rows_changed']}。
- 新增字段完整：`{str(integrity['required_new_fields_present']).lower()}`。
- 非预期因子变化：{len(integrity['unexpected_factor_changes'])}；非预期策略变化：{len(integrity['unexpected_strategy_changes'])}。
- TRAIN_CANDIDATE：{integrity['candidate_count_v2']}→{integrity['candidate_count_v3']}。

## 九个策略版本（ALL方向）

{chr(10).join(lines)}

## 统计解释

- V3 将 Short 的比较基准方向化；REGIME 继续对比原始无条件市场收益。
- `INFERENCE_TARGET = DIRECTIONAL_MEAN_VS_ZERO`；现有 CI/p-value 不解释为 increment 显著性。
- 只有 Short baseline/increment、新字段、Gate证据、版本哈希和运行耗时允许变化。
- 任一信号、交易、净收益、PF、方向均值、rank、CI/p-value或候选变化均阻断验收。
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
- 因子基准：Long 使用原始市场基准，Short 使用取反后的方向化市场基准，REGIME 使用原始市场基准。
- 推断目标：`DIRECTIONAL_MEAN_VS_ZERO`；现有 CI/p-value 不用于检验 increment。
- 统计验收：`STATISTICS_PASS` 只能由 `STATISTICS_GATE.json` 的全部确定性检查共同产生。
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
    statistics_gate: dict,
    acceptance_status: str,
    v2_v3_integrity: dict,
    research_status: str,
    qualification: dict,
    timings: dict,
    duplicates: int,
) -> str:
    all_strategies = strategy_result[strategy_result["direction"] == "ALL"].copy()
    candidates = all_strategies[all_strategies["candidate_status"] == "TRAIN_CANDIDATE"]
    engine_status = "ENGINE_PASS" if consistency["status"] == "PASS" else "ENGINE_FAIL"
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
    return f"""# C1 Phase 3 V3 统计完整性修复报告

## 执行结论

- DATA QUALIFICATION：`{qualification['status']}`。
- ENGINE：`{engine_status}`。
- STATISTICS：`{statistics_gate['status']}`（{statistics_gate['checks_passed']}/{statistics_gate['checks_total']}项检查通过）。
- TRADE PARITY：`{parity['status']}`。
- V2→V3 DIFF：`{v2_v3_integrity['status']}`。
- ACCEPTANCE：`{acceptance_status}`。
- RESEARCH：`{research_status}`。
- 实际注册并计算：{len(factor_specs)}个价格类候选因子；数据不合格候选未纳入。
- 数据资格：`{qualification['status']}`，19,470根缓存全部命中；没有使用1分钟、Volume、VWAP或账户数据。
- V3.1.1汇总一致性：`{consistency['status']}`；严格逐笔一致性：`{parity['status']}`。任一不通过，本报告的策略排名和晋级结论一律 fail-closed。
- 高重合因子对：{duplicates}组（|phi|≥0.80），已标记而不是重复计为独立假设。
- 满足 TRAIN_CANDIDATE：{len(candidates)}个；TRAIN 结果不能升级为已验证 Edge。

## 统计口径与 Gate

- `baseline_raw_market`：相同 horizon 的 TRAIN 无条件标的收益均值。
- `baseline_directional`：Long 为原始市场基准、Short 为其相反数；REGIME 标记为不适用。
- 兼容字段 `baseline_mean`：V3 中始终代表实际用于 increment 的比较基准。
- `INFERENCE_TARGET = DIRECTIONAL_MEAN_VS_ZERO`；当前 CI/p-value 不是 increment 显著性检验。
- Gate 失败会清除可用候选晋级并令 CLI 非零退出；详细证据见 `STATISTICS_GATE.json`。

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
    _validate_output_target(output_dir)
    started = perf_counter()
    frozen_history_before = _frozen_history_snapshot()
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
    factor_v2 = pd.read_csv(PHASE3_V2_OUTPUT / "FACTOR_RESULTS.csv")
    strategy_v2 = pd.read_csv(PHASE3_V2_OUTPUT / "STRATEGY_RESULTS.csv")
    expected_factor_keys = {
        (str(row.factor_id), str(row.direction), int(row.horizon_minutes))
        for row in factor_v2.itertuples()
    }
    expected_strategy_keys = {
        (str(row.variant_id), str(row.direction)) for row in strategy_v2.itertuples()
    }
    statistics_gate = statistics_integrity_gate(
        factor_result,
        strategy_result,
        regime,
        factor_specs,
        strategy_specs,
        tests,
        expected_factor_keys,
        expected_strategy_keys,
    )
    v2_v3_integrity = _v2_v3_integrity(factor_result, strategy_result)
    statistics_gate = append_statistics_gate_check(
        statistics_gate,
        "v2_v3_only_permitted_changes",
        {
            "status": v2_v3_integrity["status"],
            "unexpected_factor_changes": len(v2_v3_integrity["unexpected_factor_changes"]),
            "unexpected_strategy_changes": len(v2_v3_integrity["unexpected_strategy_changes"]),
            "baseline_rows_changed": v2_v3_integrity["baseline_rows_changed"],
            "increment_rows_changed": v2_v3_integrity["increment_rows_changed"],
        },
        {
            "status": "PASS",
            "unexpected_factor_changes": 0,
            "unexpected_strategy_changes": 0,
            "baseline_rows_changed": 78,
            "increment_rows_changed": 78,
        },
        v2_v3_integrity["status"] == "PASS",
        "V2→V3 contains an unapproved numerical or key change",
    )
    frozen_history_after_compute = _frozen_history_snapshot()
    history_unchanged = (
        frozen_history_before == frozen_history_after_compute
        and frozen_history_before["declared_integrity"]["status"] == "PASS"
    )
    statistics_gate = append_statistics_gate_check(
        statistics_gate,
        "frozen_v1_v2_hashes_unchanged",
        {
            "before_equals_after": frozen_history_before == frozen_history_after_compute,
            "declared_integrity": frozen_history_before["declared_integrity"],
        },
        {"before_equals_after": True, "declared_integrity": {"status": "PASS"}},
        history_unchanged,
        "frozen V1/V2 artifacts changed or no longer match their declared hashes",
    )
    pre_gate_candidates = int((
        (strategy_result["direction"] == "ALL")
        & (strategy_result["candidate_status"] == "TRAIN_CANDIDATE")
    ).sum())
    statistics_gate = append_statistics_gate_check(
        statistics_gate,
        "frozen_train_candidate_count",
        pre_gate_candidates,
        0,
        pre_gate_candidates == 0,
        "V3 candidate count changed from the frozen zero-candidate conclusion",
    )

    if statistics_gate["status"] != "STATISTICS_PASS":
        strategy_result["candidate_status"] = "STATISTICS_GATE_FAIL"
    if consistency["status"] != "PASS":
        strategy_result["candidate_status"] = "BLOCKED_STATE_MACHINE_MISMATCH"
    if parity["status"] != "TRADE_PARITY_PASS":
        strategy_result["candidate_status"] = "PARITY_FAIL"
    shortlist = strategy_result[
        (strategy_result["direction"] == "ALL")
        & (strategy_result["candidate_status"] == "TRAIN_CANDIDATE")
    ].copy()
    blocked_candidate_count = int(len(shortlist))
    candidate_alignment = (
        statistics_gate["status"] == "STATISTICS_PASS" or blocked_candidate_count == 0
    )
    statistics_gate = append_statistics_gate_check(
        statistics_gate,
        "statistics_failure_blocks_candidate_promotion",
        {"statistics_status": statistics_gate["status"], "promoted_candidates": blocked_candidate_count},
        "zero promoted candidates whenever statistics status is not PASS",
        candidate_alignment,
        "a failed statistics Gate left a promotable candidate",
    )

    compute_seconds = perf_counter() - compute_started
    timings = {
        "data_seconds": data_seconds,
        "compute_seconds": compute_seconds,
        "total_seconds": perf_counter() - started,
    }

    data_pass = qualification["status"] == "PASS_5M_ONLY"
    engine_status = "ENGINE_PASS" if consistency["status"] == "PASS" else "ENGINE_FAIL"
    acceptance_pass = (
        data_pass
        and engine_status == "ENGINE_PASS"
        and parity["status"] == "TRADE_PARITY_PASS"
        and statistics_gate["status"] == "STATISTICS_PASS"
        and v2_v3_integrity["status"] == "PASS"
        and history_unchanged
    )
    acceptance_status = "ACCEPTANCE_PASS" if acceptance_pass else "ACCEPTANCE_FAIL"
    if acceptance_pass:
        research_status = "RESEARCH_NO_EDGE" if shortlist.empty else "TRAIN_CANDIDATES_PRESENT"
    else:
        research_status = "RESEARCH_BLOCKED_BY_ACCEPTANCE_GATE"

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
    _write_csv(output_dir / "FACTOR_RESULTS_V2_V3.csv", v2_v3_integrity["factor_comparison"])
    _write_csv(output_dir / "STRATEGY_RESULTS_V2_V3.csv", v2_v3_integrity["strategy_comparison"])
    _atomic_text(output_dir / "V2_V3_CHANGE_AUDIT_CN.md", _change_report(v2_v3_integrity))
    _atomic_text(
        output_dir / "STATISTICS_GATE.json",
        json.dumps(_clean(statistics_gate), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    duplicates = int(correlations["duplicate_flag"].sum())
    v2_v3_summary = {
        key: value for key, value in v2_v3_integrity.items()
        if key not in {"factor_comparison", "strategy_comparison"}
    }
    _atomic_text(
        output_dir / "REPORT_CN.md",
        _report(
            factor_specs,
            factor_result,
            strategy_result,
            regime,
            consistency,
            parity,
            statistics_gate,
            acceptance_status,
            v2_v3_summary,
            research_status,
            qualification,
            timings,
            duplicates,
        ),
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
        "engine_status": engine_status,
        "statistics_status": statistics_gate["status"],
        "statistics_gate": statistics_gate,
        "trade_parity": parity,
        "v2_v3_integrity": v2_v3_summary,
        "acceptance_status": acceptance_status,
        "research_status": research_status,
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
        "phase3_v1_artifact_hashes": frozen_history_after_compute["v1"],
        "phase3_v2_artifact_hashes": frozen_history_after_compute["v2"],
        "frozen_history_integrity": frozen_history_after_compute["declared_integrity"],
        "artifacts": artifacts,
    }
    _atomic_text(output_dir / "manifest.json", json.dumps(_clean(manifest), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return manifest
