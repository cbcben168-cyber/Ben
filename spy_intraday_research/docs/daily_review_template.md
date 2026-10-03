# 每日 Forward Test 复盘 — {{session_date_et}}

状态：{{SUCCESS/PARTIAL/FAILED_EXECUTION/INSUFFICIENT}}
冻结版本：{{version}}｜模式：{{shadow/broker_paper}}｜修订：{{revision}}
证据：{{run_id/input_hash/code_sha/config_hash}}｜生成时间：{{generated_at_utc}}

## 当日结果

| 指标 | 当日 | 累计 | 来源/缺失原因 |
|---|---|---|---|
| 合格session/完成交易 | {{value}} | {{value}} | {{source}} |
| 信号/成交/拒单/取消 | {{value}} | {{value}} | {{source}} |
| 实现/未实现盈亏USD | {{value}} | {{value}} | {{source}} |
| 费用/滑点USD | {{value}} | {{value}} | {{source}} |
| 净期望bps与日期聚类95%CI | {{value_or_NA}} | {{value_or_NA}} | {{sample_status}} |
| MFE/MAE bps | {{value}} | {{value}} | {{source}} |

持仓与挂单核验：{{reconciliation}}。数据/执行异常：{{issues_or_none}}。

## 归因与证据

已观察：{{observations}}。尚未证实：{{hypotheses}}。相对冻结模型偏差：{{model_deviation}}。
累计样本是否达到门槛：{{sample_gate}}。不能从单日得出的结论：{{limitations}}。

## 优化选项（最多三个）

| 选项/Proposal ID | 依据与假设 | 修改范围 | 预期作用与风险 | 验证窗口/标准 | 建议 |
|---|---|---|---|---|---|
| A 保持不变/继续收集 | {{evidence}} | 无策略修改 | {{uncertainty}} | {{remaining_sample}} | 默认 |
| B {{optional}} | {{evidence}} | {{exact_scope}} | {{effect_and_risk}} | {{new_future_plan}} | {{recommendation}} |
| C {{optional}} | {{evidence}} | {{exact_scope}} | {{effect_and_risk}} | {{new_future_plan}} | {{recommendation}} |

用户选择：{{pending_or_option}}。获批范围：{{pending_or_scope}}。
当前版本保持冻结；候选实施和替换须分别满足授权与验证规则。
