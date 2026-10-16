# Factor Scout V1 Phase A 人工筛选报告

- 证据等级：`SYNTHETIC_DEMO`
- 运行ID：`FACTOR_SCOUT_V1_PHASE_A_SYNTHETIC_DEMO_V1`
- 人工OHLC SHA256：`7d576a8170c641f47ff9d5f00018308979b87d6587fe5b098fcb9e6d1467c60a`
- 因子范围：F01, F02, F03, F04, F05, F06
- 静态状态：REVIEW=4，WATCH=2，BLOCKED=0

## 分类别功能结果

以下数值仅用于核对计算链；方向类单位为bp，波动率/状态类为非年化实现波动率。不同类别不得混排。

### DIRECTION

- F06：events=23，eligible=26，forward_mean=8.715932，`SYNTHETIC_DEMO`
- F01：events=5，eligible=5，forward_mean=5.820432，`SYNTHETIC_DEMO`
- F03：events=22，eligible=26，forward_mean=5.783361，`SYNTHETIC_DEMO`

### VOLATILITY

- F02：events=4，eligible=5，forward_mean=0.000525，`SYNTHETIC_DEMO`

### STATE

- F04：events=22，eligible=25，forward_mean=3.847433，`SYNTHETIC_DEMO`
- F05：events=3，eligible=4，forward_mean=0.002035，`SYNTHETIC_DEMO`

## 限制与下一阶段门

本次只有人工OHLC，筛选结果属于探索性功能观察，不能证明交易Edge；没有读取真实TRAIN、Validation/OOS，也没有计算订单、期权PnL或资金曲线。

如需Phase B，必须另行明确授权真实TRAIN数据路径/读取方式、日期、Stage、Run ID和输出目录。

本报告未产生任何验证Edge、样本外通过或实盘就绪结论。
