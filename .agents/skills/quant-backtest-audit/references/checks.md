# Backtest Audit Checks

| Check | Required evidence | Failure or warning code |
| --- | --- | --- |
| Data quality | Standardized UTC OHLCV rows validated by `validate_ohlcv` | `DATA_QUALITY_FAILURE` |
| Next-bar fills | UTC signal and fill timestamps; every fill is strictly later | `SAME_BAR_SIGNAL_FILL` |
| Costs | Trade gross notional, commission, slippage bps, and configured bps | `COST_MISMATCH` |
| Benchmark fairness | Benchmark return plus matching symbol, timeframe, dates, commission, and slippage | `BENCHMARK_MISMATCH` |
| Optimization | Strategy specification and manifest both set `optimization_allowed: false` | `OPTIMIZATION_ENABLED` |
| Manifest | Non-empty config hash, data hash, code commit, fill timing, cost rates, and UTC generation time | `MISSING_MANIFEST_FIELD` |
| Artifacts | Any supplied summary, equity, trades, manifest, or audit path exists as a file | `MISSING_ARTIFACT` |
| Sample | Fill records | `NO_TRADES` |
| Closed-trade concentration | Paired buy/sell cash flows | `SINGLE_TRADE_DOMINANCE` |
| Annual concentration | Timestamped equity rows and positive annual equity growth | `ANNUAL_RETURN_CONCENTRATION` |
| Reproducibility | Non-empty input hashes and, when supplied, a hashable `data_path` matching `data_hash` | `MISSING_MANIFEST_FIELD`, `HASH_MISMATCH` |
