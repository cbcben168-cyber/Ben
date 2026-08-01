# Quant Research Automation V2 Design

状态：V2 权威设计基线；V2.1 Contract & Gate 已验收

日期：2026-07-26

来源基线：`81438c7`（Phase 1 Quant Research Skills Pipeline 完成提交）

目标分支：`codex/quant-research-automation-v2`

本文件使用中文描述产品边界和行为，代码、状态码、文件路径与接口名称保留英文。第 1-28 节定义完整 V2 目标；第 29 节只记录已经实现并验收的 V2.1 Contract & Gate，不授权 V2.2/V2.3 执行能力。

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
3. 面向美股和美股 ETF 的日线、60 分钟、30 分钟、15 分钟研究配置；实现顺序固定为日线先行，盘中周期只有在独立数据合同通过后才开放。
4. Parquet 优先的本地缓存、缓存完整性检查和增量更新。
5. Futu OpenD 作为正式数据获取路径，遵守进程、登录、权限、额度和一次性启动约束。
6. VectorBT 作为日常主回测引擎；版本和依赖必须锁定并写入运行证据。
7. 现有 Python EMA 引擎作为黄金样本验证器，而不是第二套通用回测引擎。
8. 统一的 next-bar open、现金、仓位、成本、流动性和公司行为语义。
9. VIX、SPY 趋势、多周期确认和相对强弱等高级过滤器的受控表达；首个可用里程碑不依赖这些后续能力。
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
| Stage 2 | 选择本地缓存或按规则通过 OpenD 启动适配器取数 | 数据源可用且来源可记录；确认授权有效 |
| Stage 3 | 校验数据、日历、时间对齐、公司行为和覆盖范围 | 通过数据质量合同 |
| Stage 4 | 执行未优化主回测和必要的黄金样本验证 | 生成完整权益与成交产物 |
| Stage 5 | 使用同口径执行 Buy and Hold | 基准产物完整 |
| Stage 6 | 执行确定性审计 | `PASS` 或允许报告的 `CONDITIONAL_PASS` |
| Stage 7 | 写入中文报告、manifest 绑定和摘要 | 审计未失败 |

任何阶段失败立即停机。Stage 0 至 Stage 3 的失败必须只写 provisional `failure_<run_id>.json`，不得生成正式 `summary.json`、`equity.csv` 或 `trades.csv`。Stage 4 至 Stage 7 可以产生 provisional 产物，但在最终审计完成前不得发布为正式结果；所有 blocker 都禁止取数、回测和模板保存。

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

### 7.3 机器可验证的确认协议

确认页生成不可变的 `ConfirmationRequest`，至少包含：`request_id`、规范化配置哈希 `strategy_config_hash`、假设哈希 `assumptions_hash`、数据需求哈希 `data_requirements_hash`、展示时间 `presented_at_utc`、过期时间 `expires_at_utc` 和 `action=execute_once`。用户只能通过精确回复“确认执行”授予一次执行权；自然语言同义表达不算确认。

系统随后生成一次性 `ConfirmationGrant`。grant 至少包含 `request_id`、上述三个哈希、随机 `confirmation_token`、token 的 SHA-256、创建时间、过期时间和 `used=false`。token 只通过本地进程间接口传递，manifest 只保存 token 哈希，不保存明文 token。

本地 runner 的执行入口必须同时接收配置路径、grant 和 token。取数前、回测前和任何正式模板保存前都必须校验：request 未过期、token 未使用、三项哈希完全匹配、action 为 `execute_once`。任一校验失败返回 `CONFIRMATION_REQUIRED` 或 `CONFIRMATION_MISMATCH_BLOCKER`，不下载、不回测、不保存；首次成功进入运行后立即原子标记 token 已使用，重复调用必定拒绝。配置、数据需求或假设发生任何变化都必须生成新的 request 和 grant。

## 8. 配置合同与默认模板

### 8.1 固定模板

```yaml
strategy_name: ema_baseline
schema_version: v2.1
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
stop_loss:
  enabled: false
take_profit:
  enabled: false
commission_model:
  profile_id: futu_us_equity_locked_v1
slippage_model:
  profile_id: timeframe_liquidity_v1
fill_timing: next_bar_open
data_source: validated_local_cache_first
adjustment: split_adjusted_ohlcv_with_separate_cash_dividend
optimization_allowed: false
report_language: zh-CN
```

该 YAML 是可复用的候选模板，不是新策略的隐式默认配置。初始资金固定为 `100000 USD`，正式数据优先使用 Futu 或已验证本地文件，基准是同标的 Buy and Hold，成交语义为 `next_bar_open`，报告语言为 `zh-CN`，优化固定关闭。每个新策略必须在向导中显式输入并确认 `position_sizing`；历史模板中的仓位字段只能作为待确认候选，不能补齐新策略的缺失值。无法确认锁定的 Futu 美国股票手续费模型时，不允许使用零成本回测。

### 8.2 字段合同

必填字段包括 schema 版本、标的、周期、开始日期、结束日期、固定初始资金、入场、退出、仓位方式、手续费 profile、滑点 profile、成交时点、数据源、复权方式、交易时段和报告语言。字段类型、枚举、范围、单位和时区必须由 schema 校验。`position_sizing` 缺失或为 null 只能停在向导，不得进入能力检查后的执行路径。

内部统一字段：

- `timestamp_utc`：所有计算和产物中的时间主键。
- `timeframe`：`1d`、`60m`、`30m` 或 `15m`。
- `fill_timing`：规范值为 `next_bar_open`；Phase 1 的 `next_bar` 仅可作为兼容输入并规范化为该值。
- `optimization_allowed`：V2 首版固定为 `false`。
- `regular_hours_only`：固定为 `true`，不含盘前盘后。
- `strategy_config_hash`：规范化配置的 SHA-256。
- `schema_version`：V2 配置 schema 的显式版本，当前设计锁定为 `v2.1`。
- `initial_capital`：不可被用户或模板覆盖的 `100000 USD`；输入其他值返回 `INITIAL_CAPITAL_POLICY_BLOCKER`。
- `benchmark`：V2 对象 `{"type":"buy_and_hold","symbol":"same_as_strategy"}`；Phase 1 字符串 `buy_and_hold` 只能经兼容适配器转换。
- `position_sizing`：每次新策略必填，枚举为 `full_capital`、`fixed_fraction` 或 `risk_based`，没有系统默认值。

## 9. 策略 DSL

### 9.1 首版允许的表达式

注册候选指标：EMA、SMA、RSI、MACD、ATR、Bollinger Bands、N 周期高低点突破、Donchian Channel、成交量均线和 Relative Volume。候选不等于已开放能力；每个实施计划只开放其出口门禁明确列出的节点，首个可用里程碑只开放 EMA50/EMA200。

交易规则：固定持仓时间、固定百分比止损/止盈、ATR 止损、移动止损，以及 `all`、`any`、`not` 布尔组合。

所有指标必须声明参数类型、最小值、最大值、warm-up lookback、输出列、时区语义和允许使用的位置。每个条件必须明确返回 entry、exit、filter 或 position-sizing 输入。

### 9.2 编译边界

DSL 编译器只允许把白名单节点编译为已注册的 VectorBT adapter 输入。禁止 DSL 注入任意 Python、表达任意文件访问、网络请求、账户操作或动态导入。无法表达的规则返回 `PLUGIN_REQUIRED` 或 `STRATEGY_CAPABILITY_BLOCKER`，不以近似规则替代。

DSL 的规范化结果必须保存：原始中文意图、规范化 YAML、schema 版本、能力矩阵、warm-up 需求、编译器版本和编译输出哈希。

### 9.3 V2 schema、规范化 IR 与 Phase 1 适配器

V2 的正式 schema 为版本化 YAML，规范化后必须生成不可变的 `StrategyIR`。IR 至少包含：

- `schema_version`、`strategy_name`、`asset_class`、`symbol`、`timeframe`、`start_date`、`end_date`、`currency` 和固定 `initial_capital=100000 USD`；
- `session`（`America/New_York`、`regular_hours_only=true`、交易日历版本）；
- `entry_rules`、`exit_rules`、`filters`、显式 `position_sizing`、显式 `stop_loss` 和 `take_profit`；
- `cost_profile_id`、`slippage_profile_id`、`fill_timing=next_bar_open`、`adjustment`、`benchmark`、`optimization_allowed=false`；
- 每个节点的 `node_id`、输入列、参数、lookback、时间语义、依赖节点和能力注册版本。

V2 的 benchmark 必须是对象，不再使用会产生歧义的字符串；V2 的仓位方式使用 `full_capital`、`fixed_fraction`、`risk_based`，V2 的成本使用 profile ID，不把 `commission_bps`、`timeframe_bps` 或 `futu_us_equity_locked` 等旧字段直接当作 V2 语义。Phase 1 `StrategySpec` 的 `benchmark: buy_and_hold`、`fill_timing: next_bar`、`position_sizing: {type: cash_limited_long_only}` 和 basis-points mapping 只由显式 `Phase1Adapter` 转换为黄金样本输入；转换结果、原始字段和适配器版本写入 manifest。无法无损转换时返回 `SCHEMA_COMPATIBILITY_BLOCKER`，不运行黄金样本。

schema 校验必须拒绝未知字段、重复语义字段、非固定初始资金、缺失仓位方式、未声明的 stop/target 和未注册节点。规范化 IR 是 VectorBT adapter 的唯一输入；Codex、插件和报告层不得绕过 IR 直接构造 orders、cash 或 equity。

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
- 每个过滤器必须声明 provider、symbol、timeframe、session、调整方式、数据覆盖、warm-up、完成 K 线规则、最大允许延迟和 `data_hash`；辅助数据缺失、未注册或不能证明完成时返回 `FILTER_DATA_CAPABILITY_BLOCKER`。
- VIX 现货必须使用注册的现货序列；不得用 VIX 期货或其他代理替代。SPY 趋势过滤器和相对强弱基准必须分别登记为辅助 dataset，并经过与目标标的一致的 session/calendar 对齐。
- 高周期确认只能在目标 bar 开始前使用最近一根已完成的高周期 bar；相对强弱只能使用目标 bar 开始前已完成的基准 bar。辅助序列不得用 `reindex`、填充或插值制造尚未完成的值。
- 未指定相对强弱基准返回 `RELATIVE_STRENGTH_BENCHMARK_BLOCKER`。
- 所有辅助数据的来源、时间范围、对齐规则、warm-up、完成 bar 时间和哈希写入 manifest，并由 look-ahead fixture 验证。

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

OpenD 启动由独立 `OpenDStartupAdapter` 负责。适配器按以下顺序定位可执行文件：显式配置路径、项目允许的环境变量、Windows 注册表中 Futu 安装项、受控的标准安装目录；不得扫描整个磁盘或假设固定安装位置。适配器先检查目标 host/port 的健康状态和当前进程 PID；已存在且 ready 的 OpenD 直接复用。未找到 ready 实例时，每个 pipeline run 最多调用一次启动命令，并使用固定的 ready timeout、poll interval、host、port 和日志目录。启动命令、解析到的 executable path、PID、版本、尝试次数和结果写入 run manifest；路径不存在、启动失败、超时、登录、验证码、权限或额度问题立即返回对应 blocker，不循环重启、不生成替代数据。

“只尝试启动一次”的边界是一次 pipeline run，而不是一次对话或一个进程生命周期。无论失败发生在下载前还是增量请求中，同一 run 不得第二次启动；下一次用户明确发起的新 run 必须重新做健康检查。

### 11.3 缓存合同

缓存按规范化 dataset ID 分区，优先 Parquet，CSV 仅作为导入兼容格式。dataset ID 的输入字段固定为：`provider`、`market`、`symbol`、`timeframe`、`session`、`calendar_id`、`timezone`、`schema_version`、`adjustment_version`、`corporate_action_version`。规范化字符串、字段顺序、大小写、日期和版本均固定后计算 ID；文件名、绝对路径、抓取时间和本机 PID 不得进入 dataset ID。

每个 Parquet 必须有同目录的不可变 sidecar manifest，记录 canonical dataset ID、provider capability、symbol/provider code、bar label、覆盖区间、行数、列 schema、calendar、timezone、quality status、source content hash、Parquet file hash、corporate-action hash、创建时间和修订版本。缓存命中必须同时验证 ID、sidecar、文件 hash、覆盖范围和质量状态；缺失 sidecar 或任何版本不匹配视为缓存不可用，不得静默标记为 Futu。增量写入使用新版本目录并原子发布，旧版本只读保留；运行目录和缓存目录分离。

缓存目录与运行产物目录分离。增量更新必须保留旧文件或可追溯版本；原始行情不被运行覆盖。

### 11.4 公司行为

正式研究需要拆股因子、现金分红事件、除息日、支付规则和覆盖范围。策略和 Buy and Hold 使用同一套规则；分红不得被重复计算。manifest 记录复权方式、分红 source、action content hash、处理版本和覆盖区间。

Data provider capability matrix 必须按 provider、symbol、timeframe 和 adjustment 列出：raw OHLCV、split factor、cash dividend、ex-date、calendar、RTH、历史覆盖和版本证据。当前 Futu 适配器只有在矩阵明确证明所需公司行为字段可用且已验证时，才允许正式发布；仅有 QFQ/复权 OHLCV、但没有可核验现金分红事件时，返回 `CORPORATE_ACTION_DATA_BLOCKER`，不得从收盘价差额推断分红。公司行为能力缺失也阻止 Buy and Hold、正式回测和模板保存。

### 11.5 交易时段和回测截止点

常规盘中时段为 `09:30-16:00 America/New_York`，不含盘前盘后；交易所日历版本决定节假日和半日市实际收盘。正式运行只使用完整 RTH bars，当前会话或最后一个不完整 bar 必须被排除并写入 warning；若配置区间因此无法覆盖，返回 `DATA_VALIDATION_BLOCKER`。

### 11.6 日内数据合同与聚合语义

所有内部计算仍使用 UTC。每根 bar 的主时间戳是 `bar_start_utc`，代表该 bar 在 New York RTH 的起始时刻；`bar_end_utc` 是按交易所 session 计算的结束时刻，不能用固定 UTC 偏移替代 DST 规则。信号只在 `bar_end_utc` 已到达且 bar 已完成后产生，成交使用下一根合法 bar 的 `open`。

首版日内合同固定如下：15 分钟序列包含正常日 `09:30` 至 `15:45` 起始的 26 根完整 bars；30 分钟序列包含 `09:30` 至 `15:30` 起始的 13 根完整 bars；60 分钟序列以 `09:30` 为锚点产生 `09:30-10:30`、`10:30-11:30`、`11:30-12:30`、`12:30-13:30`、`13:30-14:30`、`14:30-15:30` 六根完整 bars，`15:30-16:00` 尾段不足 60 分钟，正式 60 分钟数据排除。半日市按实际 session end 重新计算，任何不足目标周期的尾段排除并记录原因。

15 分钟是日内聚合的最小 canonical source；30/60 分钟只能由同一 provider、同一 symbol、同一 session、同一 adjustment、同一日历版本的完整 15 分钟 bars 聚合，禁止跨 session、跨日期、跨 provider 或用未来 bars 补齐。若 provider 只提供标记语义不明的 30/60 分钟 bars，则该 timeframe 返回 `INTRADAY_TIME_SEMANTICS_BLOCKER`。每个 bar 保存 `source_bar_count`、组成区间、缺失组件和是否为完整 bar；日内正式入口必须通过 DST、节假日、半日市、尾段、缺失组件和未完成 bar 的 fixture 验证。首个可用里程碑只开放 `1d`，因此在上述合同和验证门禁完成前，60/30/15 分钟只能返回 blocker。

## 12. 预热、时间和未来函数控制

指标预热只用于形成指标，不产生交易，不计入绩效，也不改变正式回测起点。manifest 必须记录：

- `warmup_start`
- `backtest_start`
- `warmup_bars`
- `longest_lookback`

同一根 K 线不得同时用作信号和成交；规范成交为下一根可交易 K 线开盘。没有下一根 K 线时，最后一根信号只能记录为 warning，不得虚构成交。高周期、VIX、SPY 和相对强弱数据都必须先完成时间对齐，再进入信号计算。

`next_bar_open` 的黄金协议固定为：在 bar `t` 完成后计算信号，信号索引为 `t`；从同一 symbol、同一 session/calendar、严格时间递增的序列中选择第一个 `bar_start` 大于 `t.bar_end` 的完整 bar `t+1`；订单时间为 `t+1.bar_start`，市场参考价为 `t+1.open`。买入成交价为 `open * (1 + effective_slippage)`，卖出成交价为 `open * (1 - effective_slippage)`，手续费在同一成交事件计入现金；不得使用 signal bar 的 close、next bar 的 high/low 或未来 bar 的任何字段决定成交。

同一 bar 同时触发 stop-loss 和 take-profit 时使用保守的 stop-first 顺序；若 stop 在 bar open 发生，按 gap open 价成交，否则按预先声明的 stop 触发价和方向性滑点成交；take-profit 只在 stop 未先触发时生效。没有可证明的盘中路径时，不得选择对结果更有利的顺序，必须将 `stop_target_priority=stop_first` 和 gap 规则写入 manifest。最后一个 bar 的信号永不成交，只写 `FINAL_BAR_SIGNAL_IGNORED` warning。以上协议必须有固定输入 fixture，逐项对比 signal index、fill index、price、shares、cash、fees、equity 和 warning。

## 13. VectorBT 主回测与 Python 黄金样本

### 13.1 VectorBT adapter

VectorBT 是 V2 的日常主回测引擎。adapter 负责：

- 将规范化 entry/exit/filter/position-sizing 编译为统一输入。
- 统一 `entries`、`exits`、`size`、`fees`、`slippage` 和 `price` 接口。
- 明确 next-bar open 的实现和最后一根 K 线行为。
- 输出 orders、trades、equity、cash、position、metrics 和 warnings。
- 保留空交易、部分资金、现金和公司行为的语义。

VectorBT 版本、依赖版本和代码 commit 必须进入运行 manifest；版本未锁定、adapter 未验证或依赖不可用时返回 `ENGINE_CAPABILITY_BLOCKER`，不得生成正式结果。VectorBT 是唯一日常主引擎，V2 首版不执行参数搜索，VectorBT 只执行已确认配置。现有 Python 引擎仅接收 `Phase1Adapter` 输出的黄金样本 IR，不接收任意 V2 DSL，也不实现第二套通用仓位、成本、过滤器或公司行为逻辑。

### 13.2 黄金样本验证器

现有 Python 引擎只保留以下验证范围：EMA crossover、next_bar_open、手续费、滑点、Buy and Hold、固定止损、空交易、最后一根 K 线、数据不足 blocker、现金权益对账。

对受支持的黄金样本，VectorBT 结果必须与 Python 结果在允许的数值容差内对齐：信号时间、成交时间、成交方向、成交数量、成交价、成本、现金、权益曲线、交易数和 Buy and Hold。对账失败返回 `ENGINE_PARITY_BLOCKER` 或 `FAIL`，不能修改结果以强行通过。

黄金样本验证器不扩展成第二个完整 DSL 引擎。新 DSL 节点必须先由 VectorBT adapter 和审计契约验证，再决定是否加入黄金样本范围。

## 14. 仓位、成本、流动性与现金

### 14.1 仓位方式

V2 目标枚举为：

1. `full_capital`：最多使用 100% 可用资金、无杠杆、同一时刻只持有一个标的。
2. `fixed_fraction`：用户显式提供资金比例。
3. `risk_based`：用户显式提供 `risk_per_trade` 和明确止损距离。

没有默认仓位方式；缺少 `position_sizing` 或必要输入时返回 `POSITION_SIZING_INPUT_BLOCKER`。不允许根据账户余额、隐含风险偏好或历史配置猜测仓位。`risk_based` 缺少 stop distance 时即使策略未启用 stop-loss，也必须返回 blocker；stop-loss 和 take-profit 的默认状态都是 `enabled=false`，但必须显式写入 IR 和确认页。

### 14.2 手续费和滑点

手续费使用版本化的 `futu_us_equity_locked_v1` cost profile。profile 必须明确买卖方向、佣金、平台费、交易所费、监管费、最低收费、按股/按金额计费、费率上限、USD 舍入规则、现金币种和生效版本；公式固定为每笔订单各项费用逐项计算后按 profile 规定舍入，禁止用一个未解释的 bps 近似替代。profile 缺失、版本未锁定或未验证时返回 `COST_PROFILE_CAPABILITY_BLOCKER`，不得零成本运行。

滑点使用版本化的 `timeframe_liquidity_v1` profile：先按 timeframe 选择单边基础 bps，再乘 liquidity coefficient，买卖方向分别应用到 open；有效 bps、profile 版本、流动性分层、计算区间和订单 notional 写入 manifest。手续费和滑点必须同时进入 order、cash、equity、策略指标和 Buy and Hold。

### 14.3 流动性

平均每日成交额定义为最近 20 个完整交易日的平均成交量乘平均收盘价。分层：

- 不低于 10 亿美元：`high`，系数 `1.0`。
- 2 亿至 10 亿美元：`medium`，系数 `1.5`。
- 5000 万至 2 亿美元：`low`，系数 `2.0`，并出具 warning。
- 低于 5000 万美元：`LIQUIDITY_CAPABILITY_BLOCKER`。

manifest 必须写入基础滑点、流动性等级、系数、有效滑点和计算区间。现金、持仓价值、订单规模和权益必须逐时点可对账。

## 15. Buy and Hold 基准

基准自动使用同标的、同 dataset ID、同数据版本、同有效区间、同初始资金、同复权和公司行为规则、同币种、同交易时段、同 cost/slippage profile 和同 `next_bar_open` 执行约束。Buy and Hold 在第一根有效 bar 的 open 按相同买入滑点和手续费买入整数股，保留未投资现金；在最后一根有效 bar 的 close 进行期末估值，并在需要实现现金收益的报告口径中按同一卖出成本计算，不得使用主动策略的成交序列或不同的起止价。现金分红、拆股和股数变化按同一 corporate-action ledger 处理，不得只对策略或只对基准处理。

基准必须输出与策略同结构的 orders、trades、equity、cash、metrics、cost breakdown 和 data/action hashes。任何一项标的、数据、区间、公司行为、初始资金或成本不一致，都返回 `BENCHMARK_FAIRNESS_BLOCKER`，不得发布相对收益结论。

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

审计产物分为 `provisional` 和 `formal` 两类。Stage 0 至 Stage 5 只能写 provisional；只有 Stage 6 返回 `PASS` 或允许报告的 `CONDITIONAL_PASS`、所有 blocker 为空、配置/数据/假设/代码/引擎/插件/产物哈希完整且 self-check 通过，才可原子发布 formal 结果。`FAIL`、任何 blocker、smoke test、缺失或不一致的 hash 只能保留 provisional 失败记录，不能通过改写状态或摘要升级。

## 17. 运行产物、manifest 与中文报告

每次运行使用独立目录，不覆盖原始数据和历史运行。第一阶段的 `run_manifest.py`、`backtest_audit.py`、`reporting.py` 和 `run_manifest` hash/binding 能力是唯一 artifact、audit、provenance 和 hash 所有者；V2 只通过 adapter 扩展字段，不创建第二套 manifest、hash、audit 或报告写入器。至少保存：

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

正式发布采用临时目录加原子 rename：先校验所有 provisional 文件、manifest 声明的路径、文件 hash、dataset/action hash、audit status 和目标 run ID，再一次性发布 formal marker。任何校验或 rename 失败都保留 failure record，不覆盖已存在运行目录，不生成正式报告或模板。Phase 1 既有 artifact 名称和字段继续由其 owner 发布，V2 新增字段必须通过版本化扩展并保持旧字段语义不变。

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

插件运行必须是独立进程，使用固定版本解释器和最小权限工作目录；父进程通过版本化 JSON 输入输出协议通信。插件输入只能是已验证的 IR、声明的数据列和只读辅助序列；插件输出只能是带时间戳的 `entry`、`exit` 或 target-position signals、lookback、warnings 和 plugin metadata，禁止输出订单、成交价、手续费、现金、权益、benchmark 或 audit status。Pipeline/VectorBT adapter 独占订单、仓位、成本、公司行为、现金、基准和审计。

运行时必须实施 imports、网络、文件路径、环境变量和子进程 allowlist，并设置 CPU、内存、输出大小和 wall-clock timeout；越权、超时、非零退出、输出 schema 不合法或 hash 不匹配返回 `PLUGIN_SANDBOX_BLOCKER`。注册表保存 plugin name、immutable version、source hash、metadata hash、依赖版本、测试证据、批准记录和能力范围；未注册、未批准或 hash 改变的插件不能执行。

## 19. 策略模板与版本管理

只有回测结束后才询问模板处理：

1. 只运行一次。
2. 保存为新模板。
3. 覆盖已有模板。

用户未回复时默认为只运行一次。覆盖前必须显示差异并再次确认“确认覆盖”；旧版本保留，不原地覆盖历史版本。

以下结果不得保存为正式模板：`FAIL`、任意 blocker、`SMOKE_TEST_DATA_ONLY`、执行不完整、配置不可复现、未批准插件、插件测试失败或审计失败。模板只能写入 `templates/registry/<strategy_family>/<symbol>/<timeframe>/<schema_version>/`，以 `strategy_family`、`symbol`、`timeframe`、`schema_version`、`dependency_hash` 和完整配置哈希作为查找键；同键版本不可变，latest 指针只能指向最新合格版本。

模板保存内容包括规范化 YAML、配置哈希、IR/schema/compiler 版本、插件版本、依赖版本、数据来源要求、成本和公司行为 profile、审计状态、OOS 状态和创建时间。模板不是账户配置，不包含 API key、密码或账户资料。回测、Buy and Hold、审计和 formal artifact 完成后才询问“只运行一次/保存为新模板/覆盖已有模板”；询问前不写模板目录。最近一次可复用配置只从 registry 查找 `PASS` 或明确允许复用的 `CONDITIONAL_PASS`，且无 blocker、非 smoke、hash 完整、schema/依赖/插件仍兼容；找不到时自动进入新策略向导。

## 20. 低 Token 运行设计

日常路径遵循以下顺序：

- 优先加载最近一次 `PASS` 或 `CONDITIONAL_PASS` 的有效配置。
- 只询问指定修改字段和由修改引起的依赖字段。
- YAML 作为唯一运行事实来源，固定默认模板不重复解释。
- 本地程序执行计算，Codex 只读取紧凑摘要和审计状态。
- 只有用户请求时才读取完整交易明细、权益曲线或审计 payload。
- 不默认优化、Monte Carlo、Walk-forward 或参数扫描。
- 不在对话中重写指标、成本、回撤或 Buy and Hold 计算代码。

本地 runner 的最小接口固定为：`run --config <path> --confirmation-grant <path> --confirmation-token <token> --mode formal`。它只读取 YAML、registry、cache 和 provider adapter，返回一份短 JSON：`status`、`blocker_code`、`run_id`、`run_directory`、`audit_status`、`formal_result_published`、`report_summary_path` 和 `next_action`。Codex 默认只读取该 JSON 和 `report_zh.md` 的摘要；只有用户要求时才读取完整交易明细、权益曲线或审计 payload。任何缺少 grant、过期/重复 token、非 formal 证据或 blocker 的运行都不得让 `formal_result_published=true`。

每次运行保留完整证据；低 Token 只影响展示和读取方式，不得删减审计必需字段。Codex 不直接启动 provider、不直接调用 VectorBT、不读取大文件计算指标；它只负责问答、配置生成、确认、调用本地 runner 和结果解释。

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

V2 不作为一份无门禁的大实施任务。冻结为五个可独立验收的实施计划；每个计划只开放其出口门禁声明的能力，后续计划不得提前依赖未通过的契约。

### V2.1 合同、确认与本地 runner

- 范围：V2.1 schema、StrategyIR、Phase1Adapter、问答状态机、ConfirmationRequest/Grant、配置/假设/数据需求哈希、provisional/formal 产物边界和短 JSON runner 接口。
- 入口门禁：`81438c7` 的 Phase 1 manifest、audit、provenance、hash、Stage 0-7 和 blocker 语义可被只读调用；没有 VectorBT、真实账户或新数据依赖。
- 出口门禁：未知字段、缺仓位、非 `100000 USD`、未确认、过期/重复/错 hash grant 均有确定性 blocker；Phase 1 旧字段只能经 adapter 转换；runner 能在本地返回短 JSON，且未授权时不触发取数/回测/保存。

### V2.2 数据、缓存与 provider adapter

- 范围：日线 canonical dataset、Parquet sidecar/版本键、数据质量、交易日历、RTH、公司行为 capability matrix、Futu OpenD 健康检查和每 run 一次启动策略；辅助数据只建立注册接口。
- 入口门禁：V2.1 的 IR 和 confirmation grant 已冻结；本地 fixture 覆盖缺失、重复、排序、覆盖不足、sidecar/hash 不匹配和 provider blocker。
- 出口门禁：已验证本地 Parquet 命中不启动 OpenD；缓存不足时最多尝试一次；OpenD 路径不依赖固定安装位置；公司行为证据不足返回 `CORPORATE_ACTION_DATA_BLOCKER`；正式数据没有隐式 Futu 标签。V2.2 只开放 `1d`，盘中周期仍返回 blocker。

### V2.3 日线 VectorBT 主引擎与黄金样本

- 范围：VectorBT adapter、EMA50/EMA200 首个注册 DSL、`next_bar_open` 黄金协议、三种仓位模式、锁定 Futu 成本 profile、周期/流动性滑点、同口径 Buy and Hold、Python 黄金样本逐笔对账和审计。
- 入口门禁：V2.1 合同和 V2.2 日线数据均通过出口门禁；VectorBT 及依赖版本已锁定并可写入 manifest。
- 出口门禁：固定 fixture 验证 signal/fill index、open 价格、stop-first、最后一根 bar、现金、整数股、成本、公司行为和 benchmark 公平性；VectorBT 与黄金样本在容差内一致；审计通过后才能发布 formal report。

V2.3 是首个可用里程碑：用户输入策略、SPY/QQQ、`1d` 和回测区间后，向导生成 YAML，用户回复“确认执行”，本地 runner 优先命中 Parquet、必要时一次性协调 OpenD，由 VectorBT 完成日线回测和 Buy and Hold，生成审计状态和中文摘要；若任一能力或数据条件不满足，返回 blocker 且不保存正式模板。

### V2.4 盘中合同、过滤器与受控插件

- 范围：15 分钟 canonical source、30/60 分钟聚合、DST/节假日/半日市/尾段合同，VIX 现货、SPY、一个高周期确认、用户指定基准相对强弱，以及插件独立进程、参数白名单、sandbox 和注册流程。
- 入口门禁：V2.3 的日线主路径和 audit fixture 全部通过；每个辅助数据集有 provider、完成 bar、lag、calendar、hash 证据；插件有 immutable version、测试和批准记录。
- 出口门禁：完整日内数据合同和 look-ahead fixture 通过；任意未验证时间语义、辅助数据缺失、插件越权或输出订单/成本的请求均 blocker；不引入市场宽度、多标的轮动、期权、IBKR、LEAN、TradingView 自动化或实盘。

### V2.5 交付、模板 registry 与全量验收

- 范围：formal/provisional 原子发布、中文报告、模板查找/保存/覆盖确认、最近有效配置复用、低 Token 短 JSON、OOS 锁定和完整回滚/迁移验收。
- 入口门禁：V2.1-V2.4 的契约、能力、数据、引擎、插件和 audit 证据已通过；Phase 1 artifact、manifest、provenance 和 hash owner 不变。
- 出口门禁：PASS/允许的 CONDITIONAL_PASS、FAIL 和两个 blocker 的下游行为可验证；正式模板只来自合格 formal run；无最近配置自动进入新策略向导；全部排除项没有可达路径。

每个计划只能修改其声明的接口和文件；计划完成前不得开放下一个计划的策略能力。任何计划都不得下载非必要数据、安装未批准依赖、接入账户、发送订单或进入 Phase 2。五个计划是同一 V2 设计文档中的冻结实施边界，不创建额外的未审查实施计划文件。

## 23. 迁移与兼容

V2 以 `81438c7` 为基础，不修改该提交的历史内容，不覆盖 Phase 1 运行产物，不复制 Phase 1 manifest、audit、report 或 EMA 计算逻辑。

兼容规则：

- 现有 EMA 配置继续作为黄金样本。
- Phase 1 `next_bar` 输入可规范化为 V2 `next_bar_open`，但运行 manifest 同时记录原始值和规范值。
- 现有运行产物只读，不自动迁移或改写；V2 运行使用独立目录和独立 manifest 版本。
- 现有 CLI 和 PowerShell 参数保持兼容，新增参数必须显式传入并有测试。
- 现有项目级 Skills 保持可发现和隔离；用户级 Skills 不受影响。
- V2 DSL 必须能够表达原有 EMA 案例，否则不得宣称兼容完成。
- Phase 1 当前 parser 仍只接受 `1d`、固定 EMA 和 basis-points mapping；V2 不把该现状描述为已支持日内、通用 DSL、Futu 公司行为或 VectorBT。V2.1/V2.2 的 adapter 和数据合同完成前，相关请求必须返回 blocker。
- OOS 只有在 parser、锁定区间、manifest 字段和审计检查全部实现并通过后才允许 `PASS`。在此之前即使有 in-sample 结果，也只能是 `CONDITIONAL_PASS` 并写入 `OOS_NOT_LOCKED`；不允许保存为正式模板或宣称样本外通过。

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

## 27. 独立设计审查解决矩阵

以下决策是本文件的冻结补充。若本文件早前的示例、简称或旧字段与本节冲突，以本节以及第 7.3、9.3、11.3-11.6、12、16-22 节为准；这些契约对实现具有约束力。

### 27.1 Required Changes

| ID | Severity | Design Section | Problem | Required Resolution |
|---|---|---|---|---|
| R1 | BLOCKER | 7.3 | “确认执行”没有机器可验证授权，可能被 CLI 绕过。 | 使用绑定 request/config/assumption/data hashes 的一次性、可过期 `ConfirmationGrant`；runner 在取数、回测、模板保存前校验，缺失、过期、重复或不匹配均停止。 |
| R2 | BLOCKER | 8.2, 9.3 | DSL schema、AST/IR 与 Phase 1 字段存在冲突。 | 锁定 `v2.1` schema 和 `StrategyIR`；V2 benchmark 为对象、成本为 profile、fill 为 `next_bar_open`，旧 Phase 1 字段只能经 `Phase1Adapter` 转换。 |
| R3 | HIGH | 22 | 同一实施计划同时覆盖数据、引擎、过滤器、插件和交付，无法分阶段验收。 | 冻结 V2.1-V2.5 五个计划，各有范围、入口门禁、出口门禁；V2.3 才是首个日线可用里程碑。 |
| R4 | BLOCKER | 12, 13.1 | `next_bar_open` 的 signal/fill、价格、末 bar 和 stop/target 行为不完整。 | 固定 bar start/end、下一完整 bar open、方向性滑点、最后 bar warning、gap 规则和 stop-first；用 golden fixture 对账。 |
| R5 | HIGH | 11.6 | 15/30/60 分钟聚合、bar 标签、DST、半日市和未完成 bar 未冻结。 | 15m 为 canonical source，30m/60m 按 09:30 锚点聚合，60m 尾段排除；完整 RTH、NY 日历、UTC 主键和 fixture 验证，首个里程碑只开放 1d。 |
| R6 | BLOCKER | 11.4 | Futu 的复权 OHLCV 不等于可核验分红事件。 | 建立 provider capability matrix；缺少现金分红/ex-date/版本证据返回 `CORPORATE_ACTION_DATA_BLOCKER`，不推断、不回测、不保存。 |
| R7 | HIGH | 11.2 | OpenD 启动路径依赖本机固定安装位置。 | `OpenDStartupAdapter` 支持显式路径、受控环境变量、注册表和标准目录发现；每 pipeline run 只尝试一次并记录 path/PID/version/结果。 |
| R8 | HIGH | 11.3 | Parquet 缓存键、版本、缺口和 provenance 不足，可能误标来源。 | dataset ID 固定 provider/market/symbol/timeframe/session/calendar/timezone/schema/adjustment/corporate-action 字段；sidecar、content/file hash、coverage 和质量必须同时验证，禁止隐式 Futu 标签。 |
| R9 | HIGH | 14.2 | Futu 费率、最低收费、舍入和滑点公式不明确。 | 使用版本化 `futu_us_equity_locked_v1` 与 `timeframe_liquidity_v1` profiles，明确费用组成、最低值、舍入、币种、方向和流动性系数；缺 profile 返回 blocker。 |
| R10 | BLOCKER | 15 | Buy and Hold 只描述了同口径，未冻结整数股、现金、退出成本和公司行为。 | 同 dataset/区间/资本/行动 ledger/cost profile；第一有效 open 买入整数股并保留现金，末 bar close 估值并按同一卖出成本报告，输出同结构产物。 |
| R11 | HIGH | 10 | VIX、SPY、高周期和相对强弱缺乏数据源、lag 和完成 bar 契约。 | 每个辅助 dataset 必须注册 provider/timeframe/session/calendar/lag/completion/warm-up/hash；只能使用目标 bar 前已完成数据，缺失或未验证返回 blocker。 |
| R12 | BLOCKER | 9.2, 18 | 插件可能绕过 DSL、订单、审计或实盘限制。 | 插件独立进程、最小权限和 allowlist sandbox；只返回 normalized signals/positions，不返回 orders/cost/cash/audit；版本、参数、测试、批准和 hash 必须注册。 |
| R13 | HIGH | 19 | 模板 registry、查找键、合格状态和保存时点不明确。 | 固定 registry 路径和 key（strategy family/symbol/timeframe/schema/dependency/config hash）；只在 formal audit 后询问保存，PASS 或允许的 CONDITIONAL_PASS 才可复用，缺失则进新策略向导。 |
| R14 | HIGH | 20 | 低 Token 只有口号，没有本地执行接口和短结果契约。 | 固定 `run --config --confirmation-grant --confirmation-token --mode`；返回短 JSON，Codex 只读取 JSON/摘要，不计算指标、不读大文件。 |
| R15 | HIGH | 5, 17 | Phase 1 与 V2 的 manifest/audit/hash/provenance 所有权重叠。 | Phase 1 既有 owner 保持唯一写入权；V2 以 adapter 扩展 schema，不重复实现 manifest、artifact hash、audit、provenance 和基础报告。 |
| R16 | HIGH | 23 | 设计把 Phase 1 已有接口误表述为 V2 已兼容能力。 | 明确当前 Phase 1 仍是 daily/fixed EMA/legacy fields；只有 adapter 和相应门禁通过后才宣称 V2 兼容，未实现能力返回 blocker。 |
| R17 | BLOCKER | 8.1, 14.1 | 固定资金、无默认仓位和可选 stop/target 之间有冲突。 | 资金不可变为 `100000 USD`；新策略显式输入仓位；stop/target 默认为显式 `enabled=false`；risk-based 缺 stop distance 返回 `POSITION_SIZING_INPUT_BLOCKER`。 |
| R18 | BLOCKER | 6.2, 16, 17 | blocker、provisional、formal 和最终审计发布边界不清。 | blocker 不取数/回测/保存；Stage 4-5 只写 provisional；只有最终 audit 与 hash self-check 通过才原子发布 formal，FAIL 不得升级。 |

### 27.2 Ambiguities

| ID | Question | Why It Matters | Recommended Decision |
|---|---|---|---|
| A1 | 首版是否同时实现四种周期？ | 同时开放会把数据语义和验证范围扩大到无法验收。 | V2.3 首个里程碑只支持 `1d`；15/30/60m 归 V2.4，未通过合同前返回 blocker。 |
| A2 | benchmark 是字符串还是对象？ | 字符串无法表达同标的、成本和公司行为绑定。 | V2.1+ 使用 versioned object；`buy_and_hold` 字符串只作为 Phase 1 输入，经 adapter 转换。 |
| A3 | 用户能否覆盖初始资金？ | 会破坏固定比较口径和模板复现。 | 固定 `100000 USD`，任何其他值返回 `INITIAL_CAPITAL_POLICY_BLOCKER`。 |
| A4 | 无默认仓位如何处理模板？ | 模板候选值不能变成新策略隐式默认。 | 模板可保存已确认仓位，但新策略必须再次显式输入并确认；缺失停在向导。 |
| A5 | 同 bar 同时止损/止盈谁先？ | OHLC 没有足够路径信息，顺序会改变收益。 | `stop_first`、gap open 规则、方向性滑点和 manifest 字段固定；无路径不选择有利顺序。 |
| A6 | Futu 费率和分红证据如何确定？ | 不明确会产生零成本或重复/遗漏分红结果。 | 只接受锁定 profile 和 capability matrix 证据；缺失费率或现金 action 返回 blocker。 |
| A7 | “OpenD 只启动一次”的范围是什么？ | 不同范围会导致循环重启或跨 run 误判。 | 以一次 pipeline run 为边界；先健康检查，未 ready 最多启动一次。 |
| A8 | dataset ID 包含哪些字段？ | 键不稳定会错误复用缓存。 | 固定 provider、market、symbol、timeframe、session、calendar、timezone、schema、adjustment、corporate-action 版本字段。 |
| A9 | bar timestamp 是开始还是结束？ | 信号和成交错位会制造未来函数。 | `bar_start_utc` 是主键，`bar_end_utc` 表示完成；信号在完成后只映射到下一完整 bar open。 |
| A10 | Buy and Hold 是否计入双边成本和分红？ | 否则主动策略比较不公平。 | 使用同一 cost/slippage/action ledger；第一 open 买入，末 bar close 估值/同口径退出成本。 |
| A11 | 辅助 symbol 如何验证？ | VIX、SPY 和 relative-strength benchmark 可能来源不同或时间未对齐。 | 每个辅助 symbol 独立注册 dataset、provider、calendar、lag 和 hash，未通过能力检查即 blocker。 |
| A12 | 模板最近一次的查找键是什么？ | 只按策略名查找会复用错误周期、依赖或 schema。 | 至少使用 strategy_family、symbol、timeframe、schema_version、dependency_hash，并绑定完整 config hash。 |
| A13 | OOS 何时可标记 PASS？ | 未锁定 OOS 会把 in-sample 结果误称样本外。 | parser、locked range、manifest 和 audit 全部通过前只允许 `CONDITIONAL_PASS` + `OOS_NOT_LOCKED`，不得模板化。 |

## 28. 修订后自审与实现就绪门禁

本次设计修订的自审结论为 `NOT_READY -> READY_FOR_STAGED_IMPLEMENTATION`，含义是设计已经具备分阶段实现所需的冻结契约，并不表示任何 V2 代码已实现或 VectorBT 已安装。自审逐项确认：

1. 自动化系统建设优先于策略收益研究；V2.3 首个里程碑只验证日线系统闭环。
2. Codex 只做问答、YAML/IR 生成、确认、runner 调用和结构化结果解释；本地代码负责取数、回测、审计和报告。
3. YAML/DSL 是唯一策略语义来源；DSL 不可表达时只能进入注册且受控的插件流程。
4. VectorBT 是唯一日常主引擎；Python 只做 Phase 1 黄金样本对账；Phase 1 manifest/audit/provenance/hash 能力没有第二份实现。
5. 本地 Parquet 优先，OpenD 只在缓存不足时每 run 启动一次；Futu 能力、公司行为、成本、时间和缓存 hash 不足都会阻塞。
6. 确认、无默认仓位、固定资金、可选 stop/target、next-bar、Buy and Hold、RTH、四种 timeframe、四类高级过滤器和全部排除项均有明确契约或阶段门禁。
7. blocker 不下载、不回测、不保存；模板只在正式审计结束后询问；最近合格配置找不到时进入新策略向导。
8. 实施范围已经冻结为五个计划；没有遗留未决占位项或被推迟到实现阶段的关键行为。

在五个计划全部完成并通过其出口门禁前，`IMPLEMENTATION_READINESS` 只能解释为“可按冻结计划开始实现”，不能解释为“V2 已完成”。

## 29. V2.1 implementation acceptance evidence

本节是 V2.1 的实现证据索引，不改变第 1-28 节的完整 V2 目标。V2.1 状态为 `V2.1_CONTRACT_GATE_ACCEPTED`：schema、contracts、Phase 1 adapter、confirmation、local runner gate、template contract 和 CLI gate 已实现；provider、数据下载、intraday、VectorBT、plugin、正式回测、正式报告和正式模板发布仍不可用。

### 29.1 Frozen references and implementation snapshot

| Evidence | Actual path or interface | Commit | V2.1 status |
|---|---|---|---|
| Frozen implementation plan | `docs/superpowers/plans/2026-07-27-v2-1-contract-gate-implementation-plan.md` | `36ac03d7` | FROZEN |
| Implemented contract exports | `src/tv_quant/contracts/__init__.py` | `570c518ed1429d3b84f6fe9151bd18ea621f1150` | IMPLEMENTED_CONTRACT_ONLY |
| Phase 1 to V2 adapter export | `src/tv_quant/adapters/phase1_config_adapter.py::Phase1ToV2AdapterResult` | `570c518ed1429d3b84f6fe9151bd18ea621f1150` | IMPLEMENTED_CONTRACT_ONLY |
| Local runner and CLI gate | `src/tv_quant/contracts/runner_protocol.py::run_v2` and `src/tv_quant/pipeline_cli.py` | `570c518ed1429d3b84f6fe9151bd18ea621f1150` | IMPLEMENTED_GATE_ONLY |
| Contract and gate acceptance | `tests/contracts`, `tests/adapters`, `tests/pipeline/test_v2_cli_gate.py`, `tests/integration` | `570c518ed1429d3b84f6fe9151bd18ea621f1150` plus Task 19 acceptance commit | VERIFIED |

`IMPLEMENTED_CONTRACT_ONLY` 和 `IMPLEMENTED_GATE_ONLY` 都不表示执行引擎可用。V2.1 的合法 `execute` 请求仍确定性返回 `NOT_IMPLEMENTED` / `EXECUTION_CAPABILITY_NOT_IMPLEMENTED`，且 `formal_result_published=false`。

### 29.2 Final plan review evidence

| Review item | Independent evidence | Status |
|---|---|---|
| P1 | `tests/adapters/test_phase1_config_adapter.py::test_phase1_to_v2_result_preserves_source_and_generated_hashes`<br>`tests/adapters/test_phase1_config_adapter.py::test_v2_to_phase1_adapter_is_not_part_of_v21` | RESOLVED |
| P2 | `tests/contracts/test_strategy_v2_schema.py::test_each_explicit_root_field_is_required_without_normalization_default`<br>`tests/contracts/test_normalized_ir.py::test_missing_explicit_fields_never_become_normalization_defaults` | RESOLVED |
| P3 | `tests/contracts/test_strategy_v2_schema.py::test_disabled_stop_target_and_empty_filters_must_be_present`<br>`tests/contracts/test_normalized_ir.py::test_normalization_requires_position_sizing` | RESOLVED |
| P4 | `tests/contracts/test_ast_contract.py::test_entry_exit_and_filter_roots_require_predicates`<br>`tests/contracts/test_ast_contract.py::test_node_id_depth_and_node_count_limits_are_deterministic` | RESOLVED |
| P5 | `tests/contracts/test_execution_assumptions.py::test_assumptions_hash_accepts_only_execution_assumptions`<br>`tests/contracts/test_confirmation.py::test_request_binds_formal_execution_assumptions_hash` | RESOLVED |
| P6 | `tests/contracts/test_runner_protocol.py::test_grant_confirmation_returns_token_once`<br>`tests/contracts/test_runner_protocol.py::test_non_grant_modes_never_return_plaintext_token` | RESOLVED |
| P7 | `tests/contracts/test_schema_contract.py::test_python_contract_definitions_are_unique_source_of_truth`<br>`tests/contracts/test_strategy_v2_schema.py::test_python_contract_and_json_schema_required_fields_match` | RESOLVED |
| P8 | `tests/contracts/test_strategy_v2_schema.py::test_symbol_schema_accepts_valid_us_equity_symbol_without_spy_qqq_cap`<br>`tests/contracts/test_capability_registry.py::test_require_formal_rejects_not_live_verified` | RESOLVED |
| P9 | `tests/contracts/test_numeric_canonicalization.py::test_decimal_strings_normalize_1_1_00_to_one_semantic_hash`<br>`tests/contracts/test_normalized_ir.py::test_decimal_numeric_forms_produce_identical_hash` | RESOLVED |
| P10 | `tests/contracts/test_confirmation_store.py::test_atomic_consume_allows_exactly_one_consumer`<br>`tests/contracts/test_confirmation_store.py::test_windows_lock_backend_uses_msvcrt_contract`<br>`tests/contracts/test_confirmation_store.py::test_posix_lock_backend_uses_fcntl_contract`<br>`tests/contracts/test_confirmation_store.py::test_crash_before_replace_leaves_grant_retryable` | RESOLVED |
| P11 | `tests/contracts/test_path_safety.py::test_resolve_under_root_rejects_parent_traversal_absolute_and_root_escape`<br>`tests/contracts/test_path_safety.py::test_resolve_under_root_rejects_ntfs_ads_and_reserved_dos_devices` | RESOLVED |
| P12 | `tests/contracts/test_artifact_contract.py::test_dependency_hash_payload_contains_all_components`<br>`tests/integration/test_v2_1_gate.py::test_evidence_paths_are_contained_and_dependency_hash_is_complete` | RESOLVED |
| P13 | `tests/contracts/test_template_contract.py::test_only_one_active_version_exists_per_key`<br>`tests/contracts/test_template_contract.py::test_supersedes_points_to_same_key_older_record`<br>`tests/contracts/test_template_contract.py::test_supersedes_cycles_and_non_monotonic_versions_are_rejected` | RESOLVED |
| P14 | `tests/contracts/test_capability_registry.py::test_symbol_structural_support_is_not_phase1_execution_support`<br>`tests/contracts/test_capability_registry.py::test_require_formal_rejects_not_live_verified` | RESOLVED |
| P15 | `tests/contracts/test_status_codes.py::test_recoverable_retryable_terminal_semantics_are_consistent`<br>`tests/integration/test_v2_1_security.py::test_all_status_metadata_defines_recoverable_retryable_terminal` | RESOLVED |

The acceptance commands are:

~~~powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m pytest tests/contracts tests/adapters tests/pipeline/test_v2_cli_gate.py tests/integration -q
python -m pytest tests/contracts -q
python -m pytest tests/adapters -q
python -m pytest tests/pipeline/test_v2_cli_gate.py -q
python -m pytest tests/integration -q
python -m pytest tests/pipeline -q
python -m pytest tests -q
python -m compileall -q src tests
git diff --check
~~~

### 29.3 V2.1 exit evidence

| ID | Exit condition | Independent evidence | Status |
|---|---|---|---|
| E1 | Schema identity, version enforcement, and Python parity | `tests/contracts/test_schema_contract.py::test_python_contract_definitions_are_unique_source_of_truth`<br>`tests/contracts/test_strategy_v2_schema.py::test_schema_id_and_version_are_quant_strategy_v2_v21` | PASS |
| E2 | StrategySpecV2 valid load and legacy, unknown, unsafe rejection | `tests/contracts/test_strategy_v2_schema.py::test_valid_minimal_v2_config_loads`<br>`tests/contracts/test_strategy_v2_schema.py::test_invalid_enum_and_unknown_field_are_rejected`<br>`tests/contracts/test_strategy_v2_schema.py::test_legacy_phase1_mapping_requires_explicit_v2_loader` | PASS |
| E3 | Explicit required root fields with no normalization defaults | `tests/contracts/test_strategy_v2_schema.py::test_each_explicit_root_field_is_required_without_normalization_default`<br>`tests/contracts/test_normalized_ir.py::test_missing_explicit_fields_never_become_normalization_defaults` | PASS |
| E4 | Typed AST root, type, unit, depth, and node-count rules | `tests/contracts/test_ast_contract.py::test_entry_exit_and_filter_roots_require_predicates`<br>`tests/contracts/test_ast_contract.py::test_node_id_depth_and_node_count_limits_are_deterministic` | PASS |
| E5 | Immutable, deterministic, unit-explicit, float-free NormalizedStrategyIR | `tests/contracts/test_normalized_ir.py::test_identical_semantics_produce_identical_ir_and_hash`<br>`tests/contracts/test_normalized_ir.py::test_ir_contains_no_float_callable_or_python_source` | PASS |
| E6 | Stable normalized hash through the Phase 1 hash owner | `tests/contracts/test_normalized_ir.py::test_decimal_numeric_forms_produce_identical_hash`<br>`tests/integration/test_v2_1_security.py::test_v2_contracts_reference_existing_hash_owner` | PASS |
| E7 | One-way Phase1ToV2Adapter evidence and unchanged source | `tests/adapters/test_phase1_config_adapter.py::test_phase1_to_v2_result_preserves_source_and_generated_hashes`<br>`tests/adapters/test_phase1_config_adapter.py::test_v2_to_phase1_adapter_is_not_part_of_v21` | PASS |
| E8 | ExecutionAssumptions is the only assumptions hash payload | `tests/contracts/test_execution_assumptions.py::test_assumptions_contains_all_frozen_policy_and_version_fields`<br>`tests/contracts/test_execution_assumptions.py::test_assumptions_hash_accepts_only_execution_assumptions` | PASS |
| E9 | ConfirmationRequest binds all frozen hashes, summaries, profiles, and expiry | `tests/contracts/test_confirmation.py::test_request_contains_three_binding_hashes_and_summaries`<br>`tests/contracts/test_confirmation.py::test_request_hashes_change_with_each_bound_contract` | PASS |
| E10 | ConfirmationGrant is expiring, hash-bound, single-use, atomic, concurrent, and crash-safe | `tests/contracts/test_confirmation_store.py::test_atomic_consume_allows_exactly_one_consumer`<br>`tests/contracts/test_confirmation_store.py::test_windows_lock_backend_uses_msvcrt_contract`<br>`tests/contracts/test_confirmation_store.py::test_posix_lock_backend_uses_fcntl_contract`<br>`tests/contracts/test_confirmation_store.py::test_crash_before_replace_leaves_grant_retryable` | PASS |
| E11 | Plaintext token is returned once and absent from persistent and later outputs | `tests/integration/test_v2_1_gate.py::test_confirmation_token_is_returned_only_by_grant_response`<br>`tests/integration/test_v2_1_security.py::test_plaintext_confirmation_token_is_absent_from_persistent_outputs` | PASS |
| E12 | Missing, invalid, expired, mismatched, and reused tokens return frozen blockers | `tests/contracts/test_confirmation_store.py::test_missing_expired_mismatched_and_reused_token_are_rejected`<br>`tests/contracts/test_runner_protocol.py::test_execute_without_token_returns_confirmation_required`<br>`tests/contracts/test_runner_protocol.py::test_execute_with_invalid_token_returns_confirmation_invalid` | PASS |
| E13 | Capability status separates structural, implementation, formal, and smoke-only states | `tests/contracts/test_capability_registry.py::test_symbol_structural_support_is_not_phase1_execution_support`<br>`tests/contracts/test_capability_registry.py::test_require_formal_rejects_not_live_verified` | PASS |
| E14 | Artifact ownership reuses Phase 1 owners and dependency hash is complete | `tests/contracts/test_artifact_contract.py::test_existing_run_manifest_hash_owner_is_declared`<br>`tests/integration/test_v2_1_security.py::test_v2_contracts_reference_existing_hash_owner` | PASS |
| E15 | Provisional and formal results are distinct and evidence paths are root-contained | `tests/contracts/test_artifact_contract.py::test_provisional_evidence_accepts_only_contained_paths`<br>`tests/contracts/test_artifact_contract.py::test_v21_execute_cannot_mark_formal_result_published` | PASS |
| E16 | Four runner modes, compact JSON, stderr diagnostics, stable exits, and NOT_IMPLEMENTED execute | `tests/contracts/test_runner_protocol.py::test_runner_response_contains_required_short_json_fields`<br>`tests/contracts/test_runner_protocol.py::test_execute_with_valid_token_consumes_once_and_returns_not_implemented` | PASS |
| E17 | Explicit V2 CLI namespace cannot route to Phase 1 execution or refresh | `tests/pipeline/test_v2_cli_gate.py::test_v2_command_never_calls_legacy_run_pipeline_or_refresh`<br>`tests/integration/test_v2_1_security.py::test_v2_runner_does_not_call_legacy_pipeline` | PASS |
| E18 | Template contract has immutable version, deterministic lookup, eligibility, invalidation, and active fields | `tests/contracts/test_template_contract.py::test_template_record_contains_immutable_version_and_hashes`<br>`tests/contracts/test_template_contract.py::test_invalidated_record_cannot_be_active` | PASS |
| E19 | Template registry enforces one active version, supersession, acyclic history, semantic version order, and no mtime lookup | `tests/contracts/test_template_contract.py::test_lookup_uses_key_not_file_mtime`<br>`tests/contracts/test_template_contract.py::test_only_one_active_version_exists_per_key`<br>`tests/contracts/test_template_contract.py::test_supersedes_cycles_and_non_monotonic_versions_are_rejected` | PASS |
| E20 | Contract, adapter, CLI, and integration suites pass together | `tests/integration/test_v2_1_gate.py::test_final_plan_review_matrix_has_p1_through_p15_resolved`<br>`tests/integration/test_v2_1_gate.py::test_v21_exit_gate_checklist_is_complete`<br>`tests/integration/test_v2_1_gate.py::test_v22_entry_interfaces_match_public_exports` | PASS |
| E21 | Existing Phase 1 suite remains green | `tests/integration/test_v2_1_security.py::test_phase1_suite_remains_unchanged` | PASS |
| E22 | Static review finds no live, provider, network, VectorBT, plugin, or arbitrary Python execution path | `tests/integration/test_v2_1_security.py::test_v2_modules_have_no_network_provider_or_engine_import`<br>`tests/integration/test_v2_1_security.py::test_v2_modules_have_no_arbitrary_execution_construct` | PASS |
| E23 | Acceptance performed no download, OpenD connection, formal backtest, or VectorBT installation | `tests/contracts/test_runner_protocol.py::test_runner_does_not_call_pipeline_backtest_or_provider`<br>`tests/contracts/test_confirmation_store.py::test_store_has_no_network_process_or_backtest_side_effects` | PASS |
| E24 | Every status defines recoverable, retryable, terminal, and user_action semantics | `tests/contracts/test_status_codes.py::test_recoverable_retryable_terminal_semantics_are_consistent`<br>`tests/integration/test_v2_1_security.py::test_all_status_metadata_defines_recoverable_retryable_terminal` | PASS |
| E25 | Final Task 19 tracked tree is clean after the acceptance commit | Task 19 post-commit `git status --short` review | PASS |

### 29.4 V2.2 frozen public interfaces

V2.2 must preserve all 19 names in the unchanged plan entry gate. Each frozen name below maps to its implemented V2.1 public symbol or, for the three contract-family labels, the complete concrete public boundary that carries that contract. The acceptance test derives the authoritative names from the frozen plan, checks this mapping independently, and resolves every symbol against the live modules.

| Frozen interface | Actual public module | Concrete V2.1 symbols | Status |
|---|---|---|---|
| StrategySpecV2 | `tv_quant.contracts` | `StrategySpecV2` | FROZEN |
| NormalizedStrategyIR | `tv_quant.contracts` | `NormalizedStrategyIR` | FROZEN |
| DataPlan | `tv_quant.contracts` | `DataPlan` | FROZEN |
| DatasetRequirement | `tv_quant.contracts` | `DatasetRequirement` | FROZEN |
| ExecutionAssumptions | `tv_quant.contracts` | `ExecutionAssumptions` | FROZEN |
| CapabilityRegistry | `tv_quant.contracts` | `CapabilityRegistry` | FROZEN |
| ConfirmationRequest | `tv_quant.contracts` | `ConfirmationRequest` | FROZEN |
| ConfirmationGrant | `tv_quant.contracts` | `ConfirmationGrant` | FROZEN |
| AuthorizedExecutionContext | `tv_quant.contracts.confirmation` | `ConfirmationAuditRecord`<br>`validate_and_consume` | FROZEN_CONTRACT_FAMILY |
| RunnerRequest | `tv_quant.contracts` | `RunnerRequest` | FROZEN |
| RunnerResponse | `tv_quant.contracts` | `RunnerResponse` | FROZEN |
| ArtifactContract | `tv_quant.contracts.artifact_contract` | `ARTIFACT_OWNERS`<br>`ArtifactOwner`<br>`DependencyFingerprint`<br>`ProvisionalEvidence`<br>`FormalResultContract`<br>`dependency_hash`<br>`formal_eligibility` | FROZEN_CONTRACT_FAMILY |
| DependencyFingerprint | `tv_quant.contracts` | `DependencyFingerprint` | FROZEN |
| ProvisionalEvidence | `tv_quant.contracts` | `ProvisionalEvidence` | FROZEN |
| FormalResultContract | `tv_quant.contracts` | `FormalResultContract` | FROZEN |
| StatusCodeRegistry | `tv_quant.contracts.status_codes` | `BlockerCode`<br>`PipelineStatus`<br>`StatusDefinition`<br>`STATUS_DEFINITIONS`<br>`status_definition`<br>`status_snapshot_hash` | FROZEN_CONTRACT_FAMILY |
| Phase1ToV2AdapterResult | `tv_quant.adapters.phase1_config_adapter` | `Phase1ToV2AdapterResult` | FROZEN |
| TemplateLookupKey | `tv_quant.contracts` | `TemplateLookupKey` | FROZEN |
| TemplateRecord | `tv_quant.contracts` | `TemplateRecord` | FROZEN |

The `AuthorizedExecutionContext` mapping preserves the one-time validated-consumption boundary as `ConfirmationAuditRecord` returned by `validate_and_consume`; it does not authorize an engine. `ArtifactContract` preserves the Phase 1 ownership ledger plus dependency/provisional/formal gates. `StatusCodeRegistry` preserves the enum, immutable metadata ledger, lookup, and snapshot hash. V2.2 must not bypass, rename, narrow, or replace any of these boundaries.

Nothing in this section marks VectorBT, OpenD/provider access, intraday aggregation, dividend handling, plugin execution, formal backtest publication, or formal template publication as available. Those remain gated by their later phase plans.
