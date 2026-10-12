# 数据资格报告

## 结论

- 数据 Gate：`PASS_5M_ONLY`。
- 状态机一致性：`PASS`。
- 仅允许5分钟研究；1分钟状态为 `NOT_AVAILABLE_NOT_REQUIRED`。
- Volume/VWAP：`PROHIBITED`。

## 缓存身份与覆盖

- US.SPY 5分钟 RTH：2025-07-01 至 2026-06-30。
- 共 19,470 根、251 个交易日；TRAIN 14,514 根、187 日。
- 时区及标签：`America/New_York`，`bar_end`。
- 半日市：2025-07-03, 2025-11-28, 2025-12-24。
- 动态前复权事件：2025-09-19, 2025-12-19, 2026-03-20, 2026-06-18。
- 缓存命中：`True`，未重新下载全年数据。
- OHLC SHA256：`e5e3ab7cfa981be022388b7a54952a6f8fa29e2dc0043672edf4e84997940e2f`。
- 审计 manifest SHA256：`f1f750867dd4a32eaf74d4d776dcf47002f0aa7f5b123db4177e57c4a1a266da`。
- 复权表 SHA256：`16a1bae16d562edffac364cbba2a6a26d72765e1eca57ab0c31189b37ceb17c4`；四组复权系数逐项冻结并校验。

## 冻结复权系数

- 2025-09-19：factor_a=0.99723，factor_b=0.0，per_cash_div=1.83111。
- 2025-12-19：factor_a=0.99705，factor_b=0.0，per_cash_div=1.99337。
- 2026-03-20：factor_a=0.99727，factor_b=0.0，per_cash_div=1.797。
- 2026-06-18：factor_a=0.99743，factor_b=0.0，per_cash_div=1.90352。

## 限制

当前没有合格1分钟缓存，因此止损与目标在同一5分钟K线内同时触发时采用止损优先，并保存目标优先敏感性；不得解释为真实市场撮合顺序。
