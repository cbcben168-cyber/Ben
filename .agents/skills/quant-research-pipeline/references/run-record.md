# Run record

每次标准运行必须保留以下证据：

- 策略配置及 `strategy_config_hash`
- 假设与固定 EMA50/EMA200 参数
- provider、symbol、timeframe、start_date、end_date
- 原始数据路径及 `data_hash`
- `code_commit`
- `fill_timing`
- `commission_bps` 与 `slippage_bps`
- 策略指标：total return、CAGR、max drawdown、Sharpe、trade count、win rate
- Buy and Hold 指标与策略相对 Buy and Hold 的差值
- audit status、checks、issues 与 warnings
- 所有 summary、equity、trades、manifest、audit artifact 路径
- summary、equity、trades、manifest 与 audit payload 的 SHA256 证据
- 仅在适用时记录 `SMOKE_TEST_DATA_ONLY` marker

运行记录只保存确定性接口产生的数值。不得由 Codex 或其他 LLM 在说明文字中重新计算
收益、回撤、手续费、滑点或基准差异。

仅审计模式必须读取 `summary.json`、`equity.csv`、`trades.csv`、
`run_manifest.json` 和 `audit.json`，先验证 audit payload 与 manifest 哈希，
再验证数据文件及 summary、equity、trades 的哈希，然后仅重写 `audit.json`。
