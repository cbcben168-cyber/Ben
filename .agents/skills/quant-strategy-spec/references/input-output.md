# Strategy specification input and output

本 reference 描述自然语言策略到 YAML 配置的最小输入输出形状。完整的 20 字段约束见 [config-schema.md](config-schema.md)，能力判断见 [capability-matrix.md](capability-matrix.md)。

## Supported EMA example

下面是固定 EMA 规则的有效策略规则示例；生成最终配置时仍须补齐 schema 要求的标的、日期、资金、仓位、成本和其他字段。

```yaml
strategy_name: ema_baseline
symbol: SPY
timeframe: 1d
entry_rules:
  - type: ema_crossover
    fast_period: 50
    slow_period: 200
exit_rules:
  - type: ema_crossunder
fill_timing: next_bar
optimization_allowed: false
```

## Unsupported RSI response

遇到当前引擎未支持的 RSI 规则时，不得把它近似成 EMA，也不得访问数据或运行回测。返回紧凑 blocker：

```text
STRATEGY_CAPABILITY_BLOCKER
unsupported_rule: RSI(2) < 10
reason: current engine supports only fixed EMA50/EMA200
next_development_request: add a versioned RSI signal contract and tests before enabling it
```

## Successful response shape

成功时返回已通过 `validate_strategy_mapping`、`load_strategy_spec` 和
`check_capabilities` 的 YAML 路径，以及简短假设摘要；不返回未经 Python
计算的收益、回撤或其他绩效数字。
