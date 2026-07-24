---
name: quant-research-pipeline
description: Run the fixed local quant research workflow from validated strategy configuration through data checks, EMA baseline, benchmark, audit, and Chinese report.
---

# quant-research-pipeline

只调用固定 pipeline CLI，按 Stage 0 至 Stage 7 顺序运行；失败或 blocker 状态停止后续阶段。
