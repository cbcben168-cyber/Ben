# Audit Statuses

- `PASS`: Formal baseline report is allowed. This never grants live-trading permission.
- `CONDITIONAL_PASS`: A conditional report is allowed; no optimization, promotion, or out-of-sample pass claim is allowed.
- `FAIL`: Stop the formal conclusion.
- `STRATEGY_CAPABILITY_BLOCKER`: Stop before data selection or backtest when the capability check blocks the strategy.
- `DATA_CAPABILITY_BLOCKER`: Stop before backtest when data selection produces the blocker.
