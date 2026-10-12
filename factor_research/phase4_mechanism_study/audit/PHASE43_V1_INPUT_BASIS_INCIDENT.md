# Phase 4.3 V1 输入价格基础事故记录

## 裁定

- 发现日期：2026-10-13。
- 审计来源：用户提供的独立审计结论；Codex 在指定工作树执行只读复核。
- 固定状态：`P4_TRAIN_V1 = INVALID_INPUT_BASIS`。
- 验收状态：`ENGINE_ACCEPTANCE = BLOCKED`。
- 失败类型：`ACTUAL_INTEGRITY_FAILURE — ADJUSTMENT_BASIS_MISMATCH`。
- 候选晋级：禁止。V1 不能用于候选晋级、Validation、OOS、Forward 或交易决策。

本记录是对既有研究可信度的后续裁定。它不修改、覆盖或重写 V1 原始 attempt 日志、注册、manifest、结果或执行时状态。

## 错误源码位置

`factor_research/phase4_mechanism_study/structural_preflight.py`：

- `_read_train_only()` 在第 143–167 行读取 `AuType.NONE` 原始 OHLC。
- 第 166 行直接写入 `adjustment_basis = AS_OF_DYNAMIC_FORWARD_FROM_GET_REHAB`。
- `qualify_authorized_train()` 第 170–226 行只校验原始 OHLC、audit manifest、rehab 文件哈希及合同字符串，然后把未经数值变换的 OHLC 交给 `qualify_ohlc()`。
- 该路径没有对 Open、High、Low、Close 应用 `factor_a * price + factor_b`，却把数据标记为动态前复权。

因此，V1 的 `DATA_GATE = PASS` 只证明文件身份和标签匹配，不证明价格已处于声明的复权基准。

## 冻结输入身份

| 输入 | SHA256 |
|---|---|
| `opend_5m_ohlc.csv` | `e5e3ab7cfa981be022388b7a54952a6f8fa29e2dc0043672edf4e84997940e2f` |
| `opend_rehab.csv` | `16a1bae16d562edffac364cbba2a6a26d72765e1eca57ab0c31189b37ceb17c4` |
| audit `manifest.json` | `f1f750867dd4a32eaf74d4d776dcf47002f0aa7f5b123db4177e57c4a1a266da` |

原始 OHLC 文件继续保持 `AuType.NONE` 身份，不得覆盖或改写。

## V1 执行与结果身份

| 证据 | SHA256 |
|---|---|
| `phase4_train_runner.py` | `c45b2454c192bb241cb93bf1f81a2310fceeec8de06573df49da0904fa3a692b` |
| `tests/test_phase4_train_runner.py` | `d65b46846ea8fb1be9a78fb47d86442f109419227662df44a670778f44168f4c` |
| `train_registration.json` | `c5fcf9bd290e500ec7dce9cc14a5818cbabc02d18063eb6830650736104237fb` |
| `synthetic_validation.json` | `039d816d2a4f0cc4d3ad9afe4888ebf3d1db9f3a9a79dae69ca15b91010079c8` |
| `registry/TRAIN_ATTEMPT_REGISTRY.csv` | `21b4f9b200bb8d0f06efeda9e267f00ed82e557636a65ea0569589904ac65b12` |
| `outputs/phase4_train_v1/manifest.json` | `682bf9f4cf4eb97bb1f20899b58659909d83c862a1e03df0f95ba55c7151bc49` |

V1 manifest 内登记的九项产物 SHA256 已逐项与磁盘文件复核一致。该一致性只证明 V1 证据未漂移，不修复错误输入价格基础。

## 2026-06-18 错误锚点

- 2026-06-17 原始收盘价：`740.96`。
- 2026-06-18 `forward_adj_factor_a`：`0.99743`。
- `forward_adj_factor_b`：`0.0`。
- 正确的同基准前收盘价：`740.96 × 0.99743 + 0 = 739.0557328`。
- V1 路径仍使用 `740.96`，因此 M06 的前收盘与 Gap 锚点不在同一复权基准。

## 影响范围

- `M01`：依赖 OHLC、日内 TR/ATR、入场/止损/目标价格；价格基础错误可能传播到触发与回放。
- `M02`：依赖 OHLC、区间宽度及 ATR；价格基础错误可能传播到压缩、突破与回放。
- `M06`：直接依赖前收盘、当日开盘和 Gap；2026-06-18 已有确定性错误锚点。
- 全部三个机制的交易数、收益、稳健性和统计 Gate 都建立在同一错误输入基础上，不能局部豁免。

## 为什么 V1 不能通过验收

V1 把 `AuType.NONE` 数值标记为动态前复权，却没有执行 rehab 数值变换。其数据身份声明与实际 OHLC 不一致，违反 fail-closed DATA_GATE 合同。因此：

- 原始 `PHASE4_3_TRAIN_COMPLETE` 和 `RESEARCH_NO_EDGE` 仅作为历史执行记录保存。
- V1 报告不能作为有效研究结论，也不能恢复为候选资格证据。
- 在独立数据修复、数值 Gate、Phase 3 交叉核验及完整测试验收前，保持 `PHASE4_3_1_BLOCKED`。
