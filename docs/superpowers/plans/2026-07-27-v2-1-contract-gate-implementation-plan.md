# V2.1 Contract & Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax (- [ ]) for tracking.

**Goal:** 建立 V2.1 Contract & Gate 的机器可验证配置、确认授权和本地 runner gate；V2.1 不执行正式回测。

**Architecture:** 在现有 Phase 1 pipeline 外增加 contracts、adapters 和显式 v2 CLI 命名空间。Phase 1 的 hash、manifest、audit 和 provenance 模块继续作为唯一 owner。

**Tech Stack:** Python 3.14-compatible code, standard library, PyYAML 6.0.3, existing pytest 9.1.1, existing Phase 1 modules, JSON Schema. No new dependency is added.

## Global Constraints

- 只实现 V2.1 Contract & Gate，不实现 VectorBT、Futu OpenD 自动启动、数据下载、正式回测或插件执行。
- schema identity 固定为 quant-strategy/v2，schema_version 固定为 v2.1。
- initial_capital 固定为 100000 USD；position_sizing 无默认值，必须显式提供。
- stop 和 target 必须显式为 enabled=false 或完整启用配置。
- optimization_allowed 固定为 false，fill_timing 规范值为 next_bar_open，报告语言为 zh-CN。
- 所有内部时间使用 UTC；session 固定为 America/New_York、regular_hours_only=true。
- NormalizedStrategyIR 只允许 immutable JSON-like values，不允许任意 Python、callable、表达式字符串或动态导入。
- ConfirmationGrant 绑定 normalized config hash、data plan hash 和 assumptions hash，单次、过期、原子消费。
- V2.1 execute 通过 gate 后仍返回 NOT_IMPLEMENTED 和 EXECUTION_CAPABILITY_NOT_IMPLEMENTED。
- run_manifest.py 的 canonical_hash、sha256_file、bind_artifact_hashes 和既有 provenance/audit 接口是唯一 owner。
- 新增测试必须先写失败测试；不得删除、减弱或绕过 Phase 1 测试。
- 每个逻辑任务一个独立提交；不推送、不创建 PR、不合并、不安装依赖。

---

## 1. 目标

V2.1 完成后，系统能够：

- 接受 quant-strategy/v2、schema_version=v2.1 的策略配置。
- 将配置验证并归一化为 StrategySpecV2 和 NormalizedStrategyIR。
- 生成机器可验证的 ConfirmationRequest 和一次性 ConfirmationGrant。
- 在 token 缺失、过期、已消费或绑定 hash 不一致时拒绝 execute。
- 输出稳定、紧凑、stdout 只有 JSON 的 RunnerResponse。
- 保留第一阶段 hash、manifest、audit 和 provenance 所有权。
- 为 V2.2/V2.3 提供 StrategySpecV2、NormalizedStrategyIR、DataPlan、CapabilityRegistry、ConfirmationGrant、RunnerResponse、ArtifactContract 和 StatusCodeRegistry。

V2.1 完成后仍不能运行正式 VectorBT 回测；execute 即使收到有效 token，也只能原子消费 token 后返回 NOT_IMPLEMENTED，不得下载行情、连接 Futu OpenD、调用 run_pipeline 或产生 formal backtest artifact。

## 2. 现有能力映射

| Existing Module | Current Capability | V2.1 Reuse | Required Adapter | Must Not Duplicate |
|---|---|---|---|---|
| src/tv_quant/research_pipeline.py | PipelineOptions、PipelineResult、Stage 0-7、failure record、provenance helper、run_pipeline | 只读取 blocker/stage 语义并复用 provenance owner | V2 使用独立 run_v2 gate | 不复制数据选择、回测、报告和失败写入 |
| src/tv_quant/pipeline_cli.py | Phase 1 parser、main、退出码、refresh callback | 保持现有 flags/main 行为 | 增加显式 v2 命名空间和 main_v2 | 不把旧 run_pipeline 入口当作 V2 gate |
| src/tv_quant/run_manifest.py | canonical_hash、sha256_file、build_manifest、bind_artifact_hashes、write_manifest | 继续作为唯一 hash/artifact owner | 增加 sha256_bytes primitive | 不在 contracts 中新增 hash 或 manifest writer |
| src/tv_quant/backtest_audit.py | AuditContext、audit_backtest、成本/现金/产物/hash/OOS 检查 | 保留审计状态作为未来 formal eligibility 参考 | ArtifactContract 只定义接口 | 不复制 audit_backtest |
| src/tv_quant/data_quality.py | daily OHLCV、UTC、重复、排序、价格/volume 校验 | 只引用 daily capability | DataPlan 只声明需求 | 不加载行情或复制 validator |
| src/tv_quant/strategy.py | 固定 EMA50/EMA200、next-bar open、费用和现金权益 | 只作为 Phase 1 golden capability evidence | adapter 输出旧 mapping，不调用 engine | 不实现第二套引擎 |
| src/tv_quant/strategy_spec.py | StrategySpec、validate_strategy_mapping、load_strategy_spec、check_capabilities；只支持 Phase 1 daily EMA | 作为 adapter 目标验证器 | 显式 Phase1ConfigAdapter | 不让旧 parser 静默接受 V2 |
| src/tv_quant/pipeline_models.py | Phase 1 status 和 dataclasses | 保留兼容输出 | V2 status bridge | 不把 V2 status 写入旧 enum |
| src/tv_quant/reporting.py / metrics.py | 基础报告和指标/B&H | 只保留为未来 formal owner | 无 V2.1 runtime adapter | 不生成 V2.1 formal result |
| src/tv_quant/futu_downloader.py / futu_quota.py | Futu daily download、CSV update、quota decision | 只记录 capability evidence | V2.2 才定义 provider adapter | V2.1 不启动 OpenD/下载 |
| tests/pipeline/test_strategy_spec.py | Phase 1 schema/capability tests | 全部保留 | 新 adapter tests 独立 | 不修改旧测试适配 V2 |
| tests/pipeline/test_run_manifest.py | hash/manifest/artifact tests | 扩展 owner-level sha256_bytes test | contract tests 调用 owner | 不新增第二套 hash |
| tests/pipeline/test_backtest_audit.py | formal audit tests | 保留 regression | synthetic formal eligibility tests | 不把 V2.1 validation 当 audit |
| tests/pipeline/test_pipeline_cli.py | legacy CLI tests | 全部保留 | 新 test_v2_cli_gate.py | 不改变旧 CLI 契约 |

## 3. 目标目录和文件结构

### 3.1 新增文件

~~~text
src/tv_quant/contracts/
  __init__.py
  status_codes.py
  strategy_v2.py
  normalized_ir.py
  data_plan.py
  confirmation.py
  capability_registry.py
  artifact_contract.py
  runner_protocol.py
  template_contract.py

src/tv_quant/adapters/
  __init__.py
  phase1_config_adapter.py

schemas/quant-strategy-v2.schema.json
config/capability-registry-v2.1.json

tests/contracts/
tests/adapters/test_phase1_config_adapter.py
tests/pipeline/test_v2_cli_gate.py
tests/integration/test_v2_1_gate.py
tests/integration/test_v2_1_security.py
~~~

### 3.2 修改文件

| File | Responsibility | Public Interface | Inputs | Outputs | Dependencies | Tests |
|---|---|---|---|---|---|---|
| src/tv_quant/run_manifest.py | 添加 owner-backed bytes hash | sha256_bytes(payload: bytes) -> str | bytes | SHA-256 hex | existing hashlib owner | tests/pipeline/test_run_manifest.py |
| src/tv_quant/pipeline_cli.py | 保留 legacy、增加 V2 route | build_v2_parser(), main_v2(argv), main(argv) | argv | exit code and V2 JSON | runner_protocol and legacy imports | test_pipeline_cli.py、test_v2_cli_gate.py |

### 3.3 新文件职责

| File | Responsibility | Public Interface | Inputs | Outputs | Tests |
|---|---|---|---|---|---|
| contracts/status_codes.py | V2 status/blocker registry | PipelineStatus、BlockerCode、StatusDefinition、status_definition、status_snapshot_hash | code | metadata/hash | status tests |
| contracts/strategy_v2.py | V2 schema and user model | StrategySpecV2、load_strategy_spec_v2、validate_strategy_mapping_v2 | mapping/path | frozen spec | schema tests |
| contracts/normalized_ir.py | normalization and hash | NormalizedStrategyIR、normalize_strategy_spec、normalized_config_hash | spec/registry/source hash | immutable IR/result | IR tests |
| contracts/data_plan.py | declarative data requirements | DatasetRequirement、DataPlan、build_data_plan、data_plan_hash | IR/registry | DataPlan | DataPlan tests |
| contracts/confirmation.py | request/grant/store | ConfirmationRequest、ConfirmationGrant、ConfirmationStore、FileConfirmationStore | IR/DataPlan/approval/token | grant/context/blocker | confirmation tests |
| contracts/capability_registry.py | honest versioned snapshot | CapabilityRecord、CapabilityRegistry、load_capability_registry | JSON path | snapshot/lookup/hash | registry tests |
| contracts/artifact_contract.py | ownership/formal gate | ArtifactOwner、ProvisionalEvidence、FormalResultContract、formal_eligibility | evidence/status | eligibility | artifact tests |
| contracts/runner_protocol.py | mode/request/response | RunnerMode、RunnerRequest、RunnerResponse、run_v2 | config/token/mode | compact response | runner tests |
| contracts/template_contract.py | deterministic lookup contract | TemplateLookupKey、TemplateRecord、TemplateRegistry | index/key | record/no-match | template tests |
| adapters/phase1_config_adapter.py | explicit old-schema bridge | Phase1AdapterResult、adapt_to_phase1 | IR/cost mapping | Phase 1 mapping/hashes | adapter tests |
| schemas/quant-strategy-v2.schema.json | machine-readable schema | $id=quant-strategy/v2 | JSON mapping | JSON Schema | schema tests |
| config/capability-registry-v2.1.json | initial honest capability data | six static records | JSON | snapshot | registry tests |

Tests use tmp_path、memory mappings、offline fixtures and monkeypatch only；no network、Futu、VectorBT、provider、run_pipeline or formal backtest.

## 4. Schema V2

### 4.1 Identity and root fields

schemas/quant-strategy-v2.schema.json uses $schema draft 2020-12、$id quant-strategy/v2 and additionalProperties=false. schema_version has only enum v2.1.

Required root fields:

| Field | Type | Frozen Rule |
|---|---|---|
| schema_version | string | v2.1 |
| strategy_id | string | non-empty ASCII slug |
| strategy_family | string | non-empty stable key |
| strategy_name | string | non-empty name |
| symbol | string | uppercase; Phase 1 only SPY/QQQ |
| market | string | US_EQUITY |
| timeframe | string | 1d/15m/30m/60m; V2.1 capability only 1d |
| session | object | timezone America/New_York、regular_hours_only true、calendar_id |
| backtest_range | object | ISO dates、start < end |
| initial_capital | object | exactly amount 100000 and currency USD |
| entry | AST object | non-empty allow-listed AST |
| exit | AST object | non-empty allow-listed AST |
| filters | AST array | empty array is explicit no-filter |
| position_sizing | object | required、no null/default |
| stop | object | required enabled boolean |
| target | object | required enabled boolean |
| data | object | DataPlan requirements only |
| benchmark | object | type buy_and_hold、symbol same_as_strategy |
| plugin | object or null | null means no plugin |
| optimization_allowed | boolean | only false |
| report_language | string | only zh-CN in Phase 1 |

### 4.2 Units and defaults

- Capital is a decimal USD object and is checked before IR creation; other capital returns INITIAL_CAPITAL_POLICY_BLOCKER.
- Dates are YYYY-MM-DD calendar dates, not local timestamps.
- Session timezone accepts only America/New_York；regular_hours_only is true.
- V2 input fill_timing is next_bar_open；legacy next_bar is accepted only inside the explicit Phase1ConfigAdapter.
- stop/target use enabled=false with no trigger fields, or enabled=true with one registered rule and required units；null is rejected.
- position_sizing has no disabled/null state. full_capital has no parameters；fixed_fraction requires fraction in (0,1]；risk_based requires risk_per_trade and stop_distance.
- benchmark is a same-symbol object, never a free string.
- plugin is null or {name, version, source_hash}；a non-null plugin reference is BLOCKED in V2.1.
- Allowed normalization defaults are fill_timing=next_bar_open、optimization_allowed=false、report_language=zh-CN、session timezone/RTH、empty filters and disabled stop/target. Position sizing has no default.
- Unknown root fields, duplicate semantic fields, unknown schema versions and legacy Phase 1 YAML without explicit V2 loading are rejected.

### 4.3 AST

Allowed op values are all、any、not、compare、indicator、constant、cross_above and cross_below.

- all/any require a non-empty children array.
- not requires exactly one child.
- compare requires operator gt、gte、lt、lte、eq or neq and two indicator_ref/constant operands.
- indicator requires a registered structural name, params and output. Structural names are EMA、SMA、RSI、MACD、ATR、BOLLINGER、DONCHIAN、VOLUME_SMA and RELATIVE_VOLUME; capability registry decides execution availability.
- cross_above/cross_below require two indicator references.
- constant requires a JSON scalar and unit.
- AST objects use additionalProperties=false; no Python source、callable、dynamic import、filesystem or network field is accepted.
- Node IDs are assigned during normalization from deterministic traversal order.

### 4.4 Validation and serialization

Python validation is the equivalent runtime implementation of the JSON Schema. It returns deterministic issue paths and rejects unknown fields before construction. A future version requires a named migration before acceptance. Hash payloads use UTF-8、ensure_ascii=false、sort_keys=true、compact separators、normalized dates、uppercase symbols、explicit disabled states and stable list order. normalized_config_hash calls the existing run_manifest.canonical_hash and excludes file path and mtime.

## 5. StrategySpecV2 和 NormalizedStrategyIR

### 5.1 StrategySpecV2

StrategySpecV2 preserves validated user semantics before derived defaults:

~~~python
@dataclass(frozen=True)
class StrategySpecV2:
    schema_version: str
    strategy_id: str
    strategy_family: str
    strategy_name: str
    symbol: str
    market: str
    timeframe: str
    session: Mapping[str, object]
    backtest_range: Mapping[str, str]
    initial_capital: Mapping[str, object]
    entry: Mapping[str, object]
    exit: Mapping[str, object]
    filters: tuple[Mapping[str, object], ...]
    position_sizing: Mapping[str, object]
    stop: Mapping[str, object]
    target: Mapping[str, object]
    data: Mapping[str, object]
    benchmark: Mapping[str, object]
    plugin: Mapping[str, object] | None
    optimization_allowed: bool
    report_language: str
    source_payload: Mapping[str, object]
~~~

~~~python
def validate_strategy_mapping_v2(payload: Mapping[str, object]) -> StrategySpecV2:
    pass

def load_strategy_spec_v2(path: Path) -> StrategySpecV2:
    pass
~~~

The loader preserves source_payload, does not mutate the file, fill position sizing, call a provider or call run_pipeline.

### 5.2 NormalizedStrategyIR

NormalizedStrategyIR is frozen and contains only recursively immutable JSON-like values. It contains no source payload、callable、module、class、code string or Python expression.

~~~python
@dataclass(frozen=True)
class NormalizedStrategyIR:
    schema_version: str
    strategy_id: str
    strategy_family: str
    strategy_name: str
    symbol: str
    market: str
    timeframe: str
    session: FrozenMapping
    backtest_range: FrozenMapping
    initial_capital: FrozenMapping
    entry: FrozenAst
    exit: FrozenAst
    filters: tuple[FrozenAst, ...]
    position_sizing: FrozenMapping
    stop: FrozenMapping
    target: FrozenMapping
    data: FrozenMapping
    benchmark: FrozenMapping
    plugin: FrozenMapping | None
    fill_timing: str
    optimization_allowed: bool
    report_language: str
    compiler_version: str
    source_config_hash: str
~~~

~~~python
def normalize_strategy_spec(
    spec: StrategySpecV2,
    *,
    capability_registry: CapabilityRegistry,
    source_config_hash: str,
) -> NormalizationResult:
    pass

def normalized_config_payload(ir: NormalizedStrategyIR) -> Mapping[str, object]:
    pass

def normalized_config_hash(ir: NormalizedStrategyIR) -> str:
    pass
~~~

Normalization rules:

1. uppercase symbol、canonicalize market/timeframe/enums/ISO dates；
2. set fill_timing、optimization_allowed、report_language、session timezone/RTH、benchmark symbol and filters explicitly；
3. require position_sizing without choosing a default；
4. convert missing stop/target to enabled=false and reject extra disabled fields；
5. reject non-100000 USD capital；
6. normalize numeric units and AST order; assign node IDs deterministically；
7. report unsupported capability with code/path/severity/message/recoverable/pipeline_stage/formal_result_eligible；
8. compute hash only from the complete canonical IR.

~~~python
@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    severity: str
    message: str
    recoverable: bool
    pipeline_stage: str
    formal_result_eligible: bool
~~~

## 6. Phase1ConfigAdapter

The adapter is explicit and never edits a Phase 1 YAML, changes StrategySpec or claims that the old parser accepts V2.

### 6.1 Supported conversion

Only this shape converts:

- US_EQUITY、SPY/QQQ、1d；
- exact EMA fast 50/slow 200 crossover and exact EMA crossunder；
- filters empty and plugin null；
- full_capital mapped to {type: cash_limited_long_only}；
- stop/target disabled；
- benchmark object mapped to buy_and_hold；
- next_bar_open mapped to next_bar；
- optimization_allowed false、report_language zh-CN、validated_local_cache_first；
- explicit injected cost mapping for commission/slippage profile IDs.

### 6.2 Interfaces

~~~python
@dataclass(frozen=True)
class Phase1CostMapping:
    profile_id: str
    commission_bps: Decimal
    slippage_bps: Decimal

@dataclass(frozen=True)
class Phase1AdapterResult:
    phase1_payload: Mapping[str, object]
    source_schema_version: str
    target_schema_version: str
    source_config_hash: str
    adapter_version: str
    result_hash: str
    warnings: tuple[str, ...]

def adapt_to_phase1(
    ir: NormalizedStrategyIR,
    *,
    cost_mapping: Phase1CostMapping,
    adapter_version: str,
) -> Phase1AdapterResult:
    pass
~~~

The adapter uses existing canonical_hash for result_hash and returns a new mapping. Tests call existing validate_strategy_mapping on that mapping and verify original config bytes are unchanged. Filters、non-EMA AST、fixed_fraction、risk_based、enabled stop/target、plugin、non-daily timeframe、non-SPY/QQQ and missing cost mapping return the precise blocker path.

## 7. Confirmation 协议

### 7.1 Types and functions

~~~python
@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    confirmation_request_id: str
    decision: str
    recorded_at_utc: str
    actor: str

@dataclass(frozen=True)
class ConfirmationRequest:
    confirmation_request_id: str
    schema_version: str
    normalized_config_hash: str
    data_plan_hash: str
    assumptions_hash: str
    config_summary: FrozenMapping
    data_plan_summary: FrozenMapping
    cost_profile_id: str
    corporate_action_profile_id: str
    generated_at: str
    expires_at: str

@dataclass(frozen=True)
class ConfirmationGrant:
    confirmation_request_id: str
    confirmation_token: str
    bound_config_hash: str
    bound_data_plan_hash: str
    bound_assumptions_hash: str
    issued_at: str
    expires_at: str
    single_use: bool
    consumed_at: str | None
~~~

Public functions are create_confirmation_request(ir, data_plan, assumptions, cost_profile_id, corporate_action_profile_id, generated_at, expires_at), issue_confirmation_grant(request, approval, store, issued_at), and validate_and_consume(grant_token, request, ir, data_plan, store, now). The exact function annotations must be frozen in the implementation.

ApprovalRecord.decision must equal CONFIRMED_EXECUTE and is created only after the dialogue layer has matched the exact user response. No function accepts free-form chat text. secrets.token_urlsafe(32) generates the token. Persistent state stores only its SHA-256 hash through run_manifest.sha256_bytes.

### 7.2 Atomic consumption

ConfirmationStore exposes put_issued、get、consume_once and write_audit_record. FileConfirmationStore stores one state JSON per request, uses an exclusive lock with PID/UTC timestamp, checks expiry and all three hashes under the lock, writes consumed_at through temporary file plus os.replace, and removes the lock in finally.

- Crash before replace leaves the grant retryable；crash after replace leaves it consumed.
- A dead PID lock older than 30 seconds is stale and may be replaced；a live PID or younger lock returns retryable CONFIRMATION_INVALID without consuming.
- Concurrent consumers are serialized；exactly one receives AuthorizedExecutionContext.
- Missing token -> CONFIRMATION_REQUIRED；invalid/missing state -> CONFIRMATION_INVALID；expired -> CONFIRMATION_EXPIRED；hash mismatch -> CONFIRMATION_HASH_MISMATCH；consumed -> CONFIRMATION_ALREADY_USED.
- Audit record stores request ID、binding hashes、timestamps、outcome and blocker code，never plaintext token.

## 8. DataPlan 契约

V2.1 does not download or open data files. It only declares requirements.

~~~python
@dataclass(frozen=True)
class DatasetRequirement:
    dataset_role: str
    provider_preference: tuple[str, ...]
    symbol: str
    market: str
    timeframe: str
    session: FrozenMapping
    timezone: str
    requested_start: str
    requested_end: str
    warmup_bars: int
    adjustment_requirement: str
    corporate_action_requirement: str
    cost_profile_requirement: str
    capability_requirements: tuple[str, ...]

@dataclass(frozen=True)
class DataPlan:
    schema_version: str
    primary: DatasetRequirement
    auxiliary: tuple[DatasetRequirement, ...]
    requested_range: FrozenMapping
    data_plan_hash: str
~~~

build_data_plan(ir, capability_registry) uses validated_local_cache_first、futu_opend_incremental、validated_csv_import、yfinance_smoke_only；it writes no file and calls no provider. It declares symbol/timeframe/session/range、AST warmup、adjustment、corporate-action、cost profile and capability IDs. Auxiliary VIX/SPY/high-timeframe/relative-strength requirements are structural but BLOCKED in V2.1. data_plan_hash uses existing canonical_hash and excludes timestamps、paths and PIDs.

## 9. Capability Registry

### 9.1 Record and lookup

~~~python
@dataclass(frozen=True)
class CapabilityRecord:
    capability_id: str
    version: str
    implementation_status: str
    supported_market: tuple[str, ...]
    supported_timeframes: tuple[str, ...]
    provider: str | None
    required_dependencies: tuple[str, ...]
    formal_status: str
    blocker_code: str | None
    evidence: tuple[str, ...]
    last_verified: str
    implementation_owner: str

class CapabilityRegistry:
    def get(self, capability_id: str, version: str) -> CapabilityRecord:
        pass
    def require(self, capability_id: str, version: str) -> CapabilityRecord:
        pass
    def snapshot_payload(self) -> Mapping[str, object]:
        pass
    def snapshot_hash(self) -> str:
        pass
~~~

load_capability_registry loads one versioned JSON file and rejects duplicate IDs、missing fields、unknown statuses and formal records carrying blocker codes. snapshot_hash uses existing canonical_hash.

### 9.2 Initial honest records

config/capability-registry-v2.1.json contains:

| Capability ID | Implementation Status | Formal Status | Blocker/Evidence |
|---|---|---|---|
| phase1.ema.daily.golden | implemented | formal_verified | existing strategy.run_backtest、tests and 81438c7; SPY/QQQ、1d |
| futu.daily.current | implemented | not_live_verified | existing futu_downloader/futu_quota/tests; no V2.1 live connection |
| vectorbt.daily.main | not_implemented | unavailable | ENGINE_CAPABILITY_BLOCKER |
| intraday.15m.30m.60m | not_implemented | unavailable | DATA_CAPABILITY_BLOCKER |
| corporate_actions.cash_dividend | not_verified | unavailable | CORPORATE_ACTION_DATA_BLOCKER |
| plugin.execution.sandbox | not_implemented | unavailable | PLUGIN_VALIDATION_BLOCKER |

Design-only capabilities must not be marked implemented.

## 10. Artifact Ownership

Phase 1 remains owner of run_manifest.canonical_hash、sha256_file、sha256_bytes、bind_artifact_hashes、research_pipeline provenance、backtest_audit.audit_backtest and reporting.write_reports. V2.1 wrappers reference these functions and do not create a second hash, manifest, audit, provenance or report writer.

~~~python
@dataclass(frozen=True)
class ArtifactOwner:
    artifact_kind: str
    owner_module: str
    owner_function: str
    required: bool

@dataclass(frozen=True)
class ProvisionalEvidence:
    run_id: str
    evidence_kind: str
    paths: tuple[str, ...]
    config_hash: str
    data_plan_hash: str
    capability_snapshot_hash: str
    status: str
    formal_result_published: bool

@dataclass(frozen=True)
class FormalResultContract:
    execution_complete: bool
    final_audit_acceptable: bool
    artifact_hashes_complete: bool
    blocking_status_absent: bool
    atomic_publish_complete: bool

def formal_eligibility(contract: FormalResultContract) -> bool:
    pass
~~~

formal_eligibility returns true only when all five booleans are true and status registry permits formal publication. V2.1 always returns formal_result_published=false. Provisional evidence may contain config、IR、DataPlan、request、grant metadata、capability snapshot and blocker records. V2.1 does not write summary.json、equity.csv、trades.csv、audit.json or template records.
## 11. Provisional 与 Formal Result

### 11.1 Provisional evidence

V2.1 may write only evidence under an injected request/run root:

- source config copy and source config hash；
- NormalizedStrategyIR canonical JSON and normalized_config_hash；
- DataPlan and data_plan_hash；
- ConfirmationRequest and grant metadata with token hash, never plaintext token in persistent state；
- validation issues and blocker records；
- capability snapshot and capability_snapshot_hash；
- confirmation audit record and diagnostics。

All provisional paths use request/run IDs and are not interpreted as backtest results.

### 11.2 Formal result contract

Future formal publication requires execution complete、final audit acceptable、config/data/code/engine/plugin/artifact hashes complete and matching、no blocking status and temporary-directory-plus-atomic-rename publication. V2.1 implements the contract and negative tests only；it does not call write_reports、audit_backtest or any engine/provider and cannot set formal_result_published=true.

## 12. Runner Protocol

### 12.1 Request and response

~~~python
class RunnerMode(str, Enum):
    VALIDATE = "validate"
    PREPARE_CONFIRMATION = "prepare_confirmation"
    GRANT_CONFIRMATION = "grant_confirmation"
    EXECUTE = "execute"

@dataclass(frozen=True)
class RunnerRequest:
    config_path: Path
    mode: RunnerMode
    confirmation_token: str | None = None
    confirmation_request_path: Path | None = None
    approval_record_path: Path | None = None
    evidence_root: Path | None = None

@dataclass(frozen=True)
class RunnerResponse:
    protocol_version: str
    status: str
    blocker_code: str | None
    run_id: str
    confirmation_request_id: str | None
    run_directory: str | None
    audit_status: str | None
    formal_result_published: bool
    report_summary_path: str | None
    next_action: str
~~~

RunnerResponse.to_json uses stable keys and compact separators；stdout emits exactly one JSON object plus one newline；diagnostics go to stderr.

### 12.2 Mode behavior

| Mode | Required Inputs | Allowed Effects | Result |
|---|---|---|---|
| validate | config path | read schema/registry only | SUCCESS or BLOCKED；no confirmation/data/backtest |
| prepare_confirmation | valid config path | write provisional request/IR/DataPlan evidence | SUCCESS with request ID and AWAIT_USER_CONFIRMATION |
| grant_confirmation | request path and typed ApprovalRecord path | issue grant and persist token hash only | SUCCESS with request ID and token handoff；no provider/engine |
| execute | config path、request binding、confirmation token | validate and atomically consume token；no engine/provider | valid gate returns NOT_IMPLEMENTED/EXECUTION_CAPABILITY_NOT_IMPLEMENTED；invalid gate returns confirmation blocker |

run_v2 never imports or calls run_pipeline、run_backtest、futu_downloader、legacy_cli、subprocess provider commands、requests、socket、VectorBT or plugin modules. It receives AuthorizedExecutionContext only from validate_and_consume；V2.1 stops before engine dispatch.

### 12.3 Exit codes

| Exit Code | Condition |
|---:|---|
| 0 | SUCCESS or CONDITIONAL_SUCCESS for a contract operation |
| 2 | malformed CLI arguments or unreadable config path |
| 3 | BLOCKED by strategy/config/capability/confirmation/data contract |
| 4 | FAILED due to deterministic contract/storage failure |
| 5 | NOT_IMPLEMENTED, including valid V2.1 execute |

Response JSON always carries exact status and blocker_code；exit code is only a shell convenience.

## 13. CLI Gate

### 13.1 Compatibility decision

src/tv_quant/pipeline_cli.py::main remains the Phase 1 legacy entry with current flags and tests. An explicit first argument v2 routes to main_v2；no existing invocation changes semantics.

The V2 command surface is:

~~~text
python -m tv_quant.pipeline_cli v2 validate --config <path>
python -m tv_quant.pipeline_cli v2 prepare-confirmation --config <path> --evidence-root <path>
python -m tv_quant.pipeline_cli v2 grant-confirmation --request <path> --approval-record <path> --evidence-root <path>
python -m tv_quant.pipeline_cli v2 execute --config <path> --confirmation-token <token> --request <path> --evidence-root <path>
~~~

grant-confirmation accepts a structured approval record whose decision equals CONFIRMED_EXECUTE；it never accepts a chat string. execute requires a non-empty token and request binding；missing token is rejected before any data/engine dispatch.

### 13.2 Bypass prevention

- main_v2 calls only run_v2 and contract modules；it never calls existing run_pipeline.
- run_v2 accepts only RunnerRequest；engine/provider functions are not dependencies in V2.1.
- AuthorizedExecutionContext is created only after ConfirmationStore.consume_once succeeds.
- The old run_pipeline remains a Phase 1 API and is not a V2 command.
- Tests monkeypatch research_pipeline.run_pipeline、strategy.run_backtest and legacy refresh to raise if a V2 command reaches them.
- Static source review rejects eval、exec、__import__、importlib、dynamic loading and network/provider imports in new V2 modules.

## 14. Template Registry 契约

V2.1 defines and validates registry contracts but does not implement complete user-facing save/overwrite interaction. Future default path is templates/registry/index.json；lookup never uses file modification time.

~~~python
@dataclass(frozen=True)
class TemplateLookupKey:
    strategy_family: str
    symbol: str
    timeframe: str
    schema_version: str
    dependency_hash: str

@dataclass(frozen=True)
class TemplateRecord:
    template_id: str
    immutable_version: str
    strategy_family: str
    symbol: str
    timeframe: str
    schema_version: str
    dependency_hash: str
    config_hash: str
    plugin_hash: str | None
    audit_eligibility: str
    created_at: str
    supersedes: str | None
    active_version: bool
    invalidation_reason: str | None
~~~

TemplateRegistry.lookup_latest(key) sorts valid immutable semantic versions, then config hash as deterministic tie-breaker. It ignores mtime. validate_record requires complete hashes、matching key fields、PASS or explicitly eligible CONDITIONAL_PASS、no blocker、no smoke marker and no invalidation reason. V2.1 formal_result_published=false makes every V2.1 execute ineligible for saving；lookup of pre-existing eligible records is read-only.

## 15. Status Model

### 15.1 V2 statuses

~~~python
class PipelineStatus(str, Enum):
    SUCCESS = "SUCCESS"
    CONDITIONAL_SUCCESS = "CONDITIONAL_SUCCESS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
~~~

BlockerCode includes:

~~~text
CONFIG_VALIDATION_BLOCKER
SCHEMA_VERSION_BLOCKER
SCHEMA_COMPATIBILITY_BLOCKER
INITIAL_CAPITAL_POLICY_BLOCKER
POSITION_SIZING_INPUT_BLOCKER
RELATIVE_STRENGTH_BENCHMARK_BLOCKER
STRATEGY_CAPABILITY_BLOCKER
DATA_CAPABILITY_BLOCKER
DATA_VALIDATION_BLOCKER
CORPORATE_ACTION_DATA_BLOCKER
LIQUIDITY_CAPABILITY_BLOCKER
FUTU_OPEND_START_BLOCKER
FUTU_LOGIN_BLOCKER
FUTU_MARKET_PERMISSION_BLOCKER
FUTU_QUOTA_BLOCKER
PLUGIN_REQUIRED
PLUGIN_LOGIC_CHANGE_REQUIRED
PLUGIN_PARAMETER_VALIDATION_BLOCKER
PLUGIN_VALIDATION_BLOCKER
ENGINE_CAPABILITY_BLOCKER
FILTER_DATA_CAPABILITY_BLOCKER
INTRADAY_TIME_SEMANTICS_BLOCKER
BENCHMARK_FAIRNESS_BLOCKER
COST_PROFILE_CAPABILITY_BLOCKER
CONFIRMATION_REQUIRED
CONFIRMATION_EXPIRED
CONFIRMATION_HASH_MISMATCH
CONFIRMATION_ALREADY_USED
CONFIRMATION_INVALID
EXECUTION_CAPABILITY_NOT_IMPLEMENTED
~~~

### 15.2 Status metadata

Each code maps to immutable StatusDefinition fields recoverable、terminal、retryable、user_action、pipeline_stage and formal_result_eligible.

| Code | Status | Recoverable | Retryable | User Action | Stage | Formal Eligible |
|---|---|---:|---:|---|---|---:|
| CONFIG_VALIDATION_BLOCKER | BLOCKED | yes | no | edit named config paths | Stage 0 | no |
| STRATEGY_CAPABILITY_BLOCKER | BLOCKED | no | no | select registered capability | Stage 1 | no |
| DATA_CAPABILITY_BLOCKER | BLOCKED | yes | no | provide validated dataset | Stage 2/3 | no |
| CONFIRMATION_REQUIRED | BLOCKED | yes | no | complete confirmation flow | Gate | no |
| CONFIRMATION_EXPIRED | BLOCKED | yes | no | prepare new request | Gate | no |
| CONFIRMATION_ALREADY_USED | BLOCKED | no | no | create new request | Gate | no |
| CONFIRMATION_INVALID | BLOCKED | no | no | inspect grant/create request | Gate | no |
| EXECUTION_CAPABILITY_NOT_IMPLEMENTED | NOT_IMPLEMENTED | no | no | wait for V2.3 engine milestone | Execute | no |
| PLUGIN_VALIDATION_BLOCKER | BLOCKED | no | no | register/validate in later plan | Stage 1 | no |

Existing Phase 1 CapabilityStatus and AuditStatus are mapped only at the compatibility boundary；V2 status strings are not inserted into old enums.

## 16. 安全边界

V2.1 tests and static review must prove:

- no real account、broker、order、TradingView webhook or paper/live execution path；
- no network access、Futu connection、automatic download or data refresh；
- no VectorBT import or installation；
- no plugin subprocess or plugin module load；
- no eval、exec、dynamic import、path traversal or arbitrary code string；
- no token cross-config reuse or repeated use；
- token plaintext is absent from manifest、audit、log and persistent confirmation state；
- blocked operations cannot write formal artifact names or template records；
- V2 stdout is one parseable JSON object and diagnostics are stderr；
- evidence paths remain under injected roots；
- Phase 1 legacy CLI and tests remain behaviorally unchanged.

## 17. 测试计划

Tests are written before implementation. Names below are frozen contract names.

### 17.1 Schema: tests/contracts/test_strategy_v2_schema.py

- test_valid_minimal_v2_config_loads
- test_schema_id_and_version_are_quant_strategy_v2_v21
- test_initial_capital_must_equal_100000_usd
- test_missing_position_sizing_is_rejected_without_default
- test_invalid_timeframe_and_session_enum_are_rejected
- test_unknown_root_field_is_rejected
- test_disabled_stop_and_target_are_explicit
- test_null_stop_and_target_are_rejected
- test_ast_all_any_not_and_compare_validate
- test_ast_operator_and_indicator_reference_are_allow_listed
- test_arbitrary_python_expression_field_is_rejected
- test_schema_rejects_legacy_phase1_without_explicit_v2_version
- test_deterministic_serialization_ignores_yaml_mapping_order

### 17.2 Normalization: tests/contracts/test_normalized_ir.py

- test_normalization_fills_only_allowed_explicit_defaults
- test_normalization_requires_position_sizing
- test_identical_semantics_produce_identical_ir_and_hash
- test_different_position_or_cost_semantics_change_hash
- test_symbol_dates_units_and_node_ids_are_canonical
- test_disabled_stop_target_are_present_in_ir
- test_ir_contains_no_callable_or_python_source
- test_unsupported_indicator_reports_capability_issue_without_execution
- test_non_fixed_initial_capital_returns_policy_issue

### 17.3 Adapter: tests/adapters/test_phase1_config_adapter.py

- test_valid_ema_daily_full_capital_converts_to_phase1_mapping
- test_phase1_adapter_preserves_source_and_result_hashes
- test_adapter_records_version_and_conversion_warning
- test_adapter_rejects_filter_and_non_ema_ast
- test_adapter_rejects_enabled_stop_target_and_risk_based_sizing
- test_adapter_rejects_missing_cost_mapping
- test_adapter_does_not_modify_original_v2_config_file
- test_converted_payload_passes_existing_phase1_loader

### 17.4 DataPlan and capability

tests/contracts/test_data_plan.py:

- test_primary_dataset_contains_symbol_timeframe_session_and_range
- test_data_plan_declares_warmup_adjustment_corporate_action_and_cost
- test_auxiliary_requirements_are_structural_and_do_not_fetch_data
- test_provider_preference_and_range_change_data_plan_hash
- test_unimplemented_capability_is_reported_without_provider_call

tests/contracts/test_capability_registry.py:

- test_initial_registry_records_phase1_ema_as_only_formal_golden
- test_vectorbt_is_not_available_in_v21_registry
- test_intraday_dividend_and_plugin_are_not_available
- test_duplicate_capability_or_unknown_status_is_rejected
- test_formal_status_with_blocker_is_rejected
- test_capability_snapshot_hash_is_deterministic

### 17.5 Confirmation

- test_confirmation_request_contains_all_binding_hashes_and_summaries
- test_grant_requires_typed_confirmed_execute_record
- test_token_is_random_and_persisted_state_contains_only_token_hash
- test_matching_token_and_hashes_are_accepted
- test_missing_token_returns_confirmation_required
- test_expired_token_returns_confirmation_expired
- test_mismatched_config_data_or_assumption_hash_is_rejected
- test_reused_token_returns_confirmation_already_used
- test_atomic_consume_allows_exactly_one_consumer
- test_crash_before_replace_leaves_grant_retryable
- test_crash_after_replace_keeps_grant_consumed
- test_stale_dead_lock_can_be_recovered
- test_live_lock_is_not_overwritten
- test_confirmation_audit_record_never_contains_plaintext_token

### 17.6 Artifact, runner and template

- test_existing_run_manifest_hash_owner_is_declared
- test_provisional_evidence_accepts_contract_artifacts
- test_formal_result_requires_all_five_conditions
- test_v21_execute_cannot_mark_formal_result_published
- test_validate_mode_returns_compact_success_json
- test_prepare_confirmation_writes_only_provisional_evidence
- test_grant_confirmation_returns_request_id_and_token_handoff
- test_execute_without_token_returns_confirmation_required
- test_execute_with_invalid_token_returns_confirmation_invalid
- test_execute_with_valid_token_consumes_once_and_returns_not_implemented
- test_runner_response_contains_required_short_json_fields
- test_runner_does_not_call_pipeline_backtest_or_provider
- test_registry_path_is_injected
- test_template_record_contains_immutable_version_and_hashes
- test_lookup_uses_key_not_file_mtime
- test_active_version_and_supersedes_are_validated
- test_blocker_smoke_and_invalidated_records_are_ineligible
## 18. 实施任务拆分

每个任务一个独立提交。每个任务先写失败测试、运行失败测试、实现最小行为、运行通过测试，再提交。任务不得提前开放后续能力。

### Task 1: Status model, package skeleton and shared hash primitive

**Goal:** 建立 V2 status/blocker metadata 和 owner-backed sha256_bytes。

**Files:**
- Create: src/tv_quant/contracts/__init__.py
- Create: src/tv_quant/adapters/__init__.py
- Create: src/tv_quant/contracts/status_codes.py
- Modify: src/tv_quant/run_manifest.py
- Test: tests/contracts/test_status_codes.py
- Test: tests/pipeline/test_run_manifest.py

**Interfaces:** PipelineStatus、BlockerCode、StatusDefinition、status_definition(code)、status_snapshot_hash()、sha256_bytes(payload: bytes) -> str。

**Tests written first:**
- test_all_required_v2_blocker_codes_have_metadata
- test_status_snapshot_hash_is_stable
- test_sha256_bytes_matches_known_digest
- test_existing_manifest_hash_functions_keep_behavior

- [ ] Step 1: 写上述失败测试。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_status_codes.py tests/pipeline/test_run_manifest.py -q；Expected: FAIL because new registry and bytes primitive do not exist.
- [ ] Step 3: 在 status_codes.py 实现 immutable definitions；在 run_manifest.py 只增加 sha256_bytes 并复用既有 hash owner。
- [ ] Step 4: 重新运行同一命令；Expected: PASS。
- [ ] Step 5: Commit message: Add V2.1 status registry and hash primitive.

Rollback: revert only this task commit；保留既有 canonical_hash 和 sha256_file 行为。

### Task 2: V2 schema document and machine validator

**Goal:** 冻结 quant-strategy/v2 的 root、units、AST、disabled states 和 unknown-field policy。

**Files:**
- Create: schemas/quant-strategy-v2.schema.json
- Create: src/tv_quant/contracts/strategy_v2.py
- Test: tests/contracts/test_strategy_v2_schema.py

**Interfaces:** StrategySpecV2、validate_strategy_mapping_v2(payload)、load_strategy_spec_v2(path)。

**Tests written first:**
- test_valid_minimal_v2_config_loads
- test_schema_id_and_version_are_quant_strategy_v2_v21
- test_initial_capital_must_equal_100000_usd
- test_missing_position_sizing_is_rejected_without_default
- test_invalid_enum_and_unknown_field_are_rejected
- test_disabled_stop_and_target_are_explicit
- test_ast_all_any_not_and_compare_validate
- test_arbitrary_python_expression_field_is_rejected
- test_legacy_phase1_mapping_requires_explicit_v2_loader

- [ ] Step 1: 写失败测试并建立完全离线 minimal mapping fixture。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_strategy_v2_schema.py -q；Expected: FAIL because schema and loader do not exist.
- [ ] Step 3: 实现 JSON Schema 和等价 Python validator；使用 additionalProperties=false、递归 AST 校验、固定 capital、explicit stop/target 和 deterministic issue path。
- [ ] Step 4: 重新运行命令；Expected: PASS。
- [ ] Step 5: Commit message: Define quant-strategy V2 schema contract.

Rollback: revert only the schema/loader commit；不修改 Phase 1 parser。

### Task 3: StrategySpecV2 semantic model and validation issues

**Goal:** 保留验证后的用户语义，不在 semantic model 中隐式填充仓位或执行行为。

**Files:**
- Modify: src/tv_quant/contracts/strategy_v2.py
- Create: tests/contracts/test_strategy_v2_semantics.py

**Interfaces:** frozen StrategySpecV2、ValidationIssue、source_payload preservation。

**Tests written first:**
- test_semantic_model_preserves_source_payload
- test_semantic_model_validates_iso_range
- test_semantic_model_normalizes_symbol_case_only
- test_semantic_model_rejects_non_us_equity
- test_semantic_model_never_fills_position_sizing

- [ ] Step 1: 写失败测试。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_strategy_v2_schema.py tests/contracts/test_strategy_v2_semantics.py -q；Expected: semantic tests FAIL.
- [ ] Step 3: 实现 frozen dataclass、稳定 issue path 和 source payload copy；不添加 normalization defaults。
- [ ] Step 4: 重新运行命令；Expected: PASS。
- [ ] Step 5: Commit message: Add V2 strategy semantic model.

Rollback: revert semantic-model commit；schema file remains independently reviewable。

### Task 4: NormalizedStrategyIR and deterministic normalization

**Goal:** 生成可哈希、无任意 Python、字段顺序稳定的 IR。

**Files:**
- Create: src/tv_quant/contracts/normalized_ir.py
- Create: tests/contracts/test_normalized_ir.py

**Interfaces:** NormalizedStrategyIR、NormalizationResult、normalize_strategy_spec(spec, capability_registry, source_config_hash)、normalized_config_payload(ir)、normalized_config_hash(ir)。

**Tests written first:**
- test_normalization_fills_only_allowed_defaults
- test_normalization_requires_position_sizing
- test_identical_semantics_produce_identical_ir_and_hash
- test_different_semantics_change_hash
- test_disabled_stop_target_are_present
- test_node_ids_and_units_are_canonical
- test_ir_contains_no_callable_or_python_source
- test_unsupported_capability_reports_issue_without_execution

- [ ] Step 1: 写失败测试，使用固定 registry fixture 和 fixed source hash。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_normalized_ir.py -q；Expected: FAIL because IR does not exist.
- [ ] Step 3: 实现 recursive immutable conversion、explicit defaults、fixed capital、capability issues and owner-backed canonical hash；blocking issue 时不返回 partial IR。
- [ ] Step 4: 运行 python -m pytest tests/contracts/test_strategy_v2_schema.py tests/contracts/test_normalized_ir.py tests/pipeline/test_run_manifest.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Normalize V2 strategy configuration into immutable IR.

Rollback: revert only IR commit；schema/semantic model remain usable。

### Task 5: Explicit Phase1ConfigAdapter

**Goal:** 只把冻结 EMA daily V2 shape 转成 Phase 1 mapping，并保留双向证据。

**Files:**
- Create: src/tv_quant/adapters/phase1_config_adapter.py
- Create: tests/adapters/test_phase1_config_adapter.py

**Interfaces:** Phase1CostMapping、Phase1AdapterResult、adapt_to_phase1(ir, cost_mapping, adapter_version)。

**Tests written first:**
- test_valid_ema_daily_full_capital_converts
- test_phase1_adapter_preserves_source_and_result_hashes
- test_adapter_records_version_and_warning
- test_adapter_rejects_filters_non_ema_stop_target_and_risk_sizing
- test_adapter_rejects_missing_cost_mapping
- test_adapter_does_not_modify_original_config
- test_converted_payload_passes_existing_phase1_loader

- [ ] Step 1: 写失败测试；cost mapping 必须从 fixture 注入，不能在 adapter 内猜费率。
- [ ] Step 2: 运行 python -m pytest tests/adapters/test_phase1_config_adapter.py -q；Expected: FAIL because adapter does not exist.
- [ ] Step 3: 实现 exact allow-list mapping：full_capital -> cash_limited_long_only、benchmark object -> buy_and_hold、next_bar_open -> next_bar；其余返回具体 blocker。
- [ ] Step 4: 运行 python -m pytest tests/adapters/test_phase1_config_adapter.py tests/pipeline/test_strategy_spec.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Add explicit Phase 1 V2 configuration adapter.

Rollback: revert adapter commit；不改 Phase 1 配置文件和 parser。

### Task 6: DataPlan contract

**Goal:** 声明 primary/auxiliary dataset requirements，但不访问数据。

**Files:**
- Create: src/tv_quant/contracts/data_plan.py
- Create: tests/contracts/test_data_plan.py

**Interfaces:** DatasetRequirement、DataPlan、build_data_plan(ir, capability_registry)、data_plan_hash(plan)。

**Tests written first:**
- test_primary_dataset_contains_required_fields
- test_data_plan_declares_warmup_adjustment_actions_and_cost
- test_auxiliary_requirements_are_structural
- test_provider_preference_and_range_change_hash
- test_unimplemented_capability_does_not_call_provider

- [ ] Step 1: 写失败测试并 monkeypatch provider imports to raise。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_data_plan.py -q；Expected: FAIL because DataPlan does not exist.
- [ ] Step 3: 实现 deterministic declarations、fixed provider preference、capability IDs and existing canonical_hash；不写 cache、不下载、不调用 Futu。
- [ ] Step 4: 运行 python -m pytest tests/contracts/test_data_plan.py tests/contracts/test_normalized_ir.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Define V2.1 data plan contract.

Rollback: revert DataPlan commit；不触碰 downloader 或数据文件。

### Task 7: Honest capability registry

**Goal:** 记录当前真实能力，不把设计目标标记为 implemented。

**Files:**
- Create: src/tv_quant/contracts/capability_registry.py
- Create: config/capability-registry-v2.1.json
- Create: tests/contracts/test_capability_registry.py

**Interfaces:** CapabilityRecord、CapabilityRegistry、load_capability_registry(path)、capability_snapshot_hash(registry)。

**Tests written first:**
- test_phase1_ema_is_only_formal_golden_capability
- test_vectorbt_intraday_dividend_plugin_are_unavailable
- test_futu_daily_is_not_live_verified
- test_duplicate_id_and_unknown_status_are_rejected
- test_formal_status_with_blocker_is_rejected
- test_snapshot_hash_is_deterministic

- [ ] Step 1: 写失败测试。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_capability_registry.py -q；Expected: FAIL because registry module/data do not exist.
- [ ] Step 3: 实现 strict JSON loader and six honest records：Phase 1 EMA formal verified、Futu daily not_live_verified、VectorBT/intraday/dividend/plugin unavailable。
- [ ] Step 4: 运行 python -m pytest tests/contracts/test_capability_registry.py tests/contracts/test_normalized_ir.py tests/contracts/test_data_plan.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Register honest V2.1 capability snapshot.

Rollback: revert registry commit；不连接 provider 或修改依赖。

### Task 8: ConfirmationRequest and ConfirmationGrant

**Goal:** 建立 request/grant 数据和 typed approval 边界。

**Files:**
- Create: src/tv_quant/contracts/confirmation.py
- Create: tests/contracts/test_confirmation.py

**Interfaces:** ApprovalRecord、ConfirmationRequest、ConfirmationGrant、create_confirmation_request、issue_confirmation_grant。

**Tests written first:**
- test_request_contains_three_binding_hashes_and_summaries
- test_grant_requires_typed_confirmed_execute
- test_token_is_random_and_state_has_only_token_hash
- test_expiry_and_single_use_fields_are_frozen
- test_chat_text_is_not_accepted_as_approval

- [ ] Step 1: 写失败测试；approval fixture 只能是 typed ApprovalRecord。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_confirmation.py -q；Expected: FAIL because request/grant flow does not exist.
- [ ] Step 3: 使用 secrets.token_urlsafe(32) 生成 token，使用 run_manifest.sha256_bytes 产生 token hash，绑定 config/data/assumption hashes and expiry；不保存明文 token。
- [ ] Step 4: 运行 python -m pytest tests/contracts/test_confirmation.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Add V2.1 confirmation request and grant contracts.

Rollback: revert request/grant commit；保留 status、hash 和 IR commits。

### Task 9: Atomic token store and consume gate

**Goal:** 实现一次性 token 的原子消费、并发串行化、过期和崩溃恢复。

**Files:**
- Modify: src/tv_quant/contracts/confirmation.py
- Create: tests/contracts/test_confirmation_store.py

**Interfaces:** ConfirmationStore、FileConfirmationStore、validate_and_consume、redacted confirmation audit record。

**Tests written first:**
- test_missing_expired_mismatched_and_reused_token_are_rejected
- test_atomic_consume_allows_exactly_one_consumer
- test_crash_before_replace_leaves_grant_retryable
- test_crash_after_replace_keeps_grant_consumed
- test_stale_dead_lock_can_be_recovered
- test_live_lock_is_not_overwritten
- test_audit_record_never_contains_plaintext_token

- [ ] Step 1: 写失败测试，使用 injected clock、tmp_path 和 two-consumer threads。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_confirmation_store.py -q；Expected: FAIL because atomic store does not exist.
- [ ] Step 3: 实现 exclusive lock、PID/age stale policy、three-hash check、expiry check、temporary file plus os.replace、durable consumed_at and redacted audit。
- [ ] Step 4: 运行 python -m pytest tests/contracts/test_confirmation.py tests/contracts/test_confirmation_store.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Implement atomic V2.1 confirmation token consumption.

Rollback: revert only store commit；不删除无关文件。

### Task 10: Artifact ownership and formal eligibility

**Goal:** 建立 provisional/formal contract，复用 Phase 1 owner。

**Files:**
- Create: src/tv_quant/contracts/artifact_contract.py
- Create: tests/contracts/test_artifact_contract.py

**Interfaces:** ArtifactOwner、ProvisionalEvidence、FormalResultContract、formal_eligibility(contract)。

**Tests written first:**
- test_existing_run_manifest_hash_owner_is_declared
- test_provisional_evidence_accepts_contract_artifacts
- test_formal_result_requires_all_five_conditions
- test_v21_execute_cannot_mark_formal_result_published
- test_contract_does_not_define_second_hash_or_manifest_writer

- [ ] Step 1: 写失败测试。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_artifact_contract.py -q；Expected: FAIL because contract does not exist.
- [ ] Step 3: 只 import existing canonical_hash、sha256_file、bind_artifact_hashes；不在 contracts 中 import hashlib 或创建 manifest writer。
- [ ] Step 4: 运行 python -m pytest tests/contracts/test_artifact_contract.py tests/pipeline/test_run_manifest.py tests/pipeline/test_backtest_audit.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Define V2.1 artifact ownership and formal gate.

Rollback: revert artifact contract commit；保留既有 manifest/audit 行为。

### Task 11: Runner request/response protocol

**Goal:** 建立四种 mode、稳定短 JSON 和 NOT_IMPLEMENTED execute。

**Files:**
- Create: src/tv_quant/contracts/runner_protocol.py
- Create: tests/contracts/test_runner_protocol.py

**Interfaces:** RunnerMode、RunnerRequest、RunnerResponse、run_v2(request)。

**Tests written first:**
- test_validate_mode_returns_compact_success_json
- test_prepare_confirmation_writes_only_provisional_evidence
- test_grant_confirmation_returns_request_id_and_token_handoff
- test_execute_without_token_returns_confirmation_required
- test_execute_with_invalid_token_returns_confirmation_invalid
- test_execute_with_valid_token_consumes_once_and_returns_not_implemented
- test_runner_response_contains_required_short_json_fields
- test_runner_does_not_call_pipeline_backtest_or_provider

- [ ] Step 1: 写失败测试并 monkeypatch run_pipeline、run_backtest、legacy refresh 和 provider call to raise。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_runner_protocol.py -q；Expected: FAIL because dispatcher does not exist.
- [ ] Step 3: 实现 validate、prepare_confirmation、grant_confirmation、execute；execute 只在 binding gate 通过后消费 token，然后返回 NOT_IMPLEMENTED，永不进入 engine/provider。
- [ ] Step 4: 运行 python -m pytest tests/contracts/test_runner_protocol.py tests/contracts/test_confirmation_store.py tests/contracts/test_artifact_contract.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Add V2.1 local runner protocol.

Rollback: revert runner commit；不生成数据或 formal artifact。

### Task 12: V2 CLI confirmation gate

**Goal:** 保持 legacy pipeline_cli，并增加明确 v2 namespace。

**Files:**
- Modify: src/tv_quant/pipeline_cli.py
- Create: tests/pipeline/test_v2_cli_gate.py

**Interfaces:** build_v2_parser()、main_v2(argv) -> int、legacy main(argv) behavior unchanged。

**Tests written first:**
- test_legacy_pipeline_cli_flags_remain_compatible
- test_v2_validate_command_emits_json_only
- test_v2_prepare_confirmation_and_grant_confirmation
- test_v2_execute_without_token_has_nonzero_exit
- test_v2_execute_with_mismatched_token_has_nonzero_exit
- test_v2_execute_with_valid_token_returns_exit_5_not_implemented
- test_v2_stdout_has_one_json_object_and_diagnostics_are_stderr
- test_v2_command_never_calls_legacy_run_pipeline_or_refresh

- [ ] Step 1: 写失败 CLI tests，使用 subprocess-free direct main_v2 calls and captured streams。
- [ ] Step 2: 运行 python -m pytest tests/pipeline/test_v2_cli_gate.py tests/pipeline/test_pipeline_cli.py -q；Expected: V2 tests FAIL。
- [ ] Step 3: 在 pipeline_cli.py 中检测显式 argv[0]=v2；旧 parser/main 保持不变；main_v2 只调用 run_v2，stdout 只输出 response JSON，diagnostics 写 stderr。
- [ ] Step 4: 运行 python -m pytest tests/pipeline/test_v2_cli_gate.py tests/pipeline/test_pipeline_cli.py tests/pipeline/test_run_pipeline_script.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Add explicit V2 CLI confirmation gate.

Rollback: revert V2 CLI commit；确认 Phase 1 CLI tests remain green。

### Task 13: Template registry contract

**Goal:** 定义稳定 lookup、immutable version 和 audit eligibility，不实现 UI/save flow。

**Files:**
- Create: src/tv_quant/contracts/template_contract.py
- Create: tests/contracts/test_template_contract.py

**Interfaces:** TemplateLookupKey、TemplateRecord、TemplateEligibility、TemplateRegistry、find_latest_eligible。

**Tests written first:**
- test_registry_path_is_injected
- test_template_record_contains_immutable_version_and_hashes
- test_lookup_uses_key_not_file_mtime
- test_active_version_and_supersedes_are_validated
- test_blocker_smoke_and_invalidated_records_are_ineligible
- test_v21_formal_result_cannot_be_saved

- [ ] Step 1: 写失败 tests，使用 two records with different mtimes and semantic versions。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_template_contract.py -q；Expected: FAIL because registry contract does not exist.
- [ ] Step 3: 实现 strict record validation、semantic version/hash ordering、active/supersedes/invalidation checks；V2.1 save operation returns NOT_IMPLEMENTED and writes no record。
- [ ] Step 4: 运行 python -m pytest tests/contracts/test_template_contract.py tests/contracts/test_artifact_contract.py tests/contracts/test_runner_protocol.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Define deterministic V2 template registry contract.

Rollback: revert template contract commit；不删除任何现有 registry data。

### Task 14: End-to-end V2.1 gate integration

**Goal:** 验证 public chain 在正式 execution 前完整停机。

**Files:**
- Create: tests/integration/test_v2_1_gate.py
- Modify: src/tv_quant/contracts/__init__.py only for required public exports

**Interfaces:** StrategySpecV2 -> NormalizedStrategyIR -> DataPlan -> ConfirmationRequest -> ConfirmationGrant -> RunnerResponse。

**Tests written first:**
- test_end_to_end_validate_prepare_grant_execute_stops_before_engine
- test_blocker_prevents_data_backtest_formal_artifact_and_template
- test_v21_runner_response_is_serializable_and_versioned
- test_v22_entry_interfaces_are_stable

- [ ] Step 1: 写失败 integration tests using temporary config/request/evidence roots。
- [ ] Step 2: 运行 python -m pytest tests/integration/test_v2_1_gate.py -q；Expected: FAIL until public interfaces connect.
- [ ] Step 3: 实现 only required exports and serialization glue；不增加 provider/engine dispatch。
- [ ] Step 4: 运行 python -m pytest tests/contracts tests/adapters tests/pipeline/test_v2_cli_gate.py tests/integration/test_v2_1_gate.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Verify V2.1 contract gate integration.

Rollback: revert integration glue/test commit；各 contract commit remains independently reviewable。

### Task 15: Regression, static security and duplicate-owner review

**Goal:** 证明 V2.1 不存在 live/provider/arbitrary execution path，且 Phase 1 regression unchanged。

**Files:**
- Create: tests/integration/test_v2_1_security.py

**Interfaces:** security tests inspect source and monkeypatch all prohibited dispatch points。

**Tests written first:**
- test_v2_modules_have_no_network_provider_or_engine_import
- test_v2_modules_have_no_arbitrary_execution_construct
- test_v2_runner_does_not_call_legacy_pipeline
- test_v2_contracts_reference_existing_hash_owner
- test_phase1_suite_remains_unchanged

- [ ] Step 1: 写失败 security/regression tests。
- [ ] Step 2: 运行 python -m pytest tests/integration/test_v2_1_security.py -q；Expected: FAIL until isolation checks exist.
- [ ] Step 3: 实现 only isolation fixes inside V2.1 files；删除 direct provider/engine imports and duplicate hash helpers revealed by tests。
- [ ] Step 4: 运行 python -m pytest tests/integration/test_v2_1_security.py tests/pipeline -q；Expected: PASS。
- [ ] Step 5: Commit message: Verify V2.1 security and Phase 1 regression boundaries.

Rollback: revert security test/fix commit；不改 Phase 1 source/test history。

### Task 16: Documentation and final acceptance

**Goal:** 让 V2 权威设计、V2.1 plan、tests 和 exit evidence 对齐。

**Files:**
- Modify: docs/superpowers/specs/2026-07-26-quant-research-automation-v2-design.md only for V2.1 implementation evidence links and frozen interface references
- Test: existing contract/integration tests; no new execution capability

**Interfaces:** 文档只记录实际实现的 file/interface/status，不能把 V2.2/V2.3 能力写成 available。

- [ ] Step 1: 写缺失的 final acceptance assertion for every V2.1 Exit Gate item not already covered.
- [ ] Step 2: 运行 python -m pytest tests/contracts tests/adapters tests/pipeline/test_v2_cli_gate.py tests/integration -q；Expected: PASS。
- [ ] Step 3: 运行 python -m pytest tests -q、python -m compileall -q src tests、git diff --check；Expected: all exit 0。
- [ ] Step 4: 更新 V2 design 的 V2.1 evidence references；只记录实际路径、commit 和 status，不扩展 V2.1 scope。
- [ ] Step 5: Commit message: Complete V2.1 contract and gate acceptance.

Rollback: revert only final acceptance commit；不删除或重写 Phase 1 commits。

## 19. 提交策略

Implementation remains on codex/quant-research-automation-v2. Task commits are local only and are not pushed.

| Order | Task | Commit Message |
|---:|---|---|
| 1 | Status/hash owner | Add V2.1 status registry and hash primitive |
| 2 | Schema | Define quant-strategy V2 schema contract |
| 3 | Semantic model | Add V2 strategy semantic model |
| 4 | Normalized IR | Normalize V2 strategy configuration into immutable IR |
| 5 | Phase 1 adapter | Add explicit Phase 1 V2 configuration adapter |
| 6 | DataPlan | Define V2.1 data plan contract |
| 7 | Capability registry | Register honest V2.1 capability snapshot |
| 8 | Confirmation request/grant | Add V2.1 confirmation request and grant contracts |
| 9 | Atomic token store | Implement atomic V2.1 confirmation token consumption |
| 10 | Artifact contract | Define V2.1 artifact ownership and formal gate |
| 11 | Runner protocol | Add V2.1 local runner protocol |
| 12 | CLI gate | Add explicit V2 CLI confirmation gate |
| 13 | Template registry | Define deterministic V2 template registry contract |
| 14 | Integration | Verify V2.1 contract gate integration |
| 15 | Security/regression | Verify V2.1 security and Phase 1 regression boundaries |
| 16 | Final acceptance | Complete V2.1 contract and gate acceptance |

Every commit contains only declared files, passes its task tests and leaves no unrelated modifications. No task installs VectorBT, upgrades requirements, downloads data, connects OpenD, runs a formal backtest, creates templates, pushes remote, creates PR or merges.

## 20. 验证命令

No pyproject.toml command is assumed because pyproject.toml is absent.

### 20.1 Focused and full tests

~~~powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m pytest tests/contracts -q
python -m pytest tests/adapters -q
python -m pytest tests/pipeline/test_v2_cli_gate.py -q
python -m pytest tests/integration -q
python -m pytest tests/pipeline -q
python -m pytest tests -q
~~~

Expected: each command exits 0；V2.1 tests perform no network/provider/backtest operation；existing Phase 1 suite remains green.

### 20.2 Syntax and whitespace

~~~powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m compileall -q src tests
git diff --check
~~~

Expected: both commands exit 0.

### 20.3 CLI contract

~~~powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m tv_quant.pipeline_cli --help
python -m tv_quant.pipeline_cli v2 --help
python -m tv_quant.pipeline_cli v2 validate --config tests/fixtures/v2/minimal.yaml
python -m tv_quant.pipeline_cli v2 execute --config tests/fixtures/v2/minimal.yaml --request tests/fixtures/v2/request.json
~~~

Expected: legacy help remains available；V2 help lists four modes；validate returns short JSON；execute without token returns nonzero CONFIRMATION_REQUIRED and creates no formal artifact. Fixture files are created by V2.1 tests in temporary directories, not downloaded.

### 20.4 Live and arbitrary execution path review

~~~powershell
rg -n "futu|OpenD|socket|requests|urllib|httpx|subprocess|order|account|webhook|vectorbt|plugin" src/tv_quant/contracts src/tv_quant/adapters src/tv_quant/pipeline_cli.py tests/integration
rg -n "eval\(|exec\(|__import__|importlib|compile\(" src/tv_quant/contracts src/tv_quant/adapters
~~~

Expected: no V2.1 runtime provider/account/order/network/VectorBT/plugin implementation and no arbitrary execution construct. Static references in negative tests and blocker assertions are allowed only when they do not form an execution path.

### 20.5 Duplicate owner and status review

~~~powershell
rg -n "canonical_hash|sha256_file|sha256_bytes|build_manifest|bind_artifact_hashes|write_manifest|audit_backtest|write_reports" src/tv_quant/contracts src/tv_quant/adapters
git status --short
git diff --name-only
git log --oneline --decorate -20
~~~

Expected: contracts reference existing owners instead of reimplementing them；after each commit status is clean；final history contains only declared local task commits.

## 21. V2.1 Exit Gate

V2.1 is complete only when all conditions are true:

- quant-strategy/v2 schema is machine-verifiable and schema_version=v2.1 is enforced.
- StrategySpecV2 loads valid V2 config and rejects legacy/unknown/unsafe structures.
- NormalizedStrategyIR is immutable、deterministic、unit-explicit、hash-stable and contains no executable Python.
- normalized_config_hash is stable and uses the existing hash owner.
- Phase1ConfigAdapter converts the exact EMA daily golden shape、preserves source/result hashes and leaves the source file unchanged.
- ConfirmationRequest contains request ID、schema/config/data/assumption hashes、summaries、cost/corporate-action profiles and expiry.
- ConfirmationGrant is single-use、expires、binds all hashes、stores no plaintext token and supports atomic/concurrent/crash-safe consumption.
- Missing、invalid、expired、mismatched and reused tokens produce the specified blockers.
- CapabilityRegistry honestly records Phase 1 EMA、current Futu daily status、unavailable VectorBT/intraday/dividend/plugin capabilities and deterministic snapshot hash.
- ArtifactContract reuses Phase 1 hash/manifest/audit/provenance owners and prevents duplicate writers.
- Provisional evidence is distinguishable from formal result；V2.1 never publishes formal result or template.
- Runner modes exist、stdout is compact JSON、diagnostics are stderr、exit codes are stable and valid execute returns NOT_IMPLEMENTED.
- V2 CLI has an explicit v2 namespace and cannot route execute to legacy run_pipeline or refresh.
- Template registry has immutable version、deterministic key/lookup、audit eligibility、invalidation and active version fields.
- All new contract、adapter、CLI and integration tests pass.
- All Phase 1 tests continue to pass.
- Static review finds no live trading、network、provider、VectorBT、plugin or arbitrary Python execution path.
- No data download、OpenD connection、formal backtest or VectorBT installation occurred.
- Final working tree is clean.

## 22. V2.2 Entry Gate

V2.2 may start only after every V2.1 Exit Gate item is evidenced by a passing test or committed static review. V2.2 may depend on these stable interfaces:

~~~text
StrategySpecV2
NormalizedStrategyIR
DataPlan
DatasetRequirement
CapabilityRegistry
ConfirmationRequest
ConfirmationGrant
AuthorizedExecutionContext
RunnerRequest
RunnerResponse
ArtifactContract
ProvisionalEvidence
FormalResultContract
StatusCodeRegistry
Phase1AdapterResult
TemplateLookupKey
TemplateRecord
~~~

V2.2 must not reinterpret these types、bypass ConfirmationStore.consume_once、replace Phase 1 hash/manifest/audit owners or assume that VectorBT、OpenD、intraday、dividend or plugin execution is available merely because schema fields exist.

## 23. 风险分析

| Risk | Prevention | Verification |
|---|---|---|
| 破坏 Phase 1 CLI | keep legacy parser/main unchanged；route only explicit v2 | existing test_pipeline_cli.py and V2 compatibility tests |
| 第二套 hash 系统 | add only sha256_bytes to run_manifest.py；import owner primitives elsewhere | source scan and owner tests |
| token 可重复使用 | persist token hash and consumed_at；exclusive lock plus atomic replace | concurrent/replay/crash tests |
| token 未绑定 config/data hash | compare all three hashes at every execute | mismatch tests for each binding |
| execute 绕过 CLI gate | V2 runner requires AuthorizedExecutionContext；no engine dependency | monkeypatch run_pipeline/run_backtest and source scan |
| registry 夸大未实现能力 | static records use unavailable/not_implemented with blocker | registry status tests |
| schema 过早承诺可执行指标 | structural AST enum separated from capability registry | unsupported-indicator test |
| provisional 被误当 formal | formal_result_published=false and five-condition contract | artifact/runner integration tests |
| template 接受无审计配置 | require eligible audit、no blocker/smoke、complete hashes | template validation tests |
| stdout 混入日志 | central response JSON and stderr diagnostics | captured stdout/stderr test |
| 并发消费 token | exclusive lock、PID/age stale policy and atomic replace | two-consumer and lock tests |
| 时间依赖测试不稳定 | inject clock and fixed UTC fixtures | expiry/crash/hash tests |
| Windows 路径/原子替换差异 | pathlib、os.replace、exclusive creation and tmp_path | Windows-compatible test commands |
| V2.1 触发数据下载 | DataPlan declarative；runner has no provider dependency | no-provider monkeypatch and static scan |
| Phase 1 adapter 偷渡 V2 | exact allow-list and injected cost mapping | unsupported-field tests |
| future schema silently accepted | version enum and migration registry | schema version test |
| lookup 依赖 mtime | semantic version/config hash sorting | mtime-independent test |

## 24. 计划自检

1. Scope 只包含 V2.1 Contract & Gate；没有 VectorBT、Futu 自动启动、正式数据下载、intraday、过滤器执行、通用指标、正式 Buy and Hold、公司行为处理、插件执行、模板 UI、优化或正式回测任务。
2. Existing capability mapping 覆盖 research_pipeline.py、pipeline_cli.py、run_manifest.py、backtest_audit.py、data_quality.py、strategy.py、配置 parser、报告/artifact/hash/provenance 和相关测试。
3. 所有新增/修改文件、职责、public interface、输入、输出、依赖和测试均已列出；仓库不存在 pyproject.toml，验证命令未依赖它。
4. Schema root fields、enum、units、fixed capital、position sizing、disabled stop/target、AST、migration、unknown field、serialization 和 canonical hash 已冻结。
5. StrategySpecV2 保留用户语义，NormalizedStrategyIR 只含规范结构；无任意 Python；hash 和 capability issue 结构明确。
6. Phase1ConfigAdapter 的字段映射、unsupported fields、warnings、source/result hash、version 和失败状态明确；不修改 Phase 1 配置文件。
7. Confirmation request/grant、token 生成/存储、expiry、hash binding、atomic consume、crash recovery、concurrency 和 audit redaction 均有任务与测试。
8. V2.1 不取数；DataPlan 是机器契约；初始 registry 不夸大 Phase 1、Futu、VectorBT、intraday、dividend 或 plugin capability。
9. Phase 1 hash、manifest、audit、provenance 仍是唯一 owner；sha256_bytes 进入既有 owner 模块，没有第二实现。
10. Provisional 与 formal 分离；V2.1 execute 只能返回 EXECUTION_CAPABILITY_NOT_IMPLEMENTED，不能发布 formal artifact/template。
11. 四种 runner mode、稳定 JSON、stderr diagnostics、exit codes、legacy compatibility 和 execute gate 均有接口与测试。
12. Template registry key/eligibility/invalidation、五态 status、blocker metadata、无实盘/无网络/无任意执行边界均已具体化。
13. 每个任务都有失败测试、失败命令、最小实现、通过命令和提交信息；完整 pytest、compileall、diff check、live path scan 和 duplicate owner review 已列出。
14. 16 个任务按依赖顺序拆分，每个任务一个提交；没有把所有能力堆进一个任务。
15. V2.1 Exit Gate 和 V2.2 Entry Gate 均有逐条可验证条件；没有遗留未决关键行为。
