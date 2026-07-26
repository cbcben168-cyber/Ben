# Quant Research Automation V2 Design

状态：V2 权威设计基线

日期：2026-07-26

来源基线：`81438c7`（Phase 1 Quant Research Skills Pipeline 完成提交）

目标分支：`codex/quant-research-automation-v2`

本文件使用中文描述产品边界和行为，代码、状态码、文件路径与接口名称保留英文。本文档只定义 V2，不授权本次任务开始实现 V2。

## 1. 背景与方向纠偏

Phase 1 已经建立了安全的量化研究骨架和一条有限的 EMA 流水线：策略配置先经过标准化和能力检查，再选择并验证数据，执行固定的 EMA50/EMA200 回测，计算 Buy and Hold 基准，执行确定性审计，并保存中文报告、运行 manifest 和哈希证据。

Phase 1 的核心成果不是某个收益数字，而是以下不可绕过的边界：

- Python 是数据、指标、回测、统计和审计的确定性计算核心。
- 默认使用 UTC；报告可以转换到 `America/New_York`。
- 信号默认在下一根可交易 K 线执行，禁止把信号产生当日收盘价当作成交价。
- 手续费和滑点必须进入成交、现金和权益计算。
- 数据重复、缺失、排序、价格完整性和覆盖范围必须先检查。
- 每个正式结果都必须与同标的、同区间、同成本口径的 Buy and Hold 比较。
- 数据 provenance、配置哈希、运行 manifest、产物哈希和审计状态必须可复现。
- `FAIL`、`STRATEGY_CAPABILITY_BLOCKER` 和 `DATA_CAPABILITY_BLOCKER` 不得被包装为成功。
- 当前阶段不连接真实交易账户、不发送订单、不接入 TradingView Webhook、不做期权回测。

V2 的首要任务不是寻找最高收益率，也不是让 LLM 直接计算交易绩效，而是把已经验证的底层能力组织成可重复的自动化研究系统。系统先解决“能否安全、完整、可审计地执行一次研究”，再进入策略研究；在日常运行稳定后，常规回测应主要由本地程序完成，以降低 Token 消耗和重复解释成本。

## 2. V2 目标

V2 必须提供一条由对话触发、由本地程序执行、由审计决定是否可报告的完整研究路径：

```text
Codex 对话问答
    -> 分组确认状态机
    -> 中文策略 DSL / YAML
    -> 配置标准化、默认值填充和能力检查
    -> 数据需求解析
    -> 已验证 Parquet 本地缓存
    -> Futu OpenD 按需增量取数
    -> 数据质量、时间对齐和公司行为处理
    -> VectorBT 日常主回测
    -> Phase 1 Python 黄金样本验证
    -> Buy and Hold 基准
    -> 确定性审计
    -> 中文摘要报告和可复现运行产物
    -> 可选保存为版本化策略模板
```

目标能力包括：

1. 对话内问答向导：继承最近一次有效配置，只显示继承字段、本次修改字段、自动计算字段和原始约束。
2. 中文策略描述到 YAML/DSL 的确定性转换，YAML 是运行时唯一事实来源。
3. 面向美股和美股 ETF 的日线、60 分钟、30 分钟、15 分钟研究配置。
4. Parquet 优先的本地缓存、缓存完整性检查和增量更新。
5. Futu OpenD 作为正式数据获取路径，遵守进程、登录、权限、额度和一次性启动约束。
6. VectorBT 作为日常主回测引擎；版本和依赖必须锁定并写入运行证据。
7. 现有 Python EMA 引擎作为黄金样本验证器，而不是第二套通用回测引擎。
8. 统一的 next-bar open、现金、仓位、成本、流动性和公司行为语义。
9. VIX、SPY 趋势、多周期确认和相对强弱等高级过滤器的受控表达。
10. 受控 Python 策略插件、版本化模板、中文报告、审计和低 Token 运行接口。

## 3. 非目标与硬边界

本版本不做以下工作：

- 历史期权链、多腿期权回测、Greeks、IV Rank、波动率曲面或到期结构。
- IBKR、LEAN、TradingView 自动控制、Pine 执行、Webhook 或任何真实交易连接。
- 实盘下单、自动交易、纸面交易连接、账户管理或远程推送。
- VIX 期货期限结构、市场宽度、多标的轮动、组合共享资金和跨资产组合优化。
- 大规模参数网格搜索、默认优化、Monte Carlo、Walk-forward 或自动寻找最高收益策略。
- Kronos、Agent swarm 或其他预测系统。
- 清理、迁移、覆盖或删除用户级 Skills。
- 将 VectorBT 安装、数据下载或正式回测作为本次设计任务的实现内容。

这些能力未来只能经过独立的能力注册、输入输出契约、测试、审计和用户确认后加入；在能力未注册前必须返回明确 blocker，而不是近似执行。

## 4. 设计原则

### 4.1 确定性优先

LLM 只负责理解意图、补齐问答状态、生成结构化配置和解释已生成的结果。收益、回撤、手续费、滑点、基准差异、现金和仓位由 Python 或 VectorBT 适配器确定性计算；LLM 不得在文字中重新计算最终绩效。

### 4.2 配置即合同

所有会影响结果的字段必须进入 YAML、规范化配置或 manifest。未说明的关键假设不能由系统猜测。缺失仓位方式、成本模型、时间区间、数据源或关键规则时，必须停在配置确认或 blocker 状态。

### 4.3 失败不可伪装

任一前置阶段失败，都不得调用后续回测、报告或模板保存。能力不足用 `STRATEGY_CAPABILITY_BLOCKER`，数据不可得或不合格用 `DATA_CAPABILITY_BLOCKER`；数据校验失败、配置冲突、插件不合格和审计失败必须保留具体错误码。

### 4.4 同口径比较

策略与 Buy and Hold 必须使用同标的、同数据源、同有效时间范围、同初始资金、同公司行为处理、同货币和合理相同的成本口径。报告必须同时展示绝对结果和相对 Buy and Hold 的差异。

### 4.5 版本与证据优先

配置、数据、代码、引擎、插件和每个输出产物都要可定位、可哈希、可复核。运行结果不能依赖当前目录的隐含状态，也不能覆盖原始行情或已有运行目录。

## 5. Phase 1 复用基线

V2 建立在 `81438c7` 的已完成能力之上，不重新设计第二套 Phase 1：

| Phase 1 能力 | V2 复用方式 |
|---|---|
| `src/tv_quant/strategy.py` | 保留固定 EMA50/EMA200、long-only、下一根开盘、手续费、滑点和最后一根 K 线处理，作为黄金样本验证器 |
| `src/tv_quant/metrics.py` | 复用确定性指标和成本调整后的 Buy and Hold 计算，不由报告文本重算 |
| `src/tv_quant/data_quality.py` | 复用 OHLCV 标准化、时间排序、重复和缺失检查；V2 只增加适配层和更细的 provenance |
| `src/tv_quant/futu_downloader.py` / `futu_quota.py` | 复用已验证的本地缓存和 Futu 能力边界，V2 增加按需协调，不绕过权限和额度检查 |
| `src/tv_quant/reporting.py` | 继续作为 `summary.json`、`equity.csv` 和 `trades.csv` 的唯一基础报告写入者 |
| `src/tv_quant/run_manifest.py` | 复用规范化哈希、文件哈希、运行版本和产物绑定 |
| `src/tv_quant/backtest_audit.py` | 复用 next-bar、成本、现金权益、数据 provenance、可复现性、OOS 边界和五态审计 |
| `src/tv_quant/research_pipeline.py` | 复用 Stage 0 至 Stage 7 的停机顺序、失败记录、audit-only 和中文报告边界 |
| `src/tv_quant/pipeline_cli.py` | 保留 CLI 和 PowerShell 入口的参数化及退出码语义 |
| `.agents/skills/` | 保留项目级 Skills 与用户级 Skills 的隔离，不让 V2 修改用户级 Skills |

Phase 1 的 `EMA50/EMA200` 是黄金样本，不等于 V2 的通用 DSL 已经实现；VectorBT 也不是本次仓库中已安装或已验证的现状。设计中必须明确区分“现有能力”“目标接口”和“尚未实现的能力”。

## 6. 总体架构与组件边界

### 6.1 组件职责

| 组件 | 负责 | 不负责 |
|---|---|---|
| Codex 对话层 | 问答、确认、配置变更摘要、结构化结果解释 | 计算绩效、猜测数据、绕过 blocker、修改用户策略 |
| `quant-strategy-spec` | 中文意图标准化、YAML schema、能力矩阵和假设识别 | 取数、回测、生成绩效 |
| `quant-research-pipeline` | 固定阶段编排、数据选择、回测调用、审计和报告绑定 | 重新实现指标、成交和收益计算 |
| Data provider adapter | 检查缓存、请求数据、记录来源和增量范围 | 绕过登录、权限、额度或生成伪数据 |
| Data contract layer | 标准化 OHLCV、UTC、交易日历、公司行为和数据质量 | 修改原始行情文件 |
| VectorBT adapter | 把已验证 DSL 编译成 VectorBT 可执行输入并收集输出 | 自行改变策略语义或吞掉错误 |
| Python golden verifier | 对受支持样本做逐笔、现金、权益和成本对账 | 成为第二个通用 DSL 引擎 |
| `quant-backtest-audit` | 检查时序、成本、资金、数据、产物、复现和基准公平性 | 从自然语言反推缺失结果 |
| Report/template layer | 保存结构化运行产物、中文摘要和版本化模板 | 把失败或 smoke test 保存为正式模板 |

### 6.2 固定阶段

V2 仍按 Phase 1 的 Stage 0 至 Stage 7 顺序执行：

| 阶段 | 行为 | 可继续条件 |
|---|---|---|
| Stage 0 | 解析并规范化策略 YAML/DSL | schema 和关键假设完整 |
| Stage 1 | 检查策略、数据、引擎和插件能力 | `SUPPORTED` |
| Stage 2 | 选择本地缓存或按规则启动数据提供方 | 数据源可用且来源可记录 |
| Stage 3 | 校验数据、日历、时间对齐、公司行为和覆盖范围 | 通过数据质量合同 |
| Stage 4 | 执行未优化主回测和必要的黄金样本验证 | 生成完整权益与成交产物 |
| Stage 5 | 使用同口径执行 Buy and Hold | 基准产物完整 |
| Stage 6 | 执行确定性审计 | `PASS` 或允许报告的 `CONDITIONAL_PASS` |
| Stage 7 | 写入中文报告、manifest 绑定和摘要 | 审计未失败 |

任何阶段失败立即停机。Stage 0 至 Stage 3 的失败必须只写 `failure_<run_id>.json`，不得生成看似成功的 `summary.json`、`equity.csv` 或 `trades.csv`。

## 7. Codex 对话问答向导

### 7.1 分组问答

向导按以下顺序收集配置；已继承且未变更的字段不重复提问：

1. 标的、资产类别、周期和回测区间。
2. 入场条件、退出条件和高级过滤器。
3. 仓位方式、风险预算、止损和止盈。
4. 数据源、复权方式、成本、滑点、交易时段和报告语言。
5. 完整确认页：显示继承字段、本次修改字段、自动计算字段、假设和阻塞项。

仓位方式没有默认值；止损和止盈可以选择不设置，但必须显式显示为“未启用”。用户只有回复“确认执行”后，系统才可以取数和回测。

### 7.2 状态机

```text
NEW
  -> INHERIT_LAST_VALID
  -> COLLECTING
  -> CONFIG_VALIDATED
  -> CONFIRMATION_REQUIRED
  -> EXECUTION_CONFIRMED
  -> RUNNING
  -> AUDITED
  -> REPORT_READY
```

异常转移：

- 字段冲突或格式不合法：`CONFIG_VALIDATION_BLOCKER`，返回可修正字段。
- 能力不存在：`STRATEGY_CAPABILITY_BLOCKER`，不取数、不回测。
- 数据或提供方不可用：`DATA_CAPABILITY_BLOCKER`，不回测。
- 用户未确认：停留在 `CONFIRMATION_REQUIRED`，不执行。
- 审计失败：`FAIL`，不生成正式通过结论，不保存模板。

系统不得自动修改用户策略以消除冲突，不得从历史配置猜测缺少的仓位方式或成本模型。允许用户只修改确认页中的指定字段；每次变更都必须重新规范化并生成新的配置哈希。

## 8. 配置合同与默认模板

### 8.1 固定模板

```yaml
strategy_name: ema_baseline
asset_class: equity
symbol: SPY
benchmark:
  type: buy_and_hold
timeframe: 1d
start_date: "2020-01-01"
end_date: "2024-12-31"
initial_capital: 100000
currency: USD
session:
  timezone: America/New_York
  regular_hours_only: true
entry_rules:
  - type: ema_crossover
    fast_period: 50
    slow_period: 200
exit_rules:
  - type: ema_crossunder
position_sizing:
  type: full_capital
commission_model:
  type: futu_us_equity_locked
slippage_model:
  type: timeframe_bps
fill_timing: next_bar_open
data_source: validated_local_cache_first
adjustment: split_adjusted_ohlcv_with_separate_cash_dividend
optimization_allowed: false
report_language: zh-CN
```

固定模板的含义：初始资金为 `100000 USD`；正式数据优先使用 Futu 或已验证本地文件；基准是同标的 Buy and Hold；默认 `next_bar_open`；报告语言为 `zh-CN`；默认不优化。无法确认锁定的 Futu 美国股票手续费模型时，不允许使用零成本回测。

### 8.2 字段合同

必填字段包括标的、周期、开始日期、结束日期、初始资金、入场、退出、仓位方式、手续费、滑点、成交时点、数据源、复权方式和报告语言。字段类型、枚举、范围、单位和时区必须由 schema 校验。

内部统一字段：

- `timestamp_utc`：所有计算和产物中的时间主键。
- `timeframe`：`1d`、`60m`、`30m` 或 `15m`。
- `fill_timing`：规范值为 `next_bar_open`；Phase 1 的 `next_bar` 仅可作为兼容输入并规范化为该值。
- `optimization_allowed`：V2 首版固定为 `false`。
- `regular_hours_only`：固定为 `true`，不含盘前盘后。
- `strategy_config_hash`：规范化配置的 SHA-256。

## 9. 策略 DSL

### 9.1 首版允许的表达式

基础指标：EMA、SMA、RSI、MACD、ATR、Bollinger Bands、N 周期高低点突破、Donchian Channel、成交量均线和 Relative Volume。

交易规则：固定持仓时间、固定百分比止损/止盈、ATR 止损、移动止损，以及 `all`、`any`、`not` 布尔组合。

所有指标必须声明参数类型、最小值、最大值、warm-up lookback、输出列、时区语义和允许使用的位置。每个条件必须明确返回 entry、exit、filter 或 position-sizing 输入。

### 9.2 编译边界

DSL 编译器只允许把白名单节点编译为已注册的 VectorBT adapter 输入。禁止 DSL 注入任意 Python、表达任意文件访问、网络请求、账户操作或动态导入。无法表达的规则返回 `PLUGIN_REQUIRED` 或 `STRATEGY_CAPABILITY_BLOCKER`，不以近似规则替代。

DSL 的规范化结果必须保存：原始中文意图、规范化 YAML、schema 版本、能力矩阵、warm-up 需求、编译器版本和编译输出哈希。

## 10. 高级过滤器与多周期对齐

首版允许四类过滤器：

1. VIX 现货过滤器；不包括 VIX 期货期限结构。
2. 用户定义的 SPY 市场趋势过滤器。
3. 当前周期加一个更高周期的确认。
4. 用户指定基准的相对强弱过滤器；基准必须明确为 SPY、QQQ、SOXX、IWM 或已注册标的。

规则：

- SPY 过滤器只有启用时才询问配置。
- 多周期最多一个更高周期。
- 更高周期只能使用已经完成的 K 线，不能读取尚未完成的高周期值。
- VIX、SPY、相对强弱基准和交易标的必须按 UTC 时间对齐，再映射到目标 K 线。
- 未指定相对强弱基准返回 `RELATIVE_STRENGTH_BENCHMARK_BLOCKER`。
- 所有辅助数据的来源、时间范围、对齐规则、warm-up 和哈希写入 manifest。

## 11. 数据获取、缓存与公司行为

### 11.1 来源优先级

正式顺序固定为：

1. 已验证的本地 Parquet 缓存。
2. Futu OpenD 增量补齐。
3. 已验证的本地 CSV/Parquet 导入。
4. 明确标记的 yfinance smoke test。

缓存完整且通过质量合同时，不启动 OpenD，不重复下载。缓存不完整时，只能按需补齐缺口；禁止后台循环刷新、无限重启或静默切换到未知来源。yfinance 结果必须写入 `SMOKE_TEST_DATA_ONLY`，不得作为正式结论或模板数据源。

### 11.2 Futu OpenD 状态

数据提供方必须返回明确状态：

- `FUTU_OPEND_START_BLOCKER`
- `FUTU_LOGIN_BLOCKER`
- `FUTU_MARKET_PERMISSION_BLOCKER`
- `FUTU_QUOTA_BLOCKER`
- `DATA_CAPABILITY_BLOCKER`
- `DATA_VALIDATION_BLOCKER`

OpenD 未启动时最多尝试一次自动启动；登录、验证码、权限或额度问题立即停止，不绕过权限、不循环重启、不生成替代数据。

### 11.3 缓存合同

缓存按 `provider / symbol / timeframe / adjustment` 分区，优先 Parquet，CSV 仅作为导入兼容格式。每个数据集必须记录 provider、symbol、timeframe、timezone、首尾时间、行数、重复数、缺失 K 线、OHLCV 字段、交易日历、复权方式、source hash、data hash 和 validation status。

缓存目录与运行产物目录分离。增量更新必须保留旧文件或可追溯版本；原始行情不被运行覆盖。

### 11.4 公司行为

采用拆股复权 OHLCV，现金分红单独入账。策略和 Buy and Hold 使用同一套规则；分红不得被重复计算。manifest 记录复权方式、分红来源、处理版本和覆盖区间。公司行为数据缺失时返回 `CORPORATE_ACTION_DATA_BLOCKER`。

### 11.5 交易时段和回测截止点

常规盘中时段为 `09:30-16:00 America/New_York`，不含盘前盘后。半日市使用交易所实际收盘时间。回测截止到最近一个完整交易日或完整交易时段，不读取当天未完成 K 线。

## 12. 预热、时间和未来函数控制

指标预热只用于形成指标，不产生交易，不计入绩效，也不改变正式回测起点。manifest 必须记录：

- `warmup_start`
- `backtest_start`
- `warmup_bars`
- `longest_lookback`

同一根 K 线不得同时用作信号和成交；规范成交为下一根可交易 K 线开盘。没有下一根 K 线时，最后一根信号只能记录为 warning，不得虚构成交。高周期、VIX、SPY 和相对强弱数据都必须先完成时间对齐，再进入信号计算。

## 13. VectorBT 主回测与 Python 黄金样本

### 13.1 VectorBT adapter

VectorBT 是 V2 的日常主回测引擎。adapter 负责：

- 将规范化 entry/exit/filter/position-sizing 编译为统一输入。
- 统一 `entries`、`exits`、`size`、`fees`、`slippage` 和 `price` 接口。
- 明确 next-bar open 的实现和最后一根 K 线行为。
- 输出 orders、trades、equity、cash、position、metrics 和 warnings。
- 保留空交易、部分资金、现金和公司行为的语义。

VectorBT 版本、依赖版本和代码 commit 必须进入运行 manifest；版本未锁定、adapter 未验证或依赖不可用时不得生成正式结果。V2 首版不执行参数搜索，VectorBT 只执行已确认配置。

### 13.2 黄金样本验证器

现有 Python 引擎只保留以下验证范围：EMA crossover、next_bar_open、手续费、滑点、Buy and Hold、固定止损、空交易、最后一根 K 线、数据不足 blocker、现金权益对账。

对受支持的黄金样本，VectorBT 结果必须与 Python 结果在允许的数值容差内对齐：信号时间、成交时间、成交方向、成交数量、成交价、成本、现金、权益曲线、交易数和 Buy and Hold。对账失败返回 `ENGINE_PARITY_BLOCKER` 或 `FAIL`，不能修改结果以强行通过。

黄金样本验证器不扩展成第二个完整 DSL 引擎。新 DSL 节点必须先由 VectorBT adapter 和审计契约验证，再决定是否加入黄金样本范围。

## 14. 仓位、成本、流动性与现金

### 14.1 仓位方式

必须支持：

1. `full_capital`：最多使用 100% 可用资金、无杠杆、同一时刻只持有一个标的。
2. `fixed_fraction`：用户显式提供资金比例。
3. `risk_based`：用户显式提供 `risk_per_trade` 和明确止损距离。

缺少必要输入时返回 `POSITION_SIZING_INPUT_BLOCKER`。不允许根据账户余额、隐含风险偏好或历史配置猜测仓位。

### 14.2 手续费和滑点

手续费使用项目锁定的 Futu 美国股票费率模型；滑点按周期模板和流动性系数计算。单边基础滑点的配置必须显式记录，成交价、现金流和最终权益必须包含滑点和手续费。

### 14.3 流动性

平均每日成交额定义为最近 20 个完整交易日的平均成交量乘平均收盘价。分层：

- 不低于 10 亿美元：`high`，系数 `1.0`。
- 2 亿至 10 亿美元：`medium`，系数 `1.5`。
- 5000 万至 2 亿美元：`low`，系数 `2.0`，并出具 warning。
- 低于 5000 万美元：`LIQUIDITY_CAPABILITY_BLOCKER`。

manifest 必须写入基础滑点、流动性等级、系数、有效滑点和计算区间。现金、持仓价值、订单规模和权益必须逐时点可对账。

## 15. Buy and Hold 基准

基准自动使用同标的、同数据源、同时间范围、同初始资金、同复权和公司行为规则、同货币、同交易时段和合理相同的成本模型。基准必须输出与策略同结构的指标：总收益、CAGR、最大回撤、Sharpe、Sortino、Calmar、波动率、市场暴露时间、资金利用率和超额收益。

报告至少展示：

- 策略与基准总收益差异。
- 策略与基准最大回撤差异。
- 策略超额收益及回撤改善。
- 成本敏感性和主要限制。

## 16. 审计与状态模型

审计必须覆盖：look-ahead bias、signal/fill timing、`next_bar_open`、多周期对齐、VIX/SPY/基准对齐、手续费、滑点、流动性、公司行为、空交易、交易次数、单笔和年度集中度、数据 provenance、config/data/plugin/artifact hash、现金权益对账、Buy and Hold 公平性和可重复性。

状态只有以下五种：

| 状态 | 含义 | 后续行为 |
|---|---|---|
| `PASS` | 能力、数据、执行、审计和复现证据完整 | 可生成正式基线报告；不代表允许实盘 |
| `CONDITIONAL_PASS` | 结果可解释但存在明确非致命证据缺口 | 可生成条件报告；禁止升级为 OOS 通过或正式模板 |
| `FAIL` | 数据、执行、成本、偏差、复现或报告检查失败 | 禁止正式结论和模板保存 |
| `STRATEGY_CAPABILITY_BLOCKER` | 策略超出当前引擎、DSL 或插件能力 | 停止取数和回测，返回开发请求 |
| `DATA_CAPABILITY_BLOCKER` | 数据源、范围、权限、质量或公司行为不可用 | 停止回测，返回数据补齐请求 |

审计以交易明细、权益曲线、输入配置、数据质量结果和运行记录为依据，不从自然语言摘要反推结论。`CONDITIONAL_PASS` 不得被下游自动当成 `PASS`。

## 17. 运行产物、manifest 与中文报告

每次运行使用独立目录，不覆盖原始数据和历史运行。至少保存：

```text
strategy_config.yaml
assumptions.json
data_manifest.json
run_manifest.json
orders.csv
trades.csv
equity.csv
metrics.json
benchmark_metrics.json
audit.json
report_zh.md
artifact_hashes.json
```

`run_manifest.json` 至少记录：run id、配置哈希、数据哈希、代码 commit、引擎和依赖版本、provider、symbol、timeframe、实际覆盖区间、UTC 时间、成本、成交时点、优化开关、benchmark、warm-up、插件哈希、产物路径和产物哈希。

中文报告至少包含：核心结论、审计状态、数据来源、实际区间、策略逻辑、总收益、CAGR、最大回撤、Sharpe、Sortino、Calmar、胜率、Profit Factor、平均盈利/亏损、最大连续亏损、交易次数、平均持仓时间、市场暴露、资金利用率、Buy and Hold 对比、成本敏感性、主要风险、限制和下一验证状态。

报告只读取结构化产物，不重新计算绩效。摘要先输出紧凑结果，完整审计和大型历史文件按需读取。

## 18. Python 策略插件

当 DSL 无法表达规则时，系统返回 `PLUGIN_REQUIRED`，说明缺失能力并列出已注册候选插件。未经用户选择和批准，系统不得生成插件。

插件目录固定为：

```text
plugins/strategies/<plugin_name>/<version>/
  plugin.py
  metadata.yaml
  tests/
  README.md
```

插件不可覆盖旧版本。`metadata.yaml` 必须声明接口版本、输入输出、可配置参数白名单、参数范围、数据需求、lookback、成本和时序语义。白名单之外的参数变更返回 `PLUGIN_LOGIC_CHANGE_REQUIRED`；参数越界返回 `PLUGIN_PARAMETER_VALIDATION_BLOCKER`。

插件必须通过单元测试、接口测试、look-ahead 检查、安全检查、审计和用户批准后才能进入能力注册。失败返回 `PLUGIN_VALIDATION_BLOCKER`。插件不能访问账户、订单、密钥、任意文件或未经声明的网络资源。

## 19. 策略模板与版本管理

只有回测结束后才询问模板处理：

1. 只运行一次。
2. 保存为新模板。
3. 覆盖已有模板。

用户未回复时默认为只运行一次。覆盖前必须显示差异并再次确认“确认覆盖”；旧版本保留，不原地覆盖历史版本。

以下结果不得保存为正式模板：`FAIL`、任意 blocker、`SMOKE_TEST_DATA_ONLY`、执行不完整、配置不可复现、未批准插件、插件测试失败或审计失败。

模板保存内容包括规范化 YAML、配置哈希、插件版本、依赖版本、数据来源要求、成本假设、审计状态和创建时间。模板不是账户配置，不包含 API key、密码或账户资料。

## 20. 低 Token 运行设计

日常路径遵循以下顺序：

- 优先加载最近一次 `PASS` 或 `CONDITIONAL_PASS` 的有效配置。
- 只询问指定修改字段和由修改引起的依赖字段。
- YAML 作为唯一运行事实来源，固定默认模板不重复解释。
- 本地程序执行计算，Codex 只读取紧凑摘要和审计状态。
- 只有用户请求时才读取完整交易明细、权益曲线或审计 payload。
- 不默认优化、Monte Carlo、Walk-forward 或参数扫描。
- 不在对话中重写指标、成本、回撤或 Buy and Hold 计算代码。

每次运行保留完整证据；低 Token 只影响展示和读取方式，不得删减审计必需字段。

## 21. 测试与验收策略

V2 实现阶段必须按能力单独测试，测试先于能力注册：

- 问答状态机：继承、修改、冲突、未确认不得执行。
- 配置契约：字段类型、枚举、单位、范围、默认值和未知字段拒绝。
- DSL parser/compiler：白名单节点、组合逻辑、lookback、VectorBT 编译边界和拒绝任意 Python。
- 指标：EMA、SMA、RSI、MACD、ATR、Bollinger、Donchian、成交量和 Relative Volume。
- next-bar open、空交易、最后一根 K 线、现金、整数股数、手续费和滑点。
- 高周期、VIX、SPY 和相对强弱的 UTC 对齐及未来函数检查。
- 三种仓位模式、止损距离和输入 blocker。
- Futu 进程检查、一次性启动、登录/权限/额度 blocker。
- Parquet 命中、增量更新、CSV/Parquet 导入、source/data hash 和缓存与运行目录隔离。
- 公司行为、分红不重复计算和 Buy and Hold 公平性。
- VectorBT 与黄金样本逐笔对账。
- 插件白名单、版本、参数范围、安全和审计。
- 报告、manifest、artifact hash、模板新建/覆盖确认和 audit-only。
- Token 快速路径、退出码、无网络、无账户和无订单静态检查。

验收必须证明：对话向导可用；最近配置可复用；未确认不执行；指定 DSL 可执行；Futu/Parquet 缓存按规则工作；VectorBT 和黄金样本可对账；过滤器、仓位、成本、公司行为、Buy and Hold、审计、中文报告和模板版本均可复现；没有实盘路径。

## 22. 实施阶段划分

设计批准后的实现应拆为可独立测试和提交的阶段：

1. V2 配置契约和问答状态机。
2. DSL schema、parser 和 compiler。
3. VectorBT adapter 与黄金样本对账。
4. Futu 按需取数和 Parquet 缓存。
5. 高级过滤器与多周期时间对齐。
6. 仓位、成本、公司行为、流动性和 benchmark。
7. 插件系统和能力注册。
8. 报告、模板和低 Token 接口。
9. 完整验收、迁移和回滚验证。

每个阶段只能修改其声明的文件和接口；阶段完成前不得开放下一个阶段的策略能力。任何阶段都不得安装未批准依赖、接入账户或进入 Phase 2。

## 23. 迁移与兼容

V2 以 `81438c7` 为基础，不修改该提交的历史内容，不覆盖 Phase 1 运行产物，不复制 Phase 1 manifest、audit、report 或 EMA 计算逻辑。

兼容规则：

- 现有 EMA 配置继续作为黄金样本。
- Phase 1 `next_bar` 输入可规范化为 V2 `next_bar_open`，但运行 manifest 同时记录原始值和规范值。
- 现有运行产物只读，不自动迁移或改写；V2 运行使用独立目录和独立 manifest 版本。
- 现有 CLI 和 PowerShell 参数保持兼容，新增参数必须显式传入并有测试。
- 现有项目级 Skills 保持可发现和隔离；用户级 Skills 不受影响。
- V2 DSL 必须能够表达原有 EMA 案例，否则不得宣称兼容完成。

## 24. 安全、密钥与禁止路径

API key、密码、验证码、账户资料和 token 不得写入代码、YAML、manifest、报告、日志、模板或 Git。若未来确有 provider 凭据需求，只能从 `.env` 或受控运行时注入读取，并确保 `.env` 在 `.gitignore` 中。

当前设计禁止：

- 连接真实交易账户。
- 发送、模拟发送或排队真实订单。
- 通过 TradingView、Futu、IBKR 或其他接口执行交易。
- 在 blocker 时使用随机值、近似指标、人工估算或 yfinance 正式替代数据。
- 通过用户级 Skill 绕过项目级能力矩阵。
- 为了通过测试删除断言、降低审计标准或隐藏 warning。

## 25. 回滚与失败处理

V2 使用独立分支、独立运行目录、独立缓存版本和版本化插件。任何阶段失败时：

- 保留失败阶段、错误码、输入配置哈希和 UTC 时间。
- 不覆盖 Phase 1 代码、数据和运行产物。
- 删除或停用新增能力前，先确认没有历史模板依赖该版本。
- 新依赖必须可移除；不可移除时不得进入实现阶段。
- 可以回退到 `81438c7` 的 Phase 1 基线，且不需要修改原始提交。

回滚不等于将失败结果保存为模板，也不等于绕过审计重新生成报告。

## 26. V2 完成定义

V2 只有同时满足以下条件，才能宣布完成：

- 问答向导、配置复用和确认门槛可用。
- 新策略可由中文 DSL/YAML 创建，且没有隐藏默认关键假设。
- Parquet 缓存、Futu 按需取数和数据 provenance 可复现。
- VectorBT 主回测与黄金样本在已注册能力范围内通过对账。
- EMA、SMA、RSI、MACD、ATR 等首版 DSL 能力的范围和 blocker 明确且有测试。
- VIX、SPY、多周期和相对强弱过滤器严格时间对齐。
- 三种仓位方式、next-bar open、手续费、滑点、流动性、公司行为和现金权益均通过审计。
- 每次运行都有配置、数据、代码、插件和产物哈希。
- Buy and Hold 使用同口径自动生成并比较。
- `PASS`、`CONDITIONAL_PASS`、`FAIL` 和两个 blocker 的行为边界可验证。
- 中文报告、模板版本和低 Token 读取接口可用。
- 全部正式结果可在无真实账户、无订单、无 Webhook 的条件下复现。

满足上述条件只表示研究系统 V2 的研究执行能力达到设计验收，不表示策略盈利、未来收益或允许实盘交易。
