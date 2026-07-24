# 固定 Stage 0–7

必须按以下八个外部步骤运行，不得重排或跳过：

0. Parse and normalize：调用 `load_strategy_spec` 解析并标准化策略 YAML。
1. Capability check：调用 `check_capabilities`；任何 blocker 立即停止。
2. Select data：按 `SYMBOL_daily.csv` 选择本地缓存；缺失或不完整时仅允许显式刷新回调。
3. Validate data：调用 `load_standardized_csv`，确认单一精确 ticker、UTC 日线、排序、
   无重复、价格完整且覆盖配置日期范围。
4. Run unoptimized backtest：调用固定 EMA50/EMA200 `run_backtest`，保持
   `next_bar`、手续费和滑点，不运行优化。
5. Run Buy and Hold benchmark：调用 `calculate_metrics` 和
   `buy_and_hold_return`，使用同一标的、日期、初始资金和成本。
6. Run audit：生成 manifest 和所需证据后调用 `audit_backtest`；审计失败不得返回成功。
7. Write Chinese report：通过 `write_reports` 保存确定性结果并写入最终审计状态；
   不在文字中重新计算最终绩效。

数据源规则：

- 完整且有效的本地缓存标记为 `Futu_LOCAL_CACHE`，且不得触发刷新。
- 只有配置 `data_source: yfinance` 且显式允许 smoke-test 时，刷新结果才标记为
  `SMOKE_TEST_DATA_ONLY`。
- 默认禁止网络；本模块不得直接调用 Futu、yfinance、券商、账户、订单或
  TradingView 接口。
