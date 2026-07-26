# V2.1 Contract & Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax (- [ ]) for tracking.

**Goal:** 建立 V2.1 Contract & Gate 的机器可验证配置、确认授权和本地 runner gate；V2.1 不执行正式回测。

**Architecture:** 在现有 Phase 1 pipeline 外增加 contracts、adapters 和显式 v2 CLI 命名空间。Phase 1 的 hash、manifest、audit 和 provenance 模块继续作为唯一 owner。

**Tech Stack:** Python 3.14-compatible code, standard library, PyYAML 6.0.3, existing pytest 9.1.1, existing Phase 1 modules, JSON Schema. No new dependency is added.

## Global Constraints

- 只实现 V2.1 Contract & Gate，不实现 VectorBT、Futu OpenD 自动启动、数据下载、正式回测或插件执行。
- schema identity 固定为 quant-strategy/v2，schema_version 固定为 v2.1。
- initial_capital 固定为整数 100000 USD；position_sizing 无默认值，必须显式提供。
- filters、stop、target、fill_timing、optimization_allowed、report_language 和 session 都是根级显式必填字段；缺失时不得由 normalization 补齐。
- filters 必须是显式数组（无过滤器时为 []）；stop 和 target 必须显式为 enabled=false 或完整启用配置；fill_timing 必须为 next_bar_open；optimization_allowed 必须为 false；report_language 必须为 zh-CN；session 必须显式声明 America/New_York RTH。
- 所有内部时间使用 UTC；session 固定为 America/New_York、regular_hours_only=true。
- NormalizedStrategyIR 只允许 immutable JSON-like values，不允许任意 Python、callable、表达式字符串或动态导入；ValueExpression 和 PredicateExpression 的根类型边界必须严格校验。
- ExecutionAssumptions 是 assumptions_hash 的唯一输入来源；ConfirmationGrant 绑定 normalized config hash、data plan hash 和正式 assumptions hash，单次、过期、原子消费。
- canonical IR 不含未经规范化的二进制 float；金额和 bps 使用整数，比例和阈值使用 canonical decimal string，禁止 NaN、Infinity 和 -Infinity。
- schema 不把 symbol 限制为 SPY/QQQ；SPY/QQQ 只由 phase1.ema.daily.golden capability 和 Phase1ToV2Adapter 限制。
- V2.1 execute 通过 gate 后仍返回 NOT_IMPLEMENTED 和 EXECUTION_CAPABILITY_NOT_IMPLEMENTED。
- run_manifest.py 的 canonical_hash、sha256_file、sha256_bytes、bind_artifact_hashes 和既有 provenance/audit 接口是唯一 owner。
- 明文 confirmation token 只在一次成功 grant_confirmation RunnerResponse 的 confirmation_token 字段中交付；不进入 state、manifest、evidence、audit 或 stderr，其他模式不得再次返回。
- ConfirmationStore 使用 Windows msvcrt 和 POSIX fcntl 的 lock backend abstraction；PID/age 只能辅助诊断或恢复，不能承担互斥正确性。
- provisional evidence 所有路径必须通过 resolve_under_root(root, relative_path)；dependency_hash 必须由固定的完整依赖 payload 计算。
- 新增测试必须先写失败测试；不得删除、减弱或绕过 Phase 1 测试。
- 每个逻辑任务一个独立提交；不推送、不创建 PR、不合并、不安装依赖。

---

## Final Plan Review Resolution Matrix

| ID | Severity | Resolution | Tasks Updated | Verification |
|---|---|---|---|---|
| P1 | BLOCKER | V2.1 只实现 Phase 1 config → Phase1ToV2Adapter → StrategySpecV2 → NormalizedStrategyIR；V2 → Phase 1 黄金样本转换推迟到 V2.3。适配结果保存 source hash、adapter version、generated V2 payload/hash、warnings、unsupported fields 和 original-file-unchanged evidence。 | Tasks 4、6、7、18、19 | adapter direction, source immutability, V2.1 Exit Gate and integration tests |
| P2 | BLOCKER | filters、stop、target、fill_timing、optimization_allowed、report_language、session 为根级显式必填；normalization 不补缺失字段。 | Tasks 3、4、6 | required-field and missing-explicit-field tests |
| P3 | HIGH | stop/target/filters 的 disabled/empty 状态只允许输入显式值；position_sizing 继续无默认值。 | Tasks 3、4、6 | schema and normalization tests |
| P4 | BLOCKER | AST 拆为 ValueExpression 与 PredicateExpression；entry、exit、filters 只能使用 PredicateExpression 根；compare/cross operands 只能使用 ValueExpression；节点类型、字段、输出类型、单位、ID、递归深度和节点数量均冻结。 | Tasks 5、6 | illegal-root, mixed-type, depth and node-count tests |
| P5 | BLOCKER | 新增 ExecutionAssumptions 正式契约，assumptions_hash 只能由该类型的 canonical payload 计算，并绑定 confirmation request/grant。 | Tasks 9、11、12、18 | assumption payload/hash binding tests |
| P6 | BLOCKER | RunnerResponse 增加 confirmation_token；仅成功 grant_confirmation 一次交付明文 token，持久化和所有其他输出只保存/返回 token hash 或脱敏字段。 | Tasks 11、12、15、18 | token handoff and redaction tests |
| P7 | HIGH | Python contract definitions 是运行时唯一事实来源；JSON Schema 由同一定义生成或逐项一致性核对，不能维护漂移的第二套 required/enums/AST 规则。无法完整执行 Draft 2020-12 时准确称为 contract-equivalent validator。 | Tasks 2、3、5、6、18 | schema/Python parity tests and wording check |
| P8 | BLOCKER | schema 接受合法 US_EQUITY symbol 格式，不限制 SPY/QQQ；SPY/QQQ 限制下沉到 Phase 1 capability 和 adapter；formal 只能由 formal-eligible capability 通过，not_live_verified 不可正式执行。 | Tasks 3、7、10、18 | symbol and require_formal tests |
| P9 | HIGH | IR 和 canonical hash 使用固定数值规范：100000 与 bps 为整数，比例/阈值为 canonical decimal string，Decimal 校验，禁止特殊值和等价数值多 hash。 | Tasks 2、6 | numeric canonicalization and hash tests |
| P10 | BLOCKER | ConfirmationStore 抽象 lock backend：Windows 使用 msvcrt，POSIX 使用 fcntl；temporary + flush/fsync + os.replace；PID/age 仅辅助诊断。 | Tasks 12、18 | concurrency, crash, platform and unsupported-backend tests |
| P11 | HIGH | 所有 evidence path 先经过 resolve_under_root，拒绝 traversal、绝对路径、root 外、符号链接越界、分隔符 request ID、Windows drive/UNC 越界。 | Task 13、18 | dedicated containment tests |
| P12 | HIGH | dependency_hash 由固定 canonical payload 组成，包含 schema/validator/normalizer/compiler/capability/status/cost/corporate-action/benchmark/engine/data/plugin 字段；V2.1 未实现项显式 NOT_IMPLEMENTED 或 null。 | Tasks 13、14、17、18 | dependency payload completeness and mtime-independent tests |
| P13 | HIGH | TemplateRegistry enforce one active version per key、same-key supersedes、no cycle、invalidated not active、monotonic semver、no mtime lookup。 | Tasks 16、17、18 | registry integrity tests |
| P14 | HIGH | capability metadata 同时区分 structural availability、implementation availability、formal eligibility、smoke-only status；implemented but not_live_verified 不能 require_formal。 | Task 10、18 | registry status and formal gate tests |
| P15 | HIGH | recoverable、retryable、terminal 和 user_action 语义冻结并同步到全部 status metadata；示例状态的恢复/重试结论必须可测试。 | Tasks 1、18 | status metadata consistency tests |

---

## 1. 目标

V2.1 完成后，系统能够：

- 接受 quant-strategy/v2、schema_version=v2.1 的策略配置。
- 将配置验证并归一化为 StrategySpecV2 和 NormalizedStrategyIR。
- 生成机器可验证的 ConfirmationRequest 和一次性 ConfirmationGrant。
- 在 token 缺失、过期、已消费或绑定 hash 不一致时拒绝 execute。
- 输出稳定、紧凑、stdout 只有 JSON 的 RunnerResponse。
- 保留第一阶段 hash、manifest、audit 和 provenance 所有权。
- 为 V2.2/V2.3 提供 StrategySpecV2、NormalizedStrategyIR、DataPlan、ExecutionAssumptions、CapabilityRegistry、ConfirmationGrant、RunnerResponse、ArtifactContract、DependencyFingerprint、Phase1ToV2AdapterResult 和 StatusCodeRegistry。

V2.1 完成后仍不能运行正式 VectorBT 回测；execute 即使收到有效 token，也只能原子消费 token 后返回 NOT_IMPLEMENTED，不得下载行情、连接 Futu OpenD、调用 run_pipeline 或产生 formal backtest artifact。

## 2. 现有能力映射

| Existing Module | Current Capability | V2.1 Reuse | Required Adapter | Must Not Duplicate |
|---|---|---|---|---|
| src/tv_quant/research_pipeline.py | PipelineOptions、PipelineResult、Stage 0-7、failure record、provenance helper、run_pipeline | 只读取 blocker/stage 语义并复用 provenance owner | V2 使用独立 run_v2 gate | 不复制数据选择、回测、报告和失败写入 |
| src/tv_quant/pipeline_cli.py | Phase 1 parser、main、退出码、refresh callback | 保持现有 flags/main 行为 | 增加显式 v2 命名空间和 main_v2 | 不把旧 run_pipeline 入口当作 V2 gate |
| src/tv_quant/run_manifest.py | canonical_hash、sha256_file、build_manifest、bind_artifact_hashes、write_manifest | 继续作为唯一 hash/artifact owner | 增加 sha256_bytes primitive | 不在 contracts 中新增 hash 或 manifest writer |
| src/tv_quant/backtest_audit.py | AuditContext、audit_backtest、成本/现金/产物/hash/OOS 检查 | 保留审计状态作为未来 formal eligibility 参考 | ArtifactContract 只定义接口 | 不复制 audit_backtest |
| src/tv_quant/data_quality.py | daily OHLCV、UTC、重复、排序、价格/volume 校验 | 只引用 daily capability | DataPlan 只声明需求 | 不加载行情或复制 validator |
| src/tv_quant/strategy.py | 固定 EMA50/EMA200、next-bar open、费用和现金权益 | 只作为 Phase 1 golden capability evidence | Phase1ToV2Adapter 只生成合法 V2 payload，不调用 engine | 不实现第二套引擎 |
| src/tv_quant/strategy_spec.py | StrategySpec、validate_strategy_mapping、load_strategy_spec、check_capabilities；只支持 Phase 1 daily EMA | 作为 Phase1ToV2Adapter 的目标验证器 | 显式 Phase1ToV2Adapter | 不让旧 parser 静默接受 V2 |
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
  schema_contract.py
  numeric.py
  strategy_v2.py
  ast_contract.py
  normalized_ir.py
  data_plan.py
  execution_assumptions.py
  confirmation.py
  capability_registry.py
  path_safety.py
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
| contracts/schema_contract.py | Python schema source of truth | ROOT_REQUIRED_FIELDS、ENUMS、AST_NODE_DEFINITIONS、render_json_schema、schema_contract_snapshot | definitions | schema payload/snapshot | schema parity tests |
| contracts/numeric.py | canonical numeric policy | canonical_decimal、canonical_integer、canonical_numeric_payload | scalar/path | immutable numeric value | numeric tests |
| contracts/strategy_v2.py | V2 schema and user model | StrategySpecV2、load_strategy_spec_v2、validate_strategy_mapping_v2 | mapping/path | frozen spec | schema tests |
| contracts/ast_contract.py | typed value/predicate AST | ValueExpression、PredicateExpression、validate_ast、node_id | AST mapping | frozen typed AST/issues | AST tests |
| contracts/normalized_ir.py | normalization and hash | NormalizedStrategyIR、normalize_strategy_spec、normalized_config_hash | spec/registry/source hash | immutable IR/result | IR tests |
| contracts/data_plan.py | declarative data requirements | DatasetRequirement、DataPlan、build_data_plan、data_plan_hash | IR/registry | DataPlan | DataPlan tests |
| contracts/execution_assumptions.py | formal execution assumptions | ExecutionAssumptions、build_execution_assumptions、execution_assumptions_payload、assumptions_hash | IR/DataPlan/registry | immutable assumptions/hash | assumptions tests |
| contracts/confirmation.py | request/grant/store | ConfirmationRequest、ConfirmationGrant、ConfirmationStore、FileConfirmationStore | IR/DataPlan/approval/token | grant/context/blocker | confirmation tests |
| contracts/capability_registry.py | honest versioned snapshot | CapabilityRecord、CapabilityRegistry、load_capability_registry | JSON path | snapshot/lookup/hash | registry tests |
| contracts/path_safety.py | evidence root containment | resolve_under_root(root, relative_path) | root/relative path | safe Path/blocker | containment tests |
| contracts/artifact_contract.py | ownership, dependency and formal gate | ArtifactOwner、DependencyFingerprint、dependency_hash、ProvisionalEvidence、FormalResultContract、formal_eligibility | evidence/status/versions | hashes/eligibility | artifact tests |
| contracts/runner_protocol.py | mode/request/response | RunnerMode、RunnerRequest、RunnerResponse、run_v2 | config/token/mode | compact response | runner tests |
| contracts/template_contract.py | deterministic lookup contract | TemplateLookupKey、TemplateRecord、TemplateRegistry | index/key | record/no-match | template tests |
| adapters/phase1_config_adapter.py | explicit old-to-new bridge | Phase1ToV2AdapterResult、adapt_phase1_to_v2 | Phase 1 config path | V2 payload/spec/hashes | adapter tests |
| schemas/quant-strategy-v2.schema.json | machine-readable schema | $id=quant-strategy/v2 | JSON mapping | JSON Schema | schema tests |
| config/capability-registry-v2.1.json | initial honest capability data | six static records | JSON | snapshot | registry tests |

Tests use tmp_path、memory mappings、offline fixtures and monkeypatch only；no network、Futu、VectorBT、provider、run_pipeline or formal backtest. The checked-in JSON Schema is generated from or parity-checked against schema_contract.py; it is not an independently maintained contract.

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
| symbol | string | valid uppercase US equity symbol format; schema does not restrict SPY/QQQ |
| market | string | US_EQUITY |
| timeframe | string | 1d/15m/30m/60m; V2.1 capability only 1d |
| session | object | timezone America/New_York、regular_hours_only true、calendar_id |
| backtest_range | object | ISO dates、start < end |
| initial_capital | object | exactly amount 100000 and currency USD |
| entry | AST object | non-empty allow-listed AST |
| exit | AST object | non-empty allow-listed AST |
| filters | PredicateExpression array | required; [] is explicit no-filter |
| position_sizing | object | required、no null/default |
| stop | object | required enabled boolean |
| target | object | required enabled boolean |
| data | object | DataPlan requirements only |
| benchmark | object | type buy_and_hold、symbol same_as_strategy |
| plugin | object or null | null means no plugin |
| optimization_allowed | boolean | only false |
| report_language | string | required and only zh-CN in V2.1 |

The following seven fields are root-level required fields, not normalization defaults: filters、stop、target、fill_timing、optimization_allowed、report_language and session. The schema must reject each one when absent, even if the omitted value would have been the documented disabled or fixed value.

### 4.2 Units and explicit states

- Capital is an integer USD object with amount 100000 and currency USD; other capital returns INITIAL_CAPITAL_POLICY_BLOCKER.
- Commission/slippage bps are integers；percentages、fractions、risk ratios and indicator thresholds are Decimal-validated canonical decimal strings. `1`、`1.0` and `1.00` serialize to one semantic value and hash.
- Dates are YYYY-MM-DD calendar dates, not local timestamps.
- Session timezone accepts only America/New_York；regular_hours_only is true.
- V2 input fill_timing is next_bar_open；legacy next_bar is accepted only inside the explicit Phase1ToV2Adapter.
- stop/target use enabled=false with no trigger fields, or enabled=true with one registered rule and required units；null is rejected.
- position_sizing has no disabled/null state. full_capital has no parameters；fixed_fraction requires fraction in (0,1]；risk_based requires risk_per_trade and stop_distance.
- benchmark is a same-symbol object, never a free string.
- plugin is null or {name, version, source_hash}；a non-null plugin reference is BLOCKED in V2.1.
- No missing root field in the required list is defaulted by normalization. Only casing, units, ordering and other values already present in the input may be canonicalized. Position sizing has no default.
- Unknown root fields, duplicate semantic fields, unknown schema versions and legacy Phase 1 YAML without explicit V2 loading are rejected.

### 4.3 AST

The AST has two disjoint categories:

| Category | Nodes | Output type | Allowed roots |
|---|---|---|---|
| ValueExpression | indicator_ref、constant、price_ref、volume_ref | typed scalar/series with unit | only operands of compare/cross |
| PredicateExpression | compare、cross_above、cross_below、all、any、not | boolean | entry、exit and every filters item |

- compare requires operator gt、gte、lt、lte、eq or neq and exactly two ValueExpression operands with compatible units.
- cross_above/cross_below require exactly two ValueExpression operands with compatible comparable series units.
- all/any require a non-empty tuple of PredicateExpression children；not requires exactly one PredicateExpression child.
- indicator_ref requires a registered structural name, parameters and declared output/unit；structural names include EMA、SMA、RSI、MACD、ATR、BOLLINGER、DONCHIAN、VOLUME_SMA and RELATIVE_VOLUME, while capability registry decides execution availability.
- constant requires a canonical numeric/string/bool scalar and declared unit；price_ref and volume_ref require an allowed field and unit.
- Every node definition freezes node type、required fields、output type、unit compatibility and additionalProperties=false. Node IDs are assigned from deterministic preorder traversal of canonical child order.
- Validation enforces recursive depth <= 16 and total node count <= 128；exceeding either returns AST_COMPLEXITY_BLOCKER.
- A bare indicator_ref or constant is invalid as an entry、exit or filter root；a ValueExpression cannot be used where PredicateExpression is required.
- No Python source、callable、dynamic import、filesystem or network field is accepted.

### 4.4 Validation and serialization

Python contract definitions in schema_contract.py are the runtime single source of truth for required fields、enums and AST definitions. A standard-library renderer produces the checked-in Draft 2020-12 JSON Schema, and tests compare every required field、enum、additionalProperties rule、AST definition and schema version. If an implementation cannot execute the complete Draft 2020-12 standard, its runtime name and documentation must be contract-equivalent validator, not a claim of full JSON Schema execution. Hash payloads use UTF-8、ensure_ascii=false、sort_keys=true、compact separators、normalized dates、uppercase symbols、explicit disabled states and stable list order. normalized_config_hash calls the existing run_manifest.canonical_hash and excludes file path and mtime.

## 5. StrategySpecV2 和 NormalizedStrategyIR

### 5.1 StrategySpecV2

StrategySpecV2 preserves validated user semantics before any derived compiler metadata; it does not synthesize missing required fields:

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
    raise NotImplementedError

def load_strategy_spec_v2(path: Path) -> StrategySpecV2:
    raise NotImplementedError
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
    raise NotImplementedError

def normalized_config_payload(ir: NormalizedStrategyIR) -> Mapping[str, object]:
    raise NotImplementedError

def normalized_config_hash(ir: NormalizedStrategyIR) -> str:
    raise NotImplementedError
~~~

Normalization rules:

1. uppercase symbol、canonicalize market/timeframe/enums/ISO dates only when the corresponding value exists in the input；
2. require explicit fill_timing、optimization_allowed、report_language、session、filters、stop and target; missing fields are validation blockers, not defaults；
3. require position_sizing without choosing a default；
4. preserve explicit stop/target disabled states and reject extra disabled fields；
5. reject non-integer 100000 USD capital；
6. normalize Decimal-backed numeric values and typed AST order; assign node IDs deterministically；
7. report unsupported capability with code/path/severity/message/recoverable/pipeline_stage/formal_result_eligible；
8. compute hash only from the complete canonical IR, whose numbers contain no Python float.

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

## 6. Phase1ToV2Adapter

The V2.1 compatibility direction is only `Phase 1 config -> Phase1ToV2Adapter -> StrategySpecV2 -> NormalizedStrategyIR`. V2.1 does not convert V2 back to Phase 1; that `V2ToPhase1GoldenAdapter` is deferred to V2.3. The adapter is explicit, never edits the Phase 1 YAML, and never changes StrategySpec or claims that the old parser accepts V2.

### 6.1 Supported conversion

Only this source Phase 1 shape converts into a legal V2 payload:

- equity、SPY/QQQ、1d；
- exact EMA fast 50/slow 200 crossover and exact EMA crossunder；
- generated V2 filters=[]、stop.enabled=false、target.enabled=false、fill_timing=next_bar_open、optimization_allowed=false、report_language=zh-CN and America/New_York RTH session are explicit output fields；
- Phase 1 `cash_limited_long_only` maps to V2 `full_capital`；
- Phase 1 `buy_and_hold` maps to the V2 benchmark object；
- Phase 1 `next_bar` maps to V2 `next_bar_open`；
- explicit injected cost mapping supplies the V2 cost profile IDs；
- the generated V2 payload must itself pass StrategySpecV2 validation before normalization.

### 6.2 Interfaces

~~~python
@dataclass(frozen=True)
class Phase1ToV2AdapterResult:
    generated_v2_payload: Mapping[str, object]
    source_phase1_config_hash: str
    adapter_version: str
    generated_v2_config_hash: str
    conversion_warnings: tuple[str, ...]
    unsupported_fields: tuple[str, ...]
    original_file_hash_before: str
    original_file_hash_after: str
    original_file_unchanged: bool
    source_schema_version: str
    target_schema_version: str

def adapt_phase1_to_v2(
    phase1_config_path: Path,
    *,
    adapter_version: str,
) -> Phase1ToV2AdapterResult:
    raise NotImplementedError
~~~

Phase1ToV2AdapterResult is the formal result name. The adapter computes source_phase1_config_hash from the original bytes, records adapter_version, generated V2 payload and generated V2 config hash, conversion_warnings, unsupported_fields and original_file_unchanged evidence. It calls validate_strategy_mapping_v2 on the generated payload and then the normalizer; it never calls a V2-to-Phase-1 conversion. Unsupported source fields, non-EMA rules, missing explicit Phase 1 fields, non-daily timeframe, non-SPY/QQQ and invalid cost/profile mapping return a precise blocker path without mutating the source.

### 6.3 ExecutionAssumptions

~~~python
@dataclass(frozen=True)
class ExecutionAssumptions:
    initial_capital_policy: str
    fill_timing: str
    session_policy: FrozenMapping
    optimization_policy: str
    report_language: str
    cost_profile_id: str
    corporate_action_profile_id: str
    benchmark_protocol_id: str
    capability_snapshot_hash: str
    schema_version: str
    compiler_version: str
    normalizer_version: str

def build_execution_assumptions(ir, data_plan, capability_registry) -> ExecutionAssumptions:
    raise NotImplementedError

def execution_assumptions_payload(assumptions: ExecutionAssumptions) -> Mapping[str, object]:
    raise NotImplementedError

def assumptions_hash(assumptions: ExecutionAssumptions) -> str:
    raise NotImplementedError
~~~

assumptions_hash accepts only ExecutionAssumptions, never an arbitrary mapping. Its canonical payload contains all listed policy, profile, protocol, capability and compiler/version fields and uses the shared numeric/canonical hash owner.

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

Public functions are create_confirmation_request(ir, data_plan, assumptions, generated_at, expires_at), issue_confirmation_grant(request, approval, store, issued_at), and validate_and_consume(grant_token, request, ir, data_plan, assumptions, store, now). The exact function annotations must be frozen in the implementation. cost_profile_id and corporate_action_profile_id are read from the validated ExecutionAssumptions; callers cannot supply a conflicting loose mapping.

ApprovalRecord.decision must equal CONFIRMED_EXECUTE and is created only after the dialogue layer has matched the exact user response. No function accepts free-form chat text. secrets.token_urlsafe(32) generates the token. Persistent state stores only its SHA-256 hash through run_manifest.sha256_bytes.

The plain token is delivered only as `RunnerResponse.confirmation_token` from a successful `grant_confirmation` invocation. It is returned once on stdout, is not stored in ConfirmationGrant state, manifest, provisional evidence, audit or stderr, and no later mode may reconstruct or return it. State stores `confirmation_token_hash` only.

### 7.2 Atomic consumption

ConfirmationStore exposes put_issued、get、consume_once and write_audit_record. FileConfirmationStore depends on a LockBackend abstraction with a Windows msvcrt backend and a POSIX fcntl flock backend. State updates use temporary file + flush + fsync + os.replace. PID/UTC lock metadata is diagnostic/recovery evidence only, never the mutual-exclusion mechanism; an unsupported backend returns CONFIRMATION_STORAGE_BLOCKER.

- A lock release occurs in finally；crash before replace leaves the grant retryable and crash after replace leaves it consumed. A stale-lock recovery policy may use PID/age as an auxiliary diagnostic, but cannot override a backend lock that is held.
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
    structural_availability: str
    implementation_availability: str
    formal_eligibility: str
    smoke_only_status: str
    blocker_code: str | None
    evidence: tuple[str, ...]
    last_verified: str
    implementation_owner: str

class CapabilityRegistry:
    def get(self, capability_id: str, version: str) -> CapabilityRecord:
        raise NotImplementedError
    def require(self, capability_id: str, version: str) -> CapabilityRecord:
        raise NotImplementedError
    def snapshot_payload(self) -> Mapping[str, object]:
        raise NotImplementedError
    def snapshot_hash(self) -> str:
        raise NotImplementedError
~~~

load_capability_registry loads one versioned JSON file and rejects duplicate IDs、missing fields、unknown statuses and formal records carrying blocker codes. `require_formal(capability_id, version)` succeeds only when structural_availability、implementation_availability and formal_eligibility all allow formal execution; implemented + not_live_verified is rejected. `smoke_only_status` is never formal-eligible. snapshot_hash uses existing canonical_hash.

### 9.2 Initial honest records

config/capability-registry-v2.1.json contains:

| Capability ID | Implementation Status | Formal Status | Blocker/Evidence |
|---|---|---|---|
| phase1.ema.daily.golden | implemented | formal_verified | existing strategy.run_backtest、tests and 81438c7; SPY/QQQ、1d; formal eligible |
| futu.daily.current | implemented | not_live_verified | existing futu_downloader/futu_quota/tests; no V2.1 live connection; not formal eligible |
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
class DependencyFingerprint:
    schema_version: str
    validator_version: str
    normalizer_version: str
    compiler_version: str
    capability_snapshot_hash: str
    status_registry_hash: str
    cost_profile_id: str
    cost_profile_hash: str
    corporate_action_profile_id: str
    corporate_action_profile_hash: str
    benchmark_protocol_version: str
    engine_id: str
    engine_version: str
    data_contract_version: str
    plugin_name: str | None
    plugin_version: str | None
    plugin_hash: str | None

def dependency_hash(fingerprint: DependencyFingerprint) -> str:
    raise NotImplementedError

@dataclass(frozen=True)
class FormalResultContract:
    execution_complete: bool
    final_audit_acceptable: bool
    artifact_hashes_complete: bool
    blocking_status_absent: bool
    atomic_publish_complete: bool
    dependency_hash: str

def formal_eligibility(contract: FormalResultContract) -> bool:
    raise NotImplementedError
~~~

formal_eligibility returns true only when all five booleans are true, dependency_hash is complete and status registry permits formal publication. V2.1 always returns formal_result_published=false. Provisional evidence may contain config、IR、DataPlan、request、grant metadata、capability snapshot and blocker records. V2.1 does not write summary.json、equity.csv、trades.csv、audit.json or template records.

`dependency_hash` is computed from a canonical `DependencyFingerprint` payload containing schema version、validator version、normalizer/compiler version、capability snapshot hash、status registry hash、cost profile ID/hash、corporate-action profile ID/hash、benchmark protocol version、engine ID/version、data contract version and plugin name/version/hash. V2.1 engine and plugin fields are explicit `NOT_IMPLEMENTED` or null; omitted fields are invalid.

### 10.1 Evidence path safety

~~~python
def resolve_under_root(root: Path, relative_path: str) -> Path:
    raise NotImplementedError
~~~

Every provisional evidence path passes through `resolve_under_root(root, relative_path)`. It rejects `..` traversal, absolute paths, root escapes, symlink escapes, request IDs containing path separators, Windows drive/UNC paths and any path whose resolved target is outside the resolved root.
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

All provisional paths use request/run IDs and are not interpreted as backtest results. The path is generated only after `resolve_under_root` accepts a relative path; raw request IDs never become path fragments without validation.

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
    confirmation_token: str | None
    run_directory: str | None
    audit_status: str | None
    formal_result_published: bool
    report_summary_path: str | None
    next_action: str
~~~

RunnerResponse.to_json uses stable keys and compact separators；stdout emits exactly one JSON object plus one newline；diagnostics go to stderr. `confirmation_token` is non-null only for one successful grant_confirmation response. It is null for validate、prepare_confirmation、execute、errors and every subsequent read; no persistent response/evidence field stores plaintext.

### 12.2 Mode behavior

| Mode | Required Inputs | Allowed Effects | Result |
|---|---|---|---|
| validate | config path | read schema/registry only | SUCCESS or BLOCKED；no confirmation/data/backtest |
| prepare_confirmation | valid config path | write provisional request/IR/DataPlan evidence | SUCCESS with request ID and AWAIT_USER_CONFIRMATION |
| grant_confirmation | request path and typed ApprovalRecord path | issue grant and persist token hash only | SUCCESS with request ID and one-time confirmation_token handoff；no provider/engine |
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

TemplateRegistry.lookup_latest(key) sorts valid immutable semantic versions, then config hash as deterministic tie-breaker. It ignores mtime. validate_record requires complete hashes、matching key fields、PASS or explicitly eligible CONDITIONAL_PASS、no blocker、no smoke marker and no invalidation reason. Registry integrity additionally enforces at most one active_version=true for each key, supersedes points to an older record with the same key, no supersedes cycle, invalidated records are never active and semantic versions are monotonic. V2.1 formal_result_published=false makes every V2.1 execute ineligible for saving；lookup of pre-existing eligible records is read-only.

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
CONFIRMATION_STORAGE_BLOCKER
EXECUTION_CAPABILITY_NOT_IMPLEMENTED
AST_COMPLEXITY_BLOCKER
NUMERIC_CANONICALIZATION_BLOCKER
~~~

### 15.2 Status metadata

Each code maps to immutable StatusDefinition fields recoverable、terminal、retryable、user_action、pipeline_stage and formal_result_eligible. `recoverable` means the user can repair the whole workflow through changed input、a new request or newly supplied capability; `retryable` means the exact same input is suitable for direct retry; `terminal` means the current request/run must end. These dimensions are independent and all status records must define all three.

| Code | Status | Recoverable | Retryable | Terminal | User Action | Stage | Formal Eligible |
|---|---|---:|---:|---:|---|---|---:|
| CONFIG_VALIDATION_BLOCKER | BLOCKED | yes | no | yes | edit named config paths | Stage 0 | no |
| STRATEGY_CAPABILITY_BLOCKER | BLOCKED | yes | no | yes | select registered capability | Stage 1 | no |
| DATA_CAPABILITY_BLOCKER | BLOCKED | yes | no | yes | provide validated dataset | Stage 2/3 | no |
| CONFIRMATION_REQUIRED | BLOCKED | yes | no | yes | complete confirmation flow | Gate | no |
| CONFIRMATION_EXPIRED | BLOCKED | yes | no | yes | prepare a new confirmation request | Gate | no |
| CONFIRMATION_ALREADY_USED | BLOCKED | yes | no | yes | prepare a new confirmation request | Gate | no |
| CONFIRMATION_INVALID | BLOCKED | yes | no | yes | repair request/grant binding and create a new request | Gate | no |
| CONFIRMATION_STORAGE_BLOCKER | BLOCKED | yes | no | yes | use a supported lock backend or repair storage | Gate | no |
| CONFIRMATION_HASH_MISMATCH | BLOCKED | yes | no | yes | prepare a new request for the changed configuration | Gate | no |
| EXECUTION_CAPABILITY_NOT_IMPLEMENTED | NOT_IMPLEMENTED | yes | no | yes | wait for V2.3 engine milestone | Execute | no |
| PLUGIN_VALIDATION_BLOCKER | BLOCKED | yes | no | yes | register/validate in later plan | Stage 1 | no |

Existing Phase 1 CapabilityStatus and AuditStatus are mapped only at the compatibility boundary；V2 status strings are not inserted into old enums.

The explicit examples are: CONFIRMATION_ALREADY_USED = recoverable true、retryable false、terminal true；CONFIRMATION_EXPIRED = recoverable true、retryable false、terminal true. Both user_action values require a new confirmation request rather than direct retry.

The implementation registry contains metadata for every listed BlockerCode, not only the representative rows above；tests fail if any code lacks recoverable、retryable、terminal、user_action、pipeline_stage or formal_result_eligible metadata.

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

### 17.1 Shared contracts and numeric policy

tests/contracts/test_schema_contract.py:

- test_python_contract_definitions_are_unique_source_of_truth
- test_json_schema_required_fields_and_enums_match_python_contract
- test_json_schema_ast_definitions_match_python_contract
- test_schema_version_is_consistent_everywhere

tests/contracts/test_numeric_canonicalization.py:

- test_initial_capital_is_integer_100000_usd
- test_bps_are_integer_values
- test_decimal_strings_normalize_1_1_00_to_one_semantic_hash
- test_binary_float_and_special_values_do_not_enter_ir

### 17.2 Schema and semantic model

tests/contracts/test_strategy_v2_schema.py:

- test_valid_minimal_v2_config_loads
- test_schema_id_and_version_are_quant_strategy_v2_v21
- test_symbol_schema_accepts_valid_us_equity_symbol_without_spy_qqq_cap
- test_initial_capital_must_equal_100000_usd
- test_missing_position_sizing_is_rejected_without_default
- test_each_explicit_root_field_is_required_without_normalization_default
- test_disabled_stop_target_and_empty_filters_must_be_present
- test_invalid_timeframe_and_session_enum_are_rejected
- test_unknown_root_field_is_rejected
- test_arbitrary_python_expression_field_is_rejected
- test_schema_rejects_legacy_phase1_without_explicit_v2_version

tests/contracts/test_strategy_v2_semantics.py:

- test_semantic_model_preserves_source_payload
- test_semantic_model_normalizes_symbol_case_only
- test_semantic_model_rejects_non_us_equity
- test_semantic_model_never_fills_missing_explicit_fields

### 17.3 Typed AST and normalization

tests/contracts/test_ast_contract.py:

- test_value_expression_nodes_validate
- test_predicate_expression_nodes_validate
- test_entry_exit_and_filter_roots_require_predicates
- test_bare_indicator_or_constant_root_is_rejected
- test_compare_and_cross_operands_require_value_expressions
- test_mixed_value_predicate_types_are_rejected
- test_node_id_is_deterministic
- test_depth_and_node_count_limits_are_enforced
- test_additional_properties_are_rejected

tests/contracts/test_normalized_ir.py:

- test_missing_explicit_fields_never_become_normalization_defaults
- test_position_sizing_has_no_default
- test_identical_semantics_produce_identical_ir_and_hash
- test_decimal_numeric_forms_produce_identical_hash
- test_different_position_or_cost_semantics_change_hash
- test_symbol_dates_units_and_node_ids_are_canonical
- test_ir_contains_no_float_callable_or_python_source
- test_unsupported_indicator_reports_capability_issue_without_execution

### 17.4 Phase 1 to V2 adapter

tests/adapters/test_phase1_config_adapter.py:

- test_phase1_config_flows_to_v2_spec_then_ir
- test_phase1_to_v2_result_preserves_source_and_generated_hashes
- test_adapter_records_version_warnings_unsupported_fields_and_unchanged_evidence
- test_adapter_rejects_non_ema_or_non_spy_qqq_capability
- test_adapter_emits_explicit_filters_stop_target_fill_and_session
- test_v2_to_phase1_adapter_is_not_part_of_v21
- test_original_phase1_file_bytes_remain_unchanged

### 17.5 DataPlan, assumptions and capability

tests/contracts/test_data_plan.py:

- test_primary_dataset_contains_symbol_timeframe_session_and_range
- test_data_plan_declares_warmup_adjustment_corporate_action_and_cost
- test_auxiliary_requirements_are_structural_and_do_not_fetch_data
- test_provider_preference_and_range_change_data_plan_hash
- test_unimplemented_capability_is_reported_without_provider_call

tests/contracts/test_execution_assumptions.py:

- test_assumptions_contains_all_frozen_policy_and_version_fields
- test_assumptions_hash_accepts_only_execution_assumptions
- test_equivalent_decimal_policies_have_same_hash
- test_missing_engine_and_plugin_are_explicit_not_implemented_or_null

tests/contracts/test_capability_registry.py:

- test_initial_registry_records_phase1_ema_as_only_formal_golden
- test_symbol_structural_support_is_not_phase1_execution_support
- test_vectorbt_intraday_dividend_and_plugin_are_unavailable
- test_futu_daily_is_not_live_verified_and_not_formal_eligible
- test_require_formal_rejects_not_live_verified
- test_duplicate_capability_or_unknown_status_is_rejected
- test_capability_snapshot_hash_is_deterministic

### 17.6 Confirmation and cross-platform store

tests/contracts/test_confirmation.py:

- test_confirmation_request_contains_all_binding_hashes_and_summaries
- test_request_binds_formal_execution_assumptions_hash
- test_grant_requires_typed_confirmed_execute_record
- test_token_is_random_and_persisted_state_contains_only_token_hash
- test_chat_text_is_not_accepted_as_approval

tests/contracts/test_confirmation_store.py:

- test_matching_token_and_hashes_are_accepted
- test_missing_expired_mismatched_and_reused_token_are_rejected
- test_atomic_consume_allows_exactly_one_consumer
- test_lock_release_occurs_after_success_and_failure
- test_crash_before_replace_leaves_grant_retryable
- test_crash_after_replace_keeps_grant_consumed
- test_windows_lock_backend_uses_msvcrt_contract
- test_posix_lock_backend_uses_fcntl_contract
- test_unsupported_lock_backend_returns_storage_blocker
- test_confirmation_audit_record_never_contains_plaintext_token

### 17.7 Evidence, artifact, runner and template

tests/contracts/test_path_safety.py:

- test_resolve_under_root_rejects_parent_traversal_absolute_and_root_escape
- test_resolve_under_root_rejects_symlink_escape
- test_resolve_under_root_rejects_request_id_separators_and_windows_drive_unc

tests/contracts/test_artifact_contract.py:

- test_existing_run_manifest_hash_owner_is_declared
- test_dependency_hash_payload_contains_all_components
- test_provisional_evidence_accepts_only_contained_paths
- test_formal_result_requires_all_five_conditions_and_dependency_hash
- test_v21_execute_cannot_mark_formal_result_published

tests/contracts/test_runner_protocol.py:

- test_validate_mode_returns_compact_success_json
- test_prepare_confirmation_writes_only_provisional_evidence
- test_grant_confirmation_returns_token_once
- test_non_grant_modes_never_return_plaintext_token
- test_execute_without_token_returns_confirmation_required
- test_execute_with_invalid_token_returns_confirmation_invalid
- test_execute_with_valid_token_consumes_once_and_returns_not_implemented
- test_runner_response_contains_required_short_json_fields
- test_runner_does_not_call_pipeline_backtest_or_provider

tests/contracts/test_template_contract.py:

- test_registry_path_is_injected
- test_template_record_contains_immutable_version_and_hashes
- test_lookup_uses_key_not_file_mtime
- test_only_one_active_version_exists_per_key
- test_supersedes_points_to_same_key_older_record
- test_supersedes_cycles_and_non_monotonic_versions_are_rejected
- test_invalidated_record_cannot_be_active
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
- test_recoverable_retryable_terminal_semantics_are_consistent
- test_status_snapshot_hash_is_stable
- test_sha256_bytes_matches_known_digest
- test_existing_manifest_hash_functions_keep_behavior

- [ ] Step 1: 写上述失败测试。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_status_codes.py tests/pipeline/test_run_manifest.py -q；Expected: FAIL because new registry and bytes primitive do not exist.
- [ ] Step 3: 在 status_codes.py 实现 immutable definitions；在 run_manifest.py 只增加 sha256_bytes 并复用既有 hash owner。
- [ ] Step 4: 重新运行同一命令；Expected: PASS。
- [ ] Step 5: Commit message: Add V2.1 status registry and hash primitive.

Rollback: revert only this task commit；保留既有 canonical_hash 和 sha256_file 行为。

### Task 2: Shared contract definitions and numeric canonicalization

**Goal:** 建立所有后续 schema、IR、assumptions 和 dependency hash 共用的 Python 定义与数值规则。

**Files:**
- Create: src/tv_quant/contracts/schema_contract.py
- Create: src/tv_quant/contracts/numeric.py
- Create: tests/contracts/test_schema_contract.py
- Create: tests/contracts/test_numeric_canonicalization.py
- Modify: src/tv_quant/contracts/__init__.py

**Interfaces:** ROOT_REQUIRED_FIELDS、ENUMS、AST_NODE_DEFINITIONS、render_json_schema()、schema_contract_snapshot()、canonical_decimal(value, path)、canonical_integer(value, path)。

**Tests written first:**
- test_python_contract_definitions_are_unique_source_of_truth
- test_decimal_strings_normalize_1_1_00_to_one_semantic_hash
- test_initial_capital_and_bps_are_integer_values
- test_binary_float_and_special_values_do_not_enter_ir

- [ ] Step 1: 写失败测试，使用整数、Decimal、字符串数字、Python float、NaN 和 Infinity fixtures。
- [ ] Step 2: 运行 `python -m pytest tests/contracts/test_schema_contract.py tests/contracts/test_numeric_canonicalization.py -q`；Expected: FAIL because shared definitions and canonical numeric functions do not exist.
- [ ] Step 3: 实现 immutable field/enum definition、Decimal parsing and canonical serialization；100000 USD and bps become integers，ratio/threshold become canonical decimal strings，禁止特殊值；提供 schema renderer input，不复制 hash owner。
- [ ] Step 4: 运行同一命令；Expected: PASS。
- [ ] Step 5: Commit message: Add shared V2 contract and numeric canonicalization.

Rollback: revert only this task commit；不修改 Phase 1 parser、manifest 或运行时数据。

### Task 3: V2 schema document and contract-equivalent validator

**Goal:** 冻结 quant-strategy/v2 的 root、units、AST、disabled states 和 unknown-field policy。

**Files:**
- Create: schemas/quant-strategy-v2.schema.json
- Create: src/tv_quant/contracts/strategy_v2.py
- Test: tests/contracts/test_strategy_v2_schema.py

**Interfaces:** StrategySpecV2、validate_strategy_mapping_v2(payload)、load_strategy_spec_v2(path)。

**Tests written first:**
- test_valid_minimal_v2_config_loads
- test_schema_id_and_version_are_quant_strategy_v2_v21
- test_python_contract_and_json_schema_required_fields_match
- test_symbol_schema_accepts_valid_us_equity_symbol_without_spy_qqq_cap
- test_initial_capital_must_equal_100000_usd
- test_missing_position_sizing_is_rejected_without_default
- test_each_explicit_root_field_is_required_without_normalization_default
- test_invalid_enum_and_unknown_field_are_rejected
- test_disabled_stop_target_and_empty_filters_must_be_present
- test_arbitrary_python_expression_field_is_rejected
- test_legacy_phase1_mapping_requires_explicit_v2_loader

- [ ] Step 1: 写失败测试并建立完全离线 minimal mapping fixture。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_strategy_v2_schema.py -q；Expected: FAIL because schema and loader do not exist.
- [ ] Step 3: 从 schema_contract.py 生成或逐项核对 JSON Schema；实现 contract-equivalent Python validator with additionalProperties=false、all explicit root fields、integer capital、typed AST delegation and deterministic issue paths；不声称完整 Draft 2020-12 execution unless every rule is actually implemented。
- [ ] Step 4: 重新运行命令；Expected: PASS。
- [ ] Step 5: Commit message: Define quant-strategy V2 schema contract.

Rollback: revert only the schema/loader commit；不修改 Phase 1 parser。

### Task 4: StrategySpecV2 semantic model and validation issues

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

### Task 5: Typed ValueExpression and PredicateExpression AST

**Goal:** 让 DSL 的表达式类型、布尔根节点和复杂度限制在独立契约中可验证。

**Files:**
- Create: src/tv_quant/contracts/ast_contract.py
- Create: tests/contracts/test_ast_contract.py
- Modify: src/tv_quant/contracts/schema_contract.py only to import the AST definitions

**Interfaces:** ValueExpression、PredicateExpression、validate_ast(node, expected_type, path)、node_id(node, traversal_path)、MAX_AST_DEPTH=16、MAX_AST_NODES=128。

**Tests written first:**
- test_entry_exit_and_filter_roots_require_predicates
- test_bare_indicator_or_constant_root_is_rejected
- test_compare_and_cross_operands_require_value_expressions
- test_mixed_value_predicate_types_are_rejected
- test_node_id_depth_and_node_count_limits_are_deterministic

- [ ] Step 1: 写失败测试，覆盖裸 indicator/constant 根、compare/cross 类型混用、additionalProperties、递归深度 17 和节点数 129。
- [ ] Step 2: 运行 `python -m pytest tests/contracts/test_ast_contract.py -q`；Expected: FAIL because typed AST validators do not exist.
- [ ] Step 3: 实现两个 sealed node category、required fields、output type、unit compatibility、deterministic preorder IDs、additionalProperties=false and complexity limits；只返回 immutable AST/issues，不执行指标或 Python。
- [ ] Step 4: 运行同一命令；Expected: PASS。
- [ ] Step 5: Commit message: Add typed V2 predicate and value AST contract.

Rollback: revert only the AST contract commit；schema and shared numeric definitions remain reviewable。

### Task 6: NormalizedStrategyIR and deterministic normalization

**Goal:** 生成可哈希、无任意 Python、字段顺序稳定的 IR。

**Files:**
- Create: src/tv_quant/contracts/normalized_ir.py
- Create: tests/contracts/test_normalized_ir.py

**Interfaces:** NormalizedStrategyIR、NormalizationResult、normalize_strategy_spec(spec, capability_registry, source_config_hash)、normalized_config_payload(ir)、normalized_config_hash(ir)。

**Tests written first:**
- test_missing_explicit_fields_never_become_normalization_defaults
- test_normalization_requires_position_sizing
- test_identical_semantics_produce_identical_ir_and_hash
- test_decimal_numeric_forms_produce_identical_hash
- test_different_semantics_change_hash
- test_ir_preserves_explicit_disabled_stop_target_and_empty_filters
- test_node_ids_and_units_are_canonical
- test_ir_contains_no_float_callable_or_python_source
- test_unsupported_capability_reports_issue_without_execution

- [ ] Step 1: 写失败测试，使用固定 registry fixture 和 fixed source hash。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_normalized_ir.py -q；Expected: FAIL because IR does not exist.
- [ ] Step 3: 实现 recursive immutable conversion without filling missing required fields、Decimal-backed numeric canonicalization、fixed integer capital、typed AST、capability issues and owner-backed canonical hash；blocking issue 时不返回 partial IR。
- [ ] Step 4: 运行 python -m pytest tests/contracts/test_strategy_v2_schema.py tests/contracts/test_normalized_ir.py tests/pipeline/test_run_manifest.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Normalize V2 strategy configuration into immutable IR.

Rollback: revert only IR commit；schema/semantic model remain usable。

### Task 7: Explicit Phase1ToV2Adapter

**Goal:** 把旧 Phase 1 config 单向迁移为合法 V2 config，并保留可审计的转换证据。

**Files:**
- Create: src/tv_quant/adapters/phase1_config_adapter.py
- Create: tests/adapters/test_phase1_config_adapter.py

**Interfaces:** Phase1ToV2AdapterResult、adapt_phase1_to_v2(phase1_config_path: Path, adapter_version: str)。

**Tests written first:**
- test_phase1_config_flows_to_v2_spec_then_ir
- test_phase1_to_v2_result_preserves_source_and_generated_hashes
- test_adapter_records_version_warnings_unsupported_fields_and_unchanged_evidence
- test_adapter_emits_explicit_filters_stop_target_fill_and_session
- test_adapter_rejects_non_ema_or_non_spy_qqq_capability
- test_v2_to_phase1_adapter_is_not_part_of_v21
- test_original_phase1_file_bytes_remain_unchanged

- [ ] Step 1: 写失败测试；fixture 从 Phase 1 YAML bytes 计算 source hash，验证 generated V2 payload、warnings、unsupported fields 和原文件不变。
- [ ] Step 2: 运行 `python -m pytest tests/adapters/test_phase1_config_adapter.py -q`；Expected: FAIL because Phase1ToV2Adapter does not exist.
- [ ] Step 3: 实现 Phase 1 config -> generated V2 payload -> validate_strategy_mapping_v2 -> normalize_strategy_spec；SPY/QQQ、daily EMA、cash_limited_long_only、legacy benchmark/fill 和旧成本字段按 allow-list 映射，所有 V2 explicit fields 写入 payload，unsupported field 产生 blocker；不实现 V2ToPhase1GoldenAdapter。
- [ ] Step 4: 运行 `python -m pytest tests/adapters/test_phase1_config_adapter.py tests/contracts/test_strategy_v2_schema.py tests/contracts/test_normalized_ir.py tests/pipeline/test_strategy_spec.py -q`；Expected: PASS。
- [ ] Step 5: Commit message: Add explicit Phase 1 to V2 configuration adapter.

Rollback: revert adapter commit；不改 Phase 1 配置文件和 parser。

### Task 8: DataPlan contract

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

### Task 9: ExecutionAssumptions contract

**Goal:** 把所有影响执行语义和 confirmation binding 的假设集中为一个正式、可哈希类型。

**Files:**
- Create: src/tv_quant/contracts/execution_assumptions.py
- Create: tests/contracts/test_execution_assumptions.py

**Interfaces:** ExecutionAssumptions、build_execution_assumptions(ir, data_plan, capability_registry)、execution_assumptions_payload(assumptions)、assumptions_hash(assumptions)。

**Tests written first:**
- test_assumptions_contains_all_frozen_policy_and_version_fields
- test_assumptions_hash_accepts_only_execution_assumptions
- test_equivalent_decimal_policies_have_same_hash
- test_missing_engine_and_plugin_are_explicit_not_implemented_or_null

- [ ] Step 1: 写失败测试，覆盖 initial capital、fill/session/optimization/report policy、cost/corporate-action/benchmark IDs、capability snapshot 和 schema/compiler/normalizer versions。
- [ ] Step 2: 运行 `python -m pytest tests/contracts/test_execution_assumptions.py -q`；Expected: FAIL because the assumptions type and hash function do not exist.
- [ ] Step 3: 实现 frozen ExecutionAssumptions、完整 canonical payload and owner-backed hash；assumptions_hash 只接受该类型，拒绝任意 mapping，并将未实现 engine/plugin 显式写成 NOT_IMPLEMENTED/null。
- [ ] Step 4: 运行同一命令；Expected: PASS。
- [ ] Step 5: Commit message: Add formal V2 execution assumptions contract.

Rollback: revert assumptions commit；不修改 confirmation storage 或 runner dispatch。

### Task 10: Honest capability registry

**Goal:** 记录当前真实能力，不把设计目标标记为 implemented。

**Files:**
- Create: src/tv_quant/contracts/capability_registry.py
- Create: config/capability-registry-v2.1.json
- Create: tests/contracts/test_capability_registry.py

**Interfaces:** CapabilityRecord、CapabilityRegistry、load_capability_registry(path)、capability_snapshot_hash(registry)、require_formal(capability_id, version)。

**Tests written first:**
- test_phase1_ema_is_only_formal_golden_capability
- test_symbol_structural_support_is_not_phase1_execution_support
- test_vectorbt_intraday_dividend_and_plugin_are_unavailable
- test_futu_daily_is_not_live_verified_and_not_formal_eligible
- test_require_formal_rejects_not_live_verified
- test_duplicate_id_and_unknown_status_are_rejected
- test_formal_status_with_blocker_is_rejected
- test_snapshot_hash_is_deterministic

- [ ] Step 1: 写失败测试。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_capability_registry.py -q；Expected: FAIL because registry module/data do not exist.
- [ ] Step 3: 实现 strict JSON loader and six honest records with structural_availability、implementation_availability、formal_eligibility and smoke_only_status：Phase 1 EMA is the only formal golden；Futu daily is not_live_verified and not formal-eligible；VectorBT/intraday/dividend/plugin remain unavailable；schema symbol validation remains broad US_EQUITY。
- [ ] Step 4: 运行 python -m pytest tests/contracts/test_capability_registry.py tests/contracts/test_normalized_ir.py tests/contracts/test_data_plan.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Register honest V2.1 capability snapshot.

Rollback: revert registry commit；不连接 provider 或修改依赖。

### Task 11: ConfirmationRequest, Grant and one-time handoff

**Goal:** 建立 request/grant 数据和 typed approval 边界。

**Files:**
- Create: src/tv_quant/contracts/confirmation.py
- Create: tests/contracts/test_confirmation.py

**Interfaces:** ApprovalRecord、ConfirmationRequest、ConfirmationGrant、create_confirmation_request、issue_confirmation_grant。

**Tests written first:**
- test_request_contains_three_binding_hashes_and_summaries
- test_request_binds_formal_execution_assumptions_hash
- test_grant_requires_typed_confirmed_execute
- test_token_is_random_and_state_has_only_token_hash
- test_expiry_and_single_use_fields_are_frozen
- test_chat_text_is_not_accepted_as_approval

- [ ] Step 1: 写失败测试；approval fixture 只能是 typed ApprovalRecord。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_confirmation.py -q；Expected: FAIL because request/grant flow does not exist.
- [ ] Step 3: 使用 secrets.token_urlsafe(32) 生成 token，使用 run_manifest.sha256_bytes 产生 token hash，绑定 normalized config/data plan/formal assumptions hashes and expiry；ConfirmationGrant state 只保存 token hash，明文只返回给 runner 的一次性 handoff。
- [ ] Step 4: 运行 python -m pytest tests/contracts/test_confirmation.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Add V2.1 confirmation request and grant contracts.

Rollback: revert request/grant commit；保留 status、hash 和 IR commits。

### Task 12: Cross-platform atomic token store and consume gate

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
- test_lock_release_occurs_after_success_and_failure
- test_windows_lock_backend_uses_msvcrt_contract
- test_posix_lock_backend_uses_fcntl_contract
- test_unsupported_lock_backend_returns_storage_blocker
- test_audit_record_never_contains_plaintext_token

- [ ] Step 1: 写失败测试，使用 injected clock、tmp_path 和 two-consumer threads。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_confirmation_store.py -q；Expected: FAIL because atomic store does not exist.
- [ ] Step 3: 实现 LockBackend abstraction with Windows msvcrt and POSIX fcntl flock、three-hash check、expiry check、temporary file + flush/fsync + os.replace、durable consumed_at and redacted audit；PID/age 只作为诊断和异常恢复辅助，不作为互斥正确性核心。
- [ ] Step 4: 运行 python -m pytest tests/contracts/test_confirmation.py tests/contracts/test_confirmation_store.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Implement atomic V2.1 confirmation token consumption.

Rollback: revert only store commit；不删除无关文件。

### Task 13: Path-safe artifact ownership and formal eligibility

**Goal:** 建立 provisional/formal contract，复用 Phase 1 owner。

**Files:**
- Create: src/tv_quant/contracts/artifact_contract.py
- Create: src/tv_quant/contracts/path_safety.py
- Create: tests/contracts/test_artifact_contract.py
- Create: tests/contracts/test_path_safety.py

**Interfaces:** ArtifactOwner、ProvisionalEvidence、FormalResultContract、DependencyFingerprint、dependency_hash(fingerprint)、formal_eligibility(contract)、resolve_under_root(root, relative_path)。

**Tests written first:**
- test_existing_run_manifest_hash_owner_is_declared
- test_dependency_hash_payload_contains_all_components
- test_provisional_evidence_accepts_only_contained_paths
- test_resolve_under_root_rejects_parent_traversal_absolute_and_root_escape
- test_resolve_under_root_rejects_symlink_escape
- test_resolve_under_root_rejects_request_id_separators_and_windows_drive_unc
- test_formal_result_requires_all_five_conditions_and_dependency_hash
- test_v21_execute_cannot_mark_formal_result_published
- test_contract_does_not_define_second_hash_or_manifest_writer

- [ ] Step 1: 写失败测试，覆盖 dependency payload completeness 和 root containment on Windows/POSIX fixtures。
- [ ] Step 2: 运行 `python -m pytest tests/contracts/test_artifact_contract.py tests/contracts/test_path_safety.py -q`；Expected: FAIL because the ownership, dependency and containment contracts do not exist.
- [ ] Step 3: 只 import existing canonical_hash、sha256_file、sha256_bytes、bind_artifact_hashes；实现固定 DependencyFingerprint payload，V2.1 engine/plugin 显式 NOT_IMPLEMENTED/null；所有 evidence paths 通过 resolve_under_root，使用 pathlib resolve 并拒绝 root 外路径；不创建第二个 manifest/hash/audit/provenance writer。
- [ ] Step 4: 运行 `python -m pytest tests/contracts/test_artifact_contract.py tests/contracts/test_path_safety.py tests/pipeline/test_run_manifest.py tests/pipeline/test_backtest_audit.py -q`；Expected: PASS。
- [ ] Step 5: Commit message: Define V2.1 artifact ownership and path safety gate.

Rollback: revert artifact contract commit；保留既有 manifest/audit 行为。

### Task 14: Runner request/response protocol

**Goal:** 建立四种 mode、稳定短 JSON 和 NOT_IMPLEMENTED execute。

**Files:**
- Create: src/tv_quant/contracts/runner_protocol.py
- Create: tests/contracts/test_runner_protocol.py

**Interfaces:** RunnerMode、RunnerRequest、RunnerResponse、run_v2(request)。

**Tests written first:**
- test_validate_mode_returns_compact_success_json
- test_prepare_confirmation_writes_only_provisional_evidence
- test_grant_confirmation_returns_token_once
- test_non_grant_modes_never_return_plaintext_token
- test_execute_without_token_returns_confirmation_required
- test_execute_with_invalid_token_returns_confirmation_invalid
- test_execute_with_valid_token_consumes_once_and_returns_not_implemented
- test_runner_response_contains_required_short_json_fields
- test_runner_does_not_call_pipeline_backtest_or_provider

- [ ] Step 1: 写失败测试并 monkeypatch run_pipeline、run_backtest、legacy refresh 和 provider call to raise。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_runner_protocol.py -q；Expected: FAIL because dispatcher does not exist.
- [ ] Step 3: 实现 validate、prepare_confirmation、grant_confirmation、execute；只有成功 grant_confirmation 的一次响应带 confirmation_token；execute 只在 binding gate 通过后消费 token，然后返回 NOT_IMPLEMENTED/EXECUTION_CAPABILITY_NOT_IMPLEMENTED，永不进入 engine/provider；所有其他响应 token=None。
- [ ] Step 4: 运行 python -m pytest tests/contracts/test_runner_protocol.py tests/contracts/test_confirmation_store.py tests/contracts/test_artifact_contract.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Add V2.1 local runner protocol.

Rollback: revert runner commit；不生成数据或 formal artifact。

### Task 15: V2 CLI confirmation gate

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
- test_grant_confirmation_stdout_delivers_token_once_and_no_file_contains_plaintext

- [ ] Step 1: 写失败 CLI tests，使用 subprocess-free direct main_v2 calls and captured streams。
- [ ] Step 2: 运行 python -m pytest tests/pipeline/test_v2_cli_gate.py tests/pipeline/test_pipeline_cli.py -q；Expected: V2 tests FAIL。
- [ ] Step 3: 在 pipeline_cli.py 中检测显式 argv[0]=v2；旧 parser/main 保持不变；main_v2 只调用 run_v2，stdout 只输出一次 response JSON，只有 grant_confirmation 成功响应包含 confirmation_token，diagnostics 写 stderr；不把 token 写入 grant state、manifest、evidence 或 audit。
- [ ] Step 4: 运行 python -m pytest tests/pipeline/test_v2_cli_gate.py tests/pipeline/test_pipeline_cli.py tests/pipeline/test_run_pipeline_script.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Add explicit V2 CLI confirmation gate.

Rollback: revert V2 CLI commit；确认 Phase 1 CLI tests remain green。

### Task 16: Template registry contract

**Goal:** 定义稳定 lookup、immutable version 和 audit eligibility，不实现 UI/save flow。

**Files:**
- Create: src/tv_quant/contracts/template_contract.py
- Create: tests/contracts/test_template_contract.py

**Interfaces:** TemplateLookupKey、TemplateRecord、TemplateEligibility、TemplateRegistry、find_latest_eligible。

**Tests written first:**
- test_registry_path_is_injected
- test_template_record_contains_immutable_version_and_hashes
- test_lookup_uses_key_not_file_mtime
- test_only_one_active_version_exists_per_key
- test_supersedes_points_to_same_key_older_record
- test_supersedes_cycles_and_non_monotonic_versions_are_rejected
- test_invalidated_record_cannot_be_active
- test_blocker_smoke_and_invalidated_records_are_ineligible
- test_v21_formal_result_cannot_be_saved

- [ ] Step 1: 写失败 tests，使用 two records with different mtimes and semantic versions。
- [ ] Step 2: 运行 python -m pytest tests/contracts/test_template_contract.py -q；Expected: FAIL because registry contract does not exist.
- [ ] Step 3: 实现 strict record validation、dependency/config hash key、semantic version monotonicity、one-active-per-key、same-key supersedes、cycle detection and invalidation checks；lookup ignores mtime；V2.1 save operation returns NOT_IMPLEMENTED and writes no record。
- [ ] Step 4: 运行 python -m pytest tests/contracts/test_template_contract.py tests/contracts/test_artifact_contract.py tests/contracts/test_runner_protocol.py -q；Expected: PASS。
- [ ] Step 5: Commit message: Define deterministic V2 template registry contract.

Rollback: revert template contract commit；不删除任何现有 registry data。

### Task 17: End-to-end V2.1 gate integration

**Goal:** 验证 public chain 在正式 execution 前完整停机。

**Files:**
- Create: tests/integration/test_v2_1_gate.py
- Modify: src/tv_quant/contracts/__init__.py only for required public exports

**Interfaces:** Phase1ToV2AdapterResult -> StrategySpecV2 -> NormalizedStrategyIR -> DataPlan -> ExecutionAssumptions -> ConfirmationRequest -> ConfirmationGrant -> RunnerResponse -> ProvisionalEvidence。

**Tests written first:**
- test_end_to_end_validate_prepare_grant_execute_stops_before_engine
- test_blocker_prevents_data_backtest_formal_artifact_and_template
- test_v21_runner_response_is_serializable_and_versioned
- test_v22_entry_interfaces_are_stable
- test_confirmation_token_is_returned_only_by_grant_response
- test_evidence_paths_are_contained_and_dependency_hash_is_complete

- [ ] Step 1: 写失败 integration tests using temporary config/request/evidence roots。
- [ ] Step 2: 运行 python -m pytest tests/integration/test_v2_1_gate.py -q；Expected: FAIL until public interfaces connect.
- [ ] Step 3: 实现 only required exports and serialization glue；验证 Phase1ToV2Adapter direction、assumptions binding、one-time token handoff、path containment and formal=false；不增加 provider/engine dispatch。
- [ ] Step 4: 运行 `python -m pytest tests/contracts tests/adapters tests/pipeline/test_v2_cli_gate.py tests/integration/test_v2_1_gate.py -q`；Expected: PASS。
- [ ] Step 5: Commit message: Verify V2.1 contract gate integration.

Rollback: revert integration glue/test commit；各 contract commit remains independently reviewable。

### Task 18: Regression, static security and duplicate-owner review

**Goal:** 证明 V2.1 不存在 live/provider/arbitrary execution path，且 Phase 1 regression unchanged。

**Files:**
- Create: tests/integration/test_v2_1_security.py

**Interfaces:** security tests inspect source and monkeypatch all prohibited dispatch points。

**Tests written first:**
- test_v2_modules_have_no_network_provider_or_engine_import
- test_v2_modules_have_no_arbitrary_execution_construct
- test_v2_runner_does_not_call_legacy_pipeline
- test_v2_contracts_reference_existing_hash_owner
- test_plaintext_confirmation_token_is_absent_from_persistent_outputs
- test_all_status_metadata_defines_recoverable_retryable_terminal
- test_phase1_suite_remains_unchanged

- [ ] Step 1: 写失败 security/regression tests。
- [ ] Step 2: 运行 python -m pytest tests/integration/test_v2_1_security.py -q；Expected: FAIL until isolation checks exist.
- [ ] Step 3: 实现 only isolation fixes inside V2.1 files；V2 modules contain no direct provider/engine/network/arbitrary execution path，and all hash/artifact calls route to the existing owner；token redaction and status metadata consistency are asserted。
- [ ] Step 4: 运行 python -m pytest tests/integration/test_v2_1_security.py tests/pipeline -q；Expected: PASS。
- [ ] Step 5: Commit message: Verify V2.1 security and Phase 1 regression boundaries.

Rollback: revert security test/fix commit；不改 Phase 1 source/test history。

### Task 19: Documentation and final acceptance

**Goal:** 让 V2 权威设计、V2.1 plan、tests 和 exit evidence 对齐。

**Files:**
- Modify: docs/superpowers/specs/2026-07-26-quant-research-automation-v2-design.md only for V2.1 implementation evidence links and frozen interface references
- Test: existing contract/integration tests; no new execution capability

**Interfaces:** 文档只记录实际实现的 file/interface/status，不能把 V2.2/V2.3 能力写成 available。

**Tests written first:**
- test_final_plan_review_matrix_has_p1_through_p15_resolved
- test_v21_exit_gate_checklist_is_complete
- test_v22_entry_interfaces_match_public_exports

- [ ] Step 1: 写 `test_final_plan_review_matrix_has_p1_through_p15_resolved`、`test_v21_exit_gate_checklist_is_complete` 和 `test_v22_entry_interfaces_match_public_exports`，逐项断言本计划的 P1-P15 resolution、任务编号、测试命令和出口条件。
- [ ] Step 2: 运行 `python -m pytest tests/contracts tests/adapters tests/pipeline/test_v2_cli_gate.py tests/integration -q`；Expected: PASS。
- [ ] Step 3: 运行 `python -m pytest tests -q`、`python -m compileall -q src tests`、`git diff --check` 和占位词扫描；Expected: all exit 0 and no unresolved review wording。
- [ ] Step 4: 更新 V2 design 的 V2.1 evidence references 时只记录实际路径、commit 和 status；不得把 VectorBT、provider、intraday、plugin 或正式回测标记为 V2.1 available。
- [ ] Step 5: Commit message: Complete V2.1 contract and gate acceptance.

Rollback: revert only final acceptance commit；不删除或重写 Phase 1 commits。

## 19. 提交策略

Implementation remains on codex/quant-research-automation-v2. Task commits are local only and are not pushed.

| Order | Task | Commit Message |
|---:|---|---|
| 1 | Status/hash owner | Add V2.1 status registry and hash primitive |
| 2 | Shared contracts/numeric | Add shared V2 definitions and numeric canonicalization |
| 3 | Schema | Define quant-strategy V2 contract-equivalent schema |
| 4 | Semantic model | Add V2 strategy semantic model |
| 5 | Typed AST | Add ValueExpression and PredicateExpression contract |
| 6 | Normalized IR | Normalize V2 strategy configuration into immutable IR |
| 7 | Phase 1 to V2 adapter | Add explicit Phase1ToV2Adapter |
| 8 | DataPlan | Define V2.1 data plan contract |
| 9 | Execution assumptions | Add formal ExecutionAssumptions contract |
| 10 | Capability registry | Register honest V2.1 capability snapshot |
| 11 | Confirmation request/grant | Add V2.1 confirmation request, grant and handoff contracts |
| 12 | Atomic token store | Implement cross-platform atomic V2.1 token consumption |
| 13 | Artifact/path contract | Define artifact ownership, dependency hash and path safety |
| 14 | Runner protocol | Add V2.1 local runner protocol |
| 15 | CLI gate | Add explicit V2 CLI confirmation gate |
| 16 | Template registry | Define deterministic V2 template registry contract |
| 17 | Integration | Verify V2.1 contract gate integration |
| 18 | Security/regression | Verify V2.1 security, status and Phase 1 regression boundaries |
| 19 | Final acceptance | Complete V2.1 contract and gate acceptance |

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

- quant-strategy/v2 schema is machine-verifiable, schema_version=v2.1 is enforced, and Python definitions/schema are parity-checked from one source.
- StrategySpecV2 loads valid V2 config and rejects legacy/unknown/unsafe structures.
- filters、stop、target、fill_timing、optimization_allowed、report_language and session are explicit required root fields; normalization does not fill them.
- ValueExpression/PredicateExpression rules reject bare value roots, mixed types, incompatible units, excess depth and excess node count.
- NormalizedStrategyIR is immutable、deterministic、unit-explicit、hash-stable、float-free and contains no executable Python.
- normalized_config_hash is stable and uses the existing hash owner.
- Phase1ToV2Adapter converts the Phase 1 EMA daily config into legal V2 and preserves source hash、adapter version、generated payload/hash、warnings、unsupported fields and unchanged-file evidence；V2ToPhase1GoldenAdapter is not a V2.1 interface.
- ExecutionAssumptions is the only assumptions_hash input and contains all frozen policy/profile/protocol/capability/version fields.
- ConfirmationRequest contains request ID、schema/config/data/assumption hashes、summaries、cost/corporate-action profiles and expiry.
- ConfirmationGrant is single-use、expires、binds all hashes、stores no plaintext token and supports Windows/POSIX atomic/concurrent/crash-safe consumption.
- Only one successful grant_confirmation response returns confirmation_token；state、manifest、evidence、audit、stderr and later responses never contain the plaintext token.
- Missing、invalid、expired、mismatched and reused tokens produce the specified blockers.
- CapabilityRegistry distinguishes structural、implementation、formal and smoke-only status；SPY/QQQ is not a schema restriction；not_live_verified never passes require_formal.
- ArtifactContract reuses Phase 1 hash/manifest/audit/provenance owners、contains complete dependency_hash and prevents duplicate writers.
- Provisional evidence is distinguishable from formal result、all paths are root-contained；V2.1 never publishes formal result or template.
- Runner modes exist、stdout is compact JSON、diagnostics are stderr、exit codes are stable and valid execute returns NOT_IMPLEMENTED.
- V2 CLI has an explicit v2 namespace and cannot route execute to legacy run_pipeline or refresh.
- Template registry has immutable version、deterministic key/lookup、audit eligibility、invalidation and active version fields.
- Template registry enforces one active version per key、same-key supersedes、acyclic history、monotonic semantic versions and no mtime lookup.
- All new contract、adapter、CLI and integration tests pass.
- All Phase 1 tests continue to pass.
- Static review finds no live trading、network、provider、VectorBT、plugin or arbitrary Python execution path.
- No data download、OpenD connection、formal backtest or VectorBT installation occurred.
- All status metadata defines recoverable、retryable、terminal and user_action with the frozen semantics.
- Final working tree is clean.

## 22. V2.2 Entry Gate

V2.2 may start only after every V2.1 Exit Gate item is evidenced by a passing test or committed static review. V2.2 may depend on these stable interfaces:

~~~text
StrategySpecV2
NormalizedStrategyIR
DataPlan
DatasetRequirement
ExecutionAssumptions
CapabilityRegistry
ConfirmationRequest
ConfirmationGrant
AuthorizedExecutionContext
RunnerRequest
RunnerResponse
ArtifactContract
DependencyFingerprint
ProvisionalEvidence
FormalResultContract
StatusCodeRegistry
Phase1ToV2AdapterResult
TemplateLookupKey
TemplateRecord
~~~

V2.2 must not reinterpret these types、bypass ConfirmationStore.consume_once、replace Phase 1 hash/manifest/audit owners、introduce V2ToPhase1GoldenAdapter into V2.1 or assume that VectorBT、OpenD、intraday、dividend or plugin execution is available merely because schema fields exist.

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
4. Schema root fields、enum、units、fixed capital、position sizing、explicit disabled stop/target/filters、AST、contract-equivalent validator、unknown field、serialization 和 canonical hash 已冻结。
5. StrategySpecV2 保留用户语义，NormalizedStrategyIR 只含规范结构；无任意 Python 或二进制 float；typed AST、numeric hash 和 capability issue 结构明确。
6. Phase1ToV2Adapter 的字段映射、unsupported fields、warnings、source/generated hash、version 和失败状态明确；不修改 Phase 1 配置文件，V2ToPhase1GoldenAdapter 不在 V2.1。
7. ExecutionAssumptions 是 assumptions_hash 唯一输入，包含 policy/profile/protocol/capability/version fields；confirmation request/grant、token 生成/一次性交付、expiry、hash binding、atomic consume、crash recovery、concurrency 和 audit redaction 均有任务与测试。
8. V2.1 不取数；DataPlan 是机器契约；初始 registry 不夸大 Phase 1、Futu、VectorBT、intraday、dividend 或 plugin capability。
9. Phase 1 hash、manifest、audit、provenance 仍是唯一 owner；sha256_bytes 进入既有 owner 模块，没有第二实现。
10. Provisional 与 formal 分离；V2.1 execute 只能返回 EXECUTION_CAPABILITY_NOT_IMPLEMENTED，不能发布 formal artifact/template。
11. 四种 runner mode、稳定 JSON、stderr diagnostics、exit codes、legacy compatibility 和 execute gate 均有接口与测试。
12. Evidence root containment、dependency_hash 完整组成、Template registry 单 active/同 key supersedes/无循环/semver 单调、status metadata 三种语义、无实盘/无网络/无任意执行边界均已具体化。
13. 每个任务都有失败测试、失败命令、最小实现、通过命令和提交信息；完整 pytest、compileall、diff check、placeholder scan、live path scan 和 duplicate owner review 已列出。
14. 19 个任务按依赖顺序拆分，每个任务一个提交；没有把所有能力堆进一个任务。
15. Final Plan Review Resolution Matrix 逐项关闭 P1-P15，V2.1 Exit Gate 和 V2.2 Entry Gate 均有逐条可验证条件；没有遗留未决关键行为。
