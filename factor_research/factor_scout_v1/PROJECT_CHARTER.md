# Factor Scout V1 — 项目主控规范（PROJECT_CHARTER）

**文档版本**：v1.0（2026-10-16）  
**执行状态**：`DESIGN_APPROVED_FOR_SCAFFOLD_ONLY`；尚未开始真实 TRAIN 轻筛  
**定位**：SPY 5分钟日内**因子预筛选**，不是因子显著性证明，不是交易策略回测，不是实盘系统。  
**优先级**：本文档是 Factor Scout V1 后续 Codex 任务的主控约束；如与新需求冲突，先报告差异，只有用户明确批准后才能修改本文件并升版。

## 0. 每次接管/重复沟通的固定开场

进入项目后**先读本文档**、最近一次 `STATUS.md` 和 `FACTOR_REGISTRY.csv`；先核对当前阶段、许可范围、既有缓存与输出，再执行。每次只执行本轮获批任务。输出最多包含：执行摘要、结果/异常、改动文件、测试证据、下一个授权门；不要重复长篇解释旧项目历史。任何新对话不得将“此前建议”当作“已授权执行”。

**单一目标**：以最少研究计算、最少 Codex 往返与最少无效审计，快速排除明显不合适的日内因子，并选出少数值得独立验证的候选；最终审计标准不降低，只是**后移**。

## 1. 边界与旧项目继承

- 工作树（Windows）：`C:\Users\cbcbe\.codex\worktrees\futu-factor-progress-dashboard-v1\Futu`
- **新增独立目录**：`factor_research/factor_scout_v1/`。所有新代码、规范、人工测试、生成结果限于本目录；不在旧 FDL V2 上继续做 R2.2c，除非用户单独批准。
- 冻结并**不得修改**：`factor_research/factor_discovery_lab_v2/` 全部历史 V1/R1/R2/R2.1/R2.2/R2.2a/R2.2b，以及 C1、Dashboard、Registry、历史 Attempt/Manifest。旧项目只读复用经过检查的定义/函数，不继承旧研究结果的可信地位。
- 已知旧版本：`FDL_V2_R2_2B_INDEPENDENT_AUDIT_BLOCKED`；其 PIT 日线时间语义、全因子不可识别退出、Forward Outcome 口径存在未解决问题。禁止把旧版本的回测结果、p值或旧产物直接用于新候选评级。
- 既有 TRAIN 范围：`US.SPY`、XNYS RTH、5分钟，`2025-10-01` 至 `2026-06-30`，既往187个交易日/14,514根Bar（历史描述，不代表新程序读取后已核验）。**真实 TRAIN 读取当前未授权**；需独立批准后才能运行。绝不读取 Validation/OOS，绝不接交易账户/持仓/订单。
- 市场数据优先使用**用户已有的本地合法缓存或只读 Futu OpenD**；不引入付费/机构字段、Level 2、逐笔主动买卖方、Dealer Gamma 等当前资源无法可靠获得的信息。
- 用户主要通过 **Codex Windows App GUI** 操作；不要求用户自己敲 PowerShell。每次 Codex 指令开头必须标注：新指令/补充、模型、推理强度、粘贴位置、操作步骤。

## 2. 精确研究对象：因子不是策略

因子 = 在给定Anchor已经可知的市场状态或信号，映射到可量化的、未来一小段时间的**价格方向、波动率或状态变化**。第一轮只测试“有没有可观察的条件差异”，不模拟订单、胜率、止盈止损、资金曲线、期权PnL或可交易Edge。

### 首批冻结因子（不要根据结果改写定义）

| ID | 既有机制 | 研究类型 | 设计阶段初步处置 |
|---|---|---|---|
| F01 | Opening Drive Persistence | 方向 | REVIEW |
| F02 | Opening Volatility Persistence | 波动率 | REVIEW；历史关联仍属未验证探索结果 |
| F03 | Morning Directional Efficiency | 方向 | WATCH_CAPACITY（历史仅19事件） |
| F04 | Previous-Day Close Location | 状态/条件方向 | REVIEW |
| F05 | Previous-Day Range Regime | 状态/波动率 | WATCH_MATCHING（历史匹配47） |
| F06 | Midday Range Position | 方向 | REVIEW |

**公式来源约束**：从旧 FDL V2 的冻结 Factor Spec/实际因子源码读取完整公式、时间、阈值；Registry记录精确路径、版本/文件hash。**不得根据英文名称自行猜公式**。找不到定义则 `BLOCKED_SPEC`，不运行替代公式。上述 REVIEW/WATCH 均为**开发排期**，不是统计结论。

## 3. 三级漏斗与严格阶段门

### Level 0 — 静态可行性（零行情、零回测，默认现在执行）

每个因子依次检查：①经济/市场机制是否明确；②数据字段是否已具备；③计算是否完全基于Anchor前已完成数据；④目标是方向/波动率/市场状态哪类；⑤Anchor到未来观察窗是否处于可交易时段；⑥是否与其他因子高度同义/重复；⑦既有历史容量提示。只做`REVIEW / WATCH / DROP_LOGIC / BLOCKED_DATA / BLOCKED_SPEC`标签与一句理由，不做收益优劣排序。

### Level 1 — 批量轻量事件统计（**必须另行获得真实 TRAIN 读取许可**）

**只进行一次读取和一次统一特征/Forward响应计算**：

1. 数据门：读入Raw OHLC，验证timestamp、时区、交易日历、RTH、唯一性、OHLC合法性、Bar完整性和数据身份；不得以最终复权直接冒充历史PIT数据。
2. 事件：严格复用冻结公式，一次计算F01–F06的事件掩码与Anchor可见特征；同日信号/重叠窗口按预先固定规则计数，暴露事件数和独立事件日均要呈现。
3. 响应：统一采用Anchor收盘后**未来6根完整5分钟RTH Bar**的预先固定定义；未来窗口不足、跨session或跨不可比较公司行动窗口直接排除并注明原因。若冻结某因子的目标/窗口不同，以冻结定义为准，并分列不同指标，不能静默改写。
4. 对照：使用同Anchor时钟位置、同未来窗口的**描述性基线**（全体合格session以及无信号session），只比较条件均值/中位数、方向比例或实现波动率；不称因果控制，不做匹配显著性检验。
5. 解释：方向类报告`mean_forward_bp`、`median_forward_bp`、`delta_vs_baseline_bp`、向上比例；波动率类报告非年化RV及基线差异/比率；状态类报告条件分层，不与方向/波动率跨类别排名。
6. 稳定性：把既有TRAIN按日期**固定时间顺序**分成约前60%与后40%两个探索窗口，避免跨界Forward标签。显示每段事件数与效果方向；两段均为**TRAIN内部探索，绝非OOS**。
7. 输出：为每个因子保留事件数、独立日数、排除数及原因、结果、基线与稳定性，不能只给赢家。

**Level 1禁止**：逐因子重新抓数据、交易模拟、完整Matching、2,000次Bootstrap、p值排名、Holm、复杂Manifest、因子优化、测试后重定义阈值。允许统一预先固定的轻量数据及输出hash清单用于复现。

### Level 2 — 候选对比（仅Level 1有资格者）

比较：样本数量、同Anchor基线增量、时间稳定性、市场环境依赖（仅用已可得、Anchor前可见字段）、事件重叠/相关性、机制解释与数据可靠度。控制组/匹配和Bootstrap**只在晋级后**交给旧FDL严格验证层或其另行批准的修复版本，不在Scout实现一整套复杂推断系统。

### Level 3 — 外部严格验证（不属于本项目当前实施范围）

少数入围者的前视控制、研究注册、匹配、连续交易日Block Bootstrap、多重比较、完整证据、独立Validation/OOS及交易成本回测。历史已反复审视的TRAIN数据不能被重新命名为独立OOS。

## 4. 初筛规则与标签（研究优先级，不是显著性检验）

- `KEEP_FOR_DEEP_TEST`：数据有效，具一定事件/独立日数量，与相同Anchor基线存在值得复核的效果，前/后探索窗口没有明显反转，机制可解释。
- `WATCH_CAPACITY`：事件/独立日偏少；不可据此判定无效。
- `WATCH_UNSTABLE`：效果不稳定或集中于极少日；不做确证性结论。
- `WATCH_OVERLAP`：与另一因子事件高度重叠，需合并研究优先级。
- `DROP_LOGIC`：PIT不可修复、缺乏定义或业务上根本不可执行时的逻辑排除（没有样本量时不得用“无Edge”代替）。
- `BLOCKED_DATA` / `BLOCKED_SPEC` / `BLOCKED_PIT`：缺必要字段、冻结定义或数据因果资格；必须显式停用。
- `EXPLORATORY_SCREEN_ONLY`：所有Level 1/2结果的统一证据级别。没有 `EDGE_CONFIRMED`、`OOS_PASS` 或 `LIVE_READY` 标签。

**容量阈值**：Level 1先用已有FDL经验显示`exposed_events`、`unique_session_days`与历史 `>=50事件且>=40天` 作为“适合下一阶段统计”的**排期提示**，不是初筛的概率置信门。真正深度推断仍执行已冻结的匹配`>=50对、>=40独立treated日、覆盖率>=50%`等规则，不在初筛擅自放宽。

## 5. PIT / 公司行动安全的最小合同

- 在Anchor T使用的数据必须满足 `bar_available_at_utc <= T`；交易日内不能使用尚未结束的当日High/Low/Close、未来成交量或未来因子输入。
- 前一交易日的信息必须是前一交易日已经完成且在当前T可见的数据；任何Anchor标记的`DAILY_FEATURES`均不可包含当日未来高低收盘。
- 原始价格与公司行动Rehab分离；只有 `effective_at <= T` 且可靠 `available_at_utc <= T` 的事件才能宣称PIT已证实。缺少availability历史证据不得造时间戳；如果不得不以effective-date近似，只能 `PIT_APPROXIMATION_UNVERIFIED`，严格禁用于确认性用途。
- **日内未来6根窗口**和**跨交易日输入**需要分别处理除权影响；无法验证价格口径一致的样本应标记/排除，不得用无效跳空制造“波动率预测”。
- Forward Outcome为事后可观测标签，不允许反馈进预测特征；原始价格收益、复权价格收益与含现金分红总收益必须区分，不能混称。
- 数据存在已知PIT口径缺陷时，运行应输出 `BLOCKED_PIT`/相关资格标记，而不是为了凑样本忽略问题。

## 6. 性能、Token与工程规则（硬性）

1. 只建立**一个可读、可测试的轻量Runner**；不做Codex/WorkBuddy自动循环、不做服务化、不做复杂前端、不做旧FDL复杂Manifest克隆。
2. **一次批量处理所有可运行因子**：数据读取一次、共享特征计算一次、未来响应数组一次、每因子只做掩码/聚合；可使用Pandas/NumPy向量化。不可并发暴力调用OpenD或逐因子重复下载。
3. 只有数据hash/输入规格/源码变动才使缓存失效；初筛输出为CSV和一页中文Markdown报告，附最小运行身份JSON即可。
4. 第一轮先测试6因子；新因子必须登记`factor_id`、公式、Anchor、目标、数据字段、排除/重叠关系，审核后才可添加，不允许因为结果不理想临时改阈值。
5. 每轮Codex只做一阶段，**先复用已有模块并阅读源码，再写代码**；发现障碍先给最小失败证据，不借题重构其他系统。除第一轮和集成里程碑外，不跑全仓pytest；只跑本模块定向测试。
6. 不提交Git、不删旧研究产物、不修改Futu OpenD配置、不碰真实交易API；没有单独授权不得运行真实TRAIN。
7. 进度更新用`STATUS.md`五项：当前阶段、已完成、阻断、最近运行身份、下一授权门，控制篇幅，避免长篇重复历史。
8. 任一失败不得降低统计/数据门槛换PASS；只可修正实现缺陷并留痕。

## 7. 极简目录与交付合同

建议：

```
factor_research/factor_scout_v1/
  PROJECT_CHARTER.md                # 本文件，唯一项目主控规范
  STATUS.md                         # 五项短状态，下一对话先读
  FACTOR_REGISTRY.csv               # 六因子及候选因子冻结定义的索引
  screen.py                         # 单次批量轻筛CLI / 函数入口
  core.py                           # 数据门、PIT、事件、响应和汇总
  tests/test_scout.py               # 人工合成与PIT对抗测试
  outputs/                           # 仅经批准的数据运行才能生成
    FACTOR_SCREEN_RESULTS.csv
    FACTOR_SHORTLIST.csv
    SCREEN_REPORT.md
    SCREEN_RUN_IDENTITY.json
```

可因必要性拆成少数额外文件，但**避免无理由多层目录或几十个contract/manifest文件**。本地输出目录不可覆盖已冻结的其它版本；真实运行需每次唯一Run ID。

`FACTOR_REGISTRY.csv`最少字段：`factor_id,name,target_type,anchor_spec,formula_source_path,formula_source_sha256,required_fields,pit_feasible,stage,status,reason`。

`FACTOR_SCREEN_RESULTS.csv`最少字段：`factor_id,target_type,events,unique_days,eligible_sessions,excluded_count,baseline_definition,forward_mean,forward_median,lift_vs_baseline,early_n,late_n,early_lift,late_lift,overlap_note,pit_status,screen_status,reason`。

`SCREEN_REPORT.md`中文一页，包含：数据身份、因子范围、KEEP/WATCH/BLOCKED/DROP数量、按**各自目标类别**排序、主要限制、下一阶段门。不可附暗示确定盈利的虚构交易绩效。

## 8. 当前唯一授权任务：Phase A — Scaffold + 静态注册表 + 人工测试

**可以做**：只读检查旧项目Factor Spec和源码；新建`factor_scout_v1`；复制本文档；建立STATUS/Registry；设计并实现最小轻量Runner（可在**人工数据**上验证）；跑定向测试，证明PIT、6-bar边界、不同目标、零事件、安全阻断；输出模拟示例但显式标记 `SYNTHETIC_DEMO`。

**不可做**：读取真实TRAIN/Validation/OOS；使用真实Futu OpenD行情发起研究；运行C1、交易模拟或订单；改旧FDL、Git写操作、批量优化、重复校准六因子定义；输出对真实六因子优劣的新事实判断。

**Phase A完成定义**：6因子Registry拥有可追溯公式引用（找不到的标BLOCKED）；轻量代码通过人工测试；能一次处理所有可运行因子并生成规定CSV+中文报告；前视对抗测试通过；STATUS只写`PHASE_A_SYNTHETIC_READY`或`PHASE_A_BLOCKED`；最终停止等待下一次用户授权。

## 9. Phase B真实TRAIN轻筛授权门（尚未授权）

必须经用户**单独明确批准**以下内容后方可运行：具体本地数据路径或只读OpenD获取方式、日期范围、允许的Stage、Run ID、输出目录、不可读Validation/OOS。运行前校验Raw数据完整性、PIT可用性和必要公司行动身份。若数据不合格，返回`BLOCKED_DATA`或`BLOCKED_PIT`，不能绕过因果检查。完成后只得出探索性名单，不产生Edge声明。

## 10. 未解决约束与反跑偏清单

- 旧研究 V1、R2.2b结果及其审计状态均**冻结**，不作为新筛选的统计PASS。
- 真实TRAIN、Validation/OOS均未授权；不能因“项目效率”视为自动批准。
- F02只评估波动率目标，不能和价格方向因子按平均bp混排。
- 早/晚分段是已见过的TRAIN内部探索，不得标为独立OOS。
- 前视正确性与输入复权可比性是初筛也必须保持的最低要求。
- 用阶段门淘汰研究想法；**不对低样本因子宣称“没有Edge”**。
- 高阶严谨验证保留给少数入围者；不得在Scout重写整套FDL V2。
- 任何阶段性统计显著、合成测试PASS或回测图形，都不得解释为实际可盈利策略。

---

**当前冻结结论**：`FACTOR_SCOUT_V1_DESIGN_READY`；`PHASE_A_NOT_STARTED`；`REAL_TRAIN_NOT_AUTHORIZED`；`VALIDATED_TRADING_EDGE=0`。
