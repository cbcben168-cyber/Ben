# C1 TRAIN V1 EMA补充审计

## 结论

- 补充审计：`SUPPORTED`
- 原始运行状态保持：`INCOMPLETE`
- Dashboard直接升级：`PROHIBITED`
- Edge结论：`PROHIBITED`
- 原始CSV SHA256：`bda31dddd8fc878663ce6827f11cb336ab4508c0fe0459259d88e321827af742`

本报告只补充验证EMA数据资格，不改写原始CSV、`WARMUP_AUDIT`、`RUN_END`、数据库或Gate状态。

## 原始运行

- 原始预热柱：4892；预期：4956。
- 原始预热状态：`INCOMPLETE`。
- 原始RUN_END：`INCOMPLETE`。
- ERROR：WARMUP_INCOMPLETE。
- 共享事件/标签：12083 / 36249。

## OpenD只读证据

- US.SPY、5分钟、RTH、`extended_time=False`、历史价格`AuType.NONE`。
- 时间戳：America/New_York柱结束时间。
- 系统区间：251个交易日、19470根K线。
- 预热区间：64个交易日、4956根K线。
- 预热最后柱：13:00共1日，16:00共63日。
- RTH标签范围外：0根。

## 价格与select身份

- 信号价：12083条，误差超1e-8为0，最大绝对误差0。
- 目标价：36249条，误差超1e-8为0，最大绝对误差0。
- 09:35 `select=2`：187日，身份误差0。
- 09:35 `select=3`：按当日除权因子还原上一交易日最后一根，身份误差0。

## EMA递推

- OpenD NONE价格加`get_rehab()`逐日动态前复权后，长线EMA最大误差：4.99983343616e-09。
- 短线EMA最大误差：4.99983343616e-09。
- 修正递推与平台F001/F002/F003状态差异：{"f001": 0, "f002": 0, "f003": 0}。
- 每日删除最后一根柱的重建与原日志长线EMA最大误差：5.00222085975e-11。
- 每日删除最后一根柱的重建与原日志短线EMA最大误差：5.00222085975e-11。

## 限制

本报告证明现有TRAIN事件、标签、平台EMA及因子状态可以独立重建；它不把原始`INCOMPLETE`改成`VALIDATED`，不允许进入Validation/OOS，也不构成Edge证据。
