# FUTU_FACTOR_STRATEGY_V3_1 CSV 数据合同

- marker：`FUTU_FACTOR_STRATEGY_V3_1|`
- contract：`3.1`
- strategy：`FUTU_C1_STRATEGY_BATCH_TRAIN_V3_1`
- parameter：`C1-STRATEGY-FIRST-TRAIN-V3.1`
- 参数尝试：2

V3.1保留V3全部身份字段和原始CSV SHA256。新增：

- `STRATEGY_SIGNAL_EVENT`：独立的可执行策略信号，不要求60分钟预测标签。
- `ENTRY_REJECTED`：`POSITION_BUSY`、`STOP_CROSSED_BEFORE_ENTRY`或`TARGET_CROSSED_BEFORE_ENTRY`。
- `TRADE_EVENT`：增加`entry_observed_at_et`、`entry_bar_end_et`、`exit_bar_end_et`、`exit_time_precision`、`initial_risk`和`reward_to_risk`。
- `RUN_END`：必须记录250根跨日补入末柱和4次复权状态调整。

时序必须满足：

1. `signal_time_et == entry_time_et`，表示信号柱结束与下一柱开始的同一边界。
2. `entry_observed_at_et == entry_bar_end_et == entry_time_et + 5分钟`。
3. 退出不得早于入场柱完成观察时点。

S01/S02的`reward_to_risk`必须为1.5；S03按冻结EMA20目标保存实际比率。跳空止损价不得优于该柱开盘。

TEST_REGISTRY必须精确登记30/6/12/24/6/36个检验；导入后必须实际生成114条统计结果，包含交易日聚类区间、max-|t|同时区间、Holm p值、覆盖率和样本资格状态。仅登记名称而未计算时整批不具备研究验收资格。

## 富途参数

| 项目 | 固定值 |
|---|---|
| 文件 | `SPY_C1_STRATEGY_BATCH_TRAIN_V3_1.py` |
| 标的 | `US.SPY` |
| 行情驱动 | 1分钟 |
| 研究K线 | 已完成5m RTH，`select=2` |
| 系统起点 | 2025-07-01 |
| TRAIN | 2025-10-01至2026-06-30 |
| 复权 | 与第一批TRAIN一致，并保留参数截图 |
| 订单、账户、持仓 | 禁止 |
| Volume/VWAP | 禁止 |
| 输出 | 一次RunLog CSV |
