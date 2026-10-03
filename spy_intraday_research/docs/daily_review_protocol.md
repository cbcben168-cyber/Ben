# 每日 forward test 复盘与优化选择机制

版本：1.0。适用于未来获批启动的 shadow / broker paper；当前只定义输出契约和模板，不启动调度、订阅或订单。

## 触发与完成条件

每个纽约交易日正式收盘后，先完成订单、成交、SPY持仓对账，再生成日报。半日市按交易日历实际收盘。即使无信号、无成交、断连或对账失败也必须生成对应状态的日报，不能跳过亏损或失败日期。

日报唯一键：session_date + frozen_strategy_version + mode。历史修订增加report_revision，不覆盖旧报告；同一数据hash和版本重复运行应产生相同数值。报告包含生成时间、run_id、代码/配置/数据hash和成交来源。数据未齐时标PARTIAL；对账未完成时标FAILED_EXECUTION，不能用零收益替代未知收益。

未来paper模块每个session结束调用report生成器；调度时区、运行机器、重试和通知渠道在paper实施阶段明确。日报可由用户随时手动查看；外发消息及无人值守调度另行授权。

## 必须回答的内容

1. 当日与累计：信号/可交易/成交/取消/拒单数量、gross/net PnL、费用、滑点、fill ratio、持仓、风险触发、MFE/MAE和相对冻结模型的偏差。shadow假想成交和broker实际模拟成交分开。
2. 质量与执行：缺bar、行情延迟、订单超时、重复意图、部分成交、未解释持仓。先解释运行故障，不把故障当作strategy edge失败。
3. 累计证据：冻结版本开始日期、合格session/交易数、净均值、日期聚类bootstrap CI、成本和市场状态分布。累计不足或CI不可估时明确INSUFFICIENT，不填假数值。
4. 归因：数据、执行、策略假设、正常波动/无法判断。观察与推测分别标注；单日不做统计显著性声明。
5. 最多三个优化选项，并包含“保持当前版本、继续收集”作为默认建议。每个选项给出证据窗口、触发问题、假设、精确修改范围、预期作用（不是保证）、风险、需要的新数据、试验预算、验证/停止标准和权限范围。

若没有可靠优化证据，可以只给保持不变这一项。禁止为了每天有建议而不断添加指标或优化TP/SL；TP/SL仍须先通过edge gate。

## 优化闭环与状态

`PROPOSED → SELECTED → APPROVED → IMPLEMENTED → SHADOW_VALIDATING → REVIEW_READY → PROMOTED / REJECTED`。

- 用户选择选项只是选定方向；在给出明确文件范围、验证方法、分支和PR方案后，用户明确“批准”才允许修改。若用户在同一条消息已明确批准具体选项及范围，不重复索要同一许可。
- 每个建议关联proposal_id、parent_version、evidence_run_ids和report_revision；无法识别所选版本时先澄清，不猜测。
- 新版本进入独立候选分支；当前冻结forward版本持续保持。只读数据/运行安全暂停与修复也须记录，涉及代码修改遵守审批。
- 新候选不得拿已被查看的paper历史当独立OOS；可用它诊断并回测，但必须预登记新的未来shadow比较窗口和成功标准。
- v1默认新候选验证至少20个新session且50个合格事件；此门槛仅用于初步比较，正式替换仍必须满足主规格中的OOS/paper和风险门槛，不能缩短到当天表现好即替换。
- 对照与候选使用同一未来时段、数据与成本，按日期聚类报告差异CI；统计不足则继续验证或拒绝，不挑最赚钱的停止时点。
- REVIEW_READY仅表示证据已可审阅。替换运行版本、重新部署、改变订单风险或转实盘须用户另行明确批准；不自动PROMOTE。
- 所有失败、拒绝、撤销建议保留。试验纳入research registry和多重检验族；不通过每天产生新版本规避试验预算。

## 输出契约

路径：`artifacts/paper/<version>/<session_date>/review_<revision>/`。

- `daily_review.md`：使用daily_review_template.md生成。
- `daily_metrics.csv`：session_date,version,mode,report_revision,run_id,signals,eligible_events,fills,rejections,cancellations,gross_pnl_usd,fees_usd,slippage_usd,net_pnl_usd,fill_ratio,mfe_bps_mean,mae_bps_mean,open_position_qty,reconciliation_status,data_status。
- `cumulative_metrics.csv`：version,mode,start_date,end_date,qualified_sessions,completed_trades,net_mean_bps,ci_low_bps,ci_high_bps,seed,cost_model_hash,sample_status。
- `optimization_options.csv`：proposal_id,parent_version,option_id,hypothesis,evidence_run_ids,change_scope,expected_effect,risk,validation_plan,stop_rule,requires_approval,status。
- `optimization_decisions.csv`：decision_id,proposal_id,option_id,parent_version,candidate_version,user_selection_at,user_approval_at,approved_scope,branch,commit,validation_run_ids,status,promotion_approval_at。审批证据引用本地受控记录，不保存凭据或无关个人信息。
- `review_manifest.json`：输入/输出hash、生成器版本、运行状态、缺失字段原因、版本身份。

PnL与滑点避免重复扣减：实际成交价已包含执行滑点时，slippage仅用于归因，不再从actual-fill PnL额外扣一次。持仓未平时realized/unrealized分开，不能把未知估值当零。模板中的NA必须注明原因。

## paper实施阶段的必要验证

验证无交易日、亏损日、半日市、断连、未平仓、部分成交、迟到数据修订和幂等重跑都产生日报；数值能逐笔对账；不同版本不混算；建议不会更改运行策略；没有审批不能实施或PROMOTE；未来比较窗口不使用已消耗样本。此阶段尚无可运行report命令，不把模板误报成已自动化功能。
