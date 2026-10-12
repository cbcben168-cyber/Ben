# C1 Phase 3 研究计划（冻结版）

- 引擎：`C1_PHASE3_EDGE_ENGINE_V3`
- 候选因子：36；不是阈值穷举，定义见 `FACTOR_REGISTRY.csv`。
- 策略版本：9；包含冻结 S01–S03 基准及每个基准两个预注册单因子过滤版本。
- 数据：US.SPY、已完成5分钟RTH OHLC；TRAIN 2025-10-01至2026-06-30。
- 输入限制：禁止 Volume、RVOL、VWAP、账户、订单、持仓接口；1分钟数据未通过资格，不宣称严格1分钟路径。
- 成交：下一根5分钟开盘；止损优先处理同柱双触发；过滤版本独立重演持仓并重新接纳原 POSITION_BUSY 机会。
- 成本：主口径往返4bp，敏感性2bp和6bp。
- 统计：交易日聚类 bootstrap 2000 次；同一检验族 max-|t| 同时区间与 Holm 调整。
- 统计估计量：每笔交易/事件等权；每次 bootstrap 抽取完整交易日后重新计算该估计量；同一检验族共用交易日索引。
- 因子基准：Long 使用原始市场基准，Short 使用取反后的方向化市场基准，REGIME 使用原始市场基准。
- 推断目标：`DIRECTIONAL_MEAN_VS_ZERO`；现有 CI/p-value 不用于检验 increment。
- 统计验收：`STATISTICS_PASS` 只能由 `STATISTICS_GATE.json` 的全部确定性检查共同产生。
- 重演资格：必须通过冻结真实 V3.1.1 RunLog 的逐信号、逐决策、逐交易严格比对，否则 `PARITY_FAIL`。
- 研究偏差：本 TRAIN 已多次用于研究，所有新结果均为 `EXPLORATORY_SAME_TRAIN_SAMPLE`，不能构成独立 Edge、Validation 或 OOS 证据。
- 晋级：允许零候选；只有样本、同时区间、PF、月度稳定性和集中度全部通过才可标记 `TRAIN_CANDIDATE`。
