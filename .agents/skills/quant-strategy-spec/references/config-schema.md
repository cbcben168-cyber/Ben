# Strategy configuration contract

This contract is the boundary between the `quant-strategy-spec` Skill and the
deterministic Python engine. The Skill produces YAML configuration; Python
parses, validates, and produces every numeric result. The configuration is
declarative: rules are preserved in `StrategySpec.raw` and are never converted
into generated Python code.

## Fields

`StrategySpec` has 20 fields: 19 YAML fields plus the derived `raw` mapping.

| Field | Required | Python type | Meaning and validation |
|---|---:|---|---|
| `strategy_name` | yes | `str` | Stable strategy identifier. |
| `asset_class` | yes | `str` | Asset family; current engine uses `equity`. |
| `symbol` | yes | `str` | One ticker, normalized to uppercase; Phase 1 supports SPY and QQQ. |
| `benchmark` | no | `str` | Defaults to `buy_and_hold`. |
| `timeframe` | yes | `str` | Daily bars use `1d`. |
| `start_date` | yes | `date` | ISO `YYYY-MM-DD`; must precede `end_date`. |
| `end_date` | yes | `date` | ISO `YYYY-MM-DD`; must follow `start_date`. |
| `initial_capital` | yes | `float` | Must be positive. |
| `entry_rules` | yes | `tuple[Mapping[str, Any], ...]` | Non-empty declarative entry-rule list. |
| `exit_rules` | yes | `tuple[Mapping[str, Any], ...]` | Non-empty declarative exit-rule list. |
| `position_sizing` | yes | `Mapping[str, Any]` | Current fixed engine uses `cash_limited_long_only`. |
| `commission_model` | yes | `float` in `commission_bps` | YAML model must be non-negative `basis_points`. |
| `slippage_model` | yes | `float` in `slippage_bps` | YAML model must be non-negative `basis_points`. |
| `fill_timing` | no | `str` | Defaults to `next_bar`; signals fill on the next bar. |
| `data_source` | no | `str` | Defaults to `validated_local_cache_first`. |
| `in_sample_period` | no | `tuple[date, date] \| None` | Reserved period boundary; current Task 2 mapping preserves null as `None`. |
| `out_of_sample_period` | no | `tuple[date, date] \| None` | Reserved period boundary; current Task 2 mapping preserves null as `None`. |
| `optimization_allowed` | no | `bool` | Defaults to `false`; optimization is outside the current fixed engine. |
| `report_language` | no | `str` | Defaults to `zh-CN`. |
| `raw` | derived | `Mapping[str, Any]` | Validated merged YAML mapping retained for audit and capability checks. |

## Defaults

The parser applies these defaults when the YAML omits them:

```yaml
benchmark: buy_and_hold
fill_timing: next_bar
optimization_allowed: false
report_language: zh-CN
data_source: validated_local_cache_first
```

Required fields are `strategy_name`, `asset_class`, `symbol`, `timeframe`,
`start_date`, `end_date`, `initial_capital`, `entry_rules`, `exit_rules`,
`position_sizing`, `commission_model`, and `slippage_model`.

## Example

```yaml
strategy_name: ema_baseline
asset_class: equity
symbol: SPY
benchmark: buy_and_hold
timeframe: 1d
start_date: "2020-01-01"
end_date: "2024-12-31"
initial_capital: 100000
entry_rules:
  - type: ema_crossover
    fast_period: 50
    slow_period: 200
exit_rules:
  - type: ema_crossunder
position_sizing:
  type: cash_limited_long_only
commission_model: {type: basis_points, value: 5}
slippage_model: {type: basis_points, value: 5}
fill_timing: next_bar
data_source: validated_local_cache_first
in_sample_period: null
out_of_sample_period: null
optimization_allowed: false
report_language: zh-CN
```

## Errors and engine mapping

`load_strategy_spec` rejects non-mapping YAML. `validate_strategy_mapping`
raises `ValueError` for missing required fields, invalid ISO dates, a reversed
date range, non-positive capital, empty rule lists, non-mapping position size,
or commission/slippage models that are not non-negative basis points.

The current fixed engine consumes standardized daily OHLCV for SPY or QQQ,
calculates EMA50/EMA200 crossover signals, fills by default on the next bar,
and applies commission and slippage in basis points. It compares results with
Buy and Hold. Unsupported rule shapes remain visible in the raw mapping and
are blocked by the capability check; they are not approximated.
