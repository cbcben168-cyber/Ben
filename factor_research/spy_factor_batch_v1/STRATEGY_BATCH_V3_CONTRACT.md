# FUTU_FACTOR_STRATEGY_V3 CSV 数据合同

合同版本 `3.0`，日志标记 `FUTU_FACTOR_STRATEGY_V3|`，策略版本 `FUTU_C1_STRATEGY_BATCH_TRAIN_V3`。

每条事件都必须带 `batch_id/run_id/strategy_version/strategy_hash/parameter_version/symbol/timeframe/bar_type/select/session/timezone`。全文件身份字段必须一致；`strategy_hash` 为代码规范化 SHA256。原始 CSV 字节与 SHA256 永久保留。

事件：

- `RUN_START`：TRAIN 日期、系统预热、187 日、因子与策略目录、定义哈希、参数尝试次数、成本、禁止交易声明。
- `TEST_REGISTRY`：检验 ID、层级、检验族大小、聚类单位和多重比较方法。
- `SIGNAL_EVENT`：F007–F011 或 S01 基准信号、方向、事件单位、信号时间与价格、15/30/60 分钟收益及当时 Regime。F012 每个合格时点记录状态事件，既提供同口径市场基准，也不冒充方向信号。
- `TRADE_EVENT`：信号与下一根开盘、方向、止损/目标/退出、总收益、成本、净收益、MFE/MAE、先触发结果、模糊路径与目标优先敏感性、F001–F006 过滤位。
- `DAY_END`：当日信号、交易、未决对象、错误及 COMPLETE/INCOMPLETE。
- `RUN_END`：187 日总计、错误和最终状态。
- `ERROR`：机器错误码和可审计详情。

导入规则：恰好一个 RUN_START 和 RUN_END；生产日志固定 TRAIN 范围与 187 个 COMPLETE DAY_END；不得有 ERROR、跨日未决对象、重复 ID、非下一根开盘入场、非有限数值或身份漂移。任一失败整批回滚。fixture 仅允许隔离测试库且可缩小交易日数。

同一根 5 分钟 K 线同时触及止损与目标时，`ambiguous=true`，主结果固定 `primary_path=STOP_FIRST`；必须同时保存 `target_first_net_return`。不同事件单位在看板分区展示，禁止按原始样本数或平均收益直接混排。

### 富途参数表

| 项目 | 值 |
|---|---|
| 策略文件 | `SPY_C1_STRATEGY_BATCH_TRAIN_V3.py` |
| 标的 | `US.SPY` |
| 系统回测起点 | 2025-07-01 |
| 正式 TRAIN | 2025-10-01 至 2026-06-30 |
| 行情驱动 | 1 分钟 |
| 研究 K 线 | 已完成 5m，RTH，`select=2` |
| 复权 | 与第一批 TRAIN 完全相同；保留富途参数截图，不得临时切换 |
| 提前收市 | 2025-11-28、2025-12-24 |
| 订单/账户/持仓 | 禁止 |
| Volume/VWAP | 禁止 |
| 输出 | 一次 RunLog CSV |
