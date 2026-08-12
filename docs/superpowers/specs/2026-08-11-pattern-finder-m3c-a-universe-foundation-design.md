# Pattern Finder M3C-A — Universe Foundation Design Spec

**版本**：1.0

**日期**：2026-08-11

**状态**：DESIGN_READY_FOR_FINAL_APPROVAL

**阶段**：M3C-A — Universe Foundation

**权威 base**：`codex/v2-2a-data-foundation-impl@9fd2256`，已包含 M3B / PR #6 与 Product Blueprint V3 / PR #8
**目标文件**：`docs/superpowers/specs/2026-08-11-pattern-finder-m3c-a-universe-foundation-design.md`

---

## 1. 目的

M3C-A 只建立“哪些证券有资格进入研究股票池”的可版本化、可审计基础。

本设计交付：

1. 不可变的 `UniverseProfile` 与冻结的 `CORE v1`；
2. 可创建 `CORE v2` 和 Custom Profile 的版本流程；
3. Futu 候选证券主数据与筛选证据的取得方式；
4. 可逐级对账的 Universe Funnel；
5. 可重放、可追溯、包含被排除证券的 Universe Snapshot；
6. Scan Batch 与 Profile Version、Snapshot 的强绑定；
7. 不改写历史的 Universe Preview；
8. Futu quota、限频、权限和字段缺失的显式失败规则；
9. Universe 与 Flat Base Detector 的硬边界；
10. 面向普通用户的最小网页调整与预览流程；
11. CORE v1 筛选正确性、完整性和“没有偷偷删股票”的测试策略。

M3C-A 的成功不是“马上扫描几千只股票”，而是：

> 同一份证券事实和同一版本 Profile，在任何机器上都得到相同的逐项判定；任何被排除证券都能说明在哪一级、因为什么被排除。

---

## 2. 输入文档与优先级

本设计读取并约束于：

1. `2026-08-11-pattern-research-scale-review-product-blueprint-v3.md`；
2. `2026-08-09-pattern-research-product-blueprint-v2.1.md`；
3. `2026-08-09-phase1-pattern-finder-detector-definition-v1.md`；
4. `2026-08-10-pattern-review-framework-design.md`；
5. 当前仓库 M3B / PR #6 实际实现。

冲突时优先级为：

```text
本 M3C-A Design Spec
→ Product Blueprint V3 冻结决定
→ Detector Definition V1 的 Detector / Data Quality 边界
→ Pattern Review Framework 的 Review / Detector 边界
→ Product Blueprint V2.1
```

本设计不修改 `phase1-v1` Flat Base 数学规则。

---

## 3. 明确范围

### 3.1 本轮包含

- Universe Profile schema；
- CORE v1；
- Profile 草稿、预览、发布和新版本；
- Futu 元数据与筛选字段采集设计；
- Universe Funnel；
- Universe Snapshot；
- Scan Batch 的 Universe 绑定契约；
- 最小 Universe 设置和 Preview 页面设计；
- 纯 Universe 规则、存储边界与测试设计。

### 3.2 本轮明确禁止

- Flat Base 参数修改；
- Rounded Base；
- Compression；
- READY；
- 千只股票历史 hydration；
- 大规模 Detector 扫描；
- DuckDB / Parquet 性能优化；
- Pattern Instance；
- Review Queue；
- Historical T0；
- ML；
- Future Outcome；
- 账户、券商、订单、TradingView Webhook、期权和 Phase 2 工作。

设计中可以定义未来消费者需要的引用字段，但不得实现上述功能。

---

## 4. 已比较的方案

### 4.1 方案 A — Futu 服务器直接过滤并只保存通过名单

优点：调用少、实现快。

否决原因：

- 无法保存被 Futu 服务器提前过滤的证券；
- Funnel 无法对账；
- 无法解释是否因缺字段、限额或实际不符合而消失；
- 服务器计算和客户端版本变化不易审计；
- 容易把 Universe 条件偷偷演变成不可见黑箱。

### 4.2 方案 B — 本轮下载全市场历史 K 线后全部本地计算

优点：本地计算证据最完整。

否决原因：

- 违反 M3C-A 禁止大规模历史 hydration 的范围；
- Futu 历史 K 线按最近 7 天访问的不同证券占用 quota；
- 把 M3C-B 的工作提前塞进 Foundation。

### 4.3 方案 C — 完整元数据快照 + 本地确定性判定 + fail-closed

采用本方案。

```text
Futu 枚举候选和返回事实字段
↓
标准化为不可变 Universe Evidence
↓
Python 纯规则逐项判定
↓
保存所有候选、全部判定和 Funnel
↓
只把最终 PASS 成员暴露给未来 Scan Batch
```

Futu 可提供的 `AVG_TURNOVER(20)`、`LISTED_DAYS` 等字段作为 M3C-A 的正式输入事实；Profile 的比较逻辑由本地 Python 决定。未来 M3C-B 有完整日线后，只对关键派生字段进行独立交叉核验，不改变 CORE v1 的正式权威口径。

---

## 5. 核心术语

| 术语 | 定义 |
|---|---|
| Profile Family | 稳定配置族，例如 `CORE`、`TECH_ONLY`、`CUSTOM_ABC` |
| Profile Version | 某配置族的一次不可变正式版本，例如 `CORE v1` |
| Draft | 可编辑但不可用于正式扫描的临时配置 |
| Preview Run | 用 Draft 或已发布版本进行的非正式预览，不产生 Scan Batch |
| Universe Evidence | 某证券在某次采集时取得的原始与标准化事实 |
| Funnel Decision | 某证券在某一 Funnel Stage 的 PASS / FAIL / UNKNOWN |
| Universe Snapshot | 某 Profile Version 在某个 as-of 时点对全部候选的不可变评估结果 |
| Universe Member | Snapshot 中最终所有硬条件均 PASS 的证券 |
| Quarantine | 因关键证据 UNKNOWN 或冲突而未通过，但没有被静默删除的证券集合 |
| Scan Batch | 未来 Detector 运行批次；只能绑定已发布 Profile 和完整正式 Snapshot |

---

## 6. 总体架构与边界

```text
Futu Universe Gateway
  ├─ Static Security Info
  ├─ Stock Screening V2
  ├─ Market Snapshot
  └─ Owner Plate / Industry
              ↓
Universe Evidence Normalizer
              ↓
Universe Profile Registry ──→ Universe Evaluator
                                  ├─ Per-field decisions
                                  ├─ Sequential funnel
                                  └─ Final membership
                                           ↓
                              Universe Snapshot Store
                                           ↓
                                  Scan Batch Contract

Flat Base Detector ← 只接收 OHLCV + Data Quality，不接收 Profile
```

组件职责：

- **Futu Universe Gateway**：只负责调用和原样保存外部事实，不做业务取舍；
- **Evidence Normalizer**：统一单位、枚举、时区、缺失值和来源；
- **Profile Registry**：管理 Draft 和不可变 Published Version；
- **Universe Evaluator**：纯函数，根据 Evidence + Profile 产生判定；
- **Funnel Aggregator**：只聚合逐证券判定，不重新解释规则；
- **Snapshot Store**：append-only 保存完整评估；
- **Scan Batch Contract**：禁止 Scanner 自己重算或覆盖 Universe。

---

## 7. UniverseProfile 数据结构

### 7.1 身份字段

| 字段 | 类型 | 规则 |
|---|---|---|
| `profile_family_id` | string | 稳定机器 ID，例如 `CORE`；创建后不变 |
| `profile_version` | positive integer | 同一 family 单调递增，从 1 开始 |
| `profile_version_id` | string | `{profile_family_id}:v{profile_version}`，例如 `CORE:v1` |
| `profile_kind` | enum | `CORE` / `CUSTOM` |
| `display_name` | string | 用户可读名称；发布后不可变 |
| `schema_version` | string | Profile schema 版本，首版为 `universe-profile/v1` |
| `record_state` | enum | `DRAFT` / `PUBLISHED`；Published 记录本身不再改变 |
| `parent_profile_version_id` | string/null | 克隆来源；CORE v1 为 null |
| `created_at_utc` | UTC datetime | 创建时间 |
| `published_at_utc` | UTC datetime/null | 发布时冻结 |
| `change_note` | non-empty string | 为什么创建此版本 |
| `content_sha256` | lowercase sha256/null | Published 必填；对规范化业务内容计算 |
| `filter_content_sha256` | lowercase sha256/null | Published 必填；只覆盖筛选字段，用于跨版本判断业务条件是否重复 |

某版本是否继续出现在网页默认选项中，由独立 append-only `ProfileAvailabilityEvent` 表示：`ACTIVATED` / `RETIRED`。该事件不修改 Profile 内容、版本号或 hash；`RETIRED` 只表示不再推荐新使用，历史 Snapshot 和 Scan Batch 仍可读取该版本。

### 7.2 筛选字段

| 字段 | 类型 | CORE v1 |
|---|---|---|
| `exchanges` | immutable set | `NYSE`, `NASDAQ`, `AMEX` |
| `allowed_security_classes` | immutable set | `COMMON_STOCK` |
| `min_price_usd` | decimal/null | `5.00` |
| `max_price_usd` | decimal/null | null |
| `min_market_cap_usd` | decimal/null | `1_000_000_000` |
| `max_market_cap_usd` | decimal/null | null |
| `liquidity_metric_id` | stable enum | `FUTU_AVG_TURNOVER_20D` |
| `liquidity_evidence_version` | string | 冻结 Futu Screening 字段语义与适配器契约的版本 |
| `min_avg_dollar_volume_20d_usd` | decimal/null | `20_000_000` |
| `min_avg_volume_20d_shares` | decimal/null | null |
| `listing_history_metric_id` | stable enum | `FUTU_LISTED_DAYS` |
| `listing_history_evidence_version` | string | 冻结 Futu Screening 字段语义与适配器契约的版本 |
| `min_listed_days` | integer/null | `250` |
| `sectors` | immutable set / ALL | `ALL` |
| `industries` | immutable set / ALL | `ALL` |
| `sector_mapping_version` | string/null | null；Sector/Industry 为 ALL 时不得建立映射 |
| `include_etf` | bool | false |
| `include_adr` | bool | false |
| `include_otc` | bool | false |
| `include_preferred` | bool | false |
| `include_warrant` | bool | false |
| `include_unit` | bool | false |
| `active_only` | bool | true |

### 7.3 验证规则

- 金额使用十进制定点值，禁止二进制浮点参与哈希；
- 所有美元金额规范化为整数 cents 或规范化十进制字符串；
- 最小值不得大于最大值；
- `ALL` 与具体 Sector / Industry 列表互斥；
- `allowed_security_classes={COMMON_STOCK}` 与所有非普通股开关为 false 是 CORE v1 的冻结语义；
- 未识别枚举、NaN、Infinity、空字符串和 bool 冒充 integer 均拒绝；
- Published Version 不提供 update API；
- Published 内容只可通过新版本复制后修改。

### 7.4 内容哈希

`content_sha256` 覆盖版本身份和影响 Universe 判定的规范化业务内容：

```text
schema_version
profile_family_id
profile_version
parent_profile_version_id
全部筛选字段
```

不覆盖数据库路径、进程 ID、文件 mtime、UI 排序和运行时间。集合先按稳定枚举顺序排序，JSON 使用 UTF-8、固定 key 顺序和固定十进制表达。

`filter_content_sha256` 只覆盖全部筛选字段，不覆盖 `profile_family_id`、`profile_version`、`parent_profile_version_id`、显示名称、说明或时间。发布时使用该 hash 与同一 family 的最新 Published Version 比较；相同则拒绝创建空洞新版本。`content_sha256` 用于精确引用某个正式版本，`filter_content_sha256` 用于判断跨版本筛选语义是否重复，两者不得互换。

---

## 8. CORE v1 不可变冻结版本

```yaml
profile_family_id: CORE
profile_version: 1
profile_version_id: CORE:v1
profile_kind: CORE
schema_version: universe-profile/v1
record_state: PUBLISHED
filters:
  exchanges: [NYSE, NASDAQ, AMEX]
  allowed_security_classes: [COMMON_STOCK]
  min_price_usd: "5.00"
  max_price_usd: null
  min_market_cap_usd: "1000000000.00"
  max_market_cap_usd: null
  liquidity_metric_id: FUTU_AVG_TURNOVER_20D
  liquidity_evidence_version: futu-screening-liquidity/v1
  min_avg_dollar_volume_20d_usd: "20000000.00"
  min_avg_volume_20d_shares: null
  listing_history_metric_id: FUTU_LISTED_DAYS
  listing_history_evidence_version: futu-screening-listing-history/v1
  min_listed_days: 250
  sectors: ALL
  industries: ALL
  sector_mapping_version: null
  include_etf: false
  include_adr: false
  include_otc: false
  include_preferred: false
  include_warrant: false
  include_unit: false
  active_only: true
```

边界值使用闭区间：

- `price == 5.00`：PASS；
- `market_cap == 1_000_000_000`：PASS；
- `avg_dollar_volume_20d == 20_000_000`：PASS；
- Futu Screening `LISTED_DAYS == 250`：PASS。

任何关键证据缺失或冲突均为 `UNKNOWN`，在 CORE v1 中 fail-closed，不得 PASS。

---

## 9. 如何创建 CORE v2 与 Custom Profile

### 9.1 CORE v2

```text
打开 CORE v1
→ 克隆为 CORE Draft（parent=CORE:v1）
→ 修改条件
→ Preview
→ 用户填写 change_note
→ 发布
→ 原子创建 CORE:v2
```

发布事务必须保证：

1. 同一 family 的新版本号为当前最大值 + 1；
2. `filter_content_sha256` 与最新版本相同时拒绝发布；
3. `content_sha256` 唯一且可复算；
4. CORE v1 不发生任何写入；
5. 发布成功后 Draft 变为只读引用或关闭，不转写旧版本。

### 9.2 Custom Profile

用户可以：

- 从 CORE v1/v2 克隆；
- 从另一个 Custom Version 克隆；
- 创建空白 Draft。

首次发布创建：

```text
CUSTOM_<stable_slug>:v1
```

后续修改必须创建 v2、v3。Custom Profile 的名字可在新版本中改变，但 stable family ID 不变。

### 9.3 Draft 的允许行为

Draft 可以反复修改和预览，因为它不是正式历史。Draft：

- 不得绑定正式 Scan Batch；
- 不得冒充 Profile Version；
- 不得覆盖 Published 文件或记录；
- 必须有 `draft_id` 和规范化 `draft_content_sha256`，使同一次 Preview 可追踪。

---

## 10. Futu 候选证券数据取得设计

### 10.1 数据源矩阵

| 业务字段 | Futu 接口/字段 | M3C-A 用法 | 失败处理 |
|---|---|---|---|
| 候选证券 | `get_stock_basicinfo(Market.US, SecurityType.*)` | 分类别枚举并合并 | 整批 discovery 失败 |
| Exchange | static `exchange_type` | 映射 NYSE/NASDAQ/AMEX/OTC | 未知则 UNKNOWN |
| 顶层 Security Type | static `stock_type` | 明确 ETF/Warrant 等 | 未知则 UNKNOWN |
| 稳定身份 | static `stock_id` + `code` | `stock_id` 主身份，code 为当期符号 | 冲突则整批失败 |
| 退市 | static `delisting` | Active 判定证据 | 缺失则 UNKNOWN |
| Price | Stock Screen V2 `PRICE`；snapshot `last_price` 交叉核对 | 正式快照只在规定 EOD 窗口创建 | 冲突则 UNKNOWN |
| Market Cap | Stock Screen V2 `MARKET_CAP`；snapshot `total_market_val` 交叉核对 | USD 规范化后比较 | 单位/值冲突则 UNKNOWN |
| 20D ADV | Stock Screen V2 `AVG_TURNOVER`, `days=20` | `FUTU_AVG_TURNOVER_20D`；M3C-A 唯一正式筛选口径 | 缺失则 UNKNOWN |
| 20D Avg Volume | Stock Screen V2 `AVG_VOLUME`, `days=20` | 可调字段，CORE v1 不启用 | 缺失且未启用不阻断 |
| Listing Days | Stock Screen V2 `LISTED_DAYS` | `FUTU_LISTED_DAYS`；M3C-A 唯一正式筛选口径 | 缺失则 UNKNOWN，不允许以其他口径替代 |
| Listing Date | snapshot `listing_date`；static 已停止维护 | 只保存为辅助证据，不参与 M3C-A 正式判定 | 异常/冲突则 UNKNOWN |
| Industry | Stock Screen V2 `BasicProperty.INDUSTRY` | 仅保存原始 evidence | CORE v1 Sector=ALL，不阻断 |
| Plates | `get_owner_plate(code_list)` | 补充 Industry/Concept/Other plate | 接口失败时标记缺失 |
| Sector | M3C-A 不生成顶层 Sector | 保存原始 Industry/Plate evidence；`sector_mapping_version=null` | CORE v1 为 ALL，该级 PASS |
| Suspension | snapshot `suspension` | Active 判定 | true 不通过 Active |
| Security Status | snapshot `sec_status` | Active 判定 | 未知/异常为 UNKNOWN |
| Provider Time | `update_time` + OpenD server time | staleness 与 EOD 校验 | 不可解析则整批不完整 |

### 10.2 候选枚举规则

Discovery 不得先使用 CORE 数值条件过滤。应枚举 Futu 支持的美国现货证券类别，至少覆盖可能出现在目标交易所的：

```text
STOCK
ETF / TRUST
WARRANT / BWRT
其他由当前 SDK 返回的非期权、非期货现货类别
```

然后：

1. 按 `stock_id` 去重；
2. 保存原始 `code`、`stock_type`、`exchange_type`；
3. 相同 `stock_id` 对应多个当前代码时标记 symbol identity conflict；
4. 同一代码对应多个 `stock_id` 时整批失败；
5. options、futures、crypto 不进入 M3C-A discovery 范围。

这样 Funnel 的第一层是“本次成功枚举的美国现货证券”，不是预先过滤后的 CORE 名单。

### 10.3 正式快照时间

正式 Snapshot 只能在最新 XNYS 完整常规交易日结束后创建，并固定：

```text
as_of_session
observed_at_utc
provider_update_time
market_data_delay_class
```

盘中操作只能产生 `PREVIEW / PROVISIONAL`，不能发布正式 Snapshot。价格和市值必须来自同一采集窗口；不得把昨日价格与今日市值混合。

---

## 11. 20D Average Dollar Volume 权威口径

### 11.1 M3C-A 正式输入

CORE v1 冻结：

```text
liquidity_metric_id = FUTU_AVG_TURNOVER_20D
liquidity_evidence_version = futu-screening-liquidity/v1
```

M3C-A 使用 Futu Stock Screening V2：

```text
CumulativeProperty.AVG_TURNOVER
days = 20
currency = USD for US securities
```

该字段表示 N 日平均成交额，不是换手率，也不是成交量。

正式成员判定为：

```text
FUTU_AVG_TURNOVER_20D >= 20_000_000 USD
```

M3C-A 将这一 Futu Screening 值保存为正式 Universe 判定证据。不得在同一个 CORE v1 或同一个 evidence version 下，静默切换成本地日 K 复算值。若未来决定更换正式权威口径，必须发布新的 Universe Profile Version 和新的 Evidence Version；既有 Snapshot、Funnel 与 Scan Batch 不重写。

禁止以下替代：

```text
当前价格 × 20D 平均成交量
QFQ close × 未确认复权口径的 volume
单日 turnover
20D turnover ratio
```

### 11.2 M3C-B 独立交叉核验公式

当未来已有 canonical Futu daily bars 时，对最近 20 个完整常规交易日执行：

```text
ADV20 = arithmetic_mean(turnover_t for t in last_20_complete_sessions)
```

规则：

- 只含 regular session；
- `date <= as_of_session`；
- 恰好 20 个有效 session；
- turnover 必须为有限非负 USD；
- 空白 K、重复日、缺少所需 session、币种不明均不得计算；
- 结果使用 Decimal/整数 cents；
- 本地结果仅为交叉核验 evidence，不替代 CORE v1 的 `FUTU_AVG_TURNOVER_20D` 正式口径；
- cross-check tolerance 冻结为 `liquidity-cross-check-tolerance/v1`：服务端值与本地值先规范化为 USD cents，允许绝对差最多 `1 cent`，不使用相对误差或按证券调整的动态阈值；
- 绝对差大于 `1 cent` 时产生 `LIQUIDITY_EVIDENCE_CONFLICT`，该证券 UNKNOWN，正式 Snapshot 不能将其纳入成员；
- tolerance ID、规范化规则或阈值的任何变更都必须发布新的 Liquidity Evidence Version；若其改变成员判定，还必须发布新的 Universe Profile Version，不得改写既有 Snapshot。

M3C-A 不执行千股复算，只冻结公式、字段和冲突行为。

---

## 12. Listing History >= 250 Trading Days

### 12.1 M3C-A 正式证据

CORE v1 冻结：

```text
listing_history_metric_id = FUTU_LISTED_DAYS
listing_history_evidence_version = futu-screening-listing-history/v1
```

M3C-A 正式使用 Futu Stock Screening V2：

```text
SimpleProperty.LISTED_DAYS
```

正式成员判定为：

```text
FUTU_LISTED_DAYS >= 250
```

值必须为非负整数。Futu static `listing_date` 已停止维护，不得作为唯一正式依据，也不得替代 `LISTED_DAYS` 产生 PASS。

### 12.2 M3C-B 交叉核验

M3C-B 取得完整历史数据后，可使用可靠历史数据和交易日历计算辅助证据：

```text
listing_history_sessions = count(
  sessions where listing_date <= session <= as_of_session
)
```

该计算只用于交叉核验，不改变 CORE v1 的 `FUTU_LISTED_DAYS` 正式口径。M3C-A 不执行完整历史 hydration，也不以 OHLCV 行数或 static `listing_date` 替代 Screening 值。

### 12.3 证据冲突

如果 Screening `LISTED_DAYS`、未来完整历史数据或其他可靠来源发生冲突，统一记录：

```text
LISTING_HISTORY_CONFLICT
```

该证券进入 `UNKNOWN / Quarantine`，不得猜测或选择更有利的来源。正式判定规则为：

- `LISTED_DAYS` 为空、为负数或非整数：`UNKNOWN`；
- Screening `LISTED_DAYS` 与可靠交叉核验证据不一致：`LISTING_HISTORY_CONFLICT` → `UNKNOWN / Quarantine`；
- 证券身份冲突：`UNKNOWN / Quarantine`；
- `listing_date` 为空、1970 默认值或晚于 as-of 时只记录 `LISTING_DATE_AUXILIARY_INVALID`，不得单独改变有效 `FUTU_LISTED_DAYS` 的 PASS/FAIL；只有它与另一份可靠、明确且身份一致的来源构成实质冲突时，才按 `LISTING_HISTORY_CONFLICT` 处理。

Screening `LISTED_DAYS` 等于 250 时 PASS；249 时 FAIL。

---

## 13. ADR / ETF / Preferred / Warrant / Unit 的可靠区分

### 13.1 不能使用名称猜测

禁止用以下规则直接决定正式成员：

- ticker 是否含点、横线、`U`、`W`、`P`；
- 名称是否含 `ADR`、`Depositary`、`Preferred`、`Unit`；
- 市值或价格形态；
- LLM 推断。

名称模式只能生成审计提示，不能产生 PASS。

### 13.2 证据层级

每个证券保存 `SecurityClassificationEvidence`：

| 字段 | 说明 |
|---|---|
| `normalized_class` | COMMON_STOCK / ADR / ETF / PREFERRED / WARRANT / UNIT / OTHER / UNKNOWN |
| `provider` | FUTU_STATIC / APPROVED_SECURITY_MASTER / MANUAL_VERIFIED |
| `provider_value` | 原始类型值 |
| `observed_at_utc` | 证据时间 |
| `source_version` | SDK、文件或数据集版本 |
| `source_record_sha256` | 原始证据记录哈希 |
| `confidence` | AUTHORITATIVE / CORROBORATED / AMBIGUOUS |
| `notes` | 非判定性说明 |

正式分类规则：

1. Futu 明确返回 ETF/WARRANT/BWRT 等非 STOCK 类型时直接归类并排除；
2. Futu `STOCK` 只证明顶层 Equity，不单独证明 Common Stock；
3. ADR、Preferred、Unit、Common 必须有显式 subtype 证据；
4. 经批准的 security master 必须提供明确 issue type，不接受从名称推导；
5. 人工验证必须记录来源、原始记录哈希、验证时间和验证人，并以 append-only 新证据修正，不覆盖旧证据；
6. 多来源冲突为 `AMBIGUOUS`；
7. CORE v1 只有 `COMMON_STOCK + AUTHORITATIVE/CORROBORATED` 才 PASS；
8. 其余进入 `CLASSIFICATION_UNKNOWN` 或具体排除原因，始终显示在 Funnel 和 Quarantine。

`MANUAL_VERIFIED` 不是主观判断。它只表示人工把一份明确写出 issue subtype 的外部权威记录录入证据账本；必须附原始来源定位和记录 hash。没有可引用原始记录时仍为 UNKNOWN。

Implementation Plan 必须建立独立的 **Security Master / Classification Evidence** 接口边界。Universe evaluator 只能消费该接口返回的规范化分类结论和 evidence references，不得直接依赖某个外部供应商，也不得在 evaluator 内解析名称、ticker suffix 或正则。外部权威源的具体选择属于实施计划中的验证任务；本设计不把任何名称解析规则写死为权威来源。

### 13.3 当前限制

Futu 公开顶层 `SecurityType` 不足以独立区分 STOCK 内的 ADR、Preferred 和 Unit。因此：

- M3C-A 必须实现 classification evidence port 和 fail-closed 行为；
- 在权威 subtype provider 未选定或不可用时，不得声称全市场 CORE v1 完整；
- 这不会导致“静默错删”：所有未知证券保留在 Snapshot 和隔离清单；
- 不得为了提高数量而把 UNKNOWN 当 COMMON。

这是 live universe completeness 的 HIGH 风险，不是更改 CORE v1 规则的理由。

---

## 14. Sector / Industry

### 14.1 原始证据

保存：

- Stock Screening V2 `INDUSTRY`；
- `get_owner_plate` 的全部 plate code、name、type；
- 原始值、获取时间和 provider version。

### 14.2 CORE v1 evidence-only 冻结

Futu Industry/Plate 不等于经过验证的顶层 Sector。CORE v1 为 `Sector=ALL`、`Industry=ALL`，因此 M3C-A：

- 只保存 Futu 返回的原始 Industry/Plate evidence、来源版本、获取时间和记录 hash；
- 不生成 `normalized_sector`；
- 不建立未经验证的顶层 Sector 映射；
- Snapshot 的 `sector_mapping_version` 固定为 null；
- Industry/Plate 缺失不排除证券，但保留缺失状态供审计。

未来发布 Sector/Industry 非 ALL 的 Profile 前必须：

- 建立并冻结 `sector_mapping_version`；
- 展示未映射证券数量；
- 未映射证券 fail-closed；
- 新 mapping 版本不得改写旧 Snapshot。

---

## 15. Active Status

`active_only=true` 的 PASS 条件：

```text
delisting == false
AND suspension == false
AND sec_status in frozen_active_status_allowlist
AND provider record is not stale
AND symbol identity is consistent
```

规则：

- `delisting=true`：FAIL / `DELISTED`；
- `suspension=true`：FAIL / `SUSPENDED_AS_OF_SNAPSHOT`；
- 明确 inactive/expired/unknown-stock：FAIL；
- sec_status 新增未识别枚举：UNKNOWN，不自动视为 active；
- Futu 返回默认空记录或 unknown stock：UNKNOWN；
- 暂停证券不会被数据库删除，未来新 Snapshot 可重新进入。

Active 是每个 Snapshot 的 as-of 状态，不是永久证券属性。

---

## 16. Universe Funnel

### 16.1 固定 Stage 顺序

CORE v1 的展示顺序固定为：

```text
S0 DISCOVERED_US_CASH_SECURITIES
S1 IDENTITY_VALID
S2 EXCHANGE_ALLOWED
S3 SECURITY_CLASS_ALLOWED
S4 ACTIVE_STATUS_ALLOWED
S5 PRICE_ALLOWED
S6 MARKET_CAP_ALLOWED
S7 SECTOR_INDUSTRY_ALLOWED
S8 LISTING_HISTORY_ALLOWED
S9 LIQUIDITY_ALLOWED
S10 CORE_UNIVERSE
```

把 Liquidity 放最后，既便于解释，也允许先用廉价元数据缩小未来需要独立日线审计的集合。

### 16.2 每一级统计

每个 stage 保存：

| 字段 | 说明 |
|---|---|
| `stage_order` | 固定序号 |
| `stage_id` | 稳定机器 ID |
| `input_count` | 上一级 PASS 数 |
| `pass_count` | 本级 PASS 数 |
| `fail_count` | 本级明确不符合数 |
| `unknown_count` | 本级证据不足/冲突数 |
| `reason_counts` | 具体 reason → 数量 |
| `output_count` | 等于 pass_count |

必须满足：

```text
input_count = pass_count + fail_count + unknown_count
output_count = pass_count
next_stage.input_count = current_stage.output_count
S10.output_count = number_of_members
```

### 16.3 逐证券判定

每个候选保存所有可计算字段的独立判定，即使它在早期 stage 已 FAIL。顺序 Funnel 只决定“在哪一级首次离开”，独立判定用于审计和未来 Profile Preview。

判定记录至少包括：

```text
field_id
raw_value
normalized_value
threshold/operator
decision: PASS | FAIL | UNKNOWN | NOT_APPLICABLE
reason_code
evidence_source
evidence_observed_at_utc
```

不得只保存一句 `not eligible`。

---

## 17. Universe Snapshot

### 17.1 Snapshot Header

| 字段 | 说明 |
|---|---|
| `universe_snapshot_id` | 不可变 UUID/稳定 ID |
| `snapshot_schema_version` | `universe-snapshot/v1` |
| `snapshot_kind` | FORMAL / PREVIEW |
| `completeness` | COMPLETE / INCOMPLETE |
| `profile_version_id` | FORMAL 必填 |
| `profile_content_sha256` | 与 Registry 重算一致 |
| `draft_id` / `draft_content_sha256` | PREVIEW 使用 |
| `as_of_session` | XNYS session date |
| `created_at_utc` | 创建时间 |
| `provider` | FUTU |
| `provider_sdk_version` | SDK 版本 |
| `opend_server_version` | OpenD 版本 |
| `market_data_delay_class` | 实时/延迟/未知 |
| `sector_mapping_version` | CORE v1 为 null；未来启用 Sector 筛选时记录冻结映射版本 |
| `liquidity_metric_id` / `liquidity_evidence_version` | 正式流动性口径与证据版本 |
| `listing_history_metric_id` / `listing_history_evidence_version` | 正式上市历史口径与证据版本 |
| `classification_source_versions` | subtype 证据版本集合 |
| `candidate_count` | discovery 后数量 |
| `member_count` | 最终 PASS 数量 |
| `quarantine_count` | UNKNOWN 导致未通过数量 |
| `funnel_sha256` | Funnel 规范化哈希 |
| `members_sha256` | 排序后成员身份哈希 |
| `snapshot_sha256` | 规范化业务 Header + rows + funnel 的确定性内容哈希；排除运行时身份和时间噪声 |
| `snapshot_record_sha256` | 完整持久化记录哈希；覆盖 `snapshot_sha256`、运行 ID、创建时间和全部 provenance |

`snapshot_sha256` 的规范化业务 Header 明确排除 `universe_snapshot_id`、`created_at_utc`、本地路径、attempt ID 和写入时间，但保留 Profile/evidence/schema/version、as-of、provider 版本、完整性和所有影响成员资格的字段。相同 Profile、相同 Evidence、相同 as-of 和相同逐证券判定必须得到相同 `snapshot_sha256`；任一业务事实或 provenance version 改变都必须改变该 hash。`snapshot_record_sha256` 用于完整记录防篡改，不要求跨 attempt 相同。

### 17.2 每个候选证券保存的字段

```text
stock_id
futu_code
symbol
name
exchange_raw / exchange_normalized
security_type_raw / security_class_normalized
classification evidence
delisting / suspension / sec_status / active_status
price_usd / price_observed_at
market_cap_usd / market_cap_observed_at
liquidity_metric_id / liquidity_evidence_version
avg_turnover_20d_usd / liquidity_window_end
avg_volume_20d_shares
listing_history_metric_id / listing_history_evidence_version
listing_date / listed_days / listing_history_cross_check
raw industry / raw plates / sector_mapping_version
all field decisions
first_exit_stage
first_exit_reason
is_member
is_quarantined
raw evidence references/hashes
```

### 17.3 保存全部候选

Snapshot 必须保存：

- PASS 成员；
- 明确 FAIL；
- UNKNOWN / Quarantine；
- 原始候选数量和去重账本；
- API 批次和字段缺失记录。

只保存最终成员名单属于设计违规。

### 17.4 不可变性

FORMAL Snapshot append-only。相同 Profile、相同 as-of 重新运行也创建新 attempt；只有 COMPLETE、哈希验证通过且全部必要批次成功的 Snapshot 可标记 FORMAL。不得覆盖旧 Snapshot 文件或记录。

---

## 18. Scan Batch 绑定 universe_profile_version

未来 `ScanBatch` 必须包含：

```text
scan_batch_id
scan_as_of_session
universe_profile_version_id
universe_profile_content_sha256
universe_snapshot_id
universe_snapshot_sha256
universe_snapshot_record_sha256
universe_member_count
```

创建前验证：

1. Profile record_state 为 PUBLISHED；
2. Snapshot kind 为 FORMAL；
3. Snapshot completeness 为 COMPLETE；
4. Profile ID 和 hash 与 Snapshot 完全一致；
5. Scan as-of 不早于 Snapshot as-of，且 freshness policy 合格；
6. member count 与 members hash 可复算；
7. Preview、Draft、失败 attempt 均不可绑定。

Scan Batch 只读取 Snapshot 的冻结成员，不再次访问 Futu、不再次过滤 Universe、不把当前页面设置混入历史。

---

## 19. Preview Universe 不得改写历史

### 19.1 Preview 输入

Preview 可以使用：

- Draft；
- 已发布 Profile；
- 已有 Universe Evidence；
- 用户明确点击“刷新预览数据”后取得的新 Evidence。

### 19.2 Preview 输出

Preview 显示：

- draft hash；
- evidence as-of；
- COMPLETE / INCOMPLETE；
- Funnel；
- 成员预览；
- 被排除和未知样例；
- 与父版本相比的新增/移除数量和原因。

### 19.3 禁止行为

Preview 不得：

- 修改 Published Profile；
- 修改旧 Snapshot；
- 创建正式 Scan Batch；
- 写 Pattern Results 或 Review 记录；
- 修改 Flat Base Detector；
- 把临时条件保存为 CORE v1；
- 把 INCOMPLETE 结果显示为正式股票池。

Preview 如需持久化，只能写独立 append-only `PreviewRun`，并明确 `is_formal=false`。

---

## 20. Futu quota、限频和 API 失败

### 20.1 预检

每次采集前记录：

```text
OpenD login/READY state
server version
SDK version
US quote permission/delay class
historical K-line quota snapshot（只记录，本轮不做 bulk history）
requested interface batches
```

### 20.2 批处理

- Market Snapshot 每批不超过 400 个代码；
- Market Snapshot 遵守每 30 秒最多 60 次限制；
- Owner Plate 每批不超过 200 个证券，并遵守每 30 秒最多 10 次限制；
- Stock Screen V2 必须完整分页到 `last_page=true`；
- OpenD / SDK 必须支持本设计冻结的 Stock Screening V2 字段 ID；不支持时返回 `FUTU_SCHEMA_BLOCKER`，不得静默改用语义不同的旧字段；
- 每页保存页码/游标、请求字段、返回数量和响应哈希；
- 重试只针对可重试网络/限频错误，使用有上限的 backoff；
- 不可重试的权限、schema、身份冲突立即停止。

### 20.3 原子完成

任一必要批次失败时：

```text
attempt_status = FAILED
snapshot_kind != FORMAL
completeness = INCOMPLETE
```

允许保存失败 attempt manifest 和已取得的原始证据用于排障，但不得发布部分 Universe。

### 20.4 稳定错误码

至少定义：

```text
FUTU_LOGIN_BLOCKER
FUTU_MARKET_PERMISSION_BLOCKER
FUTU_RATE_LIMIT_RETRY_EXHAUSTED
FUTU_QUOTA_BLOCKER
FUTU_SCHEMA_BLOCKER
FUTU_PAGINATION_BLOCKER
UNIVERSE_IDENTITY_BLOCKER
UNIVERSE_INCOMPLETE_BLOCKER
CLASSIFICATION_EVIDENCE_BLOCKER
LIQUIDITY_EVIDENCE_CONFLICT
LISTING_HISTORY_CONFLICT
```

缺字段不得变成 0；旧缓存不得在未显示 staleness 的情况下静默顶替新数据。

---

## 21. 避免 Universe 设置进入 Flat Base Detector

### 21.1 依赖方向

允许：

```text
Universe Snapshot → Scan Orchestrator → OHLCV/Data Quality → Flat Base Detector
```

禁止：

```text
Flat Base Detector → UniverseProfile
Flat Base Detector → market_cap / sector / exchange / ADV20
Flat Base Detector → Streamlit session settings
```

### 21.2 Detector 输入冻结

`detect_flat_base()` 的业务输入继续只有：

- 单一证券的标准化 OHLCV；
- Detector 自己冻结的 `phase1-v1` 参数；
- 现有 Data Quality 前置条件。

Universe 只决定哪些 symbol 被调用，不决定 Detector 对某个 symbol 的 YES/NO。

### 21.3 自动防线

测试必须验证：

- `flat_base.py` 不导入 Universe modules；
- Flat Base dataclass/schema 没有 market cap、sector、exchange、Profile 字段；
- 同一 OHLCV 在不同 UniverseProfile 下 Detector 输出逐字段相同；
- M3B 冻结样例和现有缓存的 Detector 结果不变；
- UI 预览不会调用 Detector。

---

## 22. CORE v1 正确性测试

### 22.1 Profile contract

- CORE v1 所有冻结值逐字段精确测试；
- dataclass/value object frozen；
- 集合顺序不影响 hash；
- Decimal 规范化稳定；
- Published Version 无 update 路径；
- CORE v2 不修改 CORE v1 hash；
- 相同 `filter_content_sha256` 禁止伪造新版本；身份或说明字段变化不绕过该检查。

### 22.2 边界矩阵

至少构造：

| 场景 | 预期 |
|---|---|
| NYSE / NASDAQ / AMEX Common | Exchange PASS |
| OTC | Exchange FAIL |
| price 5.00 / 4.99 | PASS / FAIL |
| market cap 1B / 999,999,999.99 | PASS / FAIL |
| ADV20 20M / 19,999,999.99 | PASS / FAIL |
| listing 250 / 249 | PASS / FAIL |
| valid `LISTED_DAYS` + missing/invalid auxiliary `listing_date` | preserve LISTED_DAYS PASS/FAIL; record auxiliary warning only |
| LISTED_DAYS vs reliable cross-check conflict | `LISTING_HISTORY_CONFLICT` → UNKNOWN / Quarantine |
| ETF / ADR / Preferred / Warrant / Unit | FAIL |
| security subtype unknown | UNKNOWN / Quarantine |
| delisted / suspended | FAIL |
| Sector UNKNOWN with Sector=ALL | Stage PASS，同时保存 UNKNOWN metadata |
| 缺失 price/cap/ADV/listing | UNKNOWN，不得 PASS |

### 22.3 Funnel 对账

- 每一级满足 input = pass + fail + unknown；
- next input = prior pass；
- 最终 members 等于 S10 output；
- shuffled evidence 输入得到相同 members/hash；
- duplicate stock_id 不会双计；
- identity conflict 不能静默去重。

### 22.4 Snapshot 与 Preview

- Snapshot 保存 PASS、FAIL、UNKNOWN 全部记录；
- `snapshot_sha256` 对运行 ID、创建时间、路径等噪声稳定，对业务值或 provenance version 变化敏感；
- `snapshot_record_sha256` 覆盖完整持久化记录，不要求不同 attempt 相同；
- 失败 API 页不能产生 FORMAL Snapshot；
- Preview 不改变 Profile/Snapshot/Scan Store 的文件 hash 和行数；
- Draft 不可绑定 Scan Batch；
- Scan Batch profile/snapshot hash 不匹配时拒绝。

### 22.5 Futu adapter contract

- 分页完整性；
- snapshot 400-code chunking；
- 限频重试上限；
- ret != RET_OK 显式失败；
- 缺列和新枚举显式 schema blocker/unknown；
- currency、timestamp、listing day 和 avg turnover 类型规范化；
- provider field 不得用 0 填补 null；
- `liquidity-cross-check-tolerance/v1` 在 1 cent 边界内不冲突，大于 1 cent 产生 `LIQUIDITY_EVIDENCE_CONFLICT`；
- Owner Plate 的 200-code 分批和每 30 秒 10 次限额独立于 Market Snapshot 限额测试。

### 22.6 独立审计样本

实现验收时对一组预先冻结证券进行双向抽样：

- 最终 PASS；
- 每个 Funnel stage 的 FAIL；
- 每类 UNKNOWN；
- 恰好阈值和接近阈值；
- ADR/ETF/Preferred/Warrant/Unit；
- 三个交易所。

人工页面必须能从证券行一路打开原始字段、来源、阈值和 reason。不得只抽最终成员；未入选证券同样必须抽样。

---

## 23. 如何确认系统没有错删股票

系统不以“最终列表看起来合理”作为证据，而使用五层校验：

1. **Discovery 完整性**：Futu 分页到最后一页，保存各页数量和 hash；
2. **身份账本**：所有去重、symbol change 和 identity conflict 都有记录；
3. **Funnel 恒等式**：每一级数量严格对账；
4. **被排除记录可见**：FAIL 和 UNKNOWN 都在 Snapshot，可按原因导出；
5. **独立抽样**：同时抽 PASS、每级 FAIL、UNKNOWN 和阈值附近案例。

网页提供“为什么未进入”查询：输入 symbol 后显示首次退出 stage、实际值、阈值、证据来源、证据时间以及是否因未知而隔离。

“没有记录”本身是错误；不能被解释为不符合条件。

---

## 24. 用户网页设计

### 24.1 页面结构

M3C-A 只新增/扩展一个简单页面：

```text
股票池设置
```

不在本轮创建 Candidate Gallery、Review Queue 或 Pattern 页面功能。

### 24.2 页面区域

#### A. 当前正式版本

显示：

- `CORE v1`；
- 发布时间、说明、内容 hash；
- 当前全部冻结条件；
- 最近正式 Snapshot 的 as-of、member count、quarantine count。

#### B. 编辑草稿

用户选择：

```text
从 CORE v1 克隆
从其他 Published Version 克隆
创建 Custom Draft
```

可调整：

- Exchange；
- 最低/最高 Price；
- 最低/最高 Market Cap；
- 最低 20D Average Dollar Volume；
- 最低 20D Average Volume；
- 最低 Listing History；
- Sector；
- Industry；
- ETF / ADR / OTC / Preferred / Warrant / Unit 开关。

#### C. Preview

按钮：

```text
预览股票池
```

显示：

- Preview 数据时间和完整性；
- 逐级 Funnel；
- 预计成员数量；
- 与父版本相比新增/移除；
- UNKNOWN / Quarantine 数量；
- 可下载的成员、排除和未知列表；
- symbol 查询“为什么进入/为什么未进入”。

#### D. 发布新版本

只有 Preview COMPLETE 时才显示：

```text
保存为 CORE v2
保存为新的 Custom Profile v1
保存为 Custom Profile 下一版本
```

发布前必须再次显示完整 diff 和 change_note。按钮文案不得是“覆盖 CORE v1”。

### 24.3 失败体验

- Futu 未登录：告诉用户启动 OpenD 并登录；
- 权限不足：显示权限 blocker，不展示旧结果为新 Preview；
- Preview 不完整：保留已取得的诊断，但禁用发布；
- subtype UNKNOWN：显示隔离清单和证据缺口；
- API 限频：显示重试状态和最终稳定错误码；
- 用户离开页面：Draft 可保存，但不产生正式版本。

---

## 25. 建议实现边界（供后续 Implementation Plan 使用）

后续计划应优先沿现有 `src/tv_quant/pattern_finder/` 小模块结构扩展，不重构无关代码。建议职责边界：

```text
src/tv_quant/pattern_finder/universe/
  profiles.py          # Profile value objects, CORE v1, version rules
  evidence.py          # normalized Universe evidence and evidence versions
  security_master.py   # Security Master / Classification Evidence port
  classification.py    # subtype evidence resolution and fail-closed policy
  futu_gateway.py      # static/screen/snapshot/plate adapters
  evaluator.py         # pure field and membership decisions
  funnel.py            # reconciliation-only aggregation
  snapshots.py         # append-only snapshot schema/store
  preview.py           # non-formal preview orchestration
```

现有 `universe.py` 的 M3B 100-symbol list 是 M3B 验证 fixture/allowlist，不得被悄悄改名为 CORE v1，也不得删除。是否拆为 package 由后续 Implementation Plan 根据 import compatibility 决定。

UI 只修改/新增 Universe 设置入口；不得顺便调整 Flat Base、Today Scan 或 Chart Review 语义。

---

## 26. Acceptance Gate

M3C-A Design 进入实现计划前必须满足：

- [x] CORE v1 条件逐项冻结；
- [x] Published Profile 不可变；
- [x] CORE v2 / Custom 的创建流程明确；
- [x] Futu 字段、来源、as-of 和失败行为明确；
- [x] ADV20 权威字段与未来复算公式明确；
- [x] Listing >=250 sessions 口径明确；
- [x] 非普通股分类禁止名称猜测并采用 fail-closed；
- [x] Funnel 数量恒等式明确；
- [x] Snapshot 保存全部候选及来源；
- [x] Scan Batch 绑定 Profile Version + Snapshot + hashes；
- [x] Preview 不改写历史；
- [x] quota、限频、分页和失败原子性明确；
- [x] Universe 与 Detector 依赖方向冻结；
- [x] CORE v1 测试矩阵明确；
- [x] 用户网页最小操作流程明确；
- [x] 禁止项未进入设计交付范围。

实现 Gate 未来必须额外证明：

```text
CORE_V1_PROFILE_TEST = PASS
PROFILE_IMMUTABILITY_TEST = PASS
FUNNEL_RECONCILIATION_TEST = PASS
SNAPSHOT_TRACEABILITY_TEST = PASS
PREVIEW_NON_MUTATION_TEST = PASS
SCAN_BINDING_TEST = PASS
DETECTOR_REGRESSION_TEST = PASS
FUTU_ADAPTER_CONTRACT_TEST = PASS
```

---

## 27. BLOCKER / HIGH / 不确定项

### BLOCKER

**设计阶段 BLOCKER = 0。**

设计已定义所有关键字段、边界、失败语义和验收方法。

运行时出现以下情况必须阻止正式 Snapshot，而不是降级猜测：

- Futu discovery/page 不完整；
- Profile/Snapshot hash 不一致；
- 证券 identity conflict；
- 必要字段 schema 不兼容；
- 关键证据来源冲突；
- Snapshot 不是 COMPLETE。

### HIGH-1 — STOCK subtype 分类完整性

Futu 顶层 SecurityType 不能独立证明 `STOCK` 是 Common、ADR、Preferred 还是 Unit。设计已经用 evidence port、Quarantine 和 fail-closed 防止错误纳入，但 live 全市场完整性仍取决于后续选定并验证明确 subtype 的 security master。

### HIGH-2 — Futu 派生字段现场一致性

`AVG_TURNOVER(20)`、`LISTED_DAYS` 和 USD market cap 必须在实际 OpenD / US 数据上做小样本现场核验，确认单位、窗口和更新时间。未核验前可以完成纯规则与 fixture 测试，但不能宣布 live CORE v1 全市场验收 PASS。

### HIGH-3 — Sector taxonomy

Futu Industry/Plate 不天然等同于稳定顶层 Sector。CORE v1 为 ALL，不影响当前成员；未来启用 Sector/Industry 筛选前必须冻结映射版本和未映射处理。

### 非 BLOCKER 的已知限制

- M3C-A 不下载千股历史日线；
- M3C-A 不运行 Detector；
- M3C-A 不证明大规模性能；
- M3C-A 不解决历史退市成分股和 survivorship bias；
- 当前 Universe 是 current-universe foundation，不是 Historical T0 Universe。

---

## 28. Futu 官方资料依据

本设计冻结 Futu 字段语义时使用以下官方文档：

- Static Security Info：<https://openapi.futunn.com/futu-api-doc/en/quote/get-static-info.html>
- Market Snapshot：<https://openapi.futunn.com/futu-api-doc/en/quote/get-market-snapshot.html>
- Stock Screening V2：<https://openapi.futunn.com/futu-api-doc/en/quote/get-stock-screen.html>
- Historical Candlesticks：<https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html>
- Owner Plate：<https://openapi.futunn.com/futu-api-doc/en/quote/get-owner-plate.html>
- Quote Definitions：<https://openapi.futunn.com/futu-api-doc/en/quote/quote.html>
- Authorities and Quota：<https://openapi.futunn.com/futu-api-doc/en/intro/authority.html>

实现时必须记录实际 SDK/OpenD 版本并以 adapter contract test 复核这些字段；网页文档版本变化不能自动改变旧 Profile 或 Snapshot 语义。

---

## 29. 最终设计结论

M3C-A 采用：

> **Immutable Universe Profile Versions + Complete Evidence Snapshot + Reconciled Funnel + Fail-Closed Classification + Explicit Scan Binding**

CORE v1 不是一段可随时改动的页面设置，而是一个可哈希、可引用、不可覆盖的正式研究口径。

用户以后可以调整全部 Universe 条件，但正式调整必须发布新版本。Preview 只回答“如果这样设置会发生什么”，不会改写历史，也不会改变 Detector。

系统判断股票不进入 CORE 时，必须保留该股票及其证据，并回答：

```text
在哪一级离开
实际值是什么
阈值是什么
证据从哪里来
是明确不符合，还是证据不足
```

只有满足这些条件，才允许进入 M3C-A Implementation Plan。

```text
BLOCKER = 0
HIGH = 3
DESIGN_READY_FOR_FINAL_APPROVAL
```
