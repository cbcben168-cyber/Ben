# Capability Matrix

| Request | Status | Data access | Backtest access |
|---|---|---|---|
| SPY/QQQ fixed EMA50/EMA200, 1d | SUPPORTED | Continue to local-cache check | Allowed |
| RSI or MACD | STRATEGY_CAPABILITY_BLOCKER | Stop | Not called |
| 30m/60m or multi-symbol | STRATEGY_CAPABILITY_BLOCKER | Stop | Not called |
| yfinance without smoke flag | DATA_CAPABILITY_BLOCKER | Stop | Not called |
| yfinance with smoke flag | SUPPORTED | Smoke-test data only; never formal validated data | Allowed |
| Missing local cache | DATA_CAPABILITY_BLOCKER | Stop after cache check | Not called |
| IBKR, LEAN, TradingView execution | STRATEGY_CAPABILITY_BLOCKER | Stop | Not called |
| Options or option-chain request | DATA_CAPABILITY_BLOCKER | Stop | Not called |
| optimization_allowed=true | STRATEGY_CAPABILITY_BLOCKER | Stop | Not called |
| Order or live-account request | STRATEGY_CAPABILITY_BLOCKER | Stop | Not called |
