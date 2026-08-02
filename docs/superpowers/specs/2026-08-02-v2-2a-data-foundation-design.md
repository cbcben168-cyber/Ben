# Automated Quant Research System V2.2A Data Foundation Design

状态：FROZEN DESIGN

日期：2026-08-02

基线：`4ef02c7452d7935044ccbe084766a557613b5d58`

目标分支：`codex/v2-2a-data-foundation-design`

本文是 V2.2A 的权威书面设计。它只冻结美股与 ETF 日线 OHLCV 数据基础层的边界、合同和验收标准，不授权生产实现、网络下载、回测执行、报告发布或后续阶段能力。

## 1. Executive Summary

V2.2A 在 V2.1 已冻结的合同与门禁之上定义一条本地、批次、可审计的数据路径：本地 CSV 或 Parquet 经同一 typed import contract 进入不可变 raw 层，完成 schema、日历、时区、OHLCV、重复、冲突、复权、provenance、哈希与路径验证后，生成不可变 validated 证据和 canonical Parquet bundle。只有状态为 `VALID`、全部门禁通过且非 smoke 数据的 bundle 才可由 registry 提供给未来 V2.2B。

V2.2A 把三类身份明确分离，并把运行时能力与可持久化请求分离：

- `import_id` 标识一次独立导入尝试；重复导入同一文件也产生不同 `import_id`。
- `original_file_hash` 标识原始文件字节；CSV 与 Parquet 的字节哈希通常不同。
- `dataset_id` 标识 canonical 逻辑内容及其语义依赖；相同有效内容无论来自 CSV 或 Parquet，都产生相同 `dataset_id`。
- `DataImportRuntimeContext` 只在进程内携带绝对 data root；它不持久化、不进入 canonical hash，也不进入 dataset identity。

原始 OHLCV、复权因子和复权后 OHLCV 必须作为三个独立、可追溯、不可覆盖的 canonical 组件保存。任何猜测、静默修复、前后填充、插值、mtime 决策或“最新文件优先”都被禁止。

## 2. Goals

- 支持美股和 ETF 的日线 OHLCV 本地批次导入。
- 让本地 CSV 与本地 Parquet 共享一个 typed import、validation、identity 和 provenance 模型。
- 建立 `raw -> validated -> canonical parquet` 的不可变分层。
- 以 NYSE 日历和 `America/New_York` 交易日期为主语义，同时保存可追溯 UTC session 时间。
- 保存原始 OHLCV、复权因子、复权后 OHLCV，并证明完整 lineage。
- 对缺失、重复、冲突、数值、日历、时区、哈希、provenance 和路径问题 fail closed。
- 以确定性 logical serialization 生成 content hash 和 dataset identity。
- 为未来 V2.2B 提供只读、formal-eligibility-gated 的数据交接合同。
- 保持 Windows 与 Python 3.14 兼容，并继承 V2.1 的安全与 ownership 边界。

## 3. Non-Goals

V2.2A 不设计或实现：

- 分钟线、盘前盘后数据、实时行情或流式更新。
- 期权链、期权回测、Greeks 或波动率数据。
- Futu 自动下载、OpenD 协调、IBKR 数据或任何网络 provider 同步。
- 自动增量下载、定时更新或自动合并外部数据。
- VectorBT、正式回测、参数优化、Walk-forward、Monte Carlo 或正式报告。
- TradingView Webhook、账户、Broker routing、实盘或订单。
- V2.2B 回测执行层、V2.2C 报告层或任何 Phase 2 能力。
- 根据调整后价格反推公司行动、根据本机时区解释日期或自动修复数据。

## 4. Relationship to V2.1

V2.1 的行为、公共接口与验收结论保持冻结。V2.2A 只依赖 V2.1 已冻结的 19 个入口接口，不重新解释或替换它们，尤其包括 `DataPlan`、`DatasetRequirement`、`CapabilityRegistry`、`DependencyFingerprint`、`ArtifactContract`、`StatusCodeRegistry` 和 confirmation gate。

V2.2A 必须复用下列既有 owner：

| Concern | Frozen V2.1 owner | V2.2A rule |
|---|---|---|
| Canonical payload hash | `tv_quant.run_manifest.canonical_hash` | 所有合同和 logical content hash 经该原语生成 |
| File/bytes SHA-256 | `tv_quant.run_manifest.sha256_file` / `sha256_bytes` | 原始文件和持久化 artifact 不建立第二套哈希实现 |
| Artifact hash binding | `tv_quant.run_manifest.bind_artifact_hashes` | canonical bundle 与 manifest 绑定沿用现有 owner |
| Canonical numbers | `tv_quant.contracts.numeric.canonical_decimal` / `canonical_integer` | 禁止另建 decimal normalizer |
| Path containment | `tv_quant.contracts.path_safety.resolve_under_root` | V2.2A 只加强调用门禁，不建立平行路径系统 |
| Artifact ownership | `ArtifactContract` / `ARTIFACT_OWNERS` | 新数据 artifact 通过版本化扩展登记，不建立第二份 ledger |
| Status and blocker metadata | `StatusCodeRegistry` | 数据域状态映射到既有 typed pipeline status/blocker 语义 |
| Audit/provenance/report ownership | Phase 1 owners recorded by `ArtifactContract` | V2.2A 不建立第二个 audit、provenance 或 report writer |

`DataEligibility` 中的 `VALID`、`BLOCKED`、`INCOMPLETE`、`SMOKE_ONLY`、`INVALIDATED` 和 `NOT_IMPLEMENTED` 是 dataset lifecycle 值，不是第二套 pipeline status registry。所有操作结果仍通过 V2.1 `PipelineStatus` 与 `BlockerCode` 返回。

## 5. Supported Market/Data Scope

首版唯一正式范围是：

- 资产类别：美国上市股票与 ETF。
- 频率：`1d`。
- 会话：NYSE 基准交易日的 regular session；不含盘前盘后。
- 字段：open、high、low、close、volume，以及独立的复权因子和 adjusted OHLCV。
- 正式入口：本地 CSV、本地 Parquet。
- 非正式入口标签：`YFINANCE_SMOKE`；只允许导入已物化的本地 smoke 文件，不允许 V2.2A 发起网络请求。

symbol 只是证券描述的一部分。canonical listing identity 同时记录稳定 `instrument_id`、规范化 `symbol`、规范化 `exchange` 和 ticker 生效区间；每日稳定键至少包含 `(symbol, exchange, trading_date)`，并以 `instrument_id` 防止 ticker 变更断开 lineage。

## 6. Architecture Overview

架构由六个责任边界组成：

1. Import Boundary：分别接收可持久化 `DataImportRequest` 与进程内 `DataImportRuntimeContext`，执行路径安全检查，登记原始文件字节和独立 import identity。
2. Parsing and Normalization：把 CSV/Parquet 映射为同一 canonical scalar、列和稳定键语义。
3. Calendar and Validation Authority：基于冻结 NYSE 日历快照验证交易日、半日市、时区、排序、缺口、OHLCV、重复与冲突。
4. Adjustment Authority：保存并验证 `CorporateActionEvent`、`CorporateActionEvidence`、复权因子和 adjusted OHLCV，不覆盖 raw values。
5. Identity and Artifact Boundary：使用既有哈希与 artifact owners 生成 logical content hash、dataset identity、Parquet artifacts 和 immutable manifests。
6. MarketDataRegistry：以单向 binding 关联 immutable manifest、引用该 manifest hash 的 eligibility、多个 provenance associations 和 invalidation events；不拥有文件、哈希、manifest serialization、审计或 provenance。

## 7. Data Flow

```text
DataImportRequest + DataImportRuntimeContext
  -> resolve injected root and source path; reject every escape
  -> assign unique import_id and hash exact source bytes
  -> preserve source bytes under raw/
  -> parse CSV or Parquet through one logical row contract
  -> normalize symbols, MIC, dates, canonical decimals and integers
  -> bind TradingCalendarRef and America/New_York semantics
  -> validate schema, calendar, timezone, OHLCV, gaps, duplicates,
     conflicts, adjustments, provenance, hashes and ownership
  -> persist immutable validated candidate and DataValidationReport
       BLOCKED/INCOMPLETE -> append quarantine record; no eligible dataset
        VALID             -> canonicalize deterministic logical bundle
  -> derive dataset_id without physical Parquet parameters
  -> query registry by dataset_id
       exact existing identity/components/dependencies
         -> reuse immutable canonical artifacts and manifest revision
         -> append the new import/provenance association
       same dataset_id but any identity-bearing mismatch
         -> fail closed as collision/conflict; publish nothing
       no existing dataset_id
         -> atomically publish immutable Parquet components + manifest
  -> create DataEligibility that references the manifest hash
  -> registry binds manifest + eligibility + qualifying provenance
  -> V2.2B may read only a hash-verified VALID record
```

失败不会删除 raw 或 validated 证据。`quarantine/` 保存 failure manifest、report 和对原始 artifact 的引用；它不移动、覆盖或提升任何 artifact，也永远不具有 formal eligibility。

## 8. Contract Model

### 8.1 Shared contract rules

- 所有持久化 payload 都有明确 `schema_version`，字段未知或版本不支持时阻断。
- 所有值对象默认 immutable；状态变化通过新记录或 append-only event 表达。
- 所有 hash 字段使用小写 64 位 SHA-256 hex。
- 价格使用 `canonical_decimal` 的非指数十进制字符串；volume 使用 `canonical_integer` 或明确的 canonical non-negative decimal string。binary float、boolean、NaN、Infinity 和 negative-zero 歧义不得进入正式合同。
- operation contract 可以编排既有 owners，但不能成为新的 hash、manifest、artifact、audit、provenance 或 decimal owner。
- “formal eligible” 只属于 MarketDataRegistry 中完整且 hash-consistent 的 `manifest + eligibility + qualifying provenance` binding；`DataEligibility` 单向引用 manifest hash，manifest 不引用 eligibility。任何单独 row、factor、report、provenance、manifest 或 identity 都不能自行授予资格。

### 8.2 Value and record contracts

#### MarketDataSourceType

| Property | Frozen design |
|---|---|
| Purpose | 标识来源能力和资格，不隐含 provider 可用性 |
| Required values | `LOCAL_CSV`, `LOCAL_PARQUET`, `YFINANCE_SMOKE` |
| Invariants | 前两者可进入正式验证；`YFINANCE_SMOKE` 强制 `SMOKE_ONLY`；不允许未知值或自动降级 |
| Owner | Data Foundation Import Boundary |
| Hash ownership | 枚举值作为 canonical payload 字段，由 `canonical_hash` 处理 |
| Error semantics | 未知来源映射 `DATA_CAPABILITY_BLOCKER` |
| Immutable / persistable / formal eligible | immutable；可持久化；本身不授予资格 |

#### DailyBarRaw

| Property | Frozen design |
|---|---|
| Purpose | 保存 canonical、未复权的每日 OHLCV，不覆盖源值 |
| Required fields | `instrument_id`, `symbol`, `exchange`, `trading_date`, `session_open_utc`, `session_close_utc`, `timezone`, `currency`, `open`, `high`, `low`, `close`, `volume`, `volume_status`, `source_row_ref` |
| Invariants | 稳定键唯一；symbol/exchange 大写规范；日期为 NY trading date；UTC session 来自同一 calendar snapshot；OHLC finite 且 `>0`；volume 非 boolean 且 `>=0`；raw values 不含调整 |
| Owner | Parsing and Normalization boundary；源字节仍由 ArtifactContract owner 管理 |
| Hash ownership | canonical row serialization 经 `canonical_hash`；物理文件经 `sha256_file` |
| Error semantics | schema/数值/时序/OHLC 问题映射 `DATA_VALIDATION_BLOCKER` |
| Immutable / persistable / formal eligible | immutable；可持久化；单独不具资格 |

`volume` 默认必填。只有 `volume_status=MISSING_MARKET_EXPLAINED` 且具有允许的结构化市场原因时，validated candidate 才能保留空值；该 dataset 默认是 `INCOMPLETE`，未来 consumer 未显式注册支持前不得 formal eligible。空 volume 永不转换为 `0`。

#### DailyBarAdjusted

| Property | Frozen design |
|---|---|
| Purpose | 保存由 raw bar 和审计通过的 factor 确定性生成的 adjusted OHLCV |
| Required fields | DailyBarRaw 的 identity/time fields，`adjustment_factor_id`, `adjustment_method`, `adjusted_open`, `adjusted_high`, `adjusted_low`, `adjusted_close`, `adjusted_volume` |
| Invariants | stable key 与 raw bar 一一对应；公式、舍入和 factor version 固定；不能反推或覆盖 raw；adjusted OHLC 仍满足全部质量约束 |
| Owner | Adjustment Authority |
| Hash ownership | canonical logical rows 经 `canonical_hash`；artifact 经 `sha256_file` |
| Error semantics | 缺失 factor、lineage 或结果不一致映射 `CORPORATE_ACTION_DATA_BLOCKER` |
| Immutable / persistable / formal eligible | immutable；可持久化；仅作为完整 bundle 组件具资格 |

#### AdjustmentFactor

| Property | Frozen design |
|---|---|
| Purpose | 显式记录 raw 到 adjusted 的可审计变换 |
| Required fields | `adjustment_factor_id`, stable listing identity, `effective_trading_date`, `price_factor`, `volume_factor`, `adjustment_method`, `corporate_action_semantic_coverage_hash`, lineage `corporate_action_evidence_id/hash`, ordered `corporate_action_event_ids`, `factor_version` |
| Invariants | factors finite、canonical、`>0`；method 注册且公式固定；事件顺序确定；event IDs 必须来自所引 evidence；identity-bearing factor payload 使用 source-independent semantic coverage hash/event IDs，lineage evidence ID/hash 不进入 dataset identity；identity factor 必须引用 `NO_ACTIONS_IN_RANGE` evidence；禁止从 adjusted close 反推 |
| Owner | Adjustment Authority |
| Hash ownership | factor payload 使用 `canonical_hash`；公司行动输入文件使用 `sha256_file` |
| Error semantics | 缺事件、范围、方法或 hash 映射 `CORPORATE_ACTION_DATA_BLOCKER` |
| Immutable / persistable / formal eligible | immutable；可持久化；单独不具资格 |

#### CorporateActionEvent

| Property | Frozen design |
|---|---|
| Purpose | 以 typed、可哈希事件表达影响复权的单个公司行动 |
| Required fields | `event_schema_version`, `event_id`, `instrument_id`, `symbol`, `exchange`, `event_type`, `ex_date`, `effective_trading_date`, type-specific split ratio or cash amount/currency |
| Invariants | `event_type` 首版只允许 `SPLIT` 或 `CASH_DIVIDEND`；split ratio finite 且 `>0`；cash amount finite 且 `>=0` 并有 currency；日期与绑定 calendar 一致；event payload 完全 source-independent，`event_id` 由排除自身的 semantic payload 生成；同一 event 可被多个 evidence records 证明，source event refs 只属于 evidence lineage |
| Owner | Adjustment Authority |
| Hash ownership | event payload 使用既有 `canonical_hash`，数值使用既有 canonical decimal owner |
| Error semantics | 类型字段不完整、日期无效、重复 event ID 内容冲突或 hash 不一致映射 `CORPORATE_ACTION_DATA_BLOCKER` |
| Immutable / persistable / formal eligible | immutable；必须持久化；单独不具资格 |

#### CorporateActionEvidence

| Property | Frozen design |
|---|---|
| Purpose | 证明一个 listing 与日期范围内“存在事件”或“确定无事件”的完整覆盖结论 |
| Required fields | `evidence_schema_version`, `evidence_id`, `evidence_hash`, `semantic_coverage_hash`, `coverage_state`, `instrument_id`, `symbol`, `exchange`, `coverage_start`, `coverage_end`, `source_type`, `source_name`, `original_file_name`, `original_file_hash`, `calendar_id/hash`, ordered `event_ids`, source event refs, `events_hash`, `validation_status`, blocker codes |
| Invariants | `coverage_state` 只允许 `EVENTS_PRESENT` 或 `NO_ACTIONS_IN_RANGE`；前者要求至少一个已验证 event、每个 source event ref 映射到一个 event ID 且全部 event 在 coverage 内；后者要求 event_ids/source event refs 均为空，并有来源明确声明的完整覆盖，不能由缺文件、空响应或未下载推断；evidence coverage 必须覆盖 canonical source range；`semantic_coverage_hash` 只覆盖 listing、range、state、calendar 和 ordered semantic event IDs，排除 provider/source/import lineage；`evidence_id/hash` 覆盖完整 lineage payload |
| Owner | Adjustment Authority；source bytes 仍由 ArtifactContract owner 管理 |
| Hash ownership | evidence/events logical payload 使用 `canonical_hash`；原始 evidence artifact 使用 `sha256_file` |
| Error semantics | coverage 缺口、state 与 events 不一致、来源或 hash 不完整映射 `CORPORATE_ACTION_DATA_BLOCKER` |
| Immutable / persistable / formal eligible | immutable；必须持久化；是 adjustment eligibility 的必要证据但不单独授予资格 |

#### TradingCalendarRef

| Property | Frozen design |
|---|---|
| Purpose | 冻结交易日、session 和半日市的权威语义 |
| Required fields | `calendar_id=NYSE`, `calendar_source`, `calendar_version`, `calendar_hash`, `timezone=America/New_York`, `coverage_start`, `coverage_end`, `sessions` with open/close UTC and `is_half_day` |
| Invariants | snapshot 覆盖完整 source/canonical range；不能仅按周一至周五推断；同一 dataset 只绑定一个 snapshot |
| Owner | Calendar and Validation Authority |
| Hash ownership | snapshot logical payload 由 `canonical_hash`；snapshot artifact 由 `sha256_file` |
| Error semantics | 日历未知、不覆盖或 hash 不匹配映射 `DATA_CAPABILITY_BLOCKER` 或 `DATA_VALIDATION_BLOCKER` |
| Immutable / persistable / formal eligible | immutable；必须持久化引用；单独不具资格 |

#### DataImportRequest

| Property | Frozen design |
|---|---|
| Purpose | 一个本地批次导入的可持久化、可哈希 typed request |
| Required fields | `request_schema_version`, `source_type`, contained `source_relative_path`, `source_name`, `instrument_id`, `symbol`, `exchange`, `currency`, column mapping/schema profile, `TradingCalendarRef`, declared timezone, corporate-action evidence relative refs, adjustment method, `smoke_only` |
| Invariants | 只含 root-relative logical inputs；不得包含 absolute root、runtime handle、下载 URL、账户或凭据；source type 与 smoke flag 一致；request 不产生 dataset identity |
| Owner | Data Foundation Import Boundary |
| Hash ownership | request payload 由 `canonical_hash`；不包含 plaintext secret |
| Error semantics | 格式或路径错误映射 `CONFIG_VALIDATION_BLOCKER`；不支持的能力映射 `DATA_CAPABILITY_BLOCKER` |
| Immutable / persistable / formal eligible | immutable；可作为审计输入持久化；不具资格 |

#### DataImportRuntimeContext

| Property | Frozen design |
|---|---|
| Purpose | 在一次 import call 内提供可信本地 filesystem capability，与可持久化 request 隔离 |
| Required fields | existing absolute `data_root`, `path_safety_policy_version`, process-local runtime handle/clock as required by the caller |
| Invariants | 仅由可信本地调用方构造；生命周期不超过一次 operation；absolute data root 不进入 request、manifest、provenance、registry、日志、canonical serialization 或任何 hash；所有 request relative refs 都必须通过该 root 解析并重复验证 containment |
| Owner | Data Foundation Import Boundary runtime adapter |
| Hash ownership | 无；本合同明确禁止 canonical hash 和 file serialization |
| Error semantics | root 不存在、非目录、policy 不支持或 containment 不可证明映射 `CONFIG_VALIDATION_BLOCKER` |
| Immutable / persistable / formal eligible | operation 内 immutable；禁止持久化；不具资格 |

#### DataImportManifest

| Property | Frozen design |
|---|---|
| Purpose | 记录一次独立导入尝试和所有阶段结果 |
| Required fields | `import_id`, `request_hash`, `source_type`, `source_name`, `original_file_name`, `original_file_hash`, `import_timestamp_utc`, raw artifact ref/hash, parser/schema versions, stage statuses, validation report ref/hash, candidate/final dataset ID if any, blocker codes |
| Invariants | 每次调用新建 import identity；原始字节先登记后解析；完成后不可修改；失败也必须保存；import timestamp/file hash 不进入 dataset identity；manifest 只记录 request hash 和 contained relative refs，不记录 RuntimeContext 或 absolute root |
| Owner | Import Boundary 编排；manifest serialization/hash 仍归 V2.1 owner |
| Hash ownership | `canonical_hash`, `sha256_file`, `bind_artifact_hashes` |
| Error semantics | 任一失败以 typed stage status 和 blocker 返回；warning 不能替代成功 |
| Immutable / persistable / formal eligible | finalized record immutable；必须持久化；不具资格 |

#### DatasetIdentity

| Property | Frozen design |
|---|---|
| Purpose | 稳定标识一个 canonical daily bundle |
| Required fields | `identity_schema_version`, `dataset_id`, `dataset_kind`, `content_hash`, sorted `semantic_dependency_hashes` |
| Invariants | `dataset_id = canonical_hash(identity payload excluding dataset_id)`；payload 不含路径、mtime、import order、import_id、timestamp、source format、original file hash、Parquet writer profile、compression、row-group 或任何物理序列化参数；不同 logical content 必须改变 content hash |
| Owner | V2.1 hash owner；Data Foundation 只定义 payload |
| Hash ownership | `tv_quant.run_manifest.canonical_hash` 独占 |
| Error semantics | hash 缺失、不规范或重算不一致映射 `DATA_VALIDATION_BLOCKER` |
| Immutable / persistable / formal eligible | immutable；必须持久化；身份本身不授予资格 |

`semantic_dependency_hashes` 只包含会改变逻辑数据语义的冻结依赖，例如 logical schema、calendar snapshot、timezone policy、corporate-action semantic coverage/event set、adjustment method/factors 和 canonical scalar/row ordering rules。完整 CorporateActionEvidence、Parquet writer/library profile、compression、compression level、row-group size、dictionary/statistics policy、metadata order 和其他来源/物理参数只进入 lineage、`CanonicalDatasetManifest` 与 artifact file hash，不进入 content hash、semantic dependency hashes 或 `dataset_id`。`original_file_hash`、import manifest、provenance 和 validation report 也属于 lineage hashes。因此 CSV/Parquet 输入、不同 provider evidence 和不同物理 Parquet packaging 可在逻辑内容相同时共享同一 `dataset_id`。

#### DatasetProvenance

| Property | Frozen design |
|---|---|
| Purpose | 完整证明 dataset 的来源、转换、依赖和父子关系 |
| Required fields | `provenance_id`, `provenance_hash`, `provider_id`, `provider_capability_id/version`, `source_type`, `source_name`, `original_file_name`, `original_file_hash`, `import_timestamp_utc`, `schema_version`, `calendar_id`, `calendar_version`, `timezone`, `adjustment_status`, `adjustment_method`, `source_date_range`, `canonical_date_range`, `row_count`, `validation_status`, `blocker_codes`, optional `parent_dataset_id`, `dataset_id`, `content_hash`, `dependency_hashes` |
| Invariants | 每次 import 产生独立 immutable provenance，即使复用既有 dataset；所有引用 hash 可重算；range/row count 与 artifacts 一致；同一 dataset 可有多个 provenance records 和 provider claims；新增 provenance 只能由 registry 追加 association，不得改写 dataset、manifest 或既有 eligibility |
| Owner | 既有 Phase 1 provenance owner，通过版本化扩展承载 V2.2A 字段 |
| Hash ownership | provenance payload 使用 `canonical_hash`；依赖 artifacts 使用现有 file/bytes hash owners |
| Error semantics | 缺字段、断链或 hash 不一致映射 `DATA_VALIDATION_BLOCKER` |
| Immutable / persistable / formal eligible | immutable；必须持久化；完整 provenance 是资格必要条件但不单独授予资格 |

#### DataValidationIssue

| Property | Frozen design |
|---|---|
| Purpose | 以结构化、可排序的形式表达单个数据问题 |
| Required fields | `issue_code`, `category`, `severity`, `blocking`, optional stable key/field/source row, `observed`, `expected`, optional `gap_reason_code`, `mapped_blocker_code` |
| Invariants | code 来自冻结 issue registry；禁止仅用自由文本日志；issue 排序键固定；敏感本机绝对路径不得进入 payload |
| Owner | Calendar and Validation Authority |
| Hash ownership | 作为 report payload 由 `canonical_hash` 处理 |
| Error semantics | 每个 blocking issue 必须映射现有 typed blocker；warning 不得让失败变成功 |
| Immutable / persistable / formal eligible | immutable；可持久化；不具资格 |

#### DataValidationReport

| Property | Frozen design |
|---|---|
| Purpose | 汇总一个 candidate 的全部确定性验证结果 |
| Required fields | `report_schema_version`, `report_id`, `report_hash`, `import_id`, candidate content hash, validator versions, calendar/timezone refs, ordered issues, per-check status, counts, `validation_status`, blocker codes |
| Invariants | issue order、counts 和 overall status 可重算；任何 blocking issue 导致 fail closed；report 不修复数据 |
| Owner | Calendar and Validation Authority |
| Hash ownership | report logical payload 由 `canonical_hash`；artifact 由 `sha256_file` |
| Error semantics | 自身不完整或 hash 不一致也构成 `DATA_VALIDATION_BLOCKER` |
| Immutable / persistable / formal eligible | immutable；必须持久化；通过报告是资格必要条件但不单独授予资格 |

#### DataEligibility

| Property | Frozen design |
|---|---|
| Purpose | 对 dataset lifecycle 与 future formal use 作唯一结论 |
| Required fields | `eligibility_id`, `eligibility_hash`, `dataset_id`, `manifest_hash`, sorted `qualifying_provenance_hashes`, `state`, `formal_eligible`, check matrix, blocker codes, optional invalidation event ref/reason |
| Invariants | eligibility 单向引用已完整验证的 manifest hash；manifest 不得引用 eligibility；qualifying provenance 必须在 registry association 中存在且完整；`formal_eligible=true` 时 qualifying provenance hashes 非空且全部非 smoke；states 至少为 `VALID`, `BLOCKED`, `INCOMPLETE`, `SMOKE_ONLY`, `INVALIDATED`, `NOT_IMPLEMENTED`；只有 `VALID` 可令 `formal_eligible=true`；值必须由检查矩阵推导，不接受调用方直接覆盖 |
| Owner | Eligibility Gate，操作状态仍映射 V2.1 StatusCodeRegistry |
| Hash ownership | eligibility payload 使用 `canonical_hash` |
| Error semantics | 状态/布尔不一致映射 `DATA_VALIDATION_BLOCKER` |
| Immutable / persistable / formal eligible | 每次评估或失效事件产生新 immutable record；必须持久化；本合同决定资格 |

#### CanonicalDatasetManifest

| Property | Frozen design |
|---|---|
| Purpose | 绑定 canonical bundle 的身份、组件、creation lineage、质量与物理 serialization；不拥有资格结论 |
| Required fields | `manifest_schema_version`, monotonic `manifest_revision`, `DatasetIdentity`, schema/calendar/timezone refs, stable-key definition, source/canonical ranges, row/gap counts, refs and hashes for raw OHLCV、corporate-action evidence/events、adjustment factors、adjusted OHLCV, creation provenance ref/hash, validation report ref/hash, physical artifact hashes, Parquet writer/library profile、compression、row-group and metadata policy, parent dataset ID if applicable |
| Invariants | manifest 不得包含 eligibility ref/hash/state；三个 canonical 组件与 corporate-action evidence 完整且互相对账；所有 refs contained；logical hash、file hash 和 dataset ID 可重算；manifest 不把文件名当身份；已发布 manifest 不可修改 |
| Owner | `ArtifactContract` 的版本化 data-manifest extension；不是新 manifest owner |
| Hash ownership | `canonical_hash`, `sha256_file`, `bind_artifact_hashes` |
| Error semantics | 任一断链、缺失或不一致映射 `DATA_VALIDATION_BLOCKER` 或 `CORPORATE_ACTION_DATA_BLOCKER` |
| Immutable / persistable / formal eligible | immutable；必须持久化；manifest 自身不具资格，只能由 registry 绑定一个引用其 hash 的 VALID DataEligibility |

`manifest_revision` 的语义冻结如下：

- revision 作用域是同一 `dataset_id`，首个发布值为 `1`，只能单调增加且每个 revision immutable。
- 普通重复导入不得增加 revision；完全一致时复用现有 canonical artifacts 与现有 manifest revision，只追加 import/provenance association。
- 只有单独批准的物理 repackaging 或不改变 identity-bearing content 的 manifest metadata 修订才能创建更高 revision；logical component hashes、content hash、semantic dependency hashes 和 dataset ID 必须保持完全一致。
- 更高 revision 可以改变 writer/library profile、compression、row-group、metadata policy、artifact paths 或 artifact file hashes；这些变化仍不得进入 dataset ID。
- registry 保留所有 revisions；active revision 由显式 registry event 选择，不依据 mtime、导入时间或 provider preference。旧 revision 不删除、不覆盖。

#### MarketDataRegistry

| Property | Frozen design |
|---|---|
| Purpose | 按 dataset identity 绑定 immutable manifest、引用该 manifest hash 的 eligibility、多个 provenance associations 和 invalidation events |
| Required records | registry schema/version, dataset ID, manifest revision/ref/hash, eligibility ref/hash, qualifying provenance refs/hashes with provider IDs/capability versions, semantic query fields, registration/active-revision event, optional invalidation event |
| Invariants | 每个 binding 必须满足 `eligibility.dataset_id == manifest.dataset_id`、`eligibility.manifest_hash == registered manifest hash`，且 eligibility 的 qualifying provenance hashes 是 registry associations 的子集；manifest 无反向 eligibility 引用；append-only records；atomic snapshot/index publish；lookup 不依赖 mtime/path/import order；registry 不写数据、不生成 manifest/hash、不修改 eligibility |
| Owner | MarketDataRegistry only for index and invalidation ledger |
| Hash ownership | registry snapshot 使用既有 `canonical_hash`；registry file 使用 `sha256_file` |
| Error semantics | duplicate identical registration 可幂等；binding、revision、provenance 或 hash 冲突阻断；损坏 snapshot fail closed |
| Immutable / persistable / formal eligible | service interface；records/snapshots immutable 且持久化；registry 本身不授予资格 |

### 8.3 Operation contracts

#### import_local_dataset

- Purpose：唯一的 V2.2A 本地批次编排入口。
- Required input/output：分别接收 `DataImportRequest` 与 `DataImportRuntimeContext`；返回 finalized `DataImportManifest`、`DataValidationReport`、可选 `CanonicalDatasetManifest`、`DataEligibility` 和 registry binding/ref。
- Invariants：绝对 root 只从 RuntimeContext 读取且不持久化/hash；只接受 contained local file；先保存/hash raw，再解析；不得访问网络；同一 request 的不同调用产生不同 import ID 和 provenance；同一有效逻辑内容产生同一 dataset ID，并遵守幂等复用门禁。
- Ownership：只编排 import、validation、canonicalization、artifact owner 和 registry；不吸收任何下游 owner 职责。
- Hash ownership：全部委托 V2.1 hash owners。
- Error semantics：返回 typed status/blocker；失败仍保存审计证据；不自动重试、猜测、修复或降级。
- Immutable/persistence/eligibility：operation 本身不持久化为 mutable state；输出记录 immutable；不直接授予资格。

#### validate_daily_dataset

- Purpose：对 normalized candidate 执行纯确定性的日线验证。
- Required input/output：candidate rows、schema profile、`TradingCalendarRef`、`CorporateActionEvent`/`CorporateActionEvidence`、adjustment inputs、provenance candidate；返回 `DataValidationReport`。
- Invariants：无网络、无文件选择、无修复；检查顺序和 issue order 固定；同一输入及依赖得到相同 report logical hash。
- Ownership：Calendar and Validation Authority。
- Hash ownership：report hash 委托 `canonical_hash`。
- Error semantics：blocking issue 映射 typed blocker；异常不能包装为 warning。
- Immutable/persistence/eligibility：纯 operation；输出 immutable、可持久化；不单独授予资格。

#### canonicalize_daily_dataset

- Purpose：把 validation 通过的 logical rows 生成 canonical daily bundle。
- Required input/output：VALID report、raw rows、corporate-action events/evidence、factor rows、adjusted rows、calendar/timezone/logical schema dependencies，以及单独的 physical writer configuration；返回 `DatasetIdentity` 和 `CanonicalDatasetManifest` candidate。
- Invariants：拒绝 BLOCKED/INCOMPLETE/SMOKE_ONLY candidate 的 formal publish；logical column order、row order 和 numeric representation 决定 content hash/dataset ID；writer profile、compression、row group 和 metadata 只决定 manifest fields 与 artifact file hash；不覆盖旧 artifact。
- Ownership：Data Foundation Canonicalization Boundary；artifact publication 仍由 ArtifactContract owner 完成。
- Hash ownership：logical/identity hash 与 file hashes 全部委托现有 owners。
- Error semantics：重建不一致、collision 或 dependency mismatch 映射 `DATA_VALIDATION_BLOCKER`。
- Immutable/persistence/eligibility：operation 不可持久化；输出 bundle immutable；资格仅由 registry 中 hash-consistent 的 manifest/eligibility/provenance binding 决定。

#### find_latest_eligible_dataset

- Purpose：为冻结的 `DatasetRequirement` 查找唯一、完整覆盖且 formal eligible 的 dataset。
- Required input/output：requirement、registry snapshot hash、ordered provider preference/capability snapshot；返回一个 exact registry binding，其中包含 dataset ID、manifest revision/ref/hash、eligibility ref/hash 和 selected provenance ref/hash，或 typed blocker。
- Invariants：先验证 manifest/eligibility/provenance 单向 binding，再按 exact instrument/symbol/exchange/timeframe/session/timezone/adjustment 和 date coverage 过滤；只保留 `VALID` 且 hashes 完整的 bindings；provider preference 匹配 provenance 的 provider capability，不改变 dataset ID、manifest 或 eligibility；选择规则见下方冻结语义；mtime、文件名和导入顺序不参与。
- Ownership：MarketDataRegistry query boundary；不改变 registry 或 dataset。
- Hash ownership：验证现有 hashes，不创建新 owner。
- Error semantics：无候选返回 `DATA_CAPABILITY_BLOCKER`；同一最高语义优先级出现内容冲突返回 `DATA_VALIDATION_BLOCKER`，不得任选其一。
- Immutable/persistence/eligibility：只读 operation；不持久化、不授予新资格。

#### invalidate_dataset

- Purpose：在不删除或改写历史 artifact 的前提下撤销 future eligibility。
- Required input/output：dataset ID、expected manifest hash、结构化 reason code、actor/ref、event timestamp UTC；返回 immutable invalidation event 和新的 registry snapshot ref/hash。
- Invariants：compare-and-append；重复相同事件幂等；不同原因并存保留；原 manifest、raw、validated、canonical 和 provenance 全部只读保留。
- Ownership：MarketDataRegistry invalidation ledger only。
- Hash ownership：event/snapshot 由现有 canonical/file hash owners 处理。
- Error semantics：未知 dataset、hash mismatch、非法 reason 或 registry conflict fail closed。
- Immutable/persistence/eligibility：event 必须持久化且 immutable；一旦有效，最新 eligibility 为 `INVALIDATED`、formal false。

### 8.4 Idempotent re-import, provenance, and provider preference

同一 `dataset_id` 的重复导入按以下顺序 fail closed：

1. 重算并比较 identity schema、dataset kind、bundle/component logical hashes、sorted semantic dependency hashes、calendar/timezone、corporate-action semantic coverage/event set、adjustment factors 和 stable-key ranges；完整 evidence/provenance hashes 只用于 lineage binding 比较，不作为 dataset identity。
2. 如果以上 identity-bearing values 全部一致，继续验证 registry active manifest、manifest hash、physical artifact hashes 和 eligibility binding。
3. 如果现有 binding 完整有效，复用现有 canonical artifacts、dataset ID 和 manifest revision；本次仍生成新的 import ID、DataImportManifest 与 DatasetProvenance，并把 provenance association append 到 registry。不得重写 canonical files、manifest 或既有 eligibility。
4. 如果同一 dataset ID 的任一 identity-bearing value 不一致，视为 hash collision 或 registry corruption：产生 blocking conflict、保留本次 raw/validated/quarantine evidence，不注册、不复用、不覆盖。
5. 如果 identity-bearing values 一致但现有 manifest/artifact/binding 已损坏或 invalidated，不得自动重建或覆盖；返回 typed blocker，等待单独批准的 recovery、repackaging 或新 revision 流程。

多 provenance 的语义冻结如下：

- 每次 import 都有独立 provenance；多个 provenance records 可以指向同一 dataset ID 和同一 manifest hash。
- canonical manifest 只保留 creation provenance；后续 provenance 只由 registry associations 追加，不能触发 manifest revision。
- 一个 DataEligibility 记录 manifest hash 和使该次评估成立的 sorted qualifying provenance hashes；新 provenance 不会改写旧 eligibility。需要以新 provenance 获得资格时，创建新的 immutable eligibility record，并由 registry 建立新 binding。
- provider preference 是 `DatasetRequirement.provider_preference` 中的非空、ordered capability IDs；它选择 registry binding 的 qualifying/selected provenance，不是 dataset 属性，也不进入 dataset identity。
- 查询先选择 preference 中第一个存在 VALID binding 的 provider rank。相同 dataset ID 的多个同 rank provenances 可确定性合并为同一候选；不同 dataset IDs 在相同 stable keys/range 上内容冲突时必须阻断，不能以 revision、时间或 lexical order 选胜者。
- 在无内容冲突的候选之间，依次按完整 coverage、canonical range end、active manifest revision 和 dataset ID 做确定性排序。manifest revision 只比较同一 dataset ID 的物理 revisions，不能让某 provider 获得更高语义优先级。

## 9. Stable Identity and Hash Ownership

### 9.1 Stable row key

canonical row key 是 `(instrument_id, symbol, exchange, trading_date)`，其中最低外部可见稳定键仍包含 `(symbol, exchange, trading_date)`：

- `instrument_id` 是内部稳定 listing identity，不从文件名推断。
- `symbol` 转为注册的 uppercase canonical form；source spelling 保留在 provenance。
- `exchange` 使用冻结的 uppercase MIC；未知或含糊交易所阻断。
- `trading_date` 是 NYSE/`America/New_York` 交易日期，不是本机日期。
- ticker 变更以同一 instrument_id 下的 immutable symbol-effective-range records 表达；历史 bar 保留当日有效 symbol，不回写新 ticker。

### 9.2 Hash layers

| Hash | Covers | Explicitly excludes |
|---|---|---|
| `original_file_hash` | 原始输入的精确字节 | 解析结果、路径、mtime |
| component logical content hash | 固定 schema、columns、canonical scalars、stable-key row order | Parquet metadata、import ID、timestamp |
| bundle `content_hash` | raw OHLCV、corporate-action semantic coverage/event set、factor、adjusted OHLCV 和 gap component hashes | full lineage evidence、source format、物理路径和 physical packaging |
| semantic dependency hashes | logical schema、calendar、timezone、corporate-action/adjustment semantics、canonical scalar/row rules | writer/library profile、compression、row-group、import timestamp、original file hash、provenance record order |
| `dataset_id` | bundle content hash + sorted semantic dependencies + identity schema | path、mtime、filename、import order、source type 和全部物理序列化参数 |
| physical serialization profile hash | writer/library、compression、row-group、dictionary/statistics、metadata policy | dataset identity 和 logical equivalence |
| artifact file hash | 实际 CSV/Parquet/JSON bytes | logical equivalence claims |
| lineage hashes | request、import manifest、provenance、validation report、original file | dataset identity |

任何 physical hash 或 logical hash 不一致都阻断；不能用一个 hash 替代另一层的责任。

## 10. File and Registry Layout

逻辑布局如下，本文不创建这些目录：

```text
<injected-data-root>/
  raw/
    <import_id>/
      <preserved-original-file>
  validated/
    <import_id>/
      normalized-candidate.parquet
      validation-report.json
  canonical/
    <dataset_id>/
      <manifest_revision>/
        daily-bar-raw.parquet
        corporate-action-events.parquet
        corporate-action-evidence.json
        adjustment-factors.parquet
        daily-bar-adjusted.parquet
        canonical-dataset-manifest.json
  manifests/
    imports/
    provenance/
    registry/
  quarantine/
    <import_id>/
      failure-manifest.json
```

- 实际 root 只通过 `DataImportRuntimeContext` 注入且已存在；禁止写入 `DataImportRequest`、持久化 artifact 或 canonical hash，也禁止硬编码用户路径。
- 所有相对路径先经 V2.1 containment contract，再在发布前重新解析。
- raw、validated、canonical 全部 immutable；创建使用独占新目录和同 root 内 atomic publish，禁止覆盖。
- quarantine 只保存失败证据和引用，不具 formal eligibility。
- 文件名和目录名只用于定位，不是 dataset identity 来源。
- registry 只保存 contained relative refs 与 hashes，不保存不受控绝对路径。

## 11. CSV/Parquet Import Rules

CSV 与 Parquet 只在 parser adapter 不同；parser 输出必须进入同一 logical row contract：

- CSV encoding、delimiter、header、column mapping 和 date format 必须由 versioned profile 明确；首版日期只接受严格 ISO `YYYY-MM-DD` 交易日期字段。
- 禁止 locale-dependent decimal、逗号千位分隔歧义、布尔 volume、scientific special values 和隐式空字符串转换。
- Parquet 必须验证 Arrow logical types、column nullability、timezone metadata 和 schema fingerprint；不能仅凭扩展名信任格式。
- 未知列默认阻断，除非 versioned profile 明确声明为 ignored 且该声明进入 request hash。
- CSV/Parquet 的 column order、row order 和物理类型差异，经合法规范化后不得改变 logical content hash。
- 原始文件永远原样保留；parser 不得原地重写。
- `YFINANCE_SMOKE` 的本地物化文件沿同一验证路径处理，但 eligibility 强制 `SMOKE_ONLY`，不能升级。

## 12. Trading Calendar and Timezone Semantics

- primary date 是 `America/New_York` 的 exchange trading date。
- 每个 daily bar 同时保存从冻结 calendar snapshot 得到的 `session_open_utc` 和 `session_close_utc`；canonical `bar_timestamp_utc` 等于 session close UTC。
- 半日市使用实际早收盘 UTC，并设置 `is_half_day=true`；不能用常规 16:00 close 替代。
- DST 转换由 calendar snapshot 决定；不得使用本机 timezone 或固定 UTC offset。
- holidays/weekends 不属于 expected trading dates；expected session 上缺 bar 才进入 gap validation。
- calendar source/version/hash、coverage 和 timezone policy 都进入 semantic dependencies。
- 无法确定 calendar、timezone、DST 或 session mapping 时 fail closed。

## 13. Corporate Actions and Adjustment Model

canonical dataset 的价格数据是三组件 bundle，并由独立公司行动合同提供输入证据：

1. `daily-bar-raw.parquet`：canonical unadjusted OHLCV。
2. `adjustment-factors.parquet`：按 effective date 排序的 explicit factors 与公司行动 lineage。
3. `daily-bar-adjusted.parquet`：由前两者和冻结公式确定性生成。

`corporate-action-events.parquet` 与 `corporate-action-evidence.json` 分别保存 typed events 和覆盖结论。`EVENTS_PRESENT` 必须绑定范围内完整事件集合；`NO_ACTIONS_IN_RANGE` 必须绑定来源明确声明的无事件覆盖，不能由空文件、缺下载或零 events 自动推断。

规则：

- 原始价格永不覆盖，复权后价格永不冒充 raw。
- events、evidence 与 factors 必须有本地输入、source hash、coverage 和 method version；`EVENTS_PRESENT` 中每个 factor 引用的 event 必须存在于 evidence 的 ordered event set。
- 没有行动的区间也必须由 `NO_ACTIONS_IN_RANGE` evidence 支持 identity factor；不能用“未提供 actions”假装没有行动。
- 复权公式和 decimal rounding 属于 adjustment method version，并进入 semantic dependencies。
- split 对 price/volume factors 的方向必须由 method 固定；cash dividend 只有在本地事件、ex-date 和方法完整时才可使用。
- 仅有 adjusted OHLCV、adjusted close 或 provider 黑盒复权结果但缺少 events/evidence/factors 时，状态为 `BLOCKED`。
- raw、evidence/events、factors、adjusted 的 stable keys、ranges 和 row counts 必须可对账；差异必须有结构化 gap reason。

## 14. Data Quality Rules

下列检查默认 blocking：

- 预期交易日缺失且无允许的 gap reason。
- stable key 重复、乱序或同键内容冲突。
- OHLC 为空、非有限、`<=0` 或不满足：`high >= open`、`high >= close`、`high >= low`、`low <= open`、`low <= close`、`low <= high`。
- volume 为负、boolean、NaN、Infinity，或无批准原因的空值。
- date 不属于 calendar、半日市/session UTC 不一致、timezone/DST 不可确定。
- schema/calendar/adjustment/provenance/hash 版本缺失或不支持。
- source、validated 或 canonical artifact hash 不可重算。
- path containment、immutable ownership 或 atomic publish 证据不足。

验证不做自动纠错。发现问题后保留 observed value、expected rule、stable key、source row ref、issue code 和 mapped blocker。

## 15. Missing Data and Gap Reason Codes

允许的 gap reason 是冻结的结构化集合：

| Reason | Meaning | Default dataset effect |
|---|---|---|
| `PRE_IPO` | instrument 尚未上市，且 listing metadata 可验证 | 合法 coverage exclusion |
| `POST_DELISTING` | 已退市，且 delisting metadata 可验证 | 合法 coverage exclusion |
| `HALT` | 交易所或权威输入明确停牌 | 合法 gap，证据必须绑定 |
| `EXCHANGE_NO_TRADING` | calendar/session 明确当日无该证券交易 | 合法 gap，证据必须绑定 |
| `SOURCE_MISSING` | provider/source 明确缺失 | `BLOCKED` |
| `SOURCE_INCOMPLETE` | source 明确不完整但范围可描述 | `INCOMPLETE` |

禁止静默前填、后填、插值、用前收盘补 OHLC、把空 volume 转为零，或删除 gap 而不记录。原因码与 listing/calendar/source evidence 不一致时仍然阻断。

## 16. Duplicate and Conflict Handling

- 同一 stable key 且 canonical row 内容完全一致：允许确定性去重；保留所有 source row refs、duplicate count、row hash 和 `DEDUPLICATED_IDENTICAL` 处理结果。
- 同一 stable key 但任一 canonical 字段不同：产生 blocking `CONFLICTING_STABLE_KEY` issue，candidate 进入 quarantine，不生成 eligible canonical bundle。
- duplicate 判断使用 canonical values；原始文本差异但语义相同可去重，原始文本仍由 raw/provenance 保留。
- 禁止按 mtime、文件顺序、路径、导入顺序或“最新”自动选胜者。

## 17. Provenance and Auditability

每个 import、validated candidate 和 canonical bundle 都必须能沿 immutable refs 回溯到：

```text
MarketDataRegistry binding
  -> dataset_id + manifest revision/ref/hash
       -> canonical component logical/file hashes
       -> validation report
       -> corporate-action evidence/events + adjustment factors
       -> calendar/timezone/logical-schema dependencies
       -> creation provenance
  -> eligibility ref/hash
       -> the same manifest hash
       -> qualifying provenance hashes
  -> selected/additional provenance associations
       -> import manifest
       -> original file name and exact file hash
```

同一 dataset ID 可以由不同 CSV/Parquet imports 和不同 providers 证明；registry 追加 provenance association，不重写 canonical artifacts、manifest 或既有 eligibility。每个 eligibility 只对其引用的 exact manifest hash 与 qualifying provenances 作结论。所有审计时间使用 UTC；时间戳是 audit metadata，不进入 dataset identity。

## 18. Formal Eligibility

`formal_eligible=true` 当且仅当：

- state 为 `VALID`。
- eligibility 的 `manifest_hash` 精确匹配 registry binding 的 immutable manifest，manifest 中不存在任何 eligibility 反向引用。
- schema、calendar、timezone、OHLCV、duplicate/conflict、corporate-action evidence/events、adjustment、qualifying provenance、hash、path containment 和 immutable ownership 检查全部通过。
- 三个 canonical price components、corporate-action artifacts 与 manifest 完整且 logical/physical hashes 可重算。
- selected qualifying provenance 的 source type 不是 `YFINANCE_SMOKE`，smoke flag 为 false。
- 没有 unresolved blocker、incomplete marker 或 invalidation event。
- manifest、eligibility、qualifying provenance 和 registry snapshot hashes 完整，且 registry binding 全部相等关系成立。

以下状态永远不能进入 V2.2B formal path：`BLOCKED`、`INCOMPLETE`、`SMOKE_ONLY`、`INVALIDATED`、`NOT_IMPLEMENTED`。任何调用方都不能直接设置 formal boolean；它只能由 Eligibility Gate 从检查矩阵推导。

## 19. Error and Blocker Model

V2.2A 复用 V2.1 typed status/blocker owner，不建立平行错误系统：

| Condition | Pipeline mapping |
|---|---|
| request、schema mapping 或 path input 非法 | `CONFIG_VALIDATION_BLOCKER` |
| source/calendar/timezone/provider capability 不可用 | `DATA_CAPABILITY_BLOCKER` |
| OHLCV、duplicate/conflict、gap、hash、provenance 或 registry 不合格 | `DATA_VALIDATION_BLOCKER` |
| company action、factor 或 adjusted lineage 不完整 | `CORPORATE_ACTION_DATA_BLOCKER` |
| 同一 dataset ID 内容不一致、manifest/eligibility 反向或错向引用、registry binding 不一致 | `DATA_VALIDATION_BLOCKER` |
| 数据能力尚未实现 | dataset state `NOT_IMPLEMENTED` + typed capability blocker |

每个返回必须包含 status、blocker code、recoverable/retryable/terminal semantics、user action、stage、issue refs 和已产生的 immutable evidence refs。不得自动猜测、自动修复、静默降级、把 warning 当 success，或只写日志文本。

## 20. Security and Path Safety

- absolute data root 只由可信调用方注入 `DataImportRuntimeContext`；request 只携带 root-contained relative path；RuntimeContext 与 absolute root 禁止持久化、canonical hash 或写入日志。
- 在读取、raw publish、canonical publish 和 registry commit 前分别验证 containment，降低检查后替换风险。
- 拒绝 `..`、absolute、drive-relative、UNC、NTFS ADS、DOS device、NUL、symlink/junction/reparse escape 和大小写规范化后的 root escape。
- Windows reparse target 必须解析后仍在 root 内；无法验证时 fail closed。
- staging directory 必须位于同一 injected root；atomic rename 不跨 volume。
- existing target、hash mismatch 或 partial directory 不能覆盖；转入 quarantine evidence。
- 不扫描磁盘、不读取 `.env`、不记录 API key/密码/账户资料、不连接网络或 broker。

## 21. Determinism Requirements

- logical columns、null representation、canonical scalars 和 stable-key row order 固定。
- manifest/report/registry JSON 使用 UTF-8、sorted keys、fixed separators 和 existing `canonical_hash` semantics。
- canonical Parquet writer profile 固定 Arrow/Parquet physical schema mapping、timezone encoding、compression、compression level、row-group size、dictionary/statistics policy 和 metadata order；profile 与参数写入 manifest 并由 artifact file hash 证明，明确排除于 semantic dependencies、content hash 和 dataset ID。
- 同一 logical content 与相同 semantic dependencies 必须产生同一 component hashes、bundle content hash 和 dataset ID。
- 不同 logical content 必须改变 content hash；检测到实际 collision 时 fail closed，不发布任一候选。
- import ID、timestamps、source format、path、mtime 和 import order 不进入 dataset identity。
- physical Parquet file hash 与 logical content hash 分开验证；两者都必须保存。
- 所有排序都有显式 tie-break；不得依赖 dict iteration、filesystem enumeration 或 locale。

## 22. Test Strategy

未来实现必须以离线 fixtures 覆盖：

### Import and equivalence

- CSV 正常导入、Parquet 正常导入、CSV/Parquet canonical equivalence。
- 相同输入产生相同 dataset identity，不同输入不碰撞。
- 原始文件 hash、dataset logical hash、Parquet physical hash 分层验证。
- 改变 writer/library profile、compression、row-group 或 metadata policy 时 dataset ID 不变，manifest/artifact hash 改变。
- `DataImportRequest` canonical hash 不含 absolute root；`DataImportRuntimeContext` 不可 serialization、持久化或 hash。

### Calendar and time

- 日期乱序、缺失交易日、非交易日 row、NYSE holiday、半日市。
- timezone 错误、America/New_York 与 UTC 追溯、DST 两侧 session UTC。

### Quality, gaps and conflicts

- 重复日期、identical dedupe、conflicting duplicate。
- 全部 OHLC 逻辑错误、非正价格、负 volume、空 volume、NaN、Infinity、boolean volume、negative zero。
- 每个允许 gap reason 的合法与伪造证据；禁止 fill/interpolation。

### Corporate actions

- `CorporateActionEvent` split/cash-dividend 类型字段、日期、canonical hash 和 duplicate conflict。
- `CorporateActionEvidence` 的 `EVENTS_PRESENT` 完整 event set、`NO_ACTIONS_IN_RANGE` 明确覆盖，以及空文件/缺下载伪证据拒绝。
- factor 公式、identity factor、raw/event/evidence/factor/adjusted 隔离、lineage 和 component 对账。
- adjusted-only 或缺 event/evidence/action hash 时阻断。

### Immutability, provenance and eligibility

- raw、validated、canonical 不被覆盖。
- provenance 完整/缺失、parent linkage、多个 imports/providers 对同一 dataset ID。
- 同一 dataset ID 完全一致重复导入复用 canonical artifacts/manifest revision 并追加 provenance；identity-bearing mismatch、损坏 binding 和 invalidated target 全部 fail closed。
- 普通重复导入不增加 manifest revision；批准的 physical repackaging 增加 revision 但不改变 dataset ID；旧 revisions 保留。
- manifest 无 eligibility 引用；eligibility 引用 exact manifest hash；registry 验证并绑定 manifest、eligibility 与 qualifying provenances。
- ordered provider preference 选择 provenance binding，不进入 dataset identity；同 rank 内容冲突阻断。
- `VALID` 唯一 formal-eligible；smoke-only、blocked、incomplete、invalidated、not-implemented 全部拒绝。
- invalidation append-only、重复幂等和 hash mismatch conflict。

### Security and determinism

- path traversal、symlink、junction、reparse escape。
- Windows drive、UNC、ADS、DOS device、NUL 和 case-normalization escape。
- deterministic serialization、fixed Parquet profile、row/column order independence。
- fail-closed on unsupported schema/calendar/writer/hash/registry versions。

### Regression

- V2.1 frozen public interface tests、完整 Phase 1/V2.1 suite、Python 3.14、Windows path behavior。
- 静态确认没有网络下载、Futu/OpenD、IBKR、VectorBT、broker、account、order 或 formal backtest path。
- duplicate-owner scan 确认没有第二套 hash、manifest、artifact、audit、provenance 或 decimal owner。

## 23. Acceptance Criteria

V2.2A 后续实现只有同时满足以下条件才算完成：

- 本地 CSV/Parquet 通过同一 typed import contract。
- 相同有效逻辑内容产生相同 canonical dataset identity；不同内容产生不同 identity。
- dataset ID 排除 writer/library profile、compression、row-group 和其他物理序列化参数；这些参数只改变 manifest revision/fields 与 artifact hash。
- `DataImportRequest` 与非持久化 `DataImportRuntimeContext` 分离，absolute data root 不进入 canonical hash 或任何持久化 payload。
- 原始输入保持不变，raw、validated、canonical 均不覆盖。
- canonical Parquet 在冻结 writer profile 下可确定性重建。
- NYSE 日历、半日市、America/New_York 交易日期和 UTC session 可验证、可追溯。
- OHLCV 质量规则 fail closed；合法 gap 具有结构化原因和证据。
- identical duplicate 可审计去重；conflict 不自动覆盖。
- raw OHLCV、CorporateActionEvent/Evidence、adjustment factors、adjusted OHLCV 分离并完整对账；`EVENTS_PRESENT` 与 `NO_ACTIONS_IN_RANGE` 均有可验证覆盖证据。
- 相同 dataset ID 的完全一致重复导入幂等复用；任何 identity-bearing 不一致 fail closed。
- manifest/eligibility 单向引用正确，registry binding 完整；manifest revision、provider preference 与多 provenance 语义符合冻结规则。
- provenance、file hashes、logical hashes、dependency hashes 和 registry refs 完整。
- yfinance 数据只能是 `SMOKE_ONLY`。
- 不执行网络下载、正式回测或 formal result/report 发布。
- V2.1 的完整测试保持通过；Windows 与 Python 3.14 兼容。
- 路径安全不退化；无第二套 ownership。

## 24. Migration and Rollback

- V2.1 数据、合同、缓存和 artifacts 不原地迁移或改写。
- 既有 Phase 1 CSV 只能经显式 `DataImportRequest` 作为新 import candidate；不能因文件存在而自动获得 V2.2A 资格。
- logical schema、calendar、timezone、corporate-action/adjustment semantics 变化必须产生新的 semantic dependencies 和 dataset ID；不能伪装为 manifest revision。
- 仅 physical writer/library profile、compression、row-group、metadata policy 或非 identity-bearing manifest metadata 变化，可经单独批准创建同一 dataset ID 的更高 immutable manifest revision；旧 revisions 保留可读，不原地升级。
- registry upgrade 使用新 snapshot + atomic pointer publication；失败继续使用前一已验证 snapshot。
- rollback 不删除数据：停止新注册，恢复前一 registry snapshot，并通过 `invalidate_dataset` 撤销错误版本的 future eligibility。
- 已生成的 raw、validated、canonical、manifests 和 audit evidence 始终保留，除非未来另有单独批准的 retention policy。

## 25. Explicit Deferred Scope

以下能力明确延期：Futu/OpenD provider、network refresh、automatic merge、intraday、pre/post-market、real-time、IBKR、options、VectorBT、backtest execution、optimization、Walk-forward、Monte Carlo、report publication、template publication、TradingView、broker、account 和 orders。

## 26. V2.2B Handoff Contract

V2.2B 只能通过 `find_latest_eligible_dataset` 或 exact dataset ID 读取 V2.2A，交接 payload 至少包含：

- exact registry binding：dataset ID、active manifest revision/ref/hash、eligibility ref/hash、selected qualifying provenance ref/hash/provider capability rank、registry snapshot hash。
- raw/event/evidence/factor/adjusted component refs、logical hashes 和 physical hashes。
- stable identity、symbol/exchange、date range、calendar/timezone/session semantics。
- adjustment method、CorporateActionEvent/Evidence dependencies、provenance/report/eligibility refs and hashes。
- schema、canonical writer、dependency versions。

V2.2B 必须在执行前重新验证 registry binding、`eligibility.manifest_hash`、qualifying provenance/provider preference、manifest revision、registry snapshot 和全部 component hashes，并把 dataset/dependency hashes 绑定进 V2.1 `DataPlan`、confirmation 和 run manifest。V2.2B 不得：

- 读取 quarantine、smoke-only、blocked、incomplete、invalidated 或 not-implemented datasets。
- 修改、修复、复权、合并或重新解释 V2.2A 数据。
- 用文件路径、mtime 或 provider label 替代 dataset identity。
- 绕过 V2.1 confirmation、artifact、status、audit、next-bar、成本或 Buy and Hold 边界。

本交接合同不启动 V2.2B，也不授权回测。

## 27. Open Questions

没有阻断性开放问题。V2.2A 所需决策已在本文冻结；未来出现的新阻断问题必须通过用户批准的版本化设计修订处理，不能在实现中自行猜测。
