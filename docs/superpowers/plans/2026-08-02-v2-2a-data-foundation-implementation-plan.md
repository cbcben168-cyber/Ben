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
- CSV/Parquet parser 保留原始输入顺序和重复行；validation 前禁止排序、去重
  或静默修复，canonical stable sort 只发生在 VALID 结果之后。
- market data、calendar snapshot、全部 gap/action evidence 必须先 containment
  check，再原子复制到 `raw/<import_id>/inputs/`；复制后所有消费者只读 preserved
  refs/hashes，禁止回读原始用户路径。
- `validate_daily_dataset` 同时返回 report 与可选 validated candidate；后续
  adjustment、identity、canonicalization 只能消费 validated candidate。
- canonical reuse 只由 logical descriptor 决定；新发布严格遵守 components
  → file hashes → provenance → complete manifest → verify → atomic publish。
- 每个 registry snapshot 对 `(dataset_id, manifest_hash)` 最多一个 current
  binding；re-import 合并 provenance 并替换 current eligibility pointer。
- 首版复权只实现 `split-only-v1` 与 `NO_ACTIONS_IN_RANGE` identity factor；
  `CASH_DIVIDEND` 必须返回 NOT_IMPLEMENTED + DATA_CAPABILITY_BLOCKER。
- invalidation event、INVALIDATED eligibility、registry snapshot 必须作为一个
  transaction directory 发布，active snapshot pointer 最后原子替换。
- V2.1 的 19 个冻结公共接口、next-bar、成本、Buy and Hold、确认门禁和
  517-test baseline 不得退化。

- Canonical JSON is fail-closed: V2.2A persists only recursive JSON
  `null`/bool/int/string/list/mapping values with string mapping keys. `Path`,
  `datetime`, `set`, `bytes`, every float (including NaN/Infinity), `Decimal`,
  and custom objects are rejected before serialization; `default=str` is
  prohibited.
- `artifact_paths` are transient hash-time `Path` values only. Every V2.2A
  persisted artifact, provenance, manifest, registry snapshot, eligibility and
  import manifest contains only validated `RelativePath` references; an
  absolute data root or resolved absolute file path is a blocker.
- Registry activation is explicit and append-only. A formal lookup reads only
  `active_manifest_by_dataset_id` and its `ManifestActivationEvent`; it never
  infers activity from manifest revision, mtime, import time, or lexical order.
- `DataEligibility.qualifying_provenance_hashes` is the explicit
  formal-qualifying subset of one-to-one `ProvenanceAssociation` records. A
  smoke re-import cannot lower VALID, a later local formal association upgrades
  SMOKE_ONLY to VALID, and normal re-import never restores INVALIDATED.
- `split-only-v1` uses only Decimal arithmetic on a latest-basis backward
  adjustment: later effective events apply to earlier bars, multiplication is
  cumulative and deterministically ordered, and the only quantization is the
  final `0.000000000001` ROUND_HALF_EVEN conversion.
- Before any Task 1 write/test implementation action, the dependency preflight
  must prove installed `exchange-calendars==4.13.2` and `pyarrow==25.0.0`.
  A missing or wrong version stops execution; it never runs pip or contacts a
  package index.

## Independent Review Closure Map

| Review item | Frozen closure | Tasks | Primary acceptance nodes |
|---|---|---:|---|
| BLOCKER 1 — parser repair before validation | parser preserves source order/duplicates; validation blocks out-of-order input; stable sort follows VALID only | 4, 8, 16 | `test_parsers_preserve_out_of_order_source_sequence`, `test_out_of_order_input_remains_blocked`, lifecycle equivalence test |
| BLOCKER 2 — original input and evidence TOCTOU | `PreservedImportInputs` atomically contains and hashes market, calendar, gap and action inputs; all consumers read preserved refs only | 10, 14, 15 | preservation-package, mutation-during-copy, preserved-parser-path and post-preservation-mutation tests |
| BLOCKER 3 — validation output not propagated | `DailyDatasetValidationResult` returns the only allowed `ValidatedDatasetCandidate`; identical duplicates are removed there and never read again from normalized rows | 8, 15 | validated-candidate, duplicate canonical-row and downstream-input tests |
| BLOCKER 4 — cyclic/incomplete publication | descriptor-only reuse decision; components → file hashes → provenance → complete manifest → verify → atomic publish; reuse performs no canonical write | 9, 10, 12, 15 | publication-order, complete-manifest and reuse-no-write tests |
| BLOCKER 5 — parallel current registry binding | each snapshot upserts one binding per `(dataset_id, manifest_hash)`; re-import merges provenances and replaces eligibility pointer | 11, 12, 13, 16 | exact-pair uniqueness, two-provenance re-import and invalidation lifecycle tests |
| BLOCKER 6 — undefined dividend adjustment | only `split-only-v1`, SPLIT and the no-actions identity factor are implemented; cash dividends are typed NOT_IMPLEMENTED blockers | 7, 8, 15 | cash-dividend coverage, validation and no-output importer tests |
| IMPORTANT 1 — hash/signature ambiguity | the only bundle helper is `component_logical_hashes`; publisher return is `PublishedCanonicalBundle`; inconsistent same-ID claims are `IDENTITY_CLAIM_MISMATCH` | 3, 9, 10, 12 | helper ownership, exact claim mismatch and frozen signature tests |
| IMPORTANT 2 — invalidation transaction semantics | event, INVALIDATED eligibility and snapshot publish as one verified directory; active pointer is last; complete inactive orphans remain inactive | 13, 16 | no-partial-active-visibility, replay, current eligibility replacement and lifecycle tests |

### Second independent review closure map

| Review item | Frozen closure | Tasks | Primary acceptance nodes |
|---|---|---:|---|
| BLOCKER 1 – permissive canonical JSON | recursive validator and `allow_nan=False`; no writer fallback/string coercion | 1, 17 | `test_canonical_json_rejects_non_json_values` |
| BLOCKER 2 – absolute persisted paths | transient `artifact_paths` are separated from serialized relative refs; legacy call behavior remains | 1, 10, 14, 17 | `test_v22a_artifact_refs_are_relative_and_separate_from_hash_paths` |
| BLOCKER 3 – implicit active revision | activation event + snapshot mapping select one explicit manifest only | 11, 12, 13, 16 | activation/inactive-revision/no-fallback query tests |
| BLOCKER 4 – provenance/eligibility ambiguity | one-to-one associations and qualifying subset control state transitions and provider ranking | 11, 12, 15 | smoke/local transition and qualifying-provider tests |
| BLOCKER 5 – unrepresentable query result | `EligibleDatasetSelection` returns exact binding and chosen association/capability | 12, 16 | `test_formal_lookup_returns_selected_qualifying_provenance` |
| IMPORTANT 1 – incomplete import evidence | every outcome publishes immutable import manifest binding final provenance/eligibility/snapshot where present | 10, 15, 16 | success/failure/final-link import-manifest tests |
| IMPORTANT 2 – underspecified splits/preflight | explicit Decimal formula and no-network dependency gate precede implementation | 1, 7, 17 | boundary/cumulative/rounding/preflight tests |

---

## 1. Existing Owner and Dependency Map

| Concern | Existing owner | V2.2A integration rule |
|---|---|---|
| Canonical payload hash | `tv_quant.run_manifest.canonical_hash(value: Mapping[str, Any]) -> str` | 所有 logical、identity、manifest、eligibility、registry payload 委托该函数 |
| Bytes/file SHA-256 | `sha256_bytes(payload: bytes) -> str` / `sha256_file(path: Path) -> str` | 不导入 `hashlib` 到 data-foundation modules |
| Canonical JSON validation/write | `tv_quant.run_manifest.validate_canonical_json_value` / `write_canonical_json_artifact` | strict JSON and serialized-relative-ref validation stay with the existing writer owner |
| Artifact hash binding | `bind_artifact_hashes(manifest, artifact_paths, *, persisted_refs=None)` | `artifact_paths` are transient; V2.2A writes validated refs while the absent-ref branch preserves V2.1 |
| Canonical numbers | `canonical_decimal(value, path) -> str` / `canonical_integer(value, path) -> int` | 所有价格、因子和 volume 通过现有 owner |
| Path containment | `resolve_under_root(root, relative_path) -> Path` | 在全输入 preflight、preserved read/package publish、canonical publish、registry commit 前重复调用 |
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
CanonicalJsonScalar = str | int | bool | None
CanonicalJsonValue = (
    CanonicalJsonScalar
    | tuple["CanonicalJsonValue", ...]
    | Mapping[str, "CanonicalJsonValue"]
)

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
`validate_canonical_json_value` walks every mapping key and array item before
the writer runs: keys must be strings; supported values are `None`, `bool`,
`int`, `str`, tuple/list and mapping. It rejects `float` before its finite
state is considered, so NaN and both infinities fail closed alongside `Path`,
`datetime`, `set`, `bytes`, `Decimal`, and arbitrary objects. Persisted refs
are independently checked as non-absolute, normalized `RelativePath` values.

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
class PreservedImportInputs:
    import_id: str
    inputs_root_ref: RelativePath
    preserved_inputs_hash: Sha256Hex
    market_data_ref: RelativePath
    market_data_hash: Sha256Hex
    calendar_snapshot_ref: RelativePath
    calendar_snapshot_hash: Sha256Hex
    gap_evidence_refs: tuple[RelativePath, ...]
    gap_evidence_hashes: tuple[Sha256Hex, ...]
    corporate_action_evidence_refs: tuple[RelativePath, ...]
    corporate_action_evidence_hashes: tuple[Sha256Hex, ...]

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
class ValidatedDatasetCandidate:
    import_id: str
    validated_raw_bars: tuple[DailyBarRaw, ...]
    daily_gaps: tuple[DailyGapRecord, ...]
    gap_evidence: GapEvidence
    corporate_action_events: tuple[CorporateActionEvent, ...]
    corporate_action_evidence: CorporateActionEvidence
    calendar_ref: TradingCalendarRef

@dataclass(frozen=True, slots=True)
class DailyDatasetValidationResult:
    report: DataValidationReport
    validated_candidate: ValidatedDatasetCandidate | None

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
def provenance_payload(provenance: "DatasetProvenance") -> Mapping[str, object]: ...
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
) -> DailyDatasetValidationResult: ...
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
    import_id: str
    request_hash: Sha256Hex
    preserved_inputs_hash: Sha256Hex
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
    original_file_hash: Sha256Hex | None
    import_timestamp_utc: UtcTimestamp
    preserved_inputs: PreservedImportInputs | None
    parser_version: str
    schema_version: str
    stage_statuses: Mapping[str, ValidationOutcome]
    validated_candidate_ref: RelativePath | None
    validated_candidate_hash: Sha256Hex | None
    validation_report_ref: RelativePath | None
    validation_report_hash: Sha256Hex | None
    gap_evidence_refs: tuple[RelativePath, ...]
    gap_evidence_hashes: tuple[Sha256Hex, ...]
    candidate_dataset_id: Sha256Hex | None
    final_dataset_id: Sha256Hex | None
    final_provenance_ref: RelativePath | None
    final_provenance_hash: Sha256Hex | None
    final_eligibility_ref: RelativePath | None
    final_eligibility_hash: Sha256Hex | None
    final_registry_snapshot_ref: RelativePath | None
    final_registry_snapshot_hash: Sha256Hex | None
    blocker_codes: tuple[BlockerCode, ...]

@dataclass(frozen=True, slots=True)
class PublishedImportManifest:
    manifest: DataImportManifest
    manifest_ref: RelativePath
    manifest_hash: Sha256Hex

@dataclass(frozen=True, slots=True)
class CanonicalDatasetDescriptor:
    descriptor_schema_version: str
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
    component_logical_hashes: Mapping[str, Sha256Hex]
    gap_semantic_coverage_hash: Sha256Hex
    corporate_action_semantic_coverage_hash: Sha256Hex

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

@dataclass(frozen=True, slots=True)
class PublishedCanonicalBundle:
    manifest: CanonicalDatasetManifest
    manifest_ref: RelativePath
    manifest_hash: Sha256Hex
    provenance: DatasetProvenance
    provenance_ref: RelativePath
    reused_existing: bool

@dataclass(frozen=True, slots=True)
class ProvenanceInputs:
    request: DataImportRequest
    preserved_inputs: PreservedImportInputs
    import_timestamp_utc: UtcTimestamp
    validation_report_ref: RelativePath
    validation_report_hash: Sha256Hex
    parent_dataset_id: Sha256Hex | None

@dataclass(frozen=True, slots=True)
class RegistrationDecision:
    reuse_existing: bool
    manifest_revision: int
    existing_manifest: CanonicalDatasetManifest | None
    existing_manifest_ref: RelativePath | None
    existing_manifest_hash: Sha256Hex | None
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
class ProvenanceAssociation:
    provenance_ref: RelativePath
    provenance_hash: Sha256Hex
    import_id: str
    request_hash: Sha256Hex
    provider_capability_id: str
    source_type: MarketDataSourceType
    qualifies_for_formal: bool

@dataclass(frozen=True, slots=True)
class ManifestActivationEvent:
    event_schema_version: str
    activation_event_id: Sha256Hex
    activation_event_hash: Sha256Hex
    dataset_id: Sha256Hex
    manifest_hash: Sha256Hex
    prior_manifest_hash: Sha256Hex | None
    reason_code: str
    actor_ref: str
    event_timestamp_utc: UtcTimestamp
    parent_registry_snapshot_hash: Sha256Hex

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
    provenance_associations: tuple[ProvenanceAssociation, ...]

@dataclass(frozen=True, slots=True)
class EligibleDatasetSelection:
    binding: RegistryBinding
    selected_provenance_ref: RelativePath
    selected_provenance_hash: Sha256Hex
    selected_provider_capability_id: str

@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    registry_schema_version: str
    snapshot_hash: Sha256Hex
    parent_snapshot_hash: Sha256Hex | None
    bindings: tuple[RegistryBinding, ...]
    invalidation_event_refs: tuple[RelativePath, ...]
    active_manifest_by_dataset_id: Mapping[Sha256Hex, Sha256Hex]
    manifest_activation_event_refs: tuple[RelativePath, ...]

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
    import_manifest_ref: RelativePath
    import_manifest_hash: Sha256Hex
    validation_report: DataValidationReport | None
    canonical_manifest: CanonicalDatasetManifest | None
    eligibility: DataEligibility | None
    registry_binding: RegistryBinding | None
~~~

~~~python
def publish_canonical_bundle(
    root: Path,
    bundle: LogicalDatasetBundle,
    descriptor: CanonicalDatasetDescriptor,
    decision: RegistrationDecision,
    provenance_inputs: ProvenanceInputs,
    report: DataValidationReport,
    writer_profile: Mapping[str, object],
) -> PublishedCanonicalBundle: ...

def publish_import_manifest(
    root: Path,
    manifest: DataImportManifest,
) -> PublishedImportManifest: ...

def build_canonical_descriptor(
    bundle: LogicalDatasetBundle,
    identity: DatasetIdentity,
) -> CanonicalDatasetDescriptor: ...

class MarketDataRegistry:
    @classmethod
    def load(cls, root: Path, snapshot_ref: RelativePath) -> MarketDataRegistry: ...
    @property
    def snapshot(self) -> RegistrySnapshot: ...
    @property
    def snapshot_ref(self) -> RelativePath: ...
    def binding_for_exact(
        self,
        dataset_id: Sha256Hex,
        manifest_hash: Sha256Hex,
    ) -> RegistryBinding | None: ...
    def active_binding_for(self, dataset_id: Sha256Hex) -> RegistryBinding | None: ...
    def load_manifest(self, binding: RegistryBinding) -> CanonicalDatasetManifest: ...
    def load_provenances(
        self,
        binding: RegistryBinding,
    ) -> tuple[DatasetProvenance, ...]: ...
    def register(
        self,
        manifest: CanonicalDatasetManifest,
        manifest_ref: RelativePath,
        provenance: DatasetProvenance,
        provenance_ref: RelativePath,
        eligibility: DataEligibility,
        eligibility_ref: RelativePath,
    ) -> RegistrySnapshot: ...
    def activate_manifest(
        self,
        dataset_id: Sha256Hex,
        manifest_hash: Sha256Hex,
        expected_snapshot_hash: Sha256Hex,
        reason_code: str,
        actor_ref: str,
        event_timestamp_utc: UtcTimestamp,
    ) -> tuple[ManifestActivationEvent, RegistrySnapshot]: ...

def find_latest_eligible_dataset(
    requirement: DatasetRequirement,
    registry: MarketDataRegistry,
    expected_snapshot_hash: Sha256Hex,
    capability_registry: CapabilityRegistry,
) -> EligibleDatasetSelection | DataFoundationOperationResult: ...

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
# run_manifest.py -- existing canonical JSON owner; this is not a second path
# containment owner. It only rejects nonportable serialized refs before JSON.
def validate_canonical_json_value(value: object, path: str = "$") -> None: ...
def validate_persisted_relative_ref(value: object, path: str) -> RelativePath: ...

# projections.py
def component_logical_hashes(bundle: LogicalDatasetBundle) -> Mapping[str, Sha256Hex]: ...
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
def build_validated_candidate(
    candidate: NormalizedDatasetCandidate,
    deduplicated_rows: tuple[DailyBarRaw, ...],
) -> ValidatedDatasetCandidate: ...
def run_check(
    name: str,
    check: Callable[[], tuple[DataValidationIssue, ...]],
) -> tuple[DataValidationIssue, ...]: ...

# adjustments.py
from decimal import Decimal, ROUND_HALF_EVEN, localcontext

SPLIT_METHOD_ID = "split-only-v1"
SPLIT_WORKING_PRECISION = 80
SPLIT_QUANTUM = Decimal("0.000000000001")
SPLIT_ROUNDING = ROUND_HALF_EVEN
def mul_price(value: CanonicalDecimal, factor: CanonicalDecimal) -> CanonicalDecimal: ...
def mul_volume(
    value: int | CanonicalDecimal | None,
    factor: CanonicalDecimal,
) -> int | CanonicalDecimal: ...
def factor_for_trading_date(
    factors: tuple[AdjustmentFactor, ...],
    trading_date: IsoDate,
) -> AdjustmentFactor: ...
def ordered_split_events(
    events: tuple[CorporateActionEvent, ...],
) -> tuple[CorporateActionEvent, ...]: ...
def backward_factor_for_date(
    trading_date: IsoDate,
    events: tuple[CorporateActionEvent, ...],
) -> tuple[CanonicalDecimal, CanonicalDecimal, tuple[Sha256Hex, ...]]: ...
def quantize_final_adjusted_decimal(value: Decimal) -> Decimal: ...

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
def preserve_import_inputs(
    root: Path,
    import_id: str,
    request: DataImportRequest,
) -> PreservedImportInputs: ...
def preflight_all_contained_inputs(
    root: Path,
    request: DataImportRequest,
) -> tuple[tuple[str, Path], ...]: ...
def create_preserved_inputs_staging(root: Path, import_id: str) -> Path: ...
def copy_open_input_and_verify(
    source: Path,
    staging: Path,
    role: str,
    index: int,
) -> tuple[str, RelativePath, Sha256Hex]: ...
def build_preserved_import_inputs(
    import_id: str,
    copied: tuple[tuple[str, RelativePath, Sha256Hex], ...],
) -> PreservedImportInputs: ...
def verify_preserved_input_hashes(
    root: Path,
    preserved: PreservedImportInputs,
) -> None: ...
def publish_preserved_inputs_directory(
    root: Path,
    staging: Path,
    final_ref: RelativePath,
) -> None: ...
def hash_staged_components(staging: Path) -> Mapping[str, Sha256Hex]: ...
def build_dataset_provenance(
    descriptor: CanonicalDatasetDescriptor,
    component_file_hashes: Mapping[str, Sha256Hex],
    inputs: ProvenanceInputs,
) -> DatasetProvenance: ...
def write_provenance(staging: Path, provenance: DatasetProvenance) -> RelativePath: ...
def publish_import_provenance(
    root: Path,
    import_id: str,
    provenance: DatasetProvenance,
) -> RelativePath: ...
def data_import_manifest_payload(
    manifest: DataImportManifest,
) -> Mapping[str, object]: ...
def build_complete_manifest(
    descriptor: CanonicalDatasetDescriptor,
    component_file_hashes: Mapping[str, Sha256Hex],
    provenance: DatasetProvenance,
    provenance_ref: RelativePath,
    inputs: ProvenanceInputs,
    writer_profile: Mapping[str, object],
    manifest_revision: int,
) -> CanonicalDatasetManifest: ...
def canonical_manifest_payload(
    manifest: CanonicalDatasetManifest,
) -> Mapping[str, object]: ...
def require_reusable_manifest(
    decision: RegistrationDecision,
    descriptor: CanonicalDatasetDescriptor,
) -> CanonicalDatasetManifest: ...

# registry.py
def require_exact_manifest_hash(
    manifest: CanonicalDatasetManifest,
    manifest_hash: Sha256Hex,
) -> None: ...
def descriptor_payload(
    descriptor: CanonicalDatasetDescriptor,
) -> Mapping[str, object]: ...
def descriptor_from_manifest(
    manifest: CanonicalDatasetManifest,
) -> CanonicalDatasetDescriptor: ...
def association_for_provenance(
    provenance: DatasetProvenance,
    provenance_ref: RelativePath,
) -> ProvenanceAssociation: ...
def merge_provenance_associations(
    prior: tuple[ProvenanceAssociation, ...],
    new: ProvenanceAssociation,
) -> tuple[ProvenanceAssociation, ...]: ...
def qualifying_association_hashes(
    associations: tuple[ProvenanceAssociation, ...],
) -> tuple[Sha256Hex, ...]: ...
def build_hashed_eligibility(**fields: object) -> DataEligibility: ...
def verify_binding(
    manifest: CanonicalDatasetManifest,
    manifest_hash: Sha256Hex,
    eligibility: DataEligibility,
    associations: tuple[ProvenanceAssociation, ...],
) -> None: ...
def build_registry_snapshot(
    parent_hash: Sha256Hex | None,
    bindings: tuple[RegistryBinding, ...],
    invalidation_event_refs: tuple[RelativePath, ...],
    active_manifest_by_dataset_id: Mapping[Sha256Hex, Sha256Hex],
    manifest_activation_event_refs: tuple[RelativePath, ...],
) -> RegistrySnapshot: ...
def upsert_current_binding(
    bindings: tuple[RegistryBinding, ...],
    replacement: RegistryBinding,
) -> tuple[RegistryBinding, ...]: ...
def publish_registry_snapshot_atomically(root: Path, snapshot: RegistrySnapshot) -> None: ...
def verify_and_filter_bindings(
    registry: MarketDataRegistry,
    requirement: DatasetRequirement,
    expected_snapshot_hash: Sha256Hex,
) -> tuple[RegistryBinding, ...]: ...
def load_eligibility(binding: RegistryBinding) -> DataEligibility: ...
def select_qualifying_association(
    binding: RegistryBinding,
    eligibility: DataEligibility,
    provider_capability_id: str,
) -> ProvenanceAssociation | None: ...
def select_without_content_conflict(
    selections: tuple[EligibleDatasetSelection, ...],
) -> EligibleDatasetSelection: ...
def require_explicit_active_binding(
    registry: MarketDataRegistry,
    dataset_id: Sha256Hex,
) -> RegistryBinding | None: ...
def capability_blocker(issue_code: str) -> DataFoundationOperationResult: ...
def replace_prior_as_invalidated(
    prior: DataEligibility,
    event_id: Sha256Hex,
    event_hash: Sha256Hex,
) -> DataEligibility: ...
class RegistryTransaction:
    def stage_json(self, name: str, payload: Mapping[str, object]) -> None: ...
    def verify_all_hashes(self) -> None: ...
    def publish_transaction_directory(self) -> RelativePath: ...
    def activate_snapshot_pointer_last(self) -> None: ...

def registry_transaction(
    root: Path,
    expected_snapshot_hash: Sha256Hex,
) -> ContextManager[RegistryTransaction]: ...

# path_safety.py
def existing_ancestors(path: Path) -> tuple[Path, ...]: ...
def is_reparse_point(path: Path) -> bool: ...
def volume_identity(path: Path) -> tuple[int, int]: ...

# importer.py
def finalize_and_publish_import_manifest(
    root: Path,
    manifest: DataImportManifest,
    operation: DataFoundationOperationResult,
    validation_report: DataValidationReport | None,
    canonical_manifest: CanonicalDatasetManifest | None,
    eligibility: DataEligibility | None,
    registry_binding: RegistryBinding | None,
) -> ImportLocalDatasetResult: ...
def load_preserved_calendar(
    preserved: PreservedImportInputs,
    runtime: DataImportRuntimeContext,
) -> TradingCalendarRef: ...
def load_preserved_evidence(
    preserved: PreservedImportInputs,
    runtime: DataImportRuntimeContext,
) -> tuple[
    tuple[DailyGapRecord, ...],
    GapEvidence,
    tuple[CorporateActionEvent, ...],
    CorporateActionEvidence,
]: ...
def parse_by_source_type(
    preserved: PreservedImportInputs,
    request: DataImportRequest,
    runtime: DataImportRuntimeContext,
    calendar_ref: TradingCalendarRef,
) -> tuple[DailyBarRaw, ...]: ...
def assemble_candidate(
    import_id: str,
    rows: tuple[DailyBarRaw, ...],
    gaps: tuple[DailyGapRecord, ...],
    gap_evidence: GapEvidence,
    events: tuple[CorporateActionEvent, ...],
    action_evidence: CorporateActionEvidence,
    request: DataImportRequest,
    calendar_ref: TradingCalendarRef,
) -> NormalizedDatasetCandidate: ...
def finalize_failed_import(
    root: Path,
    request: DataImportRequest,
    import_id: str,
    imported_at: UtcTimestamp,
    preserved: PreservedImportInputs | None,
    error: DataFoundationError,
) -> ImportLocalDatasetResult: ...
def finalize_nonvalid_import(
    root: Path,
    request: DataImportRequest,
    import_id: str,
    imported_at: UtcTimestamp,
    preserved: PreservedImportInputs,
    candidate: NormalizedDatasetCandidate,
    report: DataValidationReport,
) -> ImportLocalDatasetResult: ...
def continue_valid_import(
    request: DataImportRequest,
    runtime: DataImportRuntimeContext,
    imported_at: UtcTimestamp,
    preserved: PreservedImportInputs,
    candidate: ValidatedDatasetCandidate,
    report: DataValidationReport,
) -> ImportLocalDatasetResult: ...
def assemble_logical_bundle(
    candidate: ValidatedDatasetCandidate,
    factors: tuple[AdjustmentFactor, ...],
    adjusted: tuple[DailyBarAdjusted, ...],
) -> LogicalDatasetBundle: ...
def check_matrix(report: DataValidationReport) -> Mapping[str, bool]: ...
def provenance_inputs(
    request: DataImportRequest,
    preserved: PreservedImportInputs,
    imported_at: UtcTimestamp,
    validation_report_ref: RelativePath,
    validation_report_hash: Sha256Hex,
) -> ProvenanceInputs: ...
def publish_eligibility(
    root: Path,
    eligibility: DataEligibility,
) -> RelativePath: ...
def finalize_successful_import(
    root: Path,
    request: DataImportRequest,
    imported_at: UtcTimestamp,
    preserved: PreservedImportInputs,
    validated_candidate_ref: RelativePath,
    validated_candidate_hash: Sha256Hex,
    report: DataValidationReport,
    published: PublishedCanonicalBundle,
    eligibility: DataEligibility,
    snapshot: RegistrySnapshot,
) -> ImportLocalDatasetResult: ...
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
| PreservedImportInputs | import_id/inputs_root_ref | N | Y | Y |
| PreservedImportInputs | preserved_inputs_hash | N | Y | Y |
| PreservedImportInputs | market-data ref/hash | N | Y | Y |
| PreservedImportInputs | calendar snapshot ref/hash | N | Y | Y |
| PreservedImportInputs | gap evidence refs/hashes | N | Y | Y |
| PreservedImportInputs | corporate-action evidence refs/hashes | N | Y | Y |
| ValidatedDatasetCandidate | validated_raw_bars | feeds identity after validation | N | Y |
| ValidatedDatasetCandidate | evidence/calendar fields | feeds identity after validation | N | Y |
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
| CorporateActionEvent | cash_amount/cash_currency | N; CASH_DIVIDEND blocks before identity | Y | Y |
| CorporateActionEvidence | evidence_schema_version | N | Y | Y |
| CorporateActionEvidence | evidence_id/evidence_hash | N | Y | Y |
| CorporateActionEvidence | semantic_coverage_hash | Y | N | Y |
| CorporateActionEvidence | coverage_state | Y | N | Y |
| CorporateActionEvidence | listing/range/calendar fields | Y | N | Y |
| CorporateActionEvidence | event_ids/events_hash | Y | N | Y |
| CorporateActionEvidence | source/provider/original-file fields | N | Y | Y |
| CorporateActionEvidence | source_event_refs | N | Y | Y |
| CorporateActionEvidence | validation_status/blocker_codes | N | Y | Y |
| DatasetProvenance | provenance_id/provenance_hash/import_id/request_hash/preserved_inputs_hash | N | Y | Y |
| DatasetProvenance | provider/source/original-file fields | N | Y | Y |
| DatasetProvenance | import_timestamp_utc | N | Y | Y |
| DatasetProvenance | schema/calendar/timezone fields | N | Y | Y |
| DatasetProvenance | adjustment/range/count fields | N | Y | Y |
| DatasetProvenance | component logical/file hashes | N | Y | Y |
| DatasetProvenance | gap evidence full/semantic hashes | N | Y | Y |
| DatasetProvenance | validation_status/blockers | N | Y | Y |
| DatasetProvenance | parent_dataset_id/dataset_id/content_hash | N | Y | Y |
| DatasetProvenance | dependency_hashes | N | Y | Y |
| CanonicalDatasetDescriptor | DatasetIdentity/logical schema/calendar/timezone | Y | N | transient |
| CanonicalDatasetDescriptor | stable key/ranges/counts | Y | N | transient |
| CanonicalDatasetDescriptor | component logical/semantic coverage hashes | Y | N | transient |
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
| DataImportManifest | preserved_inputs | N | Y | Y |
| DataImportManifest | final provenance/eligibility/registry snapshot refs/hashes | N | Y | Y |
| PublishedImportManifest | manifest ref/hash | N | Y | Y |
| ProvenanceAssociation | exact provenance ref/hash/import/provider capability/formal qualifier | N | Y | Y |
| RegistryBinding | provenance associations and eligibility pointer | N | Y | Y |
| ManifestActivationEvent | active manifest selection/audit fields | N | Y | Y |
| RegistrySnapshot | explicit active-manifest mapping/activation refs | N | Y | Y |

Physical Parquet parameters never enter `DatasetIdentity`. Logical and physical
hashes remain separate. No projection function may call a new hash helper;
all projections terminate at `tv_quant.run_manifest.canonical_hash`.
`CanonicalDatasetDescriptor` contains only the identity-bearing logical fields
listed above. Component file hashes, all physical refs, provenance/report
refs and hashes, writer results and physical profiles are prohibited from the
descriptor and therefore cannot be used to decide logical reuse.

## 5. Design-to-Test Traceability Matrix

| Design requirement | Task | Test file | Test name | Expected result |
|---|---:|---|---|---|
| CSV/Parquet logical equivalence | 16 | `tests/data_foundation/test_end_to_end.py` | `test_csv_parquet_reimport_query_and_invalidation_lifecycle` | validated canonical rows and dataset IDs match |
| out-of-order input remains blocked | 8 | `tests/data_foundation/test_validation.py` | `test_out_of_order_input_remains_blocked` | BLOCKED; validated candidate is None |
| parser does not sort before validation | 4 | `tests/data_foundation/test_parsers.py` | `test_parsers_preserve_out_of_order_source_sequence` | parsed tuple retains source order |
| parser reads preserved raw copy | 15 | `tests/data_foundation/test_importer.py` | `test_parser_receives_only_preserved_market_data_path` | parser path is under `raw/<import_id>/inputs` |
| modified original after preservation does not affect import | 15 | `tests/data_foundation/test_importer.py` | `test_original_mutation_after_preservation_cannot_change_import` | result follows preserved hash/bytes |
| all evidence/calendar inputs are preserved and hashed | 10 | `tests/data_foundation/test_artifacts.py` | `test_preservation_package_contains_and_hashes_every_declared_input` | all declared inputs have immutable refs and verified hashes |
| identical duplicate is absent from canonical rows | 8, 15 | `tests/data_foundation/test_importer.py` | `test_identical_duplicate_is_absent_from_canonical_rows` | one canonical raw row; audit issue retained |
| validated candidate is the canonicalization input | 15 | `tests/data_foundation/test_importer.py` | `test_canonicalization_receives_validated_candidate_only` | original normalized rows never reach adjustment/identity/publication |
| provenance is built after component file hashes exist | 10 | `tests/data_foundation/test_artifacts.py` | `test_provenance_is_built_only_after_component_file_hashes` | provenance contains verified staged or reused file hashes |
| no incomplete manifest candidate | 10 | `tests/data_foundation/test_artifacts.py` | `test_manifest_is_built_only_after_physical_and_lineage_hashes` | manifest construction cannot precede components/provenance/report hashes |
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
| invalidation transaction has no partial active visibility | 13 | `tests/data_foundation/test_invalidation.py` | `test_invalidation_transaction_has_no_partial_active_visibility` | old pointer remains active; no partial triple is active |
| invalidation replay idempotency | 13 | `tests/data_foundation/test_invalidation.py` | `test_identical_invalidation_replay_reuses_triple` | same three hashes returned |
| one current binding per dataset_id + manifest_hash | 11 | `tests/data_foundation/test_registry.py` | `test_register_upserts_one_current_binding_per_exact_pair` | exactly one current binding in new snapshot |
| equivalent re-import updates provenance on same binding | 12 | `tests/data_foundation/test_registry_query.py` | `test_identical_reimport_updates_same_binding_provenances` | same artifacts/revision and binding key; two provenances |
| identity claim mismatch fails closed | 12 | `tests/data_foundation/test_registry_query.py` | `test_claimed_dataset_id_rejects_logical_mismatch` | DATA_VALIDATION_BLOCKER / IDENTITY_CLAIM_MISMATCH |
| invalidation removes the only current VALID eligibility | 13 | `tests/data_foundation/test_invalidation.py` | `test_invalidation_replaces_only_current_valid_eligibility` | exact current binding points only to INVALIDATED eligibility |
| manifest/eligibility one-way reference | 10 | `tests/data_foundation/test_artifacts.py` | `test_manifest_has_no_eligibility_back_reference` | manifest payload has no eligibility fields |
| path traversal and Windows special paths | 14 | `tests/data_foundation/test_security.py` | `test_windows_special_paths_and_reparse_escape_are_rejected` | CONFIG_VALIDATION_BLOCKER before read/write |
| request excludes absolute root | 2 | `tests/data_foundation/test_contracts.py` | `test_runtime_root_is_not_serializable_or_hashable` | request hash unchanged; serialization rejected |
| NYSE half-day and DST UTC sessions | 5 | `tests/data_foundation/test_calendar.py` | `test_xnys_half_day_and_dst_sessions_are_frozen` | exact UTC opens/closes |
| corporate-action lineage excluded from factor identity | 7 | `tests/data_foundation/test_adjustments.py` | `test_evidence_lineage_does_not_change_factor_identity` | factor IDs equal |
| cash dividend returns NOT_IMPLEMENTED | 7, 8, 15 | `tests/data_foundation/test_importer.py` | `test_cash_dividend_returns_not_implemented_without_outputs` | DATA_CAPABILITY_BLOCKER; no validated candidate/canonical/eligibility |
| full local import orchestration | 15 | `tests/data_foundation/test_importer.py` | `test_valid_local_csv_publishes_complete_binding` | immutable manifest + VALID binding |
| static duplicate-owner/security checks | 17 | `tests/data_foundation/test_static_ownership.py` | `test_data_foundation_reuses_existing_owners_and_has_no_network_path` | no forbidden definitions/imports |
| V2.1 regression | 17 | existing full suite | `py -3.14 -m pytest tests -q` | 517 existing tests plus V2.2A tests pass |

| canonical JSON rejects non-JSON values | 1 | `tests/data_foundation/test_registration.py` | `test_canonical_json_rejects_non_json_values` | Path/datetime/set/bytes/float/custom objects fail closed |
| absolute root absent from persisted artifacts | 1, 10, 17 | `tests/data_foundation/test_artifacts.py` | `test_persisted_v22a_payloads_never_contain_absolute_root` | no serialized value contains runtime root |
| artifact file paths and persisted refs are separate | 1 | `tests/contracts/test_artifact_contract.py` | `test_v22a_artifact_refs_are_relative_and_separate_from_hash_paths` | transient paths hash files; persisted payload has refs only |
| explicit active manifest revision only | 11 | `tests/data_foundation/test_registry.py` | `test_activate_manifest_records_explicit_mapping_and_event` | snapshot mapping/event selects exact hash |
| inactive higher revision is not automatically selected | 12 | `tests/data_foundation/test_registry_query.py` | `test_formal_lookup_ignores_inactive_higher_revision` | higher revision is ignored without activation |
| active invalidated revision does not silently fall back | 13 | `tests/data_foundation/test_invalidation.py` | `test_active_invalidated_revision_has_no_fallback` | typed blocker; active mapping remains invalidated hash |
| smoke then formal produces current VALID | 11 | `tests/data_foundation/test_registry.py` | `test_smoke_then_local_transition_upgrades_current_to_valid` | VALID and formal eligible |
| formal then smoke keeps current VALID | 11 | `tests/data_foundation/test_registry.py` | `test_local_then_smoke_transition_keeps_current_valid` | VALID is retained |
| provider preference uses qualifying provenance only | 12 | `tests/data_foundation/test_registry_query.py` | `test_provider_preference_uses_qualifying_associations_only` | non-qualifying provider cannot rank selection |
| selected provenance is returned by formal lookup | 12 | `tests/data_foundation/test_registry_query.py` | `test_formal_lookup_returns_selected_qualifying_provenance` | exact binding/ref/hash/capability returned |
| provenance contains unique import_id | 15 | `tests/data_foundation/test_importer.py` | `test_repeat_same_file_provider_fixed_clock_has_distinct_provenance_import_ids` | distinct import IDs and provenance hashes |
| successful and failed imports publish immutable import manifests | 15 | `tests/data_foundation/test_importer.py` | `test_successful_and_failed_imports_publish_immutable_import_manifests` | result always has ref/hash and stored payload |
| finalized import manifest binds provenance/eligibility/registry | 15 | `tests/data_foundation/test_importer.py` | `test_success_import_manifest_binds_final_provenance_eligibility_and_registry` | final refs/hashes match returned records |
| split effective-date boundary | 7 | `tests/data_foundation/test_adjustments.py` | `test_split_backward_adjustment_excludes_event_on_effective_bar` | only events with effective date later than bar apply |
| cumulative split factors | 7 | `tests/data_foundation/test_adjustments.py` | `test_split_backward_adjustment_uses_cumulative_later_events` | reciprocal price/direct volume products |
| split rounding and deterministic precision | 7 | `tests/data_foundation/test_adjustments.py` | `test_split_adjustment_quantizes_once_with_half_even_precision` | Decimal-only, deterministic, no intermediate rounding |
| missing exchange-calendars stops before Task 1 execution | 1 | `tests/data_foundation/test_registration.py` | `test_pre_task1_dependency_preflight_stops_when_required_version_missing` | dependency gate exits before write/test task work |

### 5.1 Test helper contract

Every helper name used in a test snippet is a private function defined above
the test in that same test module. The implementation follows these signatures;
helpers construct public records or local `tmp_path` state and never bypass a
production validation, publication, eligibility or registry gate.

~~~python
def valid_request(**changes: object) -> DataImportRequest: ...
def canonical_json_values() -> tuple[object, ...]: ...
def persisted_payloads(root: Path) -> tuple[Mapping[str, object], ...]: ...
def valid_eligibility_fields() -> dict[str, object]: ...
def dataclass_payload(value: object) -> Mapping[str, object]: ...
def utc_clock() -> datetime: ...
def uuid_factory() -> UUID: ...
def raw_bar(**changes: object) -> DailyBarRaw: ...
def bar(*, date: IsoDate = "2026-01-09", **changes: object) -> DailyBarRaw: ...
def bundle_with(**changes: object) -> LogicalDatasetBundle: ...
def gap_evidence(**changes: object) -> GapEvidence: ...
def csv_request(**changes: object) -> DataImportRequest: ...
def parquet_request(**changes: object) -> DataImportRequest: ...
def calendar() -> TradingCalendarRef: ...
def write_equivalent_parquet(root: Path, rows: tuple[DailyBarRaw, ...]) -> Path: ...
def write_out_of_order_csv(root: Path, dates: tuple[IsoDate, ...]) -> Path: ...
def write_out_of_order_parquet(root: Path, dates: tuple[IsoDate, ...]) -> Path: ...
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
def validated_candidate_with(
    *rows: DailyBarRaw,
    **changes: object,
) -> ValidatedDatasetCandidate: ...
def conflicting_rows() -> tuple[DailyBarRaw, DailyBarRaw]: ...
def earlier_bar() -> DailyBarRaw: ...
def later_bar() -> DailyBarRaw: ...
def cash_dividend_event() -> CorporateActionEvent: ...
def split_event(*, effective_date: IsoDate, ratio: CanonicalDecimal) -> CorporateActionEvent: ...
def apply_split_decimal(value: CanonicalDecimal, ratio: CanonicalDecimal) -> CanonicalDecimal: ...
def bundle(**changes: object) -> LogicalDatasetBundle: ...
def identity_for(value: LogicalDatasetBundle) -> DatasetIdentity: ...
def claimed_identity(
    value: LogicalDatasetBundle,
    **changes: object,
) -> DatasetIdentity: ...
def writer_profile(**changes: object) -> Mapping[str, object]: ...
def request_with_market_calendar_gap_and_action_inputs(root: Path) -> DataImportRequest: ...
def record_provenance_file_hash_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> list[Mapping[str, Sha256Hex]]: ...
def record_publication_build_order(monkeypatch: pytest.MonkeyPatch) -> list[str]: ...
def record_canonical_write_attempts(monkeypatch: pytest.MonkeyPatch) -> list[Path]: ...
def publish_reuse(
    root: Path,
    existing: PublishedCanonicalBundle,
    value: LogicalDatasetBundle,
) -> PublishedCanonicalBundle: ...
def publish_bundle(root: Path, value: LogicalDatasetBundle, profile: Mapping[str, object]) -> PublishedCanonicalBundle: ...
def read_table(bundle: PublishedCanonicalBundle, component: str) -> pa.Table: ...
def read_manifest(bundle: PublishedCanonicalBundle) -> Mapping[str, object]: ...
def manifest(**changes: object) -> CanonicalDatasetManifest: ...
def manifest_hash() -> Sha256Hex: ...
def smoke_provenance() -> DatasetProvenance: ...
def local_provenance() -> DatasetProvenance: ...
def association(provenance: DatasetProvenance, *, qualifies: bool) -> ProvenanceAssociation: ...
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
def requirement(**changes: object) -> DatasetRequirement: ...
def smoke_registry() -> MarketDataRegistry: ...
def snapshot_hash() -> Sha256Hex: ...
def capabilities() -> CapabilityRegistry: ...
def registry_with_two_revisions() -> MarketDataRegistry: ...
def registry_with_active_and_inactive_revisions() -> MarketDataRegistry: ...
def qualifying_registry() -> MarketDataRegistry: ...
def activate_exact_manifest(
    registry: MarketDataRegistry,
    dataset_id: Sha256Hex,
    manifest_hash: Sha256Hex,
) -> tuple[ManifestActivationEvent, RegistrySnapshot]: ...
def binding(snapshot: RegistrySnapshot, manifest_hash: Sha256Hex) -> RegistryBinding: ...
def invalidate_twice_same_request() -> tuple[InvalidationEvent, DataEligibility, RegistrySnapshot]: ...
def invalidate_once() -> tuple[InvalidationEvent, DataEligibility, RegistrySnapshot]: ...
def inject_invalidation_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None: ...
def invalidate_fixture_binding(
    root: Path,
) -> tuple[InvalidationEvent, DataEligibility, RegistrySnapshot]: ...
def active_invalidation_records(root: Path) -> tuple[RelativePath, ...]: ...
def active_snapshot_pointer(root: Path) -> RelativePath: ...
def orphan_transaction_directories(root: Path) -> tuple[RelativePath, ...]: ...
def record_verify_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]: ...
def record_input_preflight_and_copy_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]: ...
def unsafe_last_evidence_request() -> DataImportRequest: ...
def mutate_during_preserved_copy(monkeypatch: pytest.MonkeyPatch) -> None: ...
def publish_contained_bundle() -> PublishedCanonicalBundle: ...
def valid_csv_request() -> DataImportRequest: ...
def runtime(root: Path, *, fixed_clock: bool = False) -> DataImportRuntimeContext: ...
def preserved_inputs(root: Path, import_id: str = "import-1") -> PreservedImportInputs: ...
def mutate_original_inputs_after_preservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None: ...
def all_preserved_hashes(preserved: PreservedImportInputs) -> tuple[Sha256Hex, ...]: ...
def hashes_of_declared_inputs(
    root: Path,
    request: DataImportRequest,
) -> tuple[Sha256Hex, ...]: ...
def identity_from_preserved_bytes(
    root: Path,
    preserved: PreservedImportInputs,
) -> DatasetIdentity: ...
def request_with_identical_duplicate() -> DataImportRequest: ...
def cash_dividend_request() -> DataImportRequest: ...
def missing_source_request() -> DataImportRequest: ...
def record_parser_paths(monkeypatch: pytest.MonkeyPatch) -> list[Path]: ...
def record_canonicalization_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> list[ValidatedDatasetCandidate]: ...
def read_canonical_component(
    result: ImportLocalDatasetResult,
    component_name: str,
) -> pa.Table: ...
def import_with_forced_outcome(outcome: ValidationOutcome) -> ImportLocalDatasetResult: ...
def read_import_manifest(root: Path, result: ImportLocalDatasetResult) -> Mapping[str, object]: ...
def import_with_gap_reason(reason: GapReasonCode) -> ImportLocalDatasetResult: ...
def spy_csv_request() -> DataImportRequest: ...
def spy_parquet_request() -> DataImportRequest: ...
def load_registry(root: Path) -> MarketDataRegistry: ...
def load_snapshot(snapshot: RegistrySnapshot) -> MarketDataRegistry: ...
def invalidate_exact_binding(binding: RegistryBinding, root: Path) -> tuple[InvalidationEvent, DataEligibility, RegistrySnapshot]: ...
def fixture_calendar() -> TradingCalendarRef: ...
def fixture_spy_rows() -> tuple[DailyBarRaw, ...]: ...
def read_validated_rows(
    root: Path,
    manifest: DataImportManifest,
) -> tuple[DailyBarRaw, ...]: ...
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
    persisted_refs: Mapping[str, RelativePath] | None = None,
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

- [ ] **Step 0: Run the no-network dependency preflight before Task 1 work**

Run this command before creating Task 1 files, changing requirements, or
running its RED suite. It inspects installed distribution metadata only and
must not contain `pip`, `install`, an index URL, or a network client:

~~~powershell
$required = @{
  "exchange-calendars" = "4.13.2"
  "pyarrow" = "25.0.0"
}
$missing = foreach ($entry in $required.GetEnumerator()) {
  $raw = py -3.14 -c "import importlib.metadata as m; print(m.version('$($entry.Key)'))" 2>$null
  $actual = if ($null -eq $raw) { "" } else { ([string]$raw).Trim() }
  if ($LASTEXITCODE -ne 0 -or $actual -ne $entry.Value) {
    "$($entry.Key)==$($entry.Value) (installed: $actual)"
  }
}
if ($missing) { throw "V2.2A dependency preflight failed; stop before Task 1: $($missing -join '; ')" }
~~~

Expected: both exact versions are installed. If either is missing or wrong,
stop the implementation plan immediately, report the missing dependency, and
do not install, download, or otherwise modify the environment.

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

@pytest.mark.parametrize("value", [
    Path("x"), datetime(2026, 8, 2), {"x"}, b"x", float("nan"),
    float("inf"), object(),
])
def test_canonical_json_rejects_non_json_values(tmp_path: Path, value: object) -> None:
    with pytest.raises(TypeError, match="canonical JSON"):
        write_canonical_json_artifact(tmp_path / "x.json", {"value": value})

def test_v22a_artifact_refs_are_relative_and_separate_from_hash_paths(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    path.write_text("{}", encoding="utf-8")
    bound = bind_artifact_hashes(
        {"schema_version": "v2.2a"}, {"report": path},
        persisted_refs={"report": "reports/import-1/report.json"},
        hashed_names=("report",),
    )
    assert bound["artifact_refs"] == {"report": "reports/import-1/report.json"}
    assert "artifact_paths" not in bound and str(tmp_path) not in json.dumps(bound)
~~~

- [ ] **Step 2: Run RED focused tests**

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
def bind_artifact_hashes(
    manifest, artifact_paths, *, persisted_refs=None,
    hashed_names=HASHED_ARTIFACT_NAMES,
):
    names = tuple(hashed_names)
    missing = tuple(name for name in names if name not in artifact_paths)
    if missing:
        raise ValueError(f"artifact_paths: missing {missing!r}")
    bound = dict(manifest)
    bound["artifact_hashes"] = {name: sha256_file(Path(artifact_paths[name])) for name in names}
    if persisted_refs is None:  # frozen V2.1 compatibility branch
        bound["artifact_paths"] = {
            name: str(artifact_paths[name]) for name in sorted(artifact_paths)
        }
    else:  # mandatory V2.2A branch
        if set(persisted_refs) != set(artifact_paths):
            raise ValueError("persisted_refs: exact artifact key set required")
        bound["artifact_refs"] = {
            name: validate_persisted_relative_ref(persisted_refs[name], f"artifact_refs.{name}")
            for name in sorted(persisted_refs)
        }
    if persisted_refs is None and "strategy_config" in artifact_paths:
        bound["strategy_config_path"] = str(artifact_paths["strategy_config"])
        bound["strategy_config_file_hash"] = sha256_file(Path(artifact_paths["strategy_config"]))
    return bound

def write_canonical_json_artifact(path, payload):
    validate_canonical_json_value(payload)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
        newline="\n",
    )
~~~

`artifact_paths` is never serialized by the V2.2A branch: it exists only while
`sha256_file` reads bytes. `persisted_refs` must be exact-key, validated
relative refs, and every Task 10+ caller supplies it. The `persisted_refs is
None` branch is the frozen V2.1 behavior, including its legacy
`artifact_paths`/`strategy_config_path` fields. V2.2A manifests, provenance,
registry snapshots, eligibility and import manifests reject absolute strings
at their payload constructors as a second defense.

`write_data_provenance` keeps its legacy payload when `payload is None`. In
typed mode it validates `schema_version == "v2.2a"`, writes sorted UTF-8 JSON,
and never computes a hash itself.
`write_canonical_json_artifact` lives in `tv_quant.run_manifest` and owns
sorted-key, UTF-8, fixed-separator JSON serialization for validation reports,
manifests, eligibilities, registry snapshots and invalidation events. V2.2A
modules assemble typed payloads and delegate every JSON write to this owner.
The same validator is called by `canonical_hash` before canonical encoding, so
hash-time and write-time payload acceptance cannot diverge; V2.1 payload tests
must continue to pass without stringifying unsupported runtime objects.

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
- Produces: scalar/enums plus request/runtime, preserved-input, market record,
  evidence, validation, normalized/validated candidate, logical bundle,
  operation and import-result contracts in Sections 3.1-3.3. Task 3 completes
  `DatasetIdentity`; Task 9 completes `CanonicalDatasetDescriptor`; Task 10
  completes provenance/manifest/publication/registration-decision contracts;
  Task 11 completes eligibility/binding/snapshot contracts; Task 13 completes
  invalidation contracts.
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
`DataImportManifest.preserved_inputs` may be `None` only when failure occurs
before raw-package publication, and only that branch permits
`original_file_hash=None`. Otherwise `original_file_hash` equals
`preserved_inputs.market_data_hash`, and the manifest gap refs/hashes equal the
preserved gap-evidence refs/hashes. Successful, blocked-after-preservation,
incomplete and not-implemented manifests all persist the complete
`PreservedImportInputs`, including calendar and corporate-action evidence.

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
    hashes = component_logical_hashes(bundle)
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
hashing; do not deduplicate in projection code. These canonical sort helpers
accept only a `LogicalDatasetBundle` assembled from `ValidatedDatasetCandidate`;
no parser or pre-validation call site may invoke them.

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

- [ ] **Step 1: Write strict parser and raw-order preservation tests**

~~~python
def test_parsers_preserve_out_of_order_source_sequence(tmp_path: Path) -> None:
    expected_dates = ("2026-01-05", "2026-01-02")
    csv_path = write_out_of_order_csv(tmp_path, expected_dates)
    parquet_path = write_out_of_order_parquet(tmp_path, expected_dates)

    csv_rows = parse_csv_source(csv_path, csv_request(), calendar())
    parquet_rows = parse_parquet_source(parquet_path, parquet_request(), calendar())

    assert tuple(row.trading_date for row in csv_rows) == expected_dates
    assert tuple(row.trading_date for row in parquet_rows) == expected_dates
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
return rows
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
return tuple(
    normalize_source_row(row, row_ref=f"parquet:{index}",
                         request=request, calendar_ref=calendar_ref)
    for index, row in enumerate(table.to_pylist())
)
~~~

Do not trust the file extension. Reject unsupported dictionary/timezone/null
metadata unless the profile explicitly fixes their interpretation. Both parser
adapters preserve the exact input sequence and may neither sort nor deduplicate;
order and duplicate policy belongs exclusively to Task 8 validation.

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_parsers.py -q`

Expected: PASS; both adapters preserve even an invalid out-of-order sequence.

- [ ] **Step 6: Refactor shared row decoding, then run targeted and data-quality regression**

Make `parse_csv_source` and `parse_parquet_source` delegate only to the shared
`normalize_source_row`; keep adapter-specific file/schema checks in their own
functions. Inspect both return paths to prove neither calls `sorted`,
`stable_row_key`, `dict.fromkeys`, `set` or a duplicate-removal helper.

Run:
`py -3.14 -m pytest tests/data_foundation/test_parsers.py tests/contracts/test_numeric_canonicalization.py tests/test_data_quality.py -q`

Expected: PASS; no parser silently coerces invalid numeric inputs, repairs row
order or removes duplicates. CSV/Parquet logical equivalence is deliberately
deferred to validated canonical rows in Task 16.

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
    left = derive_adjustment_factors(events(), evidence(source_name="a"), "split-only-v1")
    right = derive_adjustment_factors(events(), evidence(source_name="b"), "split-only-v1")
    assert tuple(f.adjustment_factor_id for f in left) == tuple(
        f.adjustment_factor_id for f in right
    )
    assert left[0].corporate_action_evidence_hash != right[0].corporate_action_evidence_hash

def test_no_actions_range_produces_identity_factor() -> None:
    factors = derive_adjustment_factors((), no_actions_evidence(), "split-only-v1")
    assert factors == (identity_factor(price="1", volume="1"),)

def test_cash_dividend_is_an_explicit_capability_blocker() -> None:
    issues = validate_corporate_action_coverage(
        (cash_dividend_event(),), evidence(), calendar()
    )
    assert issues[0].issue_code == "CASH_DIVIDEND_NOT_IMPLEMENTED"
    assert issues[0].mapped_blocker_code is BlockerCode.DATA_CAPABILITY_BLOCKER
    with pytest.raises(DataFoundationError, match="CASH_DIVIDEND_NOT_IMPLEMENTED"):
        derive_adjustment_factors(
            (cash_dividend_event(),), evidence(), "split-only-v1"
        )
~~~

Add split direction, bad dates, source-event ref mismatch, duplicate conflicting
event ID, unsupported method, adjusted OHLC rules, and adjusted-only input
rejection. Add these frozen boundary/precision tests:

~~~python
def test_split_backward_adjustment_excludes_event_on_effective_bar() -> None:
    rows = (bar(date="2026-01-09"), bar(date="2026-01-10"))
    event = split_event(effective_date="2026-01-10", ratio="2")
    adjusted = apply_adjustments(rows, derive_adjustment_factors((event,), evidence(), "split-only-v1"), "split-only-v1")
    assert adjusted[0].adjusted_close == "50"
    assert adjusted[1].adjusted_close == "100"

def test_split_backward_adjustment_uses_cumulative_later_events() -> None:
    events = (split_event(effective_date="2026-01-10", ratio="2"),
              split_event(effective_date="2026-01-20", ratio="3"))
    factor = factor_for_trading_date(derive_adjustment_factors(events, evidence(), "split-only-v1"), "2026-01-09")
    assert (factor.price_factor, factor.volume_factor) == ("0.166666666667", "6")

def test_split_adjustment_quantizes_once_with_half_even_precision() -> None:
    assert apply_split_decimal("1", "6") == "0.166666666667"
    assert apply_split_decimal("1", "2.000000000002") == "0.499999999999"
    assert apply_split_decimal("1", "6") == apply_split_decimal("1", "6")
~~~

The only supported first-release method is `split-only-v1`; no combined
split-and-dividend method or cash-dividend formula exists.

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

`split-only-v1` is frozen as follows. It normalizes all ratio/value strings
through the existing finite numeric owner, converts them to `Decimal`, and runs
the multiplication/division sequence under `localcontext().prec == 80`. For a
bar date `d`, include exactly SPLIT events `e` where
`e.effective_trading_date > d`, order them by
`(effective_trading_date, event_id)`, and calculate on the latest basis:

~~~text
price_factor(d)  = product(Decimal("1") / e.split_ratio for e in ordered_later_events)
volume_factor(d) = product(e.split_ratio for e in ordered_later_events)
adjusted_price   = raw_price * price_factor(d)
adjusted_volume  = raw_volume * volume_factor(d)
~~~

No intermediate `quantize`, float conversion or rounding is permitted.
Immediately before serialization, each adjusted decimal is quantized once to
`Decimal("0.000000000001")` with `ROUND_HALF_EVEN`; price uses
`canonical_decimal`. Volume uses the same final quantization and then
`canonical_integer` only if the quantized value is integral, otherwise
`canonical_decimal`. `NO_ACTIONS_IN_RANGE` produces the exact `("1", "1")`
identity factor. The existing unique numeric policy is canonical finite-string
serialization and has no rounding quantum; therefore this method-specific final
quantization does not conflict. If implementation finds another unique numeric
owner specifying a conflicting quantization or rounding rule, stop and report
the conflict instead of selecting a rule.

`mul_price` and `mul_volume` use `Decimal` only internally and serialize through
the final conversion rule above. SPLIT fixes reciprocal price and direct volume
direction in `split-only-v1`. Any `CASH_DIVIDEND` event yields a
`CASH_DIVIDEND_NOT_IMPLEMENTED` issue mapped to
`DATA_CAPABILITY_BLOCKER`; `derive_adjustment_factors` repeats that fail-closed
guard and never constructs factors for the unsupported event.

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_adjustments.py -q`

Expected: PASS; split and identity-factor paths preserve raw bars
byte-for-byte/dataclass-equal, while cash dividends are rejected without an
adjusted output.

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
- Produces:
  `validate_daily_dataset(candidate) -> DailyDatasetValidationResult`, where a
  non-`None` `ValidatedDatasetCandidate` is the only downstream data input, and:

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
    result = validate_daily_dataset(candidate_with(**{field: value}))
    assert result.report.validation_status is ValidationOutcome.BLOCKED
    assert result.validated_candidate is None
    assert BlockerCode.DATA_VALIDATION_BLOCKER in result.report.blocker_codes

def test_identical_duplicate_is_audited_and_removed_from_validated_candidate() -> None:
    result = validate_daily_dataset(candidate_with(bar(), bar()))
    assert result.report.validation_status is ValidationOutcome.VALID
    assert tuple(issue.issue_code for issue in result.report.issues) == (
        "DEDUPLICATED_IDENTICAL",
    )
    assert len(result.validated_candidate.validated_raw_bars) == 1

def test_out_of_order_input_remains_blocked() -> None:
    result = validate_daily_dataset(candidate_with(later_bar(), earlier_bar()))
    assert result.report.validation_status is ValidationOutcome.BLOCKED
    assert "OUT_OF_ORDER" in {issue.issue_code for issue in result.report.issues}
    assert result.validated_candidate is None

def test_cash_dividend_validation_has_no_candidate() -> None:
    result = validate_daily_dataset(candidate_with(
        corporate_action_events=(cash_dividend_event(),),
        corporate_action_evidence=evidence(),
    ))
    assert result.report.validation_status is ValidationOutcome.NOT_IMPLEMENTED
    assert result.report.blocker_codes == (BlockerCode.DATA_CAPABILITY_BLOCKER,)
    assert result.validated_candidate is None
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
def validate_daily_dataset(
    candidate: NormalizedDatasetCandidate,
) -> DailyDatasetValidationResult:
    issues: list[DataValidationIssue] = []
    issues.extend(validate_order_and_unique_keys(candidate.raw_bars))
    rows, duplicate_issues = deduplicate_identical_rows(candidate.raw_bars)
    issues.extend(duplicate_issues)
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
    report = build_validation_report(candidate, ordered_issues(issues))
    if report.validation_status is not ValidationOutcome.VALID:
        return DailyDatasetValidationResult(report, None)
    validated = build_validated_candidate(
        candidate,
        tuple(sorted(rows, key=stable_row_key)),
    )
    return DailyDatasetValidationResult(report, validated)
~~~

Do not fill, interpolate, select a conflicting winner, convert null volume to
zero, or downgrade a blocking issue. Validation inspects the parser-preserved
sequence before duplicate handling. Canonical stable sorting happens only in
the `VALID` branch after every check has completed; an out-of-order input is
never repaired into a validated candidate.
`validate_order_and_unique_keys` emits `OUT_OF_ORDER` and blocking
`CONFLICTING_DUPLICATE` issues from the untouched sequence; identical duplicates
are reported once as non-blocking `DEDUPLICATED_IDENTICAL` by
`deduplicate_identical_rows`. `build_validated_candidate` copies evidence and
calendar records and stable-sorts all canonical tuples only after the report is
VALID.

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
The named `CASH_DIVIDEND_NOT_IMPLEMENTED` issue forces the `NOT_IMPLEMENTED`
branch even if all remaining checks pass. It always returns
`validated_candidate=None`.

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

Expected: PASS with stable issue/report hashes for repeated identical input;
changing source order is observable and an out-of-order sequence remains
blocked.

- [ ] **Step 6: Refactor check aggregation, then run targeted and related contract tests**

Replace repeated issue extension with
`run_check(name, callable) -> tuple[DataValidationIssue, ...]` while preserving
`VALIDATION_CHECK_ORDER` and exact issue sorting.

Run: `py -3.14 -m pytest tests/data_foundation/test_contracts.py tests/data_foundation/test_parsers.py tests/data_foundation/test_calendar.py tests/data_foundation/test_gap_evidence.py tests/data_foundation/test_adjustments.py tests/data_foundation/test_validation.py -q`

Expected: PASS; every design validation criterion maps to a named test.
Inspect downstream tests to confirm only
`DailyDatasetValidationResult.validated_candidate` can reach adjustment,
identity or canonicalization.

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

def build_canonical_descriptor(
    bundle: LogicalDatasetBundle,
    identity: DatasetIdentity,
) -> CanonicalDatasetDescriptor: ...
~~~

- [ ] **Step 1: Write identity sensitivity and claimed-identity mismatch tests**

~~~python
def test_logical_value_change_changes_dataset_id() -> None:
    assert build_dataset_identity(bundle(close="100")).dataset_id != (
        build_dataset_identity(bundle(close="101")).dataset_id
    )

def test_claimed_dataset_id_rejects_logical_mismatch() -> None:
    original = identity_for(bundle(close="100"))
    false_claim = claimed_identity(
        bundle(close="101"),
        dataset_id=original.dataset_id,
    )
    with pytest.raises(DataFoundationError, match="IDENTITY_CLAIM_MISMATCH"):
        verify_identity_claim(false_claim, bundle(close="101"))

def test_descriptor_contains_only_identity_bearing_logical_fields() -> None:
    descriptor = build_canonical_descriptor(bundle(), identity_for(bundle()))
    assert {field.name for field in dataclasses.fields(descriptor)} == {
        "descriptor_schema_version", "dataset_identity", "schema_hash",
        "calendar_ref", "timezone_policy_hash", "stable_key_definition",
        "source_range", "requested_range", "canonical_range", "row_count",
        "gap_count", "component_logical_hashes",
        "gap_semantic_coverage_hash",
        "corporate_action_semantic_coverage_hash",
    }
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

Build `CanonicalDatasetDescriptor` from this map and the same logical
schema/calendar/timezone/range/count values used by identity. Its constructor
has no component-file hash, physical ref, provenance, report, writer-profile or
physical-result parameter. Task 12 reconstructs this exact descriptor from an
existing complete manifest for reuse comparison.

- [ ] **Step 4: Implement exact identity-claim verification**

`verify_identity_claim` first compares the recomputed content/dependency
payload and component logical hashes, then compares the recomputed dataset ID.
If one claimed `dataset_id` is paired with a different `content_hash`, semantic
dependency set or component logical-hash map, raise
`DataFoundationError(DATA_VALIDATION_BLOCKER, "IDENTITY_CLAIM_MISMATCH")`
before publication. This gate verifies internal claims and registry
consistency; it does not claim to detect a general cryptographic SHA-256
collision.

- [ ] **Step 5: Run GREEN focused tests**

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
- Modify: `src/tv_quant/data_foundation/contracts.py`
- Modify: `src/tv_quant/data_foundation/__init__.py`
- Modify: `src/tv_quant/research_pipeline.py`
- Test: `tests/data_foundation/test_artifacts.py`

**Interfaces:**
- Consumes: `CanonicalDatasetDescriptor`, `RegistrationDecision`,
  `LogicalDatasetBundle`, `ProvenanceInputs`, `DataValidationReport`,
  `PreservedImportInputs`, `resolve_under_root`,
  `bind_artifact_hashes`, `sha256_file`, typed provenance mode from Task 1.
- Produces: `DatasetProvenance`, `CanonicalDatasetManifest`,
  `PublishedCanonicalBundle`, `PublishedImportManifest`, `ProvenanceInputs`, `RegistrationDecision`,
  `preserve_import_inputs`,
  `publish_canonical_bundle(...) -> PublishedCanonicalBundle` and:

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

def publish_validated_candidate(
    root: Path,
    import_id: str,
    candidate: ValidatedDatasetCandidate,
    report: DataValidationReport,
) -> tuple[RelativePath, Sha256Hex, RelativePath, Sha256Hex]: ...

def publish_import_manifest(
    root: Path,
    manifest: DataImportManifest,
) -> PublishedImportManifest: ...
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

def test_preservation_package_contains_and_hashes_every_declared_input(
    tmp_path: Path,
) -> None:
    request = request_with_market_calendar_gap_and_action_inputs(tmp_path)
    preserved = preserve_import_inputs(tmp_path, "import-1", request)
    refs = (
        preserved.market_data_ref,
        preserved.calendar_snapshot_ref,
        *preserved.gap_evidence_refs,
        *preserved.corporate_action_evidence_refs,
    )
    hashes = (
        preserved.market_data_hash,
        preserved.calendar_snapshot_hash,
        *preserved.gap_evidence_hashes,
        *preserved.corporate_action_evidence_hashes,
    )
    assert all(ref.startswith("raw/import-1/inputs/") for ref in refs)
    assert tuple(sha256_file(tmp_path / ref) for ref in refs) == hashes
    assert preserved.preserved_inputs_hash == canonical_hash({
        "import_id": preserved.import_id, "refs": refs, "hashes": hashes,
    })

def test_persisted_v22a_payloads_never_contain_absolute_root(tmp_path: Path) -> None:
    result = publish_bundle(tmp_path, bundle(), writer_profile())
    payloads = (read_manifest(result), provenance_payload(result.provenance))
    assert all(str(tmp_path) not in json.dumps(payload, sort_keys=True) for payload in payloads)

def test_provenance_is_built_only_after_component_file_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed = record_provenance_file_hash_inputs(monkeypatch)
    published = publish_bundle(tmp_path, bundle(), writer_profile())
    assert observed == [published.manifest.component_file_hashes]
    assert published.provenance.component_file_hashes == observed[0]

def test_manifest_is_built_only_after_physical_and_lineage_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = record_publication_build_order(monkeypatch)
    publish_bundle(tmp_path, bundle(), writer_profile())
    assert calls == [
        "descriptor", "reuse-decision", "components", "file-hashes",
        "provenance", "manifest", "verify", "publish",
    ]

def test_reuse_keeps_canonical_artifacts_and_uses_existing_file_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = publish_bundle(tmp_path, bundle(), writer_profile())
    writes = record_canonical_write_attempts(monkeypatch)
    second = publish_reuse(tmp_path, first, bundle())
    assert writes == []
    assert second.manifest_ref == first.manifest_ref
    assert second.manifest_hash == first.manifest_hash
    assert second.reused_existing is True
    assert second.provenance.component_file_hashes == first.manifest.component_file_hashes
    assert second.provenance.provenance_hash != first.provenance.provenance_hash
~~~

Add repeat publication, existing target, partial staging, hash mismatch, fixed
column order, writer metadata, physical profile changes, contained refs, all
input roles preflighted before copying, source mutation during copy, immutable
preserved-package target conflicts and reuse without canonical writes.

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_artifacts.py -q`

Expected: FAIL because artifact schemas and atomic publication do not exist.

- [ ] **Step 3: Preserve every import input before any consumer opens it**

Build the complete source set from the market-data, calendar snapshot, every
gap-evidence and every corporate-action-evidence request ref. Resolve and
containment-check the entire set before creating a staging directory or copying
one byte. Copy from already-opened handles into fixed role paths under one
`raw/<import_id>/inputs/` staging directory. For each handle, compare file
identity/size/mtime before and after the copy, rewind and hash the source handle,
and require that hash to equal the copied file's `sha256_file`; a concurrent
mutation fails with `INPUT_CHANGED_DURING_PRESERVATION`. Verify every copied
hash, atomically publish the whole package, then return only preserved refs and
hashes.

~~~python
sources = preflight_all_contained_inputs(root, request)
staging = create_preserved_inputs_staging(root, import_id)
copied = tuple(copy_open_input_and_verify(source, staging, role, index)
               for index, (role, source) in enumerate(sources))
preserved = build_preserved_import_inputs(import_id, copied)
verify_preserved_input_hashes(root, preserved)
publish_preserved_inputs_directory(root, staging, preserved.inputs_root_ref)
return preserved
~~~

No downstream parser, calendar loader, evidence loader, identity builder or
provenance builder may retain or reopen an original request path after this
function returns.

- [ ] **Step 4: Implement fixed Arrow schemas and deterministic component writes**

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
bytes through `sha256_file` and bound through `bind_artifact_hashes` with
transient `artifact_paths` plus exact, validated `persisted_refs`. No V2.2A
payload contains an `artifact_paths` key, a `*_path` absolute path value, or a
resolved root string.

- [ ] **Step 5: Implement descriptor-driven publication in frozen dependency order**

Create an exclusive staging directory under the contained root. Re-resolve
containment before each write and immediately before `Path.replace`. The caller
must already have constructed the logical bundle, identity, descriptor and
reuse decision, in that order. `CanonicalDatasetDescriptor` is the only reuse
input and contains no physical refs/hashes, provenance/report refs/hashes or
writer result.

For a new dataset: stage physical components, compute and verify their file
hashes, build `DatasetProvenance`, then build the complete
`CanonicalDatasetManifest`, verify all cross-references and hashes, and publish
the canonical directory atomically. No partially populated manifest object is
constructed. Reject an existing final directory,
cross-volume staging, partial target or hash mismatch. On failure retain the
raw/validated evidence and write only quarantine references.

~~~python
staging = create_exclusive_staging(root, dataset_id, revision)
verify_same_volume_staging(root, staging, target)
write_and_verify_components(staging, bundle, writer_profile)
component_file_hashes = hash_staged_components(staging)
provenance = build_dataset_provenance(
    descriptor, component_file_hashes, provenance_inputs
)
provenance_ref = write_provenance(staging, provenance)
manifest = build_complete_manifest(
    descriptor, component_file_hashes, provenance, provenance_ref,
    provenance_inputs,
    writer_profile, decision.manifest_revision,
)
write_canonical_json_artifact(
    staging / CANONICAL_MANIFEST_NAME,
    canonical_manifest_payload(manifest),
)
verify_published_hashes(staging, manifest)
verify_contained_path(root, target_relative, require_existing=False)
if target.exists():
    raise DataFoundationError(BlockerCode.DATA_VALIDATION_BLOCKER,
                              "IMMUTABLE_TARGET_EXISTS", str(target_relative))
staging.replace(target)
return PublishedCanonicalBundle(
    manifest, manifest_ref, manifest_hash, provenance, provenance_ref, False
)
~~~

For `decision.reuse_existing=True`, verify the descriptor against the existing
manifest, do not create or replace any canonical component, report or manifest,
and build the new provenance with
`decision.existing_manifest.component_file_hashes`. Publish only the new
provenance association outside the immutable canonical directory and return the
same manifest ref/hash with `reused_existing=True`.

~~~python
if decision.reuse_existing:
    manifest = require_reusable_manifest(decision, descriptor)
    provenance = build_dataset_provenance(
        descriptor, manifest.component_file_hashes, provenance_inputs
    )
    provenance_ref = publish_import_provenance(
        root, provenance_inputs.preserved_inputs.import_id, provenance
    )
    return PublishedCanonicalBundle(
        manifest=manifest,
        manifest_ref=decision.existing_manifest_ref,
        manifest_hash=decision.existing_manifest_hash,
        provenance=provenance,
        provenance_ref=provenance_ref,
        reused_existing=True,
    )
~~~

`build_preserved_import_inputs` derives `preserved_inputs_hash` from an ordered
payload of the import ID and every relative input ref/hash pair. Every
`DatasetProvenance` carries the producing `import_id`, `request_hash`, and that
hash. The immutable provenance payload includes these fields, so two imports of
the same file from the same provider at a fixed clock remain different because
their UUID-backed import IDs (and hence provenance IDs/hashes) differ.

`publish_import_manifest` writes one immutable contained JSON artifact at
`imports/<import_id>/import-manifest-<manifest_hash>.json`, after strict JSON
and relative-ref validation, and returns `PublishedImportManifest`. Its payload
includes final provenance, eligibility and registry snapshot refs/hashes when
the corresponding stage succeeded; it uses `None` only for stages not reached.
It never writes an absolute input or artifact path.

- [ ] **Step 6: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_artifacts.py -q`

Expected: PASS; physical writer changes alter file/manifest hashes but not
logical hashes or dataset ID.

- [ ] **Step 7: Refactor schema dispatch, then run targeted manifest and path regressions**

Use one immutable `COMPONENT_ARROW_SCHEMAS` mapping and one
`records_to_table(component_name, records) -> pa.Table` dispatcher.

Run:
`py -3.14 -m pytest tests/data_foundation/test_artifacts.py tests/pipeline/test_run_manifest.py tests/contracts/test_artifact_contract.py tests/contracts/test_path_safety.py -q`

Expected: PASS with old artifact semantics unchanged.

- [ ] **Step 8: Commit**

~~~powershell
git add src/tv_quant/data_foundation/artifacts.py src/tv_quant/data_foundation/contracts.py src/tv_quant/data_foundation/__init__.py src/tv_quant/research_pipeline.py tests/data_foundation/test_artifacts.py
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
    associations: tuple[ProvenanceAssociation, ...],
    prior: DataEligibility | None,
    check_matrix: Mapping[str, bool],
) -> DataEligibility: ...

def registry_snapshot_payload(snapshot: RegistrySnapshot) -> Mapping[str, object]: ...
def manifest_activation_event_payload(
    event: ManifestActivationEvent,
) -> Mapping[str, object]: ...
~~~

- [ ] **Step 1: Write RED tests for one-way binding and legal states**

~~~python
def test_eligibility_rejects_operation_outcomes() -> None:
    for illegal in ("BLOCKED", "INCOMPLETE", "NOT_IMPLEMENTED"):
        with pytest.raises(ValueError, match="state"):
            DataEligibility(state=illegal, **eligibility_fields())

def test_smoke_import_creates_smoke_only() -> None:
    eligibility = derive_eligibility(
        manifest(), manifest_hash(), (association(smoke_provenance(), qualifies=False),),
        None, all_checks_true()
    )
    assert eligibility.state is DataEligibilityState.SMOKE_ONLY
    assert eligibility.formal_eligible is False

def test_register_upserts_one_current_binding_per_exact_pair() -> None:
    first = register_dataset(registry(), dataset(close="100"), provider="local-csv")
    second = register_dataset(
        first.registry, dataset(close="100"), provider="local-parquet"
    )
    key = (first.binding.dataset_id, first.binding.manifest_hash)
    current = tuple(
        item for item in second.registry.snapshot.bindings
        if (item.dataset_id, item.manifest_hash) == key
    )
    assert len(current) == 1
    assert len(current[0].provenance_associations) == 2
    assert current[0].eligibility_hash == second.binding.eligibility_hash
~~~

Add exact manifest hash mismatch, missing provenance association, empty
qualifying set, smoke/non-smoke mixture, reverse manifest reference, duplicate
identical registration, corrupt snapshot and immutable history tests.
Add the following transition and activation cases here (not Task 2, which does
not own `DataEligibility`):

~~~python
def test_smoke_then_local_transition_upgrades_current_to_valid() -> None:
    prior = derive_eligibility(manifest(), manifest_hash(),
        (association(smoke_provenance(), qualifies=False),), None, all_checks_true())
    current = derive_eligibility(manifest(), manifest_hash(),
        (association(smoke_provenance(), qualifies=False), association(local_provenance(), qualifies=True)),
        prior, all_checks_true())
    assert current.state is DataEligibilityState.VALID and current.formal_eligible

def test_local_then_smoke_transition_keeps_current_valid() -> None:
    prior = derive_eligibility(manifest(), manifest_hash(),
        (association(local_provenance(), qualifies=True),), None, all_checks_true())
    current = derive_eligibility(manifest(), manifest_hash(),
        (association(local_provenance(), qualifies=True), association(smoke_provenance(), qualifies=False)),
        prior, all_checks_true())
    assert current.state is DataEligibilityState.VALID and current.formal_eligible

def test_activate_manifest_records_explicit_mapping_and_event() -> None:
    current = registry_with_active_and_inactive_revisions()
    event, activated = activate_exact_manifest(current, DATASET_ID, MANIFEST_V1_HASH)
    assert activated.active_manifest_by_dataset_id[DATASET_ID] == MANIFEST_V1_HASH
    assert event.manifest_hash == MANIFEST_V1_HASH
~~~

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_registry.py -q`

Expected: FAIL because registry/eligibility binding is absent.

- [ ] **Step 3: Implement derived eligibility only**

~~~python
def derive_eligibility(manifest, manifest_hash, associations, prior, check_matrix):
    require_exact_manifest_hash(manifest, manifest_hash)
    if not associations:
        raise DataFoundationError(BlockerCode.DATA_VALIDATION_BLOCKER, "MISSING_PROVENANCE_ASSOCIATION", "")
    all_checks = all(check_matrix.values())
    if not all_checks:
        raise DataFoundationError(BlockerCode.DATA_VALIDATION_BLOCKER, "ELIGIBILITY_CHECK_FAILED")
    qualifying = qualifying_association_hashes(associations)
    if prior is not None and prior.state is DataEligibilityState.INVALIDATED:
        return build_hashed_eligibility(
            state=DataEligibilityState.INVALIDATED, formal_eligible=False,
            qualifying_provenance_hashes=prior.qualifying_provenance_hashes,
            invalidation_event_id=prior.invalidation_event_id,
            invalidation_event_hash=prior.invalidation_event_hash, ...,
        )
    if qualifying:
        return build_hashed_eligibility(
            state=DataEligibilityState.VALID, formal_eligible=True,
            qualifying_provenance_hashes=qualifying, ...,
        )
    if prior is not None and prior.state is DataEligibilityState.VALID:
        return build_hashed_eligibility(
            state=DataEligibilityState.VALID, formal_eligible=True,
            qualifying_provenance_hashes=prior.qualifying_provenance_hashes, ...,
        )
    return build_hashed_eligibility(
        state=DataEligibilityState.SMOKE_ONLY, formal_eligible=False,
        qualifying_provenance_hashes=(), ...,
    )
~~~

`ProvenanceAssociation` is one-to-one with a persisted provenance record and
copies its ref/hash/import ID/request hash/provider capability/source type.
Only local CSV/Parquet associations that independently satisfy the frozen
formal qualification checks have `qualifies_for_formal=True`; smoke is never
marked qualifying. `DataEligibility.qualifying_provenance_hashes` must equal
the sorted explicit qualifying association subset for a new VALID record;
SMOKE_ONLY has an empty subset. Callers cannot pass `formal_eligible`.
`INVALIDATED` is created only by Task 13 and ordinary re-import is forbidden to
clear it.

- [ ] **Step 4: Implement append-only snapshots with one current exact-pair binding**

Validate:
`eligibility.dataset_id == manifest.dataset_identity.dataset_id`,
`eligibility.manifest_hash == manifest_hash`, and qualifying provenance hashes
are exactly the sorted `qualifies_for_formal=True` subset of associations (and
therefore non-empty only for VALID). Within each new snapshot,
`(dataset_id, manifest_hash)` is a unique key. Registration merges the prior and
new provenance associations, constructs the replacement eligibility first, and
upserts exactly one replacement binding with its new eligibility pointer. Sort
current bindings by `(dataset_id, manifest_revision, manifest_hash)`. Publish a
new contained snapshot and pointer atomically; never rewrite the prior snapshot,
prior eligibility or prior provenance records.

~~~python
verify_binding(manifest, manifest_hash, eligibility, all_provenances)
bindings = upsert_current_binding(self.snapshot.bindings, replacement_binding)
assert sum(
    (item.dataset_id, item.manifest_hash)
    == (replacement_binding.dataset_id, replacement_binding.manifest_hash)
    for item in bindings
) == 1
snapshot = build_registry_snapshot(
    self.snapshot.snapshot_hash, bindings,
    self.snapshot.invalidation_event_refs,
    self.snapshot.active_manifest_by_dataset_id,
    self.snapshot.manifest_activation_event_refs,
)
publish_registry_snapshot_atomically(self.root, snapshot)
~~~

`upsert_current_binding` rejects a pre-existing duplicate exact-pair key rather
than guessing a winner. A new eligibility in a later snapshot replaces only the
current eligibility pointer for that exact pair; historical snapshots and all
historical eligibility records remain addressable. Registration never activates
a manifest or changes an active mapping. `activate_manifest` requires an exact
current binding, emits an immutable `ManifestActivationEvent`, and atomically
publishes a successor snapshot whose `active_manifest_by_dataset_id[dataset_id]`
is exactly the requested manifest hash and whose activation refs include that
event. It is the only activation path.

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_registry.py -q`

Expected: PASS; only VALID is formal, SMOKE_ONLY is permanent false, manifest
payloads contain no eligibility reference, and every current snapshot has at
most one binding for each `(dataset_id, manifest_hash)`.

- [ ] **Step 6: Refactor binding verification, then run identity/artifact regression**

Extract `verify_binding(manifest, manifest_hash, eligibility, associations)` and
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
  `MarketDataRegistry`, `RegistryBinding`, `EligibleDatasetSelection`, identity and manifest hashes.
- Produces: `find_latest_eligible_dataset` and:

~~~python
def decide_registration(
    registry: MarketDataRegistry,
    descriptor: CanonicalDatasetDescriptor,
) -> RegistrationDecision: ...

def associated_provenances_for_registration(
    registry: MarketDataRegistry,
    decision: RegistrationDecision,
    new_provenance: DatasetProvenance,
    new_provenance_ref: RelativePath,
) -> tuple[ProvenanceAssociation, ...]: ...
~~~

- [ ] **Step 1: Write RED idempotency, identity-claim, and provider-order tests**

~~~python
def test_identical_reimport_updates_same_binding_provenances() -> None:
    first = register_dataset(registry(), dataset(close="100"), provider="local-csv")
    second = register_dataset(first.registry, dataset(close="100"), provider="local-parquet")
    assert second.binding.manifest_hash == first.binding.manifest_hash
    assert second.binding.manifest_revision == 1
    assert len(second.binding.provenance_associations) == 2
    matches = tuple(
        item for item in second.registry.snapshot.bindings
        if (item.dataset_id, item.manifest_hash)
        == (second.binding.dataset_id, second.binding.manifest_hash)
    )
    assert matches == (second.binding,)

def test_formal_lookup_excludes_smoke_binding() -> None:
    result = find_latest_eligible_dataset(requirement(), smoke_registry(), snapshot_hash(), capabilities())
    assert result.blocker_code is BlockerCode.DATA_CAPABILITY_BLOCKER

def test_claimed_dataset_id_rejects_logical_mismatch() -> None:
    first = register_dataset(registry(), dataset(close="100"), provider="local-csv")
    with pytest.raises(DataFoundationError, match="IDENTITY_CLAIM_MISMATCH"):
        register_dataset(
            first.registry,
            dataset(close="101", claimed_dataset_id=first.binding.dataset_id),
            provider="local-csv",
        )
~~~

Add same-ID logical-claim mismatch, same provider rank content conflict, preference
fallback, complete coverage, canonical range end, and deterministic dataset-ID
tie-break tests. Add the activation and selected-provenance proofs:

~~~python
def test_formal_lookup_ignores_inactive_higher_revision() -> None:
    current = registry_with_active_and_inactive_revisions()
    result = find_latest_eligible_dataset(requirement(), current, current.snapshot.snapshot_hash, capabilities())
    assert result.binding.manifest_hash == MANIFEST_V1_HASH

def test_provider_preference_uses_qualifying_associations_only() -> None:
    result = find_latest_eligible_dataset(requirement(provider_preference=("local-parquet", "local-csv")), qualifying_registry(), snapshot_hash(), capabilities())
    assert result.selected_provider_capability_id == "local-csv"

def test_formal_lookup_returns_selected_qualifying_provenance() -> None:
    result = find_latest_eligible_dataset(requirement(), qualifying_registry(), snapshot_hash(), capabilities())
    selected = next(a for a in result.binding.provenance_associations
                    if a.provenance_hash == result.selected_provenance_hash)
    assert selected.provenance_ref == result.selected_provenance_ref
    assert selected.qualifies_for_formal is True
~~~

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_registry_query.py -q`

Expected: FAIL because reuse and query policies are absent.

- [ ] **Step 3: Implement idempotent registration decision**

For an existing `dataset_id`, compare the complete
`CanonicalDatasetDescriptor` against logical descriptor fields reconstructed
from the registered manifest: content hash, semantic dependencies, every
component logical hash, semantic coverage hashes, logical schema/calendar/
timezone, stable key, ranges and counts. Exact equality reuses canonical
artifacts and manifest revision and adds the new provenance to the same current
binding; it never rewrites canonical files or appends a parallel active
binding. Any mismatch raises
`DataFoundationError(DATA_VALIDATION_BLOCKER, "IDENTITY_CLAIM_MISMATCH")`. A
normal re-import never creates revision 2. This is a claimed-identity
consistency check, not a generic cryptographic collision detector.

~~~python
identity = descriptor.dataset_identity
existing = registry.active_binding_for(identity.dataset_id)
if existing is None:
    return RegistrationDecision(False, 1, None, None, None)
registered = registry.load_manifest(existing)
if descriptor_payload(descriptor) != descriptor_payload(
    descriptor_from_manifest(registered)
):
    raise DataFoundationError(
        BlockerCode.DATA_VALIDATION_BLOCKER,
        "IDENTITY_CLAIM_MISMATCH",
        identity.dataset_id,
    )
return RegistrationDecision(
    True, registered.manifest_revision, registered,
    existing.manifest_ref, existing.manifest_hash,
)
~~~

- [ ] **Step 4: Implement the frozen query order**

~~~python
candidates = verify_and_filter_bindings(registry, requirement, expected_snapshot_hash)
# It returns only binding_for_exact(dataset_id, snapshot.active_manifest_by_dataset_id[dataset_id]).
# No revision, mtime, import time, or inactive binding enters this tuple.
candidates = tuple(
    (binding, load_eligibility(binding)) for binding in candidates
    if binding.eligibility_state is DataEligibilityState.VALID
    and load_eligibility(binding).formal_eligible
)
for provider_id in requirement.provider_preference:
    ranked = tuple(
        EligibleDatasetSelection(
            binding=binding,
            selected_provenance_ref=association.provenance_ref,
            selected_provenance_hash=association.provenance_hash,
            selected_provider_capability_id=association.provider_capability_id,
        )
        for binding, eligibility in candidates
        if (association := select_qualifying_association(binding, eligibility, provider_id))
        is not None
    )
    if ranked:
        return select_without_content_conflict(ranked)
return capability_blocker("NO_FORMAL_ELIGIBLE_DATASET")
~~~

`verify_and_filter_bindings` first requires the snapshot hash and then iterates
only the explicit active-manifest mapping, resolving each with
`binding_for_exact(dataset_id, manifest_hash)`. An absent mapping, missing
exact binding, or active INVALIDATED binding produces the formal typed blocker;
it never falls back to an inactive binding. `select_qualifying_association`
requires both an association in the eligibility's explicit qualifying hash
subset and the requested provider capability. `select_without_content_conflict`
sorts selections by complete coverage, canonical range end and dataset ID only
after rejecting conflicting logical content at the same provider rank. It never
reads manifest revision, mtime or import timestamp to infer activity.

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

@pytest.mark.parametrize("failure_point", [
    "after-event-stage",
    "after-eligibility-stage",
    "after-snapshot-stage",
    "after-transaction-publish",
])
def test_invalidation_transaction_has_no_partial_active_visibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    before_pointer = active_snapshot_pointer(tmp_path)
    before_records = active_invalidation_records(tmp_path)
    inject_invalidation_failure(monkeypatch, failure_point)
    with pytest.raises(DataFoundationError):
        invalidate_fixture_binding(tmp_path)
    assert active_snapshot_pointer(tmp_path) == before_pointer
    assert active_invalidation_records(tmp_path) == before_records
    if failure_point == "after-transaction-publish":
        assert len(orphan_transaction_directories(tmp_path)) == 1

def test_invalidation_replaces_only_current_valid_eligibility() -> None:
    event, invalidated, snapshot = invalidate_once()
    matches = tuple(
        item for item in snapshot.bindings
        if (item.dataset_id, item.manifest_hash)
        == (invalidated.dataset_id, invalidated.manifest_hash)
    )
    assert len(matches) == 1
    assert matches[0].eligibility_state is DataEligibilityState.INVALIDATED
    assert not any(
        item.eligibility_state is DataEligibilityState.VALID for item in matches
    )

def test_active_invalidated_revision_has_no_fallback() -> None:
    _, invalidated, snapshot = invalidate_once()
    active_hash = snapshot.active_manifest_by_dataset_id[invalidated.dataset_id]
    assert active_hash == invalidated.manifest_hash
    result = find_latest_eligible_dataset(requirement(), load_snapshot(snapshot), snapshot.snapshot_hash, capabilities())
    assert result.blocker_code is BlockerCode.DATA_CAPABILITY_BLOCKER
~~~

Inject failures after each record stage and after the complete transaction
directory publish to prove no partial triple becomes active and the prior
snapshot pointer remains unchanged.

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

- [ ] **Step 4: Implement compare-and-replace transaction publication**

Verify all expected hashes against the current snapshot. Derive a deterministic
request key from the complete request. If that key already maps to a committed
transaction, return the same triple. Otherwise replace the exact current
binding's eligibility ref/hash/state through `upsert_current_binding`, so the
new snapshot retains exactly one `(dataset_id, manifest_hash)` binding and no
current VALID eligibility for that pair. Stage event, INVALIDATED eligibility
and registry snapshot together under one same-root transaction staging
directory, fsync/close and verify every hash. Atomically rename that one complete
directory into the transaction namespace, then atomically replace the active
snapshot pointer last. A mismatched parent or partial historical record fails
closed.

The invalidation successor passes through the prior
`active_manifest_by_dataset_id` and `manifest_activation_event_refs` unchanged,
and appends only the new invalidation ref. It does not synthesize a replacement
active revision while producing the invalidated eligibility.

~~~python
with registry_transaction(root, expected_snapshot_hash) as tx:
    tx.stage_json("invalidation-event.json", event_payload)
    tx.stage_json("eligibility-invalidated.json", eligibility_payload)
    tx.stage_json("registry-snapshot.json", snapshot_payload)
    tx.verify_all_hashes()
    transaction_ref = tx.publish_transaction_directory()
    tx.activate_snapshot_pointer_last()
~~~

No individual event, eligibility or snapshot file is ever published directly
into its final namespace. A crash after the transaction-directory rename but
before pointer replacement may leave a complete, verified orphan transaction;
it is not active, is ignored by readers, and is retained for a future retention
workflow. V2.2A invalidation does not delete it automatically.
Invalidation does not alter `active_manifest_by_dataset_id`: if the invalidated
manifest was active, it remains the explicit active hash and formal lookup
blocks. The query must not search an earlier/later revision for a replacement;
only a later explicit `activate_manifest` event may select one.

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_invalidation.py -q`

Expected: PASS for exact scope, one current exact-pair binding, all-or-none
active visibility, idempotent replay, retained inactive orphan and parent/hash
conflicts.

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
- Consumes: existing `resolve_under_root(root, relative_path) -> Path` and Task
  10 `preserve_import_inputs`.
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
    assert calls == ["preserved-package-publish", "canonical-publish"]

def test_all_inputs_are_contained_before_first_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = record_input_preflight_and_copy_calls(monkeypatch)
    with pytest.raises(ValueError):
        preserve_import_inputs(tmp_path, "import-1", unsafe_last_evidence_request())
    assert events == [
        "contain:market-data", "contain:calendar", "contain:gap-evidence:0",
        "contain:corporate-action-evidence:0",
    ]
    assert not any(event.startswith("copy:") for event in events)

def test_source_mutation_during_preservation_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mutate_during_preserved_copy(monkeypatch)
    with pytest.raises(DataFoundationError, match="INPUT_CHANGED_DURING_PRESERVATION"):
        preserve_import_inputs(tmp_path, "import-1", valid_csv_request())
    assert not (tmp_path / "raw" / "import-1" / "inputs").exists()
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

- [ ] **Step 4: Freeze input-package containment and TOCTOU checks**

`preflight_all_contained_inputs` resolves the full declared input set before
the first copy. Immediately before each open, repeat containment/reparse and
file-identity verification against the preflight result. Open only those
resolved paths, reject any file identity or
metadata change observed during copy, verify the preserved byte hash against a
second pass over the same open handle, and atomically publish the complete raw
input package. Re-resolve every preserved ref before downstream reads; never
re-resolve or reopen `DataImportRequest` paths after preservation. A preserved
package hash mismatch is a blocker, not a reason to fall back to the original.

- [ ] **Step 5: Enforce same-root, same-volume atomic publication**

Compare `Path.anchor` and Windows volume serial/device identity where available.
Re-run `verify_contained_path` immediately before preserved-package and
canonical-directory replace. Task 15 adds preserved-source-read and
registry-commit checks around the orchestrator. Never log `runtime.data_root`
or the resolved absolute target.

~~~python
if volume_identity(staging) != volume_identity(target.parent):
    raise ValueError("staging: same-volume publication required")
verify_contained_path(root, raw_relative, require_existing=False)
verify_contained_path(root, canonical_relative, require_existing=False)
~~~

- [ ] **Step 6: Run GREEN**

Run:
`py -3.14 -m pytest tests/data_foundation/test_security.py tests/contracts/test_path_safety.py -q`

Expected: PASS on Windows; symlink/junction/reparse escape cannot reach read or
write calls.

- [ ] **Step 7: Refactor platform probes, then run artifact and confirmation-store regression**

Isolate Windows attribute/volume inspection behind private functions in the
existing `path_safety.py` owner so non-Windows code remains deterministic.

Run:
`py -3.14 -m pytest tests/data_foundation/test_artifacts.py tests/data_foundation/test_security.py tests/contracts/test_artifact_contract.py tests/contracts/test_confirmation_store.py -q`

Expected: PASS with V2.1 root containment and atomic confirmation semantics
unchanged.

- [ ] **Step 8: Commit**

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
    "ALL_INPUT_CONTAINMENT",
    "RAW_INPUT_PRESERVATION",
    "PRESERVED_CALENDAR_AND_EVIDENCE_LOADING",
    "PRESERVED_MARKET_DATA_PARSING",
    "VALIDATION",
    "VALIDATED_EVIDENCE_PUBLICATION",
    "ADJUSTMENT",
    "LOGICAL_BUNDLE",
    "IDENTITY",
    "DESCRIPTOR_AND_REUSE_DECISION",
    "CANONICAL_PUBLICATION",
    "ELIGIBILITY",
    "REGISTRY_COMMIT",
    "FINALIZED_IMPORT_MANIFEST",
    "IMMUTABLE_IMPORT_MANIFEST_PUBLICATION",
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
    assert result.import_manifest.final_provenance_hash == result.registry_binding.provenance_associations[-1].provenance_hash
    assert result.import_manifest.final_eligibility_hash == result.eligibility.eligibility_hash
    assert result.import_manifest.final_registry_snapshot_hash == load_registry(tmp_path).snapshot.snapshot_hash
    assert result.import_manifest_ref and result.import_manifest_hash

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

def test_parser_receives_only_preserved_market_data_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = record_parser_paths(monkeypatch)
    result = import_local_dataset(valid_csv_request(), runtime(tmp_path))
    assert result.operation.status is PipelineStatus.SUCCESS
    assert paths == [tmp_path / result.import_manifest.preserved_inputs.market_data_ref]
    assert "raw" in paths[0].parts and "inputs" in paths[0].parts

def test_original_mutation_after_preservation_cannot_change_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = request_with_market_calendar_gap_and_action_inputs(tmp_path)
    expected_hashes = hashes_of_declared_inputs(tmp_path, request)
    mutate_original_inputs_after_preservation(monkeypatch)
    result = import_local_dataset(request, runtime(tmp_path))
    assert result.operation.status is PipelineStatus.SUCCESS
    assert all_preserved_hashes(result.import_manifest.preserved_inputs) == expected_hashes
    assert result.canonical_manifest.dataset_identity == identity_from_preserved_bytes(
        tmp_path, result.import_manifest.preserved_inputs
    )

def test_canonicalization_receives_validated_candidate_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidates = record_canonicalization_candidates(monkeypatch)
    result = import_local_dataset(request_with_identical_duplicate(), runtime(tmp_path))
    assert result.operation.status is PipelineStatus.SUCCESS
    assert len(candidates) == 1
    assert isinstance(candidates[0], ValidatedDatasetCandidate)
    assert len(candidates[0].validated_raw_bars) == 1

def test_identical_duplicate_is_absent_from_canonical_rows(tmp_path: Path) -> None:
    result = import_local_dataset(request_with_identical_duplicate(), runtime(tmp_path))
    assert result.validation_report.validation_status is ValidationOutcome.VALID
    assert "DEDUPLICATED_IDENTICAL" in {
        issue.issue_code for issue in result.validation_report.issues
    }
    assert read_canonical_component(result, "daily-bar-raw").num_rows == 1

def test_cash_dividend_returns_not_implemented_without_outputs(tmp_path: Path) -> None:
    result = import_local_dataset(cash_dividend_request(), runtime(tmp_path))
    assert result.operation.status is PipelineStatus.NOT_IMPLEMENTED
    assert result.operation.blocker_code is BlockerCode.DATA_CAPABILITY_BLOCKER
    assert result.validation_report.validation_status is ValidationOutcome.NOT_IMPLEMENTED
    assert result.canonical_manifest is None
    assert result.eligibility is None
    assert result.registry_binding is None

def test_repeat_same_file_provider_fixed_clock_has_distinct_provenance_import_ids(tmp_path: Path) -> None:
    first = import_local_dataset(valid_csv_request(), runtime(tmp_path, fixed_clock=True))
    second = import_local_dataset(valid_csv_request(), runtime(tmp_path, fixed_clock=True))
    assert first.import_manifest.import_id != second.import_manifest.import_id
    assert first.import_manifest.final_provenance_hash != second.import_manifest.final_provenance_hash

def test_successful_and_failed_imports_publish_immutable_import_manifests(tmp_path: Path) -> None:
    success = import_local_dataset(valid_csv_request(), runtime(tmp_path))
    failed = import_local_dataset(missing_source_request(), runtime(tmp_path))
    for result in (success, failed):
        assert result.import_manifest_ref and result.import_manifest_hash
        assert canonical_hash(read_import_manifest(tmp_path, result)) == result.import_manifest_hash

def test_success_import_manifest_binds_final_provenance_eligibility_and_registry(tmp_path: Path) -> None:
    result = import_local_dataset(valid_csv_request(), runtime(tmp_path))
    assert result.import_manifest.final_provenance_hash == result.registry_binding.provenance_associations[-1].provenance_hash
    assert result.import_manifest.final_eligibility_hash == result.eligibility.eligibility_hash
    assert result.import_manifest.final_registry_snapshot_hash == load_registry(tmp_path).snapshot.snapshot_hash
~~~

Add tests for all-input-preservation before any loader/parser, failed manifest
finalization, quarantine refs, no auto retry and `YFINANCE_SMOKE -> SMOKE_ONLY`.
Assert that every success or typed failure publishes an immutable import manifest
and `ImportLocalDatasetResult` returns that manifest's ref/hash. Assert that
`DataImportManifest` records the
market-data, calendar, every gap-evidence and every corporate-action-evidence
preserved ref/hash. Record containment checks at all original-input preflights,
`preserved-market-read`, `preserved-calendar-read`, `preserved-evidence-read`,
`canonical-publish` and `registry-commit`.

- [ ] **Step 2: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_importer.py -q`

Expected: FAIL because orchestration and finalized result semantics are absent.

- [ ] **Step 3: Implement request/raw/parser/validation stages**

~~~python
def import_local_dataset(request, runtime):
    import_id = runtime.uuid_factory().hex
    imported_at = utc_z(runtime.clock())
    preserved: PreservedImportInputs | None = None
    try:
        preserved = preserve_import_inputs(runtime.data_root, import_id, request)
        calendar_ref = load_preserved_calendar(preserved, runtime)
        gaps, gap_evidence, events, action_evidence = load_preserved_evidence(
            preserved, runtime
        )
        rows = parse_by_source_type(preserved, request, runtime, calendar_ref)
        normalized = assemble_candidate(
            import_id, rows, gaps, gap_evidence, events, action_evidence,
            request, calendar_ref,
        )
        validation = validate_daily_dataset(normalized)
    except DataFoundationError as exc:
        return finalize_failed_import(runtime.data_root, request, import_id, imported_at, preserved, exc)
    if validation.validated_candidate is None:
        return finalize_nonvalid_import(
            runtime.data_root, request, import_id, imported_at, preserved, normalized, validation.report
        )
    return continue_valid_import(
        request, runtime, imported_at, preserved,
        validation.validated_candidate, validation.report,
    )
~~~

All original paths are containment-checked before the first copy. The immutable
raw input package is atomically published before any parser/calendar/evidence
loader runs. After `preserve_import_inputs` returns, the request paths are used
only as lineage strings in the finalized import manifest; every byte read comes
from `PreservedImportInputs`. Every expected domain exception is translated to
typed status metadata and immutable evidence; all finalizers call
`finalize_and_publish_import_manifest`, including failures before preservation
(whose permitted `preserved_inputs` and original hash are `None`) and failures
after preservation (which retain every preserved ref/hash). Programming errors
are not converted into success.

- [ ] **Step 4: Implement valid identity/publication/eligibility/registry stages**

Consume only `ValidatedDatasetCandidate`: derive factors/adjusted rows,
construct the logical bundle, compute component logical hashes and identity,
build the logical-only descriptor, then decide reuse. Call the single
`publish_canonical_bundle` boundary, which either performs the frozen new-data
publication order or reuses canonical artifacts without rewriting them while
creating a new provenance from the existing manifest's component file hashes.
Derive a replacement VALID or SMOKE_ONLY eligibility from all provenance
associations, upsert the one current exact-pair registry binding, then publish
the complete `DataImportManifest` containing all preserved inputs and final
provenance/eligibility/registry refs/hashes. If registry commit fails, no
eligibility/binding is returned, but a failure import manifest is still
published and staged records remain unreachable.

~~~python
validated = candidate
validated_ref, validated_hash, report_ref, report_hash = publish_validated_candidate(
    runtime.data_root, validated.import_id, validated, report
)
factors = derive_adjustment_factors(
    validated.corporate_action_events,
    validated.corporate_action_evidence,
    request.adjustment_method,
)
adjusted = apply_adjustments(
    validated.validated_raw_bars, factors, request.adjustment_method
)
bundle = assemble_logical_bundle(validated, factors, adjusted)
identity = build_dataset_identity(bundle)
descriptor = build_canonical_descriptor(bundle, identity)
registry = load_registry_from_runtime(runtime)
decision = decide_registration(registry, descriptor)
published = publish_canonical_bundle(
    runtime.data_root, bundle, descriptor, decision,
    provenance_inputs(request, preserved, imported_at, report_ref, report_hash),
    report, PARQUET_WRITER_PROFILE,
)
associations = associated_provenances_for_registration(
    registry, decision, published.provenance, published.provenance_ref
)
prior_binding = registry.binding_for_exact(
    published.manifest.dataset_identity.dataset_id, published.manifest_hash
)
eligibility = derive_eligibility(
    published.manifest, published.manifest_hash, associations,
    load_eligibility(prior_binding) if prior_binding is not None else None,
    check_matrix(report),
)
eligibility_ref = publish_eligibility(runtime.data_root, eligibility)
snapshot = registry.register(
    published.manifest, published.manifest_ref,
    published.provenance, published.provenance_ref, eligibility, eligibility_ref,
)
if (
    eligibility.state is DataEligibilityState.VALID
    and registry.active_binding_for(published.manifest.dataset_identity.dataset_id) is None
):
    _, snapshot = registry.activate_manifest(
        published.manifest.dataset_identity.dataset_id, published.manifest_hash,
        snapshot.snapshot_hash, "INITIAL_FORMAL_ACTIVATION", "importer:v2.2a", imported_at,
    )
result = finalize_successful_import(
    runtime.data_root, request, imported_at, preserved, validated_ref, validated_hash,
    report, published, eligibility, snapshot
)
~~~

`finalize_successful_import`, `finalize_nonvalid_import`, and
`finalize_failed_import` each build a complete `DataImportManifest` first and
call the single `publish_import_manifest` owner before returning
`ImportLocalDatasetResult`. Success must bind `final_provenance_ref/hash`,
`final_eligibility_ref/hash`, and the active `final_registry_snapshot_ref/hash`.
Failure stores `None` only for unreached final stages, never fabricates a
success binding. A fixed clock is not an identity input: `uuid_factory` must
produce a fresh import ID for every invocation, and that ID is carried through
preservation, provenance, manifest and result.

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_importer.py -q`

Expected: PASS for success, smoke, blocker, incomplete, not-implemented,
repeat, identity-claim mismatch and failure-evidence paths.

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
    assert tuple(map(daily_bar_semantic_payload, read_validated_rows(
        tmp_path, csv_result.import_manifest
    ))) == tuple(map(daily_bar_semantic_payload, read_validated_rows(
        tmp_path, parquet_result.import_manifest
    )))
    assert csv_result.canonical_manifest.dataset_identity.dataset_id == (
        parquet_result.canonical_manifest.dataset_identity.dataset_id
    )
    current = load_registry(tmp_path)
    matches = tuple(
        item for item in current.snapshot.bindings
        if (item.dataset_id, item.manifest_hash) == (
            csv_result.canonical_manifest.dataset_identity.dataset_id,
            csv_result.registry_binding.manifest_hash,
        )
    )
    assert len(matches) == 1
    assert len(matches[0].provenance_associations) == 2
    selection = find_latest_eligible_dataset(
        requirement(), current, current.snapshot.snapshot_hash, capabilities()
    )
    assert selection.binding.dataset_id == csv_result.canonical_manifest.dataset_identity.dataset_id
    assert any(
        association.provenance_hash == selection.selected_provenance_hash
        and association.qualifies_for_formal
        for association in selection.binding.provenance_associations
    )
    _, invalidated, _ = invalidate_exact_binding(selection.binding, tmp_path)
    assert invalidated.state is DataEligibilityState.INVALIDATED
    after = load_registry(tmp_path)
    exact = tuple(
        item for item in after.snapshot.bindings
        if (item.dataset_id, item.manifest_hash)
        == (selection.binding.dataset_id, selection.binding.manifest_hash)
    )
    assert len(exact) == 1
    assert exact[0].eligibility_state is DataEligibilityState.INVALIDATED
    assert find_latest_eligible_dataset(
        requirement(), after, after.snapshot.snapshot_hash, capabilities()
    ).blocker_code is BlockerCode.DATA_CAPABILITY_BLOCKER
~~~

- [ ] **Step 3: Run RED**

Run: `py -3.14 -m pytest tests/data_foundation/test_end_to_end.py -q`

Expected: FAIL until fixture adapters expose every complete local evidence
reference required by the pipeline.

- [ ] **Step 4: Wire fixture factories through only public APIs**

Test helpers may create roots, local Parquet and requests; they must not call
private publication or registry mutation helpers to bypass gates. Freeze the
expected component names, identity equality, eligibility state, binding hashes,
manifest revision, one-current-binding invariant, two provenance associations
and post-invalidation lookup result. Also prove the selected formal provenance
is returned, an inactive higher revision is never inferred active, and an
active invalidated revision does not fall back. CSV/Parquet equivalence is asserted over
the persisted validated-candidate rows, never the parser output.

~~~python
def materialize_parquet_fixture(root: Path, csv_request: DataImportRequest) -> Path:
    rows = fixture_spy_rows()
    path = root / "incoming" / "spy.parquet"
    write_test_parquet(path, rows, writer_profile())
    return path
~~~

`fixture_spy_rows` is a test-owned literal tuple matching the CSV fixture; it
does not call a production parser. Both public imports independently preserve,
parse and validate their own input package before the comparison.

- [ ] **Step 5: Run GREEN**

Run: `py -3.14 -m pytest tests/data_foundation/test_end_to_end.py -q`

Expected: PASS for SPY/QQQ validated CSV/Parquet equivalence, legal gaps,
smoke-only exclusion, one exact-pair binding with two provenance associations,
selected qualifying provenance handoff, and an invalidation lifecycle whose
formal lookup ends in a blocker without revision fallback.

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
V2.2B/V2.2C modules. Statically reject `default=str` in any JSON writer and
assert each V2.2A persisted JSON payload constructor routes refs through the
relative-ref validator; runtime `Path` values may appear only in nonpersisted
hash/copy/containment parameters.

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
    "DataImportRequest", "DataImportRuntimeContext", "PreservedImportInputs",
    "DailyBarRaw", "DailyBarAdjusted", "DailyGapRecord", "GapEvidence",
    "CorporateActionEvent", "CorporateActionEvidence", "AdjustmentFactor",
    "DataValidationIssue", "DataValidationReport", "ValidatedDatasetCandidate",
    "DailyDatasetValidationResult", "DatasetIdentity", "DatasetProvenance",
    "DataImportManifest", "CanonicalDatasetDescriptor",
    "CanonicalDatasetManifest", "PublishedCanonicalBundle", "DataEligibility",
    "ProvenanceAssociation", "ManifestActivationEvent", "RegistryBinding",
    "EligibleDatasetSelection", "RegistrySnapshot",
    "PublishedImportManifest", "InvalidationEvent",
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
    "identity_claim_mismatch", "one_way_manifest_eligibility",
    "parser_order_preserved", "out_of_order_blocked",
    "preserved_input_package", "original_mutation_isolated",
    "validated_candidate_propagation", "publication_dependency_order",
    "current_binding_uniqueness", "same_binding_provenance_update",
    "cash_dividend_not_implemented",
    "invalidation_no_partial_active_visibility",
    "atomic_invalidation", "windows_path_security", "v21_regression",
    "canonical_json_rejects_non_json_values",
    "absolute_root_absent_from_persisted_artifacts",
    "artifact_paths_separate_from_persisted_refs",
    "explicit_active_manifest_revision_only",
    "inactive_higher_revision_not_selected",
    "active_invalidated_revision_no_fallback",
    "smoke_then_formal_valid", "formal_then_smoke_valid",
    "provider_preference_qualifying_only", "selected_provenance_handoff",
    "unique_provenance_import_id", "success_failure_import_manifests",
    "finalized_import_manifest_links", "split_effective_date_boundary",
    "cumulative_split_factors", "split_rounding_deterministic_precision",
    "dependency_preflight_stops_before_task1",
})
assert traceability_test_nodes() == TRACEABILITY_REQUIREMENTS
~~~

- [ ] **Step 5: Run GREEN focused tests and compile checks**

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
0 dependency preflight (`exchange-calendars==4.13.2`, `pyarrow==25.0.0`; no network)
  -> 1 registration/owners
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
Task 14. Task 1 must not begin unless Task 0 passes; a missing dependency stops
execution before writes, RED tests or package installation. No task may begin
V2.2B, formal backtesting or network/provider work.

## 7. Final Acceptance Commands

Run from repository root on the implementation branch:

~~~powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$required = @{ "exchange-calendars" = "4.13.2"; "pyarrow" = "25.0.0" }
$missing = foreach ($entry in $required.GetEnumerator()) {
  $raw = py -3.14 -c "import importlib.metadata as m; print(m.version('$($entry.Key)'))" 2>$null
  $actual = if ($null -eq $raw) { "" } else { ([string]$raw).Trim() }
  if ($LASTEXITCODE -ne 0 -or $actual -ne $entry.Value) { "$($entry.Key)==$($entry.Value) (installed: $actual)" }
}
if ($missing) { throw "Dependency preflight failed before implementation: $($missing -join '; ')" }
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
refactor, focused regression and commit are independently reviewable. Before
this plan is implemented, the plan reviewer must execute and record these
seventeen gates:

1. **Spec coverage review:** every frozen requirement and both independent
   reviews map to a Section 5 test node.
2. **Placeholder scan:** no undefined helper, placeholder return, unstated
   authority, or forward-owned test remains.
3. **Type/signature consistency review:** every referenced public/private type
   and operation has one exact Section 3 signature.
4. **Task dependency review:** Task 0 preflight precedes Task 1 and no task
   consumes a later owner.
5. **JSON serialization fail-closed review:** no `default=str`; recursive
   validation rejects all prohibited values and writer uses `allow_nan=False`.
6. **Absolute-path persistence review:** inspect every persisted V2.2A payload
   for only relative refs; `artifact_paths` remains transient.
7. **Active manifest revision review:** ensure mapping/event activation is the
   sole selector and inactive higher revisions cannot be inferred active.
8. **Qualifying provenance review:** verify one-to-one associations and that
   provider preference observes only the exact qualifying hash subset.
9. **Smoke/formal transition review:** prove smoke→local upgrades to VALID,
   local→smoke keeps VALID, and ordinary re-import cannot clear INVALIDATED.
10. **Selected provenance handoff review:** formal lookup returns an
    `EligibleDatasetSelection` with its exact binding/ref/hash/capability.
11. **Import-manifest persistence review:** every success and failure returns
    a published immutable import-manifest ref/hash; success binds final records.
12. **Provenance uniqueness review:** same file/provider/fixed clock with
    fresh UUIDs produces distinct import IDs and provenance IDs/hashes.
13. **Split algorithm review:** check effective-date `>`, deterministic event
    order, cumulative Decimal factors, no intermediate quantize, and final
    quantum/ROUND_HALF_EVEN conversion against the existing numeric owner.
14. **Dependency/no-network review:** verify the metadata-only exact-version
    preflight stops before Task 1 and no install/index/network command exists.
15. **Design-to-test traceability review:** every Section 5 node has the exact
    module, test name and expected result stated.
16. **Diff check:** `git diff --check` reports no whitespace errors.
17. **Commit scope check:** this revision changes only this plan document; no
    frozen design, production code, tests, fixtures, requirements, capability
    registry, V2.1 document, push, PR, or Task 1 implementation is included.

After this plan revision, stop and wait for the final independent review. Do
not start Task 1 or V2.2B.
