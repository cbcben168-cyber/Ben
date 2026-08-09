# V2.2A Visual Verification Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a browser-clickable V2.2A Visual Verification Console v0.1 on `127.0.0.1` within one effective working day, without changing V2.2A production code or starting V2.2A Task 2.

**Architecture:** Use Python 3.14 standard-library `http.server`, `subprocess`, filesystem, threading, and JSON facilities behind a fixed `/api/v1` contract. Serve one native HTML/CSS/JavaScript page from `tools/verification_console/`; keep command selection, execution, evidence, task truth, and drift checks server-owned and fail closed. The browser only polls GET endpoints, submits an exact `command_id`, and renders server responses as text.

**Tech Stack:** Python 3.14, Python standard library only for the Console, native HTML/CSS/JavaScript, pytest 9.1.1 for tests, existing Git CLI for read-only inspection and `git diff --check`.

## Global Constraints

- Frozen design authority: `docs/superpowers/specs/2026-08-09-v2-2a-verification-console-design.md` at design commit `551900bd2a64f8772fc77c0bd4970fb5567c8248`.
- V2.2A Task 1 implementation binding: `c58f59b95e0291685d4f71119f1e765d1b3a596a`.
- Work only on `codex/v2-2a-data-foundation-impl`; each implementation task ends in one independently reviewable commit.
- Do not modify `src/tv_quant/data_foundation/`, any other `src/tv_quant/**` production module, the frozen V2.2A business design, Task 1 production implementation/tests, `requirements.txt`, or capability metadata.
- Do not begin V2.2A Task 2 or add Task 2–17 production files/tests/commits.
- Put every Console module and static asset under `tools/verification_console/`; put Console-only tests under `tests/verification_console/`.
- Add zero third-party Web, routing, templating, persistence, frontend, or process-execution dependencies.
- Start every Console Python module with `from __future__ import annotations`; use `TYPE_CHECKING` imports for cross-owner annotations so runtime imports follow the task dependency order.
- Bind only `127.0.0.1`; expose no host override and no LAN/Internet access.
- Keep API base path `/api/v1`; preserve the frozen eight endpoint forms and deterministic response ordering.
- Accept only exact command-ID POST input. Never accept raw commands, argv, paths, pytest nodes, repository roots, Python code, URLs, or arbitrary query-to-command mappings.
- Execute only server-owned argv tuples with `shell=False`, a validated repository-root `cwd`, minimal child environment, and one concurrent run.
- Give every pytest stage a server-owned, run/stage-specific `--basetemp`; never accept basetemp from a request.
- Persist append-only, deterministic JSON evidence under ignored `.verification-console/runs/`; do not persist secrets, raw environment, or absolute user paths.
- Treat stdout/stderr as untrusted text, strip control characters, truncate summaries, and render with `textContent`, never `innerHTML`.
- Do not add login, authentication, database, WebSocket, SSE, backtest UI, broker/account/provider/order/Webhook/options capability, auto-fix, file editing, commit, push, PR, merge, deploy, or network data access.
- Hard implementation timebox: 7.5 hours, never more than one effective working day. If time is tight, remove polish, animation, filtering, and nonessential interaction; do not weaken API, security, evidence, drift, or truthful status.
- After every RED or GREEN failure, stop that task. Do not start the next task until the current task is committed, independently reviewed, Console-verified, and truthfully `DONE` under the frozen workflow.

---

## 1. Frozen File Map

Repository inspection at `551900bd2a64f8772fc77c0bd4970fb5567c8248` found no existing `tools/` directory, no `tests/verification_console/` directory, and no target plan file. Freeze this implementation layout:

| File | Responsibility | First task |
|---|---|---:|
| `tools/verification_console/__init__.py` | Stable service/API/version constants | 1 |
| `tools/verification_console/__main__.py` | No-argument developer entry point; repository discovery; fixed loopback start | 1 |
| `tools/verification_console/server.py` | Standard-library HTTP server, route/method/media/Host/Origin validation, JSON/static responses | 1 |
| `tools/verification_console/status.py` | Git identity, frozen Task 1–17 definitions, predicate and top-level status derivation | 1 |
| `tools/verification_console/catalog.py` | Fixed command and stage specifications; public allow-list projection | 2 |
| `tools/verification_console/runner.py` | Single-run lifecycle, argv materialization, child isolation, output capture, shutdown cleanup | 2 |
| `tools/verification_console/evidence.py` | Evidence schema, sanitization, deterministic append-only persistence and retrieval | 3 |
| `tools/verification_console/drift.py` | Read-only architecture and scope drift checks | 4 |
| `tools/verification_console/static/index.html` | One-page six-view semantic structure | 1 |
| `tools/verification_console/static/app.css` | Minimal accessible layout; no animation requirement | 1 |
| `tools/verification_console/static/app.js` | GET polling, command-ID POST, stale/disconnected state, text-only rendering | 1 |
| `tests/verification_console/conftest.py` | Ephemeral loopback server and HTTP client fixtures | 1 |
| `tests/verification_console/test_server.py` | Browser skeleton, health/status/static and basic HTTP contract | 1 |
| `tests/verification_console/test_catalog_runner.py` | Catalog, request security, argv isolation, concurrency and shutdown | 2 |
| `tests/verification_console/test_evidence_status.py` | Evidence persistence/API and truthful Task 1–17 state matrix | 3 |
| `tests/verification_console/test_drift_e2e.py` | Drift, full API/security contract, UI/E2E acceptance | 4 |
| `.gitignore` | Ignore only `.verification-console/` runtime evidence/temp data | 3 |

No other file is in scope. In particular, do not create a Console package under `src/`, do not modify dependency metadata, and do not add a separate build system or frontend toolchain.

## 2. Frozen Interface Catalog

These names and signatures are the cross-task contract. Later tasks may fill behavior but must not rename parameters, change return meanings, or create a second owner.

### 2.1 Service and HTTP ownership

```python
# tools/verification_console/__init__.py
API_VERSION: str = "v1"
SERVICE_NAME: str = "v2-2a-verification-console"
BIND_HOST: str = "127.0.0.1"
DEFAULT_PORT: int = 8765
MAX_POST_BODY_BYTES: int = 1024

# tools/verification_console/__main__.py
def discover_repository_root(start: Path) -> Path: ...
def main() -> int: ...

# tools/verification_console/server.py
class VerificationHTTPServer(ThreadingHTTPServer):
    repo_root: Path
    runtime_root: Path
    run_manager: RunManager | None

def build_server(
    repo_root: Path,
    *,
    port: int = DEFAULT_PORT,
    runtime_root: Path | None = None,
) -> VerificationHTTPServer: ...

def serve(
    repo_root: Path,
    *,
    port: int = DEFAULT_PORT,
) -> None: ...

def health_payload() -> dict[str, object]: ...
def error_payload(code: str, message: str) -> dict[str, object]: ...
```

`build_server` accepts `port=0` only for an OS-assigned test port. Neither `main` nor `serve` accepts a host parameter. The server always constructs its address as `(BIND_HOST, port)`.

### 2.2 Catalog and runner ownership

```python
# tools/verification_console/catalog.py
PYTEST_BASETEMP_TOKEN: str = "{SERVER_PYTEST_BASETEMP}"
CATALOG_VERSION: str = "v0.1"

@dataclass(frozen=True)
class StageSpec:
    stage_id: str
    argv: tuple[str, ...]
    task_ids: tuple[str, ...] = ()

@dataclass(frozen=True)
class CommandSpec:
    command_id: str
    label: str
    description: str
    scope: str
    stages: tuple[StageSpec, ...]
    enabled: bool
    disabled_reason: str | None

def command_catalog(python_executable: str) -> tuple[CommandSpec, ...]: ...
def find_command(command_id: str, python_executable: str) -> CommandSpec | None: ...
def public_commands(python_executable: str) -> list[dict[str, object]]: ...

# tools/verification_console/runner.py
@dataclass(frozen=True)
class StartResult:
    run_id: str
    status: str

class RunConflictError(RuntimeError):
    run_id: str

class CommandNotFoundError(LookupError): ...
class CommandDisabledError(RuntimeError): ...

class RunManager:
    def __init__(
        self,
        repo_root: Path,
        runtime_root: Path,
        *,
        evidence_store: EvidenceStore | None = None,
    ) -> None: ...

    def start(self, command_id: str) -> StartResult: ...
    def running_run_id(self) -> str | None: ...
    def get_run(self, run_id: str) -> dict[str, object] | None: ...
    def list_runs(self) -> list[dict[str, object]]: ...
    def wait_for_idle(self, timeout_seconds: float) -> bool: ...
    def shutdown(self) -> None: ...

def materialize_argv(
    stage: StageSpec,
    *,
    pytest_basetemp: Path,
) -> tuple[str, ...]: ...

def minimal_child_environment(repo_root: Path) -> dict[str, str]: ...
```

The only substitution allowed by `materialize_argv` is replacing the one server-owned `PYTEST_BASETEMP_TOKEN` with `<runtime_root>/pytest/<run_id>/<stage_id>`. Request values never reach `StageSpec`, argv, cwd, environment, or filesystem paths.

### 2.3 Evidence and truthful status ownership

```python
# tools/verification_console/evidence.py
EVIDENCE_SCHEMA_VERSION: str = "v1"
RUN_ID_PATTERN: Pattern[str] = re.compile(r"^run-[0-9a-f]{32}$")
SUMMARY_LIMIT: int = 8000

@dataclass(frozen=True)
class StageResult:
    stage_id: str
    status: str
    started_at: str | None
    ended_at: str | None
    duration_ms: int
    exit_code: int | None
    passed: int | None
    failed: int | None
    errors: int | None
    stdout_summary: str
    stderr_summary: str

@dataclass(frozen=True)
class RunRecord:
    schema_version: str
    run_id: str
    command_id: str
    catalog_version: str
    status: str
    result: str
    branch: str
    commit_sha: str
    end_branch: str
    end_commit_sha: str
    repository_drift: bool
    repository_id: str
    task_bindings: dict[str, str]
    review_evidence_refs: dict[str, str]
    started_at: str
    ended_at: str
    duration_ms: int
    exit_code: int | None
    passed: int | None
    failed: int | None
    errors: int | None
    stdout_summary: str
    stderr_summary: str
    stages: tuple[StageResult, ...]

class EvidenceStore:
    def __init__(self, repo_root: Path, runtime_root: Path) -> None: ...
    def persist(self, record: RunRecord) -> Path: ...
    def get(self, run_id: str) -> dict[str, object] | None: ...
    def list(self, *, limit: int = 100) -> list[dict[str, object]]: ...

def new_run_id() -> str: ...
def utc_now_z() -> str: ...
def sanitize_summary(text: str, *, limit: int = SUMMARY_LIMIT) -> str: ...
def parse_pytest_summary(text: str) -> tuple[int | None, int | None, int | None]: ...
def repository_id(repo_root: Path) -> str: ...

# tools/verification_console/status.py
class TaskStatus(StrEnum):
    DONE = "DONE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    NOT_TESTED = "NOT_TESTED"
    FAILED = "FAILED"
    REVIEW_PENDING = "REVIEW_PENDING"
    VERIFY_PENDING = "VERIFY_PENDING"

class PredicateState(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"

@dataclass(frozen=True)
class RepositoryState:
    branch: str
    commit_sha: str
    worktree_clean: bool

@dataclass(frozen=True)
class ReviewEvidence:
    reference: str
    implementation_commit_sha: str
    reviewed_at: str
    result: str

@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    title: str
    implementation_commit_sha: str | None
    implementation_paths: tuple[str, ...]
    focused_command_id: str | None
    regression_command_id: str | None
    review_evidence: ReviewEvidence | None

def task_definitions() -> tuple[TaskDefinition, ...]: ...
def inspect_repository(repo_root: Path) -> RepositoryState: ...
def derive_task_snapshot(
    definition: TaskDefinition,
    repository: RepositoryState,
    records: Sequence[Mapping[str, object]],
) -> dict[str, object]: ...
def build_tasks_payload(
    repo_root: Path,
    records: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]: ...
def build_status_payload(
    repo_root: Path,
    *,
    running_run_id: str | None,
    records: Sequence[Mapping[str, object]],
    architecture_drift: Mapping[str, object],
    scope_drift: Mapping[str, object],
) -> dict[str, object]: ...
```

`task_definitions()` returns IDs `"1"` through `"17"` in numeric order with the exact titles frozen in the V2.2A implementation plan. Task 1 owns commit `c58f59b95e0291685d4f71119f1e765d1b3a596a`, its exact implementation paths, `task1.focused`, and `task1.regression`. Tasks 2–17 have `implementation_commit_sha=None`, empty implementation paths, and no commands. Task 1 starts with `review_evidence=None` because the current repository contains no explicit independent-review PASS bound to `c58f59b...`; the Console must not infer review from commit messages or passing tests.

Freeze the title source and current Task 1 binding as these source-controlled literals:

```python
TASK_TITLES = (
    ("1", "Register V2.2A versions, dependency, capabilities, and artifact ownership"),
    ("2", "Define immutable data contracts and isolate runtime capability"),
    ("3", "Freeze semantic identity and lineage projections"),
    ("4", "Implement strict CSV and Parquet parser profiles"),
    ("5", "Materialize and validate frozen XNYS calendar snapshots"),
    ("6", "Define daily gaps, evidence coverage, and validation records"),
    ("7", "Validate corporate-action evidence and derive deterministic adjustments"),
    ("8", "Implement fail-closed daily dataset validation"),
    ("9", "Finalize logical component hashes and dataset identity gates"),
    ("10", "Publish deterministic immutable canonical artifacts and manifests"),
    ("11", "Bind manifests, provenance, and eligibility in MarketDataRegistry"),
    ("12", "Enforce idempotent re-import and formal dataset lookup"),
    ("13", "Implement exact-binding atomic invalidation"),
    ("14", "Strengthen the existing Windows path-containment owner"),
    ("15", "Orchestrate the complete local import pipeline"),
    ("16", "Add end-to-end offline fixtures and canonical equivalence acceptance"),
    ("17", "Enforce duplicate-owner, security, V2.1 regression, and final acceptance"),
)

TASK_1_IMPLEMENTATION_PATHS = (
    "requirements.txt",
    "config/capability-registry-v2.1.json",
    "src/tv_quant/contracts/artifact_contract.py",
    "src/tv_quant/data_foundation/__init__.py",
    "src/tv_quant/data_foundation/contracts.py",
    "src/tv_quant/research_pipeline.py",
    "src/tv_quant/run_manifest.py",
    "tests/contracts/test_artifact_contract.py",
    "tests/contracts/test_capability_registry.py",
    "tests/data_foundation/test_registration.py",
)
```

### 2.4 Drift ownership

```python
# tools/verification_console/drift.py
class DriftState(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class DriftCheck:
    check_id: str
    state: DriftState
    reason: str
    signal_kind: str

def architecture_drift_report(
    repo_root: Path,
    runtime_root: Path,
) -> dict[str, object]: ...

def scope_drift_report(
    repo_root: Path,
    *,
    baseline_sha: str = "551900bd2a64f8772fc77c0bd4970fb5567c8248",
) -> dict[str, object]: ...

def summarize_drift(checks: Sequence[DriftCheck]) -> dict[str, object]: ...
```

`summarize_drift` returns `FAIL` if any check fails, otherwise `UNKNOWN` if any check is unknown, otherwise `PASS`. It never aggregates `UNKNOWN` as healthy.

## 3. Frozen API and Error Contract

The final server supports exactly these endpoint forms:

| Method | Route | Success |
|---|---|---|
| GET | `/api/v1/health` | `200` health payload; no Git, pytest, evidence, or drift access |
| GET | `/api/v1/status` | `200` branch/commit/worktree/run/task counts/drift/generated-at payload or explicit error state |
| GET | `/api/v1/tasks` | `200` ordered Task 1–17 summaries |
| GET | `/api/v1/tasks/{task_id}` | `200` canonical task detail; noncanonical/missing ID `404` |
| GET | `/api/v1/commands` | `200` ordered public catalog projection without argv |
| GET | `/api/v1/runs` | `200` newest-first, server-limited run summaries |
| GET | `/api/v1/runs/{run_id}` | `200` validated run detail; malformed/missing ID `404` |
| POST | `/api/v1/runs` | `202` only for exact `{"command_id":"<enabled-id>"}`; conflict `409` |

All non-2xx API responses use only:

```json
{"error":{"code":"INVALID_REQUEST","message":"request object must contain only command_id"}}
```

Stable error codes are `NOT_FOUND`, `METHOD_NOT_ALLOWED`, `INVALID_REQUEST`, `UNSUPPORTED_MEDIA_TYPE`, `REQUEST_TOO_LARGE`, `INVALID_HOST`, `ORIGIN_FORBIDDEN`, `COMMAND_NOT_FOUND`, `COMMAND_DISABLED`, `RUN_CONFLICT`, `RUN_NOT_FOUND`, and `INTERNAL_ERROR`. Messages are sanitized and contain no absolute path, environment dump, secret, or child output.

V1 compatibility is append-only: optional response fields and reviewed command IDs may be added, but existing routes, fields, meanings, status values, and command IDs may not be removed or renamed; an optional request field may not become required; and the POST body remains command-ID-only. Any breaking contract requires `/api/v2` while v1 remains available during migration.

Every API response uses `application/json; charset=utf-8`, sorted JSON keys, and UTC timestamps ending in `Z`. Static content types are fixed by suffix and only files resolved beneath `tools/verification_console/static/` are readable. The server emits no `Access-Control-Allow-Origin` header.

---

### Task 1: Minimal Browser + API Skeleton

**Timebox:** 1.5 hours. The last step must leave a real Dashboard visible in the user's browser.

**Files:**
- Create: `tools/verification_console/__init__.py`
- Create: `tools/verification_console/__main__.py`
- Create: `tools/verification_console/server.py`
- Create: `tools/verification_console/status.py`
- Create: `tools/verification_console/static/index.html`
- Create: `tools/verification_console/static/app.css`
- Create: `tools/verification_console/static/app.js`
- Create: `tests/verification_console/conftest.py`
- Create: `tests/verification_console/test_server.py`

**Interfaces:**
- Produces: Section 2.1, `RepositoryState`, `inspect_repository`, ordered frozen Task definitions, and `build_status_payload` with fail-closed drift summaries.
- Leaves unchanged: all production modules, dependencies, frozen business design, Task 1 tests and Task 2+ paths.

**Focused test cases:**

| Test node | Exact assertion |
|---|---|
| `test_health_is_minimal_and_does_not_inspect_repository` | exact health core fields; patched Git/drift functions are never called |
| `test_status_reports_branch_commit_worktree_counts_and_unknown_drift` | current Git identity; Task 1 `NOT_TESTED`, Tasks 2–17 `NOT_IMPLEMENTED`; both drift summaries `UNKNOWN` |
| `test_dashboard_and_static_assets_are_browser_visible` | `/`, `/app.css`, `/app.js` return 200 and HTML contains Dashboard branch/commit/health hooks |
| `test_server_binds_only_ipv4_loopback` | `server.server_address[0] == "127.0.0.1"`; `build_server` has no host parameter |
| `test_non_loopback_host_and_static_traversal_fail_closed` | foreign Host returns `400 INVALID_HOST`; encoded traversal returns `404` |
| `test_unknown_api_route_and_wrong_method_use_v1_error_envelope` | unknown route `404`; POST to health `405`; JSON content type exact |

- [ ] **Step 1: Write the RED server/browser tests**

Create a real ephemeral loopback fixture with `ThreadingHTTPServer`, `threading.Thread`, and `http.client.HTTPConnection`. Do not use FastAPI, Starlette, HTTPX, Requests, Selenium, or Playwright.

```python
def test_server_binds_only_ipv4_loopback(repo_root: Path, tmp_path: Path) -> None:
    signature = inspect.signature(build_server)
    assert "host" not in signature.parameters
    server = build_server(repo_root, port=0, runtime_root=tmp_path)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()

def test_health_is_minimal_and_does_not_inspect_repository(
    running_console: RunningConsole,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_call(*args: object, **kwargs: object) -> object:
        raise AssertionError("health must not inspect repository or drift")

    monkeypatch.setattr(status_module, "inspect_repository", forbidden_call)
    response, payload = running_console.json_request("GET", "/api/v1/health")
    assert response.status == 200
    assert payload == {
        "api_version": "v1",
        "bind_host": "127.0.0.1",
        "service": "v2-2a-verification-console",
        "status": "ok",
    }

def test_dashboard_and_static_assets_are_browser_visible(
    running_console: RunningConsole,
) -> None:
    html = running_console.text_request("GET", "/")
    css = running_console.text_request("GET", "/app.css")
    javascript = running_console.text_request("GET", "/app.js")
    assert html.status == css.status == javascript.status == 200
    assert 'id="dashboard-view"' in html.body
    assert 'id="branch-value"' in html.body
    assert 'id="commit-value"' in html.body
    assert "fetchStatus" in javascript.body
```

- [ ] **Step 2: Run RED and record the expected failure**

Run:

```powershell
py -3.14 -m pytest tests/verification_console/test_server.py -q --basetemp "$env:TEMP\tvqc-task1-red"
```

Expected: collection fails with `ModuleNotFoundError: No module named 'tools'` or `No module named 'tools.verification_console'`. Any pass means the test is not exercising the new boundary; stop and correct the test.

- [ ] **Step 3: Implement the minimal loopback server and truthful bootstrap status**

Implement the Section 2.1 signatures with `ThreadingHTTPServer` and a private `BaseHTTPRequestHandler` subclass. `main()` accepts no CLI arguments, discovers the first parent containing `.git`, and calls `serve(repo_root)`; `serve` prints only `http://127.0.0.1:8765/` and calls `serve_forever()`.

`GET /api/v1/status` uses argv-only, `shell=False` Git inspection for `branch`, `commit_sha`, and porcelain cleanliness. At this task boundary it returns all six task-count keys: Task 1 is `NOT_TESTED` only when `c58f59b...` is an ancestor and every Task 1 path exists; Tasks 2–17 are `NOT_IMPLEMENTED`. Architecture and scope summaries are exact fail-closed values:

```json
{"checks":[],"reason":"drift evidence is unavailable","state":"UNKNOWN"}
```

The browser polls health/status every five seconds, sets `data-connection-state` to `current`, `stale`, or `disconnected`, and records the last successful refresh in UTC. Use `textContent` for every API-derived value. Task 1 HTML contains only the Dashboard view and a compact notice that the runner, matrix, evidence, and detailed drift views are unavailable in this commit; it does not render fake PASS values.

- [ ] **Step 4: Run GREEN and focused refactor verification**

Run:

```powershell
py -3.14 -m pytest tests/verification_console/test_server.py -q --basetemp "$env:TEMP\tvqc-task1-green"
```

Expected: all six Task 1 tests pass. Refactor only duplicated JSON/error/static response code into private helpers, rerun with `tvqc-task1-refactor`, and expect the same pass count.

- [ ] **Step 5: Perform the first real browser-visible acceptance**

Run from repository root in a terminal:

```powershell
$env:PYTHONPATH = (Get-Location).Path
py -3.14 -m tools.verification_console
```

Open `http://127.0.0.1:8765/` in the user's browser. Verify the Dashboard visibly shows API health `ok`, the actual branch and commit, current/stale state, task counts, and explicit `UNKNOWN` drift summaries. Stop the server with Ctrl+C and verify clean shutdown. Do not defer this first visual check to a later task.

- [ ] **Step 6: Commit Task 1 only**

```powershell
git add tools/verification_console/__init__.py tools/verification_console/__main__.py tools/verification_console/server.py tools/verification_console/status.py tools/verification_console/static/index.html tools/verification_console/static/app.css tools/verification_console/static/app.js tests/verification_console/conftest.py tests/verification_console/test_server.py
git commit -m "Build browser-visible verification console skeleton."
```

Expected: one reviewer-sized commit; no production/dependency/design file appears in `git show --stat HEAD`.

---

### Task 2: Fixed Catalog + Secure Test Runner

**Timebox:** 2.25 hours.

**Files:**
- Create: `tools/verification_console/catalog.py`
- Create: `tools/verification_console/runner.py`
- Modify: `tools/verification_console/server.py`
- Modify: `tools/verification_console/static/index.html`
- Modify: `tools/verification_console/static/app.css`
- Modify: `tools/verification_console/static/app.js`
- Create: `tests/verification_console/test_catalog_runner.py`

**Interfaces:**
- Consumes: `build_server`, fixed loopback/HTTP constants, repository root, frozen Task 1 test paths.
- Produces: Section 2.2, `GET /api/v1/commands`, `POST /api/v1/runs`, in-memory lifecycle visibility, and the browser Test Runner view.
- Does not produce: durable evidence or Task Matrix; those have one owner in Task 3.

**Fixed catalog:**

```python
task1_focused = (
    sys.executable, "-m", "pytest",
    "tests/data_foundation/test_registration.py",
    "tests/contracts/test_artifact_contract.py",
    "tests/contracts/test_capability_registry.py",
    "-q", "--basetemp", PYTEST_BASETEMP_TOKEN,
)
task1_regression = (
    sys.executable, "-m", "pytest",
    "tests/data_foundation/test_registration.py",
    "tests/contracts/test_artifact_contract.py",
    "tests/contracts/test_capability_registry.py",
    "tests/pipeline/test_run_manifest.py",
    "-q", "--basetemp", PYTEST_BASETEMP_TOKEN,
)
baseline_v21_stage_1 = (
    sys.executable, "-m", "pytest",
    "tests/contracts", "tests/adapters",
    "tests/pipeline/test_v2_cli_gate.py",
    "tests/integration/test_v2_1_gate.py",
    "tests/integration/test_v2_1_security.py",
    "-q", "--basetemp", PYTEST_BASETEMP_TOKEN,
)
baseline_v21_stage_2 = (
    sys.executable, "-m", "pytest", "tests/pipeline", "-q",
    "--basetemp", PYTEST_BASETEMP_TOKEN,
)
repo_diff_check = ("git", "diff", "--check")
```

The catalog order is exactly `task1.focused`, `task1.regression`, `baseline.v21`, `repo.diff_check`, `completed.all`. `completed.all` exists but is explicitly disabled with reason `no task has explicit independent-review PASS evidence`; this is required because the current repository has no review evidence bound to Task 1. It must not silently skip Task 1 and claim aggregate success.

**Focused test cases:**

| Test node | Exact assertion |
|---|---|
| `test_catalog_has_exact_order_ids_and_server_owned_targets` | exact five IDs/order/targets; no shell string or request field |
| `test_public_catalog_never_exposes_argv_or_executable` | public keys only; `completed.all` disabled with exact reason |
| `test_post_runs_accepts_only_exact_command_id_object` | exact body gets `202` and server-generated run ID |
| `test_post_runs_rejects_every_execution_shaping_field_without_popen` | parameterize command/args/path/pytest_node/repo_path/python_code/url; `400`; Popen untouched |
| `test_post_runs_enforces_media_size_host_and_origin_boundaries` | `415`, `413`, `400 INVALID_HOST`, `403 ORIGIN_FORBIDDEN`; no CORS |
| `test_unknown_and_disabled_commands_never_start_process` | unknown `404`; disabled `409`; Popen untouched |
| `test_runner_uses_argv_shell_false_fixed_cwd_and_minimal_environment` | exact argv, `shell=False`, repo cwd, only allowed environment keys |
| `test_each_pytest_stage_receives_unique_server_owned_basetemp` | paths are runtime/run/stage descendants and no request string occurs |
| `test_second_concurrent_run_returns_existing_run_id` | one Popen only; second request `409` with current run ID |
| `test_nonzero_stage_stops_remaining_stages` | first failing stage yields FAIL; remaining stages `not_run` |
| `test_shutdown_terminates_owned_child_and_marks_cancelled` | terminate/kill/wait cleanup; CANCELLED is not PASS |

- [ ] **Step 1: Write RED catalog, request-security, and runner-isolation tests**

Use `unittest.mock` around `subprocess.Popen`; assert the exact call rather than running production tests inside focused runner unit tests.

```python
@pytest.mark.parametrize(
    "forbidden_field, value",
    [
        ("command", "pytest -q"),
        ("args", ["-k", "anything"]),
        ("path", "C:/Windows/System32"),
        ("pytest_node", "tests/test_anything.py"),
        ("repo_path", "C:/other"),
        ("python_code", "print(1)"),
        ("url", "https://example.invalid"),
    ],
)
def test_post_runs_rejects_every_execution_shaping_field_without_popen(
    running_console: RunningConsole,
    popen_spy: Mock,
    forbidden_field: str,
    value: object,
) -> None:
    response, payload = running_console.json_request(
        "POST",
        "/api/v1/runs",
        body={"command_id": "task1.focused", forbidden_field: value},
    )
    assert response.status == 400
    assert payload["error"]["code"] == "INVALID_REQUEST"
    popen_spy.assert_not_called()

def test_runner_uses_argv_shell_false_fixed_cwd_and_minimal_environment(
    run_manager: RunManager,
    repo_root: Path,
    popen_spy: Mock,
) -> None:
    result = run_manager.start("task1.focused")
    assert run_manager.wait_for_idle(2.0)
    argv = popen_spy.call_args.args[0]
    kwargs = popen_spy.call_args.kwargs
    assert argv[:3] == [sys.executable, "-m", "pytest"]
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == repo_root
    assert set(kwargs["env"]) <= {
        "COMSPEC", "PATH", "PATHEXT", "PYTHONPATH", "PYTHONUTF8",
        "SYSTEMROOT", "TEMP", "TMP", "WINDIR",
    }
    assert result.run_id.startswith("run-")
```

- [ ] **Step 2: Run RED and record the expected failure**

```powershell
py -3.14 -m pytest tests/verification_console/test_catalog_runner.py -q --basetemp "$env:TEMP\tvqc-task2-red"
```

Expected: collection fails because `tools.verification_console.catalog` and `runner` do not exist. Do not weaken assertions or add a generic command input.

- [ ] **Step 3: Implement the fixed allow-list and single-run manager**

Build the five immutable `CommandSpec` values from the exact tuples above. Validate at catalog construction that IDs are unique, order is stable, every pytest stage contains exactly one basetemp token, no stage contains `cmd.exe`, PowerShell, `bash`, `-c`, a shell metacharacter, or a non-repository test target, and the only Git tuple is `("git", "diff", "--check")`.

`RunManager.start` validates the catalog entry before allocating `run-<uuid4 hex>`, holds one lock-protected active run, returns conflict instead of queueing, and starts one owned worker thread. Use `Popen(list(argv), cwd=repo_root, env=minimal_child_environment(repo_root), shell=False, stdin=DEVNULL, stdout=PIPE, stderr=PIPE, text=True, encoding="utf-8", errors="replace")`. A nonzero stage stops immediately and records all later stages as `not_run`. `shutdown` terminates, waits briefly, kills only if required, joins the worker, and never maps cancellation to PASS.

`minimal_child_environment` copies only the frozen Windows process keys if present, then sets server-owned `PYTHONPATH=<repo_root>/src` and `PYTHONUTF8=1`. Never inherit `.env` values or persist the environment.

- [ ] **Step 4: Add strict POST routing and the minimal Test Runner view**

Validate Host on every request. For POST, require `Content-Length <= 1024`, JSON media type with absent/UTF-8 charset, exact same loopback Origin or absent Origin, a JSON object with exactly one key `command_id`, and a nonempty string matching an enabled catalog ID. Reject before calling `RunManager.start`.

Add `GET /api/v1/commands`; return only `command_id`, `label`, `description`, `scope`, `enabled`, `disabled_reason`, and fixed `test_targets`. Add a Test Runner section that creates buttons only from the response. The click handler sends `JSON.stringify({command_id: button.dataset.commandId})` and renders the returned run ID with `textContent`.

- [ ] **Step 5: Run GREEN, refactor, and verify browser behavior**

```powershell
py -3.14 -m pytest tests/verification_console/test_server.py tests/verification_console/test_catalog_runner.py -q --basetemp "$env:TEMP\tvqc-task2-green"
```

Expected: Task 1 and Task 2 focused tests pass. Refactor only duplicate request/error validation and catalog projection; rerun with `tvqc-task2-refactor` and expect identical results.

Start the Console, refresh the browser, verify five ordered command cards appear, `completed.all` is visibly disabled with its reason, and clicking `repo.diff_check` returns an accepted run ID. Do not add a text command box or path input.

- [ ] **Step 6: Commit Task 2 only**

```powershell
git add tools/verification_console/catalog.py tools/verification_console/runner.py tools/verification_console/server.py tools/verification_console/static/index.html tools/verification_console/static/app.css tools/verification_console/static/app.js tests/verification_console/test_catalog_runner.py
git commit -m "Add fixed secure verification command runner."
```

---

### Task 3: Evidence + Task Matrix + Truthful Status

**Timebox:** 2.0 hours.

**Files:**
- Create: `tools/verification_console/evidence.py`
- Modify: `tools/verification_console/runner.py`
- Modify: `tools/verification_console/server.py`
- Modify: `tools/verification_console/status.py`
- Modify: `tools/verification_console/static/index.html`
- Modify: `tools/verification_console/static/app.css`
- Modify: `tools/verification_console/static/app.js`
- Create: `tests/verification_console/test_evidence_status.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: frozen catalog/lifecycle, current branch/HEAD, Task 1 implementation binding, explicit review metadata.
- Produces: Section 2.3, `GET /api/v1/runs`, `GET /api/v1/runs/{run_id}`, `GET /api/v1/tasks`, `GET /api/v1/tasks/{task_id}`, durable Evidence and Task Matrix views, and complete Dashboard counts.

**Evidence rules:**

- Generate only `run-<32 lowercase hex>` IDs and validate the regex before any path mapping.
- Keep live ACCEPTED/RUNNING state in `RunManager`; persist one terminal JSON record after PASS, FAIL, ERROR, or CANCELLED.
- Write UTF-8 JSON with `sort_keys=True`, `ensure_ascii=False`, `separators=(",", ":")`, and one trailing newline.
- Write a same-directory exclusive temp file, flush and `os.fsync`, atomically link/rename it to a previously nonexistent final run path, then remove the temp. Any collision or persistence failure makes the run `ERROR`; never overwrite an older run.
- Store only the first/last sanitized summary within 8000 characters; strip C0/C1 control characters except newline/tab. Do not retain full output in v0.1.
- Bind start and end branch/commit. A changed branch or HEAD sets `repository_drift=true`, terminal `status="ERROR"`, `result="FAIL"`, and disqualifies the record from task predicates.
- Store `repository_id` as the first 16 hex characters of SHA-256 over the normalized repository-root identity; never store the raw absolute root.
- Capture `task_bindings` and explicit `review_evidence_refs` at run start. No later review can retroactively convert an earlier run into Console verification.

**Task status algorithm:**

1. Missing implementation commit/path evidence → `NOT_IMPLEMENTED`.
2. Latest applicable focused, regression, or post-review Console verification terminal evidence is FAIL → `FAILED`.
3. Missing applicable focused or regression PASS → `NOT_TESTED`.
4. Missing explicit PASS review bound to the implementation commit → `REVIEW_PENDING`.
5. Missing latest post-review Console PASS bound to current branch, implementation commit, and catalog version → `VERIFY_PENDING`.
6. All five predicates PASS → `DONE`.

For Task 1, `task1.focused` supplies focused evidence; `task1.regression` supplies regression evidence. A PASS `task1.regression` also supplies Console verification only if the run captured an explicit PASS review reference before it started. Tasks 2–17 remain `NOT_IMPLEMENTED`. Current repository truth therefore cannot exceed `REVIEW_PENDING` for Task 1 until a separate reviewed source change records explicit review evidence.

**Focused test cases:**

| Test node | Exact assertion |
|---|---|
| `test_terminal_record_has_every_frozen_field_and_utc_types` | all Section 11 fields, Z timestamps, nonnegative duration, deterministic stage order |
| `test_persist_is_atomic_append_only_and_refuses_overwrite` | second same-ID write fails; first bytes unchanged; no temp visible |
| `test_evidence_never_contains_absolute_repo_path_environment_or_controls` | serialized text omits root/env/secrets/control bytes |
| `test_run_id_is_validated_before_evidence_path_resolution` | traversal, slash, uppercase, oversized ID all return no record/404 |
| `test_runs_are_newest_first_and_server_limited` | descending `started_at`, deterministic tie-breaker, max 100 |
| `test_head_or_branch_change_during_run_becomes_error` | drift true, result FAIL, no predicate credit |
| `test_tasks_are_exactly_1_through_17_with_frozen_titles` | exact IDs/order/titles; only Task 1 implementation binding populated |
| `test_status_priority_not_implemented_before_all_other_states` | missing implementation wins |
| `test_latest_applicable_failure_overrides_older_pass` | same binding/catalog newest FAIL → FAILED |
| `test_old_commit_or_catalog_pass_is_not_applicable` | stale PASS → NOT_TESTED/VERIFY_PENDING |
| `test_passing_tests_without_explicit_review_is_review_pending` | Task 1 focused/regression PASS + no review → REVIEW_PENDING |
| `test_review_without_post_review_console_run_is_verify_pending` | explicit review + only pre-review run → VERIFY_PENDING |
| `test_all_five_current_predicates_are_required_for_done` | only full conjunction → DONE |
| `test_tasks_and_runs_api_return_detail_and_safe_404` | lists/detail fields, canonical IDs, no path mapping |

- [ ] **Step 1: Write RED evidence, API, and status-priority tests**

```python
def test_passing_tests_without_explicit_review_is_review_pending(
    task1_definition: TaskDefinition,
    repository_state: RepositoryState,
    task1_pass_records: list[dict[str, object]],
) -> None:
    snapshot = derive_task_snapshot(
        task1_definition,
        repository_state,
        task1_pass_records,
    )
    assert snapshot["focused_tests"]["state"] == "PASS"
    assert snapshot["regression"]["state"] == "PASS"
    assert snapshot["independent_review"]["state"] == "PENDING"
    assert snapshot["console_verification"]["state"] == "PENDING"
    assert snapshot["status"] == "REVIEW_PENDING"

def test_persist_is_atomic_append_only_and_refuses_overwrite(
    evidence_store: EvidenceStore,
    passing_record: RunRecord,
) -> None:
    path = evidence_store.persist(passing_record)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        evidence_store.persist(passing_record)
    assert path.read_bytes() == original
    assert not list(path.parent.glob("*.tmp"))

def test_run_id_is_validated_before_evidence_path_resolution(
    running_console: RunningConsole,
) -> None:
    for invalid in ("../x", "%2e%2e%2fx", "run-ABC", "run-" + "a" * 64):
        response, payload = running_console.json_request(
            "GET", f"/api/v1/runs/{invalid}"
        )
        assert response.status == 404
        assert payload["error"]["code"] == "RUN_NOT_FOUND"
```

- [ ] **Step 2: Run RED and record the expected failure**

```powershell
py -3.14 -m pytest tests/verification_console/test_evidence_status.py -q --basetemp "$env:TEMP\tvqc-task3-red"
```

Expected: collection fails because `tools.verification_console.evidence` does not exist and the four GET task/run endpoints are absent.

- [ ] **Step 3: Implement terminal evidence persistence and runner integration**

Implement Section 2.3 exactly. Parse pytest counts only for display; stage exit code plus infrastructure integrity owns PASS/FAIL. If counts cannot be parsed, preserve `None`; never change a nonzero exit to PASS. Persist ERROR on interpreter, Git inspection, result parsing integrity, or storage failure. Include every later stage as `not_run` after a failure.

Add exactly `.verification-console/` to `.gitignore`. Do not ignore all JSON, all tools, tests, or evidence-like names.

- [ ] **Step 4: Implement Task 1–17 truth derivation and four GET endpoints**

Freeze all 17 titles from `docs/superpowers/plans/2026-08-02-v2-2a-data-foundation-implementation-plan.md`. Represent each predicate as `{state, reason, evidence_ref}`. Task list items contain `task_id`, `title`, five predicates, `status`, `implementation_commit_sha`, `latest_run_id`, and `updated_at`; detail adds `applicable_command_ids`, `evidence_refs`, `failure_reasons`, and `pending_reasons`.

`GET /api/v1/runs` merges any live in-memory run with final records and sorts by `started_at` descending then `run_id` ascending, maximum 100. Detail lookup validates the ID before calling `EvidenceStore.get`.

- [ ] **Step 5: Add Task Matrix and Evidence views without client-side truth derivation**

Add the Task Matrix and Evidence sections to the same page. JavaScript renders predicate/status strings returned by the API and does not contain the `DONE` conjunction. Run detail stdout/stderr uses `.textContent`. Poll failures mark the entire page stale/disconnected and retain the last-success timestamp without labeling cached data current.

- [ ] **Step 6: Run GREEN and focused refactor verification**

```powershell
py -3.14 -m pytest tests/verification_console/test_server.py tests/verification_console/test_catalog_runner.py tests/verification_console/test_evidence_status.py -q --basetemp "$env:TEMP\tvqc-task3-green"
```

Expected: all Console tests through Task 3 pass. Refactor only deterministic JSON/sanitization and shared task-evidence selection into their single owners; rerun with `tvqc-task3-refactor` and expect identical results.

Start the server, click `task1.focused` and `task1.regression`, wait for terminal results, then verify Evidence lists both records and Task 1 shows `REVIEW_PENDING`, not `DONE`, because explicit review evidence is absent.

- [ ] **Step 7: Commit Task 3 only**

```powershell
git add .gitignore tools/verification_console/evidence.py tools/verification_console/runner.py tools/verification_console/server.py tools/verification_console/status.py tools/verification_console/static/index.html tools/verification_console/static/app.css tools/verification_console/static/app.js tests/verification_console/test_evidence_status.py
git commit -m "Persist verification evidence and derive task status."
```

---

### Task 4: Drift + Security + End-to-End Acceptance

**Timebox:** 1.75 hours. If time is tight, keep drift as basic tables in the existing page and remove only styling/filtering.

**Files:**
- Create: `tools/verification_console/drift.py`
- Modify: `tools/verification_console/server.py`
- Modify: `tools/verification_console/status.py`
- Modify: `tools/verification_console/static/index.html`
- Modify: `tools/verification_console/static/app.css`
- Modify: `tools/verification_console/static/app.js`
- Create: `tests/verification_console/test_drift_e2e.py`

**Interfaces:**
- Consumes: Section 2.4 baseline, server/catalog/runner/evidence/status interfaces, and the exact frozen API table.
- Produces: architecture and scope drift details inside `GET /api/v1/status`, six navigable single-page views, full API/security tests, browser/API Task 1 verification, and final acceptance evidence.

**Architecture checks:**

| `check_id` | PASS evidence | FAIL/UNKNOWN behavior |
|---|---|---|
| `console_placement` | all Console Python/static paths under `tools/verification_console/` | outside path FAIL; unreadable tree UNKNOWN |
| `production_console_absence` | no Console/server/frontend file under `src/tv_quant/data_foundation/` | match FAIL |
| `production_reverse_import` | AST imports under `src/tv_quant/**` do not reference `tools.verification_console` | import FAIL; parse error UNKNOWN |
| `web_dependency_boundary` | dependency metadata unchanged from design baseline | relevant diff FAIL; Git failure UNKNOWN |
| `loopback_bind` | `BIND_HOST == "127.0.0.1"`; server signatures expose no host | mismatch FAIL |
| `api_v1_schema` | route/method table and error envelope equal Section 3 | mismatch FAIL |
| `fixed_catalog` | exact five IDs, immutable stages, no exposed argv/request shaping | mismatch FAIL |
| `argv_only_runner` | AST/runtime test confirms list argv and `shell=False`; no shell interpreter | violation FAIL; uninspectable call UNKNOWN |
| `evidence_boundary` | runtime root resolves below repo `.verification-console`, outside `src` | escape FAIL |
| `no_production_logic_copy` | Console imports no data-foundation algorithms and defines none of their owners | match is review-needed FAIL; parse error UNKNOWN |

**Scope checks relative to `551900bd...`:**

- Frozen business design unchanged.
- Task 1 production paths/tests unchanged.
- No Task 2+ production implementation/test path.
- Change set is limited to this plan, `tools/verification_console/**`, `tests/verification_console/**`, and exact `.gitignore` runtime entry.
- Catalog/process calls include no provider download, broker/account/order/Webhook/options/formal-backtest, push/PR/deploy/auto-fix, arbitrary shell, auth/database/WebSocket, or network-facing bind capability.
- Literal keyword hits in test assertions or the drift scanner itself are `review_needed` signals until AST/path context confirms them; they are never reported as confirmed business capability by string match alone.

**Focused test cases:**

| Test node | Exact assertion |
|---|---|
| `test_architecture_report_contains_exact_checks_and_unknown_is_not_pass` | exact ten IDs/order; summary precedence FAIL > UNKNOWN > PASS |
| `test_scope_report_accepts_only_approved_console_change_paths` | current planned paths PASS; injected production/design/Task2 path FAIL |
| `test_production_reverse_import_and_shell_true_are_detected` | fixture AST violations produce FAIL |
| `test_keyword_signal_is_review_needed_not_confirmed_capability` | text-only token is classified separately |
| `test_all_eight_api_endpoint_forms_and_methods_match_frozen_contract` | success/missing/wrong-method matrix exact |
| `test_all_non_2xx_responses_use_sanitized_error_envelope` | stable code/message only; no path/env/output |
| `test_json_keys_task_command_and_run_order_are_deterministic` | byte-stable repeated responses excluding generated timestamp |
| `test_browser_uses_text_content_polling_and_has_six_views` | six section IDs; no innerHTML/WebSocket/EventSource |
| `test_origin_host_body_media_and_path_traversal_security_matrix` | all frozen HTTP boundary statuses; Popen untouched |
| `test_console_package_has_no_third_party_imports` | AST imports resolve only stdlib/local package |
| `test_task1_api_run_records_branch_commit_basetemp_and_terminal_result` | controlled subprocess integration record contains exact bindings |
| `test_server_shutdown_reaps_worker_and_leaves_no_running_state` | child cleanup and CANCELLED/terminal evidence |

- [ ] **Step 1: Write RED drift and complete acceptance tests**

```python
def test_architecture_report_contains_exact_checks_and_unknown_is_not_pass(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    report = architecture_drift_report(repo_root, tmp_path)
    assert [item["check_id"] for item in report["checks"]] == [
        "console_placement",
        "production_console_absence",
        "production_reverse_import",
        "web_dependency_boundary",
        "loopback_bind",
        "api_v1_schema",
        "fixed_catalog",
        "argv_only_runner",
        "evidence_boundary",
        "no_production_logic_copy",
    ]
    assert summarize_drift([
        DriftCheck("x", DriftState.UNKNOWN, "unreadable", "confirmed")
    ])["state"] == "UNKNOWN"

def test_browser_uses_text_content_polling_and_has_six_views(
    static_root: Path,
) -> None:
    html = (static_root / "index.html").read_text(encoding="utf-8")
    javascript = (static_root / "app.js").read_text(encoding="utf-8")
    for view_id in (
        "dashboard-view", "tasks-view", "runner-view", "evidence-view",
        "architecture-drift-view", "scope-drift-view",
    ):
        assert f'id="{view_id}"' in html
    assert ".textContent" in javascript
    assert "innerHTML" not in javascript
    assert "WebSocket" not in javascript
    assert "EventSource" not in javascript
```

- [ ] **Step 2: Run RED and record the expected failure**

```powershell
py -3.14 -m pytest tests/verification_console/test_drift_e2e.py -q --basetemp "$env:TEMP\tvqc-task4-red"
```

Expected: collection fails because `tools.verification_console.drift` does not exist and status lacks detailed drift checks.

- [ ] **Step 3: Implement read-only drift reports and connect them to status**

Implement Section 2.4 and the exact check tables. Use `ast`, `inspect`, `pathlib`, and argv-only Git inspection; do not execute production code, fix files, stage changes, or contact remotes. Each check catches its own inspection failure and returns `UNKNOWN` with a short sanitized reason. Include full ordered checks under `architecture_drift` and `scope_drift` in `GET /api/v1/status`.

- [ ] **Step 4: Complete six-view UI and security/API acceptance**

Add Architecture Drift and Scope Drift as plain tables in the existing page. Keep the six views as `<section>` elements selected by native buttons/anchors; do not add client routing, templates, a framework, animation, complex filtering, or new endpoints. Render FAIL and UNKNOWN distinctly and never relabel either as healthy.

Run the full HTTP matrix against an ephemeral real server. Patch only the child process where executing a real command is unrelated to the assertion. The Task 1 integration case may execute the existing focused command once with a temporary runtime root and must assert branch/commit/task binding, unique basetemp, and terminal evidence.

- [ ] **Step 5: Run GREEN Console tests and refactor verification**

```powershell
py -3.14 -m pytest tests/verification_console -q --basetemp "$env:TEMP\tvqc-task4-green"
```

Expected: all Console unit, security, API, evidence, status, drift, and E2E tests pass. Refactor only shared drift result construction and UI text rendering; rerun with `tvqc-task4-refactor` and expect identical results.

- [ ] **Step 6: Perform browser/API Task 1 verification**

Terminal A:

```powershell
$env:PYTHONPATH = (Get-Location).Path
py -3.14 -m tools.verification_console
```

Browser: open `http://127.0.0.1:8765/`; click `task1.focused`, wait for PASS, click `task1.regression`, wait for PASS, open both Evidence records, and inspect Dashboard, Task Matrix, Architecture Drift, and Scope Drift. Task 1 must remain `REVIEW_PENDING` until explicit independent review evidence exists; this is the truthful expected result, not an acceptance failure.

Terminal B API cross-check:

```powershell
$base = 'http://127.0.0.1:8765/api/v1'
$health = Invoke-RestMethod -Uri "$base/health"
if ($health.status -ne 'ok' -or $health.bind_host -ne '127.0.0.1') { throw 'health contract failed' }
$commands = Invoke-RestMethod -Uri "$base/commands"
if (($commands.command_id -join ',') -ne 'task1.focused,task1.regression,baseline.v21,repo.diff_check,completed.all') { throw 'catalog order failed' }
$tasks = Invoke-RestMethod -Uri "$base/tasks"
if ($tasks.Count -ne 17 -or $tasks[0].task_id -ne '1' -or $tasks[16].task_id -ne '17') { throw 'task matrix failed' }
$status = Invoke-RestMethod -Uri "$base/status"
if ($status.branch -ne 'codex/v2-2a-data-foundation-impl') { throw 'branch binding failed' }
```

Stop Terminal A with Ctrl+C and verify no child remains.

- [ ] **Step 7: Run V2.1, Console, Task 1, and repository acceptance**

Use a different basetemp for every pytest command:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
py -3.14 -m pytest tests/verification_console -q --basetemp .verification-console/pytest/final-console
if ($LASTEXITCODE -ne 0) { throw 'Console suite failed' }
py -3.14 -m pytest tests/data_foundation/test_registration.py tests/contracts/test_artifact_contract.py tests/contracts/test_capability_registry.py -q --basetemp .verification-console/pytest/final-task1-focused
if ($LASTEXITCODE -ne 0) { throw 'Task 1 focused suite failed' }
py -3.14 -m pytest tests/data_foundation/test_registration.py tests/contracts/test_artifact_contract.py tests/contracts/test_capability_registry.py tests/pipeline/test_run_manifest.py -q --basetemp .verification-console/pytest/final-task1-regression
if ($LASTEXITCODE -ne 0) { throw 'Task 1 regression failed' }
py -3.14 -m pytest tests/contracts tests/adapters tests/pipeline/test_v2_cli_gate.py tests/integration/test_v2_1_gate.py tests/integration/test_v2_1_security.py -q --basetemp .verification-console/pytest/final-v21-gates
if ($LASTEXITCODE -ne 0) { throw 'V2.1 gate baseline failed' }
py -3.14 -m pytest tests/pipeline -q --basetemp .verification-console/pytest/final-v21-pipeline
if ($LASTEXITCODE -ne 0) { throw 'V2.1 pipeline baseline failed' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'git diff --check failed' }
git status --short
```

Expected: every pytest command passes; `git diff --check` is silent; status shows only reviewed Task 4 changes before commit and ignored `.verification-console/` runtime files do not appear.

- [ ] **Step 8: Commit Task 4 only**

```powershell
git add tools/verification_console/drift.py tools/verification_console/server.py tools/verification_console/status.py tools/verification_console/static/index.html tools/verification_console/static/app.css tools/verification_console/static/app.js tests/verification_console/test_drift_e2e.py
git commit -m "Add drift checks and console acceptance coverage."
```

Expected: Task 4 commit contains only the listed Console and Console-test files. Do not push, create a PR, merge, deploy, or begin V2.2A Task 2.

---

## 4. Dependency and Commit Order

```text
Task 1 browser/API skeleton
  commit -> independent review -> browser verification
    -> Task 2 fixed catalog/secure runner
       commit -> independent review -> Console verification
         -> Task 3 evidence/task truth
            commit -> independent review -> Console verification
              -> Task 4 drift/security/E2E
                 commit -> independent review -> final acceptance
```

- Task 1 owns the first visible page and stable server signature.
- Task 2 consumes the server but does not invent durable evidence.
- Task 3 is the only evidence/status truth owner and consumes terminal runner results.
- Task 4 consumes all prior interfaces and adds only read-only drift/acceptance.
- No task imports a later owner. No task changes the frozen V2.2A business dependency order.
- Each task has its own RED, GREEN, REFACTOR, focused tests, visual/API check, and commit boundary.

## 5. One-Day Timebox and Degradation Order

| Task | Maximum |
|---|---:|
| Task 1 | 1.5 h |
| Task 2 | 2.25 h |
| Task 3 | 2.0 h |
| Task 4 | 1.75 h |
| **Total hard ceiling** | **7.5 h** |

At 6.5 hours, stop adding CSS polish, responsive refinements, filters, animations, keyboard shortcuts, or extra run-detail interaction. Preserve the Dashboard, Task Matrix, Test Runner, Evidence, API, security, evidence integrity, truthful status, and drift signals. Keep Architecture and Scope Drift as basic tables inside the same page if necessary. Do not extend the timebox.

## 6. Final Acceptance Command

After Task 4's independent review and before declaring v0.1 complete, run this exact repository-root block. Every pytest command owns a separate basetemp:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
py -3.14 -m pytest tests/verification_console -q --basetemp .verification-console/pytest/accept-console
if ($LASTEXITCODE -ne 0) { throw 'Console acceptance failed' }
py -3.14 -m pytest tests/data_foundation/test_registration.py tests/contracts/test_artifact_contract.py tests/contracts/test_capability_registry.py tests/pipeline/test_run_manifest.py -q --basetemp .verification-console/pytest/accept-task1
if ($LASTEXITCODE -ne 0) { throw 'Task 1 acceptance failed' }
py -3.14 -m pytest tests/contracts tests/adapters tests/pipeline/test_v2_cli_gate.py tests/integration/test_v2_1_gate.py tests/integration/test_v2_1_security.py -q --basetemp .verification-console/pytest/accept-v21-gates
if ($LASTEXITCODE -ne 0) { throw 'V2.1 gate acceptance failed' }
py -3.14 -m pytest tests/pipeline -q --basetemp .verification-console/pytest/accept-v21-pipeline
if ($LASTEXITCODE -ne 0) { throw 'V2.1 pipeline acceptance failed' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'diff check failed' }
$changed = git diff --name-only 551900bd2a64f8772fc77c0bd4970fb5567c8248..HEAD
$allowed = $changed | Where-Object {
  $_ -ne '.gitignore' -and
  $_ -ne 'docs/superpowers/plans/2026-08-09-v2-2a-verification-console-implementation-plan.md' -and
  $_ -notlike 'tools/verification_console/*' -and
  $_ -notlike 'tests/verification_console/*'
}
if ($allowed) { $allowed; throw 'implementation scope escaped approved Console paths' }
git status --short
```

Expected: all suites pass; diff check is silent; approved-scope filter returns no path; runtime evidence stays ignored; worktree is clean after the Task 4 commit. The user can start the server and click-test Task 1 from the browser. No command downloads data, contacts a broker/provider, sends an order, performs a formal backtest, changes Git state beyond the four declared local commits, or contacts a remote.

## 7. Frozen Design Coverage Self-Review

| Frozen design section | Plan coverage |
|---|---|
| 1–4 decisions/goals/non-goals/placement | Global Constraints, Frozen File Map, Tasks 1–4 |
| 5 network/process security | Task 1 Host/static boundary; Task 2 POST/runner; Task 4 security matrix |
| 6 six UI views and polling truth | Tasks 1–4 incremental browser checks; Task 4 six-view acceptance |
| 7 API v1 compatibility/determinism/errors | Sections 2–3; Task 4 API matrix |
| 8 eight endpoints | Section 3; Tasks 1–3 implementation order; Task 4 full contract test |
| 9 five-command fixed catalog | Task 2 exact tuples/order; fail-closed disabled aggregate |
| 10 lifecycle/error semantics | Task 2 runner and shutdown; Task 3 terminal persistence |
| 11 evidence model | Task 3 exact schema, atomic storage, branch/commit/task/review binding |
| 12 truthful status | Task 3 six-state priority and actual tests |
| 13 Task 1–17 matrix source | Section 2.3; Task 3 exact ordered-title test |
| 14 architecture drift | Task 4 exact ten checks and summary precedence |
| 15 scope drift | Task 4 baseline/path/capability classifications |
| 16 existing-test reuse | Task 2 fixed current paths; no production assertions duplicated |
| 17 per-task workflow | Every task RED → GREEN → REFACTOR → commit/review/verify; Section 4 |
| 18 one-day timebox | Section 5 hard 7.5-hour ceiling and degradation order |
| 19 acceptance criteria | Task 4 focused cases and Section 6 final command |
| 20 design-time freeze | This document is the only current-plan change; implementation is not part of plan authoring |
| 21 closed decisions | Global Constraints and frozen interfaces; no open design choice remains |

Self-review result expected before plan commit: every frozen section maps to an implementation task or global invariant; no requirement requires production code, Task 2 business work, a new dependency, or an extra endpoint.

## 8. Plan Review Gates

Run these checks against this plan before committing it.

1. **Placeholder scan**

```powershell
$plan = 'docs/superpowers/plans/2026-08-09-v2-2a-verification-console-implementation-plan.md'
$terms = @(
  ('T' + 'BD'),
  ('T' + 'ODO'),
  ('FIX' + 'ME'),
  ('implement' + ' later'),
  ('fill in' + ' details'),
  ('Similar' + ' to Task'),
  ('Add appropriate' + ' error handling'),
  ('Write tests' + ' for the above')
)
$hits = Select-String -LiteralPath $plan -Pattern $terms -CaseSensitive:$false
if ($hits) { $hits; throw 'plan placeholder scan failed' }
```

Expected: no matches.

2. **Type/interface consistency review**

- `BIND_HOST`, API/version/service constants have one owner in `__init__.py`.
- `CommandSpec`/`StageSpec` have one owner in `catalog.py`; `RunManager` never accepts client argv/path.
- `RunRecord`/`StageResult`/serialization have one owner in `evidence.py`.
- `TaskStatus`, Task definitions, review metadata, predicate priority, and Dashboard counts have one owner in `status.py`.
- `DriftState` and aggregation have one owner in `drift.py`.
- Server consumes these interfaces and does not duplicate truth derivation.
- Browser consumes JSON and does not duplicate server enums, command tuples, or `DONE` logic.

Expected: every Task 2–4 consumer uses the exact Section 2 name, parameter order, and return meaning; no undefined later-task owner is required by an earlier commit.

3. **Dependency/order review**

Expected: Task 1 is browser-visible alone; Task 2 depends only on Task 1; Task 3 depends only on Tasks 1–2; Task 4 depends only on Tasks 1–3. Every task has focused RED/GREEN/REFACTOR commands and a separate commit. Total time is 7.5 hours.

4. **Scope and diff checks**

```powershell
$plan = 'docs/superpowers/plans/2026-08-09-v2-2a-verification-console-implementation-plan.md'
git status --short
git diff --check --no-index NUL $plan
if ($LASTEXITCODE -ne 1) { throw 'new-file diff check did not complete as expected' }
```

Expected during plan authoring: the only status path is `docs/superpowers/plans/2026-08-09-v2-2a-verification-console-implementation-plan.md`; the no-index diff reports only the new file and no whitespace error; no `tools/verification_console/`, Console test, production, requirement, frozen design, or Task 2 file exists. After staging, run `git diff --cached --check` and require exit 0 before commit.

5. **Plan-only commit**

```powershell
git add docs/superpowers/plans/2026-08-09-v2-2a-verification-console-implementation-plan.md
git commit -m "Plan V2.2A verification console implementation."
git show --name-only --format= HEAD
git status --short
```

Expected: the commit contains exactly this plan file and the worktree is clean. Stop after reporting the commit; do not implement Console Task 1, begin V2.2A Task 2, push, create a PR, merge, or deploy.
