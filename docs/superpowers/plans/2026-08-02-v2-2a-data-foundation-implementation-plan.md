# V2.2A Data Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现已冻结的美股/ETF 日线 OHLCV 本地数据基础层。

**Architecture:** 用 immutable raw/validated/canonical 分层、typed contracts、
deterministic logical identity、manifest/eligibility/registry binding 和
fail-closed validation 实现 V2.2A。V2.2A 通过现有 V2.1 hash、artifact、
status、numeric、path 和 provenance owners 编排本地 CSV/Parquet 导入，
不建立平行 owner。

**Tech Stack:** Python 3.14.2、pytest 9.1.1、`dataclass(frozen=True,
slots=True)`、`enum.Enum`、`pathlib.Path`、`zoneinfo.ZoneInfo`、pandas
3.0.3、PyArrow/Parquet 25.0.0、tzdata 2026.3，以及
`exchange-calendars==4.13.2` 的 XNYS 日历。`exchange-calendars` 是唯一新增
依赖，用于离线生成和复核 NYSE session/holiday/half-day/DST 快照；生产导入
只消费已物化、已哈希的本地快照，不在导入期间访问网络。

## Global Constraints

- 本地 CSV/Parquet only。
- 美股/ETF 日线 only。
- no network；实现与测试不得下载行情、启动 provider 或隐式刷新日历。
- no formal backtest；不得调用回测、优化、报告发布或模板发布入口。
- immutable artifacts；raw、validated、canonical、manifest、eligibility、
  provenance、registry snapshot 和 invalidation event 均不可覆盖。
- fail closed；未知 schema、calendar、timezone、hash、path、identity、
  lineage、writer profile 或 registry 状态必须阻断。
- Windows compatible；拒绝 drive-relative、UNC、ADS、DOS device、NUL、
  symlink/junction/reparse escape 和 case-normalized root escape。
- Python 3.14 compatible；所有验收命令使用 `py -3.14`。
- reuse V2.1 owners；哈希、artifact、status、numeric、path、audit、
  provenance 和 report owner 均从现有模块扩展。
- no second hash/manifest/artifact/audit/provenance/decimal owner。
- absolute data root 仅存在于非持久化 `DataImportRuntimeContext`，不得进入
  request、日志、manifest、provenance、registry 或任何 canonical hash。
- `DataEligibility` 状态仅为 `VALID`、`SMOKE_ONLY`、`INVALIDATED`；
  `BLOCKED`、`INCOMPLETE`、`NOT_IMPLEMENTED` 只属于 operation/import/report。
- `YFINANCE_SMOKE` 只接受本地物化文件，只能产生 `SMOKE_ONLY`，永远不能
  被 formal query 选中。
- V2.1 的 19 个冻结公共接口、next-bar、成本、Buy and Hold、确认门禁和
  517-test baseline 不得退化。

---

## 1. Existing Owner and Dependency Map

| Concern | Existing owner | V2.2A integration rule |
|---|---|---|
| Canonical payload hash | `tv_quant.run_manifest.canonical_hash(value: Mapping[str, Any]) -> str` | 所有 logical、identity、manifest、eligibility、registry payload 委托该函数 |
| Bytes/file SHA-256 | `sha256_bytes(payload: bytes) -> str` / `sha256_file(path: Path) -> str` | 不导入 `hashlib` 到 data-foundation modules |
| Artifact hash binding | `bind_artifact_hashes(manifest, artifact_paths)` | 以 backward-compatible `hashed_names` 参数扩展数据组件绑定 |
| Canonical numbers | `canonical_decimal(value, path) -> str` / `canonical_integer(value, path) -> int` | 所有价格、因子和 volume 通过现有 owner |
| Path containment | `resolve_under_root(root, relative_path) -> Path` | 在 source read、raw publish、canonical publish、registry commit 前重复调用 |
| Artifact ownership | `ArtifactContract` / `ARTIFACT_OWNERS` | 追加 versioned data artifact entries；旧 entries 和接口不变 |
| Typed status | `PipelineStatus` / `BlockerCode` / `StatusCodeRegistry` | 复用已有四个 data/config blocker，不创建平行状态 enum |
| Capability registry | `CapabilityRegistry` + `config/capability-registry-v2.1.json` | 追加 `v2.2a` capability records；V2.1 records 不改义 |
| Provenance writer | `tv_quant.research_pipeline.write_data_provenance` | 增加 typed payload mode；旧 `(data_path, source)` 调用保持兼容 |
| Public contracts | `tv_quant.contracts` | 旧 19 names 不变；新 V2.2A names 从 data-foundation package 显式导出 |

`pyproject.toml` 在冻结提交中不存在；依赖 authority 是 `requirements.txt`。
Parquet 已由 `pyarrow==25.0.0` 提供。Task 1 只新增
`exchange-calendars==4.13.2`，不得增加第二个 Parquet 或 calendar package。

## 2. Planned File Structure

| Path | Responsibility |
|---|---|
| `src/tv_quant/data_foundation/contracts.py` | enums、immutable records、request/runtime separation、operation result types |
| `src/tv_quant/data_foundation/projections.py` | identity-bearing semantic payloads、lineage payloads、component/bundle identity |
| `src/tv_quant/data_foundation/parsers.py` | versioned CSV/Parquet profiles、strict parsing、logical normalization |
| `src/tv_quant/data_foundation/calendar.py` | XNYS snapshot materialization、load/hash/coverage/session validation |
| `src/tv_quant/data_foundation/adjustments.py` | corporate-action event/evidence、factor derivation、adjusted OHLCV |
| `src/tv_quant/data_foundation/validation.py` | gaps/evidence、issues/report、duplicate/conflict/OHLCV/coverage validation |
| `src/tv_quant/data_foundation/artifacts.py` | deterministic Parquet/JSON profile、immutable raw/validated/canonical publication |
| `src/tv_quant/data_foundation/registry.py` | manifest/eligibility/provenance bindings、lookup、idempotency、invalidation |
| `src/tv_quant/data_foundation/importer.py` | `import_local_dataset` stage orchestration and fail-closed evidence finalization |
| `src/tv_quant/data_foundation/__init__.py` | deliberate V2.2A public surface only |
| `tests/data_foundation/*.py` | one focused suite per responsibility boundary |
| `tests/fixtures/data_foundation/*` | local CSV/JSON evidence; Parquet equivalents generated deterministically in `tmp_path` |

No V2.2A module may import `yfinance`, `futu`, `requests`, `httpx`,
`socket`, `subprocess`, backtest engines, reporting, broker/account/order code,
or filesystem-scanning helpers.

## 3. Frozen Interface Catalog

### 3.1 Scalar aliases and enums

~~~python
Sha256Hex = str
CanonicalDecimal = str
IsoDate = str
UtcTimestamp = str
RelativePath = str

class MarketDataSourceType(str, Enum):
    LOCAL_CSV = "LOCAL_CSV"
    LOCAL_PARQUET = "LOCAL_PARQUET"
    YFINANCE_SMOKE = "YFINANCE_SMOKE"

class VolumeStatus(str, Enum):
    PRESENT = "PRESENT"
    MISSING_MARKET_EXPLAINED = "MISSING_MARKET_EXPLAINED"

class GapReasonCode(str, Enum):
    PRE_IPO = "PRE_IPO"
    POST_DELISTING = "POST_DELISTING"
    HALT = "HALT"
    EXCHANGE_NO_TRADING = "EXCHANGE_NO_TRADING"
    SOURCE_MISSING = "SOURCE_MISSING"
    SOURCE_INCOMPLETE = "SOURCE_INCOMPLETE"

class GapCoverageState(str, Enum):
    GAPS_PRESENT = "GAPS_PRESENT"
    NO_GAPS_IN_RANGE = "NO_GAPS_IN_RANGE"

class CorporateActionType(str, Enum):
    SPLIT = "SPLIT"
    CASH_DIVIDEND = "CASH_DIVIDEND"

class CorporateActionCoverageState(str, Enum):
    EVENTS_PRESENT = "EVENTS_PRESENT"
    NO_ACTIONS_IN_RANGE = "NO_ACTIONS_IN_RANGE"

class DataEligibilityState(str, Enum):
    VALID = "VALID"
    SMOKE_ONLY = "SMOKE_ONLY"
    INVALIDATED = "INVALIDATED"

class ValidationOutcome(str, Enum):
    VALID = "VALID"
    BLOCKED = "BLOCKED"
    INCOMPLETE = "INCOMPLETE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

class DataFoundationError(RuntimeError):
    blocker_code: BlockerCode
    issue_code: str

    def __init__(
        self,
        blocker_code: BlockerCode,
        issue_code: str,
        message: str,
    ) -> None: ...
~~~

### 3.2 Core record signatures

All persisted records use `@dataclass(frozen=True, slots=True)`, tuples instead
of lists, `MappingProxyType` for nested mappings, lowercase 64-hex validation,
and explicit `schema_version`. Every `*_payload` function returns only JSON
scalar/list/mapping values accepted by the existing `canonical_hash` owner.

~~~python
@dataclass(frozen=True, slots=True)
class CalendarSession:
    trading_date: IsoDate
    session_open_utc: UtcTimestamp
    session_close_utc: UtcTimestamp
    is_half_day: bool

@dataclass(frozen=True, slots=True)
class TradingCalendarRef:
    calendar_id: str
    calendar_source: str
    calendar_version: str
    calendar_hash: Sha256Hex
    timezone: str
    coverage_start: IsoDate
    coverage_end: IsoDate
    sessions: tuple[CalendarSession, ...]

@dataclass(frozen=True, slots=True)
class CsvParserProfile:
    profile_id: str
    profile_version: str
    encoding: str
    delimiter: str
    date_format: str
    column_mapping: Mapping[str, str]
    ignored_columns: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ParquetParserProfile:
    profile_id: str
    profile_version: str
    arrow_schema_fingerprint: Sha256Hex
    column_mapping: Mapping[str, str]
    ignored_columns: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class DataImportRequest:
    request_schema_version: str
    source_type: MarketDataSourceType
    source_relative_path: RelativePath
    source_name: str
    instrument_id: str
    symbol: str
    exchange: str
    currency: str
    csv_profile: CsvParserProfile | None
    parquet_profile: ParquetParserProfile | None
    calendar_ref_relative_path: RelativePath
    declared_timezone: str
    gap_evidence_relative_paths: tuple[RelativePath, ...]
    corporate_action_evidence_relative_paths: tuple[RelativePath, ...]
    adjustment_method: str
    smoke_only: bool

@dataclass(frozen=True, slots=True)
class DataImportRuntimeContext:
    data_root: Path
    path_safety_policy_version: str
    clock: Callable[[], datetime]
    uuid_factory: Callable[[], UUID]

@dataclass(frozen=True, slots=True)
class DailyBarRaw:
    instrument_id: str
    symbol: str
    exchange: str
    trading_date: IsoDate
    session_open_utc: UtcTimestamp
    session_close_utc: UtcTimestamp
    timezone: str
    currency: str
    open: CanonicalDecimal
    high: CanonicalDecimal
    low: CanonicalDecimal
    close: CanonicalDecimal
    volume: int | CanonicalDecimal | None
    volume_status: VolumeStatus
    source_row_ref: str

@dataclass(frozen=True, slots=True)
class DailyBarAdjusted:
    instrument_id: str
    symbol: str
    exchange: str
    trading_date: IsoDate
    session_open_utc: UtcTimestamp
    session_close_utc: UtcTimestamp
    timezone: str
    currency: str
    adjustment_factor_id: Sha256Hex
    adjustment_method: str
    adjusted_open: CanonicalDecimal
    adjusted_high: CanonicalDecimal
    adjusted_low: CanonicalDecimal
    adjusted_close: CanonicalDecimal
    adjusted_volume: int | CanonicalDecimal
~~~

~~~python
@dataclass(frozen=True, slots=True)
class DailyGapRecord:
    gap_schema_version: str
    gap_id: Sha256Hex
    instrument_id: str
    symbol: str
    exchange: str
    trading_date: IsoDate
    gap_reason_code: GapReasonCode
    calendar_id: str
    calendar_hash: Sha256Hex
    semantic_ref: str

@dataclass(frozen=True, slots=True)
class GapEvidence:
    evidence_schema_version: str
    evidence_id: Sha256Hex
    evidence_hash: Sha256Hex
    semantic_coverage_hash: Sha256Hex
    coverage_state: GapCoverageState
    instrument_id: str
    symbol: str
    exchange: str
    coverage_start: IsoDate
    coverage_end: IsoDate
    calendar_id: str
    calendar_hash: Sha256Hex
    gap_ids: tuple[Sha256Hex, ...]
    gap_semantic_refs: tuple[str, ...]
    source_type: MarketDataSourceType
    source_name: str
    original_evidence_refs: tuple[RelativePath, ...]
    original_evidence_hashes: tuple[Sha256Hex, ...]
    validation_status: ValidationOutcome
    blocker_codes: tuple[BlockerCode, ...]

@dataclass(frozen=True, slots=True)
class CorporateActionEvent:
    event_schema_version: str
    event_id: Sha256Hex
    instrument_id: str
    symbol: str
    exchange: str
    event_type: CorporateActionType
    ex_date: IsoDate
    effective_trading_date: IsoDate
    split_ratio: CanonicalDecimal | None
    cash_amount: CanonicalDecimal | None
    cash_currency: str | None

@dataclass(frozen=True, slots=True)
class CorporateActionEvidence:
    evidence_schema_version: str
    evidence_id: Sha256Hex
    evidence_hash: Sha256Hex
    semantic_coverage_hash: Sha256Hex
    coverage_state: CorporateActionCoverageState
    instrument_id: str
    symbol: str
    exchange: str
    coverage_start: IsoDate
    coverage_end: IsoDate
    source_type: MarketDataSourceType
    source_name: str
    original_file_name: str
    original_file_hash: Sha256Hex
    calendar_id: str
    calendar_hash: Sha256Hex
    event_ids: tuple[Sha256Hex, ...]
    source_event_refs: tuple[str, ...]
    events_hash: Sha256Hex
    validation_status: ValidationOutcome
    blocker_codes: tuple[BlockerCode, ...]

@dataclass(frozen=True, slots=True)
class AdjustmentFactor:
    adjustment_factor_id: Sha256Hex
    instrument_id: str
    symbol: str
    exchange: str
    effective_trading_date: IsoDate
    price_factor: CanonicalDecimal
    volume_factor: CanonicalDecimal
    adjustment_method: str
    corporate_action_semantic_coverage_hash: Sha256Hex
    corporate_action_evidence_id: Sha256Hex
    corporate_action_evidence_hash: Sha256Hex
    corporate_action_event_ids: tuple[Sha256Hex, ...]
    factor_version: str
~~~

~~~python
@dataclass(frozen=True, slots=True)
class DataValidationIssue:
    issue_code: str
    category: str
    severity: str
    blocking: bool
    stable_key: tuple[str, str, str, IsoDate] | None
    field: str | None
    source_row_ref: str | None
    observed: str | None
    expected: str
    gap_reason_code: GapReasonCode | None
    mapped_blocker_code: BlockerCode

@dataclass(frozen=True, slots=True)
class DataValidationReport:
    report_schema_version: str
    report_id: Sha256Hex
    report_hash: Sha256Hex
    import_id: str
    candidate_content_hash: Sha256Hex
    validator_versions: Mapping[str, str]
    calendar_id: str
    calendar_hash: Sha256Hex
    timezone: str
    daily_bar_count: int
    daily_gap_count: int
    gap_component_hash: Sha256Hex
    gap_evidence_hash: Sha256Hex
    gap_semantic_coverage_hash: Sha256Hex
    issues: tuple[DataValidationIssue, ...]
    check_statuses: Mapping[str, ValidationOutcome]
    validation_status: ValidationOutcome
    blocker_codes: tuple[BlockerCode, ...]

@dataclass(frozen=True, slots=True)
class NormalizedDatasetCandidate:
    import_id: str
    raw_bars: tuple[DailyBarRaw, ...]
    daily_gaps: tuple[DailyGapRecord, ...]
    gap_evidence: GapEvidence
    corporate_action_events: tuple[CorporateActionEvent, ...]
    corporate_action_evidence: CorporateActionEvidence
    calendar_ref: TradingCalendarRef

@dataclass(frozen=True, slots=True)
class LogicalDatasetBundle:
    raw_bars: tuple[DailyBarRaw, ...]
    daily_gaps: tuple[DailyGapRecord, ...]
    gap_evidence: GapEvidence
    corporate_action_events: tuple[CorporateActionEvent, ...]
    corporate_action_evidence: CorporateActionEvidence
    adjustment_factors: tuple[AdjustmentFactor, ...]
    adjusted_bars: tuple[DailyBarAdjusted, ...]
    semantic_dependency_hashes: tuple[Sha256Hex, ...]
~~~

### 3.3 Identity, manifest, registry and operation signatures

~~~python
def request_payload(request: DataImportRequest) -> Mapping[str, object]: ...
def daily_bar_semantic_payload(bar: DailyBarRaw) -> Mapping[str, object]: ...
def gap_semantic_payload(gap: DailyGapRecord) -> Mapping[str, object]: ...
def gap_evidence_semantic_payload(evidence: GapEvidence) -> Mapping[str, object]: ...
def corporate_action_event_payload(event: CorporateActionEvent) -> Mapping[str, object]: ...
def corporate_action_evidence_semantic_payload(
    evidence: CorporateActionEvidence,
) -> Mapping[str, object]: ...
def adjustment_factor_semantic_payload(
    factor: AdjustmentFactor,
) -> Mapping[str, object]: ...
def logical_component_hash(rows: Sequence[Mapping[str, object]]) -> Sha256Hex: ...
def build_dataset_identity(bundle: LogicalDatasetBundle) -> DatasetIdentity: ...

def parse_csv_source(
    source_path: Path,
    request: DataImportRequest,
    calendar_ref: TradingCalendarRef,
) -> tuple[DailyBarRaw, ...]: ...
def parse_parquet_source(
    source_path: Path,
    request: DataImportRequest,
    calendar_ref: TradingCalendarRef,
) -> tuple[DailyBarRaw, ...]: ...
def materialize_xnys_snapshot(
    coverage_start: IsoDate,
    coverage_end: IsoDate,
) -> TradingCalendarRef: ...
def load_calendar_snapshot(path: Path) -> TradingCalendarRef: ...
def validate_daily_dataset(
    candidate: NormalizedDatasetCandidate,
) -> DataValidationReport: ...
def derive_adjustment_factors(
    events: tuple[CorporateActionEvent, ...],
    evidence: CorporateActionEvidence,
    method: str,
) -> tuple[AdjustmentFactor, ...]: ...
def apply_adjustments(
    raw_bars: tuple[DailyBarRaw, ...],
    factors: tuple[AdjustmentFactor, ...],
    method: str,
) -> tuple[DailyBarAdjusted, ...]: ...
~~~

~~~python
@dataclass(frozen=True, slots=True)
class DatasetIdentity:
    identity_schema_version: str
    dataset_id: Sha256Hex
    dataset_kind: str
    content_hash: Sha256Hex
    semantic_dependency_hashes: tuple[Sha256Hex, ...]

@dataclass(frozen=True, slots=True)
class DatasetProvenance:
    provenance_id: Sha256Hex
    provenance_hash: Sha256Hex
    provider_id: str
    provider_capability_id: str
    provider_capability_version: str
    source_type: MarketDataSourceType
    source_name: str
    original_file_name: str
    original_file_hash: Sha256Hex
    import_timestamp_utc: UtcTimestamp
    schema_version: str
    calendar_id: str
    calendar_version: str
    timezone: str
    adjustment_status: str
    adjustment_method: str
    source_date_range: tuple[IsoDate, IsoDate]
    canonical_date_range: tuple[IsoDate, IsoDate]
    row_count: int
    gap_count: int
    component_logical_hashes: Mapping[str, Sha256Hex]
    component_file_hashes: Mapping[str, Sha256Hex]
    gap_evidence_ref: RelativePath
    gap_evidence_hash: Sha256Hex
    gap_semantic_coverage_hash: Sha256Hex
    validation_status: ValidationOutcome
    blocker_codes: tuple[BlockerCode, ...]
    parent_dataset_id: Sha256Hex | None
    dataset_id: Sha256Hex
    content_hash: Sha256Hex
    dependency_hashes: tuple[Sha256Hex, ...]

@dataclass(frozen=True, slots=True)
class DataImportManifest:
    import_id: str
    request_hash: Sha256Hex
    source_type: MarketDataSourceType
    source_name: str
    original_file_name: str
    original_file_hash: Sha256Hex
    import_timestamp_utc: UtcTimestamp
    raw_artifact_ref: RelativePath
    raw_artifact_hash: Sha256Hex
    parser_version: str
    schema_version: str
    stage_statuses: Mapping[str, ValidationOutcome]
    validation_report_ref: RelativePath | None
    validation_report_hash: Sha256Hex | None
    gap_evidence_refs: tuple[RelativePath, ...]
    gap_evidence_hashes: tuple[Sha256Hex, ...]
    candidate_dataset_id: Sha256Hex | None
    final_dataset_id: Sha256Hex | None
    blocker_codes: tuple[BlockerCode, ...]

@dataclass(frozen=True, slots=True)
class CanonicalDatasetManifest:
    manifest_schema_version: str
    manifest_revision: int
    dataset_identity: DatasetIdentity
    schema_hash: Sha256Hex
    calendar_ref: TradingCalendarRef
    timezone_policy_hash: Sha256Hex
    stable_key_definition: tuple[str, ...]
    source_range: tuple[IsoDate, IsoDate]
    requested_range: tuple[IsoDate, IsoDate]
    canonical_range: tuple[IsoDate, IsoDate]
    row_count: int
    gap_count: int
    component_refs: Mapping[str, RelativePath]
    component_logical_hashes: Mapping[str, Sha256Hex]
    component_file_hashes: Mapping[str, Sha256Hex]
    gap_semantic_coverage_hash: Sha256Hex
    corporate_action_semantic_coverage_hash: Sha256Hex
    creation_provenance_ref: RelativePath
    creation_provenance_hash: Sha256Hex
    validation_report_ref: RelativePath
    validation_report_hash: Sha256Hex
    parquet_writer_profile: Mapping[str, object]
    parent_dataset_id: Sha256Hex | None
~~~

~~~python
@dataclass(frozen=True, slots=True)
class DataEligibility:
    eligibility_id: Sha256Hex
    eligibility_hash: Sha256Hex
    dataset_id: Sha256Hex
    manifest_hash: Sha256Hex
    qualifying_provenance_hashes: tuple[Sha256Hex, ...]
    state: DataEligibilityState
    formal_eligible: bool
    check_matrix: Mapping[str, bool]
    blocker_codes: tuple[BlockerCode, ...]
    invalidation_event_id: Sha256Hex | None
    invalidation_event_hash: Sha256Hex | None
    invalidation_reason: str | None

@dataclass(frozen=True, slots=True)
class InvalidationEvent:
    event_schema_version: str
    invalidation_event_id: Sha256Hex
    invalidation_event_hash: Sha256Hex
    dataset_id: Sha256Hex
    manifest_hash: Sha256Hex
    prior_eligibility_id: Sha256Hex
    prior_eligibility_hash: Sha256Hex
    prior_eligibility_state: DataEligibilityState
    reason_code: str
    actor_ref: str
    event_timestamp_utc: UtcTimestamp
    parent_registry_snapshot_hash: Sha256Hex

@dataclass(frozen=True, slots=True)
class RegistryBinding:
    dataset_id: Sha256Hex
    manifest_revision: int
    manifest_ref: RelativePath
    manifest_hash: Sha256Hex
    eligibility_ref: RelativePath
    eligibility_hash: Sha256Hex
    eligibility_state: DataEligibilityState
    provenance_refs: tuple[RelativePath, ...]
    provenance_hashes: tuple[Sha256Hex, ...]
    provider_capability_ids: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    registry_schema_version: str
    snapshot_hash: Sha256Hex
    parent_snapshot_hash: Sha256Hex | None
    bindings: tuple[RegistryBinding, ...]
    invalidation_event_refs: tuple[RelativePath, ...]

@dataclass(frozen=True, slots=True)
class DataFoundationOperationResult:
    status: PipelineStatus
    blocker_code: BlockerCode | None
    recoverable: bool
    retryable: bool
    terminal: bool
    user_action: str
    stage: str
    issue_refs: tuple[RelativePath, ...]
    evidence_refs: tuple[RelativePath, ...]

@dataclass(frozen=True, slots=True)
class ImportLocalDatasetResult:
    operation: DataFoundationOperationResult
    import_manifest: DataImportManifest
    validation_report: DataValidationReport | None
    canonical_manifest: CanonicalDatasetManifest | None
    eligibility: DataEligibility | None
    registry_binding: RegistryBinding | None
~~~

~~~python
def publish_canonical_bundle(
    root: Path,
    bundle: LogicalDatasetBundle,
    identity: DatasetIdentity,
    provenance: DatasetProvenance,
    report: DataValidationReport,
    writer_profile: Mapping[str, object],
) -> CanonicalDatasetManifest: ...

class MarketDataRegistry:
    @classmethod
    def load(cls, root: Path, snapshot_ref: RelativePath) -> MarketDataRegistry: ...
    def register(
        self,
        manifest: CanonicalDatasetManifest,
        manifest_ref: RelativePath,
        provenance: DatasetProvenance,
        provenance_ref: RelativePath,
        eligibility: DataEligibility,
        eligibility_ref: RelativePath,
    ) -> RegistrySnapshot: ...

def find_latest_eligible_dataset(
    requirement: DatasetRequirement,
    registry: MarketDataRegistry,
    expected_snapshot_hash: Sha256Hex,
    capability_registry: CapabilityRegistry,
) -> RegistryBinding | DataFoundationOperationResult: ...

def invalidate_dataset(
    registry: MarketDataRegistry,
    dataset_id: Sha256Hex,
    expected_manifest_hash: Sha256Hex,
    expected_eligibility_ref: RelativePath,
    expected_eligibility_hash: Sha256Hex,
    expected_snapshot_hash: Sha256Hex,
    reason_code: str,
    actor_ref: str,
    event_timestamp_utc: UtcTimestamp,
) -> tuple[InvalidationEvent, DataEligibility, RegistrySnapshot]: ...

def import_local_dataset(
    request: DataImportRequest,
    runtime: DataImportRuntimeContext,
) -> ImportLocalDatasetResult: ...
~~~

### 3.4 Private helper signatures used by task pseudocode

These helpers remain private to their named module. Their signatures are frozen
here so task snippets do not depend on implicit functions.

~~~python
# projections.py
def component_hashes(bundle: LogicalDatasetBundle) -> Mapping[str, Sha256Hex]: ...
def project_raw(rows: tuple[DailyBarRaw, ...]) -> tuple[Mapping[str, object], ...]: ...
def project_gaps(rows: tuple[DailyGapRecord, ...]) -> tuple[Mapping[str, object], ...]: ...
def project_events(rows: tuple[CorporateActionEvent, ...]) -> tuple[Mapping[str, object], ...]: ...
def project_factors(rows: tuple[AdjustmentFactor, ...]) -> tuple[Mapping[str, object], ...]: ...
def project_adjusted(rows: tuple[DailyBarAdjusted, ...]) -> tuple[Mapping[str, object], ...]: ...
def identity_payload(identity: DatasetIdentity) -> Mapping[str, object]: ...
def stable_row_key(record: object) -> tuple[str, str, str, str]: ...

# parsers.py
def require_exact_columns(actual: Sequence[str] | None, profile: object) -> None: ...
def arrow_schema_payload(schema: pa.Schema) -> Mapping[str, object]: ...
def require_arrow_types(actual: pa.Schema, expected: pa.Schema) -> None: ...
def expected_arrow_fields() -> pa.Schema: ...

# calendar.py
def utc_z(value: datetime | pd.Timestamp) -> UtcTimestamp: ...
def snapshot_payload_without_hash(
    sessions: tuple[CalendarSession, ...],
) -> Mapping[str, object]: ...
def schedule_row_to_session(index: pd.Timestamp, row: pd.Series) -> CalendarSession: ...

# validation.py
def issue(
    issue_code: str,
    *,
    blocking: bool,
    mapped_blocker: BlockerCode,
    stable_key: tuple[str, str, str, IsoDate] | None = None,
) -> DataValidationIssue: ...
def ordered_issues(
    issues: Iterable[DataValidationIssue],
) -> tuple[DataValidationIssue, ...]: ...
def validate_order_and_unique_keys(
    rows: tuple[DailyBarRaw, ...],
) -> tuple[DataValidationIssue, ...]: ...
def validate_sessions(
    rows: tuple[DailyBarRaw, ...],
    calendar_ref: TradingCalendarRef,
) -> tuple[DataValidationIssue, ...]: ...
def validate_ohlcv(
    rows: tuple[DailyBarRaw, ...],
) -> tuple[DataValidationIssue, ...]: ...
def build_validation_report(
    candidate: NormalizedDatasetCandidate,
    issues: tuple[DataValidationIssue, ...],
) -> DataValidationReport: ...
def run_check(
    name: str,
    check: Callable[[], tuple[DataValidationIssue, ...]],
) -> tuple[DataValidationIssue, ...]: ...

# adjustments.py
def mul_price(value: CanonicalDecimal, factor: CanonicalDecimal) -> CanonicalDecimal: ...
def mul_volume(
    value: int | CanonicalDecimal | None,
    factor: CanonicalDecimal,
) -> int | CanonicalDecimal: ...
def factor_for_trading_date(
    factors: tuple[AdjustmentFactor, ...],
    trading_date: IsoDate,
) -> AdjustmentFactor: ...

# artifacts.py
CANONICAL_MANIFEST_NAME = "canonical-dataset-manifest.json"
COMPONENT_ARROW_SCHEMAS: Mapping[str, pa.Schema]
def create_exclusive_staging(root: Path, dataset_id: str, revision: int) -> Path: ...
def write_and_verify_components(
    staging: Path,
    bundle: LogicalDatasetBundle,
    writer_profile: Mapping[str, object],
) -> None: ...
def verify_published_hashes(
    staging: Path,
    manifest: CanonicalDatasetManifest,
) -> None: ...
def records_to_table(component_name: str, records: Sequence[object]) -> pa.Table: ...

# registry.py
def require_exact_manifest_hash(
    manifest: CanonicalDatasetManifest,
    manifest_hash: Sha256Hex,
) -> None: ...
def require_nonempty_provenances(
    provenances: tuple[DatasetProvenance, ...],
) -> None: ...
def build_hashed_eligibility(**fields: object) -> DataEligibility: ...
def verify_binding(
    manifest: CanonicalDatasetManifest,
    manifest_hash: Sha256Hex,
    eligibility: DataEligibility,
    provenances: tuple[DatasetProvenance, ...],
) -> None: ...
def build_registry_snapshot(
    parent_hash: Sha256Hex | None,
    bindings: tuple[RegistryBinding, ...],
) -> RegistrySnapshot: ...
def publish_registry_snapshot_atomically(root: Path, snapshot: RegistrySnapshot) -> None: ...
def verify_and_filter_bindings(
    registry: MarketDataRegistry,
    requirement: DatasetRequirement,
    expected_snapshot_hash: Sha256Hex,
) -> tuple[RegistryBinding, ...]: ...
def load_eligibility(binding: RegistryBinding) -> DataEligibility: ...
def select_without_content_conflict(
    bindings: tuple[RegistryBinding, ...],
) -> RegistryBinding: ...
def capability_blocker(issue_code: str) -> DataFoundationOperationResult: ...
def replace_prior_as_invalidated(
    prior: DataEligibility,
    event_id: Sha256Hex,
    event_hash: Sha256Hex,
) -> DataEligibility: ...

class RegistryTransaction:
    def stage_json(self, name: str, payload: Mapping[str, object]) -> None: ...
    def verify_all_hashes(self) -> None: ...
    def publish_files(self) -> None: ...
    def publish_snapshot_pointer_last(self) -> None: ...

def registry_transaction(
    root: Path,
    expected_snapshot_hash: Sha256Hex,
) -> ContextManager[RegistryTransaction]: ...

# path_safety.py
def existing_ancestors(path: Path) -> tuple[Path, ...]: ...
def is_reparse_point(path: Path) -> bool: ...
def volume_identity(path: Path) -> tuple[int, int]: ...

# importer.py
def verify_source(request: DataImportRequest, runtime: DataImportRuntimeContext) -> Path: ...
def load_contained_calendar(
    request: DataImportRequest,
    runtime: DataImportRuntimeContext,
) -> TradingCalendarRef: ...
def parse_by_source_type(
    source: Path,
    request: DataImportRequest,
    calendar_ref: TradingCalendarRef,
) -> tuple[DailyBarRaw, ...]: ...
def assemble_candidate(
    import_id: str,
    rows: tuple[DailyBarRaw, ...],
    request: DataImportRequest,
    runtime: DataImportRuntimeContext,
    calendar_ref: TradingCalendarRef,
) -> NormalizedDatasetCandidate: ...
def finalize_failed_import(
    import_id: str,
    imported_at: UtcTimestamp,
    raw_ref: RelativePath,
    raw_hash: Sha256Hex,
    error: DataFoundationError,
) -> ImportLocalDatasetResult: ...
def finalize_nonvalid_import(
    import_id: str,
    imported_at: UtcTimestamp,
    candidate: NormalizedDatasetCandidate,
    report: DataValidationReport,
) -> ImportLocalDatasetResult: ...
def continue_valid_import(
    request: DataImportRequest,
    runtime: DataImportRuntimeContext,
    imported_at: UtcTimestamp,
    raw_ref: RelativePath,
    raw_hash: Sha256Hex,
    candidate: NormalizedDatasetCandidate,
    report: DataValidationReport,
) -> ImportLocalDatasetResult: ...
def assemble_logical_bundle(
    candidate: NormalizedDatasetCandidate,
    factors: tuple[AdjustmentFactor, ...],
    adjusted: tuple[DailyBarAdjusted, ...],
) -> LogicalDatasetBundle: ...
def manifest_candidate(bundle: LogicalDatasetBundle) -> CanonicalDatasetManifest: ...
def reuse_or_publish(
    decision: RegistrationDecision,
    bundle: LogicalDatasetBundle,
    report: DataValidationReport,
    provenance: DatasetProvenance,
) -> PublishedCanonicalBundle: ...
def check_matrix(report: DataValidationReport) -> Mapping[str, bool]: ...
def build_and_publish_provenance(
    runtime: DataImportRuntimeContext,
    request: DataImportRequest,
    identity: DatasetIdentity,
    report: DataValidationReport,
) -> tuple[DatasetProvenance, RelativePath]: ...
def publish_eligibility(
    root: Path,
    eligibility: DataEligibility,
) -> RelativePath: ...
def load_registry_from_runtime(
    runtime: DataImportRuntimeContext,
) -> MarketDataRegistry: ...
~~~

## 4. Identity and Lineage Projection Matrix

`Semantic identity=Y` means the field or its normalized semantic projection
contributes to a component logical hash, bundle content hash, semantic
dependency hash, or dataset ID. `Lineage only=Y` means the field is persisted
for traceability but is excluded from dataset identity.

| Contract | Field | Semantic identity | Lineage only | Persisted |
|---|---|---:|---:|---:|
| DailyBarRaw | instrument_id | Y | N | Y |
| DailyBarRaw | symbol | Y | N | Y |
| DailyBarRaw | exchange | Y | N | Y |
| DailyBarRaw | trading_date | Y | N | Y |
| DailyBarRaw | session_open_utc | Y | N | Y |
| DailyBarRaw | session_close_utc | Y | N | Y |
| DailyBarRaw | timezone | Y | N | Y |
| DailyBarRaw | currency | Y | N | Y |
| DailyBarRaw | open/high/low/close | Y | N | Y |
| DailyBarRaw | volume | Y | N | Y |
| DailyBarRaw | volume_status | Y | N | Y |
| DailyBarRaw | source_row_ref | N | Y | Y |
| DailyBarAdjusted | stable identity/time/currency fields | Y | N | Y |
| DailyBarAdjusted | adjustment_factor_id | Y | N | Y |
| DailyBarAdjusted | adjustment_method | Y | N | Y |
| DailyBarAdjusted | adjusted_open/high/low/close/volume | Y | N | Y |
| DailyGapRecord | gap_schema_version | Y | N | Y |
| DailyGapRecord | gap_id | Y | N | Y |
| DailyGapRecord | stable listing identity | Y | N | Y |
| DailyGapRecord | trading_date | Y | N | Y |
| DailyGapRecord | gap_reason_code | Y | N | Y |
| DailyGapRecord | calendar_id/calendar_hash | Y | N | Y |
| DailyGapRecord | semantic_ref | Y | N | Y |
| GapEvidence | evidence_schema_version | N | Y | Y |
| GapEvidence | evidence_id/evidence_hash | N | Y | Y |
| GapEvidence | semantic_coverage_hash | Y | N | Y |
| GapEvidence | coverage_state | Y | N | Y |
| GapEvidence | listing/range/calendar fields | Y | N | Y |
| GapEvidence | gap_ids/gap_semantic_refs | Y | N | Y |
| GapEvidence | source_type/source_name | N | Y | Y |
| GapEvidence | original_evidence_refs/hashes | N | Y | Y |
| GapEvidence | validation_status/blocker_codes | N | Y | Y |
| AdjustmentFactor | adjustment_factor_id | Y | N | Y |
| AdjustmentFactor | stable listing/effective date | Y | N | Y |
| AdjustmentFactor | price_factor/volume_factor | Y | N | Y |
| AdjustmentFactor | adjustment_method/factor_version | Y | N | Y |
| AdjustmentFactor | corporate_action_semantic_coverage_hash | Y | N | Y |
| AdjustmentFactor | corporate_action_event_ids | Y | N | Y |
| AdjustmentFactor | corporate_action_evidence_id/hash | N | Y | Y |
| CorporateActionEvent | event_schema_version | Y | N | Y |
| CorporateActionEvent | event_id | Y | N | Y |
| CorporateActionEvent | stable listing identity | Y | N | Y |
| CorporateActionEvent | event_type/ex_date/effective_trading_date | Y | N | Y |
| CorporateActionEvent | split_ratio | Y when SPLIT | N | Y |
| CorporateActionEvent | cash_amount/cash_currency | Y when CASH_DIVIDEND | N | Y |
| CorporateActionEvidence | evidence_schema_version | N | Y | Y |
| CorporateActionEvidence | evidence_id/evidence_hash | N | Y | Y |
| CorporateActionEvidence | semantic_coverage_hash | Y | N | Y |
| CorporateActionEvidence | coverage_state | Y | N | Y |
| CorporateActionEvidence | listing/range/calendar fields | Y | N | Y |
| CorporateActionEvidence | event_ids/events_hash | Y | N | Y |
| CorporateActionEvidence | source/provider/original-file fields | N | Y | Y |
| CorporateActionEvidence | source_event_refs | N | Y | Y |
| CorporateActionEvidence | validation_status/blocker_codes | N | Y | Y |
| DatasetProvenance | provenance_id/provenance_hash | N | Y | Y |
| DatasetProvenance | provider/source/original-file fields | N | Y | Y |
| DatasetProvenance | import_timestamp_utc | N | Y | Y |
| DatasetProvenance | schema/calendar/timezone fields | N | Y | Y |
| DatasetProvenance | adjustment/range/count fields | N | Y | Y |
| DatasetProvenance | component logical/file hashes | N | Y | Y |
| DatasetProvenance | gap evidence full/semantic hashes | N | Y | Y |
| DatasetProvenance | validation_status/blockers | N | Y | Y |
| DatasetProvenance | parent_dataset_id/dataset_id/content_hash | N | Y | Y |
| DatasetProvenance | dependency_hashes | N | Y | Y |
| CanonicalDatasetManifest | manifest_schema_version/revision | N | Y | Y |
| CanonicalDatasetManifest | DatasetIdentity | Y | N | Y |
| CanonicalDatasetManifest | logical schema/calendar/timezone refs | Y | N | Y |
| CanonicalDatasetManifest | stable key/ranges/counts | Y | N | Y |
| CanonicalDatasetManifest | component logical hashes | Y | N | Y |
| CanonicalDatasetManifest | gap/action semantic coverage hashes | Y | N | Y |
| CanonicalDatasetManifest | component refs/file hashes | N | Y | Y |
| CanonicalDatasetManifest | creation provenance ref/hash | N | Y | Y |
| CanonicalDatasetManifest | validation report ref/hash | N | Y | Y |
| CanonicalDatasetManifest | writer/compression/row-group/metadata profile | N | Y | Y |
| CanonicalDatasetManifest | parent_dataset_id | N | Y | Y |

Physical Parquet parameters never enter `DatasetIdentity`. Logical and physical
hashes remain separate. No projection function may call a new hash helper;
all projections terminate at `tv_quant.run_manifest.canonical_hash`.

## 5. Design-to-Test Traceability Matrix

| Design requirement | Task | Test file | Test name | Expected result |
|---|---:|---|---|---|
| CSV/Parquet logical equivalence | 4 | `tests/data_foundation/test_parsers.py` | `test_csv_and_parquet_normalize_to_same_rows` | same row payload and logical hash |
| source_row_ref excluded from dataset identity | 3 | `tests/data_foundation/test_projections.py` | `test_source_row_ref_change_does_not_change_dataset_id` | dataset IDs equal |
| different evidence lineage with same semantic coverage | 3 | `tests/data_foundation/test_projections.py` | `test_lineage_change_with_same_semantics_keeps_dataset_id` | dataset IDs equal; evidence hashes differ |
| different logical data changes identity | 9 | `tests/data_foundation/test_identity.py` | `test_logical_value_change_changes_dataset_id` | dataset IDs differ |
| writer/compression/row-group only changes file hash | 10 | `tests/data_foundation/test_artifacts.py` | `test_physical_profile_changes_file_hash_not_dataset_id` | file hashes differ; dataset IDs equal |
| deterministic empty daily-gaps.parquet | 10 | `tests/data_foundation/test_artifacts.py` | `test_empty_gap_component_is_deterministic` | fixed schema, zero rows, repeatable logical hash |
| NO_GAPS_IN_RANGE | 6 | `tests/data_foundation/test_gap_evidence.py` | `test_no_gaps_requires_explicit_complete_evidence` | VALID only with complete evidence |
| PRE_IPO | 6 | `tests/data_foundation/test_gap_evidence.py` | `test_allowed_gap_reason_with_evidence_is_valid[PRE_IPO]` | accepted exclusion |
| POST_DELISTING | 6 | `tests/data_foundation/test_gap_evidence.py` | `test_allowed_gap_reason_with_evidence_is_valid[POST_DELISTING]` | accepted exclusion |
| HALT | 6 | `tests/data_foundation/test_gap_evidence.py` | `test_allowed_gap_reason_with_evidence_is_valid[HALT]` | accepted only with evidence |
| EXCHANGE_NO_TRADING | 6 | `tests/data_foundation/test_gap_evidence.py` | `test_allowed_gap_reason_with_evidence_is_valid[EXCHANGE_NO_TRADING]` | accepted only with evidence |
| SOURCE_MISSING | 15 | `tests/data_foundation/test_importer.py` | `test_source_missing_is_blocked_without_eligibility` | BLOCKED; no canonical/eligibility |
| SOURCE_INCOMPLETE | 15 | `tests/data_foundation/test_importer.py` | `test_source_incomplete_has_no_eligibility` | INCOMPLETE; no canonical/eligibility |
| invalid DataEligibility states rejected | 11 | `tests/data_foundation/test_registry.py` | `test_eligibility_rejects_operation_outcomes` | construction raises ValueError |
| YFINANCE_SMOKE qualification | 11 | `tests/data_foundation/test_registry.py` | `test_smoke_import_creates_smoke_only` | SMOKE_ONLY and formal false |
| smoke excluded from formal query | 12 | `tests/data_foundation/test_registry_query.py` | `test_formal_lookup_excludes_smoke_binding` | typed DATA_CAPABILITY_BLOCKER |
| exact manifest invalidation | 13 | `tests/data_foundation/test_invalidation.py` | `test_invalidation_scopes_exact_manifest_hash` | other revisions unchanged |
| invalidation triple atomicity | 13 | `tests/data_foundation/test_invalidation.py` | `test_invalidation_triple_is_all_or_none` | no partial visibility |
| invalidation replay idempotency | 13 | `tests/data_foundation/test_invalidation.py` | `test_identical_invalidation_replay_reuses_triple` | same three hashes returned |
| identical re-import reuse | 12 | `tests/data_foundation/test_registry_query.py` | `test_identical_reimport_reuses_manifest_revision` | same artifacts/revision; new provenance |
| identity collision fail closed | 12 | `tests/data_foundation/test_registry_query.py` | `test_dataset_id_collision_rejects_mismatch` | DATA_VALIDATION_BLOCKER |
| manifest/eligibility one-way reference | 10 | `tests/data_foundation/test_artifacts.py` | `test_manifest_has_no_eligibility_back_reference` | manifest payload has no eligibility fields |
| path traversal and Windows special paths | 14 | `tests/data_foundation/test_security.py` | `test_windows_special_paths_and_reparse_escape_are_rejected` | CONFIG_VALIDATION_BLOCKER before read/write |
| request excludes absolute root | 2 | `tests/data_foundation/test_contracts.py` | `test_runtime_root_is_not_serializable_or_hashable` | request hash unchanged; serialization rejected |
| NYSE half-day and DST UTC sessions | 5 | `tests/data_foundation/test_calendar.py` | `test_xnys_half_day_and_dst_sessions_are_frozen` | exact UTC opens/closes |
| corporate-action lineage excluded from factor identity | 7 | `tests/data_foundation/test_adjustments.py` | `test_evidence_lineage_does_not_change_factor_identity` | factor IDs equal |
| full local import orchestration | 15 | `tests/data_foundation/test_importer.py` | `test_valid_local_csv_publishes_complete_binding` | immutable manifest + VALID binding |
| static duplicate-owner/security checks | 17 | `tests/data_foundation/test_static_ownership.py` | `test_data_foundation_reuses_existing_owners_and_has_no_network_path` | no forbidden definitions/imports |
| V2.1 regression | 17 | existing full suite | `py -3.14 -m pytest tests -q` | 517 existing tests plus V2.2A tests pass |

### 5.1 Test helper contract

Every helper name used in a test snippet is a private function defined above
the test in that same test module. The implementation follows these signatures;
helpers construct public records or local `tmp_path` state and never bypass a
production validation, publication, eligibility or registry gate.

~~~python
def valid_request(**changes: object) -> DataImportRequest: ...
def valid_eligibility_fields() -> dict[str, object]: ...
def dataclass_payload(value: object) -> Mapping[str, object]: ...
def utc_clock() -> datetime: ...
def uuid_factory() -> UUID: ...
def raw_bar(**changes: object) -> DailyBarRaw: ...
def bundle_with(**changes: object) -> LogicalDatasetBundle: ...
def gap_evidence(**changes: object) -> GapEvidence: ...
def csv_request(**changes: object) -> DataImportRequest: ...
def parquet_request(**changes: object) -> DataImportRequest: ...
def calendar() -> TradingCalendarRef: ...
def write_equivalent_parquet(root: Path, rows: tuple[DailyBarRaw, ...]) -> Path: ...
def full_bars() -> tuple[DailyBarRaw, ...]: ...
def no_gaps_evidence() -> GapEvidence: ...
def gaps_present_evidence(gap: DailyGapRecord) -> GapEvidence: ...
def daily_gap(
    *,
    reason: GapReasonCode,
    semantic_ref: str,
) -> DailyGapRecord: ...
def valid_semantic_ref(reason: GapReasonCode) -> str: ...
def events() -> tuple[CorporateActionEvent, ...]: ...
def evidence(**changes: object) -> CorporateActionEvidence: ...
def no_actions_evidence() -> CorporateActionEvidence: ...
def identity_factor(*, price: str, volume: str) -> AdjustmentFactor: ...
def candidate_with(*rows: DailyBarRaw, **changes: object) -> NormalizedDatasetCandidate: ...
def conflicting_rows() -> tuple[DailyBarRaw, DailyBarRaw]: ...
def bundle(**changes: object) -> LogicalDatasetBundle: ...
def identity_for(value: LogicalDatasetBundle) -> DatasetIdentity: ...
def deterministic_collision(value: Mapping[str, object]) -> str: ...
def writer_profile(**changes: object) -> Mapping[str, object]: ...
def publish_bundle(root: Path, value: LogicalDatasetBundle, profile: Mapping[str, object]) -> PublishedCanonicalBundle: ...
def read_table(bundle: PublishedCanonicalBundle, component: str) -> pa.Table: ...
def read_manifest(bundle: PublishedCanonicalBundle) -> Mapping[str, object]: ...
def manifest(**changes: object) -> CanonicalDatasetManifest: ...
def manifest_hash() -> Sha256Hex: ...
def smoke_provenance() -> DatasetProvenance: ...
def all_checks_true() -> Mapping[str, bool]: ...
def eligibility_fields() -> dict[str, object]: ...
def registry() -> MarketDataRegistry: ...
def dataset(**changes: object) -> LogicalDatasetBundle: ...
@dataclass(frozen=True, slots=True)
class RegistrationTestResult:
    registry: MarketDataRegistry
    binding: RegistryBinding

def register_dataset(
    registry: MarketDataRegistry,
    value: LogicalDatasetBundle,
    *,
    provider: str,
) -> RegistrationTestResult: ...
def requirement() -> DatasetRequirement: ...
def smoke_registry() -> MarketDataRegistry: ...
def snapshot_hash() -> Sha256Hex: ...
def capabilities() -> CapabilityRegistry: ...
def registry_with_two_revisions() -> MarketDataRegistry: ...
def binding(snapshot: RegistrySnapshot, manifest_hash: Sha256Hex) -> RegistryBinding: ...
def invalidate_twice_same_request() -> tuple[InvalidationEvent, DataEligibility, RegistrySnapshot]: ...
def invalidate_once() -> tuple[InvalidationEvent, DataEligibility, RegistrySnapshot]: ...
def inject_failure_after_each_staged_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None: ...
def invalidate_fixture_binding(
    root: Path,
) -> tuple[InvalidationEvent, DataEligibility, RegistrySnapshot]: ...
def visible_invalidation_records(root: Path) -> tuple[RelativePath, ...]: ...
def record_verify_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]: ...
def publish_contained_bundle() -> PublishedCanonicalBundle: ...
def valid_csv_request() -> DataImportRequest: ...
def runtime(root: Path) -> DataImportRuntimeContext: ...
def import_with_forced_outcome(outcome: ValidationOutcome) -> ImportLocalDatasetResult: ...
def import_with_gap_reason(reason: GapReasonCode) -> ImportLocalDatasetResult: ...
def spy_csv_request() -> DataImportRequest: ...
def spy_parquet_request() -> DataImportRequest: ...
def load_registry(root: Path) -> MarketDataRegistry: ...
def invalidate_exact_binding(binding: RegistryBinding, root: Path) -> tuple[InvalidationEvent, DataEligibility, RegistrySnapshot]: ...
def fixture_calendar() -> TradingCalendarRef: ...
def write_test_parquet(
    path: Path,
    rows: tuple[DailyBarRaw, ...],
    profile: Mapping[str, object],
) -> None: ...
def read_python_sources(relative_root: str) -> str: ...
def frozen_public_surface() -> Mapping[str, tuple[str, str]]: ...
def traceability_test_nodes() -> frozenset[str]: ...
~~~

---

### Task 1: Register V2.2A versions, dependency, capabilities, and artifact ownership

**Files:**
- Create: `src/tv_quant/data_foundation/__init__.py`
- Create: `src/tv_quant/data_foundation/contracts.py`
- Modify: `requirements.txt`
- Modify: `config/capability-registry-v2.1.json`
- Modify: `src/tv_quant/contracts/artifact_contract.py`
- Modify: `src/tv_quant/run_manifest.py`
- Modify: `src/tv_quant/research_pipeline.py`
- Test: `tests/data_foundation/test_registration.py`
- Test: `tests/contracts/test_artifact_contract.py`
- Test: `tests/contracts/test_capability_registry.py`

**Interfaces:**
- Consumes: `ArtifactOwner`, `ArtifactContract`, `ARTIFACT_OWNERS`,
  `CapabilityRegistry`, `canonical_hash`, `sha256_file`,
  `bind_artifact_hashes`, `write_data_provenance`.
- Produces: `DATA_FOUNDATION_SCHEMA_VERSION = "v2.2a"`,
  `DATA_FOUNDATION_WRITER_PROFILE_VERSION = "parquet-v1"`,
  registered capability IDs `market-data.local-csv.daily`,
  `market-data.local-parquet.daily`, `market-data.yfinance-smoke.local`,
  and versioned data artifact entries in the existing owner ledger.
- Exact compatibility signatures:

~~~python
def bind_artifact_hashes(
    manifest: Mapping[str, Any],
    artifact_paths: Mapping[str, Path],
    *,
    hashed_names: tuple[str, ...] = HASHED_ARTIFACT_NAMES,
) -> dict[str, object]: ...

def write_data_provenance(
    data_path: Path,
    source: str,
    *,
    payload: Mapping[str, object] | None = None,
) -> None: ...

def write_canonical_json_artifact(
    path: Path,
    payload: Mapping[str, Any],
) -> None: ...
~~~

- [ ] **Step 1: Write registration and backward-compatibility tests**

~~~python
def test_v22a_capabilities_start_blocked_and_existing_v21_records_coexist() -> None:
    registry = load_capability_registry(REGISTRY_PATH)
    record = registry.require("market-data.local-csv.daily", "v2.2a")
    assert record.implementation_status == "not_implemented"
    assert record.blocker_code is BlockerCode.DATA_CAPABILITY_BLOCKER
    assert registry.require("phase1.ema.daily.golden", "v2.1").formal_status == "formal_verified"

def test_extended_artifact_binding_preserves_legacy_default(tmp_path: Path) -> None:
    assert inspect.signature(bind_artifact_hashes).parameters["hashed_names"].kind.name == "KEYWORD_ONLY"
    assert ArtifactContract().owners == ARTIFACT_OWNERS
~~~

- [ ] **Step 2: Run the focused tests and verify RED**

Run:
`py -3.14 -m pytest tests/data_foundation/test_registration.py tests/contracts/test_artifact_contract.py tests/contracts/test_capability_registry.py -q`

Expected: FAIL because `tv_quant.data_foundation`, the three `v2.2a` capability
records, new artifact entries, and the backward-compatible keyword parameter do
not exist.

- [ ] **Step 3: Add the dependency and versioned owner registrations**

Add exactly `exchange-calendars==4.13.2` to `requirements.txt`. Append capability
records whose source/network semantics are:

~~~json
{
  "capability_id": "market-data.local-csv.daily",
  "version": "v2.2a",
  "implementation_status": "not_implemented",
  "supported_market": ["US_EQUITY", "US_ETF"],
  "supported_timeframes": ["1d"],
  "provider": "local",
  "required_dependencies": ["exchange-calendars", "pyarrow"],
  "formal_status": "unavailable",
  "structural_availability": "available",
  "implementation_availability": "unavailable",
  "formal_eligibility": "not_eligible",
  "smoke_only_status": "not_smoke_only",
  "blocker_code": "DATA_CAPABILITY_BLOCKER",
  "evidence": [
    "boundary:local-files-only",
    "code:data-foundation-contracts",
    "test:v22a-registration"
  ],
  "last_verified": "2026-08-02",
  "implementation_owner": "tv_quant.data_foundation.importer"
}
~~~

`market-data.local-parquet.daily` and
`market-data.yfinance-smoke.local` use the same blocked registration at Task 1.
Task 17 promotes CSV/Parquet to `formal_verified` and the smoke capability to
`not_live_verified` only after their named implementation evidence passes.

Append artifact kinds for raw source, validated candidate, validation report,
canonical component, import manifest, dataset provenance, dataset manifest,
eligibility, registry snapshot, and invalidation event. Every entry points to
an existing owner module/function; no V2.2A module becomes a hash ledger.

- [ ] **Step 4: Extend the existing bind/provenance functions without breaking old calls**

~~~python
def bind_artifact_hashes(manifest, artifact_paths, *, hashed_names=HASHED_ARTIFACT_NAMES):
    names = tuple(hashed_names)
    missing = tuple(name for name in names if name not in artifact_paths)
    if missing:
        raise ValueError(f"artifact_paths: missing {missing!r}")
    bound = dict(manifest)
    bound["artifact_paths"] = {name: str(artifact_paths[name]) for name in sorted(artifact_paths)}
    bound["artifact_hashes"] = {name: sha256_file(Path(artifact_paths[name])) for name in names}
    if "strategy_config" in artifact_paths:
        bound["strategy_config_path"] = str(artifact_paths["strategy_config"])
        bound["strategy_config_file_hash"] = sha256_file(Path(artifact_paths["strategy_config"]))
    return bound

def write_canonical_json_artifact(path, payload):
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ) + "\n",
        encoding="utf-8",
        newline="\n",
    )
~~~

`write_data_provenance` keeps its legacy payload when `payload is None`. In
typed mode it validates `schema_version == "v2.2a"`, writes sorted UTF-8 JSON,
and never computes a hash itself.
`write_canonical_json_artifact` lives in `tv_quant.run_manifest` and owns
sorted-key, UTF-8, fixed-separator JSON serialization for validation reports,
manifests, eligibilities, registry snapshots and invalidation events. V2.2A
modules assemble typed payloads and delegate every JSON write to this owner.

- [ ] **Step 5: Run GREEN and regression tests**

Run:
`py -3.14 -m pytest tests/data_foundation/test_registration.py tests/contracts/test_artifact_contract.py tests/contracts/test_capability_registry.py tests/pipeline/test_run_manifest.py -q`

Expected: PASS; old V2.1 capability and manifest tests remain unchanged.

- [ ] **Step 6: Refactor only duplicated validation into existing helpers**

Use existing `_non_empty_string` and SHA-256 validation in
`artifact_contract.py`. Do not add `hashlib`, `json` serialization ownership,
or another artifact ledger to `data_foundation`.

Run:
`py -3.14 -m pytest tests/data_foundation/test_registration.py tests/contracts/test_artifact_contract.py tests/contracts/test_capability_registry.py tests/pipeline/test_run_manifest.py -q`

Expected: PASS after refactor.

- [ ] **Step 7: Commit**

~~~powershell
git add requirements.txt config/capability-registry-v2.1.json src/tv_quant/run_manifest.py src/tv_quant/research_pipeline.py src/tv_quant/contracts/artifact_contract.py src/tv_quant/data_foundation/__init__.py src/tv_quant/data_foundation/contracts.py tests/data_foundation/test_registration.py tests/contracts/test_artifact_contract.py tests/contracts/test_capability_registry.py
git commit -m "Register V2.2A data foundation contracts and owners."
~~~

### Task 2: Define immutable data contracts and isolate runtime capability

**Files:**
- Create: `tests/data_foundation/test_contracts.py`
- Modify: `src/tv_quant/data_foundation/contracts.py`
- Modify: `src/tv_quant/data_foundation/__init__.py`
- Test: `tests/data_foundation/test_contracts.py`

**Interfaces:**
- Consumes: `canonical_decimal(value, path)`, `canonical_integer(value, path)`,
  `BlockerCode`, `PipelineStatus`, `Path`, `Callable`, `datetime`, `UUID`.
- Produces: every enum and dataclass in Sections 3.1-3.3 except
  `DatasetIdentity`, `DatasetProvenance`, `CanonicalDatasetManifest`,
  `RegistryBinding` and `RegistrySnapshot`, which are completed in later tasks.
- Exact helpers:

~~~python
def freeze_mapping(value: Mapping[str, object], path: str) -> Mapping[str, object]: ...
def validate_sha256(value: object, path: str) -> str: ...
def validate_iso_date(value: object, path: str) -> str: ...
def validate_utc_timestamp(value: object, path: str) -> str: ...
def request_payload(request: DataImportRequest) -> Mapping[str, object]: ...
~~~

- [ ] **Step 1: Write failing immutability, exact-enum, and runtime-isolation tests**

~~~python
def test_runtime_root_is_not_serializable_or_hashable(tmp_path: Path) -> None:
    request = valid_request(source_relative_path="incoming/spy.csv")
    runtime = DataImportRuntimeContext(tmp_path, "path-v2.2a", utc_clock, uuid_factory)
    payload = request_payload(request)
    assert "data_root" not in payload
    assert str(tmp_path) not in repr(payload)
    with pytest.raises(TypeError, match="runtime context is not persistable"):
        dataclass_payload(runtime)

@pytest.mark.parametrize("state", ["BLOCKED", "INCOMPLETE", "NOT_IMPLEMENTED"])
def test_data_eligibility_rejects_operation_outcomes(state: str) -> None:
    with pytest.raises(ValueError, match="DataEligibilityState"):
        DataEligibility(state=state, **valid_eligibility_fields())
~~~

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_contracts.py -q`

Expected: FAIL because the concrete V2.2A records, deep-freeze validation,
cross-field invariants, and runtime serialization rejection are absent.

- [ ] **Step 3: Implement exact immutable record validation**

~~~python
def request_payload(request: DataImportRequest) -> Mapping[str, object]:
    if request.source_type is MarketDataSourceType.YFINANCE_SMOKE:
        if request.smoke_only is not True:
            raise ValueError("smoke_only: YFINANCE_SMOKE requires true")
    elif request.smoke_only is not False:
        raise ValueError("smoke_only: formal local source requires false")
    if (request.csv_profile is None) == (request.parquet_profile is None):
        raise ValueError("parser profile: exactly one profile required")
    return freeze_mapping({
        "request_schema_version": request.request_schema_version,
        "source_type": request.source_type.value,
        "source_relative_path": request.source_relative_path,
        "source_name": request.source_name,
        "instrument_id": request.instrument_id,
        "symbol": request.symbol,
        "exchange": request.exchange,
        "currency": request.currency,
        "parser_profile": asdict(request.csv_profile or request.parquet_profile),
        "calendar_ref_relative_path": request.calendar_ref_relative_path,
        "declared_timezone": request.declared_timezone,
        "gap_evidence_relative_paths": request.gap_evidence_relative_paths,
        "corporate_action_evidence_relative_paths":
            request.corporate_action_evidence_relative_paths,
        "adjustment_method": request.adjustment_method,
        "smoke_only": request.smoke_only,
    }, "request")
~~~

Every record validates exact enum instances, UTC `Z` timestamps, uppercase
symbol/MIC, `America/New_York`, sorted unique tuples, canonical numeric strings,
hash syntax, non-negative counts, and mutually required optional fields.
`DataImportRuntimeContext.__reduce_ex__` raises
`TypeError("runtime context is not persistable")`.

- [ ] **Step 4: Run GREEN and frozen-interface regression**

Run:
`py -3.14 -m pytest tests/data_foundation/test_contracts.py tests/contracts/test_frozen_public_interfaces.py -q`

Expected: PASS; all old public symbols resolve to the same objects.

- [ ] **Step 5: Refactor record validators without relaxing exact-field checks**

Move only scalar checks into `validate_sha256`, `validate_iso_date` and
`validate_utc_timestamp`. Keep cross-field invariants in each
`__post_init__` so error messages retain the field path.

- [ ] **Step 6: Run related numeric and status regression**

Run:
`py -3.14 -m pytest tests/data_foundation/test_contracts.py tests/contracts/test_numeric_canonicalization.py tests/contracts/test_status_codes.py -q`

Expected: PASS with existing decimal and status semantics unchanged.

- [ ] **Step 7: Commit**

~~~powershell
git add src/tv_quant/data_foundation/contracts.py src/tv_quant/data_foundation/__init__.py tests/data_foundation/test_contracts.py
git commit -m "Define immutable V2.2A data contracts."
~~~

### Task 3: Freeze semantic identity and lineage projections

**Files:**
- Create: `src/tv_quant/data_foundation/projections.py`
- Create: `tests/data_foundation/test_projections.py`
- Modify: `src/tv_quant/data_foundation/__init__.py`
- Test: `tests/data_foundation/test_projections.py`

**Interfaces:**
- Consumes: core records from Task 2, `canonical_hash`, and the exact matrix in
  Section 4.
- Produces: all `*_semantic_payload` functions in Section 3.3,
  `logical_component_hash`, `DatasetIdentity`, `build_dataset_identity`,
  `gap_evidence_lineage_payload`, `corporate_action_evidence_lineage_payload`,
  and `provenance_payload`.
- Exact bundle hash signature:

~~~python
def bundle_content_payload(
    component_logical_hashes: Mapping[str, Sha256Hex],
    gap_semantic_coverage_hash: Sha256Hex,
    corporate_action_semantic_coverage_hash: Sha256Hex,
) -> Mapping[str, object]: ...
~~~

- [ ] **Step 1: Write RED tests for every identity/lineage exclusion**

~~~python
def test_source_row_ref_change_does_not_change_dataset_id() -> None:
    first = bundle_with(raw_bars=(raw_bar(source_row_ref="csv:2"),))
    second = bundle_with(raw_bars=(raw_bar(source_row_ref="parquet:0"),))
    assert build_dataset_identity(first).dataset_id == build_dataset_identity(second).dataset_id

def test_lineage_change_with_same_semantics_keeps_dataset_id() -> None:
    left = bundle_with(gap_evidence=gap_evidence(source_name="provider-a"))
    right = bundle_with(gap_evidence=gap_evidence(source_name="provider-b"))
    assert left.gap_evidence.evidence_hash != right.gap_evidence.evidence_hash
    assert build_dataset_identity(left).dataset_id == build_dataset_identity(right).dataset_id
~~~

Also parameterize import timestamp, original file hash, source type, writer
profile, compression, row-group, evidence ID/hash, and filesystem path.

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_projections.py -q`

Expected: FAIL because projection functions and `DatasetIdentity` derivation do
not exist.

- [ ] **Step 3: Implement explicit allow-list projections**

~~~python
def daily_bar_semantic_payload(bar: DailyBarRaw) -> Mapping[str, object]:
    return {
        "instrument_id": bar.instrument_id,
        "symbol": bar.symbol,
        "exchange": bar.exchange,
        "trading_date": bar.trading_date,
        "session_open_utc": bar.session_open_utc,
        "session_close_utc": bar.session_close_utc,
        "timezone": bar.timezone,
        "currency": bar.currency,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "volume_status": bar.volume_status.value,
    }

def build_dataset_identity(bundle: LogicalDatasetBundle) -> DatasetIdentity:
    hashes = component_hashes(bundle)
    content_hash = canonical_hash(bundle_content_payload(
        hashes,
        bundle.gap_evidence.semantic_coverage_hash,
        bundle.corporate_action_evidence.semantic_coverage_hash,
    ))
    payload = {
        "identity_schema_version": "v2.2a",
        "dataset_kind": "US_EQUITY_ETF_DAILY_OHLCV",
        "content_hash": content_hash,
        "semantic_dependency_hashes": sorted(bundle.semantic_dependency_hashes),
    }
    return DatasetIdentity(dataset_id=canonical_hash(payload), **payload)
~~~

No projection uses `asdict` on an identity-bearing record; every field is
allow-listed so lineage additions cannot silently alter identity.

- [ ] **Step 4: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_projections.py -q`

Expected: PASS for identity invariance and logical-change sensitivity.

- [ ] **Step 5: Refactor shared stable sorting only**

Add `stable_row_key(record) -> tuple[str, str, str, str]` and
`sorted_payloads(records, projector)`. Reject duplicate sort keys before
hashing; do not deduplicate in projection code.

- [ ] **Step 6: Run hash-owner regression**

Run:
`py -3.14 -m pytest tests/data_foundation/test_projections.py tests/pipeline/test_run_manifest.py tests/contracts/test_artifact_contract.py -q`

Expected: PASS; inspection tests prove no `hashlib` or local SHA implementation
exists in `data_foundation`.

- [ ] **Step 7: Commit**

~~~powershell
git add src/tv_quant/data_foundation/projections.py src/tv_quant/data_foundation/__init__.py tests/data_foundation/test_projections.py
git commit -m "Freeze V2.2A semantic and lineage projections."
~~~

### Task 4: Implement strict CSV and Parquet parser profiles

**Files:**
- Create: `src/tv_quant/data_foundation/parsers.py`
- Create: `tests/data_foundation/test_parsers.py`
- Create: `tests/fixtures/data_foundation/valid-spy.csv`
- Modify: `src/tv_quant/data_foundation/__init__.py`
- Test: `tests/data_foundation/test_parsers.py`

**Interfaces:**
- Consumes: `DataImportRequest`, `CsvParserProfile`,
  `ParquetParserProfile`, `TradingCalendarRef`, canonical numeric owners.
- Produces: `parse_csv_source`, `parse_parquet_source` and:

~~~python
def normalize_source_row(
    raw: Mapping[str, object],
    *,
    row_ref: str,
    request: DataImportRequest,
    calendar_ref: TradingCalendarRef,
) -> DailyBarRaw: ...
~~~

- [ ] **Step 1: Write strict parser and equivalence tests**

~~~python
def test_csv_and_parquet_normalize_to_same_rows(tmp_path: Path) -> None:
    csv_rows = parse_csv_source(FIXTURES / "valid-spy.csv", csv_request(), calendar())
    parquet_path = write_equivalent_parquet(tmp_path, csv_rows)
    parquet_rows = parse_parquet_source(parquet_path, parquet_request(), calendar())
    assert tuple(map(daily_bar_semantic_payload, csv_rows)) == tuple(
        map(daily_bar_semantic_payload, parquet_rows)
    )
    assert logical_component_hash(tuple(map(daily_bar_semantic_payload, csv_rows))) == (
        logical_component_hash(tuple(map(daily_bar_semantic_payload, parquet_rows)))
    )
~~~

Add cases for unknown column, missing required column, invalid UTF-8, non-ISO
date, locale decimal, boolean volume, NaN/Infinity, null price, schema
fingerprint mismatch, Arrow type mismatch, timezone metadata, and ignored
columns declared in the request hash.

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_parsers.py -q`

Expected: FAIL because parser adapters and the fixture do not exist.

- [ ] **Step 3: Implement CSV parsing with Python `csv` and exact profile checks**

~~~python
with source_path.open("r", encoding=profile.encoding, newline="") as handle:
    reader = csv.DictReader(handle, delimiter=profile.delimiter, strict=True)
    require_exact_columns(reader.fieldnames, profile)
    rows = tuple(
        normalize_source_row(row, row_ref=f"csv:{index + 2}",
                             request=request, calendar_ref=calendar_ref)
        for index, row in enumerate(reader)
    )
return tuple(sorted(rows, key=stable_row_key))
~~~

Reject whitespace-only values and scientific special values before numeric
canonicalization. Exact ISO date parsing uses
`datetime.strptime(value, "%Y-%m-%d").date().isoformat() == value`.

- [ ] **Step 4: Implement Parquet schema validation and logical normalization**

~~~python
table = pq.read_table(source_path)
actual_fingerprint = canonical_hash(arrow_schema_payload(table.schema))
if actual_fingerprint != profile.arrow_schema_fingerprint:
    raise DataFoundationError(BlockerCode.DATA_VALIDATION_BLOCKER, "PARQUET_SCHEMA_MISMATCH")
require_arrow_types(table.schema, expected_arrow_fields())
return tuple(sorted(
    (normalize_source_row(row, row_ref=f"parquet:{index}",
                          request=request, calendar_ref=calendar_ref)
     for index, row in enumerate(table.to_pylist())),
    key=stable_row_key,
))
~~~

Do not trust the file extension. Reject unsupported dictionary/timezone/null
metadata unless the profile explicitly fixes their interpretation.

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_parsers.py -q`

Expected: PASS; CSV/Parquet logical rows and hashes match.

- [ ] **Step 6: Refactor shared row decoding, then run targeted and data-quality regression**

Make `parse_csv_source` and `parse_parquet_source` delegate only to the shared
`normalize_source_row`; keep adapter-specific file/schema checks in their own
functions.

Run:
`py -3.14 -m pytest tests/data_foundation/test_parsers.py tests/contracts/test_numeric_canonicalization.py tests/test_data_quality.py -q`

Expected: PASS; no parser silently coerces invalid numeric inputs.

- [ ] **Step 7: Commit**

~~~powershell
git add src/tv_quant/data_foundation/parsers.py src/tv_quant/data_foundation/__init__.py tests/data_foundation/test_parsers.py tests/fixtures/data_foundation/valid-spy.csv
git commit -m "Add strict local CSV and Parquet parsing."
~~~

### Task 5: Materialize and validate frozen XNYS calendar snapshots

**Files:**
- Create: `src/tv_quant/data_foundation/calendar.py`
- Create: `tests/data_foundation/test_calendar.py`
- Create: `tests/fixtures/data_foundation/calendar-xnys-2024.json`
- Modify: `src/tv_quant/data_foundation/__init__.py`
- Test: `tests/data_foundation/test_calendar.py`

**Interfaces:**
- Consumes: `exchange_calendars.get_calendar("XNYS")`,
  `TradingCalendarRef`, `CalendarSession`, `canonical_hash`, `sha256_file`.
- Produces: `materialize_xnys_snapshot`, `load_calendar_snapshot` and:

~~~python
def calendar_payload(ref: TradingCalendarRef) -> Mapping[str, object]: ...
def session_for_date(ref: TradingCalendarRef, trading_date: IsoDate) -> CalendarSession: ...
def expected_sessions(
    ref: TradingCalendarRef,
    start: IsoDate,
    end: IsoDate,
) -> tuple[CalendarSession, ...]: ...
~~~

- [ ] **Step 1: Write holiday, half-day, DST, coverage, and hash tests**

~~~python
def test_xnys_half_day_and_dst_sessions_are_frozen() -> None:
    ref = load_calendar_snapshot(FIXTURES / "calendar-xnys-2024.json")
    assert session_for_date(ref, "2024-11-29").session_close_utc == "2024-11-29T18:00:00Z"
    assert session_for_date(ref, "2024-03-08").session_open_utc == "2024-03-08T14:30:00Z"
    assert session_for_date(ref, "2024-03-11").session_open_utc == "2024-03-11T13:30:00Z"
    assert all(s.trading_date != "2024-07-04" for s in ref.sessions)
~~~

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_calendar.py -q`

Expected: FAIL because the snapshot contract loader and fixture are absent.

- [ ] **Step 3: Implement deterministic offline snapshot materialization**

~~~python
calendar = exchange_calendars.get_calendar("XNYS")
schedule = calendar.schedule.loc[coverage_start:coverage_end]
sessions = tuple(
    CalendarSession(
        trading_date=index.date().isoformat(),
        session_open_utc=utc_z(row["open"]),
        session_close_utc=utc_z(row["close"]),
        is_half_day=(row["close"].tz_convert("America/New_York").time()
                     < time(16, 0)),
    )
    for index, row in schedule.iterrows()
)
payload = snapshot_payload_without_hash(sessions)
return TradingCalendarRef(calendar_hash=canonical_hash(payload), sessions=sessions, **metadata)
~~~

The materializer is an implementation/build-time function. Import orchestration
loads a contained local JSON snapshot and never calls `exchange_calendars`.

- [ ] **Step 4: Implement fail-closed snapshot loading**

Load UTF-8 JSON with exact keys, rebuild every session, verify strict ascending
dates, UTC `Z` timestamps, `calendar_id == "XNYS"`,
`timezone == "America/New_York"`, full requested coverage, and exact
`calendar_hash`. A missing or mismatched snapshot maps to
`DATA_CAPABILITY_BLOCKER` or `DATA_VALIDATION_BLOCKER`.

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_calendar.py -q`

Expected: PASS with exact half-day and DST UTC values.

- [ ] **Step 6: Refactor snapshot conversion, then prove import-time code cannot refresh it**

Extract `schedule_row_to_session(index, row) -> CalendarSession` without moving
calendar hash ownership. Add an inspection test asserting `importer.py` imports only
`load_calendar_snapshot`, and monkeypatch
`exchange_calendars.get_calendar` to raise during import tests.

Run:
`py -3.14 -m pytest tests/data_foundation/test_calendar.py -q`

Expected: PASS without network or calendar refresh.

- [ ] **Step 7: Commit**

~~~powershell
git add src/tv_quant/data_foundation/calendar.py src/tv_quant/data_foundation/__init__.py tests/data_foundation/test_calendar.py tests/fixtures/data_foundation/calendar-xnys-2024.json
git commit -m "Freeze XNYS calendar and UTC session semantics."
~~~

### Task 6: Define daily gaps, evidence coverage, and validation records

**Files:**
- Create: `src/tv_quant/data_foundation/validation.py`
- Create: `tests/data_foundation/test_gap_evidence.py`
- Create: `tests/fixtures/data_foundation/no-gaps-evidence.json`
- Create: `tests/fixtures/data_foundation/gap-evidence.json`
- Modify: `src/tv_quant/data_foundation/__init__.py`
- Test: `tests/data_foundation/test_gap_evidence.py`

**Interfaces:**
- Consumes: `DailyBarRaw`, `DailyGapRecord`, `GapEvidence`,
  `TradingCalendarRef`, `canonical_hash`.
- Produces:

~~~python
def build_daily_gap(
    instrument_id: str,
    symbol: str,
    exchange: str,
    trading_date: IsoDate,
    reason: GapReasonCode,
    calendar_ref: TradingCalendarRef,
    semantic_ref: str,
) -> DailyGapRecord: ...

def validate_gap_coverage(
    raw_bars: tuple[DailyBarRaw, ...],
    gaps: tuple[DailyGapRecord, ...],
    evidence: GapEvidence,
    calendar_ref: TradingCalendarRef,
) -> tuple[DataValidationIssue, ...]: ...

def validation_report_payload(report: DataValidationReport) -> Mapping[str, object]: ...
~~~

- [ ] **Step 1: Write tests for all frozen gap reasons and empty coverage**

~~~python
@pytest.mark.parametrize("reason", [
    GapReasonCode.PRE_IPO,
    GapReasonCode.POST_DELISTING,
    GapReasonCode.HALT,
    GapReasonCode.EXCHANGE_NO_TRADING,
])
def test_allowed_semantic_gap_requires_reason_specific_ref(reason: GapReasonCode) -> None:
    gap = daily_gap(reason=reason, semantic_ref="")
    with pytest.raises(ValueError, match="semantic_ref"):
        validate_gap_coverage((), (gap,), gaps_present_evidence(gap), calendar())

def test_no_gaps_requires_explicit_complete_evidence() -> None:
    issues = validate_gap_coverage(full_bars(), (), no_gaps_evidence(), calendar())
    assert issues == ()

@pytest.mark.parametrize("reason", [
    GapReasonCode.PRE_IPO,
    GapReasonCode.POST_DELISTING,
    GapReasonCode.HALT,
    GapReasonCode.EXCHANGE_NO_TRADING,
])
def test_allowed_gap_reason_with_evidence_is_valid(reason: GapReasonCode) -> None:
    gap = daily_gap(reason=reason, semantic_ref=valid_semantic_ref(reason))
    assert validate_gap_coverage((), (gap,), gaps_present_evidence(gap), calendar()) == ()
~~~

Add explicit tests showing `SOURCE_MISSING` returns `BLOCKED`,
`SOURCE_INCOMPLETE` returns `INCOMPLETE`, and neither enters canonical gaps.

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_gap_evidence.py -q`

Expected: FAIL because gap construction and coverage partitioning do not exist.

- [ ] **Step 3: Implement semantic gap IDs and exact partitioning**

~~~python
expected = {session.trading_date for session in expected_sessions(calendar_ref, start, end)}
bar_dates = {bar.trading_date for bar in raw_bars}
gap_dates = {gap.trading_date for gap in gaps}
if bar_dates & gap_dates:
    issues.append(issue("BAR_GAP_OVERLAP", blocking=True, ...))
if expected != bar_dates | gap_dates:
    issues.append(issue("COVERAGE_NOT_PARTITIONED", blocking=True, ...))
if evidence.coverage_state is GapCoverageState.NO_GAPS_IN_RANGE and gaps:
    issues.append(issue("NO_GAPS_WITH_NONEMPTY_SET", blocking=True, ...))
~~~

`gap_id` hashes the semantic payload without `gap_id` or provider/import fields.
`GapEvidence.semantic_coverage_hash` hashes listing/range/state/calendar and
ordered gap semantic payloads. `evidence_id/hash` hash the full lineage payload.

- [ ] **Step 4: Implement deterministic issue/report ordering**

Sort issues by
`(blocking desc, category, issue_code, stable_key or (), field or "",
source_row_ref or "")`. Compute `report_id/hash` from the payload excluding
their own fields. Map every blocking issue to an existing `BlockerCode`.

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_gap_evidence.py -q`

Expected: PASS for all six reason codes, `GAPS_PRESENT`,
`NO_GAPS_IN_RANGE`, overlap, missing date, duplicate gap, range and count
failures.

- [ ] **Step 6: Refactor issue ordering, then run calendar/projection regression**

Use one `ordered_issues` function for gap and report ordering; keep semantic and
lineage projectors separate.

Run:
`py -3.14 -m pytest tests/data_foundation/test_gap_evidence.py tests/data_foundation/test_calendar.py tests/data_foundation/test_projections.py -q`

Expected: PASS; evidence lineage changes do not alter semantic coverage.

- [ ] **Step 7: Commit**

~~~powershell
git add src/tv_quant/data_foundation/validation.py src/tv_quant/data_foundation/__init__.py tests/data_foundation/test_gap_evidence.py tests/fixtures/data_foundation/no-gaps-evidence.json tests/fixtures/data_foundation/gap-evidence.json
git commit -m "Add typed daily gap and evidence coverage."
~~~

### Task 7: Validate corporate-action evidence and derive deterministic adjustments

**Files:**
- Create: `src/tv_quant/data_foundation/adjustments.py`
- Create: `tests/data_foundation/test_adjustments.py`
- Create: `tests/fixtures/data_foundation/no-actions-evidence.json`
- Create: `tests/fixtures/data_foundation/split-evidence.json`
- Modify: `src/tv_quant/data_foundation/__init__.py`
- Test: `tests/data_foundation/test_adjustments.py`

**Interfaces:**
- Consumes: `CorporateActionEvent`, `CorporateActionEvidence`,
  `AdjustmentFactor`, `DailyBarRaw`, `DailyBarAdjusted`,
  `canonical_decimal`, `canonical_hash`.
- Produces: `derive_adjustment_factors`, `apply_adjustments` and:

~~~python
ADJUSTMENT_METHODS: Mapping[str, AdjustmentMethodDefinition]

@dataclass(frozen=True, slots=True)
class AdjustmentMethodDefinition:
    method_id: str
    version: str
    decimal_quantum: str

def validate_corporate_action_coverage(
    events: tuple[CorporateActionEvent, ...],
    evidence: CorporateActionEvidence,
    calendar_ref: TradingCalendarRef,
) -> tuple[DataValidationIssue, ...]: ...
~~~

- [ ] **Step 1: Write RED tests for event types, coverage, identity factor, and formulas**

~~~python
def test_evidence_lineage_does_not_change_factor_identity() -> None:
    left = derive_adjustment_factors(events(), evidence(source_name="a"), "split-dividend-v1")
    right = derive_adjustment_factors(events(), evidence(source_name="b"), "split-dividend-v1")
    assert tuple(f.adjustment_factor_id for f in left) == tuple(
        f.adjustment_factor_id for f in right
    )
    assert left[0].corporate_action_evidence_hash != right[0].corporate_action_evidence_hash

def test_no_actions_range_produces_identity_factor() -> None:
    factors = derive_adjustment_factors((), no_actions_evidence(), "split-dividend-v1")
    assert factors == (identity_factor(price="1", volume="1"),)
~~~

Add split direction, cash-dividend method, bad dates, missing currency, source
event ref mismatch, duplicate conflicting event ID, unsupported method, adjusted
OHLC rules, and adjusted-only input rejection.

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_adjustments.py -q`

Expected: FAIL because action coverage and adjustment methods do not exist.

- [ ] **Step 3: Implement source-independent event and coverage identities**

`event_id` hashes event type, stable listing identity, ex/effective dates and
type-specific numeric fields. `semantic_coverage_hash` hashes listing, range,
calendar, state and ordered event IDs. Full evidence hash additionally includes
provider/original-file/source-event refs. Reject event sets that do not match
`EVENTS_PRESENT` or `NO_ACTIONS_IN_RANGE`.

~~~python
event_payload = corporate_action_event_payload(event)
event_id = canonical_hash(event_payload)
semantic_payload = {
    "instrument_id": evidence.instrument_id,
    "symbol": evidence.symbol,
    "exchange": evidence.exchange,
    "coverage_start": evidence.coverage_start,
    "coverage_end": evidence.coverage_end,
    "coverage_state": evidence.coverage_state.value,
    "calendar_id": evidence.calendar_id,
    "calendar_hash": evidence.calendar_hash,
    "event_ids": tuple(sorted(event.event_id for event in events)),
}
semantic_coverage_hash = canonical_hash(semantic_payload)
~~~

- [ ] **Step 4: Implement fixed factor and adjustment formulas**

~~~python
def apply_one(bar: DailyBarRaw, factor: AdjustmentFactor) -> DailyBarAdjusted:
    return DailyBarAdjusted(
        instrument_id=bar.instrument_id,
        symbol=bar.symbol,
        exchange=bar.exchange,
        trading_date=bar.trading_date,
        session_open_utc=bar.session_open_utc,
        session_close_utc=bar.session_close_utc,
        timezone=bar.timezone,
        currency=bar.currency,
        adjustment_factor_id=factor.adjustment_factor_id,
        adjustment_method=factor.adjustment_method,
        adjusted_open=mul_price(bar.open, factor.price_factor),
        adjusted_high=mul_price(bar.high, factor.price_factor),
        adjusted_low=mul_price(bar.low, factor.price_factor),
        adjusted_close=mul_price(bar.close, factor.price_factor),
        adjusted_volume=mul_volume(bar.volume, factor.volume_factor),
    )
~~~

`mul_price` and `mul_volume` use `Decimal` only internally and serialize through
`canonical_decimal`/`canonical_integer`. SPLIT fixes reciprocal price and direct
volume direction in `split-dividend-v1`. Cash dividends use only explicit local
event values and the method's frozen formula/version.

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_adjustments.py -q`

Expected: PASS; raw bars remain byte-for-byte/dataclass-equal before and after.

- [ ] **Step 6: Refactor factor lookup, then run numeric, projection, and gap regression**

Extract `factor_for_trading_date(factors, trading_date) -> AdjustmentFactor`
with an explicit effective-date tie-break and no filesystem/provider inputs.

Run:
`py -3.14 -m pytest tests/data_foundation/test_adjustments.py tests/data_foundation/test_projections.py tests/data_foundation/test_gap_evidence.py tests/contracts/test_numeric_canonicalization.py -q`

Expected: PASS with evidence lineage excluded from factor/dataset identities.

- [ ] **Step 7: Commit**

~~~powershell
git add src/tv_quant/data_foundation/adjustments.py src/tv_quant/data_foundation/__init__.py tests/data_foundation/test_adjustments.py tests/fixtures/data_foundation/no-actions-evidence.json tests/fixtures/data_foundation/split-evidence.json
git commit -m "Add deterministic corporate-action adjustments."
~~~

### Task 8: Implement fail-closed daily dataset validation

**Files:**
- Create: `tests/data_foundation/test_validation.py`
- Modify: `src/tv_quant/data_foundation/validation.py`
- Modify: `src/tv_quant/data_foundation/__init__.py`
- Test: `tests/data_foundation/test_validation.py`

**Interfaces:**
- Consumes: `NormalizedDatasetCandidate`, gap validation from Task 6,
  action validation from Task 7, canonical numeric owners.
- Produces: `validate_daily_dataset(candidate) -> DataValidationReport` and:

~~~python
VALIDATION_CHECK_ORDER = (
    "schema", "sorting", "duplicates", "calendar", "sessions", "ohlcv",
    "volume", "gaps", "corporate_actions", "adjustment_inputs",
    "provenance_candidate", "hashes",
)

def deduplicate_identical_rows(
    rows: tuple[DailyBarRaw, ...],
) -> tuple[tuple[DailyBarRaw, ...], tuple[DataValidationIssue, ...]]: ...
~~~

- [ ] **Step 1: Write RED tests for every blocking quality rule**

~~~python
@pytest.mark.parametrize(("field", "value"), [
    ("open", "0"), ("high", "-1"), ("low", "NaN"), ("close", "Infinity"),
])
def test_nonpositive_or_nonfinite_price_blocks(field: str, value: str) -> None:
    report = validate_daily_dataset(candidate_with(**{field: value}))
    assert report.validation_status is ValidationOutcome.BLOCKED
    assert BlockerCode.DATA_VALIDATION_BLOCKER in report.blocker_codes

def test_identical_duplicate_is_audited_but_conflict_blocks() -> None:
    deduped, issues = deduplicate_identical_rows((bar(), bar()))
    assert len(deduped) == 1
    assert issues[0].issue_code == "DEDUPLICATED_IDENTICAL"
    assert validate_daily_dataset(candidate_with(conflicting_rows())).validation_status is ValidationOutcome.BLOCKED
~~~

Cover all OHLC inequalities, negative/boolean/null volume, row order, duplicate,
conflict, non-session row, session UTC mismatch, half-day mismatch, gap
partition, action coverage, factor prerequisites, source missing/incomplete and
unsupported versions.

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_validation.py -q`

Expected: FAIL because complete validation order and outcome aggregation are
absent.

- [ ] **Step 3: Implement deterministic checks without repair**

~~~python
def validate_daily_dataset(candidate: NormalizedDatasetCandidate) -> DataValidationReport:
    issues: list[DataValidationIssue] = []
    rows, duplicate_issues = deduplicate_identical_rows(candidate.raw_bars)
    issues.extend(duplicate_issues)
    issues.extend(validate_order_and_unique_keys(rows))
    issues.extend(validate_sessions(rows, candidate.calendar_ref))
    issues.extend(validate_ohlcv(rows))
    issues.extend(validate_gap_coverage(
        rows, candidate.daily_gaps, candidate.gap_evidence, candidate.calendar_ref
    ))
    issues.extend(validate_corporate_action_coverage(
        candidate.corporate_action_events,
        candidate.corporate_action_evidence,
        candidate.calendar_ref,
    ))
    return build_validation_report(candidate, ordered_issues(issues))
~~~

Do not fill, interpolate, select a conflicting winner, convert null volume to
zero, or downgrade a blocking issue.

- [ ] **Step 4: Derive outcome and status metadata**

If any `SOURCE_MISSING` issue exists, outcome is `BLOCKED`. If no blocker but
`SOURCE_INCOMPLETE` or explained missing volume exists, outcome is
`INCOMPLETE`. Unsupported capability produces `NOT_IMPLEMENTED`. Only an empty
blocking set with complete checks produces `VALID`. Map report outcome to V2.1
operation status exactly as `VALID -> SUCCESS`, `BLOCKED -> BLOCKED`,
`INCOMPLETE -> BLOCKED + DATA_VALIDATION_BLOCKER` and
`NOT_IMPLEMENTED -> NOT_IMPLEMENTED + DATA_CAPABILITY_BLOCKER`. Populate
recoverable/retryable/terminal/user-action metadata through
`status_definition(blocker_code)`.

~~~python
OPERATION_STATUS_BY_OUTCOME = {
    ValidationOutcome.VALID: (PipelineStatus.SUCCESS, None),
    ValidationOutcome.BLOCKED:
        (PipelineStatus.BLOCKED, BlockerCode.DATA_VALIDATION_BLOCKER),
    ValidationOutcome.INCOMPLETE:
        (PipelineStatus.BLOCKED, BlockerCode.DATA_VALIDATION_BLOCKER),
    ValidationOutcome.NOT_IMPLEMENTED:
        (PipelineStatus.NOT_IMPLEMENTED, BlockerCode.DATA_CAPABILITY_BLOCKER),
}
~~~

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_validation.py -q`

Expected: PASS with stable issue/report hashes under input order changes.

- [ ] **Step 6: Refactor check aggregation, then run targeted and related contract tests**

Replace repeated issue extension with
`run_check(name, callable) -> tuple[DataValidationIssue, ...]` while preserving
`VALIDATION_CHECK_ORDER` and exact issue sorting.

Run: `py -3.14 -m pytest tests/data_foundation/test_contracts.py tests/data_foundation/test_parsers.py tests/data_foundation/test_calendar.py tests/data_foundation/test_gap_evidence.py tests/data_foundation/test_adjustments.py tests/data_foundation/test_validation.py -q`

Expected: PASS; every design validation criterion maps to a named test.

- [ ] **Step 7: Commit**

~~~powershell
git add src/tv_quant/data_foundation/validation.py src/tv_quant/data_foundation/__init__.py tests/data_foundation/test_validation.py
git commit -m "Implement fail-closed daily dataset validation."
~~~

### Task 9: Finalize logical component hashes and dataset identity gates

**Files:**
- Create: `tests/data_foundation/test_identity.py`
- Modify: `src/tv_quant/data_foundation/projections.py`
- Modify: `src/tv_quant/data_foundation/contracts.py`
- Test: `tests/data_foundation/test_identity.py`

**Interfaces:**
- Consumes: `LogicalDatasetBundle`, semantic projectors, `canonical_hash`.
- Produces:

~~~python
CANONICAL_COMPONENT_NAMES = (
    "daily-bar-raw",
    "daily-gaps",
    "gap-evidence-semantic",
    "corporate-action-events",
    "corporate-action-evidence-semantic",
    "adjustment-factors",
    "daily-bar-adjusted",
)

def component_logical_hashes(
    bundle: LogicalDatasetBundle,
) -> Mapping[str, Sha256Hex]: ...

def verify_identity_claim(
    claimed: DatasetIdentity,
    bundle: LogicalDatasetBundle,
) -> None: ...
~~~

- [ ] **Step 1: Write identity sensitivity and collision tests**

~~~python
def test_logical_value_change_changes_dataset_id() -> None:
    assert build_dataset_identity(bundle(close="100")).dataset_id != (
        build_dataset_identity(bundle(close="101")).dataset_id
    )

def test_identity_collision_claim_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_manifest, "canonical_hash", deterministic_collision)
    with pytest.raises(DataFoundationError, match="IDENTITY_COLLISION"):
        verify_identity_claim(identity_for(bundle(close="100")), bundle(close="101"))
~~~

Parameterize gap set, semantic coverage, event set, factor, adjustment method,
calendar, timezone policy and logical schema changes.

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_identity.py -q`

Expected: FAIL because complete component mapping and claim verification are
absent.

- [ ] **Step 3: Implement complete component hashing**

Hash fixed component names, fixed logical column order, canonical nulls, and
stable-key-sorted rows. `daily-gaps` hashes an empty tuple using its explicit
schema payload; it is never omitted. The bundle `content_hash` includes both
semantic coverage hashes but excludes full evidence lineage.

~~~python
def component_logical_hashes(bundle):
    return MappingProxyType({
        "daily-bar-raw": logical_component_hash(project_raw(bundle.raw_bars)),
        "daily-gaps": logical_component_hash(project_gaps(bundle.daily_gaps)),
        "gap-evidence-semantic": bundle.gap_evidence.semantic_coverage_hash,
        "corporate-action-events":
            logical_component_hash(project_events(bundle.corporate_action_events)),
        "corporate-action-evidence-semantic":
            bundle.corporate_action_evidence.semantic_coverage_hash,
        "adjustment-factors":
            logical_component_hash(project_factors(bundle.adjustment_factors)),
        "daily-bar-adjusted":
            logical_component_hash(project_adjusted(bundle.adjusted_bars)),
    })
~~~

- [ ] **Step 4: Implement two-stage collision verification**

`verify_identity_claim` first compares the recomputed content/dependency
payload, then compares the claimed ID. If the same `dataset_id` is associated
with any different identity-bearing payload, raise
`DataFoundationError(DATA_VALIDATION_BLOCKER, "IDENTITY_COLLISION")` before
publication.

- [ ] **Step 5: Run focused GREEN**

Run:
`py -3.14 -m pytest tests/data_foundation/test_identity.py tests/data_foundation/test_projections.py -q`

Expected: PASS for all included/excluded field cases.

- [ ] **Step 6: Refactor component dispatch, then run regression and inspect hash ownership**

Use an immutable mapping from component name to projector; do not use dynamic
reflection or `asdict`.

Run:
`py -3.14 -m pytest tests/data_foundation/test_identity.py tests/data_foundation/test_projections.py -q`

Expected: PASS.

Run:
`rg -n "hashlib|def sha256|def canonical_hash" src/tv_quant/data_foundation`

Expected: no matches.

- [ ] **Step 7: Commit**

~~~powershell
git add src/tv_quant/data_foundation/projections.py src/tv_quant/data_foundation/contracts.py tests/data_foundation/test_identity.py
git commit -m "Finalize V2.2A logical dataset identity."
~~~

### Task 10: Publish deterministic immutable canonical artifacts and manifests

**Files:**
- Create: `src/tv_quant/data_foundation/artifacts.py`
- Create: `tests/data_foundation/test_artifacts.py`
- Modify: `src/tv_quant/data_foundation/__init__.py`
- Modify: `src/tv_quant/research_pipeline.py`
- Test: `tests/data_foundation/test_artifacts.py`

**Interfaces:**
- Consumes: `DatasetIdentity`, `LogicalDatasetBundle`,
  `DatasetProvenance`, `DataValidationReport`, `resolve_under_root`,
  `bind_artifact_hashes`, `sha256_file`, typed provenance mode from Task 1.
- Produces: `publish_canonical_bundle` and:

~~~python
PARQUET_WRITER_PROFILE = MappingProxyType({
    "profile_version": "parquet-v1",
    "library": "pyarrow",
    "library_version": "25.0.0",
    "compression": "zstd",
    "compression_level": 9,
    "row_group_size": 65536,
    "use_dictionary": False,
    "write_statistics": True,
    "data_page_version": "2.0",
})

@dataclass(frozen=True, slots=True)
class PublishedCanonicalBundle:
    manifest: CanonicalDatasetManifest
    manifest_ref: RelativePath
    manifest_hash: Sha256Hex

def publish_raw_source(
    root: Path,
    import_id: str,
    source_path: Path,
) -> tuple[RelativePath, Sha256Hex]: ...

def publish_validated_candidate(
    root: Path,
    import_id: str,
    candidate: NormalizedDatasetCandidate,
    report: DataValidationReport,
) -> tuple[RelativePath, RelativePath]: ...
~~~

- [ ] **Step 1: Write RED determinism, immutability, and manifest-direction tests**

~~~python
def test_empty_gap_component_is_deterministic(tmp_path: Path) -> None:
    first = publish_bundle(tmp_path / "a", bundle(gaps=()), writer_profile())
    second = publish_bundle(tmp_path / "b", bundle(gaps=()), writer_profile())
    assert first.manifest.component_logical_hashes["daily-gaps"] == (
        second.manifest.component_logical_hashes["daily-gaps"]
    )
    assert read_table(first, "daily-gaps").num_rows == 0

def test_manifest_has_no_eligibility_back_reference(tmp_path: Path) -> None:
    payload = read_manifest(publish_bundle(tmp_path, bundle(), writer_profile()))
    assert not {"eligibility", "eligibility_hash", "formal_eligible"} & payload.keys()

def test_physical_profile_changes_file_hash_not_dataset_id(tmp_path: Path) -> None:
    first = publish_bundle(tmp_path / "a", bundle(), writer_profile(compression="zstd"))
    second = publish_bundle(tmp_path / "b", bundle(), writer_profile(compression="snappy"))
    assert first.manifest.dataset_identity.dataset_id == second.manifest.dataset_identity.dataset_id
    assert first.manifest.component_file_hashes != second.manifest.component_file_hashes
~~~

Add repeat publication, existing target, partial staging, hash mismatch, fixed
column order, writer metadata, physical profile changes, and contained refs.

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_artifacts.py -q`

Expected: FAIL because artifact schemas and atomic publication do not exist.

- [ ] **Step 3: Implement fixed Arrow schemas and deterministic writes**

Define one explicit `pa.schema` per component. Convert records using ordered
field lists, sort by stable keys, and call:

~~~python
pq.write_table(
    table,
    staging_path,
    compression=profile["compression"],
    compression_level=profile["compression_level"],
    row_group_size=profile["row_group_size"],
    use_dictionary=profile["use_dictionary"],
    write_statistics=profile["write_statistics"],
    data_page_version=profile["data_page_version"],
)
~~~

Logical hashes are computed before writing. File hashes are computed from final
bytes through `sha256_file` and bound through `bind_artifact_hashes`.

- [ ] **Step 4: Implement same-root atomic publication**

Create an exclusive staging directory under the contained root. Re-resolve
containment before each write and immediately before `Path.replace`. Reject an
existing final directory, cross-volume staging, partial target or hash mismatch.
Publish components, provenance, report and manifest as an all-verified directory;
on failure retain raw/validated evidence and write only quarantine references.

~~~python
staging = create_exclusive_staging(root, dataset_id, revision)
verify_same_volume_staging(root, staging, target)
write_and_verify_components(staging, bundle, writer_profile)
write_canonical_json_artifact(staging / CANONICAL_MANIFEST_NAME, manifest_payload)
verify_published_hashes(staging, manifest)
verify_contained_path(root, target_relative, require_existing=False)
if target.exists():
    raise DataFoundationError(BlockerCode.DATA_VALIDATION_BLOCKER,
                              "IMMUTABLE_TARGET_EXISTS", str(target_relative))
staging.replace(target)
~~~

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_artifacts.py -q`

Expected: PASS; physical writer changes alter file/manifest hashes but not
logical hashes or dataset ID.

- [ ] **Step 6: Refactor schema dispatch, then run targeted manifest and path regressions**

Use one immutable `COMPONENT_ARROW_SCHEMAS` mapping and one
`records_to_table(component_name, records) -> pa.Table` dispatcher.

Run:
`py -3.14 -m pytest tests/data_foundation/test_artifacts.py tests/pipeline/test_run_manifest.py tests/contracts/test_artifact_contract.py tests/contracts/test_path_safety.py -q`

Expected: PASS with old artifact semantics unchanged.

- [ ] **Step 7: Commit**

~~~powershell
git add src/tv_quant/data_foundation/artifacts.py src/tv_quant/data_foundation/__init__.py src/tv_quant/research_pipeline.py tests/data_foundation/test_artifacts.py
git commit -m "Publish immutable V2.2A canonical artifacts."
~~~

### Task 11: Bind manifests, provenance, and eligibility in MarketDataRegistry

**Files:**
- Create: `src/tv_quant/data_foundation/registry.py`
- Create: `tests/data_foundation/test_registry.py`
- Modify: `src/tv_quant/data_foundation/contracts.py`
- Modify: `src/tv_quant/data_foundation/__init__.py`
- Test: `tests/data_foundation/test_registry.py`

**Interfaces:**
- Consumes: `CanonicalDatasetManifest`, `DatasetProvenance`,
  `DataEligibility`, `RegistryBinding`, `RegistrySnapshot`,
  `canonical_hash`, `sha256_file`, containment owner.
- Produces: `MarketDataRegistry.load`, `MarketDataRegistry.register` and:

~~~python
def derive_eligibility(
    manifest: CanonicalDatasetManifest,
    manifest_hash: Sha256Hex,
    qualifying_provenances: tuple[DatasetProvenance, ...],
    check_matrix: Mapping[str, bool],
) -> DataEligibility: ...

def registry_snapshot_payload(snapshot: RegistrySnapshot) -> Mapping[str, object]: ...
~~~

- [ ] **Step 1: Write RED tests for one-way binding and legal states**

~~~python
def test_eligibility_rejects_operation_outcomes() -> None:
    for illegal in ("BLOCKED", "INCOMPLETE", "NOT_IMPLEMENTED"):
        with pytest.raises(ValueError, match="state"):
            DataEligibility(state=illegal, **eligibility_fields())

def test_smoke_import_creates_smoke_only() -> None:
    eligibility = derive_eligibility(
        manifest(), manifest_hash(), (smoke_provenance(),), all_checks_true()
    )
    assert eligibility.state is DataEligibilityState.SMOKE_ONLY
    assert eligibility.formal_eligible is False
~~~

Add exact manifest hash mismatch, missing provenance association, empty
qualifying set, smoke/non-smoke mixture, reverse manifest reference, duplicate
identical registration, corrupt snapshot and immutable history tests.

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_registry.py -q`

Expected: FAIL because registry/eligibility binding is absent.

- [ ] **Step 3: Implement derived eligibility only**

~~~python
def derive_eligibility(manifest, manifest_hash, provenances, check_matrix):
    require_exact_manifest_hash(manifest, manifest_hash)
    require_nonempty_provenances(provenances)
    smoke = any(p.source_type is MarketDataSourceType.YFINANCE_SMOKE for p in provenances)
    all_checks = all(check_matrix.values())
    state = DataEligibilityState.SMOKE_ONLY if smoke else DataEligibilityState.VALID
    formal = state is DataEligibilityState.VALID and all_checks
    if not all_checks:
        raise DataFoundationError(BlockerCode.DATA_VALIDATION_BLOCKER, "ELIGIBILITY_CHECK_FAILED")
    return build_hashed_eligibility(state=state, formal_eligible=formal, ...)
~~~

Callers cannot pass `formal_eligible`. `INVALIDATED` is created only by Task 13.

- [ ] **Step 4: Implement append-only atomic registry snapshots**

Validate:
`eligibility.dataset_id == manifest.dataset_identity.dataset_id`,
`eligibility.manifest_hash == manifest_hash`, and qualifying provenance hashes
are a non-empty subset of associations. Sort bindings by
`(dataset_id, manifest_revision, manifest_hash, eligibility_hash)`. Publish a
new contained snapshot and pointer atomically; never rewrite the prior snapshot.

~~~python
verify_binding(manifest, manifest_hash, eligibility, (provenance,))
bindings = tuple(sorted(
    (*self.snapshot.bindings, new_binding),
    key=lambda item: (
        item.dataset_id, item.manifest_revision,
        item.manifest_hash, item.eligibility_hash,
    ),
))
snapshot = build_registry_snapshot(self.snapshot.snapshot_hash, bindings)
publish_registry_snapshot_atomically(self.root, snapshot)
~~~

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_registry.py -q`

Expected: PASS; only VALID is formal, SMOKE_ONLY is permanent false, and
manifest payloads contain no eligibility reference.

- [ ] **Step 6: Refactor binding verification, then run identity/artifact regression**

Extract `verify_binding(manifest, manifest_hash, eligibility, provenances)` and
call it from registration, load and query paths.

Run:
`py -3.14 -m pytest tests/data_foundation/test_registry.py tests/data_foundation/test_identity.py tests/data_foundation/test_artifacts.py -q`

Expected: PASS with manifest and eligibility hashes independently reproducible.

- [ ] **Step 7: Commit**

~~~powershell
git add src/tv_quant/data_foundation/registry.py src/tv_quant/data_foundation/contracts.py src/tv_quant/data_foundation/__init__.py tests/data_foundation/test_registry.py
git commit -m "Bind V2.2A manifests and eligibility."
~~~

### Task 12: Enforce idempotent re-import and formal dataset lookup

**Files:**
- Create: `tests/data_foundation/test_registry_query.py`
- Modify: `src/tv_quant/data_foundation/registry.py`
- Modify: `src/tv_quant/data_foundation/__init__.py`
- Test: `tests/data_foundation/test_registry_query.py`

**Interfaces:**
- Consumes: `DatasetRequirement`, `CapabilityRegistry`,
  `MarketDataRegistry`, `RegistryBinding`, identity and manifest hashes.
- Produces: `find_latest_eligible_dataset` and:

~~~python
@dataclass(frozen=True, slots=True)
class RegistrationDecision:
    reuse_existing: bool
    manifest_revision: int
    existing_binding: RegistryBinding | None

def decide_registration(
    registry: MarketDataRegistry,
    identity: DatasetIdentity,
    manifest_candidate: CanonicalDatasetManifest,
) -> RegistrationDecision: ...

def append_provenance_association(
    registry: MarketDataRegistry,
    binding: RegistryBinding,
    provenance_ref: RelativePath,
    provenance_hash: Sha256Hex,
    provider_capability_id: str,
) -> RegistrySnapshot: ...
~~~

- [ ] **Step 1: Write RED idempotency, collision, and provider-order tests**

~~~python
def test_identical_reimport_reuses_manifest_revision() -> None:
    first = register_dataset(registry(), dataset(close="100"), provider="local-csv")
    second = register_dataset(first.registry, dataset(close="100"), provider="local-parquet")
    assert second.binding.manifest_hash == first.binding.manifest_hash
    assert second.binding.manifest_revision == 1
    assert len(second.binding.provenance_hashes) == 2

def test_formal_lookup_excludes_smoke_binding() -> None:
    result = find_latest_eligible_dataset(requirement(), smoke_registry(), snapshot_hash(), capabilities())
    assert result.blocker_code is BlockerCode.DATA_CAPABILITY_BLOCKER

def test_dataset_id_collision_rejects_mismatch() -> None:
    first = register_dataset(registry(), dataset(close="100"), provider="local-csv")
    with pytest.raises(DataFoundationError, match="IDENTITY_COLLISION"):
        register_dataset(first.registry, dataset(close="101"), provider="local-csv")
~~~

Add same-ID mismatch collision, same provider rank content conflict, preference
fallback, complete coverage, canonical range end, active revision and
deterministic dataset-ID tie-break tests.

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_registry_query.py -q`

Expected: FAIL because reuse and query policies are absent.

- [ ] **Step 3: Implement idempotent registration decision**

For an existing `dataset_id`, compare every identity-bearing component hash,
semantic dependency hash, range and count. Exact equality reuses canonical
artifacts and manifest revision and appends only import/provenance association.
Any mismatch raises
`DataFoundationError(DATA_VALIDATION_BLOCKER, "IDENTITY_COLLISION")`. A
normal re-import never creates revision 2.

~~~python
existing = registry.binding_for(identity.dataset_id)
if existing is None:
    return RegistrationDecision(False, 1, None)
registered = registry.load_manifest(existing)
if identity_payload(registered.dataset_identity) != identity_payload(identity):
    raise DataFoundationError(
        BlockerCode.DATA_VALIDATION_BLOCKER,
        "IDENTITY_COLLISION",
        identity.dataset_id,
    )
return RegistrationDecision(True, registered.manifest_revision, existing)
~~~

- [ ] **Step 4: Implement the frozen query order**

~~~python
candidates = verify_and_filter_bindings(
    registry, requirement, expected_snapshot_hash
)
candidates = tuple(c for c in candidates
                   if c.eligibility_state is DataEligibilityState.VALID
                   and load_eligibility(c).formal_eligible)
for provider_id in requirement.provider_preference:
    rank = tuple(c for c in candidates if provider_id in c.provider_capability_ids)
    if rank:
        return select_without_content_conflict(rank)
return capability_blocker("NO_FORMAL_ELIGIBLE_DATASET")
~~~

`select_without_content_conflict` sorts by complete coverage, canonical range
end, active revision and dataset ID only after rejecting conflicting logical
content at the same provider rank. It never reads mtime or import timestamp.

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_registry_query.py -q`

Expected: PASS; smoke bindings are invisible to formal lookup.

- [ ] **Step 6: Refactor candidate ranking, then run registry and V2.1 DataPlan regression**

Keep filters, provider-rank conflict detection and deterministic final sort as
three named pure functions.

Run:
`py -3.14 -m pytest tests/data_foundation/test_registry.py tests/data_foundation/test_registry_query.py tests/contracts/test_data_plan.py tests/contracts/test_capability_registry.py -q`

Expected: PASS with ordered V2.1 `provider_preference` unchanged.

- [ ] **Step 7: Commit**

~~~powershell
git add src/tv_quant/data_foundation/registry.py src/tv_quant/data_foundation/__init__.py tests/data_foundation/test_registry_query.py
git commit -m "Add idempotent V2.2A registry lookup."
~~~

### Task 13: Implement exact-binding atomic invalidation

**Files:**
- Create: `tests/data_foundation/test_invalidation.py`
- Modify: `src/tv_quant/data_foundation/registry.py`
- Modify: `src/tv_quant/data_foundation/contracts.py`
- Modify: `src/tv_quant/data_foundation/__init__.py`
- Test: `tests/data_foundation/test_invalidation.py`

**Interfaces:**
- Consumes: `InvalidationEvent`, `DataEligibility`,
  `RegistrySnapshot`, exact expected manifest/eligibility/snapshot hashes.
- Produces: `invalidate_dataset` with the exact signature in Section 3.3.

- [ ] **Step 1: Write RED tests for scope, atomicity, replay and conflicts**

~~~python
def test_invalidation_scopes_exact_manifest_hash() -> None:
    event, eligibility, snapshot = invalidate_dataset(
        registry_with_two_revisions(), DATASET_ID, MANIFEST_V1_HASH,
        ELIGIBILITY_V1_REF, ELIGIBILITY_V1_HASH, SNAPSHOT_HASH,
        "BAD_SOURCE_EVIDENCE", "review:42", "2026-08-02T12:00:00Z",
    )
    assert eligibility.state is DataEligibilityState.INVALIDATED
    assert binding(snapshot, MANIFEST_V2_HASH).eligibility_state is DataEligibilityState.VALID

def test_identical_invalidation_replay_reuses_triple() -> None:
    assert invalidate_twice_same_request() == invalidate_once()

def test_invalidation_triple_is_all_or_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inject_failure_after_each_staged_record(monkeypatch)
    with pytest.raises(DataFoundationError):
        invalidate_fixture_binding(tmp_path)
    assert visible_invalidation_records(tmp_path) == ()
~~~

Inject failures after event staging, eligibility staging and snapshot staging to
prove no partial record becomes visible.

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_invalidation.py -q`

Expected: FAIL because compare-and-append and triple publication do not exist.

- [ ] **Step 3: Implement event and invalidated-eligibility derivation**

~~~python
event_payload = {
    "event_schema_version": "v2.2a",
    "dataset_id": dataset_id,
    "manifest_hash": expected_manifest_hash,
    "prior_eligibility_id": prior.eligibility_id,
    "prior_eligibility_hash": prior.eligibility_hash,
    "prior_eligibility_state": prior.state.value,
    "reason_code": reason_code,
    "actor_ref": actor_ref,
    "event_timestamp_utc": event_timestamp_utc,
    "parent_registry_snapshot_hash": expected_snapshot_hash,
}
event_id = canonical_hash(event_payload)
invalidated = replace_prior_as_invalidated(prior, event_id, canonical_hash(event_payload))
~~~

Preserve exact manifest and qualifying provenance hashes. The new eligibility
is formal false and binds the event ID/hash.

- [ ] **Step 4: Implement compare-and-append triple publication**

Verify all expected hashes against the current snapshot. Derive a deterministic
request key from the complete request. If that key already maps to a committed
triple, return the same triple. Otherwise stage event, eligibility and snapshot
under one same-root transaction directory, fsync/close, verify hashes, and
atomically publish the new snapshot pointer only after all three final files are
present. A mismatched parent or partial historical record fails closed.

~~~python
with registry_transaction(root, expected_snapshot_hash) as tx:
    tx.stage_json("invalidation-event.json", event_payload)
    tx.stage_json("eligibility-invalidated.json", eligibility_payload)
    tx.stage_json("registry-snapshot.json", snapshot_payload)
    tx.verify_all_hashes()
    tx.publish_files()
    tx.publish_snapshot_pointer_last()
~~~

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_invalidation.py -q`

Expected: PASS for exact scope, all-or-none visibility, idempotent replay and
parent/hash conflicts.

- [ ] **Step 6: Refactor transaction staging, then run registry history regression**

Reuse the same private same-root staging primitive as registration while
retaining a distinct invalidation request key and triple validation.

Run:
`py -3.14 -m pytest tests/data_foundation/test_registry.py tests/data_foundation/test_registry_query.py tests/data_foundation/test_invalidation.py -q`

Expected: PASS; historical snapshots, manifestations and eligibilities remain
readable and immutable.

- [ ] **Step 7: Commit**

~~~powershell
git add src/tv_quant/data_foundation/registry.py src/tv_quant/data_foundation/contracts.py src/tv_quant/data_foundation/__init__.py tests/data_foundation/test_invalidation.py
git commit -m "Add atomic exact-binding dataset invalidation."
~~~

### Task 14: Strengthen the existing Windows path-containment owner

**Files:**
- Create: `tests/data_foundation/test_security.py`
- Modify: `src/tv_quant/contracts/path_safety.py`
- Modify: `tests/contracts/test_path_safety.py`
- Modify: `src/tv_quant/data_foundation/artifacts.py`
- Test: `tests/data_foundation/test_security.py`
- Test: `tests/contracts/test_path_safety.py`

**Interfaces:**
- Consumes: existing `resolve_under_root(root, relative_path) -> Path`.
- Produces in the same owner module:

~~~python
def verify_contained_path(
    root: Path,
    relative_path: str,
    *,
    require_existing: bool,
    reject_reparse: bool = True,
) -> Path: ...

def verify_same_volume_staging(root: Path, staging: Path, target: Path) -> None: ...
~~~

- [ ] **Step 1: Write RED Windows special-path and repeated-check tests**

~~~python
@pytest.mark.parametrize("unsafe", [
    "../x.csv", r"C:x.csv", r"C:\x.csv", r"\\server\share\x.csv",
    "x.csv:stream", "CON", "NUL.txt", "COM1.csv", "name\x00.csv",
])
def test_windows_special_paths_and_reparse_escape_are_rejected(
    tmp_path: Path, unsafe: str
) -> None:
    with pytest.raises(ValueError):
        verify_contained_path(tmp_path, unsafe, require_existing=False)

def test_artifact_publication_rechecks_containment(monkeypatch) -> None:
    calls = record_verify_calls(monkeypatch)
    publish_contained_bundle()
    assert calls == ["raw-publish", "canonical-publish"]
~~~

Create symlink/junction/reparse tests where supported; skip only when the OS
cannot create the primitive and record the reason.

- [ ] **Step 2: Run RED**

Run:
`py -3.14 -m pytest tests/data_foundation/test_security.py tests/contracts/test_path_safety.py -q`

Expected: FAIL on missing reparse/same-volume/repeated-boundary behavior.

- [ ] **Step 3: Extend the existing owner, not a new path module**

Normalize separators and Unicode/case before checking. Reject colon-bearing
components, reserved DOS basenames with or without extensions, absolute and
drive-relative paths, UNC, NUL and parent components. Resolve each existing
ancestor; inspect Windows file attributes for reparse points; resolve the final
target and prove `relative_to(resolved_root)`. If any attribute or target cannot
be inspected, raise `ValueError`.

~~~python
relative = _validated_relative_path(relative_path)
for component in existing_ancestors(resolved_root / relative):
    if reject_reparse and is_reparse_point(component):
        resolved = component.resolve(strict=True)
        resolved.relative_to(resolved_root)
candidate = (resolved_root / relative).resolve(strict=require_existing)
candidate.relative_to(resolved_root)
return candidate
~~~

- [ ] **Step 4: Enforce same-root, same-volume atomic publication**

Compare `Path.anchor` and Windows volume serial/device identity where available.
Re-run `verify_contained_path` immediately before raw copy and canonical
directory replace. Task 15 adds source-read and registry-commit checks around
the orchestrator. Never log `runtime.data_root` or the resolved absolute target.

~~~python
if volume_identity(staging) != volume_identity(target.parent):
    raise ValueError("staging: same-volume publication required")
verify_contained_path(root, raw_relative, require_existing=False)
verify_contained_path(root, canonical_relative, require_existing=False)
~~~

- [ ] **Step 5: Run GREEN**

Run:
`py -3.14 -m pytest tests/data_foundation/test_security.py tests/contracts/test_path_safety.py -q`

Expected: PASS on Windows; symlink/junction/reparse escape cannot reach read or
write calls.

- [ ] **Step 6: Refactor platform probes, then run artifact and confirmation-store regression**

Isolate Windows attribute/volume inspection behind private functions in the
existing `path_safety.py` owner so non-Windows code remains deterministic.

Run:
`py -3.14 -m pytest tests/data_foundation/test_artifacts.py tests/data_foundation/test_security.py tests/contracts/test_artifact_contract.py tests/contracts/test_confirmation_store.py -q`

Expected: PASS with V2.1 root containment and atomic confirmation semantics
unchanged.

- [ ] **Step 7: Commit**

~~~powershell
git add src/tv_quant/contracts/path_safety.py tests/contracts/test_path_safety.py src/tv_quant/data_foundation/artifacts.py tests/data_foundation/test_security.py
git commit -m "Strengthen Windows data-root containment."
~~~

### Task 15: Orchestrate the complete local import pipeline

**Files:**
- Create: `src/tv_quant/data_foundation/importer.py`
- Create: `tests/data_foundation/test_importer.py`
- Modify: `src/tv_quant/data_foundation/__init__.py`
- Modify: `src/tv_quant/data_foundation/artifacts.py`
- Modify: `src/tv_quant/data_foundation/registry.py`
- Test: `tests/data_foundation/test_importer.py`

**Interfaces:**
- Consumes: every Task 2-14 boundary, `status_definition` and
  `DataImportRuntimeContext`.
- Produces: `import_local_dataset(request, runtime) -> ImportLocalDatasetResult`.
- Exact stage order:

~~~python
IMPORT_STAGE_ORDER = (
    "REQUEST_VALIDATION",
    "SOURCE_CONTAINMENT",
    "RAW_PRESERVATION",
    "PARSING",
    "CALENDAR_BINDING",
    "VALIDATION",
    "ADJUSTMENT",
    "IDENTITY",
    "CANONICAL_PUBLICATION",
    "ELIGIBILITY",
    "REGISTRY_COMMIT",
    "FINALIZATION",
)
~~~

- [ ] **Step 1: Write RED success, failure, and smoke orchestration tests**

~~~python
def test_valid_local_csv_publishes_complete_binding(tmp_path: Path) -> None:
    result = import_local_dataset(valid_csv_request(), runtime(tmp_path))
    assert result.operation.status is PipelineStatus.SUCCESS
    assert result.import_manifest.final_dataset_id == result.canonical_manifest.dataset_identity.dataset_id
    assert result.eligibility.state is DataEligibilityState.VALID
    assert result.registry_binding.manifest_hash == result.eligibility.manifest_hash

def test_source_missing_is_blocked_without_eligibility() -> None:
    result = import_with_gap_reason(GapReasonCode.SOURCE_MISSING)
    assert result.validation_report.validation_status is ValidationOutcome.BLOCKED
    assert result.eligibility is None

def test_source_incomplete_has_no_eligibility() -> None:
    result = import_with_gap_reason(GapReasonCode.SOURCE_INCOMPLETE)
    assert result.validation_report.validation_status is ValidationOutcome.INCOMPLETE
    assert result.eligibility is None

@pytest.mark.parametrize("outcome", [
    ValidationOutcome.BLOCKED,
    ValidationOutcome.INCOMPLETE,
    ValidationOutcome.NOT_IMPLEMENTED,
])
def test_nonvalid_outcome_has_no_canonical_manifest_or_eligibility(outcome) -> None:
    result = import_with_forced_outcome(outcome)
    assert result.canonical_manifest is None
    assert result.eligibility is None
    assert result.registry_binding is None
~~~

Add tests for new import/provenance IDs on repeats, raw-before-parse, failed
manifest finalization, quarantine refs, no auto retry and
`YFINANCE_SMOKE -> SMOKE_ONLY`. Record and assert containment checks at
`source-read`, `raw-publish`, `canonical-publish` and `registry-commit`.

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_importer.py -q`

Expected: FAIL because orchestration and finalized result semantics are absent.

- [ ] **Step 3: Implement request/raw/parser/validation stages**

~~~python
def import_local_dataset(request, runtime):
    import_id = runtime.uuid_factory().hex
    imported_at = utc_z(runtime.clock())
    source = verify_source(request, runtime)
    raw_ref, raw_hash = publish_raw_source(runtime.data_root, import_id, source)
    try:
        calendar_ref = load_contained_calendar(request, runtime)
        rows = parse_by_source_type(source, request, calendar_ref)
        candidate = assemble_candidate(import_id, rows, request, runtime, calendar_ref)
        report = validate_daily_dataset(candidate)
    except DataFoundationError as exc:
        return finalize_failed_import(import_id, imported_at, raw_ref, raw_hash, exc)
    if report.validation_status is not ValidationOutcome.VALID:
        return finalize_nonvalid_import(import_id, imported_at, candidate, report)
    return continue_valid_import(
        request, runtime, imported_at, raw_ref, raw_hash, candidate, report
    )
~~~

Raw bytes are copied and hashed before parser invocation. Every exception is
translated to typed status metadata and immutable evidence; programming errors
are not converted into success.

- [ ] **Step 4: Implement valid identity/publication/eligibility/registry stages**

Derive actions/factors/adjusted rows, construct the logical bundle and identity,
check idempotent registration, publish or reuse canonical artifacts, create a
new provenance, derive VALID or SMOKE_ONLY eligibility, commit the registry
snapshot, then finalize the import manifest. If registry commit fails, no
eligibility/binding is returned and staged records remain unreachable.

~~~python
factors = derive_adjustment_factors(
    candidate.corporate_action_events,
    candidate.corporate_action_evidence,
    request.adjustment_method,
)
adjusted = apply_adjustments(candidate.raw_bars, factors, request.adjustment_method)
bundle = assemble_logical_bundle(candidate, factors, adjusted)
identity = build_dataset_identity(bundle)
registry = load_registry_from_runtime(runtime)
decision = decide_registration(registry, identity, manifest_candidate(bundle))
provenance, provenance_ref = build_and_publish_provenance(
    runtime, request, identity, report
)
published = reuse_or_publish(decision, bundle, report, provenance)
eligibility = derive_eligibility(
    published.manifest, published.manifest_hash, (provenance,), check_matrix(report)
)
eligibility_ref = publish_eligibility(runtime.data_root, eligibility)
snapshot = registry.register(
    published.manifest, published.manifest_ref,
    provenance, provenance_ref, eligibility, eligibility_ref,
)
~~~

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_importer.py -q`

Expected: PASS for success, smoke, blocker, incomplete, not-implemented,
repeat, collision and failure-evidence paths.

- [ ] **Step 6: Refactor stage dispatch, then prove no prohibited execution path**

Monkeypatch `yfinance`, `futu`, `requests`, `socket.socket`,
`subprocess.run`, `run_pipeline`, `audit_backtest` and `write_reports` to raise.

Run:
`py -3.14 -m pytest tests/data_foundation/test_importer.py -q`

Expected: PASS; no prohibited callable is reached.

- [ ] **Step 7: Commit**

~~~powershell
git add src/tv_quant/data_foundation/importer.py src/tv_quant/data_foundation/__init__.py src/tv_quant/data_foundation/artifacts.py src/tv_quant/data_foundation/registry.py tests/data_foundation/test_importer.py
git commit -m "Orchestrate local V2.2A dataset imports."
~~~

### Task 16: Add end-to-end offline fixtures and canonical equivalence acceptance

**Files:**
- Create: `tests/data_foundation/test_end_to_end.py`
- Create: `tests/fixtures/data_foundation/valid-qqq.csv`
- Create: `tests/fixtures/data_foundation/pre-ipo-gap-evidence.json`
- Create: `tests/fixtures/data_foundation/halt-gap-evidence.json`
- Modify: `tests/data_foundation/test_importer.py`
- Test: `tests/data_foundation/test_end_to_end.py`

**Interfaces:**
- Consumes: public `import_local_dataset`,
  `find_latest_eligible_dataset`, `invalidate_dataset`.
- Produces: no production interface; provides full offline acceptance evidence.

- [ ] **Step 1: Create fixed local fixture payloads and fixture hashes**

Use only SPY/QQQ daily rows, explicit XNYS calendar coverage, explicit
`NO_GAPS_IN_RANGE`/gap evidence, and explicit
`NO_ACTIONS_IN_RANGE`/split evidence. Tests generate equivalent Parquet through
the fixed writer profile in `tmp_path`; no binary file is downloaded or
committed.

- [ ] **Step 2: Write RED full-lifecycle tests**

~~~python
def test_csv_parquet_reimport_query_and_invalidation_lifecycle(tmp_path: Path) -> None:
    csv_result = import_local_dataset(spy_csv_request(), runtime(tmp_path))
    parquet_result = import_local_dataset(spy_parquet_request(), runtime(tmp_path))
    assert csv_result.import_manifest.import_id != parquet_result.import_manifest.import_id
    assert csv_result.canonical_manifest.dataset_identity.dataset_id == (
        parquet_result.canonical_manifest.dataset_identity.dataset_id
    )
    binding = find_latest_eligible_dataset(requirement(), load_registry(tmp_path), ...)
    assert binding.dataset_id == csv_result.canonical_manifest.dataset_identity.dataset_id
    _, invalidated, _ = invalidate_exact_binding(binding, tmp_path)
    assert invalidated.state is DataEligibilityState.INVALIDATED
    assert find_latest_eligible_dataset(requirement(), load_registry(tmp_path), ...).blocker_code is BlockerCode.DATA_CAPABILITY_BLOCKER
~~~

- [ ] **Step 3: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_end_to_end.py -q`

Expected: FAIL until fixture adapters expose every complete local evidence
reference required by the pipeline.

- [ ] **Step 4: Wire fixture factories through only public APIs**

Test helpers may create roots, local Parquet and requests; they must not call
private publication or registry mutation helpers to bypass gates. Freeze the
expected component names, identity equality, eligibility state, binding hashes,
manifest revision and post-invalidation lookup result.

~~~python
def materialize_parquet_fixture(root: Path, csv_request: DataImportRequest) -> Path:
    rows = parse_csv_source(
        FIXTURES / "valid-spy.csv", csv_request, fixture_calendar()
    )
    path = root / "incoming" / "spy.parquet"
    write_test_parquet(path, rows, writer_profile())
    return path
~~~

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_end_to_end.py -q`

Expected: PASS for SPY/QQQ CSV/Parquet equivalence, legal gaps, smoke-only
exclusion, idempotent repeat and invalidation lifecycle.

- [ ] **Step 6: Refactor fixture factories, then run the complete V2.2A suite twice**

Share only local object constructors and `tmp_path` writers; each end-to-end
test must still call public operations.

Run:
`py -3.14 -m pytest tests/data_foundation -q`

Run again:
`py -3.14 -m pytest tests/data_foundation -q`

Expected: both runs PASS with identical golden logical IDs/hashes; physical
temporary paths and timestamps do not enter golden identities.

- [ ] **Step 7: Commit**

~~~powershell
git add tests/data_foundation/test_end_to_end.py tests/data_foundation/test_importer.py tests/fixtures/data_foundation/valid-qqq.csv tests/fixtures/data_foundation/pre-ipo-gap-evidence.json tests/fixtures/data_foundation/halt-gap-evidence.json
git commit -m "Add offline V2.2A lifecycle acceptance fixtures."
~~~

### Task 17: Enforce duplicate-owner, security, V2.1 regression, and final acceptance

**Files:**
- Create: `tests/data_foundation/test_static_ownership.py`
- Create: `tests/integration/test_v2_2a_acceptance.py`
- Modify: `config/capability-registry-v2.1.json`
- Modify: `src/tv_quant/data_foundation/__init__.py`
- Modify: `tests/contracts/test_capability_registry.py`
- Test: `tests/data_foundation/test_static_ownership.py`
- Test: `tests/integration/test_v2_2a_acceptance.py`
- Test: complete `tests/` tree

**Interfaces:**
- Consumes: all V2.2A public exports and frozen V2.1 public-interface list.
- Produces: machine-verifiable V2.2A acceptance evidence only; no runtime
  capability beyond Tasks 1-16.

- [ ] **Step 1: Write RED static ownership and scope tests**

~~~python
def test_data_foundation_reuses_existing_owners_and_has_no_network_path() -> None:
    sources = read_python_sources("src/tv_quant/data_foundation")
    assert "import hashlib" not in sources
    assert "def canonical_hash" not in sources
    assert "def sha256" not in sources
    assert "import yfinance" not in sources
    assert "import futu" not in sources
    assert "import requests" not in sources
    assert "import socket" not in sources
    assert "subprocess." not in sources

def test_frozen_v21_public_interfaces_remain_exact() -> None:
    assert frozen_public_surface() == EXPECTED_V21_PUBLIC_SURFACE
~~~

`EXPECTED_V21_PUBLIC_SURFACE` is a literal mapping in the test from each of the
19 frozen names to its current module and qualified symbol/type signature; it
is not derived from `__all__` or the implementation under test.

Also reject a second manifest writer, artifact ledger, audit writer, provenance
owner, decimal normalizer, broker/account/order/webhook/option code and
V2.2B/V2.2C modules.

- [ ] **Step 2: Run RED**

Run:
`py -3.14 -m pytest tests/data_foundation/test_static_ownership.py tests/integration/test_v2_2a_acceptance.py -q`

Expected: FAIL until the final export allow-list and acceptance matrix are
complete.

- [ ] **Step 3: Freeze the deliberate public export list**

`tv_quant.data_foundation.__all__` contains only the contracts and operations
listed in Section 3. Internal Arrow schemas, staging helpers, payload validators
and registry serializers remain private. No V2.1 symbol is renamed or rebound.

Promote `market-data.local-csv.daily` and
`market-data.local-parquet.daily` to `implemented`, `formal_verified`,
`available`, `eligible` and `not_smoke_only` with code/test evidence from Tasks
4, 10, 15 and 16. Promote `market-data.yfinance-smoke.local` to `implemented`,
`not_live_verified`, `available`, `not_eligible` and `smoke_only` with the local
smoke gate evidence. Keep provider values `local`/`YFINANCE_SMOKE_LOCAL` and
never claim network availability.

~~~python
__all__ = (
    "DataImportRequest", "DataImportRuntimeContext",
    "DailyBarRaw", "DailyBarAdjusted", "DailyGapRecord", "GapEvidence",
    "CorporateActionEvent", "CorporateActionEvidence", "AdjustmentFactor",
    "DataValidationIssue", "DataValidationReport", "DatasetIdentity",
    "DatasetProvenance", "DataImportManifest", "CanonicalDatasetManifest",
    "DataEligibility", "InvalidationEvent", "RegistryBinding",
    "import_local_dataset", "find_latest_eligible_dataset", "invalidate_dataset",
)
~~~

- [ ] **Step 4: Add acceptance matrix assertions**

Assert every Section 5 requirement has a real test node, every canonical bundle
has seven components plus manifest, no manifest references eligibility,
DataEligibility accepts only three states, smoke never appears in formal lookup,
all failure outcomes lack eligibility, and path/identity/hash failures are
blocking.

~~~python
TRACEABILITY_REQUIREMENTS = frozenset({
    "csv_parquet_equivalence", "lineage_excluded_from_identity",
    "physical_profile_excluded_from_identity", "empty_gap_component",
    "gap_reason_states", "smoke_only", "idempotent_reimport",
    "identity_collision", "one_way_manifest_eligibility",
    "atomic_invalidation", "windows_path_security", "v21_regression",
})
assert traceability_test_nodes() == TRACEABILITY_REQUIREMENTS
~~~

- [ ] **Step 5: Run focused GREEN and compile checks**

Run:

~~~powershell
py -3.14 -m pytest tests/data_foundation tests/integration/test_v2_2a_acceptance.py -q
py -3.14 -m compileall -q src tests
~~~

Expected: PASS; compileall exits 0 with no output.

- [ ] **Step 6: Refactor the acceptance allow-list, then run V2.1 and full regression**

Consolidate only literal expected public names and capability records; do not
derive expected values from production registries.

Run:

~~~powershell
py -3.14 -m pytest tests/contracts tests/adapters tests/pipeline/test_v2_cli_gate.py tests/integration/test_v2_1_gate.py tests/integration/test_v2_1_security.py -q
py -3.14 -m pytest tests/pipeline -q
py -3.14 -m pytest tests -q
git diff --check
~~~

Expected: the frozen 517 V2.1/Phase 1 tests remain passing, every new V2.2A test
passes, and `git diff --check` reports no whitespace errors. No command performs
a data download, network call, formal backtest, push or PR.

- [ ] **Step 7: Commit**

~~~powershell
git add config/capability-registry-v2.1.json src/tv_quant/data_foundation/__init__.py tests/contracts/test_capability_registry.py tests/data_foundation/test_static_ownership.py tests/integration/test_v2_2a_acceptance.py
git commit -m "Complete V2.2A data foundation acceptance."
~~~

## 6. Task Dependency Order

~~~text
1 registration/owners
  -> 2 immutable contracts/runtime isolation
      -> 3 semantic-lineage projections
      -> 4 CSV/Parquet parsing
      -> 5 XNYS calendar
          -> 6 gaps/evidence
          -> 7 corporate actions/adjustments
              -> 8 validation
                  -> 9 dataset identity
                      -> 10 artifacts/manifests
                          -> 11 eligibility/registry
                              -> 12 idempotency/query
                              -> 13 invalidation
                      -> 14 path security
                          -> 15 import orchestration
                              -> 16 end-to-end fixtures
                                  -> 17 final acceptance
~~~

Tasks 6 and 7 may be implemented after Task 5 in either order, but Task 8
requires both. Tasks 12 and 13 both require Task 11; Task 15 requires them and
Task 14. No task may begin V2.2B, formal backtesting or network/provider work.

## 7. Final Acceptance Commands

Run from repository root on the implementation branch:

~~~powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
py -3.14 -m pytest tests/data_foundation tests/integration/test_v2_2a_acceptance.py -q
py -3.14 -m pytest tests/contracts tests/adapters tests/pipeline/test_v2_cli_gate.py tests/integration/test_v2_1_gate.py tests/integration/test_v2_1_security.py -q
py -3.14 -m pytest tests/pipeline -q
py -3.14 -m pytest tests -q
py -3.14 -m compileall -q src tests
$forbiddenHits = rg -n "hashlib|def sha256|def canonical_hash|import yfinance|import futu|import requests|import socket|subprocess\." src/tv_quant/data_foundation
if ($LASTEXITCODE -eq 0) { $forbiddenHits; throw "Forbidden owner or execution path found" }
if ($LASTEXITCODE -ne 1) { throw "Static scan failed to run" }
git diff --check
git status --short
~~~

Expected:

- all V2.2A focused and integration tests pass;
- the frozen V2.1/Phase 1 baseline of 517 tests remains passing in the expanded
  full suite;
- compileall and diff checks exit 0;
- the static search returns no matches;
- worktree contains only the reviewed implementation commits and no uncommitted
  files;
- no network, provider, account, order, webhook, option, formal-backtest,
  V2.2B or V2.2C capability exists.

## 8. Implementation Review Gates

Each task is accepted only after its RED evidence, minimal GREEN implementation,
refactor, focused regression and commit are independently reviewable. The final
review must confirm:

1. every frozen design requirement maps to Section 5 and a real test;
2. every referenced type and function is defined in Section 3 or an existing
   frozen owner;
3. task dependencies match Section 6 and contain no forward ownership cycle;
4. identity fields and lineage-only fields match Section 4 exactly;
5. logical hashes, physical hashes and lineage hashes remain separate;
6. manifest-to-eligibility references remain one-way;
7. invalidation publishes the exact event/eligibility/snapshot triple atomically;
8. Windows path checks occur at all four boundaries and never persist root;
9. no task modifies V2.1 semantics, launches a provider or executes a backtest;
10. the full regression and static-owner checks pass before final acceptance.

After Task 17, stop and request an independent implementation review. Do not
start V2.2B.
