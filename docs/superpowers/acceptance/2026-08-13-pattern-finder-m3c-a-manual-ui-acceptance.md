# M3C-A Task 3 Universe Profile Page Smoke Record

Status: `UI_SMOKE_ONLY`

Date: 2026-08-14

The initialized `CORE:v1` ProfileRegistry was supplied to the 股票池设置 page.
The page rendered the published profile identity (`CORE:v1`, `CORE v1`, and
`PUBLISHED`), frozen conditions, and both content hashes. This was exercised
with the Streamlit AppTest UI smoke command recorded in the task report.

This is a rendering-only checkpoint. It does not evaluate securities, claim
membership, render a member count, or constitute functional acceptance.

## User Manual UI Smoke

Date: 2026-08-15

`MANUAL_UI_RESULT`: `PASS`

The user manually confirmed these observed facts:

- The Universe Settings page opened normally.
- The CORE v1 Profile information displayed normally.
- The current official version came only from a `PUBLISHED` record.
- A non-Published record did not appear as the current official version.
- The page did not claim that final Universe membership was complete.
- The page did not display fabricated security `PASS`, `FAIL`, or `UNKNOWN` results.

This result is `UI_SMOKE_ONLY`. It is not full business functional acceptance.

## M3C-A Task 5 Security Master Qualification Record

Date: 2026-08-15

`QUALIFICATION_STATUS`: `PASS`

`SECURITY_MASTER_SOURCE`: Bloomberg OpenFIGI API v3

`AUTHORITY_LEVEL`: `CORROBORATED`

`SOURCE_VERSION`: `openfigi-api/v3`

OpenFIGI is approved only as corroborated Security Master evidence. It is not
authoritative evidence and may not be promoted to `AUTHORITATIVE`.

The qualified structured fields are:

- `securityType`
- `securityType2`
- `marketSector`
- `exchCode`
- `figi`

Classification remains fail-closed. No match, an empty `securityType` or
`securityType2`, or an unapproved new enum value resolves to `UNKNOWN`.
Conflicting evidence resolves to `CLASSIFICATION_EVIDENCE_CONFLICT`. Ticker,
name, suffix, and regex heuristics are prohibited. Futu `STOCK` alone never
resolves to `COMMON_STOCK`.

The raw record SHA-256 values below cover the exact UTF-8 JSON response on the
single line inside each `json` block, excluding Markdown fence newlines. The
recorded retrieval time is the original qualification-run time and was not
replaced when the locators and hashes were reverified for persistence.

### Qualified Common Stock Sample

- Normalized class: `COMMON_STOCK`
- Ticker: `AAPL`
- FIGI: `BBG000B9Y5X2`
- Structured `securityType`: `Common Stock`
- Structured `securityType2`: `Common Stock`
- Structured `marketSector`: `Equity`
- Structured `exchCode`: `UW`
- Source locator: `https://api.openfigi.com/v3/mapping/ID_BB_GLOBAL/BBG000B9Y5X2`
- Retrieval UTC: `2026-08-15T06:39:08.250Z`
- Source version: `openfigi-api/v3`
- Raw record SHA-256: `b2aaeb7b71166529ffcc597773eff7a918e999ad5107df3c83c0fb42889c3ccc`

```json
[{"data":[{"figi":"BBG000B9Y5X2","name":"APPLE INC","ticker":"AAPL","exchCode":"UW","compositeFIGI":"BBG000B9XRY4","securityType":"Common Stock","marketSector":"Equity","shareClassFIGI":"BBG001S5N8V8","securityType2":"Common Stock","securityDescription":"AAPL"}]}]
```

### Qualified ADR Sample

- Normalized class: `ADR`
- Ticker: `BABA`
- FIGI: `BBG006G2JVQ7`
- Structured `securityType`: `ADR`
- Structured `securityType2`: `Depositary Receipt`
- Structured `marketSector`: `Equity`
- Structured `exchCode`: `UN`
- Source locator: `https://api.openfigi.com/v3/mapping/ID_BB_GLOBAL/BBG006G2JVQ7`
- Retrieval UTC: `2026-08-15T06:39:09.251Z`
- Source version: `openfigi-api/v3`
- Raw record SHA-256: `d5cced9e3b49692e4dfc47d2bf1d1cc724d9c74d59b79c099f02837afb1736d0`

```json
[{"data":[{"figi":"BBG006G2JVQ7","name":"ALIBABA GROUP HOLDING-SP ADR","ticker":"BABA","exchCode":"UN","compositeFIGI":"BBG006G2JVL2","securityType":"ADR","marketSector":"Equity","shareClassFIGI":"BBG006G2JWB1","securityType2":"Depositary Receipt","securityDescription":"BABA"}]}]
```

### Qualified Preferred Sample

- Normalized class: `PREFERRED`
- Exchange ticker: `BAC PR L`
- Provider ticker: `BAC 7.25 PERP L`
- FIGI: `BBG000004TB8`
- Structured `securityType`: `PUBLIC`
- Structured `securityType2`: `Preferred Stock`
- Structured `marketSector`: `Pfd`
- Structured `exchCode`: `NEW YORK`
- Source locator: `https://api.openfigi.com/v3/mapping/ID_BB_GLOBAL/BBG000004TB8`
- Retrieval UTC: `2026-08-15T06:39:09.565Z`
- Source version: `openfigi-api/v3`
- Raw record SHA-256: `feb620bd6840ff93367dc24eab8c0026b9798ea3ae1de03d214e50c5a15f2bf2`

```json
[{"data":[{"figi":"BBG000004TB8","name":"BANK OF AMERICA CORP","ticker":"BAC 7.25 PERP L","exchCode":"NEW YORK","compositeFIGI":null,"securityType":"PUBLIC","marketSector":"Pfd","shareClassFIGI":null,"securityType2":"Preferred Stock","securityDescription":"BAC 7 1/4 PERP"}]}]
```

### Qualified Unit Sample

- Normalized class: `UNIT`
- Ticker: `FWACU`
- FIGI: `BBG022432C49`
- Structured `securityType`: `Unit`
- Structured `securityType2`: `Unit`
- Structured `marketSector`: `Equity`
- Structured `exchCode`: `US`
- Source locator: `https://api.openfigi.com/v3/mapping/ID_BB_GLOBAL/BBG022432C49`
- Retrieval UTC: `2026-08-15T06:39:09.907Z`
- Source version: `openfigi-api/v3`
- Raw record SHA-256: `7bec2b6cdfbc927e72e4589e34863e286f4ba4254b576147ee13f72b9a1b6a06`

```json
[{"data":[{"figi":"BBG022432C49","name":"FUTUREWAVE ACQUISITION CORP","ticker":"FWACU","exchCode":"US","compositeFIGI":"BBG022432C49","securityType":"Unit","marketSector":"Equity","shareClassFIGI":"BBG022432D92","securityType2":"Unit","securityDescription":"FWACU"}]}]
```

### Qualified ETF/Fund Sample

- Normalized exclusion class: `ETF`
- Ticker: `SPY`
- FIGI: `BBG000BDTF76`
- Structured `securityType`: `ETP`
- Structured `securityType2`: `Mutual Fund`
- Structured `marketSector`: `Equity`
- Structured `exchCode`: `UP`
- Source locator: `https://api.openfigi.com/v3/mapping/ID_BB_GLOBAL/BBG000BDTF76`
- Retrieval UTC: `2026-08-15T06:39:10.221Z`
- Source version: `openfigi-api/v3`
- Raw record SHA-256: `440a4badde3b92532f938229c86a2e27ba24e188745599cb183cc414e50344ad`

```json
[{"data":[{"figi":"BBG000BDTF76","name":"SS SPDR S&P 500 ETF TRUST-US","ticker":"SPY","exchCode":"UP","compositeFIGI":"BBG000BDTBL9","securityType":"ETP","marketSector":"Equity","shareClassFIGI":"BBG001S72SM3","securityType2":"Mutual Fund","securityDescription":"SPY"}]}]
```

### Qualification Boundary

- `FUTU_QUALIFICATION`: `FAIL`
- `CRSP_CURRENT_ACCESS`: `UNAVAILABLE`
- `MASSIVE_CURRENT_ACCESS`: `UNAVAILABLE`
- `CLASSIFICATION_EVIDENCE_BLOCKER`: `NONE`
- `TASK5_CODE_CHANGE_REQUIRED`: `NO`
- `TASK_6_STARTED`: `NO`

## M3C-A Task 7 Automated Projection Checkpoint

Date: 2026-08-21

`AUTOMATED_PROJECTION_RESULT`: `PASS`

The 股票池设置 page rendered only a prebuilt `EvaluationUiState`, which was
created by passing provider-shaped immutable evidence, classification, and
Task 6 prerequisites unchanged to `evaluate_security()` exactly once. The
page projected the resulting ticker/security, Profile Version / Hash, CORE
Member, Quarantine, first exit, and every Task 6 decision's actual and
normalized values, threshold, reason, evidence source/reference/version.

Automated fixture cases:

- `AAPL` Common Stock PASS: `CORE Member = YES`, `Quarantine = NO`.
- `AAPL` identity UNKNOWN: `CORE Member = NO`, `Quarantine = YES`, with
  `S1_IDENTITY_VALID / UNIVERSE_IDENTITY_BLOCKER` shown as the reason.

This is an `AUTOMATED_PROJECTION_CHECKPOINT` only. It is not the first real
manual functional acceptance: it does not claim a provider evidence loading,
Task 10 freshness/identity producer, Snapshot, Preview, publication, or live
Futu workflow. `FIRST_REAL_MANUAL_FUNCTIONAL_TEST_AFTER_TASK=15` remains
unchanged, and `MANUAL_UI_TEST_REQUIRED_AFTER_TASK_7=NO`.

## M3C-A Task 12 Automated Persisted-Snapshot Projection Checkpoint

Date: 2026-08-23

`TASK12_CHECKPOINT`: `AUTOMATED_PERSISTED_SNAPSHOT_PROJECTION`

`AUTOMATED_PERSISTED_SNAPSHOT_PROJECTION_RESULT`: `PASS`

`NOT_FIRST_REAL_MANUAL_FUNCTIONAL_GATE`: `YES`

The automated fixture was built as a production-shaped `UniverseSnapshot`,
persisted through `UniverseSnapshotStore.append()`, and reloaded only through
`UniverseSnapshotStore.get()`. The read model and 股票池设置 page projected the
persisted Snapshot status, fixed funnel, separate MEMBER / FAIL / QUARANTINE
sets, exact security search, all field decisions, raw Industry and every Owner
Plate, classification evidence, normalized Identity/Active evidence, provider
and mapping qualification bindings, prerequisite/member/content/record hashes,
and Snapshot-derived downloads. Missing, corrupt, and invalid Snapshot
contracts were displayed as explicit errors rather than zero members or an
ineligible security.

The fixture includes exact Liquidity and Listing History boundaries, listing
auxiliary warning, Classification PASS/UNKNOWN, Identity and Active
PASS/FAIL/UNKNOWN, both evidence conflicts, COMPLETE/INCOMPLETE, member,
non-member, Quarantine, and first-exit cases. The Snapshot load path performs
no evaluator, funnel, classification, mapping, freshness, reconciliation,
normalization business-rule, provider, or Futu call.

This is not a manual acceptance result and does not claim production Preview
orchestration or a live end-to-end Universe workflow. The first real Manual
Functional Gate remains Task 15. No manual Gate status was created or changed
for Task 12.
