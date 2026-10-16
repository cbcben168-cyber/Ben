# Factor Scout V1 TRAIN探索筛选报告

- 运行ID：`FACTOR_SCOUT_V1_TRAIN_SCREEN_20261016_01`
- Stage：`TRAIN_EXPLORATORY_SCREEN_ONLY`
- 证据等级：`EXPLORATORY_SCREEN_ONLY`
- PIT状态：`PIT_APPROXIMATION_UNVERIFIED`；禁止确认性用途。
- 数据：US.SPY，XNYS RTH，5分钟，2025-10-01 至 2026-06-30。
- 分类：KEEP=1，容量观察=1，不稳定=4，重叠=0。

## 六因子结果

### DIRECTION

- F01：events=55，days=55，lift=1.183951，`WATCH_UNSTABLE`；总体或60/40探索分段未保持同向正增量。
- F03：events=19，days=19，lift=-4.583815，`WATCH_CAPACITY`；低于50事件或40独立日的深测排期提示。
- F06：events=110，days=110，lift=0.594790，`WATCH_UNSTABLE`；总体或60/40探索分段未保持同向正增量。

### VOLATILITY

- F02：events=90，days=90，lift=0.000514，`KEEP_FOR_DEEP_TEST`；容量、同Anchor增量及60/40方向满足预先固定的探索排期规则。

### STATE

- F04：events=98，days=98，lift=-1.365720，`WATCH_UNSTABLE`；总体或60/40探索分段未保持同向正增量。
- F05：events=89，days=89，lift=-0.000102，`WATCH_UNSTABLE`；总体或60/40探索分段未保持同向正增量。

## 限制

本次仅为TRAIN内部探索筛选；60/40两段均非OOS。复权事件缺少历史available_at证据，按effective date近似并保留PIT_APPROXIMATION_UNVERIFIED。未访问Validation/OOS、账户、持仓或订单。

结果不构成Edge确认、交易策略回测、OOS通过或实盘就绪结论。
