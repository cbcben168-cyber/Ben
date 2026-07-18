# Forward Factor 信号与通知系统设计

## 1. 文档定位

本文定义一个每日自动运行、只生成期权日历价差信号、由用户手动交易的 Forward Factor（FF）系统。Python 负责确定性计算和数据持久化；系统不连接交易账户、不读取持仓、不提交、修改或撤销订单。

本设计的第一版覆盖 100 个高流动性美股和 ETF，使用 Futu OpenD 行情，在北京时间每日 08:00 运行。有效信号自动发送至 `cbcben168@gmail.com`，同时生成 Windows 桌面通知和 Codex 自动化摘要。用户在 Futu 手动成交后，通过本地页面登记实际开仓和平仓信息。

## 2. 成功标准与非目标

### 2.1 成功标准

1. 每个美股交易日完成一次 100 标的扫描，并为每个标的产生唯一、可审计的结果。
2. 只有数据完整、财报规则通过、双层流动性通过且 `FF > 0.20` 时才产生 `BUY_CANDIDATE`。
3. 所有拒绝和失败均有稳定状态码，不允许静默跳过或以默认值代替缺失数据。
4. 同一扫描批次重复运行不会产生重复信号、重复邮件或重复同步记录。
5. 本地数据库提交成功后才允许发送通知和创建同步任务。
6. Sites 或 Obsidian 不可用时，本地扫描和本地审计仍可完成；失败同步必须自动重试并告警。
7. 所有时间内部使用 UTC；用户界面同时显示 `America/New_York` 和 `Asia/Shanghai`。
8. 全部确定性逻辑、状态转换、费用字段和同步幂等性由 `pytest` 覆盖。

### 2.2 非目标

- 不连接券商或真实交易账户。
- 不自动下单、撤单、改单或确认成交。
- 不接入 TradingView Webhook。
- 不把 Sites D1、Obsidian 或邮件当作权威交易记录。
- 第一版不做历史期权策略回测，不宣称 27% 年化回报或 2.4 Sharpe 已在本系统复现。
- 第一版不在统计样本不足时输出 Quarter Kelly 数值。

## 3. 总体架构

系统采用本地优先、单向同步架构：

1. Windows Task Scheduler 在北京时间 08:00 启动扫描。
2. 数据层读取 Futu OpenD 期权筛选/快照、标的池和财报日历。
3. 扫描器执行数据质量、期限、财报、流动性和 FF 计算。
4. 结果以单个数据库事务写入本地 DuckDB；DuckDB 是唯一权威数据源。
5. 提交成功后，通知 outbox 发送 Gmail、Windows 和 Codex 摘要。
6. 同步 outbox 将结构化查询副本写入 Sites D1，并向 Obsidian vault 导出 Markdown。
7. 用户在 Futu 手动成交后，在本地页面登记仓位；监控器据此生成 T1 离场提醒。

## 4. 模块边界

### 4.1 `FutuOptionProvider`

- 只使用 `OpenQuoteContext`，禁止导入或实例化交易上下文。
- 查询期权到期日、筛选结果、快照、IV、Greeks、成交量、未平仓量和 Bid/Ask。
- 不为日常扫描订阅实时推送；优先使用快照式接口，避免占用期权订阅配额。
- 遵守接口频率限制，使用指数退避和带抖动重试。
- 原始 Futu IV 单位在 provider 边界统一为小数；例如实时字段 `14.794` 转为 `0.14794`。

### 4.2 `EarningsProvider`

- 股票第一版使用 `yfinance` 的已公布财报日历作为可替换 provider。
- ETF 标记为 `EARNINGS_NOT_APPLICABLE`。
- 股票无法取得明确财报日期时，结果为 `HOLD_EARNINGS_UNKNOWN`。
- 从扫描时间至 T2 到期日（含两端）存在财报时，结果为 `HOLD_EARNINGS_BEFORE_T2`。
- provider 保存来源、抓取时间和原始值；后续可替换为付费财报源，不改变扫描器接口。

### 4.3 `UniverseService`

- `universe_registry` 恰好保存 100 个启用标的及版本号。
- 初始名单由 Futu 当前期权活跃度产生候选，再人工复核一次。
- 系统每日采集标的层期权总成交量快照；每周重新排名，但名单变更必须创建新版本。
- 只有最近 20 个有效美股交易日的标的层期权总成交量均值大于 10,000 才通过第一层流动性。
- 不足 20 个有效观测时为 `HOLD_LIQUIDITY_WARMUP`，不得产生买入信号。
- 历史窗口存在缺口时为 `HOLD_LIQUIDITY_HISTORY_GAP`，不得用零填充。

### 4.4 `ContractSelector`

- T1 目标为 60 DTE，允许 55 至 65 DTE。
- T2 目标为 90 DTE，允许 85 至 95 DTE。
- 各自在允许窗口内选择绝对偏差最小的到期日；并列时选择较早日期。
- T2 必须严格晚于 T1；找不到任一期时为 `HOLD_DTE_UNAVAILABLE`。
- ATM strike 为距标的现价绝对距离最小的有效行权价；并列时选择较低行权价。
- 信号 IV 使用各到期日 ATM Call 和 ATM Put 的有效 IV 算术平均。任一腿缺失时为 `HOLD_ATM_IV_INCOMPLETE`。

### 4.5 `LiquidityGate`

流动性采用双层规则：

1. 标的层：20 日平均全部期权总成交量必须大于 10,000。
2. 合约层：计划结构的每条腿必须同时满足：
   - `bid > 0`、`ask > bid`、`mid > 0`；
   - 相对价差 `(ask - bid) / mid <= 0.15`；
   - 未平仓量 `open_interest >= 500`；
   - 当日成交量 `volume >= 50`。

任一腿失败时不推荐该结构，并保存具体失败字段。第一版阈值是保守的执行可行性基准，不声称为最优参数；变更必须创建新策略版本。

## 5. FF 数学定义

所有 IV 进入计算前均为有限、正的小数。设：

- `sigma_1`：T1 ATM Call/Put 平均 IV；
- `sigma_2`：T2 ATM Call/Put 平均 IV；
- `T1 = DTE1 / 365`；
- `T2 = DTE2 / 365`。

远期方差：

```text
forward_variance = ((sigma_2^2 * T2) - (sigma_1^2 * T1)) / (T2 - T1)
```

远期波动率与 FF：

```text
sigma_forward = sqrt(forward_variance)
FF = (sigma_1 - sigma_forward) / sigma_forward
```

硬性规则：

- `T2 <= T1`：`HOLD_INVALID_TENOR_ORDER`。
- `forward_variance <= 0` 或非有限值：`HOLD_INVALID_FORWARD_VARIANCE`。
- `sigma_forward <= 0` 或非有限值：`HOLD_INVALID_FORWARD_VOLATILITY`。
- `FF > 0.20` 才是 `BUY_CANDIDATE`；`FF == 0.20` 不触发。
- 多个候选按 FF 降序、相对价差升序、ticker 字母顺序稳定排序。

## 6. 推荐结构

### 6.1 方案 A：ATM Call Calendar

- 卖出 T1 ATM Call。
- 买入 T2 同行权价 Call。
- 两腿均通过合约层流动性后才推荐。
- 邮件展示组合 Bid、Ask、Mid 和净借记估算，但不生成订单。

### 6.2 方案 B：35 Delta Double Calendar

- 分别选择 T1 最接近 `+0.35` Delta 的 Call 与最接近 `-0.35` Delta 的 Put。
- T2 使用与对应 T1 相同行权价的 Call/Put。
- 四腿全部通过合约层流动性后才推荐。
- 若方案 B 失败但方案 A 通过，只推荐方案 A，不将失败腿替换为相邻 Delta。

## 7. 仓位建议与 Quarter Kelly

- 默认建议风险预算为账户净值的 4%，用户可配置 2% 至 8%，硬上限为 8%。
- 系统不读取账户净值；用户在本地设置中手动维护用于建议的净值。
- Quarter Kelly 仅在同一策略版本具有至少 100 个已完成、无重叠定义的历史交易生命周期，并有正期望值、有效胜率和平均盈亏比时计算。
- 第一版没有合格期权回测样本，因此输出 `KELLY_UNAVAILABLE_INSUFFICIENT_SAMPLE`，并使用 4% 默认建议，不伪造 Kelly 结果。
- 建议仓位仅供人工决策；邮件必须明确显示“非订单、需人工复核”。

## 8. 信号与人工持仓生命周期

### 8.1 信号状态

`SCANNED -> BUY_CANDIDATE -> NOTIFIED -> EXPIRED`

任何质量或规则失败直接落入稳定的 `HOLD_*` 状态。相同 `strategy_version + scan_date + ticker + T1 + T2` 生成确定性 `signal_id`。

### 8.2 人工持仓状态

用户在本地页面点击“我已开仓”，登记：

- `signal_id`；
- 实际合约代码与每腿方向；
- 数量；
- 实际净成交价格；
- 成交时间；
- 可选备注。

仓位状态为：

`OPEN -> EXIT_DUE -> CLOSED`

用户必须手动登记平仓价格和时间。系统不根据行情推断用户已经成交或平仓。

### 8.3 离场提醒

- T1 到期前一个美股交易日发送预提醒。
- T1 到期日发送最终提醒，并在本地页面标记 `EXIT_DUE`。
- 提醒要求用户在到期日收盘前手动组合平仓，以降低 pin risk。
- 未登记为 `OPEN` 的信号不产生持仓级离场提醒。

## 9. 本地数据库

本地权威数据库使用 DuckDB，至少包含：

- `strategy_versions`
- `universe_versions`
- `universe_members`
- `option_liquidity_daily`
- `option_snapshots`
- `earnings_events`
- `scan_runs`
- `scan_results`
- `signals`
- `positions`
- `position_legs`
- `notifications`
- `sync_outbox`
- `audit_events`

所有写入使用事务。原始快照不可覆盖；更正产生新记录并通过 `supersedes_id` 关联。时间字段使用 UTC，金额和 IV 字段禁止存储字符串 `N/A`。

## 10. 通知

### 10.1 Gmail

- 收件人与发送目标均为 `cbcben168@gmail.com`。
- 扫描产生有效候选后自动发送，无需逐封批准。
- 无候选时发送一封简短日结；运行失败发送失败摘要。
- Gmail 认证只放在 `.env` 或系统凭据存储，不写入代码、日志、数据库、Sites 或 Obsidian。

### 10.2 Windows

- 使用 Windows 原生 toast。
- 通知只包含 ticker、FF、信号数量和本地页面入口，不展示密钥或完整账户信息。

### 10.3 Codex

- 扫描器完成后写入机器可读摘要。
- Codex 本地自动化在扫描后读取最新已提交结果，发布候选、持仓、离场和失败摘要。
- Codex 自动化是通知消费者，不参与 FF 计算，也不反向修改本地数据库。

通知采用 outbox：数据库事务同时写入业务记录和待发送通知；worker 发送成功后记录 provider message id。重试使用相同幂等键，防止重复邮件。

## 11. Sites D1 与 Obsidian 同步

### 11.1 Sites

- Sites 建立私有、owner-only 的 FF 仪表板。
- D1 保存本地数据的查询副本，不是权威库。
- Sites 提供受保护的 `/api/sync` 写入端点；本地同步 worker 不直接连接 D1。
- 本地 worker 使用独立 bearer secret 调用 `/api/sync`，Sites 端先鉴权、校验 schema 和幂等键，再写入 D1。
- bearer secret 只保存在本机 `.env` 和 Sites 运行时 secret；不得出现在仓库、D1、日志、Obsidian 或通知正文。
- 同步只允许 upsert 已提交的扫描、信号、持仓和通知摘要。
- D1 不保存 Gmail 凭据、Futu 凭据、账户净值或自由文本敏感备注。
- 仪表板提供今日排名、拒绝原因、持仓、离场日历、通知状态和同步健康度。
- Sites 部署属于生产发布；首次部署及任何访问范围扩大必须另行批准。

### 11.2 Obsidian

目标 vault：

```text
C:\Users\cbcbe\OneDrive\Documents\TradingCodex
```

导出目录建议为 `FF-System/`：

- `Daily/YYYY-MM-DD.md`：每日扫描摘要；
- `Signals/<signal_id>.md`：信号详情；
- `Positions/<position_id>.md`：人工持仓生命周期；
- `System/Sync-Health.md`：同步状态。

Markdown 文件包含稳定 YAML frontmatter。导出器只写入 `FF-System/`，使用临时文件加原子替换；不得修改 vault 的 `.obsidian` 配置或其他笔记。

### 11.3 同步一致性

- 本地记录以不可变 `record_id` 和 `updated_at_utc` 驱动同步。
- 每个目标分别维护 checkpoint；一个目标失败不回滚另一个目标或本地事务。
- 重试达到上限后标记 `SYNC_DEAD_LETTER`，通过 Gmail、Windows 和 Codex 告警。
- Sites 或 Obsidian 不允许反向覆盖本地数据库。

## 12. 调度与运行

- Windows Task Scheduler 在每个工作日北京时间 08:00 触发。
- 扫描器使用 NYSE 交易日历判断上一美股交易日；非交易日输出 `SKIPPED_NON_TRADING_DAY`。
- Futu OpenD 未启动、未登录或状态非 `READY` 时，运行失败且不生成候选。
- 同一逻辑交易日只允许一个活动扫描；锁过期必须记录接管事件。
- CLI 提供 `scan --dry-run`、`scan --live-notifications`、`serve`、`sync` 和 `health`，但本地页面是用户首选入口。

## 13. 错误处理与失败关闭

- 行情超时：有限次数重试，仍失败则标的为 `HOLD_MARKET_DATA_TIMEOUT`。
- 期权链分页不完整：`HOLD_OPTION_CHAIN_INCOMPLETE`。
- IV 单位或范围异常：`HOLD_IV_UNIT_OR_RANGE_ERROR`。
- 财报日期未知：`HOLD_EARNINGS_UNKNOWN`。
- 数据库事务失败：整个扫描批次失败，不发送候选通知。
- Gmail 失败：本地结果保留，outbox 重试，Windows/Codex 显示邮件失败。
- Sites/Obsidian 失败：本地结果和通知不回滚，sync outbox 重试。
- 任意未分类异常：记录错误类别和相关 id，日志禁止包含凭据或完整环境变量。

## 14. 测试设计

### 14.1 单元测试

- FF 正常、阈值边界、负/零远期方差、非有限值和 IV 单位归一化。
- 55/65、85/95 DTE 边界、并列规则和 T2 顺序。
- 财报区间两端、ETF 不适用和未知日期。
- 20 日窗口、缺口、严格 `> 10,000` 边界。
- 每条合约流动性阈值及 Bid/Ask 公式。
- 稳定排序、确定性 id、仓位状态转换和 T1 交易日提醒。

### 14.2 集成测试

- 使用固定 Futu fixture，不在 `pytest` 中依赖实时行情。
- DuckDB 事务回滚、幂等重跑和 outbox 去重。
- Gmail、Windows、Codex 消费者使用 fake provider。
- Sites D1 upsert、checkpoint 和失败重试使用测试绑定。
- Obsidian 只写目标子目录、原子替换和 frontmatter schema。

### 14.3 首次 live dry-run

1. Futu 只读连接，禁止交易上下文。
2. 扫描恰好 100 个启用标的。
3. Gmail 默认生成预览但不发送；首次测试邮件另行批准。
4. Windows 测试通知允许发送到本机。
5. Sites 使用非生产测试数据；首次生产部署另行批准。
6. Obsidian 首次写入前显示目标文件清单并另行批准。
7. 输出通过、拒绝、失败总数，并保证三者之和等于 100。
8. 保存 Futu 请求数、重试数、运行耗时和配额使用情况。

## 15. 验收命令与输出

每个实施阶段必须运行：

```text
python -m pytest tests -q -p no:cacheprovider
```

首次 dry-run 还必须生成：

- 本地扫描批次摘要 JSON/CSV；
- 100 标的逐项状态表；
- 候选信号详情；
- Gmail 预览；
- Sites 与 Obsidian 待同步清单；
- 数据质量、重试和配额报告。

## 16. 分阶段实施与 Pull Request

为控制风险，实施拆为独立 PR：

1. 数据契约、DuckDB schema、Futu provider 和 FF 纯函数。
2. 100 标的池、财报、双层流动性和扫描编排。
3. 本地页面、人工持仓和离场状态机。
4. Gmail、Windows、Codex 通知与 outbox。
5. Sites D1 私有仪表板和 Obsidian 单向导出。
6. Windows 调度、健康检查和首次 live dry-run。

每个 PR 只修改对应模块和测试。不得通过删除测试、降低断言或扩大真实交易权限来通过验收。

## 17. 残余风险

1. `yfinance` 财报日历可能缺失或修订；失败关闭会减少信号但避免未知财报风险。
2. Futu 期权链曾出现超时；需要筛选接口、缓存、限速和失败关闭共同处理。
3. 20 日流动性严格暖机意味着新安装前 20 个有效交易日不会产生正式买入信号。
4. Futu IV 接口存在百分数与小数两种单位，必须在 provider 边界归一化并持久化原始单位。
5. 用户可能未登记实际开仓，系统因此不会生成持仓级平仓提醒。
6. Sites 和 OneDrive/Obsidian 是异步副本，短时间内可能滞后于本地数据库。
7. 第一版没有合格的期权历史回测，不能据此验证用户引用的年化收益、Sharpe 或 Quarter Kelly 优势。
