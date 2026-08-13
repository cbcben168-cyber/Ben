# Pattern Finder M3C-A Universe Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every task ends at an independent-review STOP gate; do not begin the next task until that review is recorded PASS.

**Goal:** Implement the frozen M3C-A Universe Foundation contract: immutable versioned profiles, authoritative and auditable security evidence, deterministic fail-closed evaluation/funnel/snapshots, explicit future scan binding, and a minimal Pattern Finder page that displays production results and evidence without reimplementing decisions.

**Architecture:** Preserve `src/tv_quant/pattern_finder/universe.py` as the frozen M3B 100-symbol fixture/allowlist and add a sibling `src/tv_quant/pattern_finder/universe_foundation/` package. External adapters only collect facts; immutable domain models normalize them; pure evaluators produce field decisions; funnel/snapshot code aggregates and persists every PASS, FAIL, and UNKNOWN record; Streamlit reads a production-owned UI read model. M3C-B hydration, bulk detector compute, benchmarking, and local daily-bar liquidity computation remain outside this plan.

**Tech Stack:** Python 3, frozen `dataclasses`, `Decimal`, JSON/JSONL, `hashlib` through existing `tv_quant.run_manifest.canonical_hash`, Futu OpenAPI adapter boundary, Streamlit 1.59.1, pandas, pytest, `streamlit.testing.v1.AppTest`.

## Authoritative inputs

- Frozen Design: `docs/superpowers/specs/2026-08-11-pattern-finder-m3c-a-universe-foundation-design.md`
- Merged V3 Blueprint: `docs/superpowers/specs/2026-08-11-pattern-research-scale-review-product-blueprint-v3.md`
- Planning base: `d50f276a0760d1748517e3cdf7822dd3267a677a`
- Existing M3B compatibility surface: `src/tv_quant/pattern_finder/universe.py`, `src/tv_quant/pattern_finder/futu_service.py`, `src/tv_quant/pattern_finder/cache.py`
- Existing UI: `app/Home.py`, `app/pages/1_Today_Scan.py`, `app/pages/2_Chart_Review.py`

## Global constraints

- Treat the Design Spec as authoritative; this plan decomposes it but does not redesign it.
- Keep `src/tv_quant/pattern_finder/universe.py`, `PILOT_SYMBOLS`, `M3B_SYMBOLS`, `M3B_UNIVERSE`, and `futu_code()` behavior unchanged.
- CORE v1 is immutable and exactly: NYSE/NASDAQ/AMEX, `COMMON_STOCK`, price `>= 5.00 USD`, market cap `>= 1_000_000_000.00 USD`, `FUTU_AVG_TURNOVER_20D >= 20_000_000.00 USD`, `FUTU_LISTED_DAYS >= 250`, Sector/Industry `ALL`, all non-common toggles false, `active_only=true`.
- Use deterministic decimal strings constructed from source text. Do not construct `Decimal` from binary floats. Liquidity cross-check normalization is `quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)` with absolute tolerance `<= Decimal("0.01")`; relative tolerance is forbidden.
- The M3C-A authoritative liquidity value remains Futu Stock Screening V2 `AVG_TURNOVER(days=20)`. A future M3C-B cross-check can disagree and yield `LIQUIDITY_EVIDENCE_CONFLICT`, but cannot replace the authoritative metric.
- The M3C-A authoritative listing-history value remains Futu Stock Screening V2 `LISTED_DAYS`. `listing_date` is auxiliary and cannot produce a PASS. A reliable conflict yields `LISTING_HISTORY_CONFLICT` and UNKNOWN/Quarantine.
- Only explicit Security Master / Classification Evidence may produce `COMMON_STOCK` PASS. Name, ticker suffix, regex, and heuristic inference are prohibited; missing or conflicting subtype evidence yields `CLASSIFICATION_UNKNOWN`.
- CORE v1 has Sector/Industry `ALL`; persist raw Industry and Owner Plate evidence and keep `sector_mapping_version=None`. Do not invent a top-level sector mapping.
- Market Snapshot has its own maximum 400 securities/request and 60 requests/30 seconds. Owner Plate independently has maximum 200 securities/request and 10 requests/30 seconds. Never share or substitute the two policies.
- Persist deterministic content hashes separately from complete record/attempt hashes; include provenance and all evidence versions; formal evidence is immutable and append-only.
- UI code only formats and displays production read models. It must not compare thresholds, infer security type, change UNKNOWN to PASS/FAIL, recompute membership, or call `detect_flat_base()`.
- No production code may import from `app/`. `flat_base.py` must not import Universe Foundation modules.
- Do not implement M3C-B hydration, canonical daily-bar ADV20 computation, warm-cache/batch compute, 500/1000/2000/3000 benchmarks, Pattern Instance, Review Queue, Historical T0, or any Phase 2/account/order/webhook/options work.
- After each task: focused tests PASS, Pattern Finder regression PASS, independent review PASS, and—when a user-verifiable UI slice exists—manual Pattern Finder UI acceptance is recorded before the next related task.

## Locked file map

The existing module `src/tv_quant/pattern_finder/universe.py` cannot safely become a same-named package because current M3B production and tests import directly from it. Preserve it and create this sibling package:

```text
src/tv_quant/pattern_finder/universe_foundation/
  __init__.py               public M3C-A exports only
  profiles.py               immutable filters/profile/draft and canonical hashes
  registry.py               append-only draft/published/availability registry
  evidence.py               raw/normalized evidence and provenance value objects
  security_master.py        classification evidence provider Protocol and ledger
  classification.py         fail-closed subtype resolution
  evaluator.py              pure field decisions and final per-security evaluation
  funnel.py                 fixed S0-S10 reconciliation
  futu_gateway.py           collection-only Futu adapter and independent rate policies
  snapshots.py              deterministic snapshot payloads and append-only store
  preview.py                non-formal preview orchestration and diff
  scan_binding.py           future ScanBatch binding contract only
  ui_read_model.py          production-owned UI projection; no Streamlit imports

app/pages/3_Universe_Settings.py
tests/pattern_finder/universe_foundation/
  test_profiles.py
  test_registry.py
  test_evidence.py
  test_classification.py
  test_evaluator.py
  test_funnel.py
  test_futu_gateway.py
  test_snapshots.py
  test_preview.py
  test_scan_binding.py
  test_ui_read_model.py
tests/pattern_finder/test_universe_settings_page.py
tests/pattern_finder/test_universe_foundation_boundaries.py
docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md
```

The repository currently uses `app/pages/` with explicit `st.navigation`; keep that established path for this one-page increment. Migrating the entire app to `app_pages/` is unrelated refactoring and belongs in Backlog.

## Spec-to-task coverage

| Frozen Design contract | Owning task(s) | Acceptance evidence |
|---|---|---|
| Profile schema, CORE v1, Decimal/hash rules | 1 | exact field/hash tests; Gate 1 |
| Draft, CORE v2/Custom, availability, immutability | 2, 12 | registry tests; Gate 3 |
| Evidence/provenance/raw Industry/Plate | 4 | evidence tests; Gate 2D |
| Security Master port; no heuristic PASS; fail-closed | 5 | classification tests; provider qualification record; Gate 2C |
| Liquidity authority, half-even cents, one-cent tolerance | 4, 6 | fractional-cent/tolerance tests; Gate 2A |
| Listing authority, listing-date auxiliary, conflict | 6 | 250/249/auxiliary/conflict tests; Gate 2B |
| Sector/Industry ALL and no mapping | 1, 4, 6 | profile/evidence/evaluator tests; Gate 2D |
| Active status and unknown provider enums | 6, 8 | evaluator/gateway contract tests |
| S0-S10 funnel and identity reconciliation | 7 | reconciliation/hash tests; Gate 2E |
| Futu discovery/screen/snapshot/plate, pagination/limits | 8 | fake adapter tests plus live-source qualification |
| All-candidate snapshot, content/record hashes, append-only | 9 | snapshot tamper/determinism tests; Gate 2E |
| Scan Batch binding without scanner implementation | 13 | binding/boundary tests |
| Preview non-mutation and parent diff | 11, 12 | store-state tests; Gate 3 |
| Minimal UI and required decision evidence fields | 3, 10, 12 | AppTest plus Gates 1-3 |
| Detector separation and M3B regression | 6, 10, 13, 14 | AST/import/output regressions |
| Full acceptance and “no silent deletion” sampling | 14 | integrated fixture, final manual record, final review |

## Gate protocol used after every task

1. Run the task's focused RED test and record the expected failure.
2. Implement only the task's GREEN surface.
3. Run focused tests and the stated Pattern Finder regression.
4. REFACTOR without changing the frozen public signatures; rerun both suites.
5. Commit only the task files with the stated commit message.
6. STOP and request independent review of that commit. Record PASS before continuing.
7. If the task has a Manual UI Gate, run the page against deterministic fixture evidence, record the observations in the acceptance record, obtain human PASS, and only then continue.

The mandatory regression command after GREEN and again after REFACTOR for **every** task is:

```powershell
pytest tests/pattern_finder -q
```

Narrower commands inside each task are its focused tests; they never replace this regression.

---

### Task 1: Immutable CORE v1 profile and canonical hashes

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `src/tv_quant/pattern_finder/universe_foundation/profiles.py`
- Create: `tests/pattern_finder/universe_foundation/test_profiles.py`
- Preserve unchanged: `src/tv_quant/pattern_finder/universe.py`

**Interfaces:**
- Produces: `UniverseFilters`, `UniverseProfile`, `UniverseDraft`, `ProfileKind`, `RecordState`, `Exchange`, `SecurityClass`, `core_v1() -> UniverseProfile`.
- Produces: `canonical_filter_payload(filters: UniverseFilters) -> dict[str, object]`, `filter_content_sha256(filters: UniverseFilters) -> str`, `profile_content_sha256(profile: UniverseProfile) -> str`, `draft_content_sha256(draft: UniverseDraft) -> str`.
- Invariant: `UniverseProfile` and nested collections are deeply immutable; published hashes are lowercase 64-character SHA-256 values.

Exact model constructors:

```python
UniverseProfile(
    profile_family_id: str, profile_version: int, profile_version_id: str,
    profile_kind: ProfileKind, display_name: str, schema_version: str,
    record_state: RecordState, parent_profile_version_id: str | None,
    created_at_utc: datetime, published_at_utc: datetime,
    change_note: str, filters: UniverseFilters,
    content_sha256: str, filter_content_sha256: str,
)

UniverseDraft(
    draft_id: str, profile_family_id: str, profile_kind: ProfileKind,
    display_name: str, parent_profile_version_id: str | None,
    created_at_utc: datetime, change_note: str, filters: UniverseFilters,
    draft_content_sha256: str,
)
```

- [ ] **Step 1: Write the failing profile contract tests (RED)**

```python
def test_core_v1_is_exactly_the_frozen_contract() -> None:
    profile = core_v1()
    assert profile.profile_version_id == "CORE:v1"
    assert profile.record_state is RecordState.PUBLISHED
    assert profile.filters.exchanges == frozenset({Exchange.NYSE, Exchange.NASDAQ, Exchange.AMEX})
    assert profile.filters.allowed_security_classes == frozenset({SecurityClass.COMMON_STOCK})
    assert profile.filters.min_price_usd == Decimal("5.00")
    assert profile.filters.min_market_cap_usd == Decimal("1000000000.00")
    assert profile.filters.liquidity_metric_id == "FUTU_AVG_TURNOVER_20D"
    assert profile.filters.min_avg_dollar_volume_20d_usd == Decimal("20000000.00")
    assert profile.filters.listing_history_metric_id == "FUTU_LISTED_DAYS"
    assert profile.filters.min_listed_days == 250
    assert profile.filters.sectors is ALL
    assert profile.filters.industries is ALL
    assert profile.filters.sector_mapping_version is None
```

Add explicit tests that collection order does not change either hash; `bool` cannot satisfy integer fields; NaN, Infinity, empty strings, inverted min/max, mixed `ALL` plus values, and direct mutation are rejected; changing only family/version changes `content_sha256` but not `filter_content_sha256`.

- [ ] **Step 2: Run the focused test and verify the expected import failure**

```powershell
pytest tests/pattern_finder/universe_foundation/test_profiles.py -q
```

Expected: FAIL because `tv_quant.pattern_finder.universe_foundation.profiles` does not exist.

- [ ] **Step 3: Implement the minimal frozen profile model (GREEN)**

```python
@dataclass(frozen=True, slots=True)
class UniverseFilters:
    exchanges: frozenset[Exchange]
    allowed_security_classes: frozenset[SecurityClass]
    min_price_usd: Decimal | None
    max_price_usd: Decimal | None
    min_market_cap_usd: Decimal | None
    max_market_cap_usd: Decimal | None
    liquidity_metric_id: str
    liquidity_evidence_version: str
    min_avg_dollar_volume_20d_usd: Decimal | None
    min_avg_volume_20d_shares: Decimal | None
    listing_history_metric_id: str
    listing_history_evidence_version: str
    min_listed_days: int | None
    sectors: _All | frozenset[str]
    industries: _All | frozenset[str]
    sector_mapping_version: str | None
    include_etf: bool
    include_adr: bool
    include_otc: bool
    include_preferred: bool
    include_warrant: bool
    include_unit: bool
    active_only: bool

def core_v1() -> UniverseProfile:
    return CORE_V1

def filter_content_sha256(filters: UniverseFilters) -> str:
    return canonical_hash(canonical_filter_payload(filters))

def profile_content_sha256(profile: UniverseProfile) -> str:
    return canonical_hash(canonical_profile_content_payload(profile))

def draft_content_sha256(draft: UniverseDraft) -> str:
    return canonical_hash(canonical_filter_payload(draft.filters))
```

Use `tv_quant.run_manifest.canonical_hash`; canonicalize all amounts as non-exponent decimal strings and all sets in stable enum/string order.

- [ ] **Step 4: Run GREEN tests and M3B compatibility regression**

```powershell
pytest tests/pattern_finder/universe_foundation/test_profiles.py tests/pattern_finder/test_universe.py -q
```

Expected: PASS; the original 100-symbol M3B universe remains byte-for-byte untouched.

- [ ] **Step 5: REFACTOR and verify public exports**

```python
from .profiles import (
    Exchange, ProfileKind, RecordState, SecurityClass,
    UniverseDraft, UniverseFilters, UniverseProfile, core_v1,
)
```

Run: `pytest tests/pattern_finder/universe_foundation/test_profiles.py tests/pattern_finder/test_universe.py -q`.

- [ ] **Step 6: Commit and STOP for independent review**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation tests/pattern_finder/universe_foundation/test_profiles.py
git commit -m "feat: freeze M3C-A universe profile contract"
```

Independent review must confirm exact CORE values, Decimal-only hashing, no M3B changes, and no M3C-B behavior. STOP until PASS.

---

### Task 2: Append-only profile draft, publication, and availability registry

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/registry.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_registry.py`

**Interfaces:**
- Consumes: Task 1 profile types and hash functions.
- Produces: `ProfileAvailabilityAction`, `ProfileAvailabilityEvent`, `ProfileRegistryError`.
- Produces: `ProfileRegistry(root: str | Path)`, `create_draft(*, draft_id: str, family_id: str, display_name: str, change_note: str, source_profile_version_id: str | None) -> UniverseDraft`, `save_draft(draft: UniverseDraft) -> None`, `publish(draft_id: str, *, published_at_utc: datetime) -> UniverseProfile`, `record_availability(event: ProfileAvailabilityEvent) -> None`, `get_published(profile_version_id: str) -> UniverseProfile`, `list_published(family_id: str | None = None) -> tuple[UniverseProfile, ...]`.

- [ ] **Step 1: Write transactional versioning tests (RED)**

```python
def test_publish_creates_core_v2_without_mutating_core_v1(tmp_path: Path) -> None:
    registry = ProfileRegistry(tmp_path)
    registry.bootstrap(core_v1())
    before = registry.get_published("CORE:v1")
    draft = registry.create_draft(
        draft_id="draft-core-v2",
        family_id="CORE",
        display_name="CORE",
        change_note="raise liquidity floor",
        source_profile_version_id="CORE:v1",
    )
    registry.save_draft(replace(draft, filters=replace(draft.filters, min_avg_dollar_volume_20d_usd=Decimal("25000000.00"))))
    published = registry.publish("draft-core-v2", published_at_utc=NOW)
    assert published.profile_version_id == "CORE:v2"
    assert registry.get_published("CORE:v1") == before
```

Add these exact tests: `test_publish_rejects_duplicate_filter_hash_despite_metadata_changes`; `test_family_versions_are_monotonic`; `test_first_custom_publish_uses_stable_slug_v1`; `test_published_profile_has_no_update_operation`; `test_availability_events_append_without_mutating_profile`; `test_corrupt_or_truncated_registry_line_fails_closed`.

- [ ] **Step 2: Verify RED**

```powershell
pytest tests/pattern_finder/universe_foundation/test_registry.py -q
```

Expected: FAIL because `ProfileRegistry` does not exist.

- [ ] **Step 3: Implement the registry (GREEN)**

```python
class ProfileRegistry:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.published_path = self.root / "published_profiles.jsonl"
        self.availability_path = self.root / "profile_availability.jsonl"

    def bootstrap(self, profile: UniverseProfile) -> None:
        if not self.published_path.exists():
            _append_jsonl(self.published_path, _profile_to_payload(profile))

    def create_draft(self, *, draft_id: str, family_id: str, display_name: str,
                     change_note: str,
                     source_profile_version_id: str | None) -> UniverseDraft:
        source = self.get_published(source_profile_version_id) if source_profile_version_id else None
        return UniverseDraft.from_source(
            draft_id=draft_id, family_id=family_id, display_name=display_name,
            change_note=change_note, source=source,
        )
```

Use separate append-only JSONL ledgers for published versions and availability events; drafts may use atomic replacement because they are explicitly non-formal. On publication, lock the family, recompute hashes, compare the latest filter hash, allocate max+1, append, flush/fsync, and never rewrite prior lines.

- [ ] **Step 4: Run focused and Pattern Finder regressions**

```powershell
pytest tests/pattern_finder/universe_foundation/test_profiles.py tests/pattern_finder/universe_foundation/test_registry.py tests/pattern_finder/test_validation.py -q
```

Expected: PASS.

- [ ] **Step 5: REFACTOR serialization into private typed helpers**

```python
def _append_jsonl(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
```

`_profile_to_payload()` must emit every dataclass field using the same canonical decimal/set rules from Task 1. `_profile_from_payload()` must require that exact field set, reconstruct the frozen types, and recompute both hashes before accepting a line. `publish()` executes under the family lock: read all published rows, select the family max version, reject an equal latest filter hash, build max+1, recompute/validate hashes, append once, fsync, and close the draft.

Rerun the same focused/regression command.

- [ ] **Step 6: Commit and STOP for independent review**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation tests/pattern_finder/universe_foundation/test_registry.py
git commit -m "feat: add immutable universe profile registry"
```

Review must confirm empty-version rejection uses `filter_content_sha256`, publication cannot mutate CORE v1, and drafts cannot masquerade as published versions. STOP until PASS.

---

### Task 3: Minimal Universe/Profile status page and first manual gate

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/ui_read_model.py`
- Create: `app/pages/3_Universe_Settings.py`
- Modify: `app/Home.py`
- Create: `tests/pattern_finder/universe_foundation/test_ui_read_model.py`
- Create: `tests/pattern_finder/test_universe_settings_page.py`
- Create: `docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md`

**Interfaces:**
- Consumes: `ProfileRegistry` and immutable profiles.
- Produces: `ProfileUiState`, `ProfileConditionRow`, `load_profile_ui_state(registry: ProfileRegistry, profile_version_id: str) -> ProfileUiState`.
- UI contract: `app/pages/3_Universe_Settings.py` imports read models only; it performs no threshold comparison or hashing.

- [ ] **Step 1: Write read-model and AppTest failures (RED)**

```python
def test_profile_ui_state_exposes_version_metric_threshold_and_hash(registry: ProfileRegistry) -> None:
    state = load_profile_ui_state(registry, "CORE:v1")
    assert state.profile_version_id == "CORE:v1"
    assert state.profile_content_sha256 == registry.get_published("CORE:v1").content_sha256
    assert any(row.metric_id == "FUTU_AVG_TURNOVER_20D" and row.threshold == ">= 20000000.00 USD" for row in state.conditions)

def test_universe_settings_page_renders_production_profile(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PATTERN_FINDER_UNIVERSE_ROOT", str(tmp_path))
    app = AppTest.from_file(ROOT / "app/pages/3_Universe_Settings.py").run()
    assert not app.exception
    assert "CORE:v1" in visible_text(app)
    assert "FUTU_AVG_TURNOVER_20D" in visible_text(app)
```

- [ ] **Step 2: Verify RED**

```powershell
pytest tests/pattern_finder/universe_foundation/test_ui_read_model.py tests/pattern_finder/test_universe_settings_page.py -q
```

Expected: FAIL because the read model and page do not exist.

- [ ] **Step 3: Implement production projection and read-only page (GREEN)**

```python
@dataclass(frozen=True, slots=True)
class ProfileConditionRow:
    field_id: str
    metric_id: str
    operator: str
    threshold: str
    evidence_version: str | None

def load_profile_ui_state(
    registry: ProfileRegistry, profile_version_id: str
) -> ProfileUiState:
    profile = registry.get_published(profile_version_id)
    return ProfileUiState.from_profile(profile)
```

Add a `st.Page("pages/3_Universe_Settings.py", title="股票池设置", icon=":material/filter_alt:")` entry. Render `CORE:v1`, published state, content hash, filter hash, change note, and every frozen condition using `st.dataframe`. Do not add custom CSS, deprecated `use_container_width`, or business comparisons.

- [ ] **Step 4: Run focused tests and existing page regression**

```powershell
pytest tests/pattern_finder/universe_foundation/test_ui_read_model.py tests/pattern_finder/test_universe_settings_page.py tests/pattern_finder/test_pages.py -q
```

Expected: PASS; Today Scan and Chart Review semantics remain unchanged.

- [ ] **Step 5: REFACTOR UI to keep all data construction out of Streamlit**

```python
state = load_profile_ui_state(
    ProfileRegistry(os.environ.get("PATTERN_FINDER_UNIVERSE_ROOT", DEFAULT_UNIVERSE_ROOT)),
    "CORE:v1",
)
st.dataframe([asdict(row) for row in state.conditions], hide_index=True)
```

Rerun the focused/regression command.

- [ ] **Step 6: Manual UI Gate 1 — Universe/Profile basic state**

```powershell
streamlit run app/Home.py
```

Human must open **股票池设置** and record: input/profile `CORE:v1`; published result; every metric and threshold; evidence version; content/filter hashes; `sector_mapping_version=null`; and that no membership claim appears before evidence exists. Record browser URL, timestamp, observed values, screenshots/notes, and PASS/FAIL in the acceptance file.

- [ ] **Step 7: Commit and STOP for independent review + human acceptance**

```powershell
git add app/Home.py app/pages/3_Universe_Settings.py src/tv_quant/pattern_finder/universe_foundation tests/pattern_finder docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md
git commit -m "feat: show M3C-A universe profile status"
```

`FIRST_MANUAL_TEST_AFTER_TASK = 3`. Do not start Task 4 until automated tests, independent review, and Manual UI Gate 1 are PASS.

---

### Task 4: Immutable evidence, provenance, raw Industry/Plate, and numeric normalization

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/evidence.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_evidence.py`

**Interfaces:**
- Produces shared enums/value objects used from Task 4 onward: `Decision(PASS, FAIL, UNKNOWN, NOT_APPLICABLE)`, `AttemptStatus`, `Completeness`, `EvidenceReference`.
- Produces: `EvidenceProvenance`, `RawIndustryEvidence`, `RawPlateEvidence`, `SecurityClassificationEvidence`, `LiquidityEvidence`, `ListingHistoryEvidence`, `UniverseSecurityEvidence`.
- Produces: `decimal_from_source(value: str, *, field_id: str, allow_negative: bool = False) -> Decimal`, `quantize_usd_cent(value: str, *, field_id: str) -> Decimal`, `evidence_record_sha256(evidence: UniverseSecurityEvidence) -> str`.

- [ ] **Step 1: Write evidence parsing and immutability tests (RED)**

```python
@pytest.mark.parametrize(("source", "expected"), [
    ("0.004", Decimal("0.00")),
    ("0.005", Decimal("0.00")),
    ("0.006", Decimal("0.01")),
    ("0.015", Decimal("0.02")),
])
def test_usd_cent_normalization_is_half_even(source: str, expected: Decimal) -> None:
    assert quantize_usd_cent(source, field_id="turnover") == expected
```

Add these exact tests: `test_decimal_source_rejects_binary_float`; `test_decimal_source_rejects_negative_nan_infinity_and_blank`; `test_evidence_timestamp_requires_utc`; `test_raw_industry_and_every_plate_round_trip_with_source_version_and_hash`; `test_provenance_change_changes_record_hash`; `test_evidence_is_deeply_immutable`.

- [ ] **Step 2: Verify RED**

```powershell
pytest tests/pattern_finder/universe_foundation/test_evidence.py -q
```

- [ ] **Step 3: Implement typed evidence (GREEN)**

```python
@dataclass(frozen=True, slots=True)
class EvidenceProvenance:
    provider: str
    interface: str
    source_version: str
    observed_at_utc: datetime
    source_record_sha256: str
    request_id: str
    response_sha256: str

@dataclass(frozen=True, slots=True)
class EvidenceReference:
    provider: str
    interface: str
    source_version: str
    source_record_sha256: str
    observed_at_utc: datetime

@dataclass(frozen=True, slots=True)
class UniverseSecurityEvidence:
    stock_id: str
    futu_code: str
    symbol: str
    name: str
    exchange_raw: str | None
    security_type_raw: str | None
    delisting: bool | None
    suspension: bool | None
    sec_status_raw: str | None
    price_usd: Decimal | None
    market_cap_usd: Decimal | None
    liquidity: LiquidityEvidence | None
    listing_history: ListingHistoryEvidence | None
    classifications: tuple[SecurityClassificationEvidence, ...]
    raw_industry: RawIndustryEvidence | None
    raw_plates: tuple[RawPlateEvidence, ...]
    provenance: tuple[EvidenceProvenance, ...]
```

- [ ] **Step 4: Run focused and canonical-hash regression**

```powershell
pytest tests/pattern_finder/universe_foundation/test_evidence.py tests/contracts/test_numeric_canonicalization.py tests/pipeline/test_run_manifest.py -q
```

- [ ] **Step 5: REFACTOR shared validation without weakening types**

```python
def _require_utc(value: datetime, field_id: str) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_id} must be UTC")
    return value

def _require_sha256(value: str, field_id: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field_id} must be lowercase sha256")
    return value
```

Sort evidence collections at construction by explicit stable keys (`source_version`, `source_record_sha256`, plate code/type); never rely on input order.

Rerun the same command.

- [ ] **Step 6: Commit and STOP for independent review**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation tests/pattern_finder/universe_foundation/test_evidence.py
git commit -m "feat: add immutable universe evidence models"
```

Review must verify Decimal source-string construction, fractional-cent boundaries, raw Industry/Plate preservation, provenance, and no network/business logic in evidence types. STOP until PASS.

---

### Task 5: Security Master port and fail-closed classification

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/security_master.py`
- Create: `src/tv_quant/pattern_finder/universe_foundation/classification.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_classification.py`

**Interfaces:**
- Consumes: `SecurityClassificationEvidence` from Task 4.
- Produces: `SecurityMasterProvider(Protocol)` with `classification_evidence(self, stock_id: str, futu_code: str, as_of_utc: datetime) -> tuple[SecurityClassificationEvidence, ...]`.
- Produces: `AppendOnlyClassificationLedger.append(evidence: SecurityClassificationEvidence) -> None`, `.get(stock_id: str, *, as_of_utc: datetime) -> tuple[SecurityClassificationEvidence, ...]`.
- Produces: `ClassificationResult(normalized_class: SecurityClass, decision: Decision, reason_code: str, evidence_refs: tuple[str, ...])` and `resolve_classification(top_level_futu_type: str | None, evidence: Sequence[SecurityClassificationEvidence]) -> ClassificationResult`.

- [ ] **Step 1: Write prohibited-heuristic and evidence hierarchy tests (RED)**

```python
@pytest.mark.parametrize("symbol,name", [
    ("ABC.W", "ABC Common Stock"),
    ("XYZ.P", "XYZ Preferred"),
    ("FOOU", "Foo Units"),
    ("ADR", "Depositary Shares"),
])
def test_name_ticker_suffix_and_regex_cannot_create_core_pass(symbol: str, name: str) -> None:
    result = resolve_classification("STOCK", ())
    assert result.decision is Decision.UNKNOWN
    assert result.reason_code == "CLASSIFICATION_UNKNOWN"
```

Add these exact tests: `test_explicit_futu_etf_warrant_and_bwrt_are_non_common_failures`; `test_futu_stock_alone_is_classification_unknown`; `test_explicit_authoritative_or_corroborated_common_subtype_passes`; `test_conflicting_subtype_sources_are_ambiguous_unknown`; `test_manual_evidence_requires_locator_hash_time_and_verifier`; `test_classification_ledger_appends_correction_without_overwrite`.

- [ ] **Step 2: Verify RED**

```powershell
pytest tests/pattern_finder/universe_foundation/test_classification.py -q
```

- [ ] **Step 3: Implement the port, ledger, and resolver (GREEN)**

```python
class SecurityMasterProvider(Protocol):
    def classification_evidence(
        self, stock_id: str, futu_code: str, as_of_utc: datetime
    ) -> tuple[SecurityClassificationEvidence, ...]:
        """Return explicit subtype records valid at as_of_utc."""

def resolve_classification(
    top_level_futu_type: str | None,
    evidence: Sequence[SecurityClassificationEvidence],
) -> ClassificationResult:
    if top_level_futu_type in EXPLICIT_NON_STOCK_TYPES:
        return ClassificationResult.from_futu_non_stock(top_level_futu_type)
    conclusions = _authoritative_conclusions(evidence)
    if conclusions == frozenset({SecurityClass.COMMON_STOCK}):
        return ClassificationResult.common_stock_pass(evidence)
    return ClassificationResult.classification_unknown(evidence)
```

Do not include `symbol`, `name`, suffix, regex, or free-text parsing parameters in `resolve_classification`; this makes the prohibition structural rather than conventional.

- [ ] **Step 4: Run focused and M3B regression tests**

```powershell
pytest tests/pattern_finder/universe_foundation/test_classification.py tests/pattern_finder/test_universe.py tests/pattern_finder/test_futu_service.py -q
```

- [ ] **Step 5: REFACTOR conflict resolution into deterministic source ordering**

```python
def _authoritative_conclusions(
    evidence: Sequence[SecurityClassificationEvidence],
) -> frozenset[SecurityClass]:
    return frozenset(
        item.normalized_class for item in evidence
        if item.confidence in {EvidenceConfidence.AUTHORITATIVE, EvidenceConfidence.CORROBORATED}
    )
```

Rerun the same command and scan the module for `regex`, `re.`, `suffix`, `name` decision logic; expected: none.

- [ ] **Step 5A: Qualify the actual Security Master source or record a blocker**

In the acceptance record, name the exact available source/dataset, version/as-of, issue-subtype field, original record locator, licensing/redistribution constraint, and a frozen sample containing Common, ADR, Preferred, and Unit. Verify that subtype is explicit—not inferred from name/ticker—and recompute each source record SHA. If no candidate meets this contract, record `CLASSIFICATION_EVIDENCE_BLOCKER`; keep those equities UNKNOWN/Quarantine and prohibit a live all-market FORMAL CORE snapshot. Do not weaken the resolver or substitute heuristics.

- [ ] **Step 6: Commit and STOP for independent review**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation tests/pattern_finder/universe_foundation/test_classification.py
git commit -m "feat: add fail-closed security classification"
```

Review must confirm no heuristic can yield CORE PASS and authoritative provider selection remains behind the port. STOP until PASS.

---

### Task 6: Pure field evaluator, liquidity/listing boundaries, and Quarantine

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/evaluator.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_evaluator.py`

**Interfaces:**
- Consumes: Task 4 `Decision`, `UniverseProfile`, `UniverseSecurityEvidence`, `ClassificationResult`.
- Produces: `FieldDecision`, `SecurityEvaluation`.
- Produces: `compare_liquidity_cross_check(authoritative_source: str, cross_check_source: str) -> FieldDecision`, `evaluate_security(profile: UniverseProfile, evidence: UniverseSecurityEvidence, classification: ClassificationResult) -> SecurityEvaluation`.

- [ ] **Step 1: Write the full boundary matrix (RED)**

```python
@pytest.mark.parametrize(("value", "expected"), [
    ("20000000.00", Decision.PASS),
    ("19999999.99", Decision.FAIL),
])
def test_authoritative_futu_avg_turnover_20d_uses_closed_threshold(value, expected):
    result = evaluate_security(
        core_v1(), evidence_with(avg_turnover_20d_usd=value), common_stock_pass()
    )
    assert result.decision_for("liquidity").decision is expected

@pytest.mark.parametrize(("listed_days", "expected"), [(250, Decision.PASS), (249, Decision.FAIL)])
def test_futu_listed_days_uses_closed_threshold(listed_days, expected):
    result = evaluate_security(
        core_v1(), evidence_with(listed_days=listed_days), common_stock_pass()
    )
    assert result.decision_for("listing_history").decision is expected
```

Implement the parameterized tests `test_price_boundary_5_00_passes_4_99_fails`, `test_market_cap_boundary_1b_passes_one_cent_below_fails`, `test_nyse_nasdaq_amex_pass_and_otc_fails`, `test_explicit_non_common_classes_fail`, `test_active_delisted_suspended_and_new_status_are_distinct`, `test_each_missing_critical_field_is_unknown`, `test_sector_industry_all_passes_while_raw_metadata_is_preserved`, and `test_first_exit_and_quarantine_follow_fixed_stage_order`.

Add exact liquidity cross-check tests:

```python
def test_cross_check_absolute_cent_tolerance_is_inclusive() -> None:
    assert compare_liquidity_cross_check("20000000.004", "20000000.014").decision is Decision.PASS

def test_cross_check_more_than_one_cent_is_conflict() -> None:
    result = compare_liquidity_cross_check("20000000.004", "20000000.015")
    assert result.decision is Decision.UNKNOWN
    assert result.reason_code == "LIQUIDITY_EVIDENCE_CONFLICT"
```

Assert `metric_id="FUTU_AVG_TURNOVER_20D"`, threshold `>= 20000000.00 USD`, evidence version, normalized value, source/ref, and no relative tolerance field.

`test_listing_date_missing_or_invalid_is_auxiliary_only` must assert the `LISTED_DAYS` 250/249 result is unchanged and adds `LISTING_DATE_AUXILIARY_INVALID`; `test_reliable_listing_cross_check_conflict_quarantines` must assert `LISTING_HISTORY_CONFLICT`, UNKNOWN, and `is_quarantined=True`.

- [ ] **Step 2: Verify RED**

```powershell
pytest tests/pattern_finder/universe_foundation/test_evaluator.py -q
```

- [ ] **Step 3: Implement pure evaluation (GREEN)**

```python
@dataclass(frozen=True, slots=True)
class FieldDecision:
    field_id: str
    metric_id: str
    raw_value: str | None
    normalized_value: str | None
    operator: str
    threshold: str | None
    decision: Decision
    reason_code: str
    evidence_source: str | None
    evidence_observed_at_utc: datetime | None
    evidence_version: str | None
    evidence_refs: tuple[str, ...]

def evaluate_security(
    profile: UniverseProfile,
    evidence: UniverseSecurityEvidence,
    classification: ClassificationResult,
) -> SecurityEvaluation:
    decisions = _evaluate_all_fields(profile.filters, evidence, classification)
    return SecurityEvaluation.from_field_decisions(evidence, decisions)
```

Compute every independent field decision even after an earlier failure; use fixed stage order only to derive `first_exit_stage`, `first_exit_reason`, `is_member`, and `is_quarantined`.

- [ ] **Step 4: Run focused and Flat Base regression**

```powershell
pytest tests/pattern_finder/universe_foundation/test_evaluator.py tests/pattern_finder/test_flat_base.py tests/pattern_finder/test_pattern_review_regression.py -q
```

- [ ] **Step 5: REFACTOR comparisons into small typed helpers**

```python
def _minimum_decimal_decision(
    *, field_id: str, metric_id: str, value: Decimal | None,
    minimum: Decimal | None, evidence_ref: EvidenceReference | None,
) -> FieldDecision:
    """Return NOT_APPLICABLE, UNKNOWN, PASS, or FAIL without source conversion."""

def _minimum_integer_decision(
    *, field_id: str, metric_id: str, value: int | None,
    minimum: int | None, evidence_ref: EvidenceReference | None,
) -> FieldDecision:
    """Use an inclusive integer minimum and preserve the evidence reference."""

def _active_status_decision(evidence: UniverseSecurityEvidence) -> FieldDecision:
    """Fail known inactive states and return UNKNOWN for absent/new provider states."""
```

Rerun the same command; verify evaluator has no Futu SDK, filesystem, Streamlit, or detector imports.

- [ ] **Step 6: Commit and STOP for independent review**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation tests/pattern_finder/universe_foundation/test_evaluator.py
git commit -m "feat: evaluate CORE universe evidence deterministically"
```

Review must explicitly sign off the authoritative metrics, ROUND_HALF_EVEN/tolerance boundaries, listing-date auxiliary behavior, classification fail-closed behavior, and Sector=ALL evidence-only rule. STOP until PASS.

---

### Task 7: Fixed S0-S10 funnel reconciliation

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/funnel.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_funnel.py`

**Interfaces:**
- Consumes: `Sequence[SecurityEvaluation]`.
- Produces: `FunnelStage`, `UniverseFunnel`, `build_funnel(evaluations: Sequence[SecurityEvaluation]) -> UniverseFunnel`, `funnel_sha256(funnel: UniverseFunnel) -> str`.
- Fixed stage IDs: `S0 DISCOVERED_US_CASH_SECURITIES` through `S10 CORE_UNIVERSE`, exactly as frozen in Design §16.

- [ ] **Step 1: Write reconciliation and determinism tests (RED)**

```python
def test_every_stage_reconciles_and_members_equal_s10_output(evaluations) -> None:
    funnel = build_funnel(evaluations)
    for current, following in pairwise(funnel.stages):
        assert current.input_count == current.pass_count + current.fail_count + current.unknown_count
        assert current.output_count == current.pass_count
        assert following.input_count == current.output_count
    assert funnel.stages[-1].output_count == len(funnel.member_stock_ids)
```

Add `test_reason_counts_are_sorted_and_stable`, `test_shuffled_evidence_has_same_members_and_funnel_hash`, `test_duplicate_identical_stock_id_is_counted_once_with_ledger_entry`, `test_one_stock_id_with_two_codes_is_identity_blocker`, and `test_one_code_with_two_stock_ids_is_identity_blocker`.

- [ ] **Step 2: Verify RED**

```powershell
pytest tests/pattern_finder/universe_foundation/test_funnel.py -q
```

- [ ] **Step 3: Implement reconciliation-only aggregation (GREEN)**

```python
def build_funnel(evaluations: Sequence[SecurityEvaluation]) -> UniverseFunnel:
    """Aggregate existing field decisions; never reinterpret a rule."""
```

The aggregator must only select each stage's already-produced `FieldDecision`; it must contain no thresholds and no source-specific parsing.

- [ ] **Step 4: Run focused and evaluator tests**

```powershell
pytest tests/pattern_finder/universe_foundation/test_funnel.py tests/pattern_finder/universe_foundation/test_evaluator.py -q
```

- [ ] **Step 5: REFACTOR stage metadata to one immutable constant**

```python
FUNNEL_STAGE_SPECS: tuple[FunnelStageSpec, ...] = (
    FunnelStageSpec(0, "S0", "DISCOVERED_US_CASH_SECURITIES", "discovery"),
    FunnelStageSpec(1, "S1", "IDENTITY_VALID", "identity"),
    FunnelStageSpec(2, "S2", "EXCHANGE_ALLOWED", "exchange"),
    FunnelStageSpec(3, "S3", "SECURITY_CLASS_ALLOWED", "security_class"),
    FunnelStageSpec(4, "S4", "ACTIVE_STATUS_ALLOWED", "active_status"),
    FunnelStageSpec(5, "S5", "PRICE_ALLOWED", "price"),
    FunnelStageSpec(6, "S6", "MARKET_CAP_ALLOWED", "market_cap"),
    FunnelStageSpec(7, "S7", "SECTOR_INDUSTRY_ALLOWED", "sector_industry"),
    FunnelStageSpec(8, "S8", "LISTING_HISTORY_ALLOWED", "listing_history"),
    FunnelStageSpec(9, "S9", "LIQUIDITY_ALLOWED", "liquidity"),
    FunnelStageSpec(10, "S10", "CORE_UNIVERSE", "membership"),
)
```

Rerun the same command.

- [ ] **Step 6: Commit and STOP for independent review**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation tests/pattern_finder/universe_foundation/test_funnel.py
git commit -m "feat: reconcile the M3C-A universe funnel"
```

Review must confirm all candidates remain auditable, stage identities are fixed, and the funnel cannot change business decisions. STOP until PASS.

---

### Task 8: Futu Universe Gateway contracts, pagination, provenance, and independent limits

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/futu_gateway.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_futu_gateway.py`
- Preserve unchanged: `src/tv_quant/pattern_finder/futu_service.py`

**Interfaces:**
- Produces: `FutuUniverseGateway`, `FutuUniverseGatewayError`, `GatewayPreflight`, `GatewayAttempt`, `ApiBatchRecord`, `RatePolicy`.
- Produces: `collect(self, *, as_of_session: date, observed_at_utc: datetime, classification_provider: SecurityMasterProvider) -> GatewayAttempt`.
- Internal typed adapter calls: `_discover_cash_securities()`, `_screen_all_pages()`, `_market_snapshots(codes: Sequence[str])`, `_owner_plates(codes: Sequence[str])`.

Stable gateway blocker codes are exactly:

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

`FutuUniverseGateway.__init__(*, sdk: Any | None = None, host: str = "127.0.0.1", port: int = 11111, clock: Callable[[], datetime], sleep: Callable[[float], None]) -> None` is the exact constructor. Dependency injection is mandatory for deterministic rate/pagination tests.

- [ ] **Step 1: Write adapter contract tests with a fake SDK (RED)**

```python
def test_owner_plate_uses_200_per_request_and_ten_per_30_seconds(fake_sdk) -> None:
    gateway = FutuUniverseGateway(fake_sdk, clock=fake_clock, sleep=fake_sleep)
    gateway.collect(
        as_of_session=date(2026, 8, 12),
        observed_at_utc=datetime(2026, 8, 12, 21, 5, tzinfo=UTC),
        classification_provider=fake_security_master,
    )
    assert max(len(call.codes) for call in fake_sdk.owner_plate_calls) <= 200
    assert gateway.owner_plate_policy == RatePolicy(max_items=200, max_requests=10, window_seconds=30)
    assert gateway.market_snapshot_policy == RatePolicy(max_items=400, max_requests=60, window_seconds=30)
```

Add the exact contract tests `test_discovery_enumerates_us_cash_types_without_core_numeric_filters`, `test_stock_screen_pages_until_last_page_true`, `test_each_request_records_fields_cursor_count_hash_and_versions`, `test_non_ret_ok_maps_to_stable_blocker`, `test_missing_frozen_field_is_schema_blocker`, `test_new_provider_enum_is_unknown_not_active`, `test_identity_conflict_stops_attempt`, `test_login_permission_schema_and_pagination_blockers_are_distinct`, `test_null_provider_value_never_becomes_zero`, `test_only_retryable_errors_use_bounded_backoff`, `test_required_batch_failure_is_failed_incomplete_non_formal`, and `test_context_closes_on_success_and_failure`.

- [ ] **Step 2: Verify RED**

```powershell
pytest tests/pattern_finder/universe_foundation/test_futu_gateway.py -q
```

- [ ] **Step 3: Implement fact collection only (GREEN)**

```python
class FutuUniverseGateway:
    market_snapshot_policy = RatePolicy(max_items=400, max_requests=60, window_seconds=30)
    owner_plate_policy = RatePolicy(max_items=200, max_requests=10, window_seconds=30)

    def collect(
        self,
        *,
        as_of_session: date,
        observed_at_utc: datetime,
        classification_provider: SecurityMasterProvider,
    ) -> GatewayAttempt:
        """Collect immutable source facts and an attempt manifest; make no eligibility decision."""
```

Preflight records OpenD READY/login, SDK/server version, US quote permission/delay, history quota snapshot as evidence only, and requested batches. Do not request history K-lines. Do not apply CORE threshold decisions in the gateway.

- [ ] **Step 4: Run focused and existing Futu regressions**

```powershell
pytest tests/pattern_finder/universe_foundation/test_futu_gateway.py tests/pattern_finder/test_futu_service.py tests/pattern_finder/test_expand_m3b_universe.py tests/test_futu_downloader.py -q
```

- [ ] **Step 5: REFACTOR common request recording without combining policies**

```python
def _record_batch(
    interface: str,
    request_payload: Mapping[str, object],
    response_payload: Mapping[str, object],
    *,
    observed_at_utc: datetime,
) -> ApiBatchRecord:
    return ApiBatchRecord(
        interface=interface,
        request_payload=request_payload,
        response_count=len(response_payload.get("rows", ())),
        response_sha256=canonical_hash(response_payload),
        observed_at_utc=observed_at_utc,
    )
```

The two `RatePolicy` instances and their limiter state must remain separate. Rerun the same command.

- [ ] **Step 5A: Run a quota-safe live OpenD source qualification**

Using a preapproved tiny sample (one allowed common stock, one explicit non-common type where available, and threshold-near symbols identified without downloading history), record actual SDK/OpenD versions, permission/delay class, Stock Screen V2 field IDs, currencies, `AVG_TURNOVER(days=20)`, `LISTED_DAYS`, price/cap timestamps, pagination flags, raw Industry, and Owner Plate response shape. Confirm units/window/update times against the frozen adapter contract. This check must not call `request_history_kline`, hydrate the universe, or exceed one normal request batch per relevant endpoint. Any unsupported field/permission/schema produces the stable blocker and prevents live FORMAL acceptance; fixture tests remain valid but cannot be represented as live evidence.

- [ ] **Step 6: Commit and STOP for independent review**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation tests/pattern_finder/universe_foundation/test_futu_gateway.py
git commit -m "feat: collect auditable Futu universe evidence"
```

Review must confirm M3C-A uses metadata/screen/snapshot/plate only, never hydration, and Owner Plate 200/10 is not replaced by Snapshot 400/60. STOP until PASS.

---

### Task 9: Deterministic Universe Snapshot and immutable evidence store

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/snapshots.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_snapshots.py`

**Interfaces:**
- Consumes: published/draft identity, `GatewayAttempt`, `SecurityEvaluation`, `UniverseFunnel`.
- Produces: `SnapshotKind(FORMAL, PREVIEW)`, `UniverseSnapshotHeader`, `UniverseSnapshotRow`, `UniverseSnapshot`, `UniverseSnapshotStore`.
- Produces: `build_snapshot(*, kind: SnapshotKind, profile: UniverseProfile | None, draft: UniverseDraft | None, gateway_attempt: GatewayAttempt, evaluations: Sequence[SecurityEvaluation], funnel: UniverseFunnel, universe_snapshot_id: UUID, created_at_utc: datetime) -> UniverseSnapshot`, `snapshot_content_sha256(snapshot: UniverseSnapshot) -> str`, `snapshot_record_sha256(snapshot: UniverseSnapshot) -> str`, `members_sha256(rows: Sequence[UniverseSnapshotRow]) -> str`.
- Produces: `UniverseSnapshotStore(root: str | Path)` with append-only `universe_snapshots.jsonl`; no caller-provided overwrite/update method.

- [ ] **Step 1: Write deterministic-content and full-record tests (RED)**

```python
def test_snapshot_content_hash_ignores_attempt_noise_but_record_hash_does_not(snapshot) -> None:
    rerun = replace(snapshot, universe_snapshot_id=uuid4(), created_at_utc=LATER, attempt_id="attempt-2")
    assert snapshot_content_sha256(rerun) == snapshot_content_sha256(snapshot)
    assert snapshot_record_sha256(rerun) != snapshot_record_sha256(snapshot)
```

Add `test_each_business_or_version_field_changes_snapshot_content_hash` parameterized over fact, decision, profile/evidence/schema/provenance/classification versions, raw record hash, as-of, completeness, and funnel; `test_runtime_path_pid_mtime_and_write_time_do_not_change_content_hash`; `test_snapshot_persists_pass_fail_unknown_rows_and_all_audit_ledgers`; `test_failed_or_incomplete_attempt_cannot_be_formal`; and `test_existing_snapshot_id_cannot_be_rewritten`.

- [ ] **Step 2: Verify RED**

```powershell
pytest tests/pattern_finder/universe_foundation/test_snapshots.py -q
```

- [ ] **Step 3: Implement deterministic payloads and append-only store (GREEN)**

```python
def build_snapshot(
    *,
    kind: SnapshotKind,
    profile: UniverseProfile | None,
    draft: UniverseDraft | None,
    gateway_attempt: GatewayAttempt,
    evaluations: Sequence[SecurityEvaluation],
    funnel: UniverseFunnel,
    universe_snapshot_id: UUID,
    created_at_utc: datetime,
) -> UniverseSnapshot:
    rows = tuple(UniverseSnapshotRow.from_evaluation(item) for item in evaluations)
    return UniverseSnapshot.create(
        kind=kind, profile=profile, draft=draft, gateway_attempt=gateway_attempt,
        rows=rows, funnel=funnel, universe_snapshot_id=universe_snapshot_id,
        created_at_utc=created_at_utc,
    )

class UniverseSnapshotStore:
    def append(self, snapshot: UniverseSnapshot) -> None:
        """Recompute both hashes, reject duplicate IDs, then append/fsync one JSONL record."""

    def get(self, universe_snapshot_id: UUID) -> UniverseSnapshot:
        """Return the exact hash-verified record or raise SnapshotNotFound."""

    def latest_formal(self, profile_version_id: str) -> UniverseSnapshot | None:
        """Return the newest COMPLETE FORMAL record for this exact published profile."""
```

`snapshot_sha256` excludes `universe_snapshot_id`, `created_at_utc`, local paths, attempt ID, and write time; `snapshot_record_sha256` covers the complete persisted payload including those fields and all provenance.

- [ ] **Step 4: Run focused and hash regressions**

```powershell
pytest tests/pattern_finder/universe_foundation/test_snapshots.py tests/pattern_finder/universe_foundation/test_funnel.py tests/contracts/test_capability_registry.py tests/pipeline/test_run_manifest.py -q
```

- [ ] **Step 5: REFACTOR canonical business/record payloads into visibly separate functions**

```python
def snapshot_content_payload(snapshot: UniverseSnapshot) -> dict[str, object]:
    payload = snapshot.to_payload()
    for runtime_field in ("universe_snapshot_id", "created_at_utc", "attempt_id", "write_time_utc"):
        payload.pop(runtime_field, None)
    return payload

def snapshot_record_payload(snapshot: UniverseSnapshot) -> dict[str, object]:
    return snapshot.to_payload()
```

Rerun the same command and assert the two field sets differ exactly by the documented runtime/provenance fields.

- [ ] **Step 6: Commit and STOP for independent review**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation tests/pattern_finder/universe_foundation/test_snapshots.py
git commit -m "feat: persist immutable universe snapshots"
```

Review must confirm content vs record hash separation, all-candidate retention, provenance sensitivity, append-only behavior, and UNKNOWN/Quarantine preservation. STOP until PASS.

---

### Task 10: Production decision detail read model and manual evidence gates

**Files:**
- Modify: `src/tv_quant/pattern_finder/universe_foundation/ui_read_model.py`
- Modify: `app/pages/3_Universe_Settings.py`
- Modify: `tests/pattern_finder/universe_foundation/test_ui_read_model.py`
- Modify: `tests/pattern_finder/test_universe_settings_page.py`
- Modify: `docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md`

**Interfaces:**
- Consumes: `UniverseSnapshotStore` only.
- Produces: `DecisionDetailUi`, `SnapshotUiState`, `load_snapshot_ui_state(store: UniverseSnapshotStore, snapshot_id: UUID) -> SnapshotUiState`, `find_security_decision(state: SnapshotUiState, query: str) -> DecisionDetailUi | None`.
- Every decision detail includes input/security, decision, metric ID, operator/threshold, raw/normalized value, source/ref, observed time, PASS/FAIL/UNKNOWN, reason code, profile version/hash, evidence version, snapshot/content/record hashes.

- [ ] **Step 1: Write AppTest coverage for all required visible fields (RED)**

```python
def test_security_detail_shows_metric_threshold_source_reason_and_versions(snapshot_store) -> None:
    state = load_snapshot_ui_state(snapshot_store, SNAPSHOT_ID)
    detail = find_security_decision(state, "US.AAPL")
    assert detail is not None
    assert detail.metric_id == "FUTU_AVG_TURNOVER_20D"
    assert detail.threshold == ">= 20000000.00 USD"
    assert detail.decision in {"PASS", "FAIL", "UNKNOWN"}
    assert detail.reason_code
    assert detail.profile_version_id == "CORE:v1"
    assert detail.evidence_version == "futu-screening-liquidity/v1"
```

Fixture snapshots must include: liquidity exact PASS and near-threshold FAIL; listing 250 PASS and 249 FAIL; classification COMMON PASS and UNKNOWN; listing/liquidity conflict Quarantine; raw Industry and multiple plates; snapshot COMPLETE/INCOMPLETE; final member and non-member.

- [ ] **Step 2: Verify RED**

```powershell
pytest tests/pattern_finder/universe_foundation/test_ui_read_model.py tests/pattern_finder/test_universe_settings_page.py -q
```

- [ ] **Step 3: Implement production projection and page sections (GREEN)**

```python
@dataclass(frozen=True, slots=True)
class DecisionDetailUi:
    stock_id: str
    symbol: str
    futu_code: str
    field_id: str
    metric_id: str
    raw_value: str | None
    normalized_value: str | None
    operator: str
    threshold: str | None
    decision: str
    reason_code: str
    evidence_source: str | None
    evidence_observed_at_utc: datetime | None
    profile_version_id: str | None
    profile_content_sha256: str | None
    evidence_version: str | None
    snapshot_sha256: str
    snapshot_record_sha256: str
```

Add these page sections, all derived from `SnapshotUiState`: Snapshot/Evidence status; actual funnel; member/FAIL/Quarantine tables; symbol/code search; selected security's all-field decisions; raw Industry/Plate evidence; downloadable members/exclusions/unknown lists. Missing records display an error (“no evidence record”) rather than “not eligible”.

- [ ] **Step 4: Run focused and Pattern Finder regression tests**

```powershell
pytest tests/pattern_finder/universe_foundation/test_ui_read_model.py tests/pattern_finder/test_universe_settings_page.py tests/pattern_finder/test_pages.py tests/pattern_finder/test_flat_base.py -q
```

- [ ] **Step 5: REFACTOR and prove UI contains no decision logic**

```powershell
rg -n "Decimal|ROUND_HALF_EVEN|>=|<=|resolve_classification|evaluate_security|detect_flat_base" app/pages/3_Universe_Settings.py
```

Expected: no business comparison, classification, evaluator, or detector references. Formatting comparisons used only by Streamlit internals are not permitted in the page source. Rerun tests.

- [ ] **Step 6: Manual UI Gate 2 — evidence and membership slices**

Run `streamlit run app/Home.py` with the deterministic acceptance snapshot. Human must inspect and record, before further related work:

1. Universe/Profile basic state and version/hash.
2. Liquidity PASS at `20,000,000.00`, FAIL at `19,999,999.99`, metric/source/evidence version.
3. Listing PASS at 250, FAIL at 249, and auxiliary `listing_date` warning without replacement.
4. Classification COMMON PASS and `CLASSIFICATION_UNKNOWN` UNKNOWN.
5. `LISTING_HISTORY_CONFLICT` and `LIQUIDITY_EVIDENCE_CONFLICT` Quarantine reasons.
6. Raw Industry and every Owner Plate with source/version/hash.
7. Snapshot COMPLETE/INCOMPLETE and content/record hashes.
8. Final membership plus an excluded and a quarantined security.

Each observation must show input/security, result, metric, threshold, source/evidence, PASS/FAIL/UNKNOWN, reason code, and profile/evidence version. Record PASS/FAIL per item in the acceptance file.

- [ ] **Step 7: Commit and STOP for independent review + human acceptance**

```powershell
git add app/pages/3_Universe_Settings.py src/tv_quant/pattern_finder/universe_foundation/ui_read_model.py tests/pattern_finder docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md
git commit -m "feat: expose universe decision evidence in Pattern Finder"
```

Do not start Task 11 until review and all Manual UI Gate 2 items are PASS.

---

### Task 11: Non-mutating Preview orchestration and parent-version diff

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/preview.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_preview.py`

**Interfaces:**
- Consumes: draft/published profile, an explicit evidence attempt, classifier/evaluator/funnel/snapshot functions, stores.
- Produces: `PreviewDiff`, `PreviewResult`, `run_preview(*, profile: UniverseProfile | UniverseDraft, gateway_attempt: GatewayAttempt, parent_snapshot: UniverseSnapshot | None, snapshot_store: UniverseSnapshotStore | None = None) -> PreviewResult`.
- Must not create Scan Batch, Pattern result/review rows, or FORMAL snapshot; optional persistence is append-only PREVIEW with `is_formal=False`.

- [ ] **Step 1: Write non-mutation and completeness tests (RED)**

```python
def test_preview_does_not_change_profile_snapshot_scan_or_review_stores(stores, draft, attempt) -> None:
    before = {name: file_state(path) for name, path in stores.items()}
    result = run_preview(profile=draft, gateway_attempt=attempt, parent_snapshot=None)
    assert result.snapshot.header.snapshot_kind is SnapshotKind.PREVIEW
    assert {name: file_state(path) for name, path in stores.items()} == before
```

Add `test_preview_exposes_draft_hash_evidence_as_of_completeness_funnel_and_members`, `test_preview_diff_has_added_removed_counts_and_reasons`, `test_incomplete_preview_is_non_formal`, `test_existing_gateway_attempt_can_be_replayed`, and `test_new_evidence_requires_an_explicit_new_gateway_attempt`.

- [ ] **Step 2: Verify RED**

```powershell
pytest tests/pattern_finder/universe_foundation/test_preview.py -q
```

- [ ] **Step 3: Implement preview orchestration (GREEN)**

```python
def run_preview(
    *,
    profile: UniverseProfile | UniverseDraft,
    gateway_attempt: GatewayAttempt,
    parent_snapshot: UniverseSnapshot | None,
    snapshot_store: UniverseSnapshotStore | None = None,
) -> PreviewResult:
    evaluations = evaluate_attempt(profile, gateway_attempt)
    funnel = build_funnel(evaluations)
    snapshot = build_preview_snapshot(profile, gateway_attempt, evaluations, funnel)
    if snapshot_store is not None:
        snapshot_store.append(snapshot)
    return PreviewResult(snapshot=snapshot, diff=diff_membership(parent_snapshot, snapshot))
```

No Futu SDK is accepted here; data refresh stays an explicit gateway action outside preview computation.

- [ ] **Step 4: Run focused and store regressions**

```powershell
pytest tests/pattern_finder/universe_foundation/test_preview.py tests/pattern_finder/universe_foundation/test_registry.py tests/pattern_finder/universe_foundation/test_snapshots.py tests/pattern_finder/test_validation.py -q
```

- [ ] **Step 5: REFACTOR diff computation into a pure function**

```python
def diff_membership(
    parent: UniverseSnapshot | None,
    current: UniverseSnapshot,
) -> PreviewDiff:
    parent_rows = {} if parent is None else parent.rows_by_stock_id()
    current_rows = current.rows_by_stock_id()
    return PreviewDiff.from_row_maps(parent_rows, current_rows)
```

Rerun the same command.

- [ ] **Step 6: Commit and STOP for independent review**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation tests/pattern_finder/universe_foundation/test_preview.py
git commit -m "feat: add non-mutating universe preview"
```

Review must confirm Preview cannot write formal history or call detector/scan/review paths. STOP until PASS.

---

### Task 12: Draft/Preview/Publish UI workflow and incremental manual gate

**Files:**
- Modify: `src/tv_quant/pattern_finder/universe_foundation/ui_read_model.py`
- Modify: `app/pages/3_Universe_Settings.py`
- Modify: `tests/pattern_finder/universe_foundation/test_ui_read_model.py`
- Modify: `tests/pattern_finder/test_universe_settings_page.py`
- Modify: `docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md`

**Interfaces:**
- Consumes: `ProfileRegistry`, `run_preview`, explicit current `GatewayAttempt`/stored evidence.
- Produces: `DraftFormInput`, `PreviewUiState`, `build_draft_form_input(profile: UniverseProfile | UniverseDraft) -> DraftFormInput`, `build_preview_ui_state(result: PreviewResult) -> PreviewUiState`.
- UI events call production methods only: clone/create/save draft, preview, publish after COMPLETE preview and non-empty change note.

- [ ] **Step 1: Write UI workflow tests (RED)**

Add `test_page_clones_core_v1_and_edits_only_allowed_fields`, `test_page_preview_renders_complete_parent_diff`, `test_page_publishes_core_v2_and_custom_v1`, `test_page_surfaces_duplicate_filter_hash_rejection`, `test_page_disables_publish_for_incomplete_preview`, `test_page_never_offers_overwrite_core_v1_copy`, `test_page_rerun_does_not_call_futu`, and `test_page_workflow_preserves_parent_profile_and_snapshot_hashes`.

- [ ] **Step 2: Verify RED**

```powershell
pytest tests/pattern_finder/test_universe_settings_page.py tests/pattern_finder/universe_foundation/test_ui_read_model.py -q
```

- [ ] **Step 3: Implement forms and production calls (GREEN)**

Use `st.form` for draft edits and publication confirmation. Use stable session keys only for per-tab selection/draft UI state; persistent truth remains in production stores. Render full parent diff and `change_note` before publish. Refresh evidence is a separate explicit button; previewing existing evidence cannot connect to Futu.

- [ ] **Step 4: Run focused and full Pattern Finder regression**

```powershell
pytest tests/pattern_finder -q
```

- [ ] **Step 5: REFACTOR page helpers into production read models, not UI business logic**

Run the UI decision-logic scan from Task 10; expected: no matches. Rerun `pytest tests/pattern_finder -q`.

- [ ] **Step 6: Manual UI Gate 3 — Draft, Preview, and version publication**

Human must record: clone source and draft hash; modified metric/threshold; Preview evidence as-of and completeness; funnel/member/Quarantine diff; full publish diff/change note; CORE:v2 or Custom:v1 created; CORE:v1 hash unchanged; incomplete preview cannot publish; old snapshot remains readable. Each decision view still exposes the nine required evidence fields.

- [ ] **Step 7: Commit and STOP for independent review + human acceptance**

```powershell
git add app/pages/3_Universe_Settings.py src/tv_quant/pattern_finder/universe_foundation/ui_read_model.py tests/pattern_finder docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md
git commit -m "feat: add versioned universe preview workflow"
```

Do not begin Task 13 until automated tests, independent review, and Manual UI Gate 3 are PASS.

---

### Task 13: Future ScanBatch binding contract and hard architecture boundaries

**Files:**
- Create: `src/tv_quant/pattern_finder/universe_foundation/scan_binding.py`
- Modify: `src/tv_quant/pattern_finder/universe_foundation/__init__.py`
- Create: `tests/pattern_finder/universe_foundation/test_scan_binding.py`
- Create: `tests/pattern_finder/test_universe_foundation_boundaries.py`

**Interfaces:**
- Consumes: published `UniverseProfile` and complete FORMAL `UniverseSnapshot` only.
- Produces: `ScanUniverseBinding`, `bind_scan_universe(*, scan_batch_id: str, scan_as_of_session: date, profile: UniverseProfile, snapshot: UniverseSnapshot, freshness_policy: Callable[[date, date], bool]) -> ScanUniverseBinding`.
- This task creates only a binding value object/validator for a future scanner; it does not create a scan orchestrator, hydrate data, or run a detector.

- [ ] **Step 1: Write scan-binding and architecture boundary tests (RED)**

```python
def test_scan_binding_requires_published_complete_formal_matching_hashes(profile, snapshot) -> None:
    binding = bind_scan_universe(
        scan_batch_id="scan-2026-08-13",
        scan_as_of_session=date(2026, 8, 13),
        profile=profile,
        snapshot=snapshot,
        freshness_policy=lambda scan_day, snapshot_day: snapshot_day <= scan_day,
    )
    assert binding.universe_profile_version_id == profile.profile_version_id
    assert binding.universe_snapshot_sha256 == snapshot.header.snapshot_sha256
    assert binding.universe_member_count == snapshot.header.member_count
```

Reject Draft, PREVIEW, INCOMPLETE, FAILED attempt, profile ID/hash mismatch, stale snapshot, as-of reversal, member count/hash mismatch. Add AST/import tests that `flat_base.py` imports no Universe Foundation module, Flat Base dataclasses expose no cap/sector/exchange/profile fields, `detect_flat_base(data: pd.DataFrame) -> FlatBaseResult` signature is unchanged, same OHLCV is identical under two profiles, UI preview never calls detector, and legacy M3B cache/universe results are unchanged.

- [ ] **Step 2: Verify RED**

```powershell
pytest tests/pattern_finder/universe_foundation/test_scan_binding.py tests/pattern_finder/test_universe_foundation_boundaries.py -q
```

- [ ] **Step 3: Implement the binding validator only (GREEN)**

```python
@dataclass(frozen=True, slots=True)
class ScanUniverseBinding:
    scan_batch_id: str
    scan_as_of_session: date
    universe_profile_version_id: str
    universe_profile_content_sha256: str
    universe_snapshot_id: UUID
    universe_snapshot_sha256: str
    universe_snapshot_record_sha256: str
    universe_member_count: int

def bind_scan_universe(
    *,
    scan_batch_id: str,
    scan_as_of_session: date,
    profile: UniverseProfile,
    snapshot: UniverseSnapshot,
    freshness_policy: Callable[[date, date], bool],
) -> ScanUniverseBinding:
    validate_scan_binding(profile, snapshot, scan_as_of_session, freshness_policy)
    return ScanUniverseBinding.from_validated(profile, snapshot, scan_batch_id, scan_as_of_session)
```

The binding reads frozen members; it has no Futu, detector, cache refresh, batch compute, or persistence dependency.

- [ ] **Step 4: Run focused and Pattern Finder regression tests**

```powershell
pytest tests/pattern_finder/universe_foundation/test_scan_binding.py tests/pattern_finder/test_universe_foundation_boundaries.py tests/pattern_finder -q
```

- [ ] **Step 5: REFACTOR invariant checks to stable reason codes**

```python
class ScanBindingError(ValueError):
    reason_code: str
```

Rerun the same command.

- [ ] **Step 6: Commit and STOP for independent review**

```powershell
git add src/tv_quant/pattern_finder/universe_foundation tests/pattern_finder
git commit -m "feat: bind future scans to immutable universe evidence"
```

Review must confirm this is only a contract boundary, not M3C-B computation, and Detector inputs remain frozen. STOP until PASS.

---

### Task 14: End-to-end M3C-A fixture acceptance, manual record, and STOP LINE

**Files:**
- Modify: `tests/pattern_finder/universe_foundation/test_profiles.py`
- Modify: `tests/pattern_finder/universe_foundation/test_evaluator.py`
- Modify: `tests/pattern_finder/universe_foundation/test_funnel.py`
- Modify: `tests/pattern_finder/universe_foundation/test_futu_gateway.py`
- Modify: `tests/pattern_finder/universe_foundation/test_snapshots.py`
- Modify: `tests/pattern_finder/test_universe_settings_page.py`
- Modify: `tests/pattern_finder/test_universe_foundation_boundaries.py`
- Modify: `docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md`

**Interfaces:**
- Consumes all prior public M3C-A interfaces without adding a new production subsystem.
- Produces acceptance evidence only: frozen cross-stage fixture, exact assertions, completed manual acceptance record, and final review report.

- [ ] **Step 1: Add the failing integrated acceptance fixture (RED)**

Create a deterministic fixture set spanning: three allowed exchanges; OTC; exact/below price/cap/liquidity/listing thresholds; explicit ETF/ADR/Preferred/Warrant/Unit; unknown subtype; delisted/suspended/new status; listing conflict; liquidity conflict; raw Industry/Plate; missing critical evidence; member/FAIL/UNKNOWN/Quarantine. Assert exact candidate/member/quarantine counts, every S0-S10 identity, all stage reconciliation equations, members/funnel/snapshot/content-record hashes, and UI projection values.

- [ ] **Step 2: Verify RED against the first missing acceptance assertion**

```powershell
pytest tests/pattern_finder/universe_foundation tests/pattern_finder/test_universe_settings_page.py tests/pattern_finder/test_universe_foundation_boundaries.py -q
```

Expected: FAIL only for the newly added incomplete fixture/assertion, not an unrelated regression.

- [ ] **Step 3: Make only fixture/contract corrections needed for GREEN**

No new feature is authorized here. If GREEN requires production behavior absent from Tasks 1-13, STOP and route it through independent scope review: either it is a missed frozen M3C-A contract and must be assigned to the owning earlier task, or it belongs in Backlog.

- [ ] **Step 3A: REFACTOR only shared acceptance fixture builders**

Extract repeated deterministic evidence/profile/snapshot builders into `tests/pattern_finder/universe_foundation/conftest.py` only when at least two acceptance tests use the same complete object. Keep literal threshold and reason-code assertions in each owning test so the frozen contract stays visible. Do not change production signatures or behavior in this step.

- [ ] **Step 4: Run focused tests**

```powershell
pytest tests/pattern_finder/universe_foundation tests/pattern_finder/test_universe_settings_page.py tests/pattern_finder/test_universe_foundation_boundaries.py -q
```

- [ ] **Step 5: Run Pattern Finder regression**

```powershell
pytest tests/pattern_finder -q
```

- [ ] **Step 6: Run full repository regression**

```powershell
pytest -q
```

- [ ] **Step 7: Complete final manual UI acceptance**

Human reruns all recorded gates against the final build and signs each row PASS/FAIL with timestamp and evidence. The record must include Universe/Profile basic state; Liquidity; Listing History; Classification PASS/UNKNOWN; Quarantine; raw Industry/Plate; Snapshot/Evidence status; final membership; Draft/Preview/version immutability; and all nine visible decision fields.

- [ ] **Step 8: Run architecture/scope and M3C-B boundary checks**

```powershell
rg -n "request_history_kline|update_futu_csv|flat_base_scan_rows|detect_flat_base|duckdb|pyarrow|benchmark|pattern_instance|review_queue" src/tv_quant/pattern_finder/universe_foundation app/pages/3_Universe_Settings.py
rg -n "from .*universe_foundation|import .*universe_foundation" src/tv_quant/pattern_finder/flat_base.py
```

Expected: no M3C-B hydration/batch compute/benchmark, Pattern Instance/Review Queue, detector call, or reverse detector dependency. Mentions in stable boundary error text/docstrings are permitted only when the independent reviewer confirms they are non-executable.

- [ ] **Step 9: Run placeholder and diff checks**

```powershell
$redFlags = @(
    ('T' + 'BD'), ('T' + 'ODO'), ('FIX' + 'ME'),
    ('implement' + ' later'), ('fill' + ' in'), ('NotImplemented' + 'Error'),
    ('Similar' + ' to Task'), ('appropriate' + ' error'), ('handle' + ' edge cases')
) -join '|'
rg -n $redFlags src/tv_quant/pattern_finder/universe_foundation app/pages/3_Universe_Settings.py tests/pattern_finder/universe_foundation docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md
git diff --check
```

Expected: no placeholders and no whitespace errors.

- [ ] **Step 10: Commit acceptance evidence and STOP for independent final review**

```powershell
git add tests/pattern_finder docs/superpowers/acceptance/2026-08-13-pattern-finder-m3c-a-manual-ui-acceptance.md
git commit -m "test: freeze M3C-A universe acceptance"
```

Independent final review must recheck frozen Design coverage, interfaces/types, task dependency order, forward implementability, UI manual testability, architecture boundaries, all test outputs, acceptance record, and `git diff --check`. STOP after review PASS. Do not start M3C-B.

---

## Manual UI Gate matrix

| Gate | Earliest task | User-verifiable complete function | Required visible evidence |
|---|---:|---|---|
| Gate 1 | 3 | Universe/Profile basic status | input/profile, frozen result, metric, threshold, evidence version, profile/hash |
| Gate 2A | 10 | Liquidity decisions | security, `FUTU_AVG_TURNOVER_20D`, actual/normalized value, `>= 20,000,000.00 USD`, source/ref, PASS/FAIL/UNKNOWN, reason, versions |
| Gate 2B | 10 | Listing History decisions | security, `FUTU_LISTED_DAYS`, actual value, `>= 250`, auxiliary listing date, source, result/reason, versions |
| Gate 2C | 10 | Classification and Quarantine | explicit evidence source/class/confidence, PASS/UNKNOWN, `CLASSIFICATION_UNKNOWN`/conflict reason, versions |
| Gate 2D | 10 | Raw Sector evidence | raw Industry, all Plate records, source/version/hash, `sector_mapping_version=null` |
| Gate 2E | 10 | Snapshot/Evidence and final membership | COMPLETE/INCOMPLETE, content/record hashes, profile/evidence versions, member/FAIL/Quarantine and first exit |
| Gate 3 | 12 | Draft → Preview → new immutable version | draft hash, changed metric/threshold, evidence as-of, diff, COMPLETE gate, new version/hash, unchanged parent/history |
| Final | 14 | Integrated M3C-A Definition of Done | all prior gates repeated on final build and signed PASS |

For every gate, the acceptance record must capture test fixture/live input, browser/page, timestamp, expected result, observed result, source/evidence reference, profile/evidence versions, reviewer, and PASS/FAIL. A FAIL blocks the next related task.

## M3C-A Definition of Done

M3C-A is DONE only when all of the following are true:

1. CORE v1 and profile/draft/version/availability contracts are immutable, deterministic, and hash-verifiable.
2. Futu metadata evidence is complete enough to evaluate or explicitly mark UNKNOWN; discovery, pages, batches, and failures are provenance-backed.
3. Security classification is evidence-driven and fail-closed; no heuristic can produce CORE PASS.
4. Liquidity and listing-history authoritative metrics, Decimal rules, half-even cent normalization, tolerance, auxiliary evidence, and conflict states have exact tests.
5. Sector/Industry is ALL for CORE v1; raw Industry/Plate evidence is retained and `sector_mapping_version=null`.
6. S0-S10 reconciles exactly; all candidates, decisions, first exits, members, FAIL, UNKNOWN, and Quarantine are preserved.
7. Snapshot content hash is deterministic, record hash covers the full attempt/provenance, and formal evidence is append-only.
8. Preview cannot mutate published profiles, old snapshots, scan/review stores, or Detector results.
9. Future ScanBatch binding rejects Draft/PREVIEW/INCOMPLETE/mismatched/stale evidence without implementing M3C-B.
10. Pattern Finder UI displays production result/evidence only and every required manual field is visible.
11. Focused tests, Pattern Finder regression, full repository regression, manual UI acceptance, architecture/scope check, `git diff --check`, and independent final review all PASS.

## STOP LINE and Backlog

After Task 14 independent final review PASS, STOP. `PRODUCTION_IMPLEMENTATION_AUTHORIZED` for M3C-A ends at the contracts and UI above. The following are Backlog and require a separately approved Design/Plan cycle:

- M3C-B bulk historical hydration, local daily-bar ADV20 computation, quota-aware cold start, warm-cache increment, read model, batch detector compute, and 500/1000/2000/3000 benchmarks.
- Selection of or commercial integration with a specific live authoritative security-master vendor beyond the Task 5 port/verified ledger.
- Sector taxonomy/mapping and any Sector/Industry filter other than ALL.
- Candidate Gallery, Pattern Instance, Review Queue, Open Review Queue, Historical T0, performance/SLA work.
- Any detector changes, Rounded Base, Compression, READY, ML, Future Outcome, accounts, brokers, orders, TradingView Webhook, options, or Phase 2 work.

## Final acceptance sequence

Execute in this exact order; any failure stops the sequence and returns to the owning task:

```text
Focused tests
→ Pattern Finder regression
→ full repository regression
→ manual UI acceptance
→ architecture/scope check
→ git diff --check
→ independent final review
→ M3C-A DONE
→ STOP (M3C-B remains unauthorized)
```
