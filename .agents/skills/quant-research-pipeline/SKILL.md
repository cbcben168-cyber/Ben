---
name: quant-research-pipeline
description: Run or re-audit the fixed local Phase 1 SPY/QQQ research workflow from a validated strategy YAML through cache-first daily data, EMA50/EMA200 backtest, Buy and Hold benchmark, deterministic audit, manifest, and Chinese report.
---

# quant-research-pipeline

调用 `tv_quant.research_pipeline.run_pipeline`，严格按 Stage 0 至 Stage 7
执行。遇到策略能力阻断、数据质量失败、数据能力阻断或审计失败时立即停止，
不得把失败包装成成功。

## 执行边界

- 始终先调用 `load_strategy_spec` 和 `check_capabilities`。
- 始终执行数据验证；不得跳过、弱化或在报告中代替确定性校验。
- 始终优先使用已验证的本地缓存；不得静默下载重复缓存数据。
- 仅在显式启用 `allow_smoke_test_data` 且配置数据源为 `yfinance` 时使用
  `SMOKE_TEST_DATA_ONLY` 标记。
- 默认且始终保持 `optimization_allowed: false`；不得自动优化或只报告最优参数。
- 仅调用既有确定性回测、指标、基准、报告和审计接口；不得在文字中重新计算绩效。
- 保持 UTC、`next_bar`、手续费、滑点和 Buy and Hold 对比证据。
- 绝不调用账户、券商、真实订单、TradingView Webhook 或任何下单路径。
- 不得扩展到期权、Phase 2 或网络默认刷新。

## 模式

- 标准运行：提供策略 YAML 和 `PipelineOptions`；缺少完整本地缓存时，仅通过调用方
  显式传入的 `refresh_data` 回调刷新。
- 仅审计：设置 `audit_only=True` 并提供已有 `run_directory`；重新验证 manifest
  数据哈希并只重写 `audit.json`，不得刷新数据或重跑绩效计算。

执行前读取 [references/stages.md](references/stages.md)；检查运行证据时读取
[references/run-record.md](references/run-record.md)。
