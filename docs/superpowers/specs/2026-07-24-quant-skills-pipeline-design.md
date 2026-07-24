# Quant Research Skills Pipeline Design

状态：设计批准，尚未实施

本文档定义“量化研究 Skills 自动化流水线”的第一阶段架构、能力边界、审计规则和验收标准。本文档只设计项目级 Skill 的工作流，不创建 Skill，不替换 Python 回测引擎，也不改变已有数据契约。

## 1. 背景与问题

当前仓库没有项目级 Skill。现有实现主要是面向 SPY 和 QQQ 的历史日线下载、固定 EMA50/EMA200 基线回测、基础指标和报告；它不是通用策略解释器，也不是多策略研究平台。

用户级环境中存在 AlphaGBM 和其他通用 Skills，但它们属于用户环境，不应成为本项目流水线的隐式运行时依赖。AlphaGBM Skills 可以辅助期权或市场分析，但不能被当作本项目的历史回测引擎。

目标用户不需要理解 Python、数据供应商或回测内部实现。流水线应接受自然语言策略描述，经过固定的配置化流程完成一次可重复、低 Token、可审计、可回滚的研究运行。Skill 只能编排已有能力，不能虚构底层系统尚不存在的指标、数据、执行模型或资产类别。

## 2. 目标

### 2.1 第一阶段

第一阶段创建三个项目级 Skill：

1. quant-strategy-spec：把自然语言规则转换为结构化策略配置，并执行能力检查。
2. quant-research-pipeline：按固定顺序编排数据、回测、基准、审计和报告。
3. quant-backtest-audit：检查回测输入、执行时序、成本、偏差、可复现性和能力边界。

第一阶段必须能够包装现有 EMA 基线，完成一次从策略描述到中文报告的流水线运行。现有 Python 代码仍是收益、回撤、手续费和滑点的确定性计算来源。

### 2.2 第二阶段候选

只有第一阶段通过全部验收后，才评估以下项目级 Skill：

- vectorbt-backtest-adapter
- strategy-compare
- walk-forward-validation

第二阶段仍必须复用已验证的 Futu 本地缓存、统一手续费和滑点、next_bar 成交、统一审计以及 Locked OOS 约束。

## 3. 非目标

第一阶段明确不做以下事项：

- 自动参数优化或大型网格搜索。
- IBKR 接入。
- LEAN 接入。
- TradingView 自动控制、Webhook 或 Pine 自动执行。
- 期权历史回测、期权链、Greeks、IV Rank 或 volatility surface 计算。
- 自动下单、实盘账户连接或纸面交易连接。
- 用户级 Skill 清理、移动、删除、停用或版本重写。
- Kronos 预测。
- 多 Agent Swarm。
- 直接安装完整外部 Skill 套件。

第一阶段也不把 Walk-forward、Monte Carlo 或多策略比较伪装成已经存在的能力。它们只能作为后续能力请求被识别并阻塞，或在第二阶段正式实现后启用。

## 4. 总体架构

### 4.1 固定数据流

~~~text
用户中文策略描述
    -> quant-strategy-spec
    -> 结构化策略配置
    -> capability check
    -> quant-research-pipeline
    -> 数据选择与数据质量检查
    -> 现有 Python 回测引擎
    -> Buy and Hold 比较
    -> quant-backtest-audit
    -> 中文紧凑报告
~~~

任何阶段失败都终止当前运行。后续阶段不得绕过前一阶段的失败状态，也不得通过 LLM 直接估算最终收益、回撤、手续费或滑点。

### 4.2 职责分层

| 层 | 职责 | 禁止事项 |
|---|---|---|
| Skill | 解析、编排、校验、错误解释、报告组织 | 不重新实现收益计算，不伪造不支持能力 |
| Python | 数据读取、质量校验、回测、指标、报告文件生成 | 不接受隐式未来数据或隐式成本假设 |
| 配置文件 | 保存策略规则、假设、数据源、成本、日期和运行选项 | 不保存密钥，不覆盖原始行情 |
| 审计 | 阻止无效结果，标记条件性结论和能力阻塞 | 不把警告静默成 PASS |
| 用户 | 提供策略意图并确认关键假设 | 不通过自然语言绕过能力阻塞 |

Skill 不在每次运行中重新编写完整回测代码。它只生成配置并调用固定的本地 Python 接口或已有脚本。

### 4.3 当前能力的硬边界

当前可正式编排的基线是：

- 标的：SPY、QQQ。
- 数据：已验证的本地标准化日线 CSV；Futu OpenD 日线下载和本地增量合并是正式数据路径。
- smoke test：可以显式使用 yfinance，但结果必须带 SMOKE_TEST_ONLY 标记，不得作为正式结论的数据来源。
- 策略：现有固定 EMA50/EMA200 多头基线。
- 成交：默认下一根 K 线开盘成交。
- 成本：手续费和滑点必须显式进入配置和回测。
- 基准：对应标的的 Buy and Hold。

现有权威数据契约和 docs/superpowers/specs/、docs/superpowers/plans/ 中已冻结的时间、日历、哈希、Manifest、Walk-forward 和 Locked OOS 规则继续有效。本设计只规定 Skill 如何识别和调用这些规则，不重新定义它们。

## 5. quant-strategy-spec 设计

### 5.1 职责

quant-strategy-spec 是输入标准化和能力检查 Skill，不执行回测。它必须：

1. 把自然语言规则转换为结构化 YAML。
2. 规范标的、周期、日期、资金、入场、退出、仓位、成本和成交时点。
3. 将用户请求映射到能力注册表，判断当前引擎是否支持。
4. 识别未说明但会影响结果的关键假设。
5. 拒绝补造无法确认的参数、数据、成交路径或期权报价。
6. 输出可供 quant-research-pipeline 消费的配置和能力检查结果。

该 Skill 不调用 Futu、不调用 yfinance、不运行回测，也不计算绩效。

### 5.2 配置契约

策略配置至少包含以下字段：

~~~yaml
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
commission_model:
  type: basis_points
  value: 5
slippage_model:
  type: basis_points
  value: 5
fill_timing: next_bar
data_source: validated_local_cache_first
in_sample_period: null
out_of_sample_period: null
optimization_allowed: false
report_language: zh-CN
~~~

默认值和约束如下：

| 字段 | 默认或约束 |
|---|---|
| fill_timing | next_bar |
| optimization_allowed | false |
| report_language | zh-CN |
| benchmark | 对应标的 Buy and Hold |
| data_source | validated_local_cache_first |
| symbol | 第一阶段仅允许 SPY、QQQ |
| asset_class | 第一阶段仅允许 equity |
| timeframe | 第一阶段仅允许现有日线基线支持的周期 |

null 只表示该字段在当前基线中不启用，不表示由 Skill 猜测值。日期、成本、成交时点、数据源和关键策略参数缺失时，配置检查必须失败或要求用户补充。

### 5.3 能力检查输出

能力检查输出包含：

- supported：当前配置可以进入正式流水线。
- unsupported_rules：具体不支持的规则及原因。
- required_data：运行所需的数据类型和字段。
- required_engine：需要的回测引擎能力。
- blocking_status：STRATEGY_CAPABILITY_BLOCKER 或 DATA_CAPABILITY_BLOCKER。
- next_development_request：可执行的后续开发需求，不生成伪回测结果。

例如，用户请求 RSI、MACD、多标的轮动、期权链或 IBKR 时，Skill 必须返回明确 blocker，而不是把规则近似成 EMA 或使用缺失数据。

## 6. quant-research-pipeline 设计

### 6.1 固定阶段

| 阶段 | 名称 | 必须完成的动作 | 失败结果 |
|---|---|---|---|
| Stage 0 | 解析和标准化策略 | 读取策略文本并生成 YAML | STRATEGY_CAPABILITY_BLOCKER |
| Stage 1 | 能力检查 | 检查标的、周期、规则、数据和引擎 | blocker，禁止回测 |
| Stage 2 | 选择和验证数据 | 优先读取 Futu 本地缓存，检查来源、范围、哈希和可用性 | DATA_CAPABILITY_BLOCKER |
| Stage 3 | 数据质量检查 | 检查重复、缺失、排序、时间、价格和交易日历要求 | FAIL，禁止回测 |
| Stage 4 | 无优化基线回测 | 调用现有 Python EMA 引擎，使用配置中的成本和 next_bar | FAIL |
| Stage 5 | Buy and Hold 基准 | 使用相同时间范围、价格空间、资金、手续费和滑点假设 | FAIL |
| Stage 6 | 回测审计 | 调用 quant-backtest-audit 并记录所有检查项 | 审计状态阻止正式结论 |
| Stage 7 | 中文报告 | 先生成紧凑摘要，再按请求生成详细审计 | 报告缺失则 FAIL |

### 6.2 执行规则

- 任一阶段失败立即停止，保留失败阶段、错误类别、输入配置和运行标识。
- 不得跳过数据检查，不得用 LLM 输出替代 Python 计算。
- 不得默认优化，不得执行参数搜索，不得根据结果反向修改配置。
- 不得默认重复下载相同数据；优先使用通过质量检查的本地缓存。
- yfinance 仅用于显式 smoke test，不能替代正式 Futu 本地数据。
- 正式结论必须优先使用已验证的 Futu 本地数据；Futu OpenD 未启动、未登录、配额不足或缓存不满足范围时停止。
- 每次运行保存策略配置、配置哈希、数据来源、数据文件哈希、运行参数、结果、审计状态和假设。
- 运行输出写入独立运行目录，不覆盖原始行情、不覆盖既有报告。
- 当前阶段不连接真实交易账户，不发送订单。

### 6.3 运行记录

每次运行至少记录：

~~~text
run_id
strategy_config_hash
data_manifest_hash_or_file_hash
engine_code_revision
data_source
symbol
timeframe
data_start_utc
data_end_utc
commission_bps
slippage_bps
fill_timing
optimization_allowed
benchmark_type
audit_status
generated_at_utc
~~~

如果当前遗留日线基线无法提供完整 Data Manifest，运行仍可作为 smoke test 或条件性基线运行，但不得将缺失的来源和哈希描述为已完成的正式审计证据。

## 7. quant-backtest-audit 设计

### 7.1 检查范围

审计至少检查：

- look-ahead bias 和未来函数。
- 同一根 K 线的信号与成交是否被错误合并。
- next_bar fill 是否实际使用下一根可交易 K 线。
- 手续费和滑点是否进入每笔成交及最终权益。
- 数据缺失、重复、乱序、无效价格和无效成交量。
- UTC 时间、报告时区和交易日历。
- 训练区、Walk-forward 区和 Locked OOS 的污染边界。
- 参数搜索泄漏和优化开关是否保持 false。
- 交易次数过少、单笔交易支配总收益、年度收益过度集中。
- 策略与 Buy and Hold 是否使用相同时间、资金、价格和成本假设。
- 相同配置、代码版本和数据哈希是否产生可复现结果。
- 当前引擎和数据源是否真的支持该策略。

审计应优先读取交易明细、权益曲线、输入配置、数据质量结果和运行记录，而不是从自然语言摘要反推结果。

### 7.2 审计状态

审计结果只能为以下五种之一：

| 状态 | 含义 | 是否允许继续 |
|---|---|---|
| PASS | 所有必需检查通过，能力、数据、执行和复现证据完整 | 允许生成正式基线报告；仍不代表允许实盘 |
| CONDITIONAL_PASS | 回测结果可解释，但存在明确的非致命证据缺口，例如遗留基线缺少完整 Manifest | 允许生成条件性报告；禁止晋级、优化或声称 OOS 通过 |
| FAIL | 数据、执行、成本、偏差、复现或报告检查失败 | 不允许正式结论 |
| STRATEGY_CAPABILITY_BLOCKER | 策略规则超出当前引擎能力 | 不运行伪回测，返回后续开发需求 |
| DATA_CAPABILITY_BLOCKER | 所需数据、范围、来源或验证证据不可用 | 不运行回测，返回数据补齐需求 |

FAIL 与两个 blocker 都必须阻止后续报告中的“策略通过”表述。CONDITIONAL_PASS 只能输出条件性结果和限制，不能被下游自动晋级流程当作 PASS。

## 8. 能力阻塞规则

当前系统无法执行的策略必须阻止，不得临时编造实现、替换规则或调用未经固定版本的用户级 Skill。

以下请求示例必须阻塞：

| 用户请求 | 阻塞原因 |
|---|---|
| RSI 规则 | 当前 EMA 基线没有 RSI 指标引擎 |
| MACD 规则 | 当前 EMA 基线没有 MACD 指标引擎 |
| 多标的轮动 | 当前回测命令按单个受支持标的运行 |
| 期权策略 | 没有期权链、Bid/Ask、到期日和合约生命周期数据 |
| IBKR 数据 | 当前没有 IBKR provider |
| TradingView Pine 执行 | 当前没有 Pine 执行或 Webhook 链路 |
| Walk-forward | 当前只有设计约束，没有可调用的验证实现 |
| 参数优化 | 第一阶段显式禁止优化 |
| Monte Carlo | 第一阶段没有该分析实现 |

输出必须包含：

~~~text
STRATEGY_CAPABILITY_BLOCKER
unsupported_rule: <具体规则>
reason: <底层能力缺失>
next_development_request: <最小后续实现范围>
~~~

数据不可用时使用 DATA_CAPABILITY_BLOCKER，不得用 yfinance、随机值、近似指标或人工估算替代正式数据。

## 9. 与现有代码的集成边界

第一阶段只包装和编排现有能力，优先调用以下现有模块和脚本：

- src/tv_quant/futu_downloader.py：Futu 日线读取和本地 CSV 增量更新。
- src/tv_quant/futu_quota.py：Futu 配额检查和配额日志。
- src/tv_quant/data_quality.py：标准化 OHLCV 校验和合并。
- src/tv_quant/downloader.py：SPY/QQQ 日线和 yfinance 下载能力。
- src/tv_quant/strategy.py：固定 EMA50/EMA200、下一根开盘成交、手续费和滑点。
- src/tv_quant/metrics.py：基础收益指标和 Buy and Hold 收益。
- src/tv_quant/reporting.py：JSON、equity CSV 和 trades CSV 输出。
- src/tv_quant/cli.py：现有 download/backtest CLI。
- scripts/run_full_pipeline.ps1：现有端到端基线脚本，必须由显式流程调用，不得在 Skill 中复制其逻辑。

集成约束：

1. 不重复实现已有数据下载、数据质量、EMA 回测、metrics 和报告逻辑。
2. 新适配层只承担配置转换、能力检查、阶段编排和审计封装。
3. 不修改现有 Phase 1 数据契约，不改变原始行情数据，不隐式改变价格空间或时间语义。
4. 不把当前设计文档中的未来 phase1_data、Walk-forward 或 Locked OOS 计划描述为现有代码能力。
5. 任何新能力必须先加入能力注册表、定义输入和输出、添加测试，再开放给策略配置。

## 10. 文件结构

以下是后续实施的目标结构。本次只创建本设计文档，不创建这些文件：

~~~text
.agents/
  skills/
    quant-strategy-spec/
      SKILL.md
      references/
    quant-research-pipeline/
      SKILL.md
      references/
    quant-backtest-audit/
      SKILL.md
      references/

config/
  strategies/
  backtest-defaults.yaml

scripts/
  quant/
    run_pipeline.ps1

tests/
  skills/
  pipeline/

reports/
  runs/
~~~

项目级 Skill 的 SKILL.md 只保存简短的 frontmatter、触发条件、输入输出、阶段规则和安全边界。较长的规则进入同一 Skill 的 references/，避免每次运行读取大型文档。

## 11. 用户级 Skills 处理原则

- 当前任务不移动、删除、停用或重写用户级 Skill。
- 用户级重复项另立任务处理，并且不作为本流水线的隐式依赖。
- 项目级 Skill 优先于依赖全局 Skill；同名项目 Skill 的行为由项目版本控制。
- 项目流水线不能依赖未固定版本、未审查来源或运行时不可验证的用户级 Skill。
- AlphaGBM Skills 只作为期权或市场分析辅助，不作为本项目历史回测引擎。
- 自动交易、高风险执行和账户连接 Skill 不得进入第一阶段流水线。
- 如果用户请求依赖某个用户级 Skill，流水线先检查其能力和版本；检查失败时阻塞，不静默替换。

## 12. Token 控制设计

1. 策略规则保存为 YAML；运行时传递配置路径和运行标识，不重复传递整段自然语言。
2. 回测计算由本地 Python 执行，LLM 只负责转换、校验、解释和摘要。
3. Skill 只引用简短、稳定、版本化的 references。
4. 报告默认先输出紧凑摘要，包括状态、标的、日期、数据源、总收益、最大回撤、交易数、Buy and Hold 差异和限制。
5. 只有用户要求时才生成逐笔交易、年度分解和完整审计解释。
6. 不重复读取大型设计文档；运行记录引用文档版本和配置哈希。
7. 不每次重新生成回测代码。
8. 不默认执行 Monte Carlo、参数优化、Walk-forward 或多策略比较。
9. 错误输出只保留必要上下文、阶段、原因和下一步，不输出密钥、账户资料或完整大文件。

## 13. 错误处理

错误必须包含运行阶段、错误类别、用户可理解的原因和可执行的下一步。至少覆盖：

| 情况 | 处理 |
|---|---|
| Futu OpenD 未启动或未登录 | 返回数据能力错误，提示启动并登录 OpenD；不静默切换正式数据源 |
| Futu 配额不足 | 停止下载，记录配额状态和代码，不继续正式回测 |
| 本地缓存缺失 | 如果请求正式研究，返回 DATA_CAPABILITY_BLOCKER；仅用户明确要求 smoke test 时才允许 yfinance |
| 数据时间范围不足 | 返回数据能力错误，显示需要范围与实际范围 |
| 不支持的策略规则 | 返回 STRATEGY_CAPABILITY_BLOCKER，列出规则和后续开发请求 |
| 测试失败 | 停止流水线，不生成通过性结论，保留失败测试和提交版本 |
| 回测返回空交易 | 允许生成事实报告，但审计标记交易样本不足；不得把空交易自动解释为策略有效 |
| 结果文件缺失 | 审计为 FAIL，不读取残缺报告 |
| 审计失败 | 停止晋级和正式结论，只输出失败原因 |
| 期权历史回测请求但没有期权链数据 | 返回 DATA_CAPABILITY_BLOCKER，不使用股票价格近似期权结果 |
| 用户请求实盘或自动下单 | 返回范围阻塞，明确当前阶段禁止账户连接和订单发送 |

## 14. 测试策略

后续实现必须加入自动化测试，至少包括：

- 每个 Skill frontmatter 合法，且 name 与目录名一致。
- 三个 Skill 名称不重复，项目级发现路径正确。
- 总控 quant-research-pipeline 能被发现并调用固定阶段。
- 工作流顺序固定为 Stage 0 至 Stage 7，不允许跳过 Stage 2 或 Stage 3。
- 数据检查失败阻止回测调用。
- 能力检查失败返回相应 blocker，且不创建伪结果。
- 审计 FAIL 阻止正式报告或晋级。
- optimization_allowed 缺省为 false，任何第一阶段优化请求都会被拒绝。
- yfinance 结果带有 SMOKE_TEST_ONLY 标记，不能进入正式结论路径。
- 没有期权数据时阻止期权回测。
- 任意流水线路径都不触发实盘账户或真实订单。
- 相同输入配置、代码版本和数据哈希产生可重复的配置和结果标识。
- 策略与 Buy and Hold 使用相同时间范围、资金、价格和成本假设。
- Futu OpenD 未启动、配额不足、本地缓存缺失和结果文件缺失均能得到明确错误。
- 对现有 EMA 基线的集成测试不修改既有数据契约或原始行情文件。

测试必须在不安装外部 Skill、不连接真实账户和不依赖网络数据的条件下完成。真实 Futu OpenD 验证属于单独审批的操作门，不属于本 Skill 测试。

## 15. 验收条件

第一阶段实施完成必须满足：

1. 三个项目级 Skill 存在，名称、frontmatter 和发现路径正确。
2. 中文 EMA 策略能够生成合法结构化配置。
3. EMA 示例能够完成一键流水线，且每个阶段都有运行记录。
4. 数据检查自动运行，任何数据质量失败都会阻止回测。
5. Buy and Hold 自动比较，并使用相同时间和成本假设。
6. quant-backtest-audit 输出五种允许状态之一。
7. RSI 示例返回 STRATEGY_CAPABILITY_BLOCKER，不运行伪回测。
8. 第一阶段不运行优化、Monte Carlo、Walk-forward 或多策略搜索。
9. 不接触实盘、不连接真实交易账户、不发送订单。
10. 所有新增 Skill、编排、审计和适配测试通过。
11. 运行配置、数据来源、哈希、结果和审计状态可追溯。
12. 回滚方式明确，删除项目级 Skill 不影响用户级 Skill 和现有 Python 基线。
13. 用户只需调用 quant-research-pipeline 即可启动受控工作流。

条件性报告不能替代上述正式验收。第一阶段只有全部条件满足后，才允许评估第二阶段。

## 16. 第二阶段进入条件

只有第一阶段全部通过，并且已保留可复现的验收证据后，才允许：

- 引入 vectorbt-backtest-adapter。
- 扩展 RSI、MACD、动量和均值回归。
- 增加 strategy-compare。
- 增加 walk-forward-validation。
- 增加 Monte Carlo。
- 评估外部 GitHub Skills。

第二阶段仍必须：

- 复用 Futu 本地缓存和已验证的数据质量链路。
- 使用统一手续费、滑点和 next_bar fill。
- 经过统一回测审计。
- 维护训练区、Walk-forward 区和 Locked OOS 的隔离。
- 为每次新增能力定义固定版本、输入契约、测试和回滚点。

## 17. 回滚方案

- 所有新增功能位于独立分支；本设计提交使用 codex/quant-skills-pipeline。
- 项目级 Skill 可整体删除而不影响用户级 Skill。
- 不修改原始行情数据，不覆盖已有报告或现有权威文档。
- 每个实施阶段独立提交，提交范围只包含该阶段声明的文件。
- 失败时可以删除项目级 Skill 目录、删除流水线配置和脚本，并保留现有 Python 基线。
- 失败时可以删除对应 worktree 或重置该功能分支；不得重置包含用户未提交工作的主工作树。
- 不触碰主工作树未跟踪目录，不把用户级 Skill 作为回滚对象。
- 当前设计阶段只提交本文档，不推送远程；后续实施和远程 PR 需要单独审批。

## 18. 实施阶段划分

后续实施顺序如下，本设计阶段不执行这些步骤：

1. 创建三个项目级 Skill 的骨架和配置契约。
2. 实现 quant-strategy-spec 的自然语言到 YAML 转换和能力检查。
3. 实现 quant-research-pipeline 的固定阶段编排和运行记录。
4. 实现 quant-backtest-audit 的审计检查和五态结果。
5. 添加 Skill、流水线、阻塞和回滚测试。
6. 使用现有 EMA 基线执行离线 smoke test。
7. 根据验收条件完成第一阶段审查。
8. 只有第一阶段通过后，决定是否进入 VectorBT 和其他第二阶段能力。

本文档本身不创建 Skill、不修改 Python、PowerShell、测试、requirements.txt、AGENTS.md 或现有权威设计文档。
