# M3C-A2 — Formal Universe Snapshot Production Qualification Design

**Status:** Proposed Design for user review — Contract Reconciliation II

**Date:** 2026-08-31

**Scope:** Architecture / Design Spec only

**Authoritative code baseline:** `a1183c543de0adb4a71b60402d64d1deedc2f80b`

**Authoritative worktree:** `C:\Users\cbcbe\TradingCodex\tv_quant_system_m3ca2_qualification`

**Authoritative branch:** `codex/pattern-finder-m3c-a2-formal-snapshot-qualification`

## 1. Decision Summary

M3C-A2 specifies one explicit, fail-closed **future** application path that may turn a live Futu/OpenD collection attempt into an immutable persisted `FORMAL` `UniverseSnapshot`. It does not claim that the baseline production adapter, gateway, evaluator, or persistence path already implements this path.

The qualification authority is **demonstrated capability for every required endpoint and every required record in the same attempt**, not account tier, quote-right label, a `QOT_RIGHT` event, or subscription quota.

The minimal production path is:

1. a user explicitly requests a formal snapshot for one published profile;
2. the application service resolves the exact provider/OpenD identity and the exact accepted qualification contracts before it asks the gateway for formal evidence;
3. the gateway validates those exact contract IDs, versions, and hashes, validates the qualified clock/window prerequisites, and collects complete per-code evidence without crossing the locked XNYS session or provider lifecycle;
4. it rejects an `OPEN`, `FAILED_FOR_EXACT_VERSION`, missing, or hash-mismatched factor/provider/clock contract before evidence reaches the evaluator;
5. the existing evaluator and funnel derive S1-S9 and S0-S10 results;
6. the existing `build_snapshot()` enforces the formal snapshot invariant;
7. the existing SQLite `SnapshotRepository.append()` atomically persists the immutable snapshot aggregate;
8. the UI reopens the persisted snapshot and displays only the persisted projection;
9. M3D consumes only that persisted snapshot ID.

Any unknown, malformed, stale, inconsistent, incomplete, unqualified, hash-mismatched, or unpersisted result is not a formal snapshot and is not eligible for M3D. In particular, `formal_ready=false` while the observed `futu_api 10.10.7008` + OpenD `1010` identity, ADV20 authority, or any other required exact qualification contract remains unaccepted.

### 1.1 Reconciliation status and dependency order

OpenD `1009` is a legacy **exact-qualified identity**. It is neither a minimum supported version nor a schema proxy. The qualification captures recorded in the linked evidence used `futu_api 10.10.7008` with OpenD `1010`. `1010 > 1009` is not compatibility evidence: `1010` needs its own versioned provider/capability qualification envelope and immutable contract hash. Until that envelope is accepted, it is unqualified, `formal_ready=false`, and no FORMAL evidence may reuse a `1009` mapping or contract hash. Low-level diagnostic capture may record `1010` without granting it that authority.

The future implementation order is intentionally constrained:

1. define and accept the exact provider/OpenD version identity and qualification envelope before accepting a concrete clock contract;
2. define the independent factor/version model and `QualificationRegistry`, freeze the provider-neutral ADV20 interface as `OPEN`, then design the required new Profile Version;
3. add gateway acquisition-bracket capture and canonical evidence retention, then replace the clock contract;
4. add the application-service fail-closed sequence and `universe-snapshot/v2` binding, reconcile acceptance/documentation, and obtain independent spec review.

Acquisition brackets are multi-layer **future** evidence: the future gateway will capture them, a qualification contract will judge them, the application service will enforce the result, `universe-snapshot/v2` will bind and persist the references/hashes, and SQLite will store the aggregate without deciding qualification.

## 2. Scope and Non-Goals

### 2.1 In scope

- A capability-based production qualification contract for a formal universe snapshot.
- Exact required Futu/OpenD evidence and fail-closed verdicts.
- A session-calendar-based freshness contract without an arbitrary age threshold.
- A proposed application orchestrator mapped onto current domain, adapter, and repository boundaries.
- Streamlit explicit-action and rerun-idempotency boundaries.
- Successful snapshot atomicity and failed-attempt diagnostics.
- A Windows real-environment acceptance contract.

### 2.2 Out of scope

- No implementation in this node.
- No change to `CORE:v1`, its rules, hashes, or publication state.
- No schema migration or SQLite mutation during design work.
- No Futu/OpenD request, subscription, quota consumption, or account mutation during design work.
- No M3D implementation change.
- No preview-snapshot redesign.
- No attempt to import or reuse uncommitted work from the legacy occupied branch.

### 2.3 Explicit prohibitions for the future production path

- It must never call `request_highest_quote_right()` or any equivalent right-escalation API.
- It must not call `subscribe()`, `unsubscribe()`, or `query_subscription()` as part of the formal qualification decision.
- It must not infer authority from account tier, remaining quota, a successful subscription, or a `QOT_RIGHT` event.
- It must not persist a `FORMAL` snapshot before all formal invariants pass.
- It must not let Streamlit construct domain hashes, choose a snapshot kind, or write snapshot rows directly.

## 3. Baseline Architecture Investigation

### 3.1 Existing authority boundaries

| Boundary | Current component | Existing responsibility | M3C-A2 treatment |
|---|---|---|---|
| Profile authority | SQLite `ProfileRepository.get_published()` | Resolve the immutable published profile version and verify payload/filter/rules hashes from the same database that owns snapshots | Sole production command authority; `ProfileRegistry` remains bootstrap/UI input only and cannot authorize a formal build |
| Provider transport | `FutuProviderAdapter` | Wrap Futu SDK calls as immutable `RawApiBatch` / `RawApiPage` with canonicalized SDK-level request/response hashes, rows, and one `acquired_at_utc` | Baseline has no full wall/monotonic send/receive brackets and no lossless wire bytes; a future gateway/adapter seam must add canonical bracket evidence |
| Provider collection | `FutuUniverseGateway.collect()` | Discover candidates, page stock screen, fetch snapshot/state/plate evidence, validate per-code coverage, and return `GatewayAttempt` | Future gateway receives the application-service-resolved immutable provider/factor contract bundle, then verifies/enforces its exact IDs, versions, and hashes before evaluator input; legacy Stock Screen factor values are not FORMAL authorities |
| Classification | `SecurityMasterProvider.classification_evidence()` and explicit classification evidence | Fail-closed security-type proof | Reuse without silent inference |
| Rule evaluation | `evaluator.evaluate_security()` | Pure S1-S9 business-threshold evaluation; unknown evidence quarantines | Reuse unchanged in concept; it never chooses a provider, accepts a contract, or decides compatibility |
| Funnel | `build_funnel()` | Deterministic S0-S10 aggregation and reconciliation | Reuse unchanged in concept |
| Snapshot construction | `build_snapshot()` | Enforce FORMAL/PREVIEW invariants and canonical hashes | Reuse as final in-memory gate |
| Snapshot persistence | `SnapshotRepository.append()` | One `BEGIN IMMEDIATE` transaction for header, securities, and decisions; rollback on failure | Reuse as the sole production snapshot write authority |
| Snapshot read model | `load_snapshot_ui_state()` currently accepts `UniverseSnapshotStore` | Project persisted snapshot data for the UI without business recomputation | Preserve projection logic, but introduce the Proposed `SnapshotReader` seam in Section 10 so production reads SQLite rather than creating a competing file-store authority |
| UI | `app/pages/3_Universe_Settings.py` | Render profile/evaluation/persisted snapshot state | Add only explicit command invocation and result rendering in a future implementation |
| Downstream scan | M3D `ScanRepository` plus Today Scan, which currently chooses `SnapshotRepository.latest_summary()` | Bind scan batch to a persisted snapshot ID | Repository/domain binding is reusable; exact snapshot-ID handoff requires a separately approved Today Scan integration seam described in Section 11 |

### 3.2 Confirmed missing production seam

At the baseline commit, `build_snapshot()` has no production caller. Existing formal-scan acceptance constructs a formal snapshot fixture and proves persistence/reopen/downstream binding, but it does not prove that a live provider attempt can qualify and produce the snapshot.

Therefore M3C-A2 is an application-boundary completion, not a new domain model and not a second snapshot store.

### 3.3 Existing formal invariants that remain authoritative

A `FORMAL` snapshot must continue to satisfy all existing `UniverseSnapshotHeader` and `build_snapshot()` requirements, including:

- published profile binding and exact profile/filter hashes;
- no draft binding;
- `GatewayAttempt.attempt_status == SUCCEEDED`;
- `Completeness.COMPLETE`;
- `GatewayPreflight.formal_ready is True`;
- no preflight or gateway reason codes;
- exact evidence, prerequisite, and evaluation key coverage;
- reconciled S0-S10 funnel counts;
- canonical mapping, prerequisite, member, content, and record hashes.

M3C-A2 must not weaken, duplicate, or bypass these checks.

## 4. Futu Required Capability Matrix

The matrix below defines the complete required provider capability set. “Success” always means SDK return success, parseable expected shape, required fields present, raw batch hash recorded, and acquisition provenance retained. A successful transport call with missing or malformed content is a failure.

The governing rule is:

> `FORMAL_FRESHNESS_AUTHORITY` does not require synchronously reading an account-displayed LV1/LV2/LV3 quote-right tier string. It requires the current production OpenD connection to demonstrate every data capability needed by this formal collection, and requires every item of evidence to pass freshness, completeness, and provenance validation.

Three axes remain separate:

- **A — Account quote-right tier knowledge:** not synchronously queryable through the confirmed current boundary and not required as a formal verdict input.
- **B — Production capability evidence:** machine-verifiable success, shape, required fields, and exact coverage for the calls actually needed by this attempt.
- **C — Data freshness authority:** timestamp/calendar and same-attempt consistency rules applied to the collected evidence; never inferred from A or quota.

Unknown A does not make B or C unknowable, and neither successful B nor C is relabeled as knowledge of A.

| Capability ID | Actual source / call | Required evidence | Coverage rule | Freshness role | Failure result |
|---|---|---|---|---|---|
| `CAP-RUNTIME-SDK` | local Futu SDK `__version__` | non-empty exact SDK version | once per attempt | version binding only | `RUNTIME_SDK_VERSION_UNAVAILABLE` |
| `CAP-RUNTIME-OPEND` | future bracketed `get_global_state()` at attempt start and end | success; `qot_logined` true/`1`; `program_status_type == READY`; exact provider/OpenD identity bound to an accepted envelope; parseable `timestamp` and `local_timestamp`; exact canonical SDK-response hashes | two bookends on the same application connection identity | future clock qualification through Section 6.5; it does not replace the application clock | `OPEND_NOT_QUOTE_LOGGED_IN`, `OPEND_NOT_READY`, `OPEND_VERSION_UNAVAILABLE`, `FAILED_FOR_EXACT_VERSION`, or `CLOCK_AUTHORITY_BLOCKER` |
| `CAP-DISCOVERY` | `get_stock_basicinfo()` for configured US security categories | successful batches; stable `code`/identity; required type and listing/delisting fields | all configured pages/categories and unique discovered codes | same-attempt static observation | `DISCOVERY_INCOMPLETE_OR_MALFORMED` |
| `CAP-SCREEN` | paginated `get_stock_screen()` | every page succeeds; pagination terminates correctly; discovery/display fields are parseable and hashed | exactly one usable row for every candidate code when the selected profile needs those non-factor fields | Stock Screen `PRICE`, `MARKET_CAP`, `LISTED_DAYS`, and `AVG_TURNOVER` are diagnostic/legacy observations only and never inherit FORMAL factor authority | `SCREEN_INCOMPLETE_OR_MALFORMED` |
| `CAP-SNAPSHOT` | `get_market_snapshot(codes)` | exact per-code rows; parseable `last_price`, `update_time`, `equity_valid`, `issued_shares`, `total_market_val`, `listing_date`, suspension, and status fields as required by accepted factor contracts | exactly one usable row per candidate code, across deterministic chunks | per-code temporal-window verdict under Section 6; factor-specific contract verification; a suspension exception requires its own qualified contract | `SNAPSHOT_INCOMPLETE_OR_STALE`, `TEMPORAL_DATE_MISMATCH`, `FACTOR_CONTRACT_UNQUALIFIED`, or `SUSPENSION_FRESHNESS_UNQUALIFIED` |
| `CAP-MARKET-STATE` | bookended `get_market_state(codes)` | exact per-code start/end states; values and transitions allowed by the exact `QualifiedMarketStateConsistencyContract` and `QualifiedFormalCollectionWindowReachabilityContract`, including `OVERNIGHT` | exactly one usable start and end row per candidate code | raw states may differ per security, but every row must map to the same completed-session terminal relationship; any next-session-active row blocks | `MARKET_STATE_INCOMPLETE_OR_INCONSISTENT`, `FORMAL_COLLECTION_WINDOW_NOT_CLOSED`, or `FORMAL_WINDOW_UNREACHABLE_FOR_CANDIDATE_SET` |
| `CAP-OWNER-PLATE` | `get_owner_plate(codes)` | successful responses and explicit plate/industry evidence or explicit absence represented by the existing contract | exactly one classified result per candidate code after normalization | same-attempt static observation | `OWNER_PLATE_INCOMPLETE_OR_MALFORMED` |
| `CAP-CLASSIFICATION` | current explicit classification provider and evidence ledger | common-stock/ETF/WARRANT classification supported by allowed authoritative sources; unknown remains unknown | exactly one classification result per candidate code | evidence-version validity, not a market-data timestamp | `CLASSIFICATION_INCOMPLETE` |

### 4.1 Capability verdict

**Proposed Interface — `RequiredCapabilityVerdict`**

```text
RequiredCapabilityVerdict
  capability_id
  status: SUCCEEDED | FAILED
  scope: ATTEMPT | EVERY_CANDIDATE
  expected_count
  observed_count
  raw_batch_hashes
  acquisition_bracket_sha256s
  reason_codes
```

This is a proposed application/gateway value object. It does not replace `RawApiBatch`, `EvidenceReference`, `GatewayPreflight`, or `GatewayAttempt`; it deterministically summarizes them so the final qualification decision is auditable.

**Proposed Interface — `ApiAcquisitionBracket`**

```text
ApiAcquisitionBracket
  endpoint_id
  call_ordinal
  scope_key: canonical page token or ordered-code-chunk hash
  canonical_request_sha256
  request_wall_sent_at_utc
  request_monotonic_sent
  response_wall_received_at_utc
  response_monotonic_received
  projected_request_utc_interval
  projected_response_utc_interval
  raw_response_sha256
  bracket_sha256
```

This is a **future requirement**, not a claim about the current adapter. The current production `RawApiBatch` / `RawApiPage` retain deterministic batching, canonicalized SDK-level request/response hashes and rows, and one `acquired_at_utc`; they have no full wall/monotonic send/receive bracket and no lossless wire-byte representation. A future gateway/adapter evolution must record exactly one immutable bracket per provider call (or embed the object it hashes). Canonical order is `(endpoint_id, call_ordinal, scope_key)` and duplicate keys fail closed.

Every matrix row is required. There is no partial-credit or account-tier override.

### 4.2 Required field-to-source matrix

This table records the actual evidence fields consumed by the baseline gateway. “Current/static” describes the field semantics; it does not claim an undocumented Futu timestamp.

| Required field / evidence | Futu or local source | Current/static | Authoritative provider timestamp? | Freshness/validity authority | Permission/capability failure | Enters provenance? |
|---|---|---|---|---|---|---:|
| SDK version | installed Futu SDK `__version__` | runtime identity | No | captured once in the attempt and exact-bound to contracts | unavailable/empty fails runtime qualification | Yes |
| OpenD version, `qot_logined`, `program_status_type`, `timestamp`, `local_timestamp` | one non-authorizing `RuntimeIdentityProbe`, then future bracketed `get_global_state()` bookends | runtime identity; clock evidence only after the accepted bundle is returned to the gateway | `timestamp` is provider/server UTC epoch seconds; `local_timestamp` is the OpenD-host epoch timestamp, not market-data time | the probe identifies the exact provider envelope; the later accepted attempt requires that envelope plus the future Section 6.5 request-send/response-receive bracket contract | SDK error, false/unknown login, non-`READY`, missing/unparseable identity/clock, unaccepted exact identity, or bracket disagreement fails | Yes, including probe provenance, raw values, future brackets, and canonical SDK-response hashes |
| `stock_id`, `code`, name, exchange, `stock_type`, delisting flag | `get_stock_basicinfo()` discovery batches | static/reference as observed | No | complete same-attempt discovery, identity uniqueness, parseable fields | permission/market/transport/schema/identity failure | Yes, per discovery batch hash |
| symbol/name/industry | paginated `get_stock_screen()` | static/reference as observed | No | exact candidate coverage and same-attempt acquisition | any failed/partial page or missing/duplicate row fails | Yes, per page hash |
| Stock Screen `PRICE`, `MARKET_CAP`, `AVG_TURNOVER`, `LISTED_DAYS` | paginated `get_stock_screen()` | historical/diagnostic observations only | No per-row timestamp exposed by the current gateway contract | none for FORMAL CORE v1 factors; `3105` None/True/False is rejected and the other three properties are replaced by the source-neutral identities in Section 4.3 | these values cannot supply or rescue FORMAL factor evidence | Diagnostic page request/response hashes only |
| `last_price`, `update_time`, `equity_valid`, `issued_shares`, `total_market_val`, `listing_date` | `get_market_snapshot(codes)` | source fields for future accepted PRICE, MARKET_CAP, and LISTED factor contracts | `update_time` is current-price timing only | exact FactorQualificationContract for the source-neutral factor identity in Section 4.3 | missing, malformed, unqualified, or hash-mismatched required factor evidence fails before evaluator input | Yes, rows, batch hashes, factor contract references, and derivation hashes |
| suspension and raw security status | `get_market_snapshot(codes)` | current-state fields observed at acquisition | The row `update_time` is the current-price update time; the documentation does not establish that it timestamps the suspension flag | normal rows use Section 6 temporal equality; stale suspended rows require the proposed `QualifiedSuspensionFreshnessContract` | malformed/conflicting state or absent qualification fails provider-level; qualified explicit suspension becomes security-level S4 `FAIL` | Yes, per-code raw values, batch hash, and suspension-contract hash |
| `update_time` | `get_market_snapshot(codes)` | current-price update time | **Yes for current-price update only** | parse in `America/New_York`; require exact `as_of_date` equality and Section 6 temporal-window verdict, not merely `>=` a prior close | absent/unparseable/future/wrong-date fails unless the narrowly qualified suspension exception applies | Yes, raw value, normalized value, per-code verdict, and batch hash |
| per-code `market_state` | bookended `get_market_state(codes)` | request-scoped lifecycle state | No provider row timestamp in the current contract | both acquisition brackets plus exact state/transition and terminal-closed relationship contracts | permission/unsupported/missing/duplicate/unknown/mismatched or changed state fails | Yes, start/end chunk hashes and consistency/window-contract hashes |
| plate code/name/type and explicit absence | `get_owner_plate(codes)` | static/reference as observed | No | complete normalized outcome per candidate in the same attempt | permission/transport/malformed response or unrepresented absence fails | Yes, response hash and normalized evidence |
| explicit security classification and its evidence references | configured `SecurityMasterProvider.classification_evidence()` / classification ledger | static/reference evidence | Uses its own evidence observation time; not a Futu market timestamp | exact source/version/hash contract; unknown remains explicit | provider exception or missing representation fails completeness; represented unknown quarantines | Yes, evidence references and classification hashes |
| quota totals and active subscriptions | `query_subscription()` | current diagnostic only | No market-data timestamp | acceptance-harness acquisition time only; never freshness or quote-right authority | failure means quota diagnostic unavailable, not provider capability failure | Supplemental audit only |
| `QOT_RIGHT` change events | registered event handler, when explicitly captured outside the required path | change-event audit | Event payload only; not an initialization snapshot | proves only observed change events in its capture window | absent/capture failure does not fail required capability qualification | Supplemental audit only |

### 4.3 Exact provider identity envelope, factor authority, version model, and registry

Historical `CORE:v1` payloads and snapshots are immutable historical records: their bytes, hashes, and legibility are never rewritten. A new authority does not silently reinterpret a historical record. It is a future profile/evidence/qualification path and is fail-closed until accepted.

**Proposed Interface — `ProviderIdentityQualificationEnvelope`**

```text
ProviderIdentityQualificationEnvelope
  contract_id: immutable exact identity
  provider_id
  provider_sdk_version
  opend_server_version
  provider_mapping_schema_version
  capability_definition_version
  qualification_contract_version
  qualification_evidence_references
  qualification_evidence_sha256s
  verdict: ACCEPTED | OPEN | FAILED_FOR_EXACT_VERSION
  reason_codes
  contract_sha256
```

This envelope is the accepted contract for one exact provider/SDK/OpenD identity, not an observation of a connection and not a minimum-version rule. It is a prerequisite for clock/window or factor acceptance. `1009` and `1010` require separate envelopes; an `OPEN` or `FAILED_FOR_EXACT_VERSION` `1010` envelope cannot reuse `1009` mappings, evidence, or hashes.

**Proposed Interface — `RuntimeIdentityProbe`**

```text
RuntimeIdentityProbe
  application_context_instance_id
  provider_id
  provider_sdk_version
  opend_server_version
  provider_mapping_schema_version
  capability_definition_version
  canonical_request_sha256
  canonical_response_sha256
  probe_provenance_sha256
```

The service may ask the gateway/adapter for this one **non-authorizing** identity-discovery operation before it can resolve an exact envelope; otherwise it cannot know whether the observed OpenD is `1009`, `1010`, or another version. The gateway/adapter creates and retains the one quote context, captures the documented runtime identity plus canonical request/response/provenance hashes, and returns the immutable probe to the service. The probe neither accepts a contract nor supplies clock, factor, or FORMAL evidence. The service resolves the envelope from this exact tuple, returns the immutable bundle to the gateway, and the gateway then performs all bracketed collection. The gateway must fail closed unless the probe, every later observed identity/bookend, `OpenDConnectionIdentity`, and the envelope match field-for-field; it closes the context in its single `finally` path on either outcome.

The following independent versions must never be overloaded into one string: **A** business semantic; **B** metric identity; **C** source identity; **D** provider/version identity; **E** derivation identity; **F** qualification-contract version; and **G** Profile Version. Each axis increments independently and every contract binds an exact G, whether that is an existing or new Profile Version. C identifies the source/evidence authority; E identifies the transformation from its inputs to the metric. An E-only change leaves C unchanged, but its evidence record and exact contract must bind the new E and F must be requalified. A/B/threshold changes require a new G. A new G is ordinarily required only when the accepted membership semantics or identity changes the published profile payload/rules, not merely because E changes; the factor decisions below record the factor-specific ADV20 exception, where selecting an alternate authority mandates a new G and a new factor-specific Evidence Version even if membership is unchanged. If a container format must change, `evidence_record_schema_version` is an orthogonal evidence-record schema version, not one of A–G and not a replacement for C or E. D/F-only changes require a new provider/factor qualification contract and Snapshot binding but no new G when A/B/C/E remain identical. `universe-snapshot/v1` lacks these bindings; M3C-A2 requires `universe-snapshot/v2`. A later contract instance/hash change does not require a schema bump unless field shape changes.

| CORE v1 prerequisite | Source-neutral metric/evidence identity and future source | Deterministic semantics | Required version action | Current authority state |
|---|---|---|---|---|
| Price `>= USD 5` | `PRICE_USD`; Market Snapshot `last_price` + `update_time` | completed-session-qualified USD latest price | new C source identity, E derivation identity, and exact D/F provider/factor contracts; under this approved factor decision G remains unchanged if business semantic/threshold remain identical | candidate only; `1010` is unqualified until exact contract acceptance |
| Market Cap `>= USD 1B` | `EQUITY_MARKET_CAP_USD`; Market Snapshot `total_market_val` + `equity_valid`/`issued_shares`/`last_price` consistency | USD equity market capitalization with the same-row identity verified | new C source identity, E derivation identity, and exact D/F provider/factor contracts; under this approved factor decision G remains unchanged if business semantic/threshold remain identical | candidate only; `1010` is unqualified until exact contract acceptance |
| Listed `>= 250 trading days` | `LISTED_TRADING_SESSIONS`; Market Snapshot `listing_date` + named/versioned `XNYS` calendar | both-inclusive completed-session count with selected-session sequence/hash | new C source identity, exact D/E/F provider/derivation/contract, **and a new G Profile Version**; keep threshold `>=250` | candidate only; `1010` is unqualified until exact contract acceptance |
| ADV20 `>= USD 20M` | frozen provider-neutral ADV20 interface; no provider implementation selected | exact arithmetic mean of actual USD dollar turnover over exactly the 20 completed XNYS sessions ending `as_of` | a later alternate scalable authority requires its C source identity, D provider identity, E derivation, F contract, **a mandatory new factor-specific Evidence Version, and a mandatory new G Profile Version even if accepted membership identity is unchanged** | `OPEN — requires alternate scalable authority`; Stock Screen `3105` `period_average` None/True/False are **REJECTED** |

**Proposed Interfaces — `FactorQualificationContract` and `QualificationRegistry`**

```text
FactorQualificationContract
  contract_id: immutable exact identity
  factor_id
  business_semantic_version                 # A
  metric_identity_version                   # B
  source_identity_version                   # C
  provider_identity_version                 # D: provider, SDK, OpenD exact identity
  derivation_version                        # E
  qualification_contract_version            # F
  profile_version_id: exact G binding
  provider_identity_contract_id
  provider_identity_contract_version        # equals envelope.qualification_contract_version
  provider_identity_contract_sha256
  evidence_record_schema_version            # orthogonal container schema, not A-G
  canonical_source_definition
  required_fields_and_coverage
  accepted_evidence_hashes
  qualification_references
  contract_sha256

QualificationRegistry
  accept_and_publish_provider_identity(immutable ProviderIdentityQualificationEnvelope)
  accept_and_publish(immutable FactorQualificationContract)
  resolve_provider_identity_exact(
    runtime_identity_probe: RuntimeIdentityProbe
  ) -> ProviderIdentityResolution
       status: ACCEPTED | OPEN | FAILED_FOR_EXACT_VERSION | MISSING
       envelope: exact ProviderIdentityQualificationEnvelope only when ACCEPTED
       contract_id, qualification_contract_version, contract_sha256, reason_codes
  resolve_factor_exact(
    business_semantic_version, metric_identity_version, source_identity_version,
    provider_identity_version, derivation_version,
    qualification_contract_version, profile_version_id, factor_id
  ) -> FactorQualificationResolution
       status: ACCEPTED | OPEN | FAILED_FOR_EXACT_VERSION | MISSING
       contract: exact FactorQualificationContract only when ACCEPTED
       contract_id, qualification_contract_version, contract_sha256, reason_codes

ResolvedFormalQualificationBundle
  provider_identity_envelope: exact ACCEPTED ProviderIdentityQualificationEnvelope
  factor_contracts: exact ACCEPTED tuple[FactorQualificationContract, ...]
  bundle_sha256
```

`QualificationRegistry`, `ProviderIdentityQualificationEnvelope`, and `FactorQualificationContract` own acceptance. The application service resolves an exact `ResolvedFormalQualificationBundle` and passes it to the gateway. The gateway never resolves or accepts a contract: it verifies/enforces the service-resolved provider and factor contract IDs, versions, and hashes before passing evidence to the evaluator. The evaluator remains a pure business-threshold consumer and never selects a provider or decides compatibility. `OPEN`, `FAILED_FOR_EXACT_VERSION`, missing, or hash-mismatched provider/factor contracts stop before evaluator, `build_snapshot()`, or persistence. `universe-snapshot/v2` binds the exact provider-envelope and factor-contract IDs/versions/hashes; SQLite stores that binding but does not decide it.

### 4.4 `QOT_RIGHT` and subscription evidence

`QOT_RIGHT` remains `CHANGE_EVENT_AUDIT_ONLY`:

- a captured event proves only that a change event was observed;
- no captured event proves only that none was observed during the capture window;
- neither state proves current account rights or per-code data usability;
- handler setup or capture failure cannot block a qualification whose required capabilities all succeed;
- if captured, raw events and hashes may be attached as supplemental diagnostics only.

`query_subscription()` remains quota/lifecycle audit evidence only. It is not invoked by the production qualification path. The existing single-code real-time quote probe remains scope-limited test/diagnostic functionality and is not a scalable universe authority.

## 5. Formal Qualification Contract

### 5.1 Inputs

The public production command requires:

- an explicit caller-generated `request_id` representing one user action;
- one exact `profile_version_id`;
- `command_schema_version`; and
- no caller-controlled clock, session, readiness, or snapshot-kind field.

Configured Futu host/port, allowed adapter settings, the application clock, `QualificationRegistry`, and the existing SQLite database authority are service dependencies, not public command values. The service resolves the exact published Profile Version and all seven independent A–G bindings. Its only pre-bundle provider operation is to ask the gateway/adapter for the non-authorizing `RuntimeIdentityProbe` in Section 4.3. From that exact observed tuple it resolves the provider/OpenD envelope and every exact accepted `FactorQualificationContract`; it must do so before accepting a concrete clock contract, calendar derivation, or FORMAL collection. The caller cannot supply or override `requested_at_utc`, a contract, provider identity, profile payload/hashes, `snapshot_kind`, `as_of_date`, or `formal_ready` flag.

### 5.2 Qualification predicate

Let `Q` be the final provider qualification predicate:

```text
Q = runtime_state_valid
    AND exact_provider_identity_envelope_accepted
    AND observed_provider_identity_equals_service_resolved_envelope
    AND every_required_factor_contract_is_exactly_accepted
    AND clock_authority_consistent
    AND every_required_capability_succeeded
    AND every_candidate_has_exact_required_evidence
    AND qualified_market_state_consistency_holds
    AND formal_collection_window_reachability_contract_holds
    AND formal_collection_window_is_terminal_closed
    AND temporal_coherence_contract_holds
    AND every_required_factor_contract_holds
    AND suspension_freshness_contract_holds
    AND gateway_reason_codes_is_empty
```

`GatewayAttempt.attempt_status` may be `SUCCEEDED` and `Completeness.COMPLETE` only when `Q` is true. `GatewayPreflight.formal_ready` may be true only when the exact runtime identity is equal to the service-resolved accepted provider envelope and the factor/provider/clock contracts, capability, consistency, and freshness evidence bound into that attempt makes `Q` true. An `OPEN`, `FAILED_FOR_EXACT_VERSION`, missing, or hash-mismatched provider/factor contract or envelope makes `Q` false and stops before evaluator, snapshot build, or persistence.

This capability predicate supersedes the baseline’s unconditional `NOT_YET_QUALIFIED` account/right constants. It does not supersede the existing structural, profile, evaluation, or snapshot invariants.

### 5.3 Evidence completeness

For candidate key set `C`:

```text
keys(discovery)      == C
keys(screen)         == C
keys(snapshot)       == C
keys(market_state)   == C
keys(owner_plate)    == C
keys(classification) == C
keys(prerequisites)  == C
keys(evaluations)    == C
keys(temporal_verdicts) == C
```

Duplicate normalized keys, missing keys, extra unmapped keys, conflicting identity, malformed fields, partial pagination, or count mismatch makes the attempt `FAILED` / `INCOMPLETE`.

An explicitly inconclusive classification/prerequisite decision that the existing domain contract can represent with complete evidence is retained and will quarantine the security under the current evaluator. A field required by the selected published profile that is absent, unparseable, or unsupported is missing required evidence and makes the provider attempt incomplete. “Unknown decision supported by evidence” is different from “required provider evidence missing.”

### 5.4 Connection identity

No undocumented Futu “connection ID” field is assumed.

**Proposed Interface — `OpenDConnectionIdentity`**

```text
OpenDConnectionIdentity
  application_context_instance_id: immutable ID generated when the adapter creates the context
  configured_host
  configured_port
  provider_sdk_version
  opend_server_version
  provider_identity_contract_id
  provider_identity_contract_version
  provider_identity_contract_sha256
  runtime_identity_probe_sha256
  global_state_response_hashes: exact start/end tuple
  connection_identity_sha256
  provider_connection_id: optional, only when returned by a documented SDK field
```

`application_context_instance_id` is non-secret, process-local identity evidence, not a provider ID. The future gateway/adapter, not the application service, must create exactly one quote context for an attempt, assign this immutable ID at context creation, route the `RuntimeIdentityProbe` and every later required call through that same object, and close it in one `finally` path. `connection_identity_sha256` is an application-generated canonical hash of the preceding non-optional fields. Its `runtime_identity_probe_sha256`, observed provider/SDK/OpenD values, and provider-identity contract ID/version/hash must exactly equal the service-resolved `ProviderIdentityQualificationEnvelope`; a missing or mismatch fails closed. When a supported documented Python mapping exposes `connID`, probe/start/end values must all be present and exactly equal; when it does not, the persisted application context ID plus enforced object reuse is the same-context proof. This identity proves context reuse only; it neither accepts a provider envelope, proves acquisition brackets, nor substitutes for their future evidence. UI and acceptance evidence must label both identities accurately and never present the application ID as provider-issued.

### 5.5 Published profile and `CORE:v1`

- Only an exact `PUBLISHED` profile version may produce `FORMAL`.
- `DRAFT` may produce only `PREVIEW` through existing boundaries and is outside this production command.
- `CORE:v1` remains immutable. M3C-A2 neither republishes it nor changes its rule payload or hashes.
- The persisted snapshot must bind the exact resolved profile version and existing content/filter hashes.

### 5.6 Required future attempt provenance

The successful snapshot-bound attempt, and the sanitized diagnostic record for a failed attempt, must account for:

- application connection identity, configured host/port, SDK version, OpenD version, and the non-authorizing runtime-identity-probe hashes/provenance;
- application-clock request time, monotonic ordering evidence, collection start/completion, and every **future gateway-captured** request-send/response-receive acquisition bracket;
- raw/normalized `get_global_state.timestamp` and `local_timestamp`, their clock-consistency verdicts, and both global-state hashes;
- endpoint/evidence type, raw response references, and raw response hashes;
- every required capability verdict and expected/observed coverage count;
- locked XNYS session/date, regular close, start/end provider lifecycle states, and the exact temporal-window verdict;
- raw and normalized provider evidence timestamps plus every per-code temporal verdict; no single oldest watermark substitutes for per-code proof;
- exact provider identity envelope plus temporal coherence, collection-window reachability, per-factor, suspension freshness, clock authority, and market-state consistency contract identities/versions/hashes;
- optional, explicitly out-of-band quota and `QOT_RIGHT` audit evidence;
- final blockers and stable reason codes;
- profile, mapping, prerequisite, member, content, record, and attempt hashes already required by the domain contract.

**Proposed Interface — `FormalQualificationProvenance`** is the application-owned assembly of these existing evidence/reference values. It must be embedded through the snapshot attempt/header contract rather than persisted as a competing membership record.

### 5.7 Proposed immutable schema binding

The baseline `universe-snapshot/v1` header does not contain all M3C-A2 qualification fields. A future implementation must therefore make an explicit schema evolution; putting the new values only in `FormalSnapshotBuildResult` or `audit_events` is insufficient.

**Proposed Interface — additions to `GatewayAttempt`**

```text
connection_identity: OpenDConnectionIdentity
runtime_identity_probe: RuntimeIdentityProbe
provider_identity_envelope: ProviderIdentityQualificationEnvelope
provider_identity_contract_id
provider_identity_contract_version
provider_identity_contract_sha256
service_resolved_qualification_bundle_sha256
formal_requested_at_utc: aware UTC datetime
collection_started_at_utc: aware UTC datetime
collection_completed_at_utc: aware UTC datetime
locked_session_close_at_utc: aware UTC datetime
locked_session_open_at_utc: aware UTC datetime
completion_session: date
completion_session_close_at_utc: aware UTC datetime
provider_lifecycle_start
provider_lifecycle_end
market_state_start_batch_hashes
market_state_end_batch_hashes
api_acquisition_brackets: tuple[ApiAcquisitionBracket, ...]
clock_authority_evidence: ClockAuthorityEvidence
temporal_coherence_contract: FormalSnapshotTemporalCoherenceContract
formal_collection_window_reachability_contract: QualifiedFormalCollectionWindowReachabilityContract
factor_qualification_contracts: tuple[FactorQualificationContract, ...]
suspension_freshness_contract: QualifiedSuspensionFreshnessContract
per_code_temporal_verdicts: tuple[SecurityTemporalVerdict, ...]
per_code_factor_temporal_verdicts: tuple[SecurityFactorTemporalVerdict, ...]
required_capability_verdicts: tuple[RequiredCapabilityVerdict, ...]
qualification_provenance_sha256: SHA-256
```

**Proposed Interfaces — persisted per-code verdicts**

```text
SecurityTemporalVerdict
  normalized_code
  snapshot_call_ordinal
  locked_as_of_date
  effective_session_date
  raw_update_time
  provider_update_local_date
  normalized_update_time_utc
  snapshot_suspension
  raw_security_status
  market_state_start_raw
  market_state_start_relationship
  market_state_end_raw
  market_state_end_relationship
  stale_price_exception_status: APPLIED | EXCEPTION_NOT_APPLIED
  evidence_sha256s
  verdict: SUCCEEDED | FAILED
  reason_codes
  verdict_sha256

SecurityFactorTemporalVerdict
  normalized_code
  factor_id
  business_semantic_version
  metric_identity_version
  source_identity_version
  provider_identity_version
  derivation_version
  qualification_contract_version
  profile_version_id
  provider_identity_contract_id
  provider_identity_contract_version
  provider_identity_contract_sha256
  raw_value
  evidence_call_ordinal
  locked_as_of_date
  effective_session_date
  canonical_evidence_request_sha256
  canonical_evidence_response_sha256
  derivation_input_sha256s
  factor_contract_sha256
  qualification_reference_sha256s
  verdict: SUCCEEDED | FAILED
  reason_codes
  verdict_sha256
```

The existing field name remains `attempt_status`, not `status`. A successful per-code verdict requires `locked_as_of_date == effective_session_date == UniverseSnapshotHeader.as_of_session`; a non-exempt snapshot row additionally requires `provider_update_local_date` to equal that date. A successful factor verdict requires its `locked_as_of_date` and `effective_session_date` to equal the same header session date. The service-resolved provider-envelope ID/version/hash must exactly equal `OpenDConnectionIdentity`, `GatewayAttempt`, every factor contract's provider reference, and the later header projection; missing or mismatched bindings are invariant failures. All proposed fields participate in `gateway_attempt_sha256`, `snapshot_content_sha256`, and `snapshot_record_sha256`; capability verdicts use canonical capability-ID order and canonical batch-hash order.

**Proposed Interface — additions to `UniverseSnapshotHeader`**

```text
formal_request_id
formal_intent_sha256
formal_command_sha256
formal_requested_at_utc
gateway_connection_identity
gateway_runtime_identity_probe
gateway_provider_identity_envelope
gateway_provider_identity_contract_id
gateway_provider_identity_contract_version
gateway_provider_identity_contract_sha256
gateway_service_resolved_qualification_bundle_sha256
gateway_collection_started_at_utc
gateway_collection_completed_at_utc
gateway_locked_session_close_at_utc
gateway_locked_session_open_at_utc
gateway_completion_session
gateway_completion_session_close_at_utc
gateway_provider_lifecycle_start
gateway_provider_lifecycle_end
gateway_market_state_start_batch_hashes
gateway_market_state_end_batch_hashes
gateway_api_acquisition_brackets
gateway_clock_authority_evidence
gateway_clock_authority_sha256
gateway_temporal_coherence_contract
gateway_temporal_coherence_sha256
gateway_formal_collection_window_reachability_contract
gateway_formal_collection_window_reachability_sha256
gateway_factor_qualification_contracts
gateway_factor_qualification_contract_sha256s
gateway_suspension_freshness_contract
gateway_suspension_freshness_sha256
gateway_per_code_temporal_verdicts
gateway_per_code_factor_temporal_verdicts
gateway_required_capability_verdicts
gateway_qualification_provenance_sha256
```

The writer emits exact `snapshot_schema_version = universe-snapshot/v2`. These fields are part of `snapshot_content_sha256` and `snapshot_record_sha256`; `formal_request_id`, `formal_intent_sha256`, and `formal_command_sha256` are therefore immutable replay bindings. The header also binds the exact runtime-identity probe, accepted provider-envelope ID/version/hash, service-resolved qualification-bundle hash, exact A–G factor/version tuple, and exact accepted contract ID/version/hash for every required factor. `build_snapshot()` must assert exact equality between this header projection, the service-resolved bundle, and the supplied `GatewayAttempt` before it can create `FORMAL`.

The future audit codec allowlist, encoder, decoder, ownership freeze, and hash tests must be extended for the proposed value objects. Future `ApiAcquisitionBracket` values use canonical call order. `SecurityTemporalVerdict` values use canonical normalized-code order. `SecurityFactorTemporalVerdict` values use canonical `(normalized_code, factor_id)` order. Duplicate ordering keys, missing candidates/factors, or noncanonical ordering are invariant failures. Readers must retain explicit `universe-snapshot/v1` read compatibility, but only `universe-snapshot/v2` can satisfy this M3C-A2 production qualification contract. SQLite stores the canonical aggregate in `payload_json` and the schema tag in `schema_version`; it stores, but never decides, qualification. No parallel snapshot table or payload is introduced. The command claim in Section 7 uses the existing `audit_events.event_id` primary key and therefore requires no snapshot-table rewrite or second source of truth.

## 6. Formal Snapshot Temporal Coherence Contract

### 6.1 Meaning of a FORMAL `as_of_date`

A FORMAL Universe Snapshot represents one **completed provider-session authority**, not an arbitrary live observation labeled with the latest completed regular session.

Definitions:

- `requested_at_utc`: the service-owned application-clock time bound into the internal command envelope before any provider request;
- `collection_started_at_utc`: application-clock time immediately before the first required provider request;
- `collection_completed_at_utc`: application-clock time immediately after the final required provider response;
- `locked_session`: the latest completed XNYS regular session derived independently at all three application-clock instants;
- `as_of_date`: exactly `locked_session.date()`;
- `locked_session_open_at_utc` and `locked_session_close_at_utc`: XNYS calendar boundaries for that session;
- `provider_terminal_closed`: a **normalized per-security relationship** proving that the security cannot emit further price/factor evidence belonging to, or following, `as_of_date` before the next XNYS session lifecycle begins. Raw Futu states may differ across securities; `AFTER_HOURS_END` is not terminal for a security that has entered `OVERNIGHT`, and `OVERNIGHT` is next-session-active rather than terminal for the prior `as_of_date`;
- `provider evidence temporal window`: the interval whose session label is `as_of_date`, begins at the locked XNYS session open, and is closed only when the qualified provider lifecycle reaches `provider_terminal_closed`.

XNYS supplies the regular-session identity and calendar boundaries. The provider market-state contracts supply pre-market/regular/after-hours lifecycle state. No hard-coded pre-market or after-hours clock time is introduced.

### 6.2 Proposed Interface — `FormalSnapshotTemporalCoherenceContract`

```text
FormalSnapshotTemporalCoherenceContract
  provider
  provider_sdk_version
  opend_server_version
  provider_identity_contract_id
  provider_identity_contract_version
  provider_identity_contract_sha256
  exchange_calendar: XNYS
  calendar_version
  provider_timezone: America/New_York
  market_state_consistency_sha256
  terminal_closed_relationship_sha256
  formal_collection_window_reachability_sha256
  factor_qualification_contract_sha256s
  suspension_freshness_sha256
  clock_authority_sha256
  qualification_references
  contract_sha256
```

The exact contract succeeds only when all of the following hold:

1. the clock-authority contract in Section 6.5 succeeds before calendar derivation is trusted;
2. `requested_at_utc`, `collection_started_at_utc`, and `collection_completed_at_utc` independently derive the same `locked_session`, session open, and session close;
3. `as_of_date == locked_session.date()` everywhere: command result, preflight, gateway attempt, evaluations, funnel, and snapshot header;
4. every candidate has an exact per-code market-state observation before dynamic/factor collection and another after it;
5. both market-state observations satisfy the exact `QualifiedMarketStateConsistencyContract`; every candidate maps to `provider_terminal_closed` for the same `as_of_date` at both bookends, while raw per-security states may differ;
6. no required response acquisition bracket crosses a change out of the qualified terminal-closed relationship;
7. every non-exempt `get_market_snapshot().update_time`, parsed as `America/New_York`, has local calendar date exactly equal to `as_of_date`, is not earlier than the locked session open, and is not later than that batch's `response_received_at_utc`;
8. every CORE v1 factor independently satisfies its exact accepted `FactorQualificationContract` in Section 4.3;
9. a stale-price timestamp exception is used only for a security proven suspended/halted by Section 6.4;
10. all temporal verdicts and contract hashes are persisted and participate in attempt/content/record hashes.

The former predicate `update_time >= locked completed session close` is removed. It cannot distinguish Monday intraday data from a Friday `as_of_date`.

### 6.3 State/window decision table

| Request/collection condition | `as_of_date` candidate | Formal temporal verdict | Reason |
|---|---|---|---|
| Current XNYS regular session is open | previous completed session | Block before full collection | Current-session live evidence could be mislabeled as the previous session |
| Current provider state is pre-market for the next XNYS session | previous completed session | Block | Provider lifecycle has left terminal-closed state; current-session evidence may already exist |
| Current provider state is after-hours but not terminal | current completed regular session | Block | Extended-hours evidence for the date can still change |
| Provider state has reached exact qualified terminal-closed after after-hours end | current completed session | Eligible to continue, subject to all per-code/factor/clock checks | The provider lifecycle for `as_of_date` is complete |
| Any candidate is `OVERNIGHT` after another candidate reports `AFTER_HOURS_END` | current completed regular session | Block | `OVERNIGHT` is active next-session evidence for that security; mixed raw states are allowed only when all map to the same completed-session terminal relationship |
| Weekend | latest prior XNYS session | Eligible only if start/end states remain terminal-closed and every evidence date/contract still binds to that session | No newer provider session may be mixed in |
| XNYS holiday | latest prior XNYS session | Same as weekend | Holiday alone does not waive provider-state or factor contracts |
| Collection crosses regular close | start/end locked session or state differs | `SESSION_BOUNDARY_CROSSED` | Never relabel or mix evidence silently |
| Collection crosses after-hours terminal boundary | state relationship changes during attempt | `PROVIDER_LIFECYCLE_BOUNDARY_CROSSED` | A single attempt cannot mix open and terminal evidence |
| Collection crosses from terminal-closed into the next pre-market/session lifecycle | locked session may still be unchanged while provider state changes | `NEXT_SESSION_BOUNDARY_CROSSED` | Calendar equality alone is insufficient |
| Any snapshot row date differs from `as_of_date` | any | `TEMPORAL_DATE_MISMATCH` | Prevents current-day data from being written under a previous session |
| UTC or `America/New_York` civil date changes while locked XNYS session, normalized provider relationship, and evidence-local dates remain unchanged | unchanged | Does not fail by itself | A civil-midnight boundary is not a session boundary |

**Proposed Interface — `QualifiedFormalCollectionWindowReachabilityContract`**

```text
QualifiedFormalCollectionWindowReachabilityContract
  provider
  provider_sdk_version
  opend_server_version
  provider_identity_contract_id
  provider_identity_contract_version
  provider_identity_contract_sha256
  market_state_consistency_sha256
  raw_state_to_session_relationship_mapping
  overnight_eligibility_evidence_contract
  representative_security_cohorts
  supported_window_classes: exact set of WEEKDAY | WEEKEND | XNYS_HOLIDAY
  unsupported_window_classes
  qualified_calendar_regimes: exact set drawn from STANDARD | EARLY_CLOSE | DST_SPRING_FORWARD | DST_FALL_BACK | WEEKEND | XNYS_HOLIDAY
  regime_observations: local/UTC open-close boundaries, UTC offsets, lifecycle bookends, acquisition brackets, and raw hashes
  negative_boundary_observations: PREMARKET | REGULAR | NONTERMINAL_AFTER_HOURS | OVERNIGHT | NEXT_SESSION_ACTIVE
  qualification_observation_references
  qualification_observation_hashes
  qualified_at_utc
  contract_sha256
```

The exact candidate set need not share one raw state. It must share one normalized `COMPLETED_SESSION_TERMINAL_CLOSED(as_of_date)` relationship at both bookends. `OVERNIGHT`, premarket, regular trading, nonterminal after-hours, unknown mapping, or a candidate-set combination for which no common terminal relationship was demonstrated yields `FORMAL_WINDOW_UNREACHABLE_FOR_CANDIDATE_SET` and no FORMAL snapshot. If qualification proves no safe weekday window for the full CORE universe, weekday FORMAL builds are intentionally unsupported; only exact qualified weekend/holiday windows may proceed. The service never pretends daily availability and never drops overnight-eligible candidates to create a window.

The service does not wait for a window to open and does not retry automatically. A new explicit command is required after a temporal blocker.

### 6.4 Suspension and halt semantics

Futu documents `suspension` and current-price `update_time`, but the current contract does not establish that a legitimately suspended security's price timestamp refreshes to the completed session. Therefore `suspension=True` cannot be ignored, and a stale timestamp cannot be accepted without separate qualification.

**Proposed Interface — `QualifiedSuspensionFreshnessContract`**

```text
QualifiedSuspensionFreshnessContract
  provider
  provider_sdk_version
  opend_server_version
  provider_identity_contract_id
  provider_identity_contract_version
  provider_identity_contract_sha256
  snapshot_schema_version
  suspension_field
  recognized_security_status_values
  required_cross_field_consistency
  independent_currentness_evidence_contract
  allowlisted_stale_price_status_mappings
  update_time_exception_scope: CURRENT_PRICE_ONLY
  required_start_end_market_state_relationship
  qualification_references
  qualified_at_utc
  contract_sha256
```

Boundary rules:

| Evidence condition | Boundary | Result |
|---|---|---|
| Exact per-code row, `suspension=True`, recognized/consistent status, all structural evidence present, and exact suspension contract qualified | Security-level | Existing `normalized_active_status()` produces S4 `FAIL / SUSPENDED_AS_OF_SNAPSHOT`; the attempt may remain `SUCCEEDED / COMPLETE`; only the current-price `update_time` date equality is exempted |
| Complete evidence with `suspension=False` but an otherwise recognized status that maps to an explicit non-pass decision | Security-level | Existing qualified Active mapping determines `FAIL` or `QUARANTINE`; normal temporal rules still apply |
| Complete evidence with an unrecognized but structurally valid status | Security-level | S4 `UNKNOWN / ACTIVE_STATUS_UNKNOWN`, therefore quarantine under existing evaluator semantics; normal temporal rules still apply |
| Missing/non-boolean suspension, conflicting suspension/status, absent contract, contract hash/version mismatch, or stale timestamp claimed as suspended without qualification | Provider-level | `GatewayAttempt.FAILED / INCOMPLETE`, `formal_ready=false`, no snapshot append |
| Missing/malformed required factor evidence or other required evidence for a suspended security | Provider-level | No suspension waiver; the attempt remains incomplete |

The exact-version `QualifiedSuspensionFreshnessContract` is an unconditional prerequisite for every FORMAL attempt, including attempts in which no candidate is suspended. Every security records `APPLIED` or `EXCEPTION_NOT_APPLIED`; absence of a suspended row never turns the contract into `is_not_needed`. `allowlisted_stale_price_status_mappings` may contain only exact independently qualified suspended/halted mappings. `UNKNOWN`, a generic no-trade condition, or an unrecognized status is never eligible for the stale-price exception.

The exception is deliberately narrow: it proves only that the suspension/halt state is current enough to exclude the security at S4. It does not make stale prices current, authorize other stale fields, change S0-S10 semantics, or convert a missing provider row into a security-level result. The required tiny qualification spike is listed in Section 17.

### 6.5 Future replacement clock authority

This is a future replacement contract, ordered after exact provider identity acceptance and future gateway bracket/canonical-evidence retention. The current production adapter has only `acquired_at_utc` and cannot satisfy this bracket contract. The application UTC clock is the primary authority for future command time, XNYS calendar lookup, acquisition brackets, and future-data rejection. It consists of one aware-UTC wall-clock anchor plus monotonic projection; subsequent raw wall reads are corroboration, not a way to enlarge a request bracket after a clock step.

`get_global_state()` supplies two independent corroborating values:

- raw `timestamp`: provider/server current GMT epoch time in whole seconds;
- raw `local_timestamp`: current epoch time on the machine running OpenD.

Neither value replaces the application clock. Both qualify it for the attempt.

**Proposed Interfaces — `ApplicationClockAnchor` and `ClockAuthorityEvidence`**

```text
ApplicationClockAnchor
  wall_read_at_utc
  wall_clock_resolution
  monotonic_before_wall_read
  monotonic_after_wall_read
  anchor_sha256

ClockAuthorityEvidence
  command_clock_anchor: ApplicationClockAnchor
  global_state_start_bracket_sha256
  global_state_end_bracket_sha256
  raw_wall_checkpoint_samples
  monotonic_projected_utc_intervals
  raw_server_timestamp_start
  raw_server_timestamp_end
  normalized_server_second_interval_start
  normalized_server_second_interval_end
  raw_opend_local_timestamp_start
  raw_opend_local_timestamp_end
  normalized_opend_local_timestamp_start
  normalized_opend_local_timestamp_end
  global_state_response_hashes
  verdict
  reason_codes
  evidence_sha256
```

Threshold-free validation:

1. Capture the command anchor in fixed read order `monotonic_before -> aware UTC wall -> monotonic_after`; monotonic values must be finite and nondecreasing, and the wall clock's documented/runtime-observed resolution must be recorded rather than guessed.
2. For any later monotonic value `m`, project its authoritative UTC uncertainty interval from the anchor as `[W + (m - m_after), W + R + (m - m_before)]`, where `W` is the anchor wall value and `R` its recorded resolution. All calendar and provider-request boundaries use these projected intervals.
3. Every later raw wall sample is itself bracketed by monotonic reads. Its resolution interval must overlap the UTC interval projected from those monotonic reads. A forward or backward wall-clock step therefore cannot widen the authoritative bracket; non-overlap yields `CLOCK_AUTHORITY_BLOCKER`.
4. Every `ApiAcquisitionBracket` requires nondecreasing send/receive monotonic values. Its projected send and receive UTC intervals are derived only from the anchor formula, and every raw sent/received wall sample must pass rule 3.
5. An integer server timestamp `s` represents its documented one-second-resolution interval `[s, s + 1 second)`; that interval must overlap the corresponding projected application request envelope from send through receive.
6. Each OpenD local timestamp, with its represented numeric resolution, must overlap the same projected request envelope. Start/end server and OpenD intervals must be nondecreasing and agree with monotonic ordering.
7. The projected UTC intervals for `requested_at`, collection start, and collection completion must each map unambiguously to one XNYS boundary result and all three results must be identical. An interval that straddles a relevant boundary fails closed; it is never collapsed using a midpoint.
8. Any missing/unparseable value, non-overlap, reversal, discontinuity, ambiguous boundary, or disagreement yields `CLOCK_AUTHORITY_BLOCKER` and no calendar/freshness verdict is trusted.

This ties wall elapsed time to monotonic elapsed time using only captured clock resolution and sampling intervals, not an invented skew tolerance. Provider market-data `update_time` is future-dated only when its represented instant/interval lies strictly after the upper bound of the monotonic-projected response interval for the batch that carried it; ambiguous overlap is not called future but must still satisfy the exact `as_of_date` and evidence-window predicates.

### 6.6 Evidence-class rules

| Evidence class | Examples | Validity rule |
|---|---|---|
| Provider-timestamped dynamic | `get_market_snapshot().update_time` and snapshot-derived current fields | Exact per-code date/window verdict under Sections 6.2 and 6.4; an aggregate oldest watermark is diagnostic only |
| Factor evidence | `PRICE_USD`, `EQUITY_MARKET_CAP_USD`, `LISTED_TRADING_SESSIONS`, and future ADV20 | Exact accepted `FactorQualificationContract`, with its A–G versions and required source/derivation hashes; never infer compatibility from another factor, version, or snapshot timestamp |
| Request-scoped current state | future bracketed `get_global_state()`, future bookended `get_market_state()` | Successful shape plus future gateway brackets and exact state/transition contracts |
| Same-attempt static/reference | identity, type/listing flags, owner plate, explicit classification | Complete, internally consistent, provenance-bound, and acquired/resolved in the attempt; no fake market-data timestamp |

### 6.7 Exact consistency binding and blockers

The existing `QualifiedMarketStateConsistencyContract` remains mandatory and exact-bound to provider, SDK version, OpenD version, raw state values, calendar relationships, qualification references, and canonical hash. M3C-A2 additionally requires an exact terminal-closed relationship and permitted-transition contract at both collection bookends.

Formal blockers include:

- naive or non-monotonic application/acquisition timestamps;
- any clock-authority failure;
- unavailable/invalid XNYS calendar or contract version;
- ambiguous/nonexistent provider local timestamp;
- pre-market, regular-open, or nonterminal after-hours state;
- provider lifecycle or XNYS session change during collection;
- snapshot `update_time` wrong date, before locked session open, or future relative to its response bracket;
- `OPEN`, `FAILED_FOR_EXACT_VERSION`, missing, or hash-mismatched exact provider/factor contract;
- an unqualified suspension timestamp exception;
- disagreement among command, preflight, attempt, funnel, and snapshot `as_of_date` or any temporal contract hash.

## 7. Proposed Production Orchestrator

All interfaces in this section are **Proposed Interfaces**, not claims about code that already exists.

### 7.1 Application command and result

```text
FormalSnapshotCommand
  request_id
  profile_version_id
  command_schema_version: formal-snapshot-command/v1

InternalFormalSnapshotCommandEnvelope
  public_command: FormalSnapshotCommand
  formal_intent_sha256
  command_clock_anchor: ApplicationClockAnchor
  formal_requested_at_utc: service-owned aware UTC datetime
  formal_command_sha256

FormalSnapshotBuildResult
  request_id
  status:
    SUCCEEDED
    PROFILE_NOT_PUBLISHED
    PREFLIGHT_FAILED
    COLLECTION_FAILED
    TEMPORAL_QUALIFICATION_FAILED
    EVALUATION_FAILED
    SNAPSHOT_BUILD_FAILED
    PERSISTENCE_FAILED
    REQUEST_ID_CONFLICT
    DUPLICATE_TERMINAL_FAILURE
    UNKNOWN_IN_FLIGHT
  snapshot_id: optional
  gateway_attempt: optional
  capability_verdicts
  diagnostics
```

The service canonicalizes the public command and computes `formal_intent_sha256` from its schema version, request ID, and profile version ID. It then captures the service-owned clock anchor, creates the internal envelope, and computes `formal_command_sha256` over the complete intent, anchor, and derived request time. The public API rejects any timestamp field. These application statuses do not replace the existing `GatewayAttempt.attempt_status` or `Completeness`; they describe the whole command, including persistence.

### 7.2 Service boundary

```text
FormalSnapshotApplicationService.build(command) -> FormalSnapshotBuildResult
```

The application service owns sequencing and resolution of the immutable exact qualification bundle. It delegates provider transport/context lifecycle, domain evaluation, snapshot construction, and persistence to their existing authorities. It coordinates the gateway/adapter's sole non-authorizing `RuntimeIdentityProbe`, then resolves and passes the bundle; it never opens, retains, or closes a quote context. The gateway receives that resolved bundle and only verifies/enforces it; it never resolves or accepts provider/factor compatibility.

### 7.3 Required sequence

1. Validate the public command, reject caller-supplied timestamp/session/readiness/provider/contract fields, canonicalize the intent, and compute `formal_intent_sha256`.
2. Derive a deterministic UUIDv5 `snapshot_id` from a fixed application namespace plus `request_id`; capture the service-owned command anchor/envelope and atomically claim it before any provider operation. Existing duplicate/conflict/terminal-failure rules remain fail-closed and make zero provider calls.
3. For a new claim, resolve the exact published Profile Version through `ProfileRepository.get_published()` on the same SQLite authority as `SnapshotRepository`, including all required A–G version bindings.
4. Ask the gateway/adapter to create and retain one quote context and return its immutable, non-authorizing `RuntimeIdentityProbe`. It captures only the documented provider/SDK/OpenD tuple plus mapping/capability versions and canonical hashes/provenance; it is not clock, factor, or FORMAL evidence. Structural probe failure is terminal. This is the sole provider discovery operation allowed before the bundle.
5. Resolve `ProviderIdentityResolution` through `QualificationRegistry.resolve_provider_identity_exact()` from the probe and every `FactorQualificationResolution` through `resolve_factor_exact()`. Construct one immutable `ResolvedFormalQualificationBundle` from the accepted provider envelope and accepted factor contracts, and pass it to the gateway. `1009` may match only its own legacy exact envelope. Observed `1010` may not reuse it. If any result is `OPEN`, `FAILED_FOR_EXACT_VERSION`, missing, or hash-mismatched — including ADV20 — record a terminal qualification failure before clock acceptance, FORMAL gateway collection, evaluator, build, or persistence; the gateway/adapter closes the retained context.
6. Only after Step 5, use the service-owned anchor and XNYS calendar to derive the candidate completed session. If the application instant is inside regular trading or no completed session exists, fail without full collection; the service does not wait, retry, or silently relabel.
7. The **future gateway** retains the context created in Step 4, receives the service-resolved `ResolvedFormalQualificationBundle`, captures one canonical `ApiAcquisitionBracket` plus canonical SDK-level request/response/row evidence for every required call, and verifies/enforces exact equality of the probe, later observed provider identity, and every provider/factor contract ID/version/hash before it freezes candidate set `C`. Current `RawApiBatch` / `RawApiPage` cannot satisfy this step with `acquired_at_utc` alone.
8. The gateway acquires future start/end `market_state` bookends and required Market Snapshot factor fields. It requires the exact accepted state/window contract, proves the bookends still equal the probe and accepted envelope, and requires every candidate to map to `COMPLETED_SESSION_TERMINAL_CLOSED` for the candidate session. Raw states may differ; normalized relationships may not.
9. Freeze `locked_as_of_session` and `as_of_date` only from XNYS and the qualified start provider lifecycle. No later evidence may move or relabel the lock.
10. Before evaluator input, the gateway verifies exact row coverage, source/derivation evidence, the accepted A–G factor versions, the service-resolved provider-envelope and factor-contract IDs/versions/hashes, and all clock/window/suspension predicates. It returns a terminal qualification failure for any unproven or mismatched contract; the evaluator, `build_snapshot()`, and persistence are not called.
11. Only after Step 10, run existing per-security evaluation and `build_funnel()`. The evaluator consumes qualified business evidence and thresholds only; it never decides provider compatibility.
12. Call `build_snapshot(kind=FORMAL, ...)` with deterministic identity, the exact service-resolved provider envelope/factor contracts, future bracket/clock evidence, locked-session evidence, and verdicts. It emits only `universe-snapshot/v2` for this path.
13. Call only `SnapshotRepository.append(snapshot)`. SQLite stores the accepted bindings; it does not decide qualification.
14. Reopen with `SnapshotRepository.get(snapshot_id)` and verify exact hashes, request/intent equality, service-resolved provider-envelope ID/version/hash, A–G bindings, exact factor contracts, and all v2 qualification fields. Return `SUCCEEDED` only after this verification.

### 7.4 Attempt diagnostics repository

**Proposed Interface — `QualificationAttemptRepository`**

This repository uses the existing `audit_events` table; it does not introduce a second snapshot store or a membership authority.

```text
claim(public_command, formal_intent_sha256, internal_envelope, snapshot_id)
  -> CLAIMED_NEW | CLAIMED_EXISTING_SAME | REQUEST_ID_CONFLICT
append_failed(request_id, application_status, diagnostics, created_at_utc)
get_state(request_id, formal_intent_sha256) -> NONE | STARTED | TERMINAL_FAILED | CONFLICT
```

Rules:

- `claim()` performs a single `BEGIN IMMEDIATE` transaction and attempts one `audit_events` insert whose deterministic primary key is `formal-snapshot-claim:{request_id}`; it never performs a check-then-insert sequence;
- the claim payload contains the canonical public intent, `formal_intent_sha256`, the first service-owned internal envelope and `formal_command_sha256`, and deterministic snapshot ID; on primary-key conflict the same transaction reads the existing claim and returns `CLAIMED_EXISTING_SAME` only after exact public-intent and snapshot-ID equality, otherwise `REQUEST_ID_CONFLICT`;
- an identical replay never replaces or re-hashes the stored service-owned time envelope; it uses the originally persisted `formal_command_sha256` and performs zero provider calls;
- the existing `audit_events.event_id` primary key is the compare-and-set uniqueness boundary, so no new command table or competing snapshot store is required;
- events are append-only;
- diagnostics contain canonical reason codes, capability verdicts, raw evidence references/hashes, and exception class/message sanitized of credentials;
- successful provider evidence is already embedded in the immutable snapshot aggregate and need not be duplicated as authority in `audit_events`;
- audit records may explain failure but can never authorize M3D membership;
- no secret, account identifier, API key, or raw credential is persisted.

### 7.5 Crash and duplicate behavior

- A duplicate successful `request_id` resolves to the deterministic persisted snapshot and performs zero provider calls.
- The same request ID with any different public profile, schema version, intent hash, or deterministic snapshot binding returns `REQUEST_ID_CONFLICT` and performs zero provider calls. Public request time does not exist.
- A duplicate terminal failure performs zero provider calls; a new explicit click creates a new request ID.
- An ambiguous `STARTED` record after a crash is fail-closed as `UNKNOWN_IN_FLIGHT`. The operator must explicitly acknowledge and issue a new command; the system does not guess whether external calls completed.
- `SnapshotRepository.append()` retains its existing idempotency: same snapshot ID and record hash is accepted; conflicting content is rejected.

## 8. Fail-Closed Decision Table

`formal_ready` below refers to `GatewayPreflight.formal_ready`; “Persist” means appending a `FORMAL` snapshot, not appending failure diagnostics.

| Condition | Gateway attempt | Completeness | `formal_ready` | Persist FORMAL? | UI outcome | M3D eligible? |
|---|---|---:|---:|---:|---|---:|
| OpenD unreachable or `get_global_state()` fails | `FAILED` | `INCOMPLETE` | false | No | Show runtime blocker and reason code | No |
| `qot_logined` false/unknown | `FAILED` | `INCOMPLETE` | false | No | Show quote-login blocker | No |
| `program_status_type != READY` | `FAILED` | `INCOMPLETE` | false | No | Show OpenD status blocker | No |
| SDK/OpenD version absent, `OPEN`, `FAILED_FOR_EXACT_VERSION`, or not bound to an exact accepted identity envelope | `FAILED` | `INCOMPLETE` | false | No | Show exact version/contract blocker; never reuse a `1009` mapping/hash for `1010` | No |
| Application UTC, provider `timestamp`, or OpenD `local_timestamp` fails the request-bracket/monotonic clock contract | `FAILED` | `INCOMPLETE` | false | No | Show `CLOCK_AUTHORITY_BLOCKER` with the failed predicate; never apply arbitrary skew | No |
| Requested instant is premarket, within the regular XNYS session, or ordinary/nonterminal after-hours | `FAILED` | `INCOMPLETE` | false | No | Show `FORMAL_COLLECTION_WINDOW_NOT_CLOSED`; do not wait or label the prior session | No |
| Any start/end per-code provider state maps to mixed normalized relationships, unknown, nonterminal, or a lifecycle transition | `FAILED` | `INCOMPLETE` | false | No | Show market-state/lifecycle blocker and require a new command; different raw states are not failure when all map terminal for the same session | No |
| Any candidate is `OVERNIGHT`/next-session-active, or the exact candidate set has no qualified common terminal window | `FAILED` | `INCOMPLETE` | false | No | Show `FORMAL_WINDOW_UNREACHABLE_FOR_CANDIDATE_SET`; never omit the candidate | No |
| Start/end authority resolves to different XNYS sessions or the next session becomes active | `FAILED` | `INCOMPLETE` | false | No | Show `NEXT_SESSION_BOUNDARY_CROSSED`; never relock | No |
| Any required endpoint transport failure | `FAILED` | `INCOMPLETE` | false | No | Show failed capability and batch evidence | No |
| Provider returns permission denied or unsupported market for any required call | `FAILED` | `INCOMPLETE` | false | No | Show exact capability, endpoint, and sanitized provider blocker | No |
| Partial page, missing/duplicate/extra per-code row, or malformed required field | `FAILED` | `INCOMPLETE` | false | No | Show exact count/key mismatch | No |
| Non-suspended current-price `update_time` is invalid/future or its provider-local date differs from exact `as_of_date` | `FAILED` | `INCOMPLETE` | false | No | Show `TEMPORAL_DATE_MISMATCH` or `FUTURE_PROVIDER_TIMESTAMP` and the exact code | No |
| Any required factor contract is `OPEN`, `FAILED_FOR_EXACT_VERSION`, missing, or hash-mismatched | `FAILED` | `INCOMPLETE` | false | No | Show exact factor/contract blocker before evaluator | No |
| ADV20 has no accepted alternate scalable authority | `FAILED` | `INCOMPLETE` | false | No | Show `ADV20_WINDOW_UNQUALIFIED`; Stock Screen `3105` None/True/False are rejected | No |
| LISTED evidence lacks a valid `listing_date`, named/versioned XNYS artifact, selected-session hash, both-inclusive derivation, or required new Profile Version | `FAILED` | `INCOMPLETE` | false | No | Show factor/profile-version blocker | No |
| Snapshot says `suspension=True`, that state is independently qualified current, and all other required evidence is complete | `SUCCEEDED` | `COMPLETE` | true | Continue to build | Evaluator records security-level `FAIL/SUSPENDED_AS_OF_SNAPSHOT`; stale price-update date alone is exempt | Only persisted members are eligible |
| Suspension state is missing/conflicting/unqualified, or is used to excuse any non-price evidence gap | `FAILED` | `INCOMPLETE` | false | No | Show `SUSPENSION_FRESHNESS_UNQUALIFIED` or exact evidence blocker | No |
| Qualified suspension/status semantics explicitly support `UNKNOWN` for the observed shape | provider attempt may remain `SUCCEEDED`/`COMPLETE` | `COMPLETE` | true | Yes, with evaluator quarantine and reconciled counts | Show security-level `QUARANTINE/ACTIVE_STATUS_UNKNOWN` | Only persisted members are eligible |
| Locked XNYS session or provider lifecycle changes before collection completes | `FAILED` | `INCOMPLETE` | false | No | Show boundary code; require a new explicit command | No |
| Static/reference evidence is complete and valid, but another capability is not yet proven | not terminal until collection completes; final result must be `FAILED` if proof remains absent | final `INCOMPLETE` | false | No | Show remaining capability blocker | No |
| `QOT_RIGHT` event absent while all required capabilities pass | `SUCCEEDED` | `COMPLETE` | true | Continue to build | Optional audit note only | Only after persistence |
| `QOT_RIGHT` handler/capture fails while all required capabilities pass | `SUCCEEDED` | `COMPLETE` | true | Continue to build | Optional audit warning only | Only after persistence |
| Subscription quota absent/unknown while all required non-subscription calls pass | `SUCCEEDED` | `COMPLETE` | true | Continue to build | No blocker; optional diagnostic | Only after persistence |
| Required classification is explicitly unknown | provider attempt may remain `SUCCEEDED` if unknown is valid evidence | `COMPLETE` | true | Yes, with evaluator quarantine and reconciled counts | Show persisted quarantine reason | Yes, but only persisted members are scanned |
| Profile is missing or not published | no gateway attempt starts | n/a | n/a | No | Show `PROFILE_NOT_PUBLISHED` | No |
| Selected profile is `DRAFT` | no gateway attempt starts | n/a | n/a | No | Show draft-is-preview-only blocker | No |
| Published profile hash does not match persisted authority | no gateway attempt starts | n/a | n/a | No | Show `PROFILE_HASH_MISMATCH` | No |
| Request ID is already claimed by a different command envelope | no gateway attempt starts | n/a | n/a | No | Show `REQUEST_ID_CONFLICT`; zero provider calls | No |
| Evaluations/funnel do not exactly reconcile | provider attempt may be `SUCCEEDED` | `COMPLETE` | true | No | Show domain-build blocker | No |
| `build_snapshot()` rejects any invariant | provider attempt may be `SUCCEEDED` | `COMPLETE` | true | No | Show snapshot-build blocker | No |
| Repository transaction fails or reopen hashes differ | provider attempt `SUCCEEDED` | `COMPLETE` | true | No successful persisted result | Show persistence blocker; never show ready | No |
| All required capabilities, profile, evaluation, funnel, build, append, and reopen verification pass | `SUCCEEDED` | `COMPLETE` | true | Yes, once/idempotently | Show persisted snapshot ID/hashes/counts | Yes |

## 9. Persistence and Atomicity

### 9.1 Single snapshot authority

SQLite `SnapshotRepository` is the only production snapshot persistence authority. The file-based `UniverseSnapshotStore` remains a tested domain codec/store boundary but is not introduced as a parallel application authority for M3C-A2.

M3D must resolve membership only from the SQLite-persisted snapshot aggregate selected by snapshot ID.

### 9.2 Successful aggregate atomicity

The existing `SnapshotRepository.append()` contract remains mandatory:

- `BEGIN IMMEDIATE` before writes;
- insert one `universe_snapshots` row;
- insert all `snapshot_securities` rows;
- insert all `snapshot_security_decisions` rows;
- rollback the whole aggregate on any error;
- commit only after all rows succeed;
- exact idempotent replay allowed;
- same ID with conflicting record hash rejected;
- immutable update/delete triggers remain effective.

A failure diagnostic event does not make a snapshot partially persisted. A successful application result exists only after transactional append and read-back hash verification.

### 9.3 Canonical ownership

- Adapter raw payloads are copied/frozen before hashing.
- Domain evidence, prerequisite, evaluation, funnel, and member collections are immutable owned values.
- The snapshot header binds all relevant hashes and provider provenance.
- Decoding/reopening must reproduce typed enums and exact canonical hashes.
- Caller mutation after append must not alter persisted or reopened content.

## 10. UI Boundary

The future `Universe Settings` change is a thin command surface.

**Proposed Interface — `SnapshotReader`**

```text
SnapshotReader.get(snapshot_id: UUID) -> UniverseSnapshot
```

`load_snapshot_ui_state()` must depend on this minimal read protocol rather than the concrete file-backed `UniverseSnapshotStore`. SQLite `SnapshotRepository` satisfies the protocol through its existing `get()` method, with missing/corrupt repository exceptions mapped to the existing fail-closed UI error projection. The file store may remain a codec/test implementation but is not the production formal authority. `Universe Settings` constructs/injects the SQLite reader from the same `RuntimeConfig.database_path`; it must not load the formal result from the current `universe_snapshot_store` session-state object.

### 10.1 Allowed UI responsibilities

- render the currently selected published profile;
- show an explicit “Build Formal Snapshot” action;
- generate one opaque request ID per actual click and retain it for that rerun;
- call `FormalSnapshotApplicationService.build()` once for that event;
- render returned structured diagnostics;
- on success, set/select the persisted snapshot ID and reload through the existing UI read model;
- render persisted counts, provenance, locked session/lifecycle, per-evidence temporal status, diagnostic oldest watermark, hashes, and reason codes.
- display quota provenance explicitly: either timestamped out-of-band audit values or `NOT_COLLECTED_BY_FORMAL_PATH`; quota is never presented as a permission/freshness verdict.

The command/status panel must explicitly label the selected Profile and Profile Version, `Snapshot mode = FORMAL`, Futu/OpenD connection identity and state, SDK/OpenD versions, preflight status, locked session, start/end provider lifecycle, clock verdict, per-evidence temporal verdicts, diagnostic oldest watermark, quota audit state, and blockers. Before an attempt, unavailable fields display `NOT_RUN` rather than a guessed value. After success, authoritative values come from the reopened snapshot projection; after failure, they come from the structured non-authoritative attempt diagnostics and are visibly labeled as failed-attempt evidence.

### 10.2 Forbidden UI responsibilities

- provider SDK calls or context lifecycle;
- account/right qualification logic;
- calendar/freshness computation;
- profile publication or hash computation;
- per-security evaluation or funnel aggregation;
- snapshot construction or direct repository row writes;
- retrying a failed/ambiguous request during a passive Streamlit rerun;
- treating session state as persistence authority.

### 10.3 Rerun contract

Page import/render and all passive reruns perform zero Futu/OpenD calls. Only a true explicit button event can create a new request ID. The application service’s durable request-state check and deterministic snapshot ID provide the second idempotency boundary.

## 11. M3D Boundary

- M3C-A2 stops after producing and reopening the formal snapshot.
- It does not start or schedule a scan.
- At the baseline, Today Scan calls `SnapshotRepository.latest_summary()` before its button action. That is not an exact handoff: a newer snapshot between M3C-A2 success and the scan click can change the selected universe.
- A separately approved M3D integration must add a Proposed `FormalScanCommand(snapshot_id)` (or equivalent explicit snapshot-ID selection/handoff seam). The command receives only the persisted ID selected/displayed by M3C-A2, never a live `GatewayAttempt`, UI object, provider response, or recomputed universe.
- Today Scan must call `SnapshotRepository.get(command.snapshot_id)`, revalidate `FORMAL`, `COMPLETE`, `universe-snapshot/v2`, and hash integrity, display that exact ID before the scan click, and use only its persisted `MEMBER` rows. `latest_summary()` must not choose the command’s snapshot.
- Any session/query/navigation value is selection input only; SQLite reopen remains authority.
- A failed, incomplete, preview, in-memory-only, or non-reopened snapshot is ineligible.
- The scan batch foreign key and manifest hashes remain the downstream audit binding.
- This M3D seam is future integration scope, not an edit authorized by this Design Spec task.

## 12. Acceptance Contract

### 12.1 Unit and contract tests required by a future implementation

1. The non-authorizing `RuntimeIdentityProbe`, runtime state, and start/end bookends accept exact supported true forms for `qot_logined` and exact `READY`; their observed provider/SDK/OpenD tuple must exactly equal an `ACCEPTED` `ProviderIdentityQualificationEnvelope` from `QualificationRegistry`, including contract ID/version/hash, or it fails closed. Tests prove the probe cannot supply clock/factor/FORMAL evidence and a changed context or identity after bundle resolution fails before evaluator/build/persist.
2. Each required capability fails on SDK error, malformed shape, missing field, duplicate code, partial pagination, or count mismatch.
3. All candidates must have exact snapshot/state/plate/classification/prerequisite/evaluation coverage.
4. No `QOT_RIGHT` event still permits success when all required capabilities pass.
5. A captured `QOT_RIGHT` event cannot rescue a failed required capability.
6. `query_subscription()` and the scope-limited quote probe are never called by the production service.
7. `request_highest_quote_right()` or equivalent is absent from the production call graph; a spy that would fail if invoked remains untouched.
8. Monday premarket and Monday regular-session requests cannot label current evidence as Friday; no `update_time >= prior_close` shortcut is accepted.
9. Regular-session and ordinary after-hours requests fail `FORMAL_COLLECTION_WINDOW_NOT_CLOSED`; `OVERNIGHT`, mixed normalized relationships, and an exact candidate set with no common terminal window fail `FORMAL_WINDOW_UNREACHABLE_FOR_CANDIDATE_SET`. Differing raw states pass only when every code maps to terminal-closed for the same session.
10. Weekend, exchange holiday, early-close, and DST cases resolve through XNYS plus qualified provider terminal state, never through hard-coded clock hours.
11. Collection crossing a regular-close, normalized provider-lifecycle, or next-session boundary fails closed and cannot mix evidence or silently relock; UTC or New York civil midnight alone does not fail when all session/relationship/date predicates remain unchanged.
12. Request-scoped/static evidence never receives a fabricated provider timestamp.
13. Non-suspended snapshot rows require exact provider-local `update_time.date == as_of_date`; future or wrong-date evidence fails provider qualification.
14. `PRICE_USD`, `EQUITY_MARKET_CAP_USD`, `LISTED_TRADING_SESSIONS`, and ADV20 each have independent accepted `FactorQualificationContract` evidence; no factor may inherit authority from Stock Screen, another factor, an acquisition timestamp, or a different provider version.
15. PRICE tests require Market Snapshot `last_price` plus `update_time` under the completed-session contract; MARKET_CAP tests require `total_market_val` plus `equity_valid`/`issued_shares`/`last_price` consistency. Both bind new C source identities, independently bound E derivations, exact D/F provider-envelope/factor contracts, and the provider-envelope reference ID/version/hash; under their approved factor decisions, G remains the exact existing Profile Version when business semantics and thresholds do not change.
16. LISTED tests require Market Snapshot `listing_date`, a named/versioned XNYS calendar, both-inclusive completed-session arithmetic, and selected-session hash. The accepted change requires the new C source identity, exact E derivation and F factor contract, and a new G Profile Version because its accepted membership identity changes, while preserving threshold `>=250`.
17. Tests preserve the observed Stock Screen `AVG_TURNOVER=3105` `period_average=None`, `True`, and `False` forms as rejected. They prove none supplies CORE v1 ADV20 authority; no provider implementation is selected until an alternate scalable authority is separately qualified.
18. Registry tests cover A business semantic, B metric identity, C source identity, D provider/version, E derivation identity, F qualification contract, and G Profile Version independently. They prove an E-only change leaves C unchanged, records/binds new E, and requires F requalification; an alternate ADV20 authority additionally requires its mandatory new factor-specific Evidence Version and G even when membership is unchanged, while E-only changes ordinarily do not change G. They also prove `OPEN`, `FAILED_FOR_EXACT_VERSION`, missing, and hash-mismatched provider/factor contracts stop before evaluator/build/persist, and that evaluator compatibility logic is absent.
19. The exact-version suspension contract is required for every FORMAL attempt; every non-exception row records `EXCEPTION_NOT_APPLIED`, and no empty/no-suspension candidate set bypasses the contract.
20. Qualified current `suspension=True` yields security-level `FAIL/SUSPENDED_AS_OF_SNAPSHOT` even when price `update_time` is old; it does not waive any other required evidence.
21. Missing, conflicting, or unqualified suspension freshness makes the provider attempt `FAILED/INCOMPLETE`; explicitly qualified unknown status may instead yield security-level `QUARANTINE/ACTIVE_STATUS_UNKNOWN` but never receives the stale-price exception.
22. Every security/factor temporal verdict round-trips explicit locked/effective/provider-local dates as applicable; a successful verdict whose session date differs from `UniverseSnapshotHeader.as_of_session` is an invariant failure and changes attempt/content/record hashes.
23. A **future implementation** captures application UTC from a wall/monotonic anchor and gateway brackets. Tests inject forward and backward wall steps, monotonic reversal, resolution-edge overlap, and an interval straddling an XNYS boundary; discontinuity/ambiguity fails without any skew threshold, while exact resolution overlap passes. This does not assert that current `RawApiBatch` / `RawApiPage` contain brackets.
24. One immutable `application_context_instance_id` covers every required future call. A changed context object fails; when documented `connID` is exposed, start/end mismatch also fails. This is context identity evidence, not proof that brackets exist.
25. `OPEN`, failed, unknown, or hash-mismatched `ProviderIdentityQualificationEnvelope`, `QualifiedMarketStateConsistencyContract`, `QualifiedFormalCollectionWindowReachabilityContract`, `FormalSnapshotTemporalCoherenceContract`, `FactorQualificationContract`, `QualifiedSuspensionFreshnessContract`, or `ClockAuthorityEvidence` fails closed.
26. Draft, missing, or hash-mismatched profile cannot produce `FORMAL`; published `CORE:v1` remains byte/hash-identical.
27. Unknown prerequisite/classification is represented and quarantined; missing evidence makes collection incomplete.
28. S0-S10 counts reconcile exactly and are bound into canonical hashes.
29. `build_snapshot()` remains the final in-memory formal gate.
30. Repository failure at every insert position rolls back header, rows, and decisions.
31. Same request ID after success returns the same reopened snapshot with zero provider calls.
32. Same request ID after terminal failure or ambiguous start makes zero provider calls.
33. The public command rejects `requested_at_utc` and every session/readiness override; identical public intent reuses the original stored internal envelope, while a different public intent produces `REQUEST_ID_CONFLICT` without provider calls.
34. Passive Streamlit render/rerun makes zero provider calls; one explicit click invokes the service once.
35. UI displays only the reopened persisted snapshot as ready.
36. M3D consumes the exact persisted snapshot ID and does not recompute membership.
37. Concurrent identical public intents produce exactly one atomic claim and at most one provider invocation; a reused request ID with a different public intent returns `REQUEST_ID_CONFLICT`.
38. A **future implementation** makes `universe-snapshot/v2` round-trip every proposed qualification field, rejects missing/unknown fields, preserves v1 read compatibility, and makes `formal_intent_sha256`, service-owned `formal_requested_at_utc`, the clock anchor, future gateway-captured `ApiAcquisitionBracket` values, the exact accepted `ProviderIdentityQualificationEnvelope` and service-resolved-bundle IDs/versions/hashes, A–G versions, exact factor contract IDs/versions/hashes, locked-session data, lifecycle/reachability contracts and bookends, fully defined per-code/per-factor verdicts, factor/suspension contracts, canonical ordering, and all associated hashes content/record-hash sensitive.
39. The current `latest_summary()` Today Scan behavior is not accepted for exact handoff; the future integration test injects/selects a specific snapshot ID and proves a newer snapshot cannot replace it.

### 12.2 Windows real-environment acceptance

This acceptance is executed only in a later authorized implementation/validation node. It is not executed during this design task.

Preconditions:

- Windows host and configured local OpenD;
- exact Futu SDK/OpenD identity with an accepted immutable provider envelope and factor/clock contracts; `1010` observations alone and any `1009` mapping/hash reuse are insufficient;
- OpenD quote login ready;
- OpenD launched with effective `auto_hold_quote_right=0`, verified and captured from its startup configuration/console before the run; no acceptance step changes this setting. This prevents OpenD’s automatic quote-right reacquisition path from undermining the no-side-effect claim; see the official [OpenD configuration documentation](https://openapi.futunn.com/futu-api-doc/en/opend/opend-cmd.html);
- a quiescent acceptance environment with no unrelated OpenD clients changing subscriptions during the evidence window;
- Telnet/O&M channels disabled for the run or independently monitored so no `request_highest_quote_right` operation can occur; the operation’s cross-device side effect is documented by Futu’s [OpenD operation command reference](https://openapi.futunn.com/futu-api-doc/en/opend/opend-operate.html);
- published `CORE:v1` loaded from the application database;
- clean, backed-up acceptance database path;
- the requested production-validation run is started only inside a window class accepted by the version-bound reachability contract for the **entire exact candidate set**; premarket, regular-session, nonterminal after-hours, `OVERNIGHT`, and unreachable weekday attempts are negative tests only;
- every applicable Section 17 prerequisite has separate explicit authorization where it needs empirical capture and has already produced its accepted immutable exact-version contract artifact before any production qualification attempt;
- explicit operator action and authorization for real provider requests.

Required evidence record:

- git commit and clean/dirty status used for the run;
- application version;
- requested UTC time, locked XNYS session/date/open/close, start/end provider lifecycle states, and the proof that both bookends refer to the same terminal-closed session;
- the future gateway's application clock anchor/resolution, every provider call's captured raw wall and monotonic send/receive sample, monotonic-projected UTC interval, raw global-state `timestamp`/`local_timestamp` value and represented interval, and every clock predicate/verdict;
- configured host/port, SDK version, OpenD server version, accepted provider-envelope ID/version/hash and qualification evidence references, immutable application context instance ID, proof that every required call used that same context object, application connection identity hash, and optional documented provider connection ID with exact start/end equality;
- `qot_logined` and `program_status_type` values;
- exact required-capability verdicts, expected/observed counts, endpoint batch hashes, and acquisition interval;
- acceptance-harness `query_subscription(is_all_conn=True)` evidence immediately before and after the service call: raw response hashes, `total_used`, `own_used`, `remain`, option quota fields, and the all-connection `sub_list`; this is out-of-band audit evidence, must show no service-created subscription or quota delta, and cannot influence the qualification verdict. The scope is explicit because the SDK can otherwise restrict results to the current connection; see the official [subscription query reference](https://openapi.futunn.com/futu-api-doc/en/quote/query-subscription.html);
- confirmation that no subscribe/unsubscribe/right-escalation call occurred; only the acceptance harness, not the production service, may issue the two read-only `query_subscription()` audit calls;
- the captured effective `auto_hold_quote_right=0` value plus an isolated OpenD log/operation interval showing no automatic reacquisition and no Telnet/O&M `request_highest_quote_right` command;
- selected published profile version and exact content/filter hashes;
- each source-neutral factor identity, its A–G versions, exact provider/derivation definition, accepted contract ID/version/hash, canonical evidence hashes, and independent per-factor verdicts; Stock Screen `3105` None/True/False remains rejected;
- accepted evidence from a separately selected alternate ADV20 authority proving arithmetic mean of actual USD dollar turnover over exactly 20 completed XNYS sessions, plus LISTED `listing_date`/XNYS both-inclusive evidence under the new Profile Version;
- start/end per-code raw market-state evidence and normalized session relationship, the accepted collection-window reachability artifact and actual candidate-set reachability verdict, snapshot suspension/status evidence, the accepted suspension qualification-spike artifact, exact snapshot update watermark, and every per-code temporal/suspension verdict;
- gateway status/completeness/formal-ready/reason codes;
- S0-S10 totals, member/fail/quarantine counts, and reconciliation;
- persisted snapshot ID plus mapping/prerequisite/member/content/record hashes;
- process restart followed by exact snapshot reopen and hash equality;
- M3D Today Scan created only after a separate explicit action through the approved exact snapshot-ID selection/handoff seam and bound to that same snapshot ID, even if a newer snapshot exists;
- proof that the M3D member set equals persisted `MEMBER` rows and that no provider call occurred during scan membership loading.

Acceptance passes only if the command returns `SUCCEEDED`, the snapshot is transactionally persisted and exactly reopened after restart, every negative assertion holds, and M3D consumes the same persisted authority.

## 13. Reason-Code Taxonomy

Future implementation must use stable machine-readable codes. At minimum:

```text
PROFILE_NOT_PUBLISHED
PROFILE_HASH_MISMATCH
RUNTIME_SDK_VERSION_UNAVAILABLE
OPEND_GLOBAL_STATE_FAILED
OPEND_NOT_QUOTE_LOGGED_IN
OPEND_NOT_READY
OPEND_VERSION_UNAVAILABLE
CONSISTENCY_CONTRACT_UNQUALIFIED
CLOCK_AUTHORITY_BLOCKER
FORMAL_COLLECTION_WINDOW_NOT_CLOSED
FORMAL_WINDOW_UNREACHABLE_FOR_CANDIDATE_SET
CONNECTION_IDENTITY_MISMATCH
DISCOVERY_INCOMPLETE_OR_MALFORMED
SCREEN_INCOMPLETE_OR_MALFORMED
SNAPSHOT_INCOMPLETE_OR_STALE
MARKET_STATE_INCOMPLETE_OR_INCONSISTENT
OWNER_PLATE_INCOMPLETE_OR_MALFORMED
CLASSIFICATION_INCOMPLETE
EVIDENCE_KEYSET_MISMATCH
FUTURE_PROVIDER_TIMESTAMP
TEMPORAL_DATE_MISMATCH
TEMPORAL_SESSION_BINDING_MISMATCH
PROVIDER_LIFECYCLE_BOUNDARY_CROSSED
NEXT_SESSION_BOUNDARY_CROSSED
SESSION_BOUNDARY_CROSSED
FACTOR_EVIDENCE_UNQUALIFIED
FACTOR_DERIVATION_MISMATCH
ADV20_WINDOW_UNQUALIFIED
LISTED_TRADING_SESSIONS_DERIVATION_MISMATCH
FACTOR_CONTRACT_UNQUALIFIED
FAILED_FOR_EXACT_VERSION
SUSPENSION_FRESHNESS_UNQUALIFIED
SUSPENSION_STATUS_CONFLICT
FUNNEL_RECONCILIATION_FAILED
SNAPSHOT_INVARIANT_FAILED
SNAPSHOT_PERSISTENCE_FAILED
SNAPSHOT_REOPEN_HASH_MISMATCH
REQUEST_ID_CONFLICT
COMMAND_FORBIDDEN_FIELD
DUPLICATE_TERMINAL_FAILURE
UNKNOWN_IN_FLIGHT
```

Human-readable messages supplement these codes but never replace them.

## 14. Security and Operational Constraints

- Never serialize credentials, account identifiers, API keys, or environment secrets into diagnostics, logs, evidence, or snapshots.
- Redact exception messages before persistence.
- Contexts must be closed on every success/failure path.
- Provider transport failure is not retried automatically by Streamlit rerun.
- Required collection must use deterministic chunking/pagination and existing rate-limit discipline.
- Formal qualification must not make subscription calls, so subscription quota is neither consumed nor an availability dependency.
- Production acceptance uses a dedicated database target and must not mutate unrelated `data/` content.

## 15. Preservation Boundaries and Future Integration Strategy

### 15.1 Preserved boundaries

M3C-A2 must not change:

- `CORE:v1` rules, publication state, or hashes;
- Flat Base V1 detector definitions or calculations;
- S0-S10 business semantics or reason-code meaning;
- published profile immutability;
- snapshot immutability and canonical hash ownership;
- JSONL human-review canonical history;
- provisional/formal isolation;
- M3D Scan Batch detector semantics;
- SQLite fail-closed transaction and foreign-key semantics;
- the prohibition on automated trading, broker integration, and order execution.

### 15.2 Future branch/integration strategy

This design node performs no integration. A later separately approved implementation follows:

```text
codex/pattern-finder-m3c-a2-formal-snapshot-qualification
  -> TDD implementation
  -> focused, Pattern Finder, and full-repository tests
  -> independent review with Critical=0 and Important=0
  -> explicitly authorized real OpenD acceptance
  -> verified commits
  -> separately approved safe integration into codex/pattern-finder-m3d-implementation
```

Before integration, the M3D worktree’s protected uncommitted state must be revalidated and preserved. Integration must be planned from committed ancestry without reset, stash, clean, checkout overwrite, or copying the protected dirty files. This Spec does not authorize merge, cherry-pick, rebase, branch deletion, or any other integration action.

## 16. Design Traceability

| Requirement | Design authority |
|---|---|
| Capability, not account tier | Sections 4 and 5 |
| Required Futu endpoint proof | Section 4 matrix |
| No `QOT_RIGHT` authority | Section 4.4 |
| No subscription/quota/right escalation | Sections 2.3, 4.4, 14 |
| Source-neutral CORE v1 factor identities and independent A-G versions | Section 4.3 |
| Completed-session and provider-lifecycle lock | Sections 5 and 6.1-6.3 |
| Independent factor qualification authority and pre-evaluator gateway enforcement | Sections 4.3, 5, 6.2, and 7 |
| Suspension/halt freshness semantics | Sections 5 and 6.4 |
| Application/provider clock authority without arbitrary skew | Sections 4.1, 5, and 6.5 |
| Temporal evidence and hash binding | Sections 5.6-5.7 and 9 |
| Existing domain invariants preserved | Sections 3.3 and 5 |
| Production entrypoint | Section 7 |
| Streamlit rerun idempotency | Sections 7.5 and 10.3 |
| Atomic immutable persistence | Section 9 |
| M3D consumes persisted authority | Section 11 |
| Windows real acceptance | Section 12.2 |

## 17. Open Design Blockers

The state machine is proposed but not implementation-ready. The linked 2026-09-01/04/05 OpenD evidence remains historical diagnostic evidence; it accepted no provider, clock, factor, or suspension qualification contract. In particular, its `futu_api 10.10.7008` + OpenD `1010` captures are unqualified. They cannot inherit any legacy exact `1009` mapping, contract, or hash, and `formal_ready=false`.

1. **`FUTU_EXACT_PROVIDER_IDENTITY_ENVELOPE`** — create and accept an immutable envelope for each exact `(provider, SDK, OpenD)` identity before any clock acceptance. The `1010` envelope must independently bind provider/version identity, mapping/schema/capability definitions, qualification references, and its canonical hash; it may not reuse any legacy `1009` artifact. The recorded `1010` observations are diagnostic, not an accepted envelope.
2. **`FUTU_FORMAL_COLLECTION_WINDOW_REACHABILITY_QUALIFICATION`** — only after the exact identity, future bracket/canonical-retention seam, and replacement clock contract are accepted, prove raw-state-to-session mapping and reachable terminal-closed windows for every claimed class: standard weekday, early close, both DST directions, weekend, XNYS holiday, and overnight/next-session boundaries. The recorded `AFTER_HOURS_END`/per-code `OVERNIGHT` and strict-clock observations are negative diagnostics. Until accepted, no supported FORMAL window is published.
3. **`CORE_V1_FACTOR_QUALIFICATION_REGISTRY`** — accept exact, source-neutral A–G contracts for `PRICE_USD`, `EQUITY_MARKET_CAP_USD`, and `LISTED_TRADING_SESSIONS`, each bound to an accepted exact provider envelope by ID/version/hash, then bind them in `universe-snapshot/v2`. PRICE requires Market Snapshot `last_price`/`update_time`; MARKET_CAP requires `total_market_val` with `equity_valid`/shares/price consistency; LISTED requires `listing_date`, named/versioned XNYS, both-inclusive completed-session derivation, selected-session hash, and a new G Profile Version because its accepted membership identity changes. The historical Stock Screen `2201`, `2301`, and `2307` results remain legible diagnostics, not FORMAL authorities. The historical `3105` None/True/False observations are REJECTED for ADV20.
4. **`ADV20_ALTERNATE_SCALABLE_AUTHORITY`** — ADV20 remains `OPEN`: it needs an authority for the exact arithmetic mean of actual USD dollar turnover across exactly 20 completed XNYS sessions ending `as_of`. The provider-neutral interface is frozen, but no provider implementation is selected or claimed. A later selected authority requires its C source identity, E derivation, F contract, accepted provider envelope, a **mandatory new factor-specific Evidence Version, and a mandatory new G Profile Version even if accepted membership identity is unchanged**. This ADV20-specific requirement does not weaken the general C/E orthogonality rule: an E-only change ordinarily leaves C and G unchanged. Historical CORE:v1 bytes/hashes are not rewritten.
5. **`FUTU_SUSPENDED_SECURITY_FRESHNESS_QUALIFICATION`** — using an authorized sample, prove that suspension/status is independently current under terminal-closed lifecycle bookends even when `last_price` `update_time` is old. Bind the exact provider identity, future gateway bracket/canonical evidence, corroboration, allowlisted mapping, and contract hash. The recorded `CRNX`, `HCHL`, and `LPSN` facts remain diagnostic; none authorizes the stale-price exception. Until accepted, that exception is forbidden.

Failure to prove a contract is not permission to weaken it. `OPEN`, `FAILED_FOR_EXACT_VERSION`, missing, or hash-mismatched qualification remains a pre-evaluator blocker. Historical recomputation is not silently substituted, and no historical CORE:v1 snapshot is rewritten.

## 18. Completion Gate for This Spec

This documentation reconciliation is ready for user spec re-review only when:

- this Design Spec and its linked qualification-evidence document reconcile the exact-identity, factor-authority, versioning, bracket, and fail-closed boundaries above;
- this docs-only node stages only those two documents and does not alter protected code, tests, profiles, data, SQLite, snapshots, or historical evidence bytes;
- spec self-review and independent `GPT-5.6 Sol` / `xhigh` review report zero Critical and zero Important findings; and
- `git diff --check` passes.

It is not implementation-ready, and the terminal token `READY FOR USER SPEC RE-REVIEW` must not be emitted while any Section 17 blocker remains open. Any provider capture, clock replacement, profile change, schema implementation, or production repair requires new explicit scope. Accepted artifacts must enter their own exact-version contracts before any implementation node begins.
