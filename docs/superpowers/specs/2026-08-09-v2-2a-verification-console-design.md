# V2.2A Visual Verification Console Design

状态：FROZEN DEVELOPER-TOOLING DESIGN

日期：2026-08-09

实施分支：`codex/v2-2a-data-foundation-impl`

Task 1 基线提交：`c58f59b95e0291685d4f71119f1e765d1b3a596a`

API 版本：`v1`

本设计只冻结 V2.2A developer verification tooling。它不修改、扩展或重新解释 `2026-08-02-v2-2a-data-foundation-design.md` 中的 frozen business design，不修改 Task 1 production code，不授权 Task 2，也不授权本设计阶段实现任何网页或服务代码。

## 1. Decision Summary

V2.2A Visual Verification Console v0.1 采用以下已批准方案：

- Python 标准库 localhost HTTP 服务；
- 原生 HTML、CSS 和 JavaScript；
- server-side fixed allow-list test runner；
- 稳定的 `/api/v1/*` JSON API；
- 0 个新增第三方 Web dependencies。

Console 是只供开发者验证实现证据的观察与受限执行界面，不是 production control plane。它只能调用仓库中已经存在的 pytest suites/test nodes 或固定的只读 Git 检查，不复制 production 测试逻辑，不提供任意命令入口，也不参与 V2.2A 数据处理、回测、provider、broker 或订单流程。

## 2. Goals

v0.1 必须做到：

1. 用一个 localhost 页面集中显示 Task 1–17 的真实实施、测试、review 和 Console verification 状态。
2. 通过固定 allow-list 执行当前任务的 focused、regression、V2.1 baseline 和 repository diff checks。
3. 为每次允许的执行保存结构化、可追溯、可由人和本地工具读取的 evidence。
4. 向当前网页、未来 Codex 调用和本地脚本提供同一个稳定 `/api/v1` 契约。
5. 明确显示 architecture drift 与 scope drift，不把缺失证据或未知状态渲染为成功。
6. 在不引入第三方 Web 依赖、不进入 production package 的前提下，于 1 个有效工作日内完成可用的 v0.1。

## 3. Non-Goals

v0.1 不提供：

- LAN 或 Internet 访问；
- login、API key 或 OAuth；
- arbitrary shell、用户提供的命令、参数或代码执行；
- WebSocket、Server-Sent Events 或后台推送；
- database；
- backtest UI；
- broker、account、provider、TradingView Webhook 或 order 能力；
- auto-fix、文件编辑、Git commit、push、PR、merge 或 deploy；
- Task 2 或任何 production implementation；
- 对 frozen V2.2A business design 的修订；
- production test logic 的复制或浏览器内重写。

无需身份认证不是允许扩大监听范围的理由。v0.1 的安全边界是 loopback-only、固定命令目录、无任意输入执行和最小写入范围的组合。

## 4. Placement and Dependency Boundary

全部 Console implementation 必须位于：

```text
tools/verification_console/
```

允许的职责布局为：

```text
tools/verification_console/
  __main__.py          # developer entry point and 127.0.0.1 bind
  server.py            # standard-library HTTP routing and JSON responses
  catalog.py           # fixed command/task catalog
  runner.py            # argv-only process execution and result capture
  evidence.py          # evidence persistence and retrieval
  status.py            # truth-state derivation
  drift.py             # architecture/scope drift checks
  static/
    index.html
    app.css
    app.js
```

该布局冻结的是责任边界，不要求实现者机械地创建每个文件；在保持职责清晰和测试隔离的前提下可合并小模块。无论具体文件拆分如何，Console 及其静态资源都不得进入：

```text
src/tv_quant/data_foundation/
```

Console 可以导入 Python 标准库，并读取仓库文档、Git metadata、pytest 输出和 Console 自己的 evidence。它不得成为 `tv_quant` production package 的依赖，`src/tv_quant/**` 不得反向导入 `tools.verification_console`。

v0.1 不得为 Web 服务、routing、templating、frontend、persistence 或 process execution 新增任何第三方 dependency。`requirements.txt`、project dependency metadata 和 lock files 不应因 Console Web 层而改变。

## 5. Network and Process Security Boundary

### 5.1 Bind rule

服务只能 bind：

```text
127.0.0.1
```

启动接口不得接受 host override。`0.0.0.0`、`::`、hostname、LAN address 或用户提供的 bind address 均不允许。端口可以使用 server-owned default；如未来允许端口配置，只能接受已验证的整数端口，且不得改变 host。

### 5.2 Request boundary

Console 只接受本设计列出的 routes、methods 和 JSON fields。未知 route 返回 `404`；已知 route 的错误 method 返回 `405`；错误或多余字段返回 `400`；不支持的 media type 返回 `415`。

POST request body 必须设置合理的固定大小上限。超限返回 `413`，不得继续解析或执行。API response 必须使用 `application/json; charset=utf-8`；静态资源只从 Console 自己冻结的 static root 提供，并阻止 path traversal。

服务必须校验 `Host` 为 loopback authority，并拒绝指向非 loopback host 的请求。Console 不发送 permissive CORS headers；浏览器 POST 只接受 absent `Origin`（本地脚本）或与当前 loopback origin 完全相同的 `Origin`。跨站 origin、`null` origin 和错误 `Content-Type` 不得启动 run。这些检查用于降低本机恶意网页、DNS rebinding 和 cross-origin request 对无认证 localhost runner 的滥用风险。

### 5.3 Execution boundary

runner 只能执行 server-side catalog 中预先声明的 argv arrays：

- 不使用 `shell=True`；
- 不把 request 字符串拼入 command line；
- 不经 `cmd.exe`、PowerShell command string、`bash -c` 或类似 shell interpreter；
- working directory 固定为服务启动时验证过的 repository root；
- child environment 使用最小、明确继承策略，不注入或回显 secrets；
- 同一时间最多运行一个 catalog command；
- 运行中的重复启动请求返回 conflict，不排入无限队列；
- server shutdown 必须终止或明确回收由本进程启动的 child process。

stdout/stderr 属于不可信文本：页面必须按 text 渲染，不得插入为 HTML。evidence summary 必须清理控制字符并应用长度上限；完整输出如保留，也只能位于 Console evidence root，不能任意指定路径。

## 6. User Interface

v0.1 是单页原生 Web UI，包含以下六个可导航页面或视图：

1. **Dashboard**：显示 branch、commit、API health、当前运行、最近验证、完成任务数、失败/待验证数和 drift 摘要。
2. **Task 1–17 Matrix**：逐任务显示 implementation、focused tests、regression、independent review、latest Console verification 和 derived status。
3. **Test Runner**：只显示 `/api/v1/commands` 返回的 command IDs、说明和适用范围；用户只能按 command ID 启动。
4. **Evidence**：列出 runs，支持按 run ID 查看结构化证据和截断后的 stdout/stderr summary。
5. **Architecture Drift**：显示 tooling placement、dependency boundary、production import direction、API/catalog schema 等结构漂移检查。
6. **Scope Drift**：显示相对冻结基线的文件范围、禁止能力关键词/路径、Task 2+ activity 和 production-code changes 等范围漂移检查。

UI 不是真值 owner。它只能渲染 API 返回的状态，不得在 JavaScript 中自行推导 `DONE`、改写失败结果或假设缺失 evidence 为通过。

页面以轮询 `GET` endpoints 更新；v0.1 不使用 WebSocket。轮询失败必须显示 disconnected/stale 状态和最后成功刷新时间，不得继续展示成 current/healthy。

## 7. API Versioning and Compatibility

API base path 固定为：

```text
/api/v1
```

`/api/v1` 同时服务于：

- 当前 Console 网页；
- 未来 Codex 调用；
- 未来本地脚本调用。

v1 compatibility rule：

- 可增加 optional response fields；
- 可增加新的 command IDs 或 task evidence fields，但不得改变既有字段含义；
- 不得删除或重命名既有 fields、routes、status values 或 command IDs；
- 不得把 optional field 改为 required request field；
- 不得改变 `POST /runs` 的 command-ID-only security model；
- breaking change 必须使用 `/api/v2`，并允许 v1 在迁移期继续工作。

所有 timestamps 使用 UTC ISO 8601，格式包含 `Z`。durations 使用非负整数 `duration_ms`。JSON object keys、task order、run order 和 command order 必须确定性输出。

非 2xx API response 使用统一 error envelope：

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "request object must contain only command_id"
  }
}
```

`code` 是稳定的机器可读字符串；`message` 可增加诊断信息，但不得包含 secrets、绝对用户路径、raw environment 或未清理的 child-process output。

## 8. API Endpoints

### 8.1 `GET /api/v1/health`

用途：最小 liveness 与版本检查，不触发 Git、pytest 或 drift scan。

成功响应至少包含：

```json
{
  "status": "ok",
  "api_version": "v1",
  "service": "v2-2a-verification-console",
  "bind_host": "127.0.0.1"
}
```

### 8.2 `GET /api/v1/status`

用途：Dashboard 聚合状态。

响应至少包含：

- `api_version`；
- `branch`；
- `commit_sha`；
- `worktree_clean`；
- `running_run_id` 或 `null`；
- `task_counts`，按冻结 status 枚举计数；
- `latest_verification_at` 或 `null`；
- `architecture_drift` summary；
- `scope_drift` summary；
- `generated_at`。

聚合读取或 Git inspection 失败时必须返回明确 error state；不得沿用旧值冒充 current。

### 8.3 `GET /api/v1/tasks`

返回 Task 1–17 的有序列表。每项至少包含：

- `task_id`，规范形式为字符串 `"1"` 至 `"17"`；
- `title`，来自冻结 implementation plan；
- `implementation`；
- `focused_tests`；
- `regression`；
- `independent_review`；
- `console_verification`；
- `status`；
- `implementation_commit_sha` 或 `null`；
- `latest_run_id` 或 `null`；
- `updated_at` 或 `null`。

### 8.4 `GET /api/v1/tasks/{task_id}`

只接受 canonical task IDs `1`–`17`。响应包含列表字段，并增加各 predicate 的 evidence references、适用 command IDs 和 failure/pending reasons。不存在的 task 返回 `404`。

### 8.5 `GET /api/v1/commands`

返回 server-side catalog 的确定性有序投影。每项只暴露：

- `command_id`；
- `label`；
- `description`；
- `scope`；
- `enabled`；
- `disabled_reason` 或 `null`。

API 不返回可被客户端修改后重放的 raw shell string。为了可审查性，可返回固定 `test_targets` 的只读展示，但该字段从 server catalog 生成，不能成为 POST 输入。

### 8.6 `GET /api/v1/runs`

返回 runs，默认按 `started_at` 降序。v0.1 可以使用 server-owned 固定上限；不得接受 filesystem path 或任意 query-to-command mapping。每项至少包含核心 evidence 字段和 detail URL。

### 8.7 `GET /api/v1/runs/{run_id}`

返回单次执行的完整结构化 evidence。`run_id` 必须先通过固定格式验证，再映射到 evidence root 内部记录；不得直接用作路径。不存在的 run 返回 `404`。

### 8.8 `POST /api/v1/runs`

唯一允许的 request schema：

```json
{
  "command_id": "task1.focused"
}
```

`command_id` 必须是非空字符串并精确匹配启用的 catalog entry。request object 必须恰好只有该字段。客户端不得提交：

- raw command；
- shell args；
- filesystem path；
- pytest node；
- repo path；
- Python code；
- URL。

任何额外字段均返回 `400`，未知或 disabled command ID 返回 `404` 或明确的 `409`，且不得启动 child process。成功接受后返回 `202` 和 server-generated `run_id`。如果已有 command 正在运行，返回 `409`，并包含当前 `run_id`，不创建第二个 run。

## 9. Fixed Command Catalog

catalog 是 server-side source-controlled fixed allow-list。客户端无法新增、覆盖或传参。首批 command IDs 固定为：

| command_id | v0.1 server-owned meaning |
|---|---|
| `task1.focused` | 执行 Task 1 focused nodes：`tests/data_foundation/test_registration.py`、`tests/contracts/test_artifact_contract.py`、`tests/contracts/test_capability_registry.py` |
| `task1.regression` | 执行 Task 1 focused nodes，并加入 `tests/pipeline/test_run_manifest.py` |
| `baseline.v21` | 执行冻结 V2.1 regression groups：contracts、adapters、V2 CLI gate、V2.1 gate/security，以及 pipeline suite；catalog 以 argv stages 固定这些路径 |
| `repo.diff_check` | 执行 `git diff --check`，不修改 index、worktree、branch 或 remote |
| `completed.all` | 按 task ID 顺序执行 catalog 中所有已完成任务的 focused/regression profiles，随后执行 `baseline.v21` 和 `repo.diff_check`；展开过程完全由 server catalog 决定 |

pytest invocation 必须使用当前受支持的 Python 3.14 interpreter 和 `-m pytest ... -q`，以 argv array 表示。一个 command ID 可以拥有多个固定 stages；任一 stage 非零退出立即 STOP，后续 stage 标记 `not_run`，整个 run 为 FAIL。

`completed.all` 不是对 `DONE` UI 状态的盲目信任。只有 catalog 明确登记且 implementation、review evidence 已存在的 completed tasks 才能进入展开集合。若任务缺少 profile 或 prerequisite，aggregate run 必须 fail closed 或明确 disabled，不能静默跳过后宣称全部通过。

未来增加 Task 2–17 command IDs 时，必须通过 source review 更新 catalog，并保持 POST schema 不变。任何允许 request 提供 pytest node、argv、path 或 code 的实现都违反本设计。

## 10. Run Lifecycle and Error Semantics

run lifecycle 固定为：

```text
ACCEPTED -> RUNNING -> PASS | FAIL | ERROR | CANCELLED
```

- `ACCEPTED`：request 已验证并分配 run ID，尚未启动 child process。
- `RUNNING`：至少一个 stage 已开始。
- `PASS`：所有 required stages exit code 为 0，且结果解析没有 infrastructure error。
- `FAIL`：命令正常执行但至少一个 stage 非零退出或 pytest 报告失败/error。
- `ERROR`：runner、interpreter、repository inspection、evidence persistence 或 result parsing 失败，无法形成可信 PASS。
- `CANCELLED`：仅用于 Console shutdown 等明确终止；不得当作 PASS。

HTTP request 超时不改变已经接受的 run；客户端通过 `GET /runs/{run_id}` 读取最终状态。v0.1 不需要 cancellation API。

pytest summary parsing 用于提取 counts，但 PASS/FAIL 最终以 stage exit code 与 infrastructure integrity 共同决定。无法解析 counts 时，counts 可为 `null`，run 必须保留 exit code；解析失败不得把非零 exit code改为 PASS。

## 11. Evidence Model and Persistence

每次 run 至少记录：

- `run_id`；
- `command_id`；
- `branch`；
- `commit_sha`；
- `started_at`；
- `ended_at`；
- `duration_ms`；
- `exit_code`；
- `passed`；
- `failed`；
- `errors`；
- `stdout_summary`；
- `stderr_summary`；
- `result`，值为 `PASS` 或 `FAIL`，infrastructure cases 另有 lifecycle `status`；
- fixed stage results；
- catalog/version identifier；
- repository root identity 的安全、非敏感表示。

branch 与 commit SHA 必须在 run 开始时读取并绑定；run 结束时再次读取。如果执行期间 HEAD 或 branch 改变，run 必须 FAIL/ERROR 并记录 drift，不能成为任何 task 的 latest valid verification。

evidence 采用 Console-owned、append-only JSON records，位于 repository-local ignored runtime directory，例如：

```text
.verification-console/runs/<server-generated-run-id>.json
```

具体 ignored directory 可在实现时选择等价名称，但必须满足：

- 不进入 `src/`；
- 不覆盖旧 run；
- atomic write 后才对 readers 可见；
- run ID 由 server 生成，不含用户路径片段；
- deterministic JSON encoding；
- evidence schema 有显式版本；
- persistence failure 使 run 为 ERROR；
- secrets、完整 environment 和任意绝对用户路径不得写入 evidence。

Console evidence 证明“该 branch/commit 上该 allow-listed command 的一次执行结果”，不替代 Git commit、independent review 或 frozen business evidence。

## 12. Truthful Task Status

顶层 task status 枚举只允许：

```text
DONE
NOT_IMPLEMENTED
NOT_TESTED
FAILED
REVIEW_PENDING
VERIFY_PENDING
```

`DONE` 必须同时满足以下五个 predicates：

```text
implementation exists
+ focused tests PASS
+ regression PASS
+ independent review PASS
+ latest console verification PASS
```

推导优先级冻结为：

1. implementation 不存在：`NOT_IMPLEMENTED`；
2. 当前 implementation commit 的 latest applicable required evidence 显示 focused、regression 或 Console verification 失败：`FAILED`；
3. focused 或 regression 尚无有效 PASS evidence：`NOT_TESTED`；
4. independent review 尚无明确 PASS evidence：`REVIEW_PENDING`；
5. latest Console verification 尚无绑定当前 implementation commit 的 PASS evidence：`VERIFY_PENDING`；
6. 五项全部满足：`DONE`。

“latest Console verification PASS”必须是适用于该 task 的最新终态 run，且绑定当前 branch、当前 implementation commit 和当前 catalog version。旧 commit 的 PASS、被更新实现之后的 PASS、取消的 run、ERROR run 或缺失 evidence 均不能满足该 predicate。

focused tests 与 regression predicates 同样只接受绑定当前 implementation commit 的 latest applicable evidence。旧失败可被同一 commit 上更新且完整的 required PASS evidence 取代；旧 commit 的 PASS 不能跨 commit 继承。

independent review evidence 必须是显式、可定位且绑定 implementation commit 的 review result。Console 不把 commit message、无改动状态或测试 PASS 推断成 independent review PASS。

Task 1–17 初始状态必须从真实 repository/evidence 推导。未来 task 即使在 frozen plan 中存在，也不能因为有标题或计划而显示为 implemented。

## 13. Task 1–17 Matrix Source

任务 ID 和标题以冻结的 V2.2A implementation plan 为只读来源：

1. Register V2.2A versions, dependency, capabilities, and artifact ownership
2. Define immutable data contracts and isolate runtime capability
3. Freeze semantic identity and lineage projections
4. Implement strict CSV and Parquet parser profiles
5. Materialize and validate frozen XNYS calendar snapshots
6. Define daily gaps, evidence coverage, and validation records
7. Validate corporate-action evidence and derive deterministic adjustments
8. Implement fail-closed daily dataset validation
9. Finalize logical component hashes and dataset identity gates
10. Publish deterministic immutable canonical artifacts and manifests
11. Bind manifests, provenance, and eligibility in MarketDataRegistry
12. Enforce idempotent re-import and formal dataset lookup
13. Implement exact-binding atomic invalidation
14. Strengthen the existing Windows path-containment owner
15. Orchestrate the complete local import pipeline
16. Add end-to-end offline fixtures and canonical equivalence acceptance
17. Enforce duplicate-owner, security, V2.1 regression, and final acceptance

Console 可以维护与这些固定 IDs 对应的 verification metadata，但不得修改任务 business acceptance criteria、重排任务依赖或把 Task 2+ 标记为开始。

## 14. Architecture Drift

Architecture Drift 视图和 API status summary 至少检查：

- Console implementation 是否全部位于 `tools/verification_console/`；
- `src/tv_quant/data_foundation/` 是否包含 Console/server/frontend code；
- production modules 是否反向依赖 developer Console；
- 是否新增第三方 Web framework/dependency；
- bind host 是否仍硬编码/约束为 `127.0.0.1`；
- API routes 与 v1 schema 是否仍符合本设计；
- command catalog 是否仍为固定 allow-list；
- runner 是否仍是 argv-only、`shell=False` 等价行为；
- evidence root 是否仍在 developer tooling/runtime boundary；
- Console 是否复制 production algorithm 或测试断言逻辑。

每个 check 返回 `PASS`、`FAIL` 或 `UNKNOWN`，并包含简短 reason。`UNKNOWN` 不得汇总为 PASS。Architecture drift scan 是只读检查，不自动修复。

## 15. Scope Drift

Scope Drift 至少检查当前 branch/commit 相对批准基线和 task evidence 的以下风险：

- 本次 Console 工作是否修改 frozen business design；
- 是否修改 Task 1 production code；
- 是否出现 Task 2+ implementation files/tests/commits；
- 是否出现 broker、account、order、provider download、Webhook、options 或 formal backtest 能力；
- 是否出现 network-facing bind、authentication system、database、WebSocket 或 arbitrary shell；
- 是否出现 push/PR/deploy/auto-fix 行为；
- Console change set 是否超出 developer tooling、Console tests、必要 docs/ignore metadata 的获批范围。

Scope Drift 只报告 evidence-backed findings。字符串命中可以触发 review，但不能单独证明业务能力已实现；UI 必须区分 confirmed drift 与 review-needed signal。

## 16. Existing-Test Reuse

Console 不复制 production 测试逻辑。它只调用仓库已有 pytest files/nodes。具体规则：

- catalog 引用现有 tests；
- Console 自身测试只验证 HTTP/API、catalog security、runner isolation、status derivation、evidence 和 drift tooling；
- Console tests 不重新实现数据合同、hash、calendar、adjustment、registry 或 eligibility assertions；
- production test 发生合法重命名时，catalog 通过 reviewed change 更新；客户端 API 仍只提交稳定 command ID；
- missing test target 必须导致 command FAIL/ERROR，不能自动替换为相似测试。

## 17. Per-Task Verification Workflow

每个未来 Task 的固定流程为：

```text
implementation
-> RED
-> GREEN
-> regression
-> commit
-> independent review
-> Console/API verification
-> progress update
-> next Task
```

任一步失败：

```text
STOP
```

Console/API verification 必须发生在 commit 和 independent review 之后，并绑定被 review 的 exact commit。进度更新不得先于 Console PASS。下一任务不得在当前任务 status 达到真实 `DONE` 之前开始。

## 18. Timebox and Degradation Order

整个 v0.1 implementation timebox 不超过 1 个有效工作日。

若逼近时间盒，先砍 UI 美化、动画、复杂筛选和非必要交互，只保留：

- Dashboard；
- Task Matrix；
- API；
- Test Runner；
- Evidence。

Architecture Drift 与 Scope Drift 的独立精美页面可以降级为 Dashboard 中的文本 summary 或基础表格，但对应只读检查和 fail-closed signals 不能被伪装为已经实现。安全边界、allow-list、证据完整性、状态真实性和 API v1 契约不可因时间盒削弱。

## 19. Verification and Acceptance Criteria

Console v0.1 未来实现只有同时满足以下条件才可验收：

1. 实际监听地址只有 `127.0.0.1`，且不存在 host override。
2. 全部 Console code/static assets 位于 `tools/verification_console/`，production package 无反向依赖。
3. 六个规定视图存在，或在时间盒降级时保留五个核心视图并明确标记 drift view 的降级展示。
4. 八个 `/api/v1` endpoints 符合本设计。
5. `POST /api/v1/runs` 只接受且恰好接受 `command_id`。
6. 未知 command、额外字段、raw command、args、path、pytest node、repo path、Python code 和 URL 均无法触发 execution。
7. 首批五个 command IDs 存在且仅映射 server-side fixed argv stages。
8. runner 不使用 shell command interpolation，同一时间最多一个 run。
9. evidence 至少包含 Section 11 的所有 required fields，并绑定 branch/commit。
10. `DONE` 严格由五 predicate conjunction 推导，其余状态符合固定优先级。
11. Console 调用现有 pytest targets，不复制 production test logic。
12. architecture/scope drift 的 FAIL 或 UNKNOWN 不被显示为 healthy PASS。
13. 0 个新增第三方 Web dependencies。
14. 不提供 Section 3 的任何禁止能力。
15. Console 自身 focused tests、security tests 和 API contract tests PASS；existing V2.1/V2.2A regression 不因 Console 退化。
16. `git diff --check` PASS，且 reviewed change scope 与批准范围一致。

## 20. Design-Time Scope Freeze

本设计任务本身只允许创建：

```text
docs/superpowers/specs/2026-08-09-v2-2a-verification-console-design.md
```

本设计任务不得：

- 创建 `tools/verification_console/` implementation；
- 修改 `src/tv_quant/data_foundation/` 或其他 production code；
- 修改 frozen V2.2A business design；
- 修改 Task 1 tests、requirements 或 capability registry；
- 编写 implementation plan；
- 开始 Task 2；
- push 或创建 Pull Request。

设计提交完成、自审和 diff check 通过后停止，等待用户评审。

## 21. Closed Decisions

本设计没有阻断性开放问题。以下决策已关闭：

- loopback host 固定为 `127.0.0.1`；
- developer tooling root 固定为 `tools/verification_console/`；
- Web stack 固定为 Python 标准库与原生 HTML/CSS/JS；
- API 固定从 `/api/v1` 开始并遵守向后兼容；
- execution 固定为 server allow-list command ID；
- v0.1 无认证，因为它不离开 loopback 且不扩大为任意执行面；
- evidence 使用 repository-local developer runtime storage，不使用 database；
- status 必须 fail closed；
- 超时优先牺牲 UI 美化，不牺牲安全、API、evidence 或真实性。

任何改变上述 closed decision、修改 frozen business design 或扩大 production scope 的需求，都必须经过新的用户批准和版本化设计修订，不能在实现中自行决定。
