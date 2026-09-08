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
2. the application service uses its stored `formal_requested_at_utc`, exact published-profile content identity, and observed runtime provider/SDK/OpenD tuple to select exactly one immutable `PublishedQualificationSet`; it then dereferences only the exact provider envelope and ordered factor contracts named by that set before it asks the gateway for formal evidence;
3. the gateway validates that exact qualification-set identity/version/hash and those exact contract IDs, versions, and hashes, validates the qualified clock/window prerequisites, and collects complete per-code evidence without crossing the locked XNYS session or provider lifecycle;
4. it rejects an `OPEN`, `FAILED_FOR_EXACT_VERSION`, missing, or hash-mismatched factor/provider/clock contract before evidence reaches the evaluator;
5. the existing evaluator and funnel derive S1-S9 and S0-S10 results;
6. the existing `build_snapshot()` enforces the formal snapshot invariant;
7. the future SQLite `SnapshotRepository.append(snapshot, evidence_manifest, evidence_artifacts)` atomically persists the immutable snapshot aggregate and its durable evidence graph;
8. the UI reopens the persisted snapshot and displays only the persisted projection;
9. M3D consumes only that persisted snapshot ID.

Any unknown, malformed, stale, inconsistent, incomplete, unqualified, hash-mismatched, or unpersisted result is not a formal snapshot and is not eligible for M3D. In particular, `formal_ready=false` while the observed `futu_api 10.10.7008` + OpenD `1010` identity, ADV20 authority, or any other required exact qualification contract remains unaccepted.

### 1.1 Reconciliation status and dependency order

OpenD `1009` is a legacy **exact-qualified identity**. It is neither a minimum supported version nor a schema proxy. The qualification captures recorded in the linked evidence used `futu_api 10.10.7008` with OpenD `1010`. `1010 > 1009` is not compatibility evidence: `1010` needs its own versioned provider/capability qualification envelope and immutable contract hash. Until that envelope is accepted, it is unqualified, `formal_ready=false`, and no FORMAL evidence may reuse a `1009` mapping or contract hash. Low-level diagnostic capture may record `1010` without granting it that authority.

The future implementation order is intentionally constrained:

1. define and accept the exact provider/OpenD version identity and qualification envelope before accepting a concrete clock contract;
2. define the independent factor/version model, `QualificationRegistry`, and immutable effective-dated `PublishedQualificationSet` selection authority; freeze the provider-neutral ADV20 interface as `OPEN`, then design the required new Profile Version;
3. add gateway acquisition-bracket capture and canonical evidence retention, then replace the clock contract;
4. add the application-service fail-closed sequence and `universe-snapshot/v2` binding for the selected qualification set and its exact contracts, reconcile acceptance/documentation, and obtain independent spec review.

Acquisition brackets are multi-layer **future** evidence: the future gateway will capture them, a qualification contract will judge them, the application service will enforce the result, `universe-snapshot/v2` will bind the evidence-manifest hash and immutable artifact references, and the same SQLite transaction will durably store the snapshot aggregate, manifest, and referenced canonical artifacts without deciding qualification or membership.

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
| Profile authority | SQLite `ProfileRepository.get_published()` | Resolve the immutable published profile version and verify payload/filter/rules hashes from the same database that owns snapshots | Sole profile-payload/G authority for the public command; it does not select C/D/E/F or provider compatibility, and `ProfileRegistry` remains bootstrap/UI input only |
| Qualification selection authority | Proposed application-policy `QualificationRegistry` records | No baseline production selector exists | Own immutable, versioned, hash-bound `PublishedQualificationSet` records selected first by exact profile content, observed runtime provider/SDK/OpenD tuple, and service-stored request time; each selected set then names the only provider envelope and ordered factor contracts that may be dereferenced; zero or multiple matches fail closed |
| Provider transport | `FutuProviderAdapter` | Wrap Futu SDK calls as immutable `RawApiBatch` / `RawApiPage` with canonicalized SDK-level request/response hashes, rows, and one `acquired_at_utc` | Baseline has no full wall/monotonic send/receive brackets and no lossless wire bytes; a future gateway/adapter seam must add canonical bracket evidence |
| Provider collection | `FutuUniverseGateway.collect()` | Discover candidates, page stock screen, fetch snapshot/state/plate evidence, validate per-code coverage, and return `GatewayAttempt` | Future gateway receives the application-service-resolved immutable qualification-set/provider/factor bundle, then verifies/enforces its exact IDs, versions, and hashes before evaluator input; it never selects compatibility, and legacy Stock Screen factor values are not FORMAL authorities |
| Classification | `SecurityMasterProvider.classification_evidence()` and explicit classification evidence | Fail-closed security-type proof | Reuse without silent inference |
| Rule evaluation | `evaluator.evaluate_security()` | Pure S1-S9 business-threshold evaluation; unknown evidence quarantines | Reuse unchanged in concept; it never chooses a provider, accepts a contract, or decides compatibility |
| Funnel | `build_funnel()` | Deterministic S0-S10 aggregation and reconciliation | Reuse unchanged in concept |
| Snapshot construction | `build_snapshot()` | Enforce FORMAL/PREVIEW invariants and canonical hashes | Reuse as final in-memory gate |
| Snapshot persistence | `SnapshotRepository.append()` | One `BEGIN IMMEDIATE` transaction for header, securities, and decisions; rollback on failure | Extend the same future transaction boundary to the evidence manifest and referenced content-addressed canonical artifacts; it remains the sole production snapshot write authority and evidence never becomes membership authority |
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
| `CAP-RUNTIME-OPEND` | future bracketed `get_global_state()` at attempt start and end | success; `qot_logined` true/`1`; `program_status_type == READY`; exact provider/OpenD identity bound to an accepted envelope; exact canonical SDK-response hashes; `timestamp` and `local_timestamp`, when present and parseable, retained with documented precision | two bookends on the same application connection identity | application UTC/XNYS remains session authority; provider timestamps are optional provenance/corroboration only | `OPEND_NOT_QUOTE_LOGGED_IN`, `OPEND_NOT_READY`, `OPEND_VERSION_UNAVAILABLE`, `FAILED_FOR_EXACT_VERSION`, or a `CLOCK_AUTHORITY_BLOCKER` based only on a provable Section 6.5 contradiction—not timestamp absence, parse failure, coarseness, or proximity |
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
| OpenD version, `qot_logined`, `program_status_type`, `timestamp`, `local_timestamp` | one non-authorizing `RuntimeIdentityProbe`, then future bracketed `get_global_state()` bookends | runtime identity; clock evidence only after the accepted bundle is returned to the gateway | `timestamp` is provider/server UTC epoch seconds; `local_timestamp` is the OpenD-host epoch timestamp, not market-data time | the probe contributes only the observed runtime tuple used in set-first selection; the selected set names the exact envelope, and any usable provider timestamps remain precision-aware provenance/corroboration under Section 6.5 | SDK error, false/unknown login, non-`READY`, missing/unparseable identity, unaccepted exact identity, or a provable Section 6.5 contradiction fails; timestamp absence/parse failure is retained explicitly as diagnostic `NOT_AVAILABLE`, not itself a blocker | Yes, including the distinct probe hash, context identity, any raw timestamp values or explicit unavailability, future brackets, and canonical SDK-response hashes |
| `stock_id`, `code`, name, exchange, `stock_type`, delisting flag | `get_stock_basicinfo()` discovery batches | static/reference as observed | No | complete same-attempt discovery, identity uniqueness, parseable fields | permission/market/transport/schema/identity failure | Yes, per discovery batch hash |
| symbol/name/industry | paginated `get_stock_screen()` | static/reference as observed | No | exact candidate coverage and same-attempt acquisition | any failed/partial page or missing/duplicate row fails | Yes, per page hash |
| Stock Screen `PRICE`, `MARKET_CAP`, `AVG_TURNOVER`, `LISTED_DAYS` | paginated `get_stock_screen()` | historical/diagnostic observations only | No per-row timestamp exposed by the current gateway contract | none for factors under the newly selected FORMAL Profile Version; `3105` None/True/False is rejected and the other three properties are replaced by the source-neutral identities in Section 4.3 | these values cannot supply or rescue FORMAL factor evidence | Diagnostic page request/response hashes only |
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
  runtime_identity_probe_sha256
```

The service may ask the gateway/adapter for this one **non-authorizing** identity-discovery operation before set selection; otherwise it cannot know whether the observed OpenD is `1009`, `1010`, or another version. The gateway/adapter creates and retains one quote context, captures the documented runtime observation tuple plus canonical request/response/provenance values, computes `runtime_identity_probe_sha256` over the complete canonical probe observation, and returns the immutable probe to the service. The probe neither accepts nor selects a contract and supplies no clock, factor, or FORMAL authority. The application context instance ID is a fifth, independent same-object observation: it is neither the probe hash nor an envelope identity. The service uses the tuple only as one input to set-first selection, dereferences the selected set's exact envelope reference, returns the immutable bundle to the gateway, and the gateway then performs all bracketed collection. The gateway must fail closed unless the probe tuple, every later observed identity/bookend, `OpenDConnectionIdentity`, and the selected envelope's required tuple match field-for-field; it closes the context in its single `finally` path on either outcome.

The following independent versions must never be overloaded into one string: **A** business semantic; **B** metric identity; **C** `factor_evidence_version` (the canonical versioned evidence/source identity); **D** provider/version identity; **E** derivation identity; **F** qualification-contract version; and **G** Profile Version. Each axis increments independently and every contract binds an exact G, whether that is an existing or new Profile Version. C identifies the factor's source/evidence authority and is the Evidence Version enforced by the registry and Snapshot bindings; it is not an additional version axis. E identifies the transformation from its inputs to the metric. An E-only change leaves C unchanged, but its evidence record and exact contract must bind the new E and F must be requalified. A/B/threshold changes require a new G. A new G is ordinarily required only when the accepted membership semantics or identity changes the published profile payload/rules, not merely because E changes; the factor decisions below record that selecting an alternate ADV20 authority mandates a new C factor_evidence_version and a new G even if membership is unchanged. If a container format must change, `evidence_record_schema_version` is an orthogonal evidence-record container schema version only, not one of A–G and not a replacement for C or E. D/F-only changes require a new provider/factor qualification contract and Snapshot binding but no new G when A/B/C/E remain identical. `universe-snapshot/v1` lacks these bindings; M3C-A2 requires `universe-snapshot/v2`. A later contract instance/hash change does not require a schema bump unless field shape changes.

| CORE v1 prerequisite | Source-neutral metric/evidence identity and future source | Deterministic semantics | Required version action | Current authority state |
|---|---|---|---|---|
| Price `>= USD 5` | `PRICE_USD`; Market Snapshot `last_price` + `update_time` | completed-session-qualified USD latest price | new C `factor_evidence_version` (canonical Evidence Version/source identity), E derivation identity, and exact D/F provider/factor contracts; under this approved factor decision G remains unchanged if business semantic/threshold remain identical | candidate only; `1010` is unqualified until exact contract acceptance |
| Market Cap `>= USD 1B` | `EQUITY_MARKET_CAP_USD`; Market Snapshot `total_market_val` + `equity_valid`/`issued_shares`/`last_price` consistency | USD equity market capitalization with the same-row identity verified | new C `factor_evidence_version` (canonical Evidence Version/source identity), E derivation identity, and exact D/F provider/factor contracts; under this approved factor decision G remains unchanged if business semantic/threshold remain identical | candidate only; `1010` is unqualified until exact contract acceptance |
| Listed `>= 250 trading days` | `LISTED_TRADING_SESSIONS`; Market Snapshot `listing_date` + named/versioned `XNYS` calendar | both-inclusive completed-session count with selected-session sequence/hash | new C `factor_evidence_version` (canonical Evidence Version/source identity), exact D/E/F provider/derivation/contract, **and a new G Profile Version**; keep threshold `>=250` | candidate only; `1010` is unqualified until exact contract acceptance |
| ADV20 `>= USD 20M` | frozen provider-neutral ADV20 interface; no provider implementation selected | exact arithmetic mean of actual USD dollar turnover over exactly the 20 completed XNYS sessions ending `as_of` | a later alternate scalable authority requires a new C `factor_evidence_version` (the canonical factor-specific Evidence Version/source identity), D provider identity, a new E only if its derivation changes, a newly qualified F contract, and **a mandatory new G Profile Version even if accepted membership identity is unchanged** | `OPEN — requires alternate scalable authority`; Stock Screen `3105` `period_average` None/True/False are **REJECTED** |

**Proposed Interfaces — `FactorQualificationContract`, `PublishedQualificationSet`, and `QualificationRegistry`**

```text
FactorQualificationContract
  contract_id: immutable exact identity
  factor_id
  business_semantic_version                 # A
  metric_identity_version                   # B
  factor_evidence_version                   # C: canonical factor Evidence Version/source identity; exact registry/Snapshot key
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

PublishedFactorSelection
  factor_id
  business_semantic_version                 # A
  metric_identity_version                   # B
  factor_evidence_version                   # C
  derivation_version                        # E
  qualification_contract_version            # F
  factor_contract_id
  factor_contract_sha256

PublishedQualificationSet
  qualification_set_id: immutable exact identity
  qualification_set_version
  profile_version_id                        # exact G
  profile_content_sha256
  runtime_provider_id                       # immutable selector tuple
  runtime_provider_sdk_version
  runtime_opend_server_version
  provider_identity_contract_id             # exact accepted D envelope
  provider_identity_contract_version
  provider_identity_contract_sha256
  ordered_factor_selections: tuple[PublishedFactorSelection, ...]
  effective_from_utc: aware UTC datetime, inclusive
  effective_until_utc: aware UTC datetime, exclusive
  record_state: PUBLISHED
  qualification_references
  qualification_reference_sha256s
  qualification_set_sha256

QualificationRegistry
  accept_and_publish_provider_identity(immutable ProviderIdentityQualificationEnvelope)
  accept_and_publish(immutable FactorQualificationContract)
  accept_and_publish_qualification_set(immutable PublishedQualificationSet)
  resolve_published_qualification_set_exact(
    profile_version_id, profile_content_sha256,
    runtime_provider_id, runtime_provider_sdk_version,
    runtime_opend_server_version,
    formal_requested_at_utc: service-owned stored value
  ) -> PublishedQualificationSetResolution
       status: EXACTLY_ONE | ZERO_MATCH | MULTIPLE_MATCH | HASH_MISMATCH
       qualification_set: exact PublishedQualificationSet only when EXACTLY_ONE
       reason_codes
  dereference_provider_identity_from_published_set_exact(
    qualification_set_id, qualification_set_version, qualification_set_sha256,
    provider_identity_contract_id, provider_identity_contract_version,
    provider_identity_contract_sha256
  ) -> ProviderIdentityResolution
       status: ACCEPTED | OPEN | FAILED_FOR_EXACT_VERSION | MISSING | HASH_MISMATCH
       envelope: exact ProviderIdentityQualificationEnvelope only when ACCEPTED
       contract_id, qualification_contract_version, contract_sha256, reason_codes
  resolve_factor_from_published_set_exact(
    qualification_set_id, qualification_set_version, qualification_set_sha256,
    selection: PublishedFactorSelection
  ) -> FactorQualificationResolution
       status: ACCEPTED | OPEN | FAILED_FOR_EXACT_VERSION | MISSING | HASH_MISMATCH
       contract: exact FactorQualificationContract only when ACCEPTED
       contract_id, qualification_contract_version, contract_sha256, reason_codes

ResolvedFormalQualificationBundle
  provider_identity_envelope: exact ACCEPTED ProviderIdentityQualificationEnvelope
  published_qualification_set: exact PUBLISHED PublishedQualificationSet
  qualification_set_id
  qualification_set_version
  qualification_set_sha256
  factor_contracts: exact ACCEPTED tuple[FactorQualificationContract, ...]
  bundle_sha256
```

`PublishedQualificationSet` is the immutable application-policy selection authority that the public profile or runtime probe alone cannot be. Its canonical hash covers its ID/version, exact `profile_version_id + profile_content_sha256 + runtime_provider_id + runtime_provider_sdk_version + runtime_opend_server_version` selector key, exact referenced provider-envelope ID/version/hash, half-open effective interval, record state, ordered per-factor A/B/C/E/F selections, exact factor-contract IDs/hashes, and qualification references. The uniqueness key is `(profile_version_id, profile_content_sha256, runtime_provider_id, runtime_provider_sdk_version, runtime_opend_server_version, effective_from_utc)`. The registry is append-only: it never edits or deletes a published set, rejects duplicate uniqueness keys, and prohibits intersecting effective intervals for the same selector tuple at publication. Boundary selection is executable and deterministic: query that exact selector tuple and require `effective_from_utc <= stored formal_requested_at_utc < effective_until_utc`. The result must be exactly one hash-valid `PUBLISHED` record. `ZERO_MATCH` yields `QUALIFICATION_SET_ZERO_MATCH`; more than one result, including corrupted/legacy intersecting intervals, yields `QUALIFICATION_SET_MULTIPLE_MATCH`. A missing/tampered set hash yields `QUALIFICATION_SET_HASH_MISMATCH`. No `latest`, `current`, highest-version, lexicographic-version, profile-only, or caller-supplied compatibility fallback is permitted.

Selection is deliberately **set first**. Only after exactly one set is selected does the registry dereference the envelope by the set's exact `provider_identity_contract_id + provider_identity_contract_version + provider_identity_contract_sha256`, recompute the envelope canonical content hash, require it to equal the stored `contract_sha256`, require `verdict == ACCEPTED`, and compare the envelope's required provider/SDK/OpenD tuple with the actual runtime observation tuple. Zero, multiple, missing, `OPEN`, `FAILED_FOR_EXACT_VERSION`, hash-mismatched, or tuple-mismatched envelope resolution fails closed. An envelope is never found by asking the runtime tuple for a newest/current/highest contract.

A D or F change without a G change still creates a new qualification-set ID/version/hash and a disjoint successor effective interval; the previous set remains immutable historical authority for its own interval. A new provider envelope is never substituted into an old set. An alternate ADV20 authority replaces frozen `CORE:v1`'s source-coupled authority and therefore mandates a new C `factor_evidence_version` and a new G even when threshold or membership semantics are unchanged; E remains orthogonal and changes only if derivation changes, while F is always requalified.

`QualificationRegistry`, `ProviderIdentityQualificationEnvelope`, `PublishedQualificationSet`, and `FactorQualificationContract` own acceptance and selection policy. The application service performs set-first selection, exact envelope/factor dereference, and construction of one `ResolvedFormalQualificationBundle`, then passes it to the gateway. The gateway never resolves or accepts a contract: it verifies/enforces the service-resolved qualification-set, provider, and factor contract IDs, versions, and hashes before passing evidence to the evaluator. The evaluator remains a pure business-threshold consumer and never selects a provider or decides compatibility. `ZERO_MATCH`, `MULTIPLE_MATCH`, `OPEN`, `FAILED_FOR_EXACT_VERSION`, missing, intersecting, or hash-mismatched set/provider/factor records stop before evaluator, `build_snapshot()`, or persistence. `universe-snapshot/v2` binds the runtime observation tuple, runtime probe hash, application context identity, exact qualification-set identity, provider-envelope identity/version/hash, and factor-contract IDs/versions/hashes as distinct values; SQLite stores those bindings but does not decide them.

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

Configured Futu host/port, allowed adapter settings, the application clock, `QualificationRegistry`, and the existing SQLite database authority are service dependencies, not public command values. `ProfileRepository` resolves only the exact published Profile Version G and its content/filter/rules hashes; it does not directly supply or select C/D/E/F. The service coordinates one retained provider context and its sole pre-bundle `RuntimeIdentityProbe`, then queries `PublishedQualificationSet` first using the originally stored service-owned `formal_requested_at_utc`, exact profile version/content hash, and observed runtime provider/SDK/OpenD tuple. Exactly one set must match. Only then does the service dereference the exact provider-envelope ID/version/hash and ordered `FactorQualificationContract` records named by that set, recompute and verify every referenced contract hash, and compare the runtime tuple with the dereferenced envelope's required tuple. It must complete those steps before accepting a concrete clock contract, calendar derivation, or FORMAL collection. The caller cannot supply or override `requested_at_utc`, a qualification set, a contract, compatibility, provider identity, profile payload/hashes, `snapshot_kind`, `as_of_date`, or `formal_ready` flag.

### 5.2 Qualification predicate

Let `Q` be the final provider qualification predicate:

```text
Q = runtime_state_valid
    AND exactly_one_published_qualification_set_matches_stored_request_time
    AND qualification_set_profile_runtime_tuple_interval_and_hash_are_exact
    AND selected_set_exact_provider_identity_envelope_is_accepted
    AND observed_provider_identity_equals_selected_set_envelope_required_tuple
    AND every_required_factor_contract_is_exactly_accepted
    AND every_required_factor_contract_equals_the_ordered_set_selection
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

`GatewayAttempt.attempt_status` may be `SUCCEEDED` and `Completeness.COMPLETE` only when `Q` is true. `GatewayPreflight.formal_ready` may be true only when the exact runtime identity is equal to the service-resolved accepted provider envelope and the qualification-set/factor/provider/clock contracts, capability, consistency, and freshness evidence bound into that attempt makes `Q` true. A zero/multiple/intersecting qualification-set match, implicit-latest selection, or an `OPEN`, `FAILED_FOR_EXACT_VERSION`, missing, or hash-mismatched set/provider/factor contract or envelope makes `Q` false and stops before evaluator, snapshot build, or persistence.

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
  runtime_identity_probe_sha256              # hash of actual canonical probe observation only
  global_state_response_hashes: exact start/end tuple
  connection_identity_sha256
  provider_connection_id: optional, only when returned by a documented SDK field
```

`application_context_instance_id` is non-secret, process-local identity evidence, not a provider ID. The future gateway/adapter, not the application service, must create exactly one quote context for an attempt, assign this immutable ID at context creation, route the `RuntimeIdentityProbe` and every later required call through that same object, and close it in one `finally` path. `connection_identity_sha256` is an application-generated canonical hash of the preceding non-optional fields. Five objects remain distinct and are persisted and validated separately: (1) the observed provider/SDK/OpenD tuple, (2) `runtime_identity_probe_sha256`, which hashes the actual canonical probe observation, (3) the selected envelope ID/version, (4) the selected envelope `contract_sha256`, which hashes immutable envelope content, and (5) the application context instance/connection identity. The probe hash is never required to equal the envelope hash, and neither hash may stand in for context identity. Validation instead recomputes each hash over its own canonical object, checks the selected set's exact envelope reference, and requires the observed tuple to equal the selected envelope's required tuple. When a supported documented Python mapping exposes `connID`, probe/start/end values must all be present and exactly equal; when it does not, the persisted application context ID plus enforced object reuse is the same-context proof. This identity proves context reuse only; it neither accepts a provider envelope, proves acquisition brackets, nor substitutes for their future evidence. UI and acceptance evidence must label all identities accurately and never present the application ID as provider-issued.

### 5.5 Published profile and `CORE:v1`

- Only an exact `PUBLISHED` profile version may produce `FORMAL`.
- `DRAFT` may produce only `PREVIEW` through existing boundaries and is outside this production command.
- `CORE:v1` is a historical immutable reference. Its bytes, rules, publication history, and hashes remain permanently readable and auditable; M3C-A2 neither republishes nor rewrites it.
- A new FORMAL snapshot under this design must bind the actual newly published and explicitly selected Profile Version whose LISTED and ADV20 C/G identities agree with the accepted contracts. It must not present historical source-coupled `CORE:v1` as that new FORMAL profile.
- The persisted snapshot must bind that exact resolved Profile Version and its own content/filter/rules hashes.

### 5.6 Required future attempt provenance

The successful snapshot-bound attempt, and the sanitized diagnostic record for a failed attempt, must account for:

- application connection identity, configured host/port, SDK version, OpenD version, and the non-authorizing runtime-identity-probe hashes/provenance;
- application-clock request time, monotonic ordering evidence, collection start/completion, and every **future gateway-captured** request-send/response-receive acquisition bracket;
- raw/normalized `get_global_state.timestamp` and `local_timestamp`, their clock-consistency verdicts, and both global-state hashes;
- endpoint/evidence type, raw response references, and raw response hashes;
- every required capability verdict and expected/observed coverage count;
- locked XNYS session/date, regular close, start/end provider lifecycle states, and the exact temporal-window verdict;
- raw and normalized provider evidence timestamps plus every per-code temporal verdict; no single oldest watermark substitutes for per-code proof;
- exact `PublishedQualificationSet` ID/version/hash/effective interval and exact provider identity envelope plus temporal coherence, collection-window reachability, per-factor, suspension freshness, clock authority, and market-state consistency contract identities/versions/hashes;
- optional, explicitly out-of-band quota and `QOT_RIGHT` audit evidence;
- final blockers and stable reason codes;
- the final downstream attempt and snapshot hashes already required by the domain contract, but only through the post-hash audit projection defined below; those hashes are not inputs to the qualification provenance hash.

Hashes and references alone are not durable evidence. Every successful FORMAL decision must be reopenable and revalidated after process restart from the following versioned canonical objects.

**Proposed Interfaces — durable evidence artifact and manifest**

```text
EvidenceArtifact
  artifact_sha256                         # content address over canonical metadata plus payload
  serializer_id
  serializer_version
  payload_kind
  provider_id
  provider_sdk_version
  opend_server_version
  canonical_payload_encoding: BYTES | UTF8_TEXT
  canonical_payload_bytes_or_text
  endpoint_id
  scope_identity

EvidenceManifestEntry
  artifact_sha256
  role
  endpoint_id
  call_ordinal
  scope_identity
  canonical_request_sha256
  canonical_response_sha256
  acquisition_bracket_sha256
  acquisition_bracket_reference
  factor_references
  security_references
  entry_sha256

GatewayAttemptEvidenceManifest
  manifest_schema_version
  gateway_attempt_id
  ordered_entries: tuple[EvidenceManifestEntry, ...]
  evidence_manifest_sha256
```

`EvidenceArtifact.canonical_payload_bytes_or_text` is the complete payload emitted by the named, versioned SDK-decoded canonical serializer; it is not claimed to be lossless provider wire data. Critical qualification/capability evidence retains the complete canonical SDK-decoded payload. Routine large-universe evidence may retain a canonical normalized projection and use content-addressed artifact deduplication, but the projection must include every input needed to reproduce each FORMAL decision and must reference any additional content-addressed payload on which that decision depends. `UNKNOWN`, `QUARANTINE`, conflict, and schema-anomaly outcomes retain the complete canonical relevant row or batch artifact rather than a success-only projection.

Manifest entry order is exactly `(endpoint_id, call_ordinal, scope_identity, role, artifact_sha256)`; duplicate semantic call/scope/role entries fail closed. `evidence_manifest_sha256` covers the manifest schema version and the complete ordered entries, including immutable artifact references. `GatewayAttempt` and `universe-snapshot/v2` bind that manifest hash and the complete ordered artifact-reference set.

The future `SnapshotRepository.append(snapshot, evidence_manifest, evidence_artifacts)` owns the only successful append path. Section 9 defines its single SQLite transaction, durable table placement, content-addressed deduplication, and restart validation. Missing artifacts, artifact/hash mismatches, unavailable serializer IDs/versions, manifest/hash mismatches, or a payload that cannot be decoded under its exact serializer fail closed; no reopened FORMAL result or M3D membership handoff is allowed. Evidence artifacts and manifests explain, verify, and replay persisted decisions only. They never independently produce a `MEMBER` verdict: the sole membership authority remains the persisted `UniverseSnapshot` plus its persisted rows and decisions.

**Proposed Interfaces — `FormalQualificationProvenance` and final audit projection**

`FormalQualificationProvenance` is an independent immutable canonical object. Its canonical projection contains exactly the following provenance-level values and references; no unlisted runtime, persistence, display, or downstream hash field is admitted implicitly.

```text
FormalQualificationProvenance
  provenance_schema_version: formal-qualification-provenance/v1
  runtime_observation_tuple: provider_id + provider_sdk_version + opend_server_version
  runtime_identity_probe_sha256
  application_context_instance_id
  connection_identity_sha256
  qualification_set_id
  qualification_set_version
  qualification_set_sha256
  provider_identity_contract_id
  provider_identity_contract_version
  provider_identity_contract_sha256
  ordered_factor_contract_references: exact canonical factor-ID order of IDs + versions + hashes
  service_resolved_qualification_bundle_sha256
  clock_authority_sha256
  temporal_coherence_sha256
  formal_collection_window_reachability_sha256
  market_state_consistency_sha256
  suspension_freshness_sha256
  ordered_required_capability_verdict_sha256s: exact canonical capability-ID order
  ordered_per_code_temporal_verdict_sha256s: exact canonical normalized-code order
  ordered_per_code_factor_verdict_sha256s: exact canonical (normalized_code, factor_id) order
  evidence_manifest_sha256
  ordered_evidence_artifact_sha256s: exact immutable manifest-reference order
  ordered_api_acquisition_bracket_sha256s: exact canonical call order
  profile_version_id
  profile_content_sha256
  profile_filter_sha256
  profile_rules_sha256
  locked_session_date
  locked_session_open_at_utc
  locked_session_close_at_utc
  provider_lifecycle_start
  provider_lifecycle_end
  stable_reason_codes: exact canonical reason-code order

PersistedFinalAuditProjection
  qualification_provenance_sha256
  gateway_attempt_sha256
  snapshot_content_sha256
  snapshot_record_sha256
  downstream_presentation_and_out_of_band_audit_fields

Canonical hash dependency DAG
  EvidenceArtifact hashes + ApiAcquisitionBracket hashes
    -> EvidenceManifestEntry hashes
    -> GatewayAttemptEvidenceManifest.evidence_manifest_sha256
    -> provider/factor/clock/temporal/capability/verdict hashes
    -> FormalQualificationProvenance canonical projection
    -> qualification_provenance_sha256
    -> gateway_attempt_sha256
    -> snapshot mapping/prerequisite/member/content/record hashes
    -> PersistedFinalAuditProjection
```

`qualification_provenance_sha256` is exactly SHA-256 over the canonical serialization of the complete `FormalQualificationProvenance` projection under its named schema/version and the future audit codec's named serializer/version. The profile fields bind the selected published G identity and its content/filter/rules hashes. Locked-session/lifecycle fields bind the session authority used by every verdict. Required capability, per-code temporal, and per-code factor verdict hashes use only the explicit canonical orders above. Evidence artifacts and acquisition brackets are frozen and hashed first; manifest entries and the manifest root are then hashed; the individual provider/factor/clock/temporal/capability/verdict objects are recomputed and hashed; only then may the application construct and hash `FormalQualificationProvenance`.

The canonical `FormalQualificationProvenance` input explicitly excludes:

- `qualification_provenance_sha256` itself;
- `gateway_attempt_sha256`;
- `mapping_sha256` / `snapshot_mapping_sha256`;
- `prerequisite_sha256` / `snapshot_prerequisite_sha256`;
- `members_sha256` / `snapshot_member_sha256`;
- `snapshot_content_sha256`;
- `snapshot_record_sha256`;
- every persistence-row hash that can exist only after provenance has been frozen;
- every downstream object or hash whose canonical input directly or transitively includes `qualification_provenance_sha256`.

No excluded value may be read, defaulted, or projected back into the provenance canonical serializer. `GatewayAttempt` may and must bind `qualification_provenance_sha256`; the `universe-snapshot/v2` mapping, prerequisite, member, content, and record hash projections may and must bind the frozen provenance/attempt hashes in their versioned downstream projections. The direction is therefore provenance to attempt to snapshot only. Changing a downstream display, out-of-band audit, persistence metadata, or final hash value cannot change valid recomputation of `qualification_provenance_sha256`.

`PersistedFinalAuditProjection` is assembled only after all listed hashes exist so a persisted audit/display view can show provenance, attempt, content, and record hashes together. It is not `FormalQualificationProvenance`, is not a direct or transitive input to its canonical hash, and creates no membership authority. The sole membership authority remains the persisted `UniverseSnapshot` rows and decisions.

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
published_qualification_set: PublishedQualificationSet
qualification_set_id
qualification_set_version
qualification_set_sha256
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
evidence_manifest: GatewayAttemptEvidenceManifest
evidence_manifest_sha256
evidence_artifact_sha256s: exact immutable ordered tuple
clock_authority_evidence: ClockAuthorityEvidence
temporal_coherence_contract: FormalSnapshotTemporalCoherenceContract
formal_collection_window_reachability_contract: QualifiedFormalCollectionWindowReachabilityContract
factor_qualification_contracts: tuple[FactorQualificationContract, ...]
suspension_freshness_contract: QualifiedSuspensionFreshnessContract
per_code_temporal_verdicts: tuple[SecurityTemporalVerdict, ...]
per_code_factor_temporal_verdicts: tuple[SecurityFactorTemporalVerdict, ...]
required_capability_verdicts: tuple[RequiredCapabilityVerdict, ...]
qualification_provenance: FormalQualificationProvenance
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
  factor_evidence_version                 # C: canonical factor Evidence Version/source identity; exact Snapshot binding
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

The existing field name remains `attempt_status`, not `status`. A successful per-code verdict requires `locked_as_of_date == effective_session_date == UniverseSnapshotHeader.as_of_session`; a non-exempt snapshot row additionally requires `provider_update_local_date` to equal that date. A successful factor verdict requires its `locked_as_of_date` and `effective_session_date` to equal the same header session date. The service-resolved qualification-set ID/version/hash must exactly equal `GatewayAttempt`, `ResolvedFormalQualificationBundle`, and the later header projection; its profile/runtime selector tuple, exact envelope reference, effective interval, stored request-time membership, and ordered factor selections must also verify exactly. The service-resolved provider-envelope ID/version/hash must exactly equal `OpenDConnectionIdentity`, the qualification set, `GatewayAttempt`, every factor contract's provider reference, and the later header projection; every factor's C `factor_evidence_version` must exactly equal between its set selection, accepted registry contract, `GatewayAttempt`, per-code factor verdict, and Snapshot v2 header projection. Missing or mismatched bindings are invariant failures. The embedded `FormalQualificationProvenance` is first recomputed from only the Section 5.6 canonical projection and compared with `qualification_provenance_sha256`; that frozen hash is then a canonical input to `gateway_attempt_sha256`. The `universe-snapshot/v2` mapping, prerequisite, member, content, and record hash projections bind the frozen `qualification_provenance_sha256` and `gateway_attempt_sha256` in addition to their existing versioned business inputs. None of those attempt/snapshot hashes is a provenance input. Capability verdicts use canonical capability-ID order and canonical batch-hash order.

**Proposed Interface — additions to `UniverseSnapshotHeader`**

```text
formal_request_id
formal_intent_sha256
formal_command_sha256
formal_requested_at_utc
gateway_connection_identity
gateway_runtime_identity_probe
gateway_runtime_identity_probe_sha256
gateway_application_context_instance_id
gateway_connection_identity_sha256
gateway_provider_identity_envelope
gateway_provider_identity_contract_id
gateway_provider_identity_contract_version
gateway_provider_identity_contract_sha256
gateway_published_qualification_set
gateway_qualification_set_id
gateway_qualification_set_version
gateway_qualification_set_sha256
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
gateway_evidence_manifest
gateway_evidence_manifest_sha256
gateway_evidence_artifact_sha256s
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

The writer emits exact `snapshot_schema_version = universe-snapshot/v2`. These fields are part of `snapshot_content_sha256` and `snapshot_record_sha256`; `formal_request_id`, `formal_intent_sha256`, and `formal_command_sha256` are therefore immutable replay bindings. The header separately binds the runtime observation tuple, `runtime_identity_probe_sha256`, application context identity, accepted `PublishedQualificationSet` ID/version/hash and effective interval, accepted provider-envelope ID/version/hash, evidence-manifest hash and immutable artifact references, service-resolved qualification-bundle hash, exact A–G factor/version tuple including C `factor_evidence_version` as the canonical factor Evidence Version, and exact accepted contract ID/version/hash for every required factor. `build_snapshot()` must assert exact equality between this header projection, the service-resolved bundle, the stored request-time-selected set, and the supplied `GatewayAttempt`, including the set's profile/runtime selector tuple, exact envelope reference, ordered factor selections, evidence manifest/artifact references, and each factor's C value; no separate factor Evidence Version field is introduced.

The future audit codec allowlist, encoder, decoder, ownership freeze, and hash tests must be extended for the proposed value objects. Future `ApiAcquisitionBracket` values use canonical call order. `PublishedQualificationSet.ordered_factor_selections` uses canonical factor-ID order. `SecurityTemporalVerdict` values use canonical normalized-code order. `SecurityFactorTemporalVerdict` values use canonical `(normalized_code, factor_id)` order. Evidence manifests use the order defined in Section 5.6. Duplicate ordering keys, missing candidates/factors/artifacts, or noncanonical ordering are invariant failures. Readers must retain explicit `universe-snapshot/v1` read compatibility, but only `universe-snapshot/v2` can satisfy this M3C-A2 production qualification contract. SQLite stores the canonical snapshot aggregate in `payload_json`, the schema tag in `schema_version`, and the referenced canonical evidence in the transaction-bound tables defined in Section 9; repository append/get round-trip must reproduce and re-verify the exact qualification-set ID/version/hash, interval, record state, profile/runtime selector tuple, envelope reference, ordered factor selections, evidence manifest, and artifacts. SQLite stores, but never decides, qualification or membership. The evidence tables are not a parallel snapshot payload or authority. The command claim in Section 7 uses the existing `audit_events.event_id` primary key and therefore requires no second command source of truth.

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
7. every non-exempt `get_market_snapshot().update_time`, parsed as `America/New_York`, has local calendar date exactly equal to `as_of_date`, is not earlier than the locked session open, and is not provably later than that batch's response under the timestamp's documented precision and captured acquisition evidence;
8. every required factor under the actual selected FORMAL Profile Version independently satisfies its exact accepted `FactorQualificationContract` in Section 4.3;
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

### 6.5 Future clock authority

This future contract replaces the rejected request-envelope proximity rule. The current production adapter has only `acquired_at_utc` and cannot satisfy the future bracket/evidence contract. Authority is intentionally separated:

- **Session authority:** aware application UTC interpreted through the named, versioned XNYS calendar. Only this pair determines `formal_requested_at_utc`, collection session boundaries, and the unique locked session.
- **Sequencing authority:** one monotonic clock orders the command anchor, every request/response bracket, lifecycle bookends, and completion. It supplies elapsed ordering, not civil/session identity.
- **Provider timestamps:** raw `get_global_state().timestamp` and `local_timestamp`, interpreted at their officially documented precision, are provenance and corroboration only. They never select the session, enlarge an application interval, or become a proximity gate against a sub-millisecond request.
- **Factor freshness authority:** each factor's exact accepted `FactorQualificationContract` defines its effective session, `update_time` semantics where applicable, and lifecycle relationship. A provider clock reading never makes factor evidence fresh.

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
  exchange_calendar: XNYS
  calendar_version
  session_derivation_inputs_and_results
  global_state_start_bracket_sha256
  global_state_end_bracket_sha256
  monotonic_sequence_samples
  raw_server_timestamp_start: optional diagnostic provenance
  raw_server_timestamp_end: optional diagnostic provenance
  server_timestamp_precision: optional; required only when a server value is interpreted
  raw_opend_local_timestamp_start: optional diagnostic provenance
  raw_opend_local_timestamp_end: optional diagnostic provenance
  opend_local_timestamp_precision: optional; required only when a local value is interpreted
  provider_timestamp_interpretations: PRESENT_WITH_DOCUMENTED_PRECISION | NOT_AVAILABLE
  factor_freshness_contract_sha256s
  global_state_response_hashes
  verdict
  reason_codes
  evidence_sha256
```

Threshold-free validation:

1. Capture each aware application UTC read in fixed order `monotonic_before -> aware UTC wall -> monotonic_after`, record its actual resolution, and derive session identity only through the exact versioned XNYS calendar.
2. Every monotonic sample must be finite and nondecreasing. Send precedes receive, start precedes end, and completion follows all required responses. A monotonic reversal is a provable `CLOCK_AUTHORITY_BLOCKER`.
3. A forward or backward application wall-clock step is a blocker only when the captured uncertainty and monotonic sequence no longer determine one unique XNYS session/boundary result for request, start, or completion. A step that leaves the same unique result does not fail merely because the clocks differ.
4. Interpret provider/server and OpenD-host timestamps only at their documented precision and retain the raw values, interpretation, endpoint, bracket, and canonical artifact. No equality, proximity, or interval-intersection predicate between either provider value and the application request bracket is required.
5. Provider corroboration fails closed only on a provable contradiction: an evidence timestamp is certainly in the impossible future relative to the response that carried it; a later same-stream provider observation is certainly earlier than its predecessor after accounting for documented precision; its explicit session label conflicts with the application/XNYS locked session; or it contradicts the qualified provider lifecycle ordering. Mere offset, coarse precision, or indeterminate ordering is not a contradiction.
6. Every required factor proves freshness independently under its selected factor contract. Missing required factor freshness evidence, an effective-session mismatch, an `update_time` contradiction, or a lifecycle contradiction fails closed even when provider clock provenance appears plausible.
7. The only clock/temporal fail-closed grounds are therefore: impossible future, provider regression, session mismatch, lifecycle contradiction, application clock step that prevents unique session determination, monotonic reversal, or missing required factor freshness evidence. Each failure records its exact predicate and durable evidence references.

No arbitrary `+/-N seconds`, magic skew tolerance, provider-to-application timestamp proximity rule, or version-order shortcut is permitted. Provider market-data `update_time` remains governed by its factor-specific effective-session/update/lifecycle contract and may be called future only when the contradiction is provable under the recorded precision and acquisition evidence.

### 6.6 Evidence-class rules

| Evidence class | Examples | Validity rule |
|---|---|---|
| Provider-timestamped dynamic | `get_market_snapshot().update_time` and snapshot-derived current fields | Exact per-code date/window verdict under Sections 6.2 and 6.4; an aggregate oldest watermark is diagnostic only |
| Factor evidence | `PRICE_USD`, `EQUITY_MARKET_CAP_USD`, `LISTED_TRADING_SESSIONS`, and future ADV20 | Exact accepted `FactorQualificationContract`, with its A–G versions and required C factor Evidence Version/source and E derivation hashes; never infer compatibility from another factor, version, or snapshot timestamp |
| Request-scoped current state | future bracketed `get_global_state()`, future bookended `get_market_state()` | Successful shape plus future gateway brackets and exact state/transition contracts |
| Same-attempt static/reference | identity, type/listing flags, owner plate, explicit classification | Complete, internally consistent, provenance-bound, and acquired/resolved in the attempt; no fake market-data timestamp |

### 6.7 Exact consistency binding and blockers

The existing `QualifiedMarketStateConsistencyContract` remains mandatory and exact-bound to provider, SDK version, OpenD version, raw state values, calendar relationships, qualification references, and canonical hash. M3C-A2 additionally requires an exact terminal-closed relationship and permitted-transition contract at both collection bookends.

Formal blockers include:

- naive/non-aware application UTC reads;
- a non-finite or decreasing monotonic sample, or a request-send/response-receive sequencing violation;
- an application wall-clock step only when the recorded wall-clock resolution plus monotonic sequencing no longer permits one unique XNYS session/boundary result for request, start, or completion; a backward or forward wall-clock step that preserves one unique result is not automatically blocked;
- any other clock-authority failure under Section 6.5;
- unavailable/invalid XNYS calendar or contract version;
- a provider timestamp contradiction proved under its documented precision; a coarse or indeterminate provider timestamp alone is not a blocker;
- pre-market, regular-open, or nonterminal after-hours state;
- provider lifecycle or XNYS session change during collection;
- snapshot `update_time` wrong date, before locked session open, or provably future relative to its response under the recorded timestamp precision and acquisition evidence;
- zero/multiple/intersecting, missing, non-effective, or hash-mismatched exact `PublishedQualificationSet`, or any implicit latest/current selection;
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

The application service owns sequencing and resolution of the immutable exact qualification bundle. It opens the attempt's single logical provider-context scope by coordinating the gateway/adapter to create and retain exactly one physical quote context; the gateway/adapter owns physical transport and the single close/finally path. Within that coordinated context the service performs only the minimal non-authorizing `RuntimeIdentityProbe`, selects exactly one stored-time-effective `PublishedQualificationSet` from profile content plus the observed runtime tuple, then dereferences/verifies the exact envelope and named factor contracts from that selected set. The gateway receives that resolved bundle and only verifies/enforces it; it never resolves or accepts compatibility.

### 7.3 Required sequence

1. Validate the public command, reject caller-supplied timestamp/session/readiness/provider/contract fields, canonicalize the intent, and compute `formal_intent_sha256`.
2. Derive a deterministic UUIDv5 `snapshot_id` from a fixed application namespace plus `request_id`; capture the service-owned command anchor/envelope and atomically claim it before any provider operation. Existing duplicate/conflict/terminal-failure rules remain fail-closed and make zero provider calls.
3. For a new claim, resolve the exact published Profile Version through `ProfileRepository.get_published()` on the same SQLite authority as `SnapshotRepository`, verify its exact content/filter/rules hashes, and retain G plus `profile_content_sha256`. This repository does not choose C/D/E/F or compatibility.
4. Open/coordinate one attempt context by asking the gateway/adapter to create and retain exactly one quote context, then perform the immutable, non-authorizing `RuntimeIdentityProbe`. It captures only the documented provider/SDK/OpenD tuple plus mapping/capability versions and canonical hashes/provenance; it is not clock, factor, or FORMAL evidence. Structural probe failure is terminal. This is the sole provider discovery operation allowed before the bundle.
5. Query `QualificationRegistry.resolve_published_qualification_set_exact()` using only the exact profile version/content hash, actual probe-observed provider/SDK/OpenD tuple, and the originally stored service-owned `formal_requested_at_utc`. Require exactly one hash-valid `PUBLISHED` set whose half-open effective interval contains that time. Never select implicit latest/current/highest or lexicographic version and never accept caller-supplied compatibility. After selection, dereference `ProviderIdentityQualificationEnvelope` only through the selected set's exact envelope ID/version/hash, recompute its canonical hash, require `ACCEPTED`, and require its tuple to equal the probe tuple. Then dereference and verify every `FactorQualificationContract` only through the set's canonical ordered A/B/C/E/F selections; each contract must bind that exact envelope D and profile G. Construct one immutable `ResolvedFormalQualificationBundle` containing the set, dereferenced envelope, and ordered factor contracts, and pass it to the gateway. `1009` may match only a set that exactly names its own legacy envelope. Observed `1010` may not reuse it. `QUALIFICATION_SET_ZERO_MATCH`, `QUALIFICATION_SET_MULTIPLE_MATCH`, interval publication corruption, boundary ambiguity, set tamper/missing state, or any `OPEN`, `FAILED_FOR_EXACT_VERSION`, missing, tuple-mismatched, or hash-mismatched dereference — including ADV20 — records a terminal qualification failure before clock acceptance, FORMAL gateway collection, evaluator, build, or persistence; the gateway/adapter closes the retained context.
6. Only after Step 5, use the service-owned anchor and XNYS calendar to derive the candidate completed session. If the application instant is inside regular trading or no completed session exists, fail without full collection; the service does not wait, retry, or silently relabel.
7. The **future gateway** retains the context created in Step 4, receives the service-resolved `ResolvedFormalQualificationBundle`, and captures one canonical `ApiAcquisitionBracket` plus a durable, still-unhashed `EvidenceArtifact` value for every required SDK-decoded request/response/row payload. It separately verifies the selected qualification-set ID/version/hash and ordered selections, the probe tuple/hash, application context identity, later observed provider identity, selected envelope ID/version/content hash, and every factor contract ID/version/hash before it freezes candidate set `C`. Current `RawApiBatch` / `RawApiPage` cannot satisfy this step with `acquired_at_utc` alone.
8. The gateway acquires future start/end `market_state` bookends and required Market Snapshot factor fields. It requires the exact accepted state/window contract, proves the bookends still equal the probe and accepted envelope, and requires every candidate to map to `COMPLETED_SESSION_TERMINAL_CLOSED` for the candidate session. Raw states may differ; normalized relationships may not.
9. Freeze `locked_as_of_session` and `as_of_date` only from XNYS and the qualified start provider lifecycle. No later evidence may move or relabel the lock.
10. Before evaluator input, the gateway verifies exact row coverage, source/derivation evidence, the accepted A–G factor versions, the service-resolved qualification-set/provider-envelope/factor-contract IDs/versions/hashes, exact ordered-set equality, and all clock/window/suspension predicates. It returns a terminal qualification failure for any unproven or mismatched set or contract; the evaluator, `build_snapshot()`, and persistence are not called. On success it freezes the complete canonical provider-evidence value graph; no later step may mutate it.
11. Compute every `EvidenceArtifact.artifact_sha256` and `ApiAcquisitionBracket` hash from the frozen canonical evidence, then every ordered `EvidenceManifestEntry.entry_sha256`, then `GatewayAttemptEvidenceManifest.evidence_manifest_sha256`. No manifest or verdict hash is computed from mutable provider data.
12. Construct and hash the individual provider/factor qualification references, clock authority, temporal coherence, collection-window reachability, market-state consistency, suspension freshness, required-capability verdicts, per-code temporal verdicts, and per-code factor verdicts. Each object binds only already-frozen evidence/artifact/manifest references and uses its specified canonical order.
13. Construct the exact immutable Section 5.6 `FormalQualificationProvenance` projection from those upstream hashes and references, then compute `qualification_provenance_sha256`. No attempt, snapshot, persistence-row, or final-audit hash exists as an input at this step.
14. Construct and freeze `GatewayAttempt` with the complete provenance object and its verified hash, then compute `gateway_attempt_sha256`. This is the first hash layer permitted to consume `qualification_provenance_sha256`.
15. Only after Step 14, run existing per-security evaluation and `build_funnel()`, then call `build_snapshot(kind=FORMAL, ...)` with deterministic identity, the exact service-resolved qualification set/provider envelope/factor contracts, future bracket/clock evidence, evidence-manifest hash and immutable artifact references, locked-session evidence, verdicts, `qualification_provenance_sha256`, and `gateway_attempt_sha256`. The evaluator consumes qualified business evidence and thresholds only; it never decides provider compatibility. The builder emits only `universe-snapshot/v2` for this path.
16. Compute the versioned snapshot mapping, prerequisite, member, content, and record hashes in that deterministic order. Their v2 projections bind the already-frozen provenance and attempt hashes; none is read back into any upstream hash. Assemble `PersistedFinalAuditProjection` only after the record hash exists.
17. Call only `SnapshotRepository.append(snapshot, evidence_manifest, evidence_artifacts)`. Its one SQLite transaction stores the accepted snapshot aggregate, manifest, referenced canonical artifacts, and any downstream final-audit projection. SQLite does not decide qualification or membership.
18. After process-independent reopen with `SnapshotRepository.get(snapshot_id)`, recompute and exact-compare in the same topological order: artifact/acquisition-bracket hashes, manifest-entry/root hashes, individual qualification/clock/temporal/capability/verdict hashes, provenance projection/hash, attempt hash, then snapshot mapping/prerequisite/member/content/record hashes. Return `SUCCEEDED` only after every layer verifies. The replay must never use stored `snapshot_record_sha256` or any other downstream hash to reconstruct provenance; a missing layer, hash mismatch, serializer mismatch, or canonical-order mismatch fails closed.

### 7.4 Attempt diagnostics repository

**Proposed Interface — `QualificationAttemptRepository`**

This repository uses the existing `audit_events` table; it does not introduce a second snapshot store or a membership authority.

```text
claim(public_command, formal_intent_sha256, internal_envelope, snapshot_id)
  -> CLAIMED_NEW | CLAIMED_EXISTING_SAME | REQUEST_ID_CONFLICT
append_failed(
  request_id, application_status, diagnostics,
  evidence_manifest: optional GatewayAttemptEvidenceManifest,
  evidence_artifacts: tuple[EvidenceArtifact, ...],
  created_at_utc
)
get_state(request_id, formal_intent_sha256) -> NONE | STARTED | TERMINAL_FAILED | CONFLICT
```

Rules:

- `claim()` performs a single `BEGIN IMMEDIATE` transaction and attempts one `audit_events` insert whose deterministic primary key is `formal-snapshot-claim:{request_id}`; it never performs a check-then-insert sequence;
- the claim payload contains the canonical public intent, `formal_intent_sha256`, the first service-owned internal envelope and `formal_command_sha256`, and deterministic snapshot ID; on primary-key conflict the same transaction reads the existing claim and returns `CLAIMED_EXISTING_SAME` only after exact public-intent and snapshot-ID equality, otherwise `REQUEST_ID_CONFLICT`;
- an identical replay never replaces or re-hashes the stored service-owned time envelope; it uses the originally persisted `formal_command_sha256` and performs zero provider calls;
- the existing `audit_events.event_id` primary key is the compare-and-set uniqueness boundary, so no new command table or competing snapshot store is required;
- events are append-only;
- diagnostics contain canonical reason codes, capability verdicts, durable evidence-manifest/artifact references, and exception class/message sanitized of credentials;
- successful provider evidence is transactionally associated with the immutable snapshot through its manifest and need not be duplicated as authority in `audit_events`; failed `UNKNOWN`, conflict, or schema-anomaly artifacts are atomically stored with their failure event and manifest by `append_failed()` under a separate attempt-diagnostic transaction;
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
| `PublishedQualificationSet` is missing, tampered, non-effective, interval-intersecting, zero/multiple-match, or selected by implicit latest/current/highest/lexicographic or caller compatibility | `FAILED` | `INCOMPLETE` | false | No | Show exact qualification-set blocker before envelope/factor dereference; use only stored `formal_requested_at_utc`, profile content, and runtime tuple | No |
| Application UTC/XNYS cannot identify one session, monotonic ordering reverses, or provider/factor evidence proves an impossible-future, regression, session, or lifecycle contradiction | `FAILED` | `INCOMPLETE` | false | No | Show `CLOCK_AUTHORITY_BLOCKER` with the exact contradiction; provider timestamp proximity and arbitrary skew are never predicates | No |
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

### 9.2 Successful aggregate and evidence atomicity

The future `SnapshotRepository.append(snapshot, evidence_manifest, evidence_artifacts)` extends, but does not split, the existing atomic boundary:

Before this method writes, the producer must complete the Section 5.6/7.3 topology in memory: freeze canonical provider evidence; compute artifact/acquisition-bracket hashes; compute manifest entry/root hashes; compute individual qualification/clock/temporal/capability/verdict hashes; construct/hash `FormalQualificationProvenance`; construct/freeze/hash `GatewayAttempt`; run evaluator/funnel/builder; and compute snapshot mapping, prerequisite, member, content, and record hashes. Every input at each layer must already exist and be immutable. No persistence-generated row hash or downstream audit projection may feed any earlier layer.

- validate and freeze the snapshot, complete ordered manifest, and referenced artifact set before writes;
- issue one `BEGIN IMMEDIATE` before any successful-result write;
- insert content-addressed artifacts into `evidence_artifacts`, keyed by `artifact_sha256`, with exact serializer ID/version, payload kind, provider/SDK/OpenD identity, endpoint, scope identity, encoding, and canonical payload;
- on an existing artifact hash, accept deduplication only when every stored metadata field and canonical payload byte/text value is identical; otherwise fail as a collision/tamper condition;
- insert one manifest root and all ordered entries into `gateway_attempt_evidence_manifests` and `gateway_attempt_evidence_manifest_entries`, with foreign keys to every referenced artifact;
- insert one `universe_snapshots` row, all `snapshot_securities` rows, and all `snapshot_security_decisions` rows, with the header binding `evidence_manifest_sha256` and the exact immutable artifact-reference tuple;
- rollback artifacts, manifest, snapshot header, rows, and decisions together on any error;
- commit only after the complete graph is present and all foreign keys/hashes verify;
- allow an exact idempotent replay only when snapshot record hash, manifest hash, entries, artifact metadata, and canonical payloads are identical;
- reject the same snapshot ID with conflicting record, manifest, or artifact content;
- keep immutable update/delete triggers effective for snapshots, manifest associations, and artifacts referenced by an immutable snapshot.

The artifact tables and manifest tables live in the same SQLite database and transaction boundary as the snapshot repository; they are not files, logs, or best-effort post-commit writes. A failure diagnostic event does not make a snapshot partially persisted. `QualificationAttemptRepository.append_failed()` may atomically retain a failed attempt's event, manifest, and required full anomaly artifacts without creating a snapshot row. A successful application result exists only after transactional append and restart-safe read-back verification.

### 9.3 Restart reopen and fail-closed validation

`SnapshotRepository.get(snapshot_id)` first reopens the immutable snapshot aggregate, then loads the manifest by the header's exact `evidence_manifest_sha256`, resolves every artifact reference, and selects the decoder only by the stored `serializer_id + serializer_version`. It then replays the same dependency DAG: recompute and exact-compare artifact/acquisition-bracket hashes; manifest entry order/hashes and root hash; individual provider/factor/clock/temporal/capability/verdict objects and hashes; the exact `FormalQualificationProvenance` canonical projection and `qualification_provenance_sha256`; the frozen `GatewayAttempt` and `gateway_attempt_sha256`; and finally snapshot mapping, prerequisite, member, content, and record hashes. Stored attempt/content/record hashes are comparison targets only and must never be supplied as provenance inputs.

Missing manifest/entry/artifact rows, duplicate or reordered entries, reference-set mismatch, artifact/hash mismatch, manifest/hash mismatch, unavailable/unsupported/substituted serializer ID or version, serializer mismatch, decode failure, canonical-order mismatch, or any layer's replay disagreement yields a repository-integrity failure and no FORMAL reopen. The UI must not show ready and M3D must not receive the snapshot ID. Deduplication never weakens this rule: one physical artifact may satisfy many immutable references only when its complete content and metadata are identical.

These tables are evidence persistence, not membership authority. They can explain, verify, and replay why a persisted row received `MEMBER`, `FAIL`, or `QUARANTINE`, but cannot create or override any decision. Only the transactionally persisted `UniverseSnapshot` header, securities, and decisions define membership, and M3D continues to load only its persisted `MEMBER` rows by exact snapshot ID.

### 9.4 Canonical ownership

- Adapter SDK-decoded payloads are copied/frozen before canonical serialization and hashing.
- Domain evidence, prerequisite, evaluation, funnel, member, manifest, and artifact-reference collections are immutable owned values.
- The snapshot header binds all relevant hashes, distinct probe/context/envelope identities, provider provenance, `evidence_manifest_sha256`, and exact artifact references.
- Decoding/reopening must reproduce typed enums, exact serializer versions, and exact canonical hashes.
- No wire-level fidelity is claimed unless an artifact's payload kind explicitly stores actual provider wire bytes; canonical SDK-decoded payload is labeled as such.
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

1. The non-authorizing `RuntimeIdentityProbe`, runtime state, and start/end bookends accept exact supported true forms for `qot_logined` and exact `READY`. Tests first select exactly one set using stored request time, profile content, and the observed provider/SDK/OpenD tuple; only then do they dereference the set's exact envelope ID/version/hash, recompute its hash, and require its tuple to equal the observation. The probe cannot select or supply clock/factor/FORMAL authority, and a changed context or identity after bundle resolution fails before evaluator/build/persist.
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
14. `PRICE_USD`, `EQUITY_MARKET_CAP_USD`, `LISTED_TRADING_SESSIONS`, and ADV20 each have independent accepted `FactorQualificationContract` evidence; each contract's C `factor_evidence_version` is the canonical factor Evidence Version enforced in the registry and Snapshot; no factor may inherit authority from Stock Screen, another factor, an acquisition timestamp, or a different provider version.
15. PRICE tests require Market Snapshot `last_price` plus `update_time` under the completed-session contract; MARKET_CAP tests require `total_market_val` plus `equity_valid`/`issued_shares`/`last_price` consistency. Both bind new C `factor_evidence_version` values, independently bound E derivations, exact D/F provider-envelope/factor contracts, and the provider-envelope reference ID/version/hash; under their approved factor decisions, G remains the exact existing Profile Version when business semantics and thresholds do not change.
16. LISTED tests require Market Snapshot `listing_date`, a named/versioned XNYS calendar, both-inclusive completed-session arithmetic, and selected-session hash. The accepted change requires the new C `factor_evidence_version`, exact E derivation and F factor contract, and a new G Profile Version because its accepted membership identity changes, while preserving threshold `>=250`.
17. Tests preserve the observed Stock Screen `AVG_TURNOVER=3105` `period_average=None`, `True`, and `False` forms as rejected. They prove none supplies CORE v1 ADV20 authority; no provider implementation is selected until an alternate scalable authority is separately qualified.
18. Registry tests cover A business semantic, B metric identity, C `factor_evidence_version` (the canonical factor Evidence Version/source identity), D provider/version, E derivation identity, F qualification contract, and G Profile Version independently. They prove selection comes only through an exact `PublishedQualificationSet`; an E-only change leaves C unchanged, records/binds new E, and requires F requalification; an alternate ADV20 authority requires a new C factor Evidence Version and a new G even when membership is unchanged, updates E only when its derivation changes, and newly qualifies F, while E-only changes ordinarily do not change G. They also prove `OPEN`, `FAILED_FOR_EXACT_VERSION`, missing, and hash-mismatched provider/factor contracts stop before evaluator/build/persist, and that evaluator compatibility logic is absent.
19. The exact-version suspension contract is required for every FORMAL attempt; every non-exception row records `EXCEPTION_NOT_APPLIED`, and no empty/no-suspension candidate set bypasses the contract.
20. Qualified current `suspension=True` yields security-level `FAIL/SUSPENDED_AS_OF_SNAPSHOT` even when price `update_time` is old; it does not waive any other required evidence.
21. Missing, conflicting, or unqualified suspension freshness makes the provider attempt `FAILED/INCOMPLETE`; explicitly qualified unknown status may instead yield security-level `QUARANTINE/ACTIVE_STATUS_UNKNOWN` but never receives the stale-price exception.
22. Every security/factor temporal verdict round-trips explicit locked/effective/provider-local dates as applicable; a successful verdict whose session date differs from `UniverseSnapshotHeader.as_of_session` is an invariant failure and changes attempt/content/record hashes.
23. A **future implementation** captures aware application UTC, named/versioned XNYS calendar inputs, monotonic sequencing, precision-aware provider corroboration, and gateway brackets. Tests inject forward/backward application clock steps, monotonic reversal, impossible-future provider evidence, provider regression, session/lifecycle contradictions, coarse provider precision, and an application interval straddling an XNYS boundary. Only a provable contradiction or inability to derive one session fails; provider/application proximity is never asserted and no skew threshold is introduced. This does not assert that current `RawApiBatch` / `RawApiPage` contain brackets.
24. Tests persist and distinguish the runtime observation tuple, actual `runtime_identity_probe_sha256`, selected envelope ID/version, recomputed envelope `contract_sha256`, and immutable `application_context_instance_id`/connection hash. Probe and envelope hashes are never compared for equality. A changed context object fails; when documented `connID` is exposed, start/end mismatch also fails. Context identity is not proof that brackets exist.
25. Zero/multiple/intersecting, non-effective, missing, or hash-mismatched `PublishedQualificationSet`, or `OPEN`, failed, unknown, or hash-mismatched `ProviderIdentityQualificationEnvelope`, `QualifiedMarketStateConsistencyContract`, `QualifiedFormalCollectionWindowReachabilityContract`, `FormalSnapshotTemporalCoherenceContract`, `FactorQualificationContract`, `QualifiedSuspensionFreshnessContract`, or `ClockAuthorityEvidence` fails closed.
26. Draft, missing, or hash-mismatched profile cannot produce `FORMAL`; published `CORE:v1` remains byte/hash-identical.
27. Unknown prerequisite/classification is represented and quarantined; missing evidence makes collection incomplete.
28. S0-S10 counts reconcile exactly and are bound into canonical hashes.
29. `build_snapshot()` remains the final in-memory formal gate.
30. Repository failure at every artifact, manifest, header, row, and decision insert position rolls back the complete successful aggregate.
31. Same request ID after success returns the same reopened snapshot with zero provider calls.
32. Same request ID after terminal failure or ambiguous start makes zero provider calls.
33. The public command rejects `requested_at_utc`, qualification-set/compatibility selection, and every session/readiness override; identical public intent reuses the original stored internal envelope and its original set-selection time, while a different public intent produces `REQUEST_ID_CONFLICT` without provider calls.
34. Passive Streamlit render/rerun makes zero provider calls; one explicit click invokes the service once.
35. UI displays only the reopened persisted snapshot as ready.
36. M3D consumes the exact persisted snapshot ID and does not recompute membership.
37. Concurrent identical public intents produce exactly one atomic claim and at most one provider invocation; a reused request ID with a different public intent returns `REQUEST_ID_CONFLICT`.
38. A **future implementation** makes `universe-snapshot/v2` round-trip every proposed qualification field, rejects missing/unknown fields, preserves v1 read compatibility, and makes `formal_intent_sha256`, service-owned `formal_requested_at_utc`, the clock anchor, future gateway-captured `ApiAcquisitionBracket` values, the distinct runtime tuple/probe hash/context identity/envelope identity/envelope hash, the exact accepted `PublishedQualificationSet` ID/version/hash/effective interval/record state/ordered selections, evidence-manifest hash and exact artifact references, service-resolved-bundle IDs/versions/hashes, A–G versions including C `factor_evidence_version`, exact factor contract IDs/versions/hashes, locked-session data, lifecycle/reachability contracts and bookends, fully defined per-code/per-factor verdicts, factor/suspension contracts, canonical ordering, and all associated hashes content/record-hash sensitive.
39. The current `latest_summary()` Today Scan behavior is not accepted for exact handoff; the future integration test injects/selects a specific snapshot ID and proves a newer snapshot cannot replace it.
40. `PublishedQualificationSet` tests prove append-only immutability, exact profile-content/runtime-provider-SDK-OpenD tuple keying, canonical ordered-factor hashing, rejection of a missing/tampered set, rejection at publication of intersecting intervals, half-open boundary behavior (`from` included, `until` excluded), exactly-one selection by the originally stored service-owned `formal_requested_at_utc`, zero-match and multiple-match fail-closed behavior under corrupted/legacy state, and the complete absence of implicit latest/current/highest/lexicographic fallback. Only after set selection do tests dereference its exact envelope ID/version/hash and ordered factor contracts; a D/F-only change creates a new disjoint effective-dated set without changing G and leaves the predecessor historically readable.
41. Evidence persistence tests inject failure at every artifact, manifest, snapshot-header, security-row, and decision-row insert and prove one rollback boundary. Restart tests reopen the manifest and every canonical artifact with exact serializer ID/version, recompute hashes, and replay FORMAL bindings. Missing artifacts, hash/manifest mismatch, serializer mismatch, dedup collision, and incomplete `UNKNOWN`/`QUARANTINE`/conflict/schema-anomaly payload retention all fail closed. Evidence never creates membership independently of persisted snapshot rows/decisions.
42. An explicit dependency/topological-order test constructs the hash DAG in the Section 5.6/7.3 order: frozen evidence -> artifact/acquisition-bracket hashes -> manifest entry/root hashes -> individual qualification/clock/temporal/capability/verdict hashes -> `FormalQualificationProvenance` -> `qualification_provenance_sha256` -> `gateway_attempt_sha256` -> snapshot mapping/prerequisite/member/content/record hashes -> `PersistedFinalAuditProjection`. It proves no self-reference or cyclic dependency exists; attempt/snapshot downstream hashes are absent from the provenance serializer; changing any provenance-level input changes `qualification_provenance_sha256`; changing that hash changes the attempt and snapshot downstream hashes; changing a downstream-only presentation/audit field does not change provenance; and restart recomputation uses the identical DAG and canonical orders. Missing layers, hash mismatches, serializer mismatches, and canonical-order mismatches all fail closed.

### 12.2 Windows real-environment acceptance

This acceptance is executed only in a later authorized implementation/validation node. It is not executed during this design task.

Preconditions:

- Windows host and configured local OpenD;
- exact Futu SDK/OpenD identity with an accepted immutable provider envelope and factor/clock contracts; `1010` observations alone and any `1009` mapping/hash reuse are insufficient;
- OpenD quote login ready;
- OpenD launched with effective `auto_hold_quote_right=0`, verified and captured from its startup configuration/console before the run; no acceptance step changes this setting. This prevents OpenD’s automatic quote-right reacquisition path from undermining the no-side-effect claim; see the official [OpenD configuration documentation](https://openapi.futunn.com/futu-api-doc/en/opend/opend-cmd.html);
- a quiescent acceptance environment with no unrelated OpenD clients changing subscriptions during the evidence window;
- Telnet/O&M channels disabled for the run or independently monitored so no `request_highest_quote_right` operation can occur; the operation’s cross-device side effect is documented by Futu’s [OpenD operation command reference](https://openapi.futunn.com/futu-api-doc/en/opend/opend-operate.html);
- historical `CORE:v1` remains loaded only as an immutable readable/auditable reference; the requested FORMAL run selects a newly published explicit Profile Version whose LISTED and ADV20 C/G identities exactly match the accepted contracts;
- clean, backed-up acceptance database path;
- the requested production-validation run is started only inside a window class accepted by the version-bound reachability contract for the **entire exact candidate set**; premarket, regular-session, nonterminal after-hours, `OVERNIGHT`, and unreachable weekday attempts are negative tests only;
- every applicable Section 17 prerequisite has separate explicit authorization where it needs empirical capture and has already produced its accepted immutable exact-version contract artifact before any production qualification attempt;
- explicit operator action and authorization for real provider requests.

Required evidence record:

- git commit and clean/dirty status used for the run;
- application version;
- requested UTC time, locked XNYS session/date/open/close, start/end provider lifecycle states, and the proof that both bookends refer to the same terminal-closed session;
- the future gateway's aware application UTC/XNYS session inputs, clock resolution, every provider call's monotonic send/receive ordering, raw global-state `timestamp`/`local_timestamp` values with documented precision, provider-corroboration interpretations, factor-specific freshness evidence, and every exact contradiction/verdict;
- configured host/port, SDK version, OpenD server version, accepted provider-envelope ID/version/hash and qualification evidence references, immutable application context instance ID, proof that every required call used that same context object, application connection identity hash, and optional documented provider connection ID with exact start/end equality;
- `qot_logined` and `program_status_type` values;
- exact required-capability verdicts, expected/observed counts, endpoint batch hashes, and acquisition interval;
- acceptance-harness `query_subscription(is_all_conn=True)` evidence immediately before and after the service call: raw response hashes, `total_used`, `own_used`, `remain`, option quota fields, and the all-connection `sub_list`; this is out-of-band audit evidence, must show no service-created subscription or quota delta, and cannot influence the qualification verdict. The scope is explicit because the SDK can otherwise restrict results to the current connection; see the official [subscription query reference](https://openapi.futunn.com/futu-api-doc/en/quote/query-subscription.html);
- confirmation that no subscribe/unsubscribe/right-escalation call occurred; only the acceptance harness, not the production service, may issue the two read-only `query_subscription()` audit calls;
- the captured effective `auto_hold_quote_right=0` value plus an isolated OpenD log/operation interval showing no automatic reacquisition and no Telnet/O&M `request_highest_quote_right` command;
- selected newly published Profile Version and exact content/filter/rules hashes, plus separate historical `CORE:v1` bytes/hash/history verification without using `CORE:v1` as the new FORMAL profile;
- selected `PublishedQualificationSet` ID/version/hash, half-open effective interval, record state, exact profile-content/runtime-provider-SDK-OpenD selector tuple, qualification references, exact envelope ID/version/hash, and canonical ordered factor selections, plus each source-neutral factor identity, its A–G versions including C `factor_evidence_version` (the canonical factor Evidence Version/source identity), exact provider/derivation definition, accepted contract ID/version/hash, canonical evidence hashes, and independent per-factor verdicts; Stock Screen `3105` None/True/False remains rejected;
- accepted evidence from a separately selected alternate ADV20 authority proving arithmetic mean of actual USD dollar turnover over exactly 20 completed XNYS sessions, with that authority bound as a new C factor Evidence Version and the required new G Profile Version, plus LISTED `listing_date`/XNYS both-inclusive evidence under the new Profile Version;
- start/end per-code raw market-state evidence and normalized session relationship, the accepted collection-window reachability artifact and actual candidate-set reachability verdict, snapshot suspension/status evidence, the accepted suspension qualification-spike artifact, exact snapshot update watermark, and every per-code temporal/suspension verdict;
- exact `GatewayAttemptEvidenceManifest`, `evidence_manifest_sha256`, ordered `EvidenceManifestEntry` records, every referenced `EvidenceArtifact`, serializer ID/version, canonical SDK-decoded payload, artifact hash, and restart replay result; no wire-level fidelity is claimed unless actual provider wire bytes are separately captured;
- exact `FormalQualificationProvenance` schema/projection and `qualification_provenance_sha256`, its explicit exclusion of attempt/snapshot/persistence-row/final-audit hashes, the topological build/restart trace, `gateway_attempt_sha256`, and the downstream-only `PersistedFinalAuditProjection`;
- gateway status/completeness/formal-ready/reason codes;
- S0-S10 totals, member/fail/quarantine counts, and reconciliation;
- persisted snapshot ID plus mapping/prerequisite/member/content/record hashes;
- process restart followed by exact snapshot, evidence-manifest, and canonical artifact reopen; exact serializer selection, artifact/manifest hash equality, and FORMAL decision replay;
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
QUALIFICATION_SET_ZERO_MATCH
QUALIFICATION_SET_MULTIPLE_MATCH
QUALIFICATION_SET_HASH_MISMATCH
PROVIDER_ENVELOPE_TUPLE_MISMATCH
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
EVIDENCE_ARTIFACT_MISSING
EVIDENCE_ARTIFACT_HASH_MISMATCH
EVIDENCE_MANIFEST_HASH_MISMATCH
EVIDENCE_SERIALIZER_VERSION_MISMATCH
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
| Set-first immutable stored-time/profile-content/runtime-tuple selection; exact envelope dereference; no implicit latest/current/highest | Sections 4.3, 5, 7, and 12.1 |
| Completed-session and provider-lifecycle lock | Sections 5 and 6.1-6.3 |
| Independent factor qualification authority and pre-evaluator gateway enforcement | Sections 4.3, 5, 6.2, and 7 |
| Suspension/halt freshness semantics | Sections 5 and 6.4 |
| Application UTC/XNYS session authority, monotonic sequencing, and provider timestamp corroboration without proximity/skew gates | Sections 4.1, 5, and 6.5 |
| Transaction-bound canonical evidence artifacts/manifests, restart replay, and hash binding | Sections 5.6-5.7 and 9 |
| Existing domain invariants preserved | Sections 3.3 and 5 |
| Production entrypoint | Section 7 |
| Streamlit rerun idempotency | Sections 7.5 and 10.3 |
| Atomic immutable persistence | Section 9 |
| M3D consumes persisted authority | Section 11 |
| Windows real acceptance | Section 12.2 |

## 17. Open Design Blockers

The state machine is proposed but not implementation-ready. The linked 2026-09-01/04/05 OpenD evidence remains historical diagnostic evidence; it accepted no provider, clock, factor, or suspension qualification contract. In particular, its `futu_api 10.10.7008` + OpenD `1010` captures are unqualified. They cannot inherit any legacy exact `1009` mapping, contract, or hash, and `formal_ready=false`.

The open items below are post-spec-review implementation and empirical blockers. They block Gate C formal production readiness, but they do not block Gate A Design Spec review completion: this Design can be internally coherent, fail-closed, and ready for independent spec review while the future implementation and empirical qualification work remains open.

1. **`FUTU_EXACT_PROVIDER_IDENTITY_ENVELOPE`** — create and accept an immutable envelope for each exact `(provider, SDK, OpenD)` identity before any clock acceptance. The `1010` envelope must independently bind provider/version identity, mapping/schema/capability definitions, qualification references, and its canonical hash; it may not reuse any legacy `1009` artifact. The recorded `1010` observations are diagnostic, not an accepted envelope.
2. **`FUTU_FORMAL_COLLECTION_WINDOW_REACHABILITY_QUALIFICATION`** — only after the exact identity, future bracket/canonical-retention seam, and replacement clock contract are accepted, prove raw-state-to-session mapping and reachable terminal-closed windows for every claimed class: standard weekday, early close, both DST directions, weekend, XNYS holiday, and overnight/next-session boundaries. The recorded `AFTER_HOURS_END`/per-code `OVERNIGHT` and historical clock observations are negative diagnostics. Until accepted, no supported FORMAL window is published.
3. **`FORMAL_PROFILE_FACTOR_QUALIFICATION_REGISTRY`** — treat `CORE:v1` only as an immutable historical reference, then accept exact, source-neutral A–G contracts for `PRICE_USD`, `EQUITY_MARKET_CAP_USD`, and `LISTED_TRADING_SESSIONS` under the actual newly published FORMAL Profile Version, each bound to an accepted exact provider envelope by ID/version/hash, and bind them in `universe-snapshot/v2`. PRICE requires Market Snapshot `last_price`/`update_time`; MARKET_CAP requires `total_market_val` with `equity_valid`/shares/price consistency; LISTED requires `listing_date`, named/versioned XNYS, both-inclusive completed-session derivation, selected-session hash, and the new G Profile Version. The historical Stock Screen `2201`, `2301`, and `2307` results remain legible diagnostics, not FORMAL authorities. The historical `3105` None/True/False observations are REJECTED for ADV20.
4. **`PUBLISHED_QUALIFICATION_SET_AUTHORITY`** — publish no selectable set until the exact provider envelope and every required factor contract, including ADV20, are accepted. The registry must append an immutable ID/version/hash-bound set for the exact profile-content/runtime-provider-SDK-OpenD selector tuple and a disjoint half-open effective interval. The service selects exactly one using that tuple plus its stored `formal_requested_at_utc`, then dereferences only the set's exact envelope ID/version/hash and ordered factor contracts. A D/F-only successor receives a new set while preserving G and the old historical set. No profile-only, runtime-to-newest-envelope, latest/current/highest-version, or caller compatibility selection is allowed.
5. **`ADV20_ALTERNATE_SCALABLE_AUTHORITY`** — ADV20 remains `OPEN`: it needs an authority for the exact arithmetic mean of actual USD dollar turnover across exactly 20 completed XNYS sessions ending `as_of`. The provider-neutral interface is frozen, but no provider implementation is selected or claimed. A later selected authority requires a **mandatory new C `factor_evidence_version` (the canonical factor-specific Evidence Version/source identity)**, a new E only if its derivation changes, a newly qualified F contract, accepted provider envelope, and a **mandatory new G Profile Version even if accepted membership identity is unchanged**. This ADV20-specific requirement does not add a separate Evidence Version axis or weaken the general C/E orthogonality rule: an E-only change ordinarily leaves C and G unchanged. Historical CORE:v1 bytes/hashes are not rewritten.
6. **`FUTU_SUSPENDED_SECURITY_FRESHNESS_QUALIFICATION`** — using an authorized sample, prove that suspension/status is independently current under terminal-closed lifecycle bookends even when `last_price` `update_time` is old. Bind the exact provider identity, future gateway bracket/canonical evidence, corroboration, allowlisted mapping, and contract hash. The recorded `CRNX`, `HCHL`, and `LPSN` facts remain diagnostic; none authorizes the stale-price exception. Until accepted, that exception is forbidden.

Failure to prove a contract is not permission to weaken it. `OPEN`, `FAILED_FOR_EXACT_VERSION`, missing, or hash-mismatched qualification remains a pre-evaluator blocker. Historical recomputation is not silently substituted, and no historical CORE:v1 snapshot is rewritten.

## 18. Completion Gate for This Spec

### 18.1 Abstract model-routing policy

Every Gate A review requires an independent high-capability review. The applicable automated model-routing policy selects the actual model and reasoning effort from task complexity, correctness risk, token/usage cost, and prior review history. This Design does not hardcode a model name, provider, tier, or reasoning level; the policy lineup may evolve without a Design edit, and the independent review records the route it actually used.

### 18.2 Gate A — Design Spec Review Ready

Gate A is reached only when this documentation reconciliation has completed independent Design Spec review and is ready for user spec re-review. It requires:

- this Design Spec and its linked qualification-evidence document reconcile the exact-identity, immutable qualification-set selection, factor-authority, versioning, bracket, and fail-closed boundaries above;
- this docs-only node's committed/PR scope cleanly contains only those two documents and does not alter protected code, tests, profiles, data, SQLite, snapshots, or historical evidence bytes;
- prior findings within this docs-only scope are repaired and linked historical Evidence integrity is preserved;
- the required independent high-capability review reports zero Critical and zero Important findings, with a review artifact that records the actual model, reasoning level, reviewed HEAD, Critical count, and Important count; and
- `git diff --check` passes.

After every Gate A requirement is satisfied, `READY FOR USER SPEC RE-REVIEW` may be emitted while any Section 17 blocker remains open. That token does not mean `IMPLEMENTATION AUTHORIZED`, `FORMAL READY`, `formal_ready=true`, or production accepted. It also must not be emitted to imply that a pending independent review has completed.

### 18.3 Gate B — Explicit user implementation authorization

Gate B requires an explicit user authorization for a separately bounded implementation scope after Gate A. It is the only gate that permits code, schema, profile, provider, clock, or production-repair work to begin. A review result, this Design, or the existence of a Draft PR does not substitute for that authorization. Any provider capture or other empirical work must receive its own explicit authorization when it reaches that boundary.

### 18.4 Gate C — Formal production ready

Gate C requires Gate B, an implemented and independently reviewed fail-closed system, all applicable tests and acceptance checks, accepted exact-version qualification artifacts, and resolution of every Section 17 blocker. It also requires the separately authorized real-environment acceptance described in Section 12.2, including immutable evidence persistence and exact restart replay. Until then, `formal_ready=false`; this Design and its Draft PR must not claim formal production readiness.
