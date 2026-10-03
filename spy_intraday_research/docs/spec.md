# SPY 日内交易研究项目：Codex 执行规格

版本：1.0｜日期：2026-10-03｜状态：实施规格，尚未实施或验证任何交易优势

实施补充（2026-10-03）：用户已授权持续开发到可forward test，无需重复开发审批。当前代码与运行说明见forward_runbook.md：正式数据/edge门槛未通过时，只允许醒目标记的diagnostic-shadow信号与quote代理观察，不把它称为验证后的策略paper。用户对优化选项的选择权保持；不会自动修改冻结策略。此补充不授权真实/模拟订单、合并、部署或系统自动启动任务。

## 1. 目标、边界与授权

目标是在可交易时点已知的 Market State 下，检验 SPY 四类日内 setup 是否具有扣除合理成本后的、可重复的正期望，并通过独立样本和模拟前向验证。允许最终结论为 NO EDGE；不得承诺盈利。

顺序固定为：数据可信 → underlying forward-return edge → matched controls / robustness → 冻结策略与 Locked OOS → paper forward test → 后续 option mapping。

- 独立新项目建议路径：`C:\Users\cbcbe\TradingCodex\spy_intraday_research`。这是拟议路径；实施前只读确认不存在名称冲突，不改动既有 Futu、QuantSkills 项目或其 data 目录。
- 标的仅 `US.SPY`；信号使用已完成 5m bar，执行与路径研究使用 1m；常规交易时段为 America/New_York 的 09:30 至当日正式收盘。遵守节假日、半日市和 DST，不能固定 UTC 偏移。
- 第一轮仅研究 underlying，禁止真实订单、0DTE 盈亏搜索、杠杆、盘前盘后交易。盘前/隔夜数据可独立记录；缺失时不得伪造。
- 创建此文档不等于批准实现或订单。实施 Codex 必须先报告文件范围、验证方法、功能分支和 PR 方案，等用户明确“批准”后才修改文件、建分支、提交、推送、建 PR。
- 获批后按用户流程同步主分支、建 `codex/spy-intraday-phase-N`、实施、测试、提交、推送、建 PR；默认分支与 remote 必须实测。无 remote 时报告阻塞，不自行发布。
- 合并、部署、删除分支、全局安装/配置、模拟下单及真实交易均需各自明确授权。paper shadow 可先只记录信号；broker paper execution 是独立授权项。不得把授权扩大到期权或单腿拆单。
- 密码、密钥、解锁密码、账户完整标识不得进入源码、CSV、日志、报告或提交。配置只含环境变量名称，敏感值用本地凭据管理。

## 2. 可验证的研究契约

每次运行必须绑定 `run_id`、Git SHA、配置 SHA256、输入数据 manifest/hash、Python/依赖/OpenD/SDK 版本、随机种子、日历版本、成本假设和试验登记版本。结果可由同一缓存重现；下载时间另记，不参与数值结果。

执行前创建 `research_registry.csv`：列出经济假设、方向、变体、状态切片、主指标、次指标、样本门槛、控制组、统计族、TP/SL 候选和试验预算。首次注册后所有尝试包括失败与负结果都保留。阈值是研究治理约定，不是盈利保证。

默认固定参数：ORB 5/15/30m；其余 setup 各一个基线；5m 信号；forward horizons 5/15/30/60 个交易分钟；主 horizon 30m；ATR14；bootstrap 10,000 次；seed 20261003。主检验族为 6 个变体（3 ORB + 其余 3）× 2 方向 = 12 个假设。主检验族使用 Holm 校正，双侧 alpha=0.05。其他 horizon 和状态切片仅探索，若转为正式候选必须加入试验登记和新独立验证计划。

不能在看到结果后改主 horizon、成本、样本门槛或排除日期。长短方向分别报告，不为凑样本随意合并。每个 setup 同一方向每日最多首次有效事件；setup 间重叠保留标签，研究不把重复事件当独立证据。组合策略另行注册资本占用及冲突优先级。

## 3. 数据接口与采集

### 3.1 Futu adapter

默认 OpenD endpoint `127.0.0.1:11111`，允许环境变量覆盖。实施时核验连接、SDK 与 OpenD 兼容性、SPY 权限、是否延迟、历史 1m 最早可用日期、分页和配额，保存脱敏 capability report。不得假定连接存在就有实时权限或多年分钟历史。

- 使用 `OpenQuoteContext` 和 `request_history_kline`，标的 `US.SPY`，类型 `KLType.K_1M`、`KLType.K_5M`、`KLType.K_DAY`；检查 `RET_OK`，分页传递返回的 `page_req_key`，结束条件为 token 为空。检测重复 token 和无新增行，避免死循环。
- 分交易日期窗口采集，原始响应落盘、校验后原子发布。checkpoint 支持断点恢复；重复拉取幂等。限流与临时错误指数退避加 jitter，默认最多 5 次；实际频率按运行时官方限制配置，不能硬编码猜测配额。
- 研究基线采用同一 `AuType.NONE` 原始价格口径；daily、1m、参考价一致。分红/拆分日需独立 corporate-action 标识；避免把除息 gap 误当信息冲击。复权敏感性分析作为独立派生集，不能混合两种口径。
- 实时 adapter 使用订阅、bar/quote 回调和必要的 `get_cur_kline` 补取；只把确认结束的 bar 交给 signal engine。先实测 time_key 是 bar 起点还是终点、时区及推送修订行为，再标准化。
- 每次上下文在 finally 中关闭。读数据模块不得初始化交易账户或调用下单接口。
- 盘前/盘后与 overnight 单独标识。`extended_time`/`session` 参数按安装版本核验，不能把 extended session 当成全 overnight 覆盖。

官方接口参考（2026-10-03 核对；实施时再次核验签名）：

- [历史 K 线与分页](https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html)
- [行情接口总览](https://openapi.futunn.com/futu-api-doc/en/quote/overview.html)
- [订单接口](https://openapi.futunn.com/futu-api-doc/en/trade/place-order.html)：其默认环境可能为 REAL，因此订单 adapter 必须显式传 `TrdEnv.SIMULATE` 并拒绝其他环境。

### 3.2 样本与不可得数据

目标至少 3 年且覆盖多种波动环境，优先 5 年；这是数据目标，不能声称 Futu 必然提供。daily 额外预热至少 60 个交易日。最低正式研究总覆盖 500 个合格 session，且各阶段满足独立样本门槛；不足时仅可标为探索/WEAK。

如 Futu 覆盖不足，输出实际覆盖与缺口报告。只能在用户批准的数据来源范围内引入替代分钟数据，保留 vendor、权限、timestamp/adjustment 差异及重叠对账，不可悄悄拼接或用 5m 插值生成 1m。

### 3.3 标准 bar schema

`symbol, session_date, ts_start_utc, ts_end_utc, ts_start_et, open, high, low, close, volume, turnover, vendor, adjustment, session_type, fetched_at_utc, raw_hash, quality_status`。

时间内部采用带时区 UTC，session 分组使用纽约交易日。价格浮点精度/货币 USD，volume 单位和 turnover 单位先核验。缺字段以 null 并记录原因，不能默认 0。

### 3.4 数据质量 gate

- 主键唯一、严格升序；重复完全一致可幂等去重，冲突重复隔离。OHLC 为正且有限，`low <= open/close <= high`，volume 非负。
- 用交易所日历生成预期分钟；完整普通日应有 390 根 1m、78 根 5m，半日市按实际时长。停牌、缺 bar、意外 extra bar 必须区分，不跨 session 填充。
- 主分析只纳入完整 RTH session 和足够预热的日期；任何缺 minute 的 session 隔离，避免择机删坏交易。报告隔离比例与状态/年份分布；若排除超 1% session，正式研究 gate 暂停直到解释与敏感性分析完成。
- 未结束 bar 禁止进入研究/交易。价格跳变先标记并检查 corporate action/原始响应，不凭收益方向删异常。
- 5m 从 1m 按 session 开盘锚点聚合：首 open、max high、min low、末 close、sum volume/turnover；仅完整 5 根生成。Futu 原生 5m 作交叉核验，容差和供应商修订原因写入报告。
- daily 与 RTH 聚合口径对齐后核验；供应商 daily 包含不同 session 时不得直接判坏。prev high/low/close 以同一口径上一交易日 RTH 数据为准。
- 输入 hash、缺口与 quarantine 清单必须附报告。真实质量失败产生 FAILED_DATA 状态，不生成貌似有效的 edge 结论。

## 4. 无未来信息的 features 与 Market State

所有 feature 都有 `available_at_utc`，signal 的每个依赖必须满足 `available_at <= decision_time`。ATR14 用截至昨日的 Wilder daily ATR，禁止当天最终 high/low。opening range 完成前为 UNKNOWN。

bar-based VWAP proxy：`sum(((H+L+C)/3)*volume)/sum(volume)`，每日 RTH 重置；这是典型价成交量近似，并非逐笔精确 VWAP。若 turnover/volume 单位和口径核验可用，可另报成交额近似，不能无说明替换基线。

| 维度 | 固定基线定义 | 可用时点 |
|---|---|---|
| Gap | `(today_open - prev_close)/ATR14_prev`；绝对值 <=0.1 为 Flat，0.1–0.5 为 Small，>=0.5 为 Large；保留方向 | 首个 1m 完成后 |
| Opening Range | 15m range/ATR；Train 分位 33/67 划 Narrow/Normal/Wide，边界锁定 | 09:45 ET 后 |
| Opening Direction | 15m 净位移/range >=0.5 Trend Up，<=-0.5 Trend Down，其余 Mixed；零 range UNKNOWN | 09:45 ET 后 |
| VWAP slope | `(VWAP_t - VWAP_{t-15m})/ATR`，>0.01 Rising，<-0.01 Falling，其余 Flat | 至少 15m 历史后 |
| Volatility | 昨日 ATR/prev_close 的 Train 33/67 分位 Low/Normal/High | 开盘前 |
| Relative price | close 相对当时 VWAP，另存距离/ATR | 已完成 bar 后 |
| Volume expansion | 当前 5m volume / 过去 20 session 相同 time bucket 中位数 | 当前 bar 完成后 |

保留连续值，状态标签仅辅助解释。分位阈值、标准化、缺失处理只在 Train fit。5m ORB 在 09:45 前不能使用未形成的 OR15 状态；记录 UNKNOWN 而非回填。

完整日 Trend/Range 标签可作为事后描述，必须存 `ex_post_*` 命名且永远不参与选股、控制匹配或入场。不得用全日 range、最终 VWAP、当日最终成交量分类后宣称可实时执行。

## 5. 四类 setup：冻结基线

共通：事件时点为已完成 5m bar 的结束时刻，最早成交为其后下一根 1m open。恰在该边界的历史分钟必须按已核验 timestamp 语义正确映射。paper 则使用真实 signal 可用后第一份可交易报价，记录延迟，不能虚构 next-open fill。

新信号窗口 09:35–15:00 ET；半日市窗口止于正式收盘前 60m。全 horizon 主研究要求目标价格存在，禁止跨隔夜。09:35、09:45、10:00 等边界均按 bar 完成时刻判断。

### A. Opening Range Breakout

OR5/OR15/OR30 区间由开盘后对应完整 1m 构成。OR结束后，首次 5m close 严格高于 OR high 触发 long，严格低于 OR low 触发 short；前一 close 位于区间内/边界，确保是首次 crossing。OR 结束 bar 本身不得拿其 high 做突破信号。各变体各方向每日最多一次；没有 crossing 不生成事件。

先统计全部突破，VWAP、gap、volume、OR/ATR 作描述变量，不立即堆过滤器。

### B. VWAP Pullback Continuation

最早 10:00 ET。long：此前连续 3 根完成 5m close > 各自 VWAP，且 slope Rising；当前 bar low 触及当时 bar VWAP proxy ±0.02 ATR 的带，close > 当前 VWAP 且 close > open，触发 long。short 镜像：连续 3 根下方、Falling、high 触带、close 下方且阴线。当前 bar 中 VWAP 是收盘后才可知，故只表示回测 setup 定义，入场必须下一分钟；不得宣称盘中触带即可成交。每方向首次事件。

EMA 替代是后续独立变体，首轮不得同时搜索 EMA 周期。

### C. Failed Breakout Reversal

levels 固定为 yesterday RTH high/low 与 OR15 high/low。long reversal：完成 5m close 跌破一个 low level 至少 0.02 ATR 后，接下来 1–3 根完成 5m bar 中首次 close 回到该 level 上方，产生 long；short 镜像。突破 bar 与回归 bar 必须不同；超 3 根失效。同一 bar 命中多个 level 合并成一个事件、保留 level 列表；同方向每日首次，冲突按预登记 yesterday level 优先。到当时 VWAP 的距离作 outcome 描述，不默认构成盈利目标。

### D. Gap Fade

仅 abs(gap/ATR)>=0.5，09:45–10:30 ET。gap up：当前 close < 首15m low 且低于当时 VWAP，且尚未触及 prev_close，首次触发 short；gap down 镜像触发 long。如信号前已触 prev_close，不属于该 setup。gap 归因中单独列 corporate-action 日期，基线不纳入未解释除息日。不得根据当天是否最终回补 gap 选择样本。

## 6. Forward-return 与控制实验

### 6.1 主 outcome

entry 参考价为下一 1m open，direction 为 +1/-1。h 分钟退出参考价是从 entry 起完整 h 根 1m 的最后 close。`gross_bps = direction*(exit/entry-1)*10000`；`net_bps = gross_bps - round_trip_cost_bps`。primary h=30；其余为次要。RTH 收盘前不足 h 的事件标 CENSORED，不把提前收盘收益混入固定 horizon。

基线研究成本为每边 1 bps，往返 2 bps，作为待校准假设；同时报告往返 0/2/4/8 bps 敏感性及盈亏平衡成本。可用 quote 实测 spread/fees 后须在 OOS 前锁定更保守模型。收益净值表不能同时再扣已嵌入成交价的 spread/slippage。short 借券/费用/资格未知时将 short 标为“研究方向，不具执行资格”；不可假设模拟卖空可行。

输出 mean/median、win rate、标准差、分位、尾部损失、bootstrap CI；MFE/MAE 用完整 1m 路径 high/low 计算，净收益与未扣成本的 excursion 分列。报告每交易日均值、事件数、独立天数及月/年分布。固定 horizon 事件研究不是可投资组合收益，不直接把事件 Sharpe 年化或声称资金回测。

### 6.2 Matched controls

目的：判断 setup 是否优于同一可观测环境中的普通入场，而非仅捕捉 SPY 长期漂移/时段效应。

- 同一 split 内、相同方向、相同 5m time bucket、同 gap/volatility 状态；仅使用当时可得状态。候选 controls 必须具有相同 horizon 可观察性和数据质量，且该 setup 当时没有触发。
- 不使用事后 return、全日分类、未来 volume、MFE/MAE、是否 hit TP 等匹配。不匹配直接定义 trigger 的 crossing/reclaim，避免把研究处理本身匹掉。
- 每事件匹配其他日期最多 5 个 controls；固定种子，无未来 outcome 筛选。同日 control 禁用，降低价格路径污染；复用情况记录权重及聚类身份。
- caliper 连续特征按 Train 标准化绝对距离 <=0.5 SD；不满足则 unmatched，不自动放宽或跨 split 借样本。至少 80% 事件匹配成功，连续 covariate 标准化差异绝对值 <=0.1；否则 control gate 未通过。
- `delta_bps = event_net_bps - weighted_control_net_bps`。event 与 control 使用同一成本模型；绝对 net>0 和 delta>0 是不同要求。
- 另提供同方向同时间 bucket 无条件 benchmark、以及保持日期聚类的置换检验作为诊断。此观察性设计提供比较证据，不声称因果证明。

### 6.3 Bootstrap 与 robustness

主区间以交易日为 block，整个日期所有 setup/controls 一起重采样，禁止逐事件 iid bootstrap。control 复用的日期与权重必须随抽样重建；每 replicate 重新执行固定匹配或采用日期权重一致的估计器，单元测试证明不丢 control 聚类。另做连续 5 日 moving-block bootstrap 检查跨日依赖，10,000 次，报告 percentile 95% CI、种子、有效次数。Holm 使用预登记主检验族的有效 cluster-based p 值，不拿未校正 CI 当多重检验通过证据。

robustness 必含：年份/季度分块、long/short、volatility/gap 分层；成本压力；入场延迟 +1/+2 分钟；删除贡献最大的 5 个日期；参数邻域只作稳定性检查（ORB 三个预登记区间，其余阈值 ±20%）；corporate-action 敏感性；数据隔离偏差。参数邻域不得选冠军替代原策略，若新增候选须登记试验。

预设通过条件：至少 3 个不重叠子期，其中 >=2/3 子期净均值为正；去掉贡献最大5日仍为正；往返4bps与+1m延迟分别测试仍为正；邻域 >=2/3 合法点为正。+2m、8bps 是更严压力测试，失败要报告，可不自动否定基线。日期贡献按每日总收益统一口径，不能混用事件均值。

## 7. Train / Validation / Locked OOS

按完整交易日顺序划分 60%/20%/20%，不得随机打散；在首次 outcome 计算前保存精确 ISO 日期边界与输入 hash。OOS 至少 100 个完整 session。跨边界 horizon 事件丢弃；任何 rolling outcome/训练标签在边界 purge 最大 horizon，另 embargo 1 个 session。feature 可用此前历史但不得用未来拟合。

- Train：拟合状态分位、探索基线与有限状态假设，保留全部尝试。最多提名 2 个 setup-direction-state 候选；state 过滤每候选最多 1 个维度、最多 2 个标签，不搜索五维笛卡尔积。
- Validation：固定候选只评估一次。主收益、controls、成本与稳定性不达标可弃选，不反复调整到通过。修改后必须新版本并承认 Validation 已消耗。
- edge 初步证明后才在 Train 上研究 TP/SL；至多 9 个事先登记组合，例如 SL 0.1/0.2/0.3 ATR × TP 1/1.5/2R，另固定时间退出基线。选择采用稳定区域和保守成本，不能挑孤立最大净利润。Validation 评估该冻结选择；不得把 forward horizon winner 与 TP/SL winner 任意拼接。
- Locked OOS：在查看任何 OOS outcome 前冻结 signal、states、成本、匹配、TP/SL、风险、配置和代码 hash。存 `lock_manifest.json`；release 命令只能评估一次，记录访问审计。质量检查可看时间/价格完整性，但不得预览 OOS 收益或策略排名。
- OOS 失败即记录失败；改版本不得继续叫同一 OOS 独立验证。等待新未来样本或建立新的从未查看 holdout。不得提前偷看再扩大窗口。

## 8. KEEP / WEAK / NO EDGE 决策

以下为冻结前的默认治理门槛，不能因结果不好而下调。每候选至少 Train 200 事件/100天、Validation 100事件/60天、OOS 100事件/60天；每个用于通过判定的子期至少20个事件。计数不足标 WEAK/INSUFFICIENT，不能解释为 NO EDGE。

| 标签 | 必须满足的证据 | 后续动作 |
|---|---|---|
| KEEP | 数据/控制gate通过；Validation与OOS绝对净均值、matched delta的95%日期聚类CI下限均>0；主族Holm p<0.05；各split的点估计至少净2bps、delta1bps；样本门槛及上述robustness通过 | 仅晋级paper，非真实交易批准 |
| WEAK | 点估计为正但CI跨0、统计校正未过、匹配不足、样本不足或稳定性不足；或者绝对净收益和相对控制优势仅一个成立 | 不下结论，补新数据/保留探索；禁止优化到“通过” |
| NO EDGE | 样本与quality/control gates充分，但OOS主净均值<=0或delta<=0；或成本/延迟/去top5压力反复显示优势消失 | 停止该版本交易候选；保留所有证据 |

若CI上限<0，可标 NEGATIVE EVIDENCE，仍归 NO EDGE。一次轻微负点估计不等于数学证明不存在优势；报告估计不确定性。KEEP 基于 underlying 固定horizon 与冻结执行模型分别检查，不能用执行模型利润掩盖原 edge 检验失败。所有失败的主候选都进入 final decision 表，禁止只输出胜者。

## 9. 执行模拟：只在 edge gate 后

执行引擎采用真实 1m 路径，入场 next-bar，风险与资金约束明确。同一分钟同时 hit TP/SL 时缺少逐笔排序，基线按 SL 先触发；gap 超 stop 以可成交开盘价加成本退出，不能按理想 stop 价。limit 单纯被 high/low 触及不等于必然成交，基线优先保守 market 模型；收盘退出、费用、卖空限制均冻结。

组合回测独立于 event study：初始虚拟资金、每笔风险、最大并发、每天最大交易数、长短冲突、资金占用和累计净值全部报告。风险拟议默认每笔0.1%虚拟净资产、日损0.5%、并发1、每日最多3笔、无隔夜；这些是待用户审批的paper配置，不是收益优化参数。short 无资格则long-only版本需重新登记，不能沿用双向验证结果。

## 10. Paper forward test

### 10.1 两种模式

1. `shadow`：实时信号、假想执行、quote与延迟日志，不调用订单接口。通过授权的只读订阅开展。
2. `broker_paper`：用户单独批准后，明确 SIMULATE、脱敏账户 allowlist、symbol allowlist 和 qty/risk cap；任何 REAL 请求直接拒绝。模拟成交与真实市场成交能力有差异，不能宣称实盘已验证。

开始前锁定版本、起止/停止条件、主指标；至少60个session且100笔已完成paper交易，先到任一条件不足继续收集，不用盈利时刻提前结束。若超过120session仍样本不足，标 WEAK并报告，不能降门槛。冻结版本期间不改信号/TP/SL；研究分支新版本不影响正在运行的paper版本。

### 10.2 运行安全与监测

- 每日开盘前检查日历、行情新鲜度、完整预热、订阅状态、账户环境、挂单与 SPY underlying 持仓；启动和重连都先 reconcile。
- order intent 用持久化唯一 `event_id`/client intent id，维护 CREATED/SENT/ACK/PARTIAL/FILLED/CANCELLED/REJECTED/UNKNOWN 状态。超时先查订单与成交，禁止盲目重复下单。
- 报价延迟默认>10秒暂停新单；bar完成后30秒仍未确认或任意数据缺口暂停信号。阈值在capability测试后锁定；时间同步、断连、拒单、超风险、持仓不一致触发kill switch。
- kill switch 停新单、查询/撤销挂单；退出持仓仅按事先获批的SIMULATE应急平仓政策执行。无法确认时报告 UNKNOWN_POSITION，不声称已flat。每次恢复必须核验订单及SPY underlying持仓。
- 常规收盘前10分钟停止新单；前5分钟执行批准的平仓策略，前1分钟核验flat；半日市同样相对收盘计算。失败立刻报告，不能用进程退出代替平仓。
- 每次确认开/平仓后输出可直接查看的PNG：SPY 1m、MA9/MA20/MA50、signal/entry/exit、成交标记和纽约时间；HTML仅补充。
- 无人值守调度、通知目的地、运行机器和停机恢复另行明确，不默认创建监控任务或外发消息。

### 10.3 Paper 验收

确认无重复订单、无跨环境请求、无未解释隔夜持仓；所有事件与成交可对账。报告paper净期望/CI、fill ratio、拒单/延迟/slippage、模型与实际差异及收益集中度。paper KEEP 要求样本门槛、净均值>0且日期bootstrap95%CI下限>0，并且没有未解决执行异常；否则WEAK或NO EDGE。重大运行异常为FAILED_EXECUTION，不与统计NO EDGE混淆。任何实盘仍需独立评审与授权。

## 11. 后续 option mapping（不属于首轮实施）

每日paper复盘与优化选择遵守 `daily_review_protocol.md`：收盘对账后无论盈亏/无交易/失败均出日报，报告当日与累计证据，最多三个优化选项由用户选择和批准。当前版本冻结，候选须新的未来shadow验证；不能自动改策略或替换运行版本。模板见 `daily_review_template.md` 和 `optimization_decisions_template.csv`。自动生成器与调度在paper模块实施，当前模板并不代表功能已运行。

只有 underlying OOS 与paper通过后才提出新的审批计划。研究 delta exposure、Gamma/Theta、IV变化、spread、手续费、流动性、到期日、行权/指派、到期残余SPY、仓位风险；不把 underlying bps 直接乘杠杆当期权PNL。

需要同时间历史 option NBBO/可交易quote、strike/expiry、Greeks与corporate actions；缺数据只可说明限制，禁止用今日链重建旧日价格。先预登记单一结构与delta/DTE范围，对long option和spread分开研究。0DTE是额外高风险研究，不默认优先。模拟平台是否支持combo必须实测；不支持时不得自动拆腿，须披露legging/清理风险并单独获批。expiry后核验期权和underlying持仓。采用新的冻结验证、成本与paper流程，不重用已消耗OOS声称独立证据。

## 12. 目录与模块职责

```text
spy_intraday_research/
  README.md
  AGENTS.md
  pyproject.toml
  configs/research_v1.yaml
  configs/paper_v1.example.yaml
  docs/spec.md
  docs/research_registry.csv
  docs/decisions.md
  src/spy_research/
    cli.py
    adapters/futu_quotes.py
    adapters/futu_paper.py
    data/calendar.py
    data/ingest.py
    data/quality.py
    data/normalize.py
    features/causal.py
    features/states.py
    setups/orb.py
    setups/vwap_pullback.py
    setups/failed_breakout.py
    setups/gap_fade.py
    study/events.py
    study/forward_returns.py
    study/controls.py
    study/inference.py
    study/robustness.py
    study/splits.py
    execution/simulator.py
    execution/paper_engine.py
    execution/reconcile.py
    reporting/tables.py
    reporting/charts.py
    audit/manifest.py
    audit/logging.py
  tests/unit/
  tests/integration/
  tests/fixtures/
  data/raw/                 # immutable, gitignored
  data/normalized/          # partitioned, gitignored
  data/quarantine/          # reason + raw pointer
  artifacts/<run_id>/
  locks/<version>/
  logs/<run_id>/
```

adapter只负责协议/返回类型/脱敏；data负责时间口径与quality；features不访问未来；setups纯函数只产event；study不发订单；simulator只读缓存；paper adapter是唯一订单边界；reporting只消费已验证产物；audit负责hash/manifest/访问记录。依赖方向单向，任何研究CLI不得import并初始化trade context。

实现优先Python、小模块、类型/schema校验；不引入不必要框架。依赖锁定，包括futu-api、pandas/numpy、适用交易日历、统计库、pytest和plotting库；版本从实际兼容性测试确定，禁止在规格中编造安装结果。

## 13. CSV / MD / 日志契约

所有CSV UTF-8、固定列顺序、UTC ISO8601、ET带偏移、数值单位写schema、null不替换0。event_id由版本/symbol/session/setup/方向/signal_time生成稳定hash。

| 输出 | 主要内容 |
|---|---|
| capability_report.md | 数据权限、版本、覆盖、接口/交易限制 |
| data_quality.csv / data_quality.md | 每session expected/actual bars、缺口、重复、异常、隔离原因 |
| market_states.csv | session/time、连续特征、标签、available_at、split |
| events.csv | event_id、setup/version、direction、level、signal_time、entry_time、state、split、quality |
| forward_returns.csv | event_id、horizon、entry/exit、gross/net_bps、成本、MFE/MAE、censored reason |
| matched_controls.csv | event/control ids、距离、权重、日期、matching reason |
| edge_summary.csv | split/candidate/horizon、events/days、mean、delta、CI、p_raw/p_adjusted、gate |
| robustness.csv | stress case/subperiod、估计、CI、样本、pass/fail |
| trials.csv | 所有尝试、参数、统计族、访问过的数据、时间、结果hash |
| trades.csv / equity.csv | 冻结执行模型、风险、费用、持仓、净值 |
| paper_events.csv / paper_orders.csv / paper_fills.csv | signal/quote/intent/order/fill、延迟、环境、脱敏账户 |
| paper_reconciliation.csv | 挂单、成交、underlying持仓、差异与处理状态 |
| decision.md / report.md | KEEP/WEAK/NO EDGE理由、失败项、局限、下一阶段权限 |
| manifest.json / lock_manifest.json | 代码/配置/数据hash、环境、split、seed、状态 |
| entry_exit_*.png | 已确认成交与MA9/20/50图 |

日志为JSONL：UTC时间、run_id、阶段、event_id、severity、error_code、retry_count、elapsed_ms；禁止记录原始凭据或完整账户对象。阶段状态 RUNNING/SUCCESS/FAILED_DATA/FAILED_ANALYSIS/FAILED_EXECUTION/INSUFFICIENT；统计标签与运行状态分别存储。异常必须保留trace（脱敏）、已完成checkpoint和partial标识；失败不发布SUCCESS报告。输出先临时文件再原子rename；停止信号能释放上下文，恢复不覆盖历史版本。

## 14. 测试与验收验证

必要单元测试：timestamp起止转换/DST/半日市、重复分页与断点幂等、缺bar隔离、OHLC与5m聚合、daily预热与corporate-action标记、VWAP重置、available_at约束、各setup正反/边界/无事件、next-bar填单、horizon/censor、short收益符号、成本去重、matching不跨split/不引用未来、date-block重采样与control复用、Holm族、锁定后禁止重跑调参、intrabar TP/SL保守处理、gap stop、partial fill、timeout reconcile、kill switch与REAL拒绝。

性质测试：追加未来数据不能改变过去feature/event；切掉最后未完成bar不改变已完成事件；打乱输入后正规化结果一致；同seed/cache结果一致；未来价格注入不得影响过去signal。合成fixture包含无edge与明确已知edge，验证推断路径而非只测试函数返回类型。

集成测试以mock OpenD为主，不默认下单；只读live smoke需验证连接、权限、小窗口分页和关闭上下文。SIMULATE下单测试须在授权范围内。所有测试产出数量/结果/命令/环境，禁止用未经运行的“通过”填报告。

## 15. 拟实现运行命令

以下是目标CLI契约，当前尚不存在，不代表已经运行。PowerShell中在获批创建的项目目录、项目专用虚拟环境执行；不全局安装。日期填写实际可得样本并冻结，不能照抄未知区间。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m spy_research.cli doctor --config configs/research_v1.yaml
.\.venv\Scripts\python.exe -m spy_research.cli ingest --config configs/research_v1.yaml --start YYYY-MM-DD --end YYYY-MM-DD
.\.venv\Scripts\python.exe -m spy_research.cli validate-data --config configs/research_v1.yaml
.\.venv\Scripts\python.exe -m spy_research.cli register --config configs/research_v1.yaml
.\.venv\Scripts\python.exe -m spy_research.cli split --config configs/research_v1.yaml
.\.venv\Scripts\python.exe -m spy_research.cli study --split train --config configs/research_v1.yaml
.\.venv\Scripts\python.exe -m spy_research.cli evaluate --split validation --candidate candidate_v1
.\.venv\Scripts\python.exe -m spy_research.cli lock --candidate candidate_v1
.\.venv\Scripts\python.exe -m spy_research.cli evaluate --split locked-oos --lock locks/candidate_v1/lock_manifest.json
.\.venv\Scripts\python.exe -m spy_research.cli report --run-id RUN_ID
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m spy_research.cli paper --mode shadow --lock locks/candidate_v1/lock_manifest.json
# 仅独立获批后：
.\.venv\Scripts\python.exe -m spy_research.cli paper --mode broker-paper --config configs/paper_v1.yaml --lock locks/candidate_v1/lock_manifest.json
```

CLI默认不下载、调度、下单或解锁OOS；每条命令作用清楚。doctor/read-only与paper-order路径隔离。失败返回非零exit code；同时输出脱敏错误、run_id、恢复建议。`register/split/lock`拒绝覆盖既有冻结版本；`evaluate locked-oos`复跑仅允许字节相同的重现审计，不允许新参数或再次选型。

research配置必须明确：symbol、endpoint env names、日期范围、日历、adjustment、bar timestamp语义、质量门槛、split边界、feature/state定义、setup变体、horizons/primary、成本/stress、matching/caliper、bootstrap/seed、multiplicity、样本与decision阈值、输出目录、registry hash。paper配置另列环境allowlist、账户引用、risk caps、stale limits、停机/平仓政策，不携带secret。

## 16. Phase 1–5 验收标准

| Phase | 工作与交付 | 通过条件 / 停止条件 |
|---|---|---|
| 1 数据基础 | 独立项目、只读Futu adapter、1m/daily缓存、派生5m、日历与quality报告、manifest | 接口/权限/时间语义实测；无未解释重复/缺口进入主集；hash可重现；所需测试通过。覆盖不足明确INSUFFICIENT，不伪造历史 |
| 2 状态与setup事件 | 因果features/states、6变体双向事件、forward-return表、Train探索报告 | future-append不变测试通过；next-bar无泄漏；四setup可精确重现；registry先于结果；样本门槛/成本标注完整 |
| 3 edge验证 | matched controls、bootstrap/Holm、robustness、最多2候选、Validation、edge证明后的有限TP/SL、锁定、一次OOS、decision.md | 按固定KEEP规则晋级；WEAK补证据；NO EDGE停止该版本。所有试验与失败留痕；OOS访问受审计 |
| 4 paper forward | shadow，再经授权SIMULATE；orders/fills/reconcile、MA图、每日审计、paper总结 | 60session+100笔、执行无未解决异常、净期望CI通过；不足WEAK；风险异常FAILED_EXECUTION；不得自动真实交易 |
| 5 option mapping计划/受批研究 | 数据可行性、结构/Greek/成本/到期风险、独立验证计划与paper评估 | underlying和paper先通过，option数据可核验，结构另行注册与授权；无可靠数据则停止。完成研究不等于实盘上线 |

每阶段PR描述包含实际实现范围、测试证据、产物、失败/未完成事项和下一阶段边界。Phase 3没有KEEP时，Phase 4/5不强行推进；仍应交付完整负结果报告。

## 17. 禁止过拟合与最终交付清单

禁止：全参数穷举、不断添加指标、按表现删日期、从完整日标签推实时状态、随机拆日期、将重叠事件当独立样本、先看OOS再锁定、只报冠军、改变成本挽救策略、用模拟理想成交宣称实盘优势、先优化TP/SL再寻找解释、假造数据/测试/交易结果。

最终交付应能回答：数据来源与覆盖是否可信；规则当时能否知道；相对matched controls是否有优势；净成本是否仍为正；是否在独立期与邻域保持；paper执行是否兑现；有哪些门槛失败；当前授权到哪一步。提供CSV/MD/PNG与manifest，不仅一个总盈亏数值。

Codex启动实施时先只读确认目标目录、用户AGENTS、可用代码图工具与Futu capability。代码发现优先codebase-memory-mcp；新仓库未索引时先index_repository，工具不可用才对相关文件精准搜索。列明Phase 1范围和PR方案，等待“批准”；获批后按此规格持续执行到该阶段完整、可复核的交付，不擅自扩大到订单或下一阶段。
