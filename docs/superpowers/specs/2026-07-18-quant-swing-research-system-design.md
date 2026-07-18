# 多角色量化波段策略研究系统设计

## 1. 文档定位与冻结规则

本文档是量化波段策略研究、审计、实现和人工审批的单一权威设计。它不是实施代码，也不授权连接交易接口、解锁交易、发送订单或进行实盘交易。

规则变更必须创建新的策略版本并记录原因。首轮阈值是冻结的研究基准，必须在研发区完成预先登记的参数邻域稳定性测试，不得描述为最优值。本文档的设计范围大于当前实现范围，必须按第22章的`Implementation Phase 1`至`Implementation Phase 12`分阶段实施。

当前仓库已有SPY和QQQ历史数据下载、EMA回测、测试和报告的基线能力；正式实施仍按第22章阶段推进，不接入TradingView Webhook、券商、自动下单或期权回测。

## 2. 系统目标与绩效原则

系统必须自动化、可重复、可审计、可解释，并由Python完成确定性计算和数据存储。回测不得使用未来函数，信号默认在下一根可交易K线成交，必须包含手续费和滑点，并始终与Buy and Hold比较。

### 2.1 目标与硬门槛

1. Locked OOS CAGR目标为对应`PRIMARY_PRICE_ONLY` Buy and Hold CAGR的95%。
2. 策略最大回撤目标为不超过20%。
3. 策略最大回撤超过25%时直接淘汰。
4. 策略最大回撤相对`PRIMARY_PRICE_ONLY` Buy and Hold改善至少25%时通过适用的相对回撤门槛。
5. Buy and Hold最大回撤为0时，`relative_drawdown_improvement=null`、`relative_drawdown_gate=NOT_APPLICABLE`、`candidate_status=HOLD_BENCHMARK_DRAWDOWN_NOT_APPLICABLE`；该状态不算通过，也不直接算策略失败。
6. 任何适用硬门槛失败不得由其他指标补偿。

### 2.2 Buy and Hold

报告同时提供两种口径：

- `PRIMARY_PRICE_ONLY`：只计算ETF价格变化，不计分红、分红再投资、利息、手续费或滑点。该口径用于主研究目标，并标记为低估完整Total Return。
- `COMPARABLE_COST`：使用相同raw价格，在第一根可交易柱买入、最后交易日收盘卖出，承担一次普通买入和一次普通卖出手续费及滑点。

策略持仓不计分红，空仓资金收益为0且不计利息。

## 3. 研究标的与验证层次

- 主研究标的：QQQ。
- 外部稳健性验证：SPY、IWM、RSP。
- 晋级压力测试：DIA。

只在QQQ上研发和选择参数。参数冻结后原封不动运行SPY、IWM、RSP。外部结果不得直接修改同一候选；若外部结果影响后续修改，相关ETF对该策略家族标记为`OBSERVED`，新修改必须创建新的`candidate_id`。DIA只对晋级候选运行。第一阶段各ETF独立回测，单标的通过后才进行共享资金组合审计。

## 4. 数据源、日历与时间框架

### 4.1 数据源与Manifest

主数据源为Futu OpenD。第一阶段使用同一Futu数据源的30分钟RTH历史K线，不混用Futu独立日线、yfinance日线或其他来源拼接序列。第二数据源只用于候选晋级后的独立复核。

统一接口预留`FutuProvider`、`SecondaryProvider`和`CSVProvider`。Futu失败时禁止静默切换。每个数据集必须生成Data Manifest，记录`dataset_id`、来源、数据版本、下载时间、时区、字段、起止日期、行数、SHA-256、质量状态、`calendar_library`、`calendar_library_version`、`calendar_schedule_hash`和`early_close_60m_policy`。第一版的`early_close_60m_policy`固定为`EXCLUDE_FROM_60M_SEQUENCE`。

所有内部时间使用UTC；交易日历和交易时段使用`America/New_York`及XNYS交易日历。原始30分钟记录必须保存：

`source_timestamp`、`bar_start_local`、`bar_end_local`、`bar_start_utc`、`bar_end_utc`、`session_date`、`is_regular_session`、`is_early_close`和`source`。

内部时间戳统一表示K线开始时间。Futu `time_key`必须由固定fixture验证其表示开始时间还是结束时间，再转换为内部开始时间，禁止直接假设。DST必须先本地化到America/New_York再转换UTC，不使用固定UTC偏移。

### 4.2 RTH 30分钟柱

正常完整交易日必须有13根RTH柱，开始时间依次为09:30、10:00、10:30、11:00、11:30、12:00、12:30、13:00、13:30、14:00、14:30、15:00、15:30。盘前盘后数据不得进入RTH研究数据。

前12根组成6根完整60分钟研究柱：09:30–10:30、10:30–11:30、11:30–12:30、12:30–13:30、13:30–14:30、14:30–15:30。15:30–16:00柱是尾盘辅助柱，不参与60分钟指标或新信号。

正常日或提前收市日出现缺失、重复、重叠、乱序或错误长度柱时，状态为`DATA_QUALITY_FAILED`，不得启动回测。每根30分钟柱的raw和research open、high、low、close都必须非空、有限且大于0，并分别满足`high>=max(open,close)`、`low<=min(open,close)`和`high>=low`。`raw_volume`、`research_volume`必须非空、有限且大于或等于0；零成交量允许，但必须记录`ZERO_VOLUME_WARNING`。负成交量、非有限值、缺失价格或价格区间错误均为`DATA_QUALITY_FAILED`。错误数据不得用于日线OHLC、持仓估值、止损判断或下一交易日D-1指标。

提前收市日由Data Manifest冻结版本的XNYS日历识别，不根据数据数量猜测。`expected_bar_count=(session_close-session_open)/30分钟`；例如09:30至13:00必须有7根30分钟柱。实际柱数量、起止时间和间隔必须与XNYS完全一致。即使30分钟数据完整，提前收市日也不生成任何60分钟研究柱，不更新60分钟EMA、ATR、pivot、趋势状态、PULLBACK或recovery状态，不产生新仓、加仓或新的60分钟趋势减仓信号。已有仓位继续使用当日30分钟raw柱检查开盘跳空止损和盘中止损，并继续执行D-1日线`RISK`清仓及其他优先级更高的风险退出；完整RTH 30分钟数据用于更新现金、仓位市值和收盘估值，仍聚合成日线供下一交易日使用，且该日计为持仓交易日。下一正常交易日的60分钟`previous_close`使用上一根正式纳入60分钟序列的research close。

提前收市日不直接执行day 5或day 15时间检查。若day 5或day 15恰好落在提前收市日，则在该日最后一根RTH柱完成后创建唯一`pending_time_check`，保存`pending_time_check_id`、`trade_lifecycle_id`、`threshold_type=DAY_5|DAY_15`、`threshold_session_date`、`created_at_utc=该日最后一根RTH柱的bar_end_utc`和`status=PENDING`。同一`trade_lifecycle_id`和同一`threshold_type`最多存在一条pending记录。

pending检查只在首个后续数据完整的正常交易日执行，固定执行时点为该日最后一根完整60分钟研究柱14:30–15:30收盘后。DAY_5使用截至该时点的`mfe_r`、正式确认pivot low和冻结的`entry_structure_low`；DAY_15使用该时点的research close、EMA20、60分钟状态、截至该时点正式确认的pivot high和pivot low，以及冻结的`entry_anchor_pivot_high`和`entry_structure_low`。检查要求退出时，在紧随其后的15:30–16:00辅助柱`raw_open`执行普通清仓订单，使用普通卖出滑点和手续费；检查允许继续持仓时状态为`COMPLETED_HOLD`，要求退出且订单已生成时状态为`COMPLETED_EXIT`。后续正常交易日数据质量失败时pending记录保持`PENDING`并等待下一完整正常交易日。pending期间继续执行跳空止损、盘中止损、D-1日线`RISK`清仓及其他更高优先级风险退出；若仓位在检查前归零，状态改为`CANCELLED_POSITION_CLOSED`。`COMPLETED_HOLD`、`COMPLETED_EXIT`和`CANCELLED_POSITION_CLOSED`均为终止状态。

### 4.3 日线聚合

日线必须由同一Futu 30分钟RTH数据按`session_date`聚合，禁止使用Futu独立日线或yfinance日线：

- `daily_open`：第一根RTH柱open。
- `daily_high`：当日RTH high最大值。
- `daily_low`：当日RTH low最小值。
- `daily_close`：最后一根RTH柱close。
- `daily_volume`：当日RTH volume总和。

日线生成后，D日盘中只允许读取D-1已完成日线。D日收盘生成的日线状态从D+1开始使用。日线EMA、ATR、波动率和市场环境均遵守D-1规则。

### 4.4 30分钟到60分钟聚合

除提前收市日外，每两根连续、完整且同一`session_date`的30分钟RTH柱组成一根60分钟研究柱。时间戳使用第一根柱的`bar_start_utc`和`bar_start_local`。raw和research字段分别按以下规则聚合：

- open：第一根柱open。
- high：两根柱high最大值。
- low：两根柱low最小值。
- close：第二根柱close。
- volume：两根柱volume之和。

禁止跨`session_date`聚合，禁止使用15:30–16:00辅助柱构造60分钟研究柱，禁止将提前收市日的任何30分钟柱纳入60分钟序列。组成柱任一根缺失或异常时，该交易日状态为`DATA_QUALITY_FAILED`。

## 5. 价格字段、拆股与分红

系统保留`raw_open`、`raw_high`、`raw_low`、`raw_close`、`raw_volume`以及对应的`research_open`、`research_high`、`research_low`、`research_close`、`research_volume`。每根30分钟柱还必须保存有限正数`split_factor_t=cumulative_split_factor`，并将该字段及其生成规则写入Data Manifest。任一`split_factor_t`为空、非有限或小于等于0时状态为`DATA_QUALITY_FAILED`。

拆股比例定义为`new_shares / old_shares`。必须记录拆股事件来源、日期、比例、获取时间和SHA-256；禁止猜测比例。未验证、缺字段或hash不一致时状态为`DATA_ACTIONS_UNVERIFIED`，不得进入正式回测。

对每根发生在拆股生效日前的历史raw柱：

`cumulative_split_factor = 该柱日期之后所有已验证拆股比例的乘积`。

`research_price_t=raw_price_t/split_factor_t`；`raw_price_t=research_price_t*split_factor_t`；`research volume=raw volume*split_factor_t`。

拆股生效日及之后不应用该次拆股的历史因子。raw字段永远不得改写，分红不得进入research调整，拆股调整不得改变真实成交现金流。

research价格空间负责EMA、ATR、波动率、pivot、趋势结构、`pullback_anchor_high`、`pullback_structure_low`、`recovery_level_research`、`initial_stop_research`、`effective_stop_research`、`initial_entry_price_research`、`initial_1r_research`、`mfe_r`、`mae_r`以及所有策略阈值和风险距离。raw价格空间负责订单成交、现金变化、手续费、实际仓位市值、实际PnL、账户权益和30分钟止损触发。除非字段明确带有raw前缀或处于成交、现金、PnL、权益及30分钟止损触发上下文，后续策略规则中的open、high、low、close和ATR均指research值。所有价格比较必须先转换到同一价格空间，禁止直接比较raw价格与research价格或距离。

在待执行柱`t`，冻结以下换算：

- `open_research_equivalent=raw_open_t/split_factor_t`。
- `expected_entry_fill_raw=raw_open_t*(1+normal_slippage_bps/10000)`。
- `expected_entry_fill_research=expected_entry_fill_raw/split_factor_t`。
- `recovery_level_raw_t=recovery_level_research*split_factor_t`。
- `effective_stop_raw_t=effective_stop_research*split_factor_t`。

拆股事件在拆股生效日第一根RTH柱的开盘事件之前处理，优先于止损、清仓、减仓和入场。若`split_ratio=new_shares/old_shares`，则`position_quantity_after=position_quantity_before*split_ratio`、`raw_average_cost_after=raw_average_cost_before/split_ratio`，所有raw价格空间的有效止损、挂单价格和参考价格均按`price_after=price_before/split_ratio`调整。research价格空间的EMA、ATR、pivot、`recovery_level_research`、`initial_stop_research`、`effective_stop_research`、`initial_entry_price_research`和`initial_1r_research`保持不变；现金不变。拆股事件不产生订单、fill、手续费或新的`trade_lifecycle_id`，在没有市场价格变化的假设下处理前后账户权益必须相等。

integer audit模式同时保存`autonomous_integer_quantity`、`corporate_action_fractional_quantity`和`total_quantity`。`autonomous_integer_quantity`只由正常自主买卖订单产生且必须是非负整数；`corporate_action_fractional_quantity`只由corporate action产生并满足`0<=corporate_action_fractional_quantity<1`；`total_quantity=autonomous_integer_quantity+corporate_action_fractional_quantity`。

拆股事件处理时先计算`total_quantity_after=total_quantity_before*split_ratio`，随后固定为`autonomous_integer_quantity_after=floor(total_quantity_after)`和`corporate_action_fractional_quantity_after=total_quantity_after-autonomous_integer_quantity_after`。出现非零小数余量时记录`CORPORATE_ACTION_FRACTIONAL_QUANTITY`。禁止自行假设cash-in-lieu成交，禁止由后续自主订单取整逻辑静默删除小数余量。

## 6. EMA、ATR与指标暖机

指标暖机未完成时状态为`INDICATOR_NOT_READY`；结构确认输入不足时状态为`STRUCTURE_NOT_READY`；两种状态均不得交易。60分钟状态的互斥判断优先级固定为`INDICATOR_NOT_READY`、`STRUCTURE_NOT_READY`、`INVALID`、`STRONG`、`WEAK`，前一状态成立时不得继续判断后一状态。

### 6.1 EMA

`alpha = 2 / (period + 1)`。第一笔有效EMA值使用最早`period`个完成柱close的简单平均作为seed；后续递推为：

`EMA_t = alpha * close_t + (1-alpha) * EMA_(t-1)`。

实现不得依赖库的默认`adjust`参数。EMA未完成暖机前不得生成依赖该EMA的信号。

### 6.2 ATR

对每个独立时间框架的第一根正式纳入指标序列的有效柱，`TR_0=high_0-low_0`。对`t>0`：

`TR_t=max(high_t-low_t,abs(high_t-previous_close),abs(low_t-previous_close))`。

其中`previous_close`是该时间框架上一根正式纳入指标序列的完成柱close；提前收市日不进入60分钟序列，因此也不得成为下一根60分钟柱的`previous_close`。

当`period=N`时，第一笔有效ATR固定在零基索引`N-1`，为`TR_0`至`TR_(N-1)`共N个值的简单平均；后续使用Wilder递推：

`ATR_t = ((period-1)*ATR_(t-1)+TR_t)/period`。

60分钟ATR20使用60分钟research OHLC；日线ATR20使用同一Futu 30分钟RTH聚合的daily research OHLC。指标未完成暖机时对应策略状态为`INDICATOR_NOT_READY`，不得交易。

## 7. 交易方向与仓位模型

策略只做多，允许0%现金仓位；禁止做空、杠杆和防御资产轮动。最终仓位为：

`min(波动率目标仓位, 日线环境仓位上限, 60分钟趋势仓位上限)`。

波动率使用split-adjusted、dividend-unadjusted的日线`research_close`收盘到收盘对数收益。20日已实现波动率为最近20个完成交易日日收益的样本标准差乘`sqrt(252)`；基准为最近252个已完成20日波动率值的中位数。D日盘中使用D-1数据，暖机至少271个完成交易日；历史不足时目标仓位为0%。

相对波动率档位：≤0.80为100%，>0.80且≤1.10为75%，>1.10且≤1.50为50%，>1.50为0%。风险升高时下一根可交易K线立即减仓；风险降低时目标档位必须连续2根完整60分钟柱有效后才加仓。期间任意风险上升或目标下降都将加仓计数器清零。

仓位数量计算在每根30分钟柱处理完更高优先级的止损、清仓和减仓后执行。`reference_price=当前30分钟柱raw_open`；`current_quantity`为处理高优先级订单后的当前数量，在integer audit模式下该字段等于`total_quantity`并只用于持仓市值和权益计算；`available_cash`为处理高优先级订单后的可用现金；`current_position_value=current_quantity*reference_price`；`pre_order_equity=available_cash+current_quantity*reference_price`；`target_position_pct`为波动率、日线环境和60分钟状态取最小值后的最终目标仓位比例；`target_position_value=pre_order_equity*target_position_pct`；`target_quantity_fractional=target_position_value/reference_price`；fractional research模式的`quantity_delta=target_quantity_fractional-current_quantity`。

fractional research模式的买入数量先按`desired_buy_value=max(0,target_position_value-current_position_value)`计算，再受到`fill_price`、手续费和现金限制：`commission_rate=commission_bps/10000`，`maximum_affordable_quantity=available_cash/(fill_price*(1+commission_rate))`，`desired_quantity=desired_buy_value/fill_price`，`buy_quantity=min(desired_quantity,maximum_affordable_quantity)`。

fractional research模式使用上述`target_quantity_fractional`和`quantity_delta`。integer audit模式固定`commission_rate=commission_bps/10000`，先计算`target_total_quantity_fractional=target_position_value/reference_price`，随后固定为：

- `target_autonomous_integer_quantity=max(0,floor(target_total_quantity_fractional-corporate_action_fractional_quantity))`。
- `order_quantity_delta=target_autonomous_integer_quantity-autonomous_integer_quantity`。
- `desired_buy_quantity=max(0,order_quantity_delta)`。
- `affordable_quantity_integer=floor(available_cash/(fill_price*(1+commission_rate)))`。
- `buy_quantity=min(desired_buy_quantity,affordable_quantity_integer)`。
- `sell_quantity=min(autonomous_integer_quantity,max(0,-order_quantity_delta))`。

普通买入和部分减仓只能修改`autonomous_integer_quantity`，不得修改或删除`corporate_action_fractional_quantity`。整数股模式必须先按上述公式扣除corporate-action小数余量后向下取整目标自主仓位，再计算订单差额；禁止对已经计算出的卖出差额再次独立取整。两种模式均禁止负持仓、负现金和杠杆；因现金约束无法达到目标仓位时记录`TARGET_NOT_FULLY_REACHED_CASH_CONSTRAINT`。小数股和整数股共享信号、事件顺序、成交价和成本公式。

## 8. 日线和60分钟状态

### 8.1 日线环境互斥优先级

日线状态只从已完成且满足暖机的数据计算，并按以下顺序互斥判断：

1. `RISK`：D-1日线close<EMA200，或`slope_daily<-0.25`；仓位上限0%。
2. 否则，`STRONG`：D-1日线close>EMA200，且EMA50>EMA200，且`slope_daily>0.25`；仓位上限100%。
3. 其余已完成暖机状态为`TRANSITION`；仓位上限50%。

`slope_daily=(EMA200当前值-EMA200二十个交易日前值)/当前日线ATR20`。

### 8.2 60分钟趋势互斥优先级

60分钟状态只从已完成数据计算。pivot结构按第9章先更新，再按以下顺序互斥判断：

1. `INDICATOR_NOT_READY`：任一必需指标未完成暖机；不得交易。
2. 否则，`STRUCTURE_NOT_READY`：正式确认pivot low少于2个，此时`pivot_structure_state=NOT_READY`；不得交易。
3. 否则，`INVALID`：`pivot_structure_state=BROKEN`，或research close<`active_higher_low_price`，或research close<EMA50且`slope_60m<-0.10`；仓位上限0%。
4. 否则，`STRONG`：`pivot_structure_state=READY`，且research close>EMA20>EMA50，且`slope_60m>0.10`，且research close>=`active_higher_low_price`；仓位上限100%。
5. 其余状态为`WEAK`；仓位上限50%。

`slope_60m=(EMA20当前值-EMA20五根研究柱前值)/当前60分钟ATR20`。状态条件只使用上述互斥定义。必须进行仅均线、仅结构、均线加结构三组消融测试。

## 9. Pivot与受控回调状态机

确认pivot使用`left_bars=2`、`right_bars=2`。对中心研究柱`c`，pivot high成立当且仅当`high[c]>high[c-2]`、`high[c]>high[c-1]`、`high[c]>high[c+1]`且`high[c]>high[c+2]`；pivot low成立当且仅当`low[c]<low[c-2]`、`low[c]<low[c-1]`、`low[c]<low[c+1]`且`low[c]<low[c+2]`。全部比较严格使用大于或小于；任一相等极值、缺失值或非有限值都不构成对应pivot。同一中心柱同时满足两组条件时允许生成两个独立pivot事件。

pivot只有在`c+2`完整60分钟柱收盘后正式可见，不得回填至中心柱`c`。`pivot_id`必须包含中心柱时间戳、pivot类型和参数版本。`confirmed_pivot_lows`是截至当前时点已经正式确认、按`confirmation_timestamp`升序排列的pivot low序列。少于2个时，`pivot_structure_state=NOT_READY`、`active_higher_low_pivot_id=null`且`active_higher_low_price=null`。

当至少存在2个正式pivot low时，只取序列中最近两个`previous_pivot_low`和`latest_pivot_low`。若`latest_pivot_low.price>previous_pivot_low.price`，则`pivot_structure_state=READY`、`active_higher_low_pivot_id=latest_pivot_low.pivot_id`、`active_higher_low_price=latest_pivot_low.price`。若`latest_pivot_low.price<=previous_pivot_low.price`，则结构立即变为`BROKEN`，两个active字段均置为`null`。结构`BROKEN`后，只有后续新确认的最近两个pivot low再次形成严格上升关系时才重新进入`READY`，并使用新严格上升对中的latest pivot low作为active higher low。新pivot low的结构转换在该pivot正式确认的完整60分钟柱收盘时执行，不回填。

结构变为`BROKEN`时，当前PULLBACK立即作废，待执行入场订单取消，已有仓位的60分钟状态按`INVALID`处理并按结构退出规则生成下一根可交易柱清仓订单。最近确认更高高点定义为最新确认pivot high严格高于前一个确认pivot high。pivot参数可在研发区做预先登记的邻域测试，不得根据Locked OOS调整。

只有上一根完整60分钟柱状态为`STRONG`且已有确认pivot high时，才允许启动受控回调监控。当前柱必须同时满足：close<EMA20、close>EMA50、`pivot_structure_state=READY`、close>=`active_higher_low_price`、日线状态不是`RISK`。当前柱启动PULLBACK，并冻结`pullback_anchor_pivot_id`、`pullback_anchor_high`、`pullback_atr20`和`pullback_start_bar`。该次回调期间不得因后续pivot high改变锚点。

回调深度为`pullback_anchor_high - 从pullback_start_bar至当前已完成柱的最低research_low`。回调持续柱数从`pullback_start_bar`计为1；`pullback_atr20`使用启动柱完成时已可见的60分钟ATR20并在本次回调期间冻结。

合格回调必须持续2至12根完整60分钟柱、深度位于0.75至2.0倍`pullback_atr20`之间、EMA50有效、`pivot_structure_state=READY`、close>=`active_higher_low_price`，且未触发波动持续扩大失格条件。波动持续扩大定义为ATR20连续3根完整60分钟柱上升，且当前ATR20高于此前20根ATR20中位数的1.10倍。

回调持续超过12根、深度超过2.0倍`pullback_atr20`、结构失效、日线进入`RISK`、波动持续扩大或完整清仓时，回调作废。作废后必须等待新的确认pivot high和新的回调过程。

`pullback_structure_low`为回调期间最低research_low。多个柱拥有相同最低价时，使用时间最晚的柱作为`pullback_structure_low_bar`。`recovery_level_research`为该低点柱之后、恢复信号柱之前已完成柱的最高research_high，至少需要一根有效恢复区间柱。恢复信号必须满足`research_close>recovery_level_research`。恢复信号柱收盘时冻结`signal_atr20_research`，用于过度扩张、追价和待执行订单检查；恢复信号柱不得参与`recovery_level_research`计算。

## 10. 入场、恢复与尾盘新仓

入场上下文冻结`entry_anchor_pivot_high=pullback_anchor_high`和`entry_structure_low=pullback_structure_low`，不得被后续pivot更新改写。在待执行柱`t`，先计算`open_research_equivalent=raw_open_t/split_factor_t`。普通买入的预期成交价分别保存为`expected_entry_fill_raw=raw_open_t*(1+normal_slippage_bps/10000)`和`expected_entry_fill_research=expected_entry_fill_raw/split_factor_t`；实际成交分别记录`actual_entry_fill_raw`和`actual_entry_fill_research=actual_entry_fill_raw/split_factor_t`。确定性研究模式下实际raw成交价必须与预期raw公式一致，且禁止价格改善。

入场必须依次满足：日线环境允许做多、60分钟趋势未失效、存在确认短期高点、受控回调合格、回调形成结构低点、恢复柱收盘突破恢复位、收盘重新站上EMA20、EMA20斜率位于转平或向上区间，随后在下一根可交易K线成交。

恢复信号柱的`research_close-recovery_level_research`不得大于`0.75*signal_atr20_research`。普通入场有效区间为`recovery_level_research<=open_research_equivalent<=recovery_level_research+0.50*signal_atr20_research`，上下边界相等时允许入场。若`open_research_equivalent<recovery_level_research`，取消入场并记录`ENTRY_CANCELLED_RECOVERY_FAILED`；若超过上限，取消入场并记录`ENTRY_CANCELLED_GAP_TOO_LARGE`。两种取消均使当前回调和恢复结构作废，必须等待新的完整回调和恢复结构。

普通时段首次入场一次进入完整目标仓位。15:30辅助柱开盘入场必须同时满足：D-1日线状态为`STRONG`；波动率目标仓位至少75%；`recovery_level_research<=open_research_equivalent<=recovery_level_research+0.35*signal_atr20_research`；初始仓位上限50%。上下边界相等时允许入场。低于恢复位时取消尾盘入场并记录`ENTRY_CANCELLED_LATE_RECOVERY_FAILED`；超过上限时取消并记录`ENTRY_CANCELLED_LATE_GAP_TOO_LARGE`；两种取消均使当前回调和恢复结构作废。其他条件失败也取消尾盘新仓并记录对应原因。尾盘入场次日只有D-1日线仍为`STRONG`、波动率目标至少75%、次日前两根完整60分钟柱均为`STRONG`且未触发止损、弱化或失效时，才在下一根可交易30分钟柱开盘恢复完整目标；该恢复同时使用连续2根确认规则。尾盘辅助柱不生成新策略信号。

## 11. 成交、止损与事件顺序

每根30分钟柱按唯一顺序处理：

1. 若为拆股生效日第一根RTH柱，在所有订单和风险事件之前按第5章处理拆股事件。
2. 开盘处理已有仓位跳空止损。
3. 处理上一根完成柱生成的清仓订单。
4. 处理减仓订单。
5. 处理入场或加仓订单。
6. 同时存在退出和入场时，退出优先，入场取消并记录冲突。
7. 用本柱raw_low检查当前长仓止损；新仓在本柱开盘成交后仍可在本柱触发止损。
8. 每个时间戳最多生成一个最终目标仓位订单。
9. 柱收盘更新估值；完整60分钟柱结束时更新指标和状态并生成下一根可交易柱订单。

普通买入：`fill_price=raw_open*(1+normal_slippage_bps/10000)`。

普通卖出、减仓或清仓：`fill_price=raw_open*(1-normal_slippage_bps/10000)`。

数据末日强制平仓：`fill_price=raw_close*(1-normal_slippage_bps/10000)`，`exit_reason=END_OF_DATA`，该生命周期计入PnL和风险指标，并报告`end_of_data_exit_count`。不得将其表述为策略主动退出信号。

禁止价格改善。手续费按每个fill的成交名义金额独立计算：`commission=abs(fill_quantity*fill_price)*commission_bps/10000`。每笔成交必须保存`reference_price`、`fill_price`、`slippage_bps`、`commission`、`side`、`order_id`和`fill_id`。

research价格空间的初始止损为`initial_stop_research=pullback_structure_low-0.25*signal_atr20_research`。入场前风险检查固定为`expected_entry_fill_research-initial_stop_research<=2.5*D-1 daily_atr20_research`；超过时直接放弃交易。2.5倍日线ATR和0.25倍60分钟ATR为首轮基准，可在研发区做预先登记的邻域测试。

在30分钟柱`t`先计算`effective_stop_raw_t=effective_stop_research*split_factor_t`。若`raw_open_t<=effective_stop_raw_t`，止损成交价为`raw_open_t*(1-stop_slippage_bps/10000)`；否则若`raw_low_t<=effective_stop_raw_t`，成交价为`effective_stop_raw_t*(1-stop_slippage_bps/10000)`；成交价不得低于0。止损必须同时保存`effective_stop_research`、`effective_stop_raw_t`、`split_factor_t`、`raw_open_t`、`raw_low_t`、`fill_price`、`gap_through_stop`和`slippage_bps`。

新的`active_higher_low`正式确认且`pivot_structure_state=READY`时，research价格空间的`candidate_stop_research=active_higher_low_price-0.25*该pivot确认时可见的60分钟ATR20 research值`。只有该candidate止损高于当前`effective_stop_research`时才更新，固定为`effective_stop_research=max(previous_effective_stop_research,candidate_stop_research)`；重新建立的较低READY结构不得降低止损。止损更新只在pivot正式确认后生效，不回填至pivot发生时间。每根待执行30分钟柱使用其`split_factor_t`重新计算raw等价值，禁止沿用不同拆股坐标下的raw止损值。

所有冲突日志必须保存`candidate_id`、时间戳、existing_position、pending_orders、selected_event、cancelled_events和reason。

## 12. 正常退出与生命周期

当`elapsed_calendar_days<=0`时，按第13章记录`metric_status=INSUFFICIENT_ELAPSED_TIME`且CAGR为`null`；此状态下不得声称CAGR或年化指标通过。

趋势弱化时目标仓位上限降至50%；结构失效时全部清仓。完整清仓当天禁止重新入场，旧回调和恢复结构作废，必须形成新的确认pivot high、受控回调和恢复突破。部分减仓不触发完整重置。

交易生命周期从首次仓位0变为正数开始，到仓位重新为0结束。中间加减仓仍属于同一`trade_lifecycle_id`，每个fill有独立`fill_id`和`order_id`。

integer audit模式中，catastrophe stop、structure exit、趋势目标变为0、time stop、`END_OF_DATA`及其他`EXIT_ALL`事件的退出数量固定为`exit_quantity=total_quantity`。`EXIT_ALL`允许精确卖出corporate action产生的小数余量，这是风险清仓和生命周期关闭的唯一小数卖出例外；必须记录`exit_quantity_integer_component=autonomous_integer_quantity`、`exit_quantity_fractional_component=corporate_action_fractional_quantity`和`fractional_exit_reason=CORPORATE_ACTION_FULL_EXIT_EXCEPTION`。退出后将三个数量字段全部置0，生命周期只有在`total_quantity=0`后才正式结束。禁止在普通部分减仓中卖出corporate-action小数余量，禁止将其永久留在已关闭生命周期，禁止静默删除或自行模拟cash-in-lieu。执行平台不支持小数卖出时只在Execution Reality Sheet记录平台差异，研究回测仍按本例外执行。

首次成交后同时保存`initial_entry_price_raw=首次成交raw加权价格`、`initial_entry_price_research=initial_entry_price_raw/split_factor_t`和`initial_1r_research=initial_entry_price_research-initial_stop_research`。`initial_1r_research`必须有限且大于0，否则拒绝创建交易生命周期。后续加仓可以改变当前raw平均成本，但不能重写`initial_entry_price_raw`、`initial_entry_price_research`或`initial_1r_research`；research初始止损不得向下放宽。`mfe_r`、`mae_r`和0.75R进展检查均使用冻结的`initial_1r_research`；实际现金、PnL和权益继续使用raw成交价格。

入场交易日为day 0，下一交易所交易日为day 1，提前收市日计一个交易日。正常交易日的day 5在当日收盘后检查第一层时间止损，正常交易日的day 15在当日收盘后检查第二层时间止损，退出订单在下一根可交易柱执行；阈值日为提前收市日时不得直接检查，必须严格使用第4.2节唯一的`pending_time_check`延后路径。

day 5的结构进展必须为：入场后出现新的正式确认pivot low，且该pivot low的research价格>`entry_structure_low`。day 5检查同时要求截至检查时点的`mfe_r>=0.75`。

day 15允许继续持仓必须同时满足：当前research close>EMA20；当前60分钟状态为`STRONG`；入场后至少出现一个research价格>`entry_anchor_pivot_high`的正式确认pivot high，或一个research价格>`entry_structure_low`的正式确认pivot low。否则在下一根可交易柱退出。

## 13. 绩效指标与异常状态

交易次数为已完成`trade_lifecycle_id`数量。`win_rate`为净PnL大于0的已完成生命周期数量除以全部已完成生命周期数量；没有已完成交易时为`null`，`win_rate_status=NO_COMPLETED_TRADES`。

Profit Factor为正生命周期净PnL总和除以负生命周期净PnL绝对值总和；无亏损交易时为`null`、状态`NO_GROSS_LOSS`；无完成PnL时为`null`、状态`NO_COMPLETED_PNL`。Sharpe使用每日账户权益收益率、无风险利率0和`sqrt(252)`；日收益标准差为0时为`null`、状态`ZERO_VARIANCE`。

`total_return=ending_equity/starting_equity-1`。`elapsed_calendar_days`为权益曲线首尾UTC日期的日历天数差。异常状态按以下优先级互斥判断：`ending_equity<=0`时CAGR为`null`、`metric_status=CAPITAL_DEPLETED`并直接淘汰；否则若`elapsed_calendar_days<=0`，CAGR为`null`、`metric_status=INSUFFICIENT_ELAPSED_TIME`；只有`ending_equity>0`且`elapsed_calendar_days>0`时，才计算`CAGR=(ending_equity/starting_equity)^(365.2425/elapsed_calendar_days)-1`。权益曲线必须包含初始资金点。

最大回撤统一为正数幅度：`drawdown_pct_t=1-equity_t/running_max_equity_t`，`max_drawdown=max(drawdown_pct_t)`，正常情况下`0<=max_drawdown<=1`。最大回撤基于每日收盘账户权益。策略目标为`max_drawdown<=0.20`；`max_drawdown>0.25`直接`REJECTED`。`relative_drawdown_improvement=(benchmark_max_drawdown-strategy_max_drawdown)/benchmark_max_drawdown`，适用时硬门槛为`relative_drawdown_improvement>=0.25`。若`PRIMARY_PRICE_ONLY` Buy and Hold的`benchmark_max_drawdown=0`，则`relative_drawdown_improvement=null`、`relative_drawdown_gate=NOT_APPLICABLE`、`candidate_status=HOLD_BENCHMARK_DRAWDOWN_NOT_APPLICABLE`。禁止将负数drawdown直接与正数门槛比较，报告禁止用0替代无定义指标。

持仓时间同时报告交易日数和完整60分钟研究柱数。资金利用率为每根30分钟柱`abs(position_market_value)/equity`的时间加权平均。`mfe_r`为生命周期内最大`(research_high-initial_entry_price_research)/initial_1r_research`；`mae_r`为生命周期内最小`(research_low-initial_entry_price_research)/initial_1r_research`并保留负数。若需要金额或百分比指标，必须使用独立字段`mfe_amount`、`mae_amount`、`mfe_pct`和`mae_pct`，不得用含义不明的`MFE`或`MAE`字段代替。

## 14. 成本与压力测试

基准成本为单边手续费1bps、普通成交滑点2bps、止损额外滑点3bps。必须运行1.0倍、1.5倍和2.0倍成本压力测试。

1.5倍成本须满足CAGR≥Buy and Hold的85%、`max_drawdown<=0.25`、`relative_drawdown_improvement>=0.15`、净收益为正。2.0倍成本须满足CAGR>0、Profit Factor≥1.0、`max_drawdown<=0.25`、总收益较基准下降≤35%，且无负权益、数据异常或成交异常。

成本压力不变量只适用于fractional research模式：1.0、1.5、2.0倍成本必须保持相同信号时间、订单意图、入场退出时间和trade lifecycle数量。integer audit允许数量和现金限制差异，但策略信号不得变化。fractional模式下交易数量变化视为实现错误。

## 15. 样本切分、实验与验证

一个日历月只有在以下条件全部满足时才计为`complete_month`：该月从第一个至最后一个XNYS交易日全部位于数据集覆盖范围内；全部预期XNYS交易日均存在；每个交易日通过对应30分钟数据质量检查；corporate action状态已经验证；Data Manifest不存在阻断性错误。所有`complete_month`按年月升序排列，`M`为其总数。

必须首先满足`M>=90`；否则`candidate_status=HOLD_INSUFFICIENT_SAMPLE`，不得继续生成正式research、Walk-forward或Locked OOS切分，也不得宣称通过或失败。满足后计算：

- `locked_oos_months=max(18,ceil(M*0.20))`。
- `walk_forward_months_raw=max(18,ceil(M*0.20))`。
- `walk_forward_months=3*ceil(walk_forward_months_raw/3)`。
- `research_months=M-walk_forward_months-locked_oos_months`。

`research_months`必须至少24个月，否则状态为`HOLD_INSUFFICIENT_SAMPLE`。按时间升序连续分配：最早`research_months`个月为`RESEARCH_REGION`，紧接其后的`walk_forward_months`个月为`WALK_FORWARD_REGION`，最新`locked_oos_months`个月为`LOCKED_OOS_REGION`。各区域必须连续，禁止跳月、重叠或重新排序；区域边界分别为边界月的第一个和最后一个XNYS交易日，Locked OOS必须是时间序列最末端连续区域。

固定滚动Walk-forward对`k=0,1,2,...`依次生成窗口：`test_start_month`为`WALK_FORWARD_REGION`第`3k+1`个月，测试集为从该月开始连续3个`complete_month`，训练集为测试开始前连续24个`complete_month`，窗口步长固定3个月且测试窗口互不重叠。训练集可以包含`RESEARCH_REGION`月份及当前测试窗口之前已经结束的`WALK_FORWARD_REGION`月份，但不得包含当前测试窗口、未来Walk-forward月份或任何Locked OOS月份。第一个窗口没有完整24个月前置训练数据时状态为`HOLD_INSUFFICIENT_SAMPLE`。Walk-forward区域必须至少生成6个完整测试窗口，串联测试至少有18个完成生命周期且至少4个测试窗口有实际交易。

正式候选排名、通过比例、正收益窗口比例、串联CAGR和最大回撤只使用固定24个月滚动结果。对相同测试窗口另做扩展训练复核：训练集从`RESEARCH_REGION`第一个月份开始，一直扩展至测试窗口前一个月份。扩展训练结果不参与参数排名、候选胜负排序或参数调整，不替代固定24个月结果，只作为报告中的稳定性诊断，不能单独使候选晋级；独立验证员仅可在发现代码、数据或泄漏异常时据此否决，单纯绩效较差不构成自动淘汰门槛。禁止使用比例近似切分。

所有区域和Walk-forward窗口必须写入Data Manifest，至少保存`region_name`、`month_start`、`month_end`、`train_months`、`test_months`、`window_id`、`fixed_or_expanding`和`data_manifest_hash`。Locked OOS区域路径在普通research和Walk-forward流程中保持不可访问。

每轮最多150个新实验，每个策略家族最多3轮，累计最多450个新实验。连续两轮没有Walk-forward改善则停止方向。所有成功和失败实验必须登记，记录`total_trials`、`selection_rounds`、`rejected_count`、`parameter_space`和`ranking_changes`。报告完整筛选过程，不只报告前5名。第一版不宣称普通Sharpe已校正多重测试选择偏差。

## 16. Locked OOS与候选不可变

Locked OOS存储于`C:\Users\cbcbe\TradingCodex\locked_oos_store\`，普通研究配置不得包含该路径。Stage 1只接收研发和Walk-forward数据路径。封存记录dataset_id、起止日期、SHA-256、行数、数据源和生成时间。

候选冻结时创建不可变candidate package，包含`candidate_id`、策略配置hash、代码提交、Data Manifest hash和实验历史hash。进入Locked OOS后任何代码、配置、参数或数据修改都创建新的`candidate_id`；Locked OOS失败的候选直接`REJECTED`。

每次正式评估创建唯一`oos_attempt_id`。只允许以下状态转换：`CREATED->RUNNING->COMPLETED`、`CREATED->FAILED_BEFORE_RESULT`、`RUNNING->FAILED_BEFORE_RESULT`和`RUNNING->FAILED_AFTER_RESULT`；禁止其他转换。`COMPLETED`、`FAILED_BEFORE_RESULT`和`FAILED_AFTER_RESULT`均为终止状态，attempt进入终止状态后不得修改或重新运行。

只有原attempt为`FAILED_BEFORE_RESULT`、没有任何指标、结果行、报告或详细结果被持久化或展示、数据hash/代码commit/配置hash完全一致且原attempt的`retry_count=0`时，才允许一次技术重试。重试必须创建新的`oos_attempt_id`，不得复用原ID，并记录`retry_of=原oos_attempt_id`、`root_attempt_id=最初attempt ID`和`retry_count=1`。`retry_count=1`的attempt无论以何种状态结束均不得再次重试；`COMPLETED`或`FAILED_AFTER_RESULT`永远不得重试。结果持久化判断必须覆盖JSON、CSV、DuckDB事务、临时报告、正式报告和任何用户可见指标输出。

所有尝试和重试必须写审计日志，记录候选、操作者、时间、数据hash、代码提交、配置hash、`retry_of`、`root_attempt_id`和`retry_count`。普通参数扫描和实验命令必须拒绝Locked OOS路径。

## 17. 机器结果与报告

机器结果业务唯一键统一为：

`dataset_id + candidate_id + experiment_id + stage + cost_scenario + benchmark_type`。

JSON、CSV和DuckDB必须使用完全相同的业务唯一键。每次程序运行另生成不可变`run_id`和`result_id`。交易明细使用`fill_id`、`order_id`和`trade_lifecycle_id`关联；OOS审计使用`oos_attempt_id`关联。

机器字段至少包括：`schema_version`、`dataset_id`、`data_manifest_hash`、`candidate_id`、`experiment_id`、`strategy_family`、`config_hash`、`code_commit`、`stage`、`cost_scenario`、`benchmark_type`、`run_id`、`result_id`、`data_start`、`data_end`、`total_return`、`CAGR`、`max_drawdown`、`Sharpe`、`Profit_Factor`、`trade_count`、`win_rate`、`win_rate_status`、`relative_drawdown_improvement`、`relative_drawdown_gate`、`candidate_status`、`average_holding_days`、`average_holding_bars`、`capital_utilization`、`mfe_r`、`mae_r`、`pending_time_check_id`、`pending_time_check_status`、`pending_time_check_type`、`threshold_session_date`、`autonomous_integer_quantity`、`corporate_action_fractional_quantity`、`total_quantity`、`pivot_structure_state`、`active_higher_low_pivot_id`、`active_higher_low_price`、`region_name`、`walk_forward_window_id`、`train_start_month`、`train_end_month`、`test_start_month`、`test_end_month`、`fixed_or_expanding`、`role_decisions`、`veto_status`、`veto_reason`、`contamination_status`、`approval_status`、`metric_status`和`generated_at_utc`。如需输出金额或百分比扩展指标，仅允许使用`mfe_amount`、`mae_amount`、`mfe_pct`和`mae_pct`。

机器序列化中，`pending_time_check_type`等于pending记录的`threshold_type`，`pending_time_check_status`等于其`status`；`walk_forward_window_id`等于Data Manifest中的`window_id`，train/test起止月份分别取对应`train_months`和`test_months`序列的首末月份。

## 18. 多角色研究委员会

| 角色 | 职责与否决权 |
|---|---|
| 研究委员会主席 | 汇总证据，作出APPROVE、REVISE、REJECT或HOLD；不得凭主观感觉决定。 |
| 数据工程师 | 检查数据源、XNYS日历、完整性、时区、RTH聚合、复权、拆股和Manifest；可否决数据质量、时间、字段或复权异常。 |
| 量化策略研究员 | 提出可证伪假设和Hypothesis Card；不得无逻辑堆叠指标。 |
| 量化交易员 | 检查信号确认、事件顺序、跳空、滑点、流动性和成交现实；输出Execution Reality Sheet。 |
| 量化开发工程师 | 实现确定性规则、测试、版本和复现；可否决测试失败、未来函数或不可复现结果。 |
| 风险管理专员 | 设置回撤、成本和风险门槛；可否决硬门槛或压力测试失败。 |
| 独立模型验证员 / Red Team | 检查未来函数、数据泄露、过拟合、OOS污染、多重测试和压力测试；可否决污染、过拟合、Walk-forward或外部验证失败。 |

## 19. 解释、归因与审批关卡

每轮生成中文摘要、完整审计报告和JSON/CSV/DuckDB机器结果。报告比较当前候选、上一版冠军和两种Buy and Hold口径，并列出总收益、CAGR、回撤、Sharpe、胜率、Profit Factor、交易数、持仓时间、资金利用率、`mfe_r`、`mae_r`、成本情景、角色意见、否决状态、污染状态和最终结论。

因果标签只允许使用`MECHANISM_HYPOTHESIS`、`OBSERVED_ATTRIBUTION`和`CAUSALLY_CONFIRMED`。观察相关性不得描述为已证明因果关系。

软件开发路线统一使用`Implementation Phase 1`至`Implementation Phase 12`，不得用Approval Gate编号表示开发阶段。完成进入Locked OOS前所需的Implementation Phases并生成候选后，进入`Approval Gate 1`并暂停；`Approval Gate 1`决定是否解锁Locked OOS。`Approval Gate 2`审查Locked OOS，`Approval Gate 3`审查SPY/IWM/RSP外部ETF验证，`Approval Gate 4`审查DIA压力测试和TradingView对账。每一关必须记录候选状态、证据、否决和审批结果；人工批准不得替代任何Implementation Phase的测试或验证。

## 20. TradingView、期权与组合边界

TradingView不是大规模研究主引擎或最终成交事实来源，只用于Python候选的Pine转换、参数/日期/时区/成本对比、至少前10笔交易逐笔对账、信号位置检查和前向Alert验证。代码bug修复后创建新候选并重走验证；平台价格或成交差异只记录parity，不反向调参。

期权执行层独立比较ETF、Long Call、Call Spread和Bull Put Spread，不得反向修改冻结的方向信号。共享资金组合审计在单标的验证通过后另行实施，使用20日和60日日线收益相关性中较高者进行仓位压缩。期权、组合审计、实时前向测试、券商模拟和真实交易不属于第一阶段核心实现。

## 21. 候选状态与错误处理

候选状态包括`IDEA`、`HYPOTHESIS_APPROVED`、`IMPLEMENTED`、`IN_SAMPLE_PASS`、`WALK_FORWARD_PASS`、`LOCKED_OOS_PASS`、`EXTERNAL_VALIDATION_PASS`、`DIA_STRESS_PASS`、`TRADINGVIEW_PARITY`、`FORWARD_TEST`、`PAPER_APPROVED`、`LIVE_CANDIDATE`、`REJECTED`、`HOLD`、`HOLD_INSUFFICIENT_SAMPLE`和`HOLD_BENCHMARK_DRAWDOWN_NOT_APPLICABLE`。失败候选不得删除，必须保存失败阶段、原因、参数、数据版本、代码版本、实验时间和新版本资格。

`pivot_structure_state`枚举只允许`NOT_READY`、`READY`和`BROKEN`。`pending_time_check_status`枚举只允许`PENDING`、`COMPLETED_HOLD`、`COMPLETED_EXIT`和`CANCELLED_POSITION_CLOSED`；后三者为终止状态。

数据失败不得覆盖有效旧数据。所有写入先写临时文件，验证后原子替换。关键失败返回非零退出码，不得静默跳过测试、删除测试、隐藏实验或写入密钥。当前阶段禁止交易接口、真实账户解锁和真实订单。

## 22. 实施边界与分阶段路线

1. `Implementation Phase 1`：数据契约、XNYS日历、Futu 30分钟RTH、日线聚合、30分钟到60分钟聚合、拆股事件和Data Manifest。
2. `Implementation Phase 2`：EMA、ATR、D-1日线指标和暖机状态。
3. `Implementation Phase 3`：pivot、趋势、波动率、受控回调和恢复状态纯函数。
4. `Implementation Phase 4`：确定性30分钟事件、普通成交、止损和末日强平引擎。
5. `Implementation Phase 5`：仓位状态机、初始1R、部分成交、现金限制和成本。
6. `Implementation Phase 6`：单ETF回测、生命周期、指标异常状态和报告。
7. `Implementation Phase 7`：实验登记、消融和参数邻域测试。
8. `Implementation Phase 8`：Walk-forward和样本可行性检查。
9. `Implementation Phase 9`：Locked OOS封存、解锁、尝试状态机和审计。
10. `Implementation Phase 10`：外部ETF验证和多角色报告。
11. `Implementation Phase 11`：DIA压力测试和TradingView parity。
12. `Implementation Phase 12`：前向测试。

期权执行层和共享资金组合审计另立项目，不进入第一阶段核心实现。

## 23. 术语与残余风险

`Data Manifest`记录数据来源、版本、时间、指纹、字段和质量；`Hypothesis Card`记录可证伪假设；`Execution Reality Sheet`记录成交时序、跳空、滑点和执行限制；`Risk Gate`记录风险、回撤和成本门槛。

残余风险如下：Futu `time_key`语义必须由真实fixture确认；90个月30分钟历史必须由数据阶段验证；30分钟OHLC不能重建柱内真实成交路径；Buy and Hold不含分红和利息；首轮阈值仍有参数选择风险；普通Sharpe未进行多重测试校正；Locked OOS的路径隔离和持久化故障判定仍需实现和故障注入验证。

## 24. 冻结一致性声明

本文档已将问题解决矩阵的29个finding_id对应方案纳入正文，并集中解决最终独立复审的`FDR-H-01`、`FDR-H-02`、`FDR-H-03`和`FDR-H-04`。矩阵finding完整清单为：`B-01`、`B-02`、`B-03`、`B-04`、`B-05`、`B-06`、`H-01`、`H-02`、`H-03`、`H-04`、`H-05`、`H-06`、`H-07`、`H-08`、`H-09`、`H-10`、`H-11`、`H-12`、`H-13`、`H-14`、`H-15`、`L-01`、`L-02`、`M-01`、`M-02`、`M-03`、`M-04`、`M-05`、`M-06`。所有时间、价格、指标、仓位、验证和报告契约均以本文档为单一权威定义。
