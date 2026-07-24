---
name: quant-backtest-audit
description: Audit deterministic backtest evidence for timing, costs, data quality, benchmark fairness, hashes, reproducibility, and capability limits.
---

<!-- Task 5 references: references/checks.md and references/statuses.md. -->

# quant-backtest-audit

Inspect deterministic backtest artifacts, trade fills, equity, configuration,
manifest evidence, and locked OOS boundaries. Produce only audit status; never
place orders, recalculate performance with an LLM, optimize parameters, or
imply live-trading permission.

Read `references/checks.md` for required evidence and issue codes, then use
`references/statuses.md` to interpret the resulting status.

读取运行清单、交易明细、权益曲线和配置，输出五种审计状态；不执行交易。
