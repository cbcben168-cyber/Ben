---
name: quant-strategy-spec
description: Convert Chinese trading rules into validated YAML and block unsupported capabilities before data access or backtesting.
---

# quant-strategy-spec

读取用户的自然语言策略规则，生成符合 20 字段 schema 的 YAML 配置，并在任何数据访问前完成确定性验证。

## 工作契约

1. 先读取自然语言策略文本。缺少 symbol、timeframe、起止日期、初始资金、entry、exit、成本或成交假设时，必须询问用户，不能猜测。
2. 参考 [config-schema.md](references/config-schema.md) 生成 YAML；参考 [capability-matrix.md](references/capability-matrix.md) 判断当前阶段能力。
3. 对生成的 mapping 调用 `validate_strategy_mapping`，将 YAML 写入配置路径后调用 `load_strategy_spec`，再调用 `check_capabilities`。
4. 能力检查成功时，只返回已验证的 YAML 配置路径和简短假设摘要，包括标的、周期、日期、资金、规则、成本、成交时点和 benchmark。
5. 校验失败或能力不支持时，只返回 `STRATEGY_CAPABILITY_BLOCKER` 或 `DATA_CAPABILITY_BLOCKER`、原因和下一步请求；不得继续访问数据或运行下游流程。

默认值为：`optimization_allowed: false`、`report_language: zh-CN`、`benchmark: Buy and Hold`、`fill_timing: next_bar`、`data_source: validated_local_cache_first`。配置中的 benchmark 以 Python schema 的规范值 `buy_and_hold` 保存。

## 非执行边界

本 Skill 不下载数据、不运行回测、不发送订单，也不调用 broker、TradingView execution 或未固定版本的用户级 Skill。它只负责策略文本、YAML 配置、Python 校验和 capability blocker；不得刷新数据、计算交易绩效或触发真实账户动作。
