# Pattern Finder M3C-A Universe Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the frozen M3C-A Universe Foundation contract as immutable profile versions, authoritative evidence, fail-closed per-security evaluation, reconciled snapshots, production-owned publication, and a UI that only displays production decisions.

**Architecture:** Preserve `src/tv_quant/pattern_finder/universe.py` as the frozen M3B fixture and create the sibling `universe_foundation/` package. Provider adapters collect facts, domain services normalize and evaluate them, append-only stores preserve every result, and Streamlit consumes production read models without calculating membership. M3C-B hydration, bulk detector compute, benchmarking, and all trading integration remain outside this plan.

**Tech Stack:** Python 3, frozen `dataclasses`, `Decimal`, JSON/JSONL, existing `tv_quant.run_manifest.canonical_hash`, Futu OpenAPI boundary, Streamlit 1.59.1, pandas, pytest, `streamlit.testing.v1.AppTest`.

## Authoritative inputs

- Frozen Design: `docs/superpowers/specs/2026-08-11-pattern-finder-m3c-a-universe-foundation-design.md`.
- Existing M3B contracts and tests under `src/tv_quant/pattern_finder/` and `tests/pattern_finder/`.
- Existing hash owner: `tv_quant.run_manifest.canonical_hash`.
- Current implementation-plan revision changes no production code and grants no implementation authority by itself.

## Global constraints

- CORE v1 is exactly the Frozen Design contract; Published Profiles and FORMAL Snapshots are append-only and immutable.
- M3C-A authoritative liquidity is Futu Stock Screening V2 `AVG_TURNOVER(days=20)` and authoritative listing history is `LISTED_DAYS`.
- Decimal values originate from deterministic source strings; liquidity cross-check uses `ROUND_HALF_EVEN`, `0.01 USD`, and inclusive absolute tolerance `<= 0.01 USD`; relative tolerance is forbidden.
- Only explicit classification evidence may PASS `COMMON_STOCK`; missing or conflicting evidence is UNKNOWN/Quarantine.
- CORE v1 Sector/Industry is ALL; preserve raw Industry/Owner Plate and keep `sector_mapping_version=None`.
- Signals, accounts, brokers, orders, TradingView Webhook, options, M3C-B hydration, detector compute, benchmarks, Pattern Instance, Review Queue, and Phase 2 are prohibited.
- UI imports production read models/services only. It cannot compare thresholds, classify securities, turn UNKNOWN into another state, calculate membership, authorize publication, or call `detect_flat_base()`.
- A deterministic provider-shaped fixture may support functional UI acceptance; it must contain real production evidence/evaluation objects and may not inject mock membership. Fixture acceptance is not live all-market acceptance.
- Live FORMAL acceptance remains blocked by an unqualified Security Master or incompatible Futu field/permission contract.

## Locked file map

```text
src/tv_quant/pattern_finder/universe_foundation/
  __init__.py
  profiles.py
  registry.py
  evidence.py
  security_master.py
  classification.py
  evaluator.py
  ui_read_model.py
  funnel.py
  futu_adapter.py
  futu_gateway.py
  snapshots.py
  preview.py
  scan_binding.py

app/pages/3_Universe_Settings.py
docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md
tests/pattern_finder/universe_foundation/*.py
tests/pattern_finder/test_universe_settings_page.py
tests/pattern_finder/test_universe_foundation_boundaries.py
```

`src/tv_quant/pattern_finder/universe.py`, `flat_base.py`, and existing M3B behavior remain unchanged.

## Dependency and interface rules

1. A task may consume only interfaces listed as produced by an earlier task.
2. `UniverseDraft.from_source()` does not exist. Task 2 constructs `UniverseDraft` with the Task 1 constructor and explicit copied/default filters.
3. `evaluate_attempt()` and `build_preview_snapshot()` do not exist. Task 13 calls Task 5 `resolve_classification()`, Task 6 `evaluate_security()`, Task 8 `build_funnel()`, and Task 11 `build_snapshot()` directly.
4. The only publication operation is Task 14 `ProfileRegistry.publish(draft_id=..., preview_id=..., published_at_utc=...)`. It ignores caller-built `PreviewResult` objects, reloads the Draft, and resolves the immutable authoritative `PreviewRecord` from the registry-bound Task 13 persistence root before validating exact Preview/evidence binding. No second profile owner or raw Published append API exists.
5. Every `FutuUniverseGateway` example uses the keyword-only constructor: `FutuUniverseGateway(sdk=fake_sdk, clock=fake_clock, sleep=fake_sleep)`.
6. Original Task 8 is deliberately split into Task 9 (provider adapter/endpoints/rate limiting) and Task 10 (qualification/identity/provenance/atomic attempt).

## Gate protocol

Every task follows this order:

```text
implementation scope
→ RED test
→ confirm intended RED
→ minimal GREEN
→ focused regression
→ refactor regression
→ exact-path staging and commit
→ independent review PASS
→ manual UI acceptance, when specified
→ acceptance evidence record
→ next related task
```

No formal manual gate occurs before its commit and independent review PASS. Task 3 has a post-review UI smoke check only. Tasks 7 and 12 prove projection behavior with prebuilt evaluation/snapshot states and therefore are not end-to-end Manual Functional Acceptance Gates. The first real Manual Functional Acceptance Gate is Task 15, after production Preview orchestration and authoritative Preview persistence exist.

The mandatory Pattern Finder regression after GREEN and after REFACTOR is:

```powershell
pytest tests/pattern_finder -q
```

---

### Task 1: Immutable CORE v1 profile and canonical hashes

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `src/tv_quant/pattern_finder/universe_foundation/profiles.py`
- Create: `tests/pattern_finder/universe_foundation/test_profiles.py`
- Preserve: `src/tv_quant/pattern_finder/universe.py`

**Interfaces:**
- Produces `UniverseFilters`, `UniverseProfile`, `UniverseDraft`, `ProfileKind`, `RecordState`, `Exchange`, `SecurityClass`, `core_v1()`.
- Produces `canonical_filter_payload(filters: UniverseFilters) -> dict[str, object]`, `filter_content_sha256(filters: UniverseFilters) -> str`, `profile_content_sha256(profile: UniverseProfile) -> str`, and `draft_content_sha256(draft: UniverseDraft) -> str`.
- `UniverseDraft` is constructed only as:

```python
UniverseDraft(
    draft_id: str,
    profile_family_id: str,
    profile_kind: ProfileKind,
    display_name: str,
    parent_profile_version_id: str | None,
    created_at_utc: datetime,
    change_note: str,
    filters: UniverseFilters,
    draft_content_sha256: str,
)
```

`core_v1()` freezes exchanges NYSE/NASDAQ/AMEX; `COMMON_STOCK`; price `>= 5.00`; market cap `>= 1000000000.00`; `FUTU_AVG_TURNOVER_20D >= 20000000.00`; `FUTU_LISTED_DAYS >= 250`; Sector/Industry ALL; all non-common toggles false; `active_only=true`; evidence versions from Frozen Design §8; and `sector_mapping_version=None`.

- [ ] **Step 1: RED** — Assert every frozen CORE v1 field, deep immutability, Decimal validation, stable set ordering, content/filter hash separation, and rejection of bool-as-int, NaN, Infinity, blanks, inverted bounds, and mixed ALL/value sets.
- [ ] **Step 2: Confirm RED** — Run `pytest tests/pattern_finder/universe_foundation/test_profiles.py -q`; expect missing module/import.
- [ ] **Step 3: GREEN** — Implement frozen models and hashes through `tv_quant.run_manifest.canonical_hash`; no alternate hash owner.
- [ ] **Step 4: Regression** — Run `pytest tests/pattern_finder/universe_foundation/test_profiles.py tests/pattern_finder/test_universe.py -q`, then the mandatory Pattern Finder regression.
- [ ] **Step 5: Commit exact files**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation/__init__.py src/tv_quant/pattern_finder/universe_foundation/profiles.py tests/pattern_finder/universe_foundation/test_profiles.py
git commit -m "feat: freeze M3C-A universe profile contract"
```

- [ ] **Step 6: Independent review** — Confirm exact CORE values, Decimal-only hashing, immutable collections, no M3B change, and no M3C-B behavior. Record PASS before Task 2.

---

### Task 2: Draft and append-only profile registry storage

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/registry.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_registry.py`

**Interfaces:**
- Consumes Task 1 models/hashes.
- Produces `ProfileAvailabilityAction(ACTIVATED, RETIRED)`, immutable `ProfileAvailabilityEvent(profile_version_id: str, action: ProfileAvailabilityAction, occurred_at_utc: datetime, reason: str)`, `ProfileRegistry(root: str | Path)`, read-only `preview_evidence_root: Path` fixed to the registry layout, `bootstrap(profile: UniverseProfile) -> None`, `create_draft(*, draft_id: str, family_id: str, profile_kind: ProfileKind, display_name: str, change_note: str, source_profile_version_id: str | None, created_at_utc: datetime) -> UniverseDraft`, `save_draft(draft: UniverseDraft) -> None`, `get_draft(draft_id: str) -> UniverseDraft`, `close_draft(draft_id: str) -> None`, `get_published(profile_version_id: str) -> UniverseProfile`, `list_published(family_id: str | None=None) -> tuple[UniverseProfile, ...]`, `record_availability(event: ProfileAvailabilityEvent) -> None`, and `latest_availability(profile_version_id: str) -> ProfileAvailabilityEvent | None`.
- `preview_evidence_root` reserves the single production Preview Evidence location consumed by Tasks 13-15; it grants no Preview write API and creates no second profile/version owner.
- Produces no raw profile-append API. Task 14 extends this same class with the only authorized publication operation after Preview types exist.
- Does not yet produce `publish`; Task 14 adds it with the complete production authorization contract.

- [ ] **Step 1: RED** — Test explicit CORE bootstrap, idempotent same-hash bootstrap, conflicting bootstrap failure, empty registry behavior, direct `UniverseDraft` constructor copying, blank-draft defaults, atomic draft save, corrupt-line fail-closed, availability append-only behavior, and absence of any raw Published append method.
- [ ] **Step 2: Confirm RED** — Run `pytest tests/pattern_finder/universe_foundation/test_registry.py -q`; expect missing `ProfileRegistry`.
- [ ] **Step 3: GREEN** — Construct a cloned draft with the Task 1 `UniverseDraft` constructor, source filters, parent ID and recomputed `draft_content_sha256`; construct a blank draft with explicitly validated Task 1 defaults. Never call `UniverseDraft.from_source()`.
- [ ] **Step 4: Regression** — Run profile/registry tests and the mandatory Pattern Finder regression.
- [ ] **Step 5: Commit exact files**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation/__init__.py src/tv_quant/pattern_finder/universe_foundation/registry.py tests/pattern_finder/universe_foundation/test_registry.py
git commit -m "feat: add universe profile registry storage"
```

- [ ] **Step 6: Independent review** — Confirm explicit bootstrap, no implicit globals, no undefined constructor, no public incomplete publication path, and append-only Published storage. Record PASS before Task 3.

---

### Task 3: Initialized Profile page UI smoke check

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/ui_read_model.py`
- Create: `app/pages/3_Universe_Settings.py`
- Modify: `app/Home.py`
- Create: `tests/pattern_finder/universe_foundation/test_ui_read_model.py`
- Create: `tests/pattern_finder/test_universe_settings_page.py`
- Create: `docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md`

**Interfaces:**
- Produces `ProfileUiState`, `ProfileConditionRow`, `load_profile_ui_state(registry: ProfileRegistry, profile_version_id: str) -> ProfileUiState` and `render_profile_status(*, registry: ProfileRegistry, profile_version_id: str) -> None` only. Later tasks add separate renderer functions after their input types exist.
- Test and production setup both call `registry.bootstrap(core_v1())` before rendering; tests may inject an already initialized registry. No environment lookup creates implicit profile state inside the read model.

- [ ] **Step 1: RED** — AppTest injects an initialized registry and asserts CORE:v1 fields; a separate test proves an empty registry produces an explicit error rather than implicit bootstrap or a false membership claim.
- [ ] **Step 2: Confirm RED** — Run the two UI test files; expect missing page/read model.
- [ ] **Step 3: GREEN** — Add navigation and render Published Profile conditions/hashes only. The production entry explicitly opens the registry and calls `bootstrap(core_v1())`; the page renderer receives that initialized instance.
- [ ] **Step 4: Regression** — Run the two UI files, `tests/pattern_finder/test_pages.py`, and the mandatory Pattern Finder regression.
- [ ] **Step 5: Commit exact files**

```powershell
git add app/Home.py app/pages/3_Universe_Settings.py src/tv_quant/pattern_finder/universe_foundation/__init__.py src/tv_quant/pattern_finder/universe_foundation/ui_read_model.py tests/pattern_finder/universe_foundation/test_ui_read_model.py tests/pattern_finder/test_universe_settings_page.py docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md
git commit -m "feat: show initialized universe profile status"
```

- [ ] **Step 6: Independent review** — Confirm commit PASS and registry initialization parity.
- [ ] **Step 7: Post-review UI smoke** — Open 股票池设置 and record that CORE:v1, conditions, versions and hashes render. Label the record `UI_SMOKE_ONLY`; do not call it functional acceptance and do not claim evaluated membership.

---

### Task 4: Immutable evidence, provenance, and numeric normalization

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/evidence.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_evidence.py`

**Interfaces:**
- Produces `Decision`, `AttemptStatus`, `Completeness`, `EvidenceReference`, `EvidenceProvenance`, `RawIndustryEvidence`, `RawPlateEvidence`, `SecurityClassificationEvidence`, `LiquidityEvidence`, `ListingHistoryEvidence`, and `UniverseSecurityEvidence`.
- Produces `decimal_from_source(value: str, *, field_id: str, allow_negative: bool=False) -> Decimal`, `quantize_usd_cent(value: str, *, field_id: str) -> Decimal`, and `evidence_record_sha256(evidence: UniverseSecurityEvidence) -> str`.

- [ ] **Step 1: RED** — Test immutable evidence, UTC, lowercase SHA-256, provider versions, raw Industry/all Plates, source-string Decimal, half-even `0.004/0.005/0.006/0.015`, non-finite/negative rejection, and provenance-sensitive hashes.
- [ ] **Step 2: Confirm RED** — Run `pytest tests/pattern_finder/universe_foundation/test_evidence.py -q`.
- [ ] **Step 3: GREEN** — Implement typed evidence with deterministic collection ordering and no network/business logic.
- [ ] **Step 4: Regression** — Run evidence, numeric canonicalization and run-manifest tests, then mandatory Pattern Finder regression.
- [ ] **Step 5: Commit exact files**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation/__init__.py src/tv_quant/pattern_finder/universe_foundation/evidence.py tests/pattern_finder/universe_foundation/test_evidence.py
git commit -m "feat: add immutable universe evidence models"
```

- [ ] **Step 6: Independent review** — Confirm evidence/version/source preservation and no alternate hash/business owner. Record PASS before Task 5.

---

### Task 5: Security Master port and fail-closed classification

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/security_master.py`
- Create: `src/tv_quant/pattern_finder/universe_foundation/classification.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_classification.py`

**Interfaces:**
- Produces `SecurityMasterProvider.classification_evidence(self, stock_id: str, futu_code: str, as_of_utc: datetime) -> tuple[SecurityClassificationEvidence, ...]`, `AppendOnlyClassificationLedger.append(evidence: SecurityClassificationEvidence) -> None`, `AppendOnlyClassificationLedger.get(stock_id: str, *, as_of_utc: datetime) -> tuple[SecurityClassificationEvidence, ...]`, `ClassificationResult`, and `resolve_classification(top_level_futu_type: str | None, evidence: Sequence[SecurityClassificationEvidence]) -> ClassificationResult`.
- The resolver accepts no symbol/name/suffix/regex parameter.

- [ ] **Step 1: RED** — Test explicit non-common FAIL, STOCK-alone UNKNOWN, explicit Common PASS, conflicts UNKNOWN, complete manual evidence locator/hash/time/verifier, correction append-only, and structural prohibition of ticker/name inference.
- [ ] **Step 2: Confirm RED** — Run `pytest tests/pattern_finder/universe_foundation/test_classification.py -q`.
- [ ] **Step 3: GREEN** — Implement the evidence hierarchy and stable reason codes `CLASSIFICATION_UNKNOWN` and `CLASSIFICATION_EVIDENCE_CONFLICT`.
- [ ] **Step 4: Regression** — Run `pytest tests/pattern_finder/universe_foundation/test_classification.py tests/pattern_finder/test_universe.py tests/pattern_finder/test_futu_service.py -q`, then mandatory Pattern Finder regression.
- [ ] **Step 5: Commit exact files**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation/__init__.py src/tv_quant/pattern_finder/universe_foundation/security_master.py src/tv_quant/pattern_finder/universe_foundation/classification.py tests/pattern_finder/universe_foundation/test_classification.py
git commit -m "feat: add fail-closed security classification"
```

- [ ] **Step 6: Independent review and qualification record** — Record exact source/version/subtype field/sample or `CLASSIFICATION_EVIDENCE_BLOCKER`; never weaken to heuristics. Record review PASS before Task 6.

---

### Task 6: Pure per-security evaluator and Quarantine

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/evaluator.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_evaluator.py`

**Interfaces:**
- Produces `FieldDecision`, `SecurityEvaluation`, `compare_liquidity_cross_check(authoritative_source: str, cross_check_source: str) -> FieldDecision`, and `evaluate_security(profile: UniverseProfile, evidence: UniverseSecurityEvidence, classification: ClassificationResult) -> SecurityEvaluation`.
- `FieldDecision` contains field/metric, raw and normalized values, operator/threshold, PASS/FAIL/UNKNOWN, reason, evidence source/time/version/refs.

- [ ] **Step 1: RED** — Test every Frozen Design boundary: exchanges, Common/non-common, active states, price, cap, listing 250/249, liquidity 20M/one-cent-below, Sector=ALL, missing/conflicting fields, auxiliary listing date, absolute cent tolerance, first exit and Quarantine.
- [ ] **Step 2: Confirm RED** — Run `pytest tests/pattern_finder/universe_foundation/test_evaluator.py -q`.
- [ ] **Step 3: GREEN** — Evaluate all independent fields, then derive first exit, final membership and Quarantine using fixed order. The evaluator imports no Futu SDK, filesystem, Streamlit or detector.
- [ ] **Step 4: Regression** — Run `pytest tests/pattern_finder/universe_foundation/test_evaluator.py tests/pattern_finder/test_flat_base.py tests/pattern_finder/test_pattern_review_regression.py -q`, then mandatory Pattern Finder regression.
- [ ] **Step 5: Commit exact files**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation/__init__.py src/tv_quant/pattern_finder/universe_foundation/evaluator.py tests/pattern_finder/universe_foundation/test_evaluator.py
git commit -m "feat: evaluate universe securities deterministically"
```

- [ ] **Step 6: Independent review** — Confirm authoritative metrics, versioned evidence, reason codes, no future/local ADV substitution, and no UI decision logic. Record PASS before Task 7.

---

### Task 7: Per-security production-result UI projection

**Files:**
- Modify: `src/tv_quant/pattern_finder/universe_foundation/ui_read_model.py`
- Modify: `app/pages/3_Universe_Settings.py`
- Modify: `tests/pattern_finder/universe_foundation/test_ui_read_model.py`
- Modify: `tests/pattern_finder/test_universe_settings_page.py`
- Modify: `docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md`

**Interfaces:**
- Produces `EvaluationUiState`, `DecisionDetailUi`, and `build_evaluation_ui_state(*, profile: UniverseProfile, evidence: UniverseSecurityEvidence, classification: ClassificationResult) -> EvaluationUiState`, which calls Task 6 `evaluate_security()` exactly once and projects its immutable output.
- Produces `render_security_evaluation(*, state: EvaluationUiState) -> None`; the page calls Task 3 `render_profile_status()` and this new renderer independently.
- UI displays production evaluation/evidence; it does not receive or invent a membership flag separately.

- [ ] **Step 1: RED** — Use provider-shaped immutable fixtures for a Common PASS and classification UNKNOWN. Assert ticker/security, evaluation status, authoritative metric, actual/normalized value, threshold, source/ref, PASS/FAIL/UNKNOWN, reason, Quarantine, profile version/hash, and evidence version.
- [ ] **Step 2: Confirm RED** — Run `pytest tests/pattern_finder/universe_foundation/test_ui_read_model.py tests/pattern_finder/test_universe_settings_page.py -q`; failure must be missing projection/rendering, not a mocked membership assertion.
- [ ] **Step 3: GREEN** — Render the complete per-security decision rows and final `SecurityEvaluation.is_member/is_quarantined` from production output.
- [ ] **Step 4: Regression** — Run `pytest tests/pattern_finder/universe_foundation/test_ui_read_model.py tests/pattern_finder/universe_foundation/test_evaluator.py tests/pattern_finder/test_universe_settings_page.py tests/pattern_finder/test_flat_base.py -q`, then mandatory Pattern Finder regression. Scan the page for `Decimal|ROUND_HALF_EVEN|resolve_classification|evaluate_security|detect_flat_base`; expected no UI business owner.
- [ ] **Step 5: Commit exact files**

```powershell
git add app/pages/3_Universe_Settings.py src/tv_quant/pattern_finder/universe_foundation/ui_read_model.py tests/pattern_finder/universe_foundation/test_ui_read_model.py tests/pattern_finder/test_universe_settings_page.py docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md
git commit -m "feat: show production universe evaluations"
```

- [ ] **Step 6: Independent review** — Review must PASS production-owner uniqueness, fixture provenance, visible fields, and no UI recomputation. Record this as an automated projection checkpoint only: `render_security_evaluation()` receives a prebuilt `EvaluationUiState`, so Task 7 does not claim fixture/input → production evidence loading → classification → evaluation → UI completeness and does not block Task 8 on a manual Gate.

---

### Task 8: Fixed S0-S10 funnel reconciliation

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/funnel.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_funnel.py`

**Interfaces:**
- Produces `FunnelStage`, `UniverseFunnel`, `build_funnel(evaluations: Sequence[SecurityEvaluation]) -> UniverseFunnel`, and `funnel_sha256(funnel: UniverseFunnel) -> str` using Design §16 stage IDs.

- [ ] **Step 1: RED** — Test each input=pass+fail+unknown, next input=prior pass, members=S10, stable reason counts/hash, shuffle stability, duplicate ledger and identity blockers.
- [ ] **Step 2: Confirm RED** — Run `pytest tests/pattern_finder/universe_foundation/test_funnel.py -q`.
- [ ] **Step 3: GREEN** — Aggregate existing `FieldDecision` objects only; no thresholds or source parsing.
- [ ] **Step 4: Regression** — Run `pytest tests/pattern_finder/universe_foundation/test_funnel.py tests/pattern_finder/universe_foundation/test_evaluator.py -q`, then mandatory Pattern Finder regression.
- [ ] **Step 5: Commit exact files**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation/__init__.py src/tv_quant/pattern_finder/universe_foundation/funnel.py tests/pattern_finder/universe_foundation/test_funnel.py
git commit -m "feat: reconcile the M3C-A universe funnel"
```

- [ ] **Step 6: Independent review** — Confirm no business decision is recalculated and all candidates remain auditable. Record PASS before Task 9.

---

### Task 9: Futu provider adapter, pagination, endpoint contracts, and rate limiters

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/futu_adapter.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_futu_adapter.py`
- Preserve: `src/tv_quant/pattern_finder/futu_service.py`

**Interfaces:**
- Produces `FutuProviderAdapter(*, sdk: Any, clock: Callable[[], datetime], sleep: Callable[[float], None])`, `RatePolicy`, `RawApiPage`, `RawApiBatch`, and endpoint methods `discover_cash_securities() -> tuple[RawApiBatch, ...]`, `screen_all_pages() -> tuple[RawApiPage, ...]`, `market_snapshots(codes: Sequence[str]) -> tuple[RawApiBatch, ...]`, `owner_plates(codes: Sequence[str]) -> tuple[RawApiBatch, ...]`.
- Market Snapshot policy is 400 items and 60 requests/30 seconds; Owner Plate is 200 items and 10 requests/30 seconds, with independent limiter state.

- [ ] **Step 1: RED** — Instantiate `FutuProviderAdapter(sdk=fake_sdk, clock=fake_clock, sleep=fake_sleep)` and test discovery categories, full pagination, raw request/response hashes, ret-code mapping, schema fields, null preservation, bounded retry, 400/60 and 200/10 independent limiters, and context close on success/failure.
- [ ] **Step 2: Confirm RED** — Run `pytest tests/pattern_finder/universe_foundation/test_futu_adapter.py -q`; expected missing adapter.
- [ ] **Step 3: GREEN** — Implement raw endpoint acquisition only. It makes no identity, classification, threshold, completeness or membership decision.
- [ ] **Step 4: Regression** — Run `pytest tests/pattern_finder/universe_foundation/test_futu_adapter.py tests/pattern_finder/test_futu_service.py tests/pattern_finder/test_expand_m3b_universe.py tests/test_futu_downloader.py -q`, then mandatory Pattern Finder regression.
- [ ] **Step 5: Commit exact files**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation/__init__.py src/tv_quant/pattern_finder/universe_foundation/futu_adapter.py tests/pattern_finder/universe_foundation/test_futu_adapter.py
git commit -m "feat: add Futu universe provider adapter"
```

- [ ] **Step 6: Independent review** — Confirm endpoint contracts, pagination and policies independently; record the interface handoff PASS before Task 10.

---

### Task 10: Futu qualification, identity reconciliation, provenance, and atomic attempt

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/futu_gateway.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_futu_gateway.py`

**Interfaces:**
- Consumes Task 9 adapter and Task 5 `SecurityMasterProvider`.
- Produces `FutuUniverseGateway(*, sdk: Any | None=None, host: str="127.0.0.1", port: int=11111, clock: Callable[[], datetime], sleep: Callable[[float], None])`, `GatewayPreflight`, `GatewayAttempt`, `ApiBatchRecord`, and `collect(*, as_of_session: date, observed_at_utc: datetime, classification_provider: SecurityMasterProvider) -> GatewayAttempt`.
- `GatewayAttempt` contains immutable evidence, page/batch manifests, identity ledger, preflight, status/completeness and stable blockers.

`GatewayAttempt` freezes `attempt_id: str`, `as_of_session: date`, `observed_at_utc: datetime`, `provider_update_time: datetime | None`, `market_data_delay_class: str`, `preflight: GatewayPreflight`, `evidence: tuple[UniverseSecurityEvidence, ...]`, `batches: tuple[ApiBatchRecord, ...]`, `identity_ledger: tuple[IdentityLedgerEntry, ...]`, `attempt_status: AttemptStatus`, `completeness: Completeness`, and `reason_codes: tuple[str, ...]`.

Stable blockers are exactly `FUTU_LOGIN_BLOCKER`, `FUTU_MARKET_PERMISSION_BLOCKER`, `FUTU_RATE_LIMIT_RETRY_EXHAUSTED`, `FUTU_QUOTA_BLOCKER`, `FUTU_SCHEMA_BLOCKER`, `FUTU_PAGINATION_BLOCKER`, `UNIVERSE_IDENTITY_BLOCKER`, `UNIVERSE_INCOMPLETE_BLOCKER`, `CLASSIFICATION_EVIDENCE_BLOCKER`, `LIQUIDITY_EVIDENCE_CONFLICT`, and `LISTING_HISTORY_CONFLICT`. FORMAL inputs require the latest complete XNYS regular session and bind `as_of_session`, `observed_at_utc`, provider update time and delay class; intraday data remains PREVIEW/PROVISIONAL.

- [ ] **Step 1: RED** — Every example calls `FutuUniverseGateway(sdk=fake_sdk, clock=fake_clock, sleep=fake_sleep)`. Test qualification, explicit versions/permissions, identity conflicts, subtype evidence, provenance, missing/new enum behavior, failed necessary batch => FAILED/INCOMPLETE/non-formal, and no partial publication.
- [ ] **Step 2: Confirm RED** — Run `pytest tests/pattern_finder/universe_foundation/test_futu_gateway.py -q`; expected missing orchestration, never constructor `TypeError`.
- [ ] **Step 3: GREEN** — Compose Task 9 adapter outputs, reconcile identities, normalize evidence, and close the attempt atomically. Do not request history K-lines or evaluate thresholds.
- [ ] **Step 4: Regression** — Run `pytest tests/pattern_finder/universe_foundation/test_futu_gateway.py tests/pattern_finder/universe_foundation/test_futu_adapter.py tests/pattern_finder/universe_foundation/test_evidence.py tests/pattern_finder/universe_foundation/test_classification.py tests/pattern_finder/test_futu_service.py -q`, then mandatory Pattern Finder regression.
- [ ] **Step 5: Commit exact files**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation/__init__.py src/tv_quant/pattern_finder/universe_foundation/futu_gateway.py tests/pattern_finder/universe_foundation/test_futu_gateway.py
git commit -m "feat: build atomic Futu universe attempts"
```

- [ ] **Step 6: Independent review and quota-safe qualification** — Record actual approved tiny-sample SDK/OpenD fields or stable blocker. Confirm no hydration, semantic fallback, partial FORMAL result, or policy merge. Record PASS before Task 11.

---

### Task 11: Deterministic Universe Snapshot and immutable store

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/snapshots.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_snapshots.py`

**Interfaces:**
- Produces `SnapshotKind`, `UniverseSnapshotHeader`, `UniverseSnapshotRow`, `UniverseSnapshot`, `UniverseSnapshotStore`, `build_snapshot(*, kind: SnapshotKind, profile: UniverseProfile | None, draft: UniverseDraft | None, gateway_attempt: GatewayAttempt, evaluations: Sequence[SecurityEvaluation], funnel: UniverseFunnel, universe_snapshot_id: UUID, created_at_utc: datetime) -> UniverseSnapshot`, `snapshot_content_sha256(snapshot: UniverseSnapshot) -> str`, `snapshot_record_sha256(snapshot: UniverseSnapshot) -> str`, and `members_sha256(rows: Sequence[UniverseSnapshotRow]) -> str`.
- `build_snapshot(*, kind, profile, draft, gateway_attempt, evaluations, funnel, universe_snapshot_id, created_at_utc)` is the only snapshot builder.
- Freezes the complete store contract before Tasks 12 and 13 use it:

```python
class UniverseSnapshotStore:
    def __init__(self, root: str | Path) -> None: ...
    def append(self, snapshot: UniverseSnapshot) -> UniverseSnapshot: ...
    def get(self, snapshot_id: UUID) -> UniverseSnapshot: ...
```

- `append()` canonicalizes and validates the complete record before one atomic create-and-fsync. It returns the persisted immutable value. A new ID appends once; the same ID with byte-identical canonical record returns the existing value without rewriting; the same ID with different content raises `SnapshotConflictError`; invalid hashes/bindings or an incomplete/failed FORMAL snapshot raise `SnapshotValidationError`; storage errors raise `SnapshotStoreError`. No overwrite/update/delete method exists.
- `get()` parses and revalidates the canonical record and both hashes on every read. A missing ID raises `SnapshotNotFoundError`; malformed, truncated or hash-mismatched storage raises `SnapshotCorruptError`. It never returns `None`, an empty snapshot, or an inferred ineligible decision. No `latest()`, `list()`, or `read()` interface exists in M3C-A.

- [ ] **Step 1: RED** — Test content-vs-record hash fields, all PASS/FAIL/UNKNOWN rows, provenance sensitivity and deterministic input order; instantiate `UniverseSnapshotStore(root=tmp_path)`, test atomic immutable `append()`/`get()`, idempotent byte-identical duplicate ID, conflicting duplicate ID, missing ID, malformed/truncated/hash-mismatched record, failed/incomplete FORMAL prohibition, persistence-error propagation, and structural absence of overwrite/update/delete/latest/list/read methods.
- [ ] **Step 2: Confirm RED** — Run `pytest tests/pattern_finder/universe_foundation/test_snapshots.py -q`.
- [ ] **Step 3: GREEN** — Build rows from evaluations and implement exactly the frozen constructor/`append()`/`get()` contract. Validate exact profile/draft/evidence binding and both hashes before atomic create/fsync; all reads and conflicts fail closed with the named typed errors.
- [ ] **Step 4: Regression** — Run `pytest tests/pattern_finder/universe_foundation/test_snapshots.py tests/pattern_finder/universe_foundation/test_funnel.py tests/pipeline/test_run_manifest.py -q`, then mandatory Pattern Finder regression.
- [ ] **Step 5: Commit exact files**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation/__init__.py src/tv_quant/pattern_finder/universe_foundation/snapshots.py tests/pattern_finder/universe_foundation/test_snapshots.py
git commit -m "feat: persist immutable universe snapshots"
```

- [ ] **Step 6: Independent review** — Confirm full-candidate retention, immutable evidence binding, exact store signatures, deterministic duplicate semantics, typed fail-closed reads, and append-only FORMAL rules. Confirm Tasks 12/13 require no undefined store method; record PASS before Task 12.

---

### Task 12: Snapshot decision read model and complete evidence UI Gate

**Files:**
- Modify: `src/tv_quant/pattern_finder/universe_foundation/ui_read_model.py`
- Modify: `app/pages/3_Universe_Settings.py`
- Modify: `tests/pattern_finder/universe_foundation/test_ui_read_model.py`
- Modify: `tests/pattern_finder/test_universe_settings_page.py`
- Modify: `docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md`

**Interfaces:**
- Produces `SnapshotUiState`, `load_snapshot_ui_state(store: UniverseSnapshotStore, snapshot_id: UUID) -> SnapshotUiState`, and `find_security_decision(state: SnapshotUiState, query: str) -> DecisionDetailUi | None`. It consumes `UniverseSnapshotStore` only.
- Produces `render_snapshot_evidence(*, state: SnapshotUiState) -> None`; it does not change either earlier renderer signature.
- Every detail exposes ticker/security, evaluation status, authoritative metric, actual/normalized value, threshold, source/ref/time, PASS/FAIL/UNKNOWN, reason, Quarantine, profile version/hash, evidence version, snapshot content/record hashes.

- [ ] **Step 1: RED** — Fixture Snapshot covers Liquidity boundary, Listing boundary/auxiliary warning, Classification PASS/UNKNOWN, both conflicts, raw Industry/all Plates, COMPLETE/INCOMPLETE, member/FAIL/Quarantine and first exit.
- [ ] **Step 2: Confirm RED** — Run `pytest tests/pattern_finder/universe_foundation/test_ui_read_model.py tests/pattern_finder/test_universe_settings_page.py -q`; failure must identify missing projection/field.
- [ ] **Step 3: GREEN** — Add Snapshot status, funnel, member/FAIL/Quarantine tables, symbol search, all-field detail, raw evidence and downloads. “No record” is an error, never “not eligible”.
- [ ] **Step 4: Regression** — Run `pytest tests/pattern_finder/universe_foundation/test_ui_read_model.py tests/pattern_finder/universe_foundation/test_snapshots.py tests/pattern_finder/test_universe_settings_page.py tests/pattern_finder/test_flat_base.py -q`, mandatory Pattern Finder regression, and UI decision-logic scan.
- [ ] **Step 5: Commit exact files**

```powershell
git add app/pages/3_Universe_Settings.py src/tv_quant/pattern_finder/universe_foundation/ui_read_model.py tests/pattern_finder/universe_foundation/test_ui_read_model.py tests/pattern_finder/test_universe_settings_page.py docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md
git commit -m "feat: expose snapshot decision evidence"
```

- [ ] **Step 6: Independent review** — Confirm projection-only UI and all visible evidence fields. Record this as an automated persisted-Snapshot projection checkpoint only: Task 12 selects a prebuilt fixture Snapshot and does not yet execute production Preview orchestration, so it is not the first real manual functional Gate and does not block Task 13 on a manual Gate.

---

### Task 13: Non-mutating Preview orchestration and parent diff

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/preview.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/registry.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_preview.py`
- Modify: `tests/pattern_finder/universe_foundation/test_registry.py`

**Interfaces:**
- Produces immutable `PreviewDiff`, `PreviewResult`, `PreviewRecord`, and `PreviewInvalidationRecord`. The production entry is `ProfileRegistry.run_preview(*, draft_id: str, gateway_attempt: GatewayAttempt, parent_snapshot: UniverseSnapshot | None, snapshot_store: UniverseSnapshotStore, universe_snapshot_id: UUID, created_at_utc: datetime) -> PreviewRecord`; `ProfileRegistry.get_preview(preview_id: UUID) -> PreviewRecord` is the only UI read entry.
- `ProfileRegistry.run_preview()` reloads the authoritative Draft, then its private orchestration explicitly loops through `gateway_attempt.evidence`, calls Task 5 `resolve_classification()`, Task 6 `evaluate_security()`, Task 8 `build_funnel()`, and Task 11 `build_snapshot(kind=PREVIEW, ...)`. It accepts no caller-built `Profile`, `PreviewResult`, classification, evaluation or completeness value.
- `PreviewResult` freezes `input_profile_version_id: str | None`, `input_draft_id: str | None`, `input_content_sha256: str`, `input_filter_content_sha256: str`, `parent_profile_version_id: str | None`, `evidence_attempt_id: str`, `evidence_binding_sha256: str`, `evidence_versions: tuple[str, ...]`, `completeness: Completeness`, `snapshot: UniverseSnapshot`, and `diff: PreviewDiff`.
- `PreviewRecord` freezes server-owned `preview_id: UUID`, `record_schema_version: str`, the complete `result: PreviewResult`, `created_at_utc: datetime`, `supersedes_preview_id: UUID | None`, and `content_sha256: str`. `PreviewInvalidationRecord` freezes `preview_id: UUID`, `invalidated_at_utc: datetime`, `reason: str`, and `record_sha256: str`. Callers cannot choose IDs, hashes or persisted status independently of `ProfileRegistry.run_preview()`.
- Freezes the authoritative evidence store contract before publication uses it:

```python
class PreviewEvidenceStore:
    def __init__(self, root: str | Path, *, id_factory: Callable[[], UUID]) -> None: ...
    def append(self, result: PreviewResult, *, created_at_utc: datetime) -> PreviewRecord: ...
    def get(self, preview_id: UUID) -> PreviewRecord: ...
    def latest_for_draft(self, draft_id: str) -> PreviewRecord: ...
    def invalidate(self, preview_id: UUID, *, invalidated_at_utc: datetime, reason: str) -> PreviewInvalidationRecord: ...
    def is_invalidated(self, preview_id: UUID) -> bool: ...
```

- `PreviewEvidenceStore` is not exported as a production application API. `ProfileRegistry` constructs it internally from exact `self.preview_evidence_root` and a server-owned UUID factory. `append()` allocates `preview_id` internally, validates the complete result, atomically appends it, and binds `supersedes_preview_id` to the prior record for that Draft; duplicate generated IDs raise `PreviewConflictError`, invalid results raise `PreviewValidationError`, and storage failure raises `PreviewStoreError`. `get()` and `latest_for_draft()` revalidate record/content hashes; missing IDs/Drafts raise `PreviewNotFoundError`, and malformed/truncated/hash-mismatched evidence raises `PreviewCorruptError`. `invalidate()` appends a hashed status event, rejects blank reasons and missing IDs, and is idempotent only for a byte-identical event; a conflicting repeat raises `PreviewConflictError`. `is_invalidated()` fail-closes on corrupt status evidence. No replace/update/delete/list/read API exists.
- `ProfileRegistry.run_preview()` derives every result field, persists the PREVIEW Snapshot through Task 11 `append()`, persists the complete immutable record through its internal store, and returns that authoritative record. A later successful Preview for the same Draft supersedes the prior record through `supersedes_preview_id` plus `latest_for_draft()`; explicit invalidation is an append-only record. Stale means the Draft/hash/parent binding no longer matches the current stored Draft or the record is not `latest_for_draft(draft_id)`; there is no unspecified wall-clock expiry in M3C-A.

- [ ] **Step 1: RED** — Test `ProfileRegistry.run_preview()` production fixture/GatewayAttempt → classification → evaluation → funnel → PREVIEW Snapshot → immutable PreviewRecord; reject caller-built result/classification/evaluation inputs; assert exact draft/profile/filter/parent/evidence/version hashes, COMPLETE/INCOMPLETE, full funnel, added/removed reasons, server-owned `preview_id`/content hash, atomic append/get/latest, generated-ID collision, missing/corrupt evidence, append-only invalidation/supersession, precise binding-stale behavior, PREVIEW-only persistence, unexported store writer, and unchanged Published/FORMAL Snapshot/Scan/Review/Detector files.
- [ ] **Step 2: Confirm RED** — Run `pytest tests/pattern_finder/universe_foundation/test_preview.py -q`.
- [ ] **Step 3: GREEN** — Implement the registry-owned production entry using only earlier production interfaces plus the internal store contract defined in this task; do not call or define `evaluate_attempt()` or `build_preview_snapshot()`. Allocate the ID and persist the full result before returning its immutable `PreviewRecord`; never accept a caller-built `PreviewResult` as authoritative evidence.
- [ ] **Step 4: Regression** — Run `pytest tests/pattern_finder/universe_foundation/test_preview.py tests/pattern_finder/universe_foundation/test_registry.py tests/pattern_finder/universe_foundation/test_snapshots.py tests/pattern_finder/universe_foundation/test_evaluator.py -q`, then mandatory Pattern Finder regression.
- [ ] **Step 5: Commit exact files**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation/__init__.py src/tv_quant/pattern_finder/universe_foundation/preview.py src/tv_quant/pattern_finder/universe_foundation/registry.py tests/pattern_finder/universe_foundation/test_preview.py tests/pattern_finder/universe_foundation/test_registry.py
git commit -m "feat: add non-mutating universe preview"
```

- [ ] **Step 6: Independent review** — Confirm all callees were defined earlier, Preview cannot write FORMAL history, diff is pure, the registry-owned evidence root is the production persistence owner, and fabricated in-memory results cannot enter the authoritative store or publish path. Record PASS before Task 14.

---

### Task 14: Registry-owned production publish authorization

**Files:**
- Modify: `src/tv_quant/pattern_finder/universe_foundation/registry.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Modify: `tests/pattern_finder/universe_foundation/test_registry.py`

**Interfaces:**
- Extends the existing `ProfileRegistry`, which remains the single profile/version owner, with its only publication method:

```python
publish(
    self,
    *,
    draft_id: str,
    preview_id: UUID,
    published_at_utc: datetime,
) -> UniverseProfile
```

- `ProfileRegistry` constructs its internal `PreviewEvidenceStore` only from `self.preview_evidence_root`; `publish()` reloads the stored Draft and authoritative `PreviewRecord` by ID. It accepts neither `PreviewResult` nor `PreviewRecord` from the caller and has no injected arbitrary-root store parameter.
- The registry fails closed unless the record exists and is uncorrupted; belongs to the exact stored Draft/family/parent; is COMPLETE with a PREVIEW Snapshot; has exact draft/profile/filter/evidence/version/snapshot hashes; still matches the current stored Draft and equals `latest_for_draft(draft_id)`; is not invalidated; contains all required candidates/batches/decisions/diff; has a non-empty change_note; differs from the latest family filter hash; and permits monotonic new-version allocation. These exact binding/latest/invalidation rules define stale Preview rejection; M3C-A adds no unstated time-to-live.
- Only after all checks does the same registry transaction append the Published Profile and close the draft. No public or private raw append path exists.

- [ ] **Step 1: RED** — Test direct production `publish()` calls cannot accept a caller-built `PreviewResult`/`PreviewRecord`; a fabricated internally self-consistent COMPLETE object or unpersisted ID cannot publish. Test missing/corrupt, incomplete/failed, stale, invalidated, superseded, wrong-draft/wrong-family/wrong-parent Preview Evidence; changed Draft after Preview; mismatched draft/filter/evidence/version/snapshot/content hashes; omitted required decisions/batches/diff; blank note; duplicate filter hash; replay and partial-write failure. Assert every rejection leaves Published and Draft state unchanged and no alternate append method exists. Test valid CORE:v2 and Custom:v1 while CORE:v1 remains byte-identical.
- [ ] **Step 2: Confirm RED** — Run `pytest tests/pattern_finder/universe_foundation/test_registry.py -q`; expect missing publish authorization.
- [ ] **Step 3: GREEN** — Implement authoritative record loading, freshness/invalidation/supersession/completeness/hash validation and transaction ordering inside the unique profile owner. The registry validates persisted production results; it does not rerun classification/evaluation or duplicate those rules in UI/a second profile owner.
- [ ] **Step 4: Regression** — Run `pytest tests/pattern_finder/universe_foundation/test_registry.py tests/pattern_finder/universe_foundation/test_preview.py tests/pattern_finder/universe_foundation/test_snapshots.py -q`, then mandatory Pattern Finder regression.
- [ ] **Step 5: Commit exact files**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation/__init__.py src/tv_quant/pattern_finder/universe_foundation/registry.py tests/pattern_finder/universe_foundation/test_registry.py
git commit -m "feat: authorize universe profile publication"
```

- [ ] **Step 6: Independent review** — Confirm `ProfileRegistry.publish()` is the unique production gate, the registry-private `PreviewEvidenceStore` rooted at `registry.preview_evidence_root` is the authoritative Preview Evidence persistence owner, and bypassing UI cannot publish fabricated, stale, wrong-profile, incomplete or hash-mismatched evidence. Record PASS before Task 15.

---

### Task 15: Draft, Preview, and Publish UI workflow

**Files:**
- Modify: `src/tv_quant/pattern_finder/universe_foundation/ui_read_model.py`
- Modify: `app/pages/3_Universe_Settings.py`
- Modify: `tests/pattern_finder/universe_foundation/test_ui_read_model.py`
- Modify: `tests/pattern_finder/test_universe_settings_page.py`
- Modify: `docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md`

**Interfaces:**
- Produces `DraftFormInput`, `PreviewUiState`, `build_draft_form_input(profile: UniverseProfile | UniverseDraft) -> DraftFormInput`, and `load_preview_ui_state(registry: ProfileRegistry, preview_id: UUID) -> PreviewUiState`.
- UI calls `ProfileRegistry` draft methods and Task 13 `ProfileRegistry.run_preview()`, reloads the authoritative record through `ProfileRegistry.get_preview(preview_id)`, and calls `ProfileRegistry.publish(draft_id=..., preview_id=..., published_at_utc=...)`. It never constructs a Preview store, submits a `PreviewResult`, writes Published storage, produces classification/evaluation, or decides completeness.
- Produces `render_profile_workflow(*, registry: ProfileRegistry, gateway_attempt: GatewayAttempt, snapshot_store: UniverseSnapshotStore, parent_snapshot: UniverseSnapshot | None) -> None`; all dependency types and store methods were produced by Tasks 2, 10, 11, 13, and 14. The page composes this function with the unchanged Task 3/7/12 renderers.

- [ ] **Step 1: RED** — Test clone/edit of Exchange, min/max Price, min/max Market Cap, minimum 20D Average Dollar Volume, minimum 20D Average Volume, minimum Listing History, Sector, Industry and ETF/ADR/OTC/Preferred/Warrant/Unit toggles; explicit deterministic Common Stock PASS and UNKNOWN/Quarantine fixture selection/injection; production evidence loading, classification, evaluation, funnel, Snapshot and persisted Preview Evidence; preview diff; UI reload by `preview_id`; incomplete/fabricated/stale/wrong-profile publish rejection from the registry; CORE:v2/Custom:v1 publication; parent immutability; duplicate rejection; rerun no implicit Futu call; and old Snapshot readability.
- [ ] **Step 2: Confirm RED** — Run `pytest tests/pattern_finder/universe_foundation/test_ui_read_model.py tests/pattern_finder/test_universe_settings_page.py -q`.
- [ ] **Step 3: GREEN** — Implement forms, explicit fixture/input selector, production pipeline invocation, authoritative Preview Evidence reload and production service errors/reason codes. UI projects only the persisted final production result: ticker/security, authoritative metric, actual value, threshold, evidence/source, PASS/FAIL/UNKNOWN, reason code, Quarantine, profile version and evidence version. Publish submits IDs only; button visibility/disabled state is presentation, not a security boundary.
- [ ] **Step 4: Regression** — Run mandatory Pattern Finder regression and page scan for evaluator/completeness/publication-storage logic.
- [ ] **Step 5: Commit exact files**

```powershell
git add app/pages/3_Universe_Settings.py src/tv_quant/pattern_finder/universe_foundation/ui_read_model.py tests/pattern_finder/universe_foundation/test_ui_read_model.py tests/pattern_finder/test_universe_settings_page.py docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md
git commit -m "feat: add versioned universe workflow"
```

- [ ] **Step 6: Independent review** — Confirm UI is not classification/evaluation/publication/completeness owner; fixture injection cannot bypass production evidence loading; UI reloads authoritative Preview Evidence; and all direct registry publish validation tests pass. Record PASS.
- [ ] **Step 7: First real Manual Functional Gate** — After commit and independent review PASS, use the page to select the deterministic Common Stock PASS fixture and the UNKNOWN/Quarantine fixture. For each, verify the complete `fixture/input → GatewayAttempt evidence → production classification → production evaluation → funnel/Snapshot → immutable PreviewRecord → UI reload` chain and record ticker/security, authoritative metric, actual value, threshold, evidence/source, PASS/FAIL/UNKNOWN, reason code, Quarantine, profile version and evidence version. Also record clone, Draft hash/change, Preview ID/content/evidence/snapshot hashes, completeness/funnel/diff, attempted incomplete/fabricated rejection, successful new version/hash, and unchanged parent/history. A FAIL blocks Task 16.
- [ ] **Step 8: Acceptance evidence record** — Label `FIRST_REAL_MANUAL_FUNCTIONAL_TEST_AFTER_TASK=15` and append selected fixture IDs/input hashes, exact parent/draft/Preview/evidence/snapshot/new-version hashes, expected/observed production fields, browser/page, timestamp, reviewer and PASS/FAIL. Only a complete PASS permits Task 16.

---

### Task 16: Future ScanBatch binding and architecture boundaries

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/scan_binding.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_scan_binding.py`
- Create: `tests/pattern_finder/test_universe_foundation_boundaries.py`

**Interfaces:**
- Produces `ScanUniverseBinding` and `bind_scan_universe(*, scan_batch_id: str, scan_as_of_session: date, profile: UniverseProfile, snapshot: UniverseSnapshot, freshness_policy: Callable[[date, date], bool]) -> ScanUniverseBinding` only; no scanner or persistence.

- [ ] **Step 1: RED** — Reject Draft, PREVIEW, INCOMPLETE, failed attempt, mismatched IDs/hashes/member count, stale evidence and as-of reversal. Add AST/import tests protecting Flat Base signature/schema/output and M3B fixtures.
- [ ] **Step 2: Confirm RED** — Run `pytest tests/pattern_finder/universe_foundation/test_scan_binding.py tests/pattern_finder/test_universe_foundation_boundaries.py -q`.
- [ ] **Step 3: GREEN** — Bind a Published Profile to one COMPLETE FORMAL Snapshot and frozen member hash only.
- [ ] **Step 4: Regression** — Run binding/boundary and mandatory Pattern Finder regression.
- [ ] **Step 5: Commit exact files**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation/__init__.py src/tv_quant/pattern_finder/universe_foundation/scan_binding.py tests/pattern_finder/universe_foundation/test_scan_binding.py tests/pattern_finder/test_universe_foundation_boundaries.py
git commit -m "feat: bind future scans to universe evidence"
```

- [ ] **Step 6: Independent review** — Confirm contract-only M3C-B boundary and unchanged Detector. Record PASS before Task 17.

---

### Task 17: Integrated M3C-A fixture acceptance and STOP line

**Files:**
- Create or Modify: `tests/pattern_finder/universe_foundation/conftest.py`
- Modify: `tests/pattern_finder/universe_foundation/test_profiles.py`
- Modify: `tests/pattern_finder/universe_foundation/test_evaluator.py`
- Modify: `tests/pattern_finder/universe_foundation/test_funnel.py`
- Modify: `tests/pattern_finder/universe_foundation/test_futu_adapter.py`
- Modify: `tests/pattern_finder/universe_foundation/test_futu_gateway.py`
- Modify: `tests/pattern_finder/universe_foundation/test_snapshots.py`
- Modify: `tests/pattern_finder/universe_foundation/test_registry.py`
- Modify: `tests/pattern_finder/test_universe_settings_page.py`
- Modify: `tests/pattern_finder/test_universe_foundation_boundaries.py`
- Modify: `docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md`

**Interfaces:**
- Consumes all prior M3C-A public interfaces; produces acceptance evidence only and no production subsystem.

- [ ] **Step 1: RED** — Freeze a provider-shaped cross-stage fixture covering all exchanges/OTC, exact/below numeric boundaries, every non-common type, unknown subtype, active states, evidence conflicts, raw Industry/Plate, missing critical evidence, member/FAIL/UNKNOWN/Quarantine, endpoint pages/batches and exact S0-S10 reconciliations/hashes/UI fields.
- [ ] **Step 2: Confirm RED** — Run focused acceptance tests; the only failure is the first newly added missing assertion. Any missing production behavior returns to its owning earlier task and review.
- [ ] **Step 3: GREEN/refactor** — Correct fixture/contracts only. Shared builders may enter `conftest.py`; no new production behavior or signature is authorized.
- [ ] **Step 4: Regressions**

```powershell
pytest tests/pattern_finder/universe_foundation tests/pattern_finder/test_universe_settings_page.py tests/pattern_finder/test_universe_foundation_boundaries.py -q
pytest tests/pattern_finder -q
pytest -q
```

- [ ] **Step 5: Scope and architecture checks**

```powershell
rg -n "request_history_kline|update_futu_csv|flat_base_scan_rows|detect_flat_base|duckdb|pyarrow|benchmark|pattern_instance|review_queue" src/tv_quant/pattern_finder/universe_foundation app/pages/3_Universe_Settings.py
rg -n "from .*universe_foundation|import .*universe_foundation" src/tv_quant/pattern_finder/flat_base.py
```

Expected: no executable M3C-B hydration/compute, detector call, Pattern/Review subsystem, or reverse dependency.

- [ ] **Step 6: Commit exact files**

```powershell
git add tests/pattern_finder/universe_foundation/conftest.py tests/pattern_finder/universe_foundation/test_profiles.py tests/pattern_finder/universe_foundation/test_registry.py tests/pattern_finder/universe_foundation/test_evaluator.py tests/pattern_finder/universe_foundation/test_funnel.py tests/pattern_finder/universe_foundation/test_futu_adapter.py tests/pattern_finder/universe_foundation/test_futu_gateway.py tests/pattern_finder/universe_foundation/test_snapshots.py tests/pattern_finder/test_universe_settings_page.py tests/pattern_finder/test_universe_foundation_boundaries.py docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md
git commit -m "test: freeze M3C-A universe acceptance"
```

- [ ] **Step 7: Independent final review** — Recheck Design coverage, dependency graph, signatures, unique owners, manual evidence, M3C-B boundary, regressions and exact staging. Record PASS.
- [ ] **Step 8: Final Manual Functional Gate** — Only after commit and independent final review PASS, rerun all UI scopes and sign each expected/observed row with evidence, timestamp and reviewer.
- [ ] **Step 9: Final acceptance record and STOP** — Record final PASS/FAIL. Stop after PASS; M3C-B remains unauthorized.

## Manual UI Gate matrix

| Gate | Earliest task | Scope | Required visible production output |
|---|---:|---|---|
| UI smoke | 3 | Profile page wiring only | initialized CORE:v1, conditions, hashes; explicitly no membership claim |
| Automated projection checkpoint | 7 | Prebuilt `EvaluationUiState` projection | visible per-security production-result fields; no end-to-end claim |
| Automated persisted-Snapshot checkpoint | 12 | Prebuilt persisted Snapshot projection | Liquidity, Listing History, Classification, UNKNOWN/Quarantine, raw Industry/Plate, snapshot/evidence; no production orchestration claim |
| First real Manual Functional Gate | 15 | selectable fixture/input → production evidence/classification/evaluation/funnel/Snapshot → authoritative Preview Evidence → UI; Draft → Preview ID → authorized publication | Common Stock PASS and UNKNOWN/Quarantine, every required decision/evidence/version field, draft/parent/Preview/evidence/snapshot hashes, completeness, diff, fabricated/incomplete rejection, immutable new version |
| Final | 17 | Integrated M3C-A | all prior gates rerun after final commit/review |

Every formal gate follows commit → independent review PASS → manual UI acceptance → evidence record. `FIRST_UI_SMOKE_AFTER_TASK=3`; `FIRST_REAL_MANUAL_FUNCTIONAL_TEST_AFTER_TASK=15`. Tasks 7 and 12 are automated projection checkpoints and cannot be reported as the first real manual functional test.

## Frozen Design §§1-29 to task coverage

| Design sections | Frozen responsibility | Plan owner |
|---|---|---|
| §§1-4 | goal, authoritative inputs, scope/prohibitions, selected architecture | Global constraints and STOP line |
| §§5-6 | terms, component ownership and dependency direction | Dependency rules; Tasks 1-16 |
| §§7-9 | Profile schema/hashes, exact CORE v1, Draft/CORE v2/Custom lifecycle | Tasks 1, 2, 14, 15 |
| §10 | candidate sources, enumeration, identity, formal as-of | Tasks 9, 10 |
| §§11-12 | authoritative Liquidity/Listing evidence, Decimal/cross-check/conflict rules | Tasks 4, 6, 10, 17 |
| §§13-15 | classification evidence, raw Industry/Plate, Active Status | Tasks 4, 5, 6, 10, 12 |
| §16 | fixed S0-S10 funnel and per-security decisions | Tasks 6, 8, 17 |
| §17 | complete immutable Snapshot, hashes and all candidates | Tasks 11, 12, 17 |
| §18 | future Scan Batch binding | Task 16 |
| §19 | non-mutating Preview and parent diff | Tasks 13, 15 |
| §20 | preflight, pagination, independent limits, atomic failure, stable blockers | Tasks 9, 10 |
| §21 | one-way Universe-to-Scanner boundary and unchanged Detector | Tasks 7, 12, 13, 16, 17 |
| §§22-23 | boundary matrix, reconciliation, audit samples and no silent deletion | Tasks 1, 4-13, 16, 17 |
| §24 | Profile/Draft/Preview/Publish page and failure experience | Tasks 3, 7, 12, 15 |
| §§25-26 | file boundaries and acceptance contract | Locked file map, Gate protocol, Tasks 1-17 |
| §27 | runtime blockers and known limitations | Tasks 5, 10, 17 and STOP line |
| §28 | Futu source/version qualification | Tasks 9, 10 |
| §29 | final immutable-profile/evidence/funnel conclusion | Definition of Done and Task 17 |

## Consistency review checklist

- [ ] Design §§1-29 each maps to a task or explicit Backlog item.
- [ ] Dependency order is acyclic: profiles/registry evidence-root reservation → evidence → classification/evaluator → UI projection/funnel → adapters/gateway → Snapshot Store → Preview Evidence Store/orchestration → publication → workflow/binding → acceptance.
- [ ] Every consumed interface is produced earlier; Task 11 defines every `UniverseSnapshotStore` method before Tasks 12/13, Task 13 defines every `PreviewEvidenceStore` method before Tasks 14/15, and no `from_source`, `evaluate_attempt`, `build_preview_snapshot`, undefined `latest/list/read`, or caller-trusted Preview publication reference exists.
- [ ] All constructor/test/example signatures match, including keyword-only Futu gateway construction.
- [ ] `ProfileRegistry.publish(draft_id, preview_id, published_at_utc)` is the sole production publication/completeness authorization owner; it loads authoritative immutable evidence from its registry-private Preview store at `preview_evidence_root`, UI submits IDs only, and no raw Published append or caller-built Preview trust path exists.
- [ ] Original Task 8 responsibilities are independently reviewable in Tasks 9 and 10 with separate RED/GREEN/review cycles.
- [ ] Formal manual gates occur only after commit and independent review PASS; Task 3 is smoke only, Tasks 7/12 are automated projection checkpoints, and Task 15 is the truthful first complete manual vertical slice.
- [ ] Every commit stages only exact current-task file paths; no directory-wide `git add` remains.
- [ ] No M3C-B hydration, detector execution, benchmark, Pattern/Review work or trading integration enters the plan.
- [ ] Placeholder and whitespace scan passes:

```powershell
$redFlags = @(
    ('T' + 'BD'), ('T' + 'ODO'), ('FIX' + 'ME'),
    ('implement' + ' later'), ('fill' + ' in'), ('NotImplemented' + 'Error'),
    ('Similar' + ' to Task'), ('appropriate' + ' error'), ('handle' + ' edge cases')
) -join '|'
rg -n $redFlags docs/superpowers/plans/2026-08-13-pattern-finder-m3c-a-universe-foundation-implementation-plan.md
git diff --check
```

Expected: no placeholder matches and no whitespace errors.

## M3C-A Definition of Done and STOP line

M3C-A is complete only after all focused, Pattern Finder and repository regressions PASS; every formal UI Gate and evidence record PASS; exact hashes/reconciliations are reproducible; independent final review PASS; and architecture/M3C-B boundary scans PASS.

After Task 17 final acceptance, STOP. M3C-B bulk history, local daily-bar ADV20, warm-cache/batch compute, detector benchmarking, Candidate Gallery, Pattern Instance, Review Queue, Historical T0, accounts, brokers, orders, webhook, options and Phase 2 require a separately approved Design/Plan cycle.
