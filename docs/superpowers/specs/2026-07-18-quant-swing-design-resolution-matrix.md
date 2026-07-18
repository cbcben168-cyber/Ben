# 量化波段冻结设计问题解决矩阵

## 文档定位

本矩阵针对冻结设计文档 `2026-07-18-quant-swing-research-system-design.md` 的独立审查结果，逐项冻结解决方案。它只解决设计问题，不提交实现代码，不改变原冻结设计。

审查基线提交：`d4a9cd4 Add frozen quant swing research system design`

矩阵状态使用以下约定：

- `resolved=DESIGN_RESOLVED`：设计层已有确定答案，可进入对应实施阶段。
- `resolved=IMPLEMENTATION_PENDING`：设计已确定，但仍需在实施阶段通过测试验证。
- `residual_risk` 必须保留，即使设计问题已经解决。

## 冻结公共契约

### 数据、日历与时间

1. 内部标准时区为UTC；交易日历和交易时段使用`America/New_York`及XNYS交易日历。
2. 原始30分钟记录必须保存`source_timestamp`、`bar_start_local`、`bar_end_local`、`bar_start_utc`、`bar_end_utc`、`session_date`、`is_regular_session`、`is_early_close`和`source`。
3. 内部时间戳统一表示K线开始时间。Futu `time_key`必须通过固定fixture验证其开始/结束时间语义后再转换，禁止直接假设。
4. 正常完整交易日必须有13根RTH 30分钟柱：09:30、10:00、10:30、11:00、11:30、12:00、12:30、13:00、13:30、14:00、14:30、15:00、15:30。前12根组成6根完整60分钟研究柱，15:30柱为尾盘辅助柱。
5. 盘前盘后数据不得进入RTH研究数据。正常日出现缺失、重复、重叠、乱序或非30分钟长度柱时，整个数据集质量检查失败，不得启动回测。
6. 提前收市日由XNYS日历识别，不根据数据数量猜测；不生成研究信号，只允许已有仓位风险处理和估值。DST先本地化再转UTC，禁止使用固定UTC偏移。
7. 每个数据集必须生成Data Manifest和SHA-256指纹。

### 日线聚合与拆股事件

1. 日线OHLC必须由同一Futu 30分钟RTH数据按`session_date`聚合：`daily_open`为第一根RTH柱open，`daily_high`为当日RTH high最大值，`daily_low`为当日RTH low最小值，`daily_close`为最后一根RTH柱close，`daily_volume`为RTH volume总和。
2. 禁止混用Futu独立日线或yfinance日线。提前收市日允许生成日线供下一交易日使用，但当天不生成60分钟研究信号。
3. 拆股事件必须记录来源、日期、比例、获取时间和SHA-256；禁止猜测拆股比例。未验证拆股事件时数据状态为`DATA_ACTIONS_UNVERIFIED`，该状态不得进入正式回测。
4. `research` OHLC只应用已验证的拆股因子，不调整分红；`raw` OHLC不得被改写。拆股事件和价格字段必须在Data Manifest中关联。

### 日线滞后、指标与结构

1. 交易日D的全部盘中决策只读取截至D-1收盘完成的日线数据。D日收盘生成的日线状态从D+1开始使用。日线EMA、ATR、波动率和市场环境均遵守该规则。
2. 已确认pivot使用`left_bars=2`、`right_bars=2`；右侧第2根完整60分钟柱收盘后才可见。
3. 最近确认更高低点是最新确认pivot low高于前一个确认pivot low；更高高点同理。回调结构低点是回调开始至恢复信号柱之前已发生的最低`research_low`；恢复位是该低点出现后至恢复信号柱之前已发生的最高`research_high`，恢复信号柱不得参与计算。
4. 60分钟EMA20斜率为`(EMA20当前值-EMA20五根研究柱前值)/当前60分钟ATR20`，大于0.10为向上，区间`[-0.10,0.10]`为转平，小于-0.10为向下。
5. 日线EMA200斜率为`(EMA200当前值-EMA200二十个交易日前值)/当前日线ATR20`，大于0.25为向上，区间`[-0.25,0.25]`为接近平坦，小于-0.25为明显向下。
6. 短期保护线固定为60分钟EMA20；突破过度扩张定义为恢复信号柱收盘价减恢复位大于`0.75*60分钟ATR20`；波动持续扩大定义为ATR20连续3根完整60分钟柱上升且当前ATR20高于此前20根ATR20中位数的1.10倍。删除不能独立编码的“价格停止恶化”等表述。

### 仓位、事件和成交

1. 日线波动率使用split-adjusted、dividend-unadjusted的日线`research_close`收盘到收盘对数收益。20日已实现波动率为最近20个完成交易日日收益的样本标准差乘`sqrt(252)`；基准为最近252个已完成20日波动率值的中位数。D日盘中只用D-1数据，暖机期至少271个完成交易日，历史不足时目标仓位为0%。
2. 目标美元仓位为当前账户权益乘最终仓位百分比。目标下降一次调整到新目标；目标上升须连续2根完整60分钟柱保持有效，期间风险上升或目标下降会将加仓计数器清零。
3. 每根30分钟柱唯一事件顺序为：开盘处理已有仓位跳空止损；处理上一根完成柱生成的清仓订单；处理减仓订单；处理入场/加仓订单；退出与入场冲突时退出优先且入场取消并记录冲突；随后用本柱low检查止损；新仓可在同柱触发止损；每个时间戳最多一个最终目标仓位订单；收盘更新估值，完整60分钟柱收盘后更新指标和状态并生成下一根可交易柱订单。15:30–16:00辅助柱不生成新策略信号。
4. 长仓止损若`raw_open<=stop_price`，成交价为`raw_open*(1-stop_slippage_bps/10000)`；否则若`raw_low<=stop_price`，成交价为`stop_price*(1-stop_slippage_bps/10000)`；成交价不得低于0。必须保存止损价、原始开盘、原始最低、成交价、是否跳空穿越和滑点。
5. 普通时段首次入场一次进入完整目标仓位。15:30尾盘入场是唯一例外，首次上限50%；次日只有D-1日线强势多头、波动率目标至少75%、次日前两根完整60分钟柱均为强势且未触发止损/弱化/失效时，才在下一根可交易30分钟柱开盘恢复完整目标。该恢复同时使用一般连续2根确认规则。

### 验证、报告与范围

1. 交易生命周期从首次仓位0变为正数开始，到重新回到0结束；部分加减仓仍属于同一`trade_lifecycle_id`，每个成交有独立`fill_id`和`order_id`。`initial_1R = 首次成交加权价格 - 当时有效止损价`。后续加仓可以改变当前平均成本，但不能重写`initial_1R`；初始止损不得向下放宽。生命周期MFE、MAE和0.75R时间进展检查均使用冻结的`initial_1R`。
2. 交易次数为已完成生命周期数；胜率为正生命周期净PnL除以已完成生命周期数；Profit Factor无亏损交易时为`null`且状态为`NO_GROSS_LOSS`，无完成PnL时为`null`且状态为`NO_COMPLETED_PNL`；Sharpe在日收益标准差为0时为`null`且状态为`ZERO_VARIANCE`；最大回撤基于每日收盘账户权益；Buy and Hold最大回撤为0时相对回撤改善为`null`且关卡状态为`NOT_APPLICABLE`；权益归零或为负时CAGR为`null`且状态为`CAPITAL_DEPLETED`并直接淘汰。报告禁止用0替代无定义指标。同时报告交易日数和完整60分钟柱数；资金利用率为每根30分钟柱`abs(position_market_value)/equity`的时间加权平均；MFE/MAE使用生命周期内30分钟raw high/low、初始加权平均入场价和冻结的初始1R。
3. Buy and Hold同时报告`PRIMARY_PRICE_ONLY`和`COMPARABLE_COST`。前者不计分红、利息、手续费或滑点；后者使用相同raw价格，在第一根可交易柱买入、最后交易日收盘卖出，并承担一次买入和一次卖出的普通手续费及滑点。主目标使用前者，审计报告必须同时展示后者。
4. 最大回撤20%是目标；超过25%是绝对硬淘汰线；相对`PRIMARY_PRICE_ONLY` Buy and Hold回撤改善至少25%是相对硬门槛。候选必须同时满足策略最大回撤不超过25%及相对改善至少25%；20%以内表示目标达成但不是额外硬门槛，任何硬门槛失败不得由其他指标补偿。
5. 进入Walk-forward前，总历史至少90个月，研发区至少24个月，至少6个完整测试窗口，Locked OOS至少18个月；串联测试至少18个完成生命周期且至少4个测试窗口有实际交易。否则状态为`HOLD_INSUFFICIENT_SAMPLE`，不得宣称通过或失败；切分日期必须进入Data Manifest和报告。
6. Locked OOS存储于`C:\Users\cbcbe\TradingCodex\locked_oos_store\`，普通配置不得包含其路径。Stage 1只接收研发和Walk-forward路径。封存记录dataset_id、日期、SHA-256、行数、来源、生成时间；候选冻结后生成不可变candidate package，包含候选ID、策略配置hash、代码提交、数据Manifest hash和实验历史hash。每次正式评估创建唯一`oos_attempt_id`，状态只能为`CREATED`、`RUNNING`、`COMPLETED`、`FAILED_BEFORE_RESULT`或`FAILED_AFTER_RESULT`。只有`FAILED_BEFORE_RESULT`、没有任何结果持久化且全部数据/代码/配置hash完全一致时，才允许一次技术重试；`COMPLETED`或`FAILED_AFTER_RESULT`后禁止再次正式评估。所有尝试和重试必须写入审计日志。只能通过独立命令显式解锁，正式评估只运行一次并记录操作者、时间、数据hash、代码提交和配置hash。
7. 进入Locked OOS后候选包不可修改；任何代码、参数、配置或数据修改都创建新candidate_id。Locked OOS失败直接REJECTED。SPY/IWM/RSP首次运行属于外部稳健性验证；若结果影响后续修改，对该策略家族标记为OBSERVED。新独立证据必须来自新未来数据、尚未使用的DIA、第二独立数据源、TradingView前向测试或券商模拟。
8. 每轮最多150个新实验，每个策略家族最多3轮，累计最多450个；连续两轮没有Walk-forward改善则提前停止。登记总实验数、轮数、淘汰数、参数空间和排名变化，并报告完整筛选过程。第一版不宣称普通Sharpe已校正选择偏差。
9. 报告机器字段至少包括`schema_version`、`dataset_id`、`data_manifest_hash`、`candidate_id`、`experiment_id`、`strategy_family`、`config_hash`、`code_commit`、`stage`、`cost_scenario`、`benchmark_type`、`run_id`、`result_id`、`data_start`、`data_end`、`total_return`、`CAGR`、`max_drawdown`、`Sharpe`、`Profit_Factor`、`trade_count`、`win_rate`、`average_holding_days`、`average_holding_bars`、`capital_utilization`、`MFE`、`MAE`、`role_decisions`、`veto_status`、`veto_reason`、`contamination_status`、`approval_status`、`metric_status`和`generated_at_utc`。机器结果唯一键统一为`candidate_id + experiment_id + stage + cost_scenario + benchmark_type`；每次程序运行另生成不可变`run_id`和`result_id`。JSON、CSV和DuckDB使用同一唯一键，不得定义冲突主键；以`fill_id`、`order_id`、`trade_lifecycle_id`和`oos_attempt_id`关联明细和审计记录。

## 问题解决矩阵

| finding_id | severity | affected_sections | exact_resolution | specification_text | required_tests | implementation_phase | resolved | residual_risk |
|---|---|---|---|---|---|---|---|---|
| B-01 | BLOCKER | 原设计4.2、4.3、30 | 采用XNYS日历、America/New_York本地化、UTC开始时间；固定13根RTH 30分钟柱和完整性失败规则；保存全部时间和来源字段。 | 正常日必须有09:30至15:30共13根RTH柱；前12根组成6根60分钟柱，15:30为辅助柱；缺失、重复、重叠、乱序或长度异常即数据集失败。 | DST跨越、普通日、节假日、半日市、盘前盘后、缺失/重复/重叠/乱序/错误长度fixture。 | 1 数据契约 | IMPLEMENTATION_PENDING | Futu `time_key`语义必须由fixture实测；供应商异常仍会导致数据集停用。 |
| B-02 | BLOCKER | 原设计7、16、30 | 所有D日盘中决策统一读取D-1完成日线，日线EMA、ATR、波动率和环境不例外。 | 修改D日收盘价不得改变D日盘中任何信号或目标仓位。 | 故意修改D日close的不变性测试；D/D+1状态边界测试。 | 2 指标引擎 | IMPLEMENTATION_PENDING | 数据修订会改变D+1及以后结果，必须保留版本指纹。 |
| B-03 | BLOCKER | 原设计4.2、4.4、11、12 | 固定每根30分钟柱的开盘、盘中、收盘事件顺序；冲突时退出优先且取消入场；辅助柱不产新信号。 | 一个时间戳最多一个最终目标仓位订单，所有取消事件写冲突日志。 | 同柱止损/清仓/减仓/入场；尾盘柱；已有仓位与新仓冲突；重复订单。 | 4 事件引擎 | IMPLEMENTATION_PENDING | 30分钟OHLC无法揭示止损与其他盘中路径的真实先后，只能采用冻结的保守规则。 |
| B-04 | BLOCKER | 原设计8、9、11、13 | pivot使用2/2右侧确认；确认前不可见；回调低点和恢复位只使用恢复信号柱之前已发生数据。 | pivot在右侧第2根完整60分钟柱收盘后才可见；当前恢复信号柱不得参与恢复位计算。 | pivot确认延迟、确认前不可用、信号柱排除、连续高低点和重启结构测试。 | 3 策略纯函数 | IMPLEMENTATION_PENDING | 2/2及其他邻域仍会产生模型选择风险，Locked OOS不得反馈。 |
| B-05 | BLOCKER | 原设计6、7、8、9、11、12 | 用ATR标准化斜率、固定保护线、固定扩张阈值和ATR连续上升规则替换主观词；所有比较符号显式冻结。 | 60分钟斜率五柱/ATR20阈值±0.10；日线斜率20日/ATR20阈值±0.25；扩张阈值0.75 ATR；波动扩张为ATR连续3柱上升且超过20柱中位数1.10倍。 | 边界等于阈值、缺少暖机数据、NaN、斜率方向和扩张条件测试。 | 3 策略纯函数 | IMPLEMENTATION_PENDING | 阈值仍属于首轮基准，必须记录邻域实验。 |
| B-06 | BLOCKER | 原设计16.2、22、28 | 将Locked OOS路径、候选包、hash封存、独立解锁命令、一次性评估和尝试状态机写入流程约束。 | 普通实验命令拒绝Locked OOS路径；每个`oos_attempt_id`只能按冻结状态机运行；解锁记录候选、操作者、时间、hash和代码提交。 | 路径拒绝、hash不匹配拒绝、重复正式评估拒绝、`FAILED_BEFORE_RESULT`单次重试、`FAILED_AFTER_RESULT`和`COMPLETED`拒绝重试、Stage 1路径白名单测试。 | 9 Locked OOS | IMPLEMENTATION_PENDING | Windows ACL/独立账户尚未纳入第一版，路径和命令隔离仍依赖实现正确性。 |
| H-01 | HIGH | 原设计6、10 | 将尾盘50%明确定义为普通首次入场规则的唯一例外；次日完整目标恢复必须满足四项条件和通用两柱确认。 | 尾盘入场当日为day 0；满足D-1环境、波动率、次日前两柱强势且无风险事件后，在下一根30分钟柱开盘调整。 | 尾盘信号、次日两柱、条件失败、风险上限下降和恢复计数器重置测试。 | 5 仓位状态机 | IMPLEMENTATION_PENDING | 次日若遇半日市或缺失柱，必须按数据质量失败/提前收市规则处理。 |
| H-02 | HIGH | 原设计6.1、7、14 | 冻结对数收益、样本标准差、252年化、252个20日值中位数、271日暖机和D-1滞后。 | 历史不足271个完成交易日时目标仓位为0%，不得缩短窗口。 | 手工波动率值、暖机边界、D-1滞后、样本标准差和中位数窗口测试。 | 2 指标引擎 | IMPLEMENTATION_PENDING | 数据源修订、异常值和非交易日缺失仍需由Data Manifest追踪。 |
| H-03 | HIGH | 原设计6.1、8、10、25 | 目标下降一次调整；目标上升连续两根完整60分钟柱确认；任何风险上升或目标下降清零加仓计数器；账户权益决定目标美元仓位。 | 每个时间戳只允许一个最终目标仓位订单，状态机保留待确认计数器和取消原因。 | 多重上限变化、连续确认中断、减仓后恢复、相关性变化和现金不足测试。 | 5 仓位状态机 | IMPLEMENTATION_PENDING | 多标的组合相关性规则后置，单标的状态机与组合状态机仍需隔离。 |
| H-04 | HIGH | 原设计9.3、11 | 止损开盘穿越使用raw_open，不再使用“附近”；盘中触发使用stop_price；滑点对长仓卖出不利且价格不低于0。 | `raw_open<=stop_price`时用raw_open滑点价，否则`raw_low<=stop_price`时用stop_price滑点价。 | 正常触发、开盘跳空、等于止损、极端低价和辅助柱止损测试。 | 4 事件引擎 | IMPLEMENTATION_PENDING | 30分钟数据无法表达柱内真实成交路径，结果是规则化估计。 |
| H-05 | HIGH | 原设计15、21、31 | 冻结生命周期、initial_1R、fill/order ID、部分成交归集、异常指标状态、Profit Factor、Sharpe、持仓时间、资金利用率和MFE/MAE公式。 | 生命周期从首次0到正仓位开始；`initial_1R`由首次成交加权价格减当时有效止损价确定，后续加仓不得重写，初始止损不得向下放宽；无定义指标使用null和状态码。 | 部分加仓/减仓、多个fill、初始止损不可下移、未平仓生命周期、无亏损、无完成PnL、零方差、B&H零回撤和权益耗尽测试。 | 6 单ETF回测与报告 | IMPLEMENTATION_PENDING | 生命周期统计对极少交易样本仍不稳定，必须报告样本数量。 |
| H-06 | HIGH | 原设计2.2、18 | 同时生成无成本价格基准和承担一次买卖成本的可比基准；主目标固定使用PRIMARY_PRICE_ONLY。 | 报告不得隐藏两种Buy and Hold口径及其差异。 | 两种基准的起止柱、raw价格、手续费、滑点和零分红测试。 | 6 单ETF回测与报告 | IMPLEMENTATION_PENDING | 价格基准不含分红，仍低估完整Total Return。 |
| H-07 | HIGH | 原设计2.1、16.3、18 | 20%为目标，>25%为绝对淘汰，回撤相对PRIMARY_PRICE_ONLY改善至少25%为硬门槛；硬门槛不可互相补偿。 | 候选必须同时满足策略最大回撤≤25%及相对改善≥25%；20%以内只表示目标达成。 | 边界20%、25%、恰好25%、相对改善边界和门槛失败优先级测试。 | 6 单ETF回测与报告 | IMPLEMENTATION_PENDING | B&H回撤极低或无回撤时，相对改善口径需定义为硬门槛失败并记录原因。 |
| H-08 | HIGH | 原设计16、30 | 增加历史可行性门槛：90个月历史、6个测试窗口、18个月Locked OOS、18个生命周期和4个有交易窗口。 | 不满足时输出`HOLD_INSUFFICIENT_SAMPLE`，不得宣称通过或失败。 | 边界历史长度、窗口数量、交易生命周期和空窗口测试。 | 8 Walk-forward | IMPLEMENTATION_PENDING | Futu实际可取得历史长度需在数据阶段验证，不能由设计假定。 |
| H-09 | HIGH | 原设计3、16.2、22、23 | Locked OOS后candidate package不可变；任意修改创建新候选；外部ETF结果影响修改时标记OBSERVED；TradingView bug修复重走验证，平台差异只记录parity；正式OOS尝试由`oos_attempt_id`审计。 | 新独立证据只能来自新未来数据、DIA、第二数据源、TradingView前向测试或券商模拟；`COMPLETED`和`FAILED_AFTER_RESULT`不得再次正式评估。 | 候选hash变更、新ID、外部结果状态、TradingView bug与平台差异分支、尝试状态和重试审计测试。 | 10 外部验证 | IMPLEMENTATION_PENDING | 外部ETF与TradingView仍可能产生研究者解释偏差，需保留污染状态。 |
| L-01 | LOW | 原设计21、31 | 统一机器结果唯一键、`run_id`、`result_id`和交易审计ID，并将候选、实验、阶段、成本情景、基准口径和交易明细关联。 | 唯一键统一为`candidate_id + experiment_id + stage + cost_scenario + benchmark_type`；每次运行另有不可变`run_id`和`result_id`；JSON、CSV、DuckDB不得冲突。 | 三种输出格式的相同主键、重复结果拒绝、run/result不可变、字段缺失和fill/order/lifecycle关联测试。 | 6 单ETF回测与报告 | IMPLEMENTATION_PENDING | DuckDB/CSV长期兼容性仍需版本迁移策略。 |
| H-11 | HIGH | 原设计4、5、7、16 | 日线只由同一Futu 30分钟RTH数据按session_date聚合，禁止Futu独立日线和yfinance日线；半日市可产生日线但当天不产60分钟信号。 | daily_open取第一根RTH open，daily_high取RTH high最大值，daily_low取RTH low最小值，daily_close取最后RTH close，daily_volume取RTH volume总和。 | 多日聚合、半日市日线、RTH过滤、首尾柱、volume求和、混合数据源拒绝和D-1使用测试。 | 1 数据契约 | IMPLEMENTATION_PENDING | 日线结果依赖30分钟数据完整性；供应商修订需重新生成Manifest。 |
| H-12 | HIGH | 原设计5、28、30 | 建立不可猜测的拆股事件契约；未验证事件标记`DATA_ACTIONS_UNVERIFIED`并禁止正式回测；research只应用拆股因子，raw不可改写。 | 拆股事件保存来源、日期、比例、获取时间和SHA-256；缺少验证不允许进入正式回测。 | 拆股来源字段、比例缺失拒绝、hash变更、状态阻断、research因子、raw不变和分红不调整测试。 | 1 数据契约 | IMPLEMENTATION_PENDING | corporate action来源可能发生历史修订，必须通过事件hash触发数据版本变化。 |
| M-05 | MEDIUM | 原设计21、31 | 用同一五字段组合作为JSON、CSV、DuckDB机器结果唯一键；run_id和result_id只追加不可变运行/结果身份，不替代业务唯一键。 | `candidate_id + experiment_id + stage + cost_scenario + benchmark_type`是跨格式唯一键。 | JSON/CSV/DuckDB schema互相校验、重复业务键拒绝、同一run多结果关联和result_id不可重写测试。 | 6 单ETF回测与报告 | IMPLEMENTATION_PENDING | 迁移旧报告时必须显式标记旧schema，不能静默映射。 |
| M-06 | MEDIUM | 原设计2、16、18、21 | 冻结所有无定义指标的null和状态码，禁止以0代替；异常状态参与关卡判定。 | 无亏损为`NO_GROSS_LOSS`；无完成PnL为`NO_COMPLETED_PNL`；零方差为`ZERO_VARIANCE`；B&H零回撤为`NOT_APPLICABLE`；权益归零/为负为`CAPITAL_DEPLETED`并淘汰。 | 各状态边界、JSON null、CSV空值、关卡状态传递、权益归零和负权益测试。 | 6 单ETF回测与报告 | IMPLEMENTATION_PENDING | 小样本下null指标仍可能被误读，摘要必须同时显示状态码。 |
| H-13 | HIGH | 原设计11、12、15 | 首次成交时冻结initial_1R；后续加仓只更新当前平均成本，不重写生命周期初始风险单位；初始止损只能保持或上移。 | MFE、MAE和0.75R进展检查全部使用冻结的initial_1R。 | 首次多fill加权价格、后续加仓、止损上移、禁止下移、0.75R检查和生命周期结束归集测试。 | 5 仓位状态机 | IMPLEMENTATION_PENDING | 首次成交价格与止损价异常时必须拒绝生命周期，而不是生成零或负R。 |
| H-14 | HIGH | 原设计16.2、22、28 | 为每次Locked OOS正式评估建立`oos_attempt_id`状态机：`CREATED`、`RUNNING`、`COMPLETED`、`FAILED_BEFORE_RESULT`、`FAILED_AFTER_RESULT`；仅允许符合全部条件的单次技术重试。 | `COMPLETED`或`FAILED_AFTER_RESULT`后禁止再次正式评估；所有尝试和重试写审计日志。 | 状态转移白名单、结果持久化前后失败、hash完全一致重试、hash变化拒绝、重复完成拒绝和审计完整性测试。 | 9 Locked OOS | IMPLEMENTATION_PENDING | 结果持久化检测必须覆盖临时文件、数据库事务和日志，避免失败状态判断错误。 |
| H-10 | HIGH | 原设计4、5、30 | 先建立30分钟raw/research双字段和Data Manifest，再替换当前日线管线；不把现有Futu K_DAY/QFQ或yfinance auto_adjust结果直接当作新研究数据。 | 现有日线EMA系统保持独立；30分钟系统以新数据契约为入口。 | raw/research字段、拆股/分红口径、旧日线输入拒绝和数据来源混用拒绝测试。 | 1 数据契约 | IMPLEMENTATION_PENDING | 当前仓库已有日线实现，两个系统并存期间需要清晰CLI和目录边界。 |
| M-01 | MEDIUM | 原设计17、18 | 每策略家族最多3轮、累计450实验；登记完整筛选过程、排名变化和淘汰数量；不宣称普通Sharpe已校正选择偏差。 | 连续两轮无Walk-forward改善则提前停止。 | 实验ID唯一性、累计预算、重复实验拒绝、停止规则和完整淘汰统计测试。 | 7 实验登记 | IMPLEMENTATION_PENDING | 第一版未实施Deflated Sharpe或其他多重测试校正。 |
| M-02 | MEDIUM | 原设计14、16、18 | 冻结1.5倍和2倍成本的数值门槛，并要求成本变化不改变信号和交易次数。 | 1.5倍需CAGR≥B&H 85%、回撤≤25%、相对改善≥15%、净收益为正；2倍需CAGR>0、PF≥1、回撤≤25%、收益下降≤35%、无负权益或异常。 | 三种成本场景、交易次数不变、信号不变、门槛边界和负权益测试。 | 6 单ETF回测与报告 | IMPLEMENTATION_PENDING | 固定bps不覆盖真实流动性冲击和极端跳空。 |
| M-03 | MEDIUM | 原设计12、14 | 入场日为day 0；下一交易所交易日为day 1；提前收市日计一个交易日；五日检查在day 5收盘后、十五日检查在day 15收盘后，退出在下一根可交易柱。 | 删除“约5日”和“约15日”。 | 普通入场、尾盘入场、半日市、周末/节假日和最后数据柱测试。 | 5 仓位状态机 | IMPLEMENTATION_PENDING | 交易日历版本变化会影响历史计数，必须锁定日历版本。 |
| M-04 | MEDIUM | 原设计28、30 | 将时间聚合、D-1滞后、pivot确认、事件顺序、止损、仓位、成本、报告和验证隔离分别设置纯函数/集成测试。 | 现有日线测试继续保留，不得替代新系统不变量测试。 | 每个冻结契约至少一个正常案例、边界案例和失败案例。 | 全部阶段 | IMPLEMENTATION_PENDING | 测试覆盖不能证明数据源本身没有历史修订，只能证明实现遵守契约。 |
| L-01 | LOW | 原设计21、31 | 冻结机器字段、JSON/CSV/DuckDB职责、统一五字段业务唯一键、不可变run/result身份，并将候选、实验、阶段、成本情景、基准口径和交易ID关联。 | JSON、CSV和DuckDB唯一键均为`candidate_id + experiment_id + stage + cost_scenario + benchmark_type`；每次运行另有不可变`run_id`和`result_id`。 | Schema校验、跨格式主键一致、主键重复、字段缺失、run/result不可重写、hash关联和UTC生成时间测试。 | 6 单ETF回测与报告 | IMPLEMENTATION_PENDING | DuckDB/CSV长期兼容性仍需版本迁移策略。 |
| L-02 | LOW | 原设计15、18 | 小数份额用于研究主结果，整数股用于执行审计；整数股结果参与执行可行性Risk Gate，并报告现金和仓位偏差。 | 两种份额模型共享同一信号、事件、成交和成本逻辑，只允许在数量舍入处不同。 | 小数/整数舍入、现金不足、止损剩余份额、结果差异和Risk Gate测试。 | 5 仓位状态机 | IMPLEMENTATION_PENDING | 小数份额结果可能高估不可实际执行的资金利用率。 |

## 实施分期与范围边界

必须拆分为独立、可测试和可提交的阶段：

1. 数据契约、XNYS日历、30分钟数据和Data Manifest。
2. 严格60分钟聚合及D-1日线指标。
3. pivot、趋势、波动率和策略状态纯函数。
4. 确定性30分钟事件与成交引擎。
5. 仓位状态机、止损、部分成交和成本。
6. 单ETF回测、交易生命周期和指标报告。
7. 实验登记、消融和参数邻域测试。
8. Walk-forward及样本可行性检查。
9. Locked OOS封存、解锁和审计。
10. 外部ETF验证和多角色报告。
11. DIA与TradingView parity。
12. 前向测试。

期权执行层和共享资金组合审计另立项目，不进入第一阶段核心实现。TradingView、期权执行层、组合资金审计、前向测试和券商模拟不得反向修改已经冻结的Python方向信号。

## 残余风险清单

1. Futu `time_key`的开始/结束时间语义必须由真实fixture确认；在确认前不得把数据标记为可研究。
2. 90个月30分钟历史及其质量尚未由本矩阵证明；历史不足时只能输出`HOLD_INSUFFICIENT_SAMPLE`。
3. 30分钟OHLC不能重建柱内真实事件路径，止损规则是明确的保守模拟，不是真实逐笔成交。
4. Buy and Hold主基准不含分红和利息，不能代表完整Total Return。
5. 首轮阈值仍需参数邻域稳定性和样本外验证，不能解释为最优参数。
6. 普通Sharpe未进行多重测试校正，报告必须明确选择偏差风险。
7. Windows ACL和独立系统账户不属于第一版强制设计；Locked OOS安全性依赖路径、命令和审计实现。
8. 日线完全依赖Futu 30分钟RTH数据；任何30分钟缺失或修订都会同时影响日线、D-1指标和研究柱，必须通过Manifest版本化。
9. corporate action来源可能发生历史修订；拆股事件hash变化必须使数据状态重新变为`DATA_ACTIONS_UNVERIFIED`，不得静默沿用旧research价格。
10. 五字段业务唯一键不能防止同一结果被错误覆盖，因此`run_id`、`result_id`和不可变写入策略仍需由实现保证。
11. null指标和状态码降低了伪精确风险，但小样本、零方差和零回撤仍可能使比较关卡不适用，报告不得将其解释为通过。
12. initial_1R依赖首次成交和当时有效止损均已正确持久化；任一字段缺失时必须拒绝生命周期，而不是推导替代值。
13. OOS重试状态依赖“结果是否已持久化”的原子判定；临时文件、事务回滚和日志落盘顺序必须经过故障注入测试。

## 完成性检查

- 审查中的28个问题均已映射至`B-01`至`L-02`及新增`H-11`至`H-14`、`M-05`至`M-06`。
- 每行均包含`finding_id`、`severity`、`affected_sections`、`exact_resolution`、`specification_text`、`required_tests`、`implementation_phase`、`resolved`和`residual_risk`。
- 设计文本不使用未确定的占位表达。
- 原冻结设计、`src`、`tests`、`scripts`和依赖不属于本文件修改范围。
