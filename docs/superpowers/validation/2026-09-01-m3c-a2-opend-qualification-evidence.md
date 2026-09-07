# M3C-A2 OpenD Qualification Evidence

Date: 2026-09-01 UTC

Status: **DIAGNOSTIC ONLY — NO QUALIFICATION CONTRACT ACCEPTED**

## 1. Scope and safety boundary

This evidence was collected under the separately approved minimum-scope OpenD qualification task for:

1. FORMAL collection-window reachability;
2. Stock Screen temporal authority; and
3. suspended/halted-security freshness.

The spike used read-only quote calls only. It did not call `subscribe()`, `request_highest_quote_right()`, any trading API, any database API, or any snapshot persistence path. It did not modify production code, `data/`, or `migration_backup/`. No fixture or fabricated provider response was used.

All hashes in this document are SHA-256. A hash explicitly described as a **sanitized projection hash** covers only the displayed field projection, not an undisclosed full provider response. Such a hash is diagnostic and cannot satisfy a contract that requires the full canonical raw response.

### Contract Reconciliation II truth label

All observations in this evidence document are historical, diagnostic qualification-harness observations. They do not establish that the current production adapter has full acquisition brackets or lossless wire bytes: production `RawApiBatch` / `RawApiPage` retain deterministic batching, canonicalized SDK-level request/response hashes and rows, and a single `acquired_at_utc`. Any wall/monotonic send/receive envelope or bracket below is qualification-harness-only until a future gateway/adapter change records the specified immutable evidence.

The observed identity `futu_api 10.10.7008` + OpenD `1010` is independently **unqualified**. Legacy production OpenD `1009` is an exact-qualified identity, not a minimum version or schema proxy. No inference may be drawn from `1010 > 1009`, and no FORMAL evidence may reuse a `1009` mapping or contract hash. This label preserves every historical timestamp, hash, table, and verdict below; it does not rewrite them.

## 2. Environment identity

| Item | Observed value |
|---|---|
| Repository base commit | `a1183c543de0adb4a71b60402d64d1deedc2f80b` |
| Branch | `codex/pattern-finder-m3c-a2-formal-snapshot-qualification` |
| Python SDK | `futu_api 10.10.7008` |
| OpenD `server_ver` | `1010` |
| Initial Protobuf runtime | `7.35.1` |
| Remediated Protobuf runtime | `6.33.6` |
| Declared dependency | `futu_api` declares `protobuf>=3.20.0` |
| Repository pins after remediation | `protobuf==6.33.6`; `futu-api>=10.9.0,<11` |
| OpenD runtime | `qot_logined=true`; `program_status_type=READY` |

The Python mapping did not expose a supported provider `connID`. Each individual spike used exactly one `OpenQuoteContext`; application process identity was not treated as provider connection identity. Context reuse is not proof that production brackets existed.

## 3. Collection-window reachability observation

### 3.1 Call shape

One application context performed bracketed `get_global_state()` and representative `get_market_state()` calls. Application UTC wall reads and monotonic reads bracketed each call. The representative set was:

`US.AAPL`, `US.SPY`, `US.QQQ`, `US.MSFT`, `US.TSLA`.

No candidate was dropped to manufacture a common state.

### 3.2 Lifecycle result

At `2026-09-01T01:35:58Z` and again at `2026-09-01T01:39:22Z`:

- global `market_us` was `AFTER_HOURS_END`;
- every representative security returned `OVERNIGHT` at the observed bookend(s);
- `OVERNIGHT` is next-session-active and is not `COMPLETED_SESSION_TERMINAL_CLOSED` under the Design Spec; and
- therefore the observed weekday window is ineligible and yields `FORMAL_WINDOW_UNREACHABLE_FOR_CANDIDATE_SET`.

Evidence hashes from the first complete capture:

| Evidence | SHA-256 |
|---|---|
| Global-state start response | `fe8eb3acbe6964bc54079a0f455818640042f973b12d4fd2217737ddf03154f8` |
| Representative market-state start response | `e08acc3595edbd661c073c5c32c3145d511b75e3a418b28570425cf06d0a7101` |
| Representative market-state end response | `e08acc3595edbd661c073c5c32c3145d511b75e3a418b28570425cf06d0a7101` |
| Global-state end response | `889f8ccd23a98239a5b60a29889b6bd97b87524927f77fd45c100c2c5bdee557` |

This single negative window does not qualify weekday, weekend, XNYS-holiday, early-close, or either DST-transition reachability.

### 3.3 Clock prerequisite result

The corroborating capture at `2026-09-01T01:39:22Z` did not include the complete Section 6.5 application-anchor artifact and therefore cannot satisfy that contract. Its direct raw-wall diagnostic also failed the required overlap shape:

| Bookend | Server whole-second interval | Application request envelope | Overlap |
|---|---|---|---|
| Start | `[1788226761, 1788226762)` | `[1788226762.6284509, 1788226762.6290004]` | false |
| End | `[1788226761, 1788226762)` | `[1788226762.6773074, 1788226762.6781204]` | false |

The start OpenD `local_timestamp=1788226762.628694` was inside its raw-wall application envelope. The end `local_timestamp=1788226762.677006` preceded its send sample by about 0.3 ms and was outside the zero-tolerance point-envelope check. No tolerance was invented and the Design Spec was not weakened. Because the complete anchor artifact is absent and the direct diagnostic does not overlap, the clock prerequisite was not established and the reachability contract remains open.

## 4. Stock Screen temporal-authority observation

### 4.1 Exact production request

The spike constructed the existing production request for US market page 0, page size 200:

- basic: `CODE=1101`, `NAME=1102`, `INDUSTRY=1103`;
- simple: `PRICE=2201`, `MARKET_CAP=2301`, `LISTED_DAYS=2307`;
- cumulative: `AVG_TURNOVER=3105`, `days=20`, omitted `period_average`; and
- cumulative: `AVG_VOLUME=3104`, `days=20`, omitted `period_average`.

The production `_screen_request_record(0)` projection hash was:

`9471d10aa13e801af0cf46665f95172083729629e841bd2437a181c810fc77aa`

An earlier diagnostic schema that explicitly represented omitted/default fields produced `2d9218b65f7e2cb3042ff79b5723bf515dd5bdc16a4817f2d719c7e479eb12f0`. These hashes cover different canonical schemas and are not compared for equality.

### 4.2 Initial result

Both exact invocations failed locally with:

- `ret_code=-1`;
- payload type `str`;
- error: `'google._upb._message.FieldDescriptor' object has no attribute 'label'`; and
- failure-response hash: `a4e0a247bd7d6821df521b6561f77fa8f73d9bfa1a07298a27c2c8010cc08b34`.

The installed `futu` package references `FieldDescriptor.label`, while Protobuf 7.35.1 does not expose that attribute. The second call returned in approximately 0.05 ms and produced no Stock Screen rows. This established a local SDK/runtime incompatibility rather than a provider permission verdict.

### 4.3 Approved dependency remediation and rerun

An isolated probe installed Protobuf 6.33.6 without changing the active environment and reran the same production request. It returned:

- `ret_code=0`;
- `all_count=9379`;
- page 0 row count 200;
- production request-record SHA-256 `9471d10aa13e801af0cf46665f95172083729629e841bd2437a181c810fc77aa`; and
- diagnostic harness response SHA-256 `1d8f1b0fac7a682f5988ce303fe59e7471f75b001e1c8f51b20b10beeeea50a3`.

This confirmed Protobuf 7.35.1 as the cause of the original serialization failure. The approved minimal remediation changed `requirements.txt` to `protobuf==6.33.6`, installed that version in the active Python 3.14 environment, and produced `pip check: No broken requirements found`.

The direct success then exposed a separate production-path shape mismatch. OpenD/Futu returned `last_page` as integer `0`, while `FutuProviderAdapter.screen_all_pages()` requires `type(last_page) is bool`. The exact production adapter rerun therefore stopped with:

`FUTU_PAGINATION_BLOCKER: last_page must be bool`

No pagination normalization or production adapter change was authorized in that remediation node. At that point:

- one diagnostic provider page was acquired, but no complete production pagination result was produced;
- no page, ADV20, `LISTED_DAYS`, PRICE, or MARKET_CAP temporal comparison was possible;
- no property semantic was qualified; and
- `FUTU_STOCK_SCREEN_TEMPORAL_AUTHORITY_QUALIFICATION` remains open.

### 4.4 Approved pagination-shape repair and full-production rerun

A subsequent explicitly approved repair used test-first development to narrow the accepted provider shape without weakening fail-closed behavior:

- Python `bool` remains accepted unchanged;
- exact Python integers `0` and `1` are normalized to application-control `False` and `True`;
- the provider's original `0`/`1` value remains in the canonical raw response and therefore in the response hash;
- integers outside `0/1`, strings, floats, and `None` remain rejected; and
- continuation state, `RawApiPage.is_last_page`, and loop termination use only the normalized `bool`.

The RED run produced `1 failed, 7 passed` at the original `last_page must be bool` branch. The GREEN boundary run produced `8 passed`; the complete adapter test file produced `37 passed`; and the focused Futu suite produced `108 passed`.

The exact production `FutuUniverseGateway` host/port binding and `FutuProviderAdapter.screen_all_pages()` path was then rerun against local OpenD. The pagination-shape blocker did not recur. OpenD logged the connection at `2026-09-01 14:06:14` Asia/Shanghai and logged an orderly adapter close at `2026-09-01 14:06:44`. At approximately the first 30-second limiter boundary, however, the provider rejected a subsequent Stock Screen request with `ret_code=-1` and raw SDK detail:

`Ƶ��̫�ߣ�����ʧ�ܣ�ÿ30�����10�Ρ�`

The raw text is mojibake, but it retains the explicit `30` and `10` limit values and occurred exactly at the adapter's first `10 requests / 30 seconds` boundary. This is recorded as `FUTU_SCREEN_RATE_LIMIT_BOUNDARY_BLOCKER`. The production method failed closed and returned no partial page tuple; the context was closed. No timing buffer, retry reinterpretation, limiter change, or diagnostic sleeper override was applied.

Consequently, complete pagination still was not obtained, the response-hash chain could not be finalized, and no page-wide PRICE, MARKET_CAP, ADV20, or `LISTED_DAYS` temporal comparison was performed. The factor contract remains unqualified.

### 4.5 Approved screen-rate boundary repair and successful full pagination

A further explicitly approved test-first repair preserved the provider limit of 10 Stock Screen requests while requiring the client to cross, rather than equal, the documented 30-second provider window. The RED test observed the previous exact `30.0` second wait and failed its strict `> 30.0` assertion. The minimal production change applies only to `SCREEN_POLICY`, using a conservative 31-second client window; the generic limiter, request count, other endpoint policies, and retry semantics were not changed. The GREEN test passed, the complete adapter file produced `37 passed`, and the focused Futu suite produced `108 passed`.

The exact production `FutuUniverseGateway` host/port binding and `FutuProviderAdapter.screen_all_pages()` path then completed successfully against local OpenD:

- started: `2026-09-01T06:22:36.677970+00:00`;
- completed: `2026-09-01T06:24:41.475227+00:00`;
- duration: `124.797` seconds;
- page count: `47`;
- `all_count`: stable at `9379` on every page;
- total returned rows: `9379`;
- offsets: deterministic `0` through `9200` in increments of `200`;
- page sizes: 46 pages of `200`, then one final page of `179`;
- provider `last_page`: exact integers `0` on pages 1-46 and `1` on page 47;
- application `is_last_page`: exact booleans `False` on pages 1-46 and `True` on page 47;
- first-page `RawApiPage.request_hash`: `733a08c5ebe50ccbce1910736c51747a9386706484a39d89910df6aeb04f99ab`; and
- ordered response-hash-chain SHA-256: `19bcdf7a97c48c6d5a6d52e68ecab07b7f3775c5ebec47f491f7b0bf3db895b1`.

OpenD logged an orderly adapter close. No rate-limit rejection recurred, so `FUTU_SCREEN_RATE_LIMIT_BOUNDARY_BLOCKER` is resolved for this observed exact-version run. The pages existed only in diagnostic process memory and were not inserted into SQLite, relabeled as a snapshot, or retained as a qualification contract artifact.

A post-window single-page schema sample at `2026-09-01T06:26:40.031542+00:00` returned 200 rows and the same `all_count=9379`. Each row contained `stock_id` plus an ordered `results` list with the requested properties `1101`, `1102`, `1103`, `2201`, `2301`, `2307`, `3105 days=20`, and `3104 days=20`. Raw absent values remained absent: property `2301` had no value member in all three sampled rows. The payload contained no per-field timestamp, completed-session label, or effective date.

Complete pagination and raw hashing are therefore proven for this run, but temporal factor semantics are not. There is still no active-versus-terminal PRICE/MARKET_CAP differential, no independent completed-session/effective-date authority, no independent 20-session ADV arithmetic comparison, and no explicit listing-date inclusivity comparison. `FUTU_STOCK_SCREEN_TEMPORAL_AUTHORITY_QUALIFICATION` remains open.

### 4.6 Temporal-factor capture preflight and automatic continuation

An approved read-only preflight at `2026-09-01T06:48:17.349942+00:00` established:

- XNYS session: `2026-09-01`;
- XNYS regular open: `2026-09-01T13:30:00+00:00`;
- XNYS regular close: `2026-09-01T20:00:00+00:00`;
- OpenD `server_ver=1010`, `qot_logined=true`, and `program_status_type=READY`;
- global US state: `AFTER_HOURS_END`;
- `US.AAPL` and `US.SPY` per-code states: `OVERNIGHT`;
- canonical global-state hash: `337241637ebca266f76a0e327e781557009373604389e1b67c17a61bbde70ad3`; and
- canonical market-state hash: `3a0fa25abf63dee4b6ebcd3a0542bd49a79b5735a4183d66743463733a0cbbd7`.

This was not an eligible active capture and was not relabeled as one. One thread heartbeat, `m3c-a2-active-factor-capture`, is active: it begins at 22:00 Asia/Shanghai and checks hourly through the expected terminal observation period. It must capture the exact production request only when raw lifecycle evidence establishes the required active or terminal side, must avoid repeating a completed active full-screen capture, and must stop after both sides complete or a genuine external blocker is fully recorded.

The provider's official v10.10 quotation definitions identify `PRICE=2201` as last price, `MARKET_CAP=2301` as market cap, `LISTED_DAYS=2307` as days since listing, and `AVG_TURNOVER=3105` as average turnover, but do not establish their effective session in the returned Stock Screen row: <https://openapi.futunn.com/futu-api-doc/en/quote/quote.html>. Nasdaq publishes dated historical prices and Nasdaq Official Closing Prices, which were then candidate independent completed-session price authorities: <https://www.nasdaq.com/market-activity/quotes/historical> and <https://www.nasdaq.com/market-activity/quotes/historical-nocp>. Its documented real-time/delayed API also exposes timestamped price and bar fields but requires subscriber credentials: <https://docs.data.nasdaq.com/docs/api-for-real-time-or-delayed-data>. No accessible independent historical market-cap source with an explicit effective date/session was qualified in this preflight. These statements preserve the historical Stock Screen investigation; the later reconciliation rejects those properties as FORMAL CORE v1 authorities and instead proposes the source-neutral interfaces in Section 9.

### 4.7 Strict clock artifact and independent-factor groundwork

**Qualification-harness-only bracket observation — not a current production adapter field.** At `2026-09-01T07:08:29Z`, a single read-only `OpenQuoteContext` captured the complete Section 6.5 diagnostic shape in the fixed anchor order `monotonic_before -> aware UTC wall -> monotonic_after`. It then bracketed global-state start, per-code market-state start/end, and global-state end with raw wall and monotonic samples. The application clock reported a runtime resolution of `0.0000001` seconds.

| Clock evidence | Start | End |
|---|---|---|
| Raw server `timestamp` | `1788246508` | `1788246508` |
| Server represented interval | `[2026-09-01T07:08:28Z, 2026-09-01T07:08:29Z)` | `[2026-09-01T07:08:28Z, 2026-09-01T07:08:29Z)` |
| Projected request/response envelope | `[2026-09-01T07:08:29.882607Z, 2026-09-01T07:08:29.883386Z]` | `[2026-09-01T07:08:29.949512Z, 2026-09-01T07:08:29.950217Z]` |
| Server interval overlaps envelope | false | false |
| Raw OpenD `local_timestamp` | `1788246509.881962` | `1788246509.949786` |
| Local represented interval | `[2026-09-01T07:08:29.881962Z, 2026-09-01T07:08:29.881963Z)` | `[2026-09-01T07:08:29.949786Z, 2026-09-01T07:08:29.949787Z)` |
| Local interval overlaps envelope | false | true |
| Raw wall versus monotonic projection | overlap | overlap |

The application anchor SHA-256 was `148f8892bfeabe5a2341a6846f10d153193fb8a5feb9ad4fe15a2925ab798b3`. The complete diagnostic artifact SHA-256 was `fef8b7a6d33fa42e13a8353f66aab4e57b1d62bf2179e5c941cc40b2d2fad116`. Start/end global response hashes were `c7bca090400aa6a2f3aee8d9535ce4b1c865fdc991b650cc308e27b5d7814ac4` and `4d5fa0b8cb32d2706d0bc5a8735672c0140bbb0b6c8dfc26376206460969215f`; both market-state response hashes were `7f07da8fe1f78292b837dbe14e21e6599aaa8d35a6d12bea1e8befbc950769a1`.

The global US state remained `AFTER_HOURS_END`; `US.AAPL` and `US.SPY` remained `OVERNIGHT` at both market-state bookends. The independently locked completed XNYS session was `2026-08-31`, with regular boundaries `2026-08-31T13:30:00Z` through `2026-08-31T20:00:00Z`. This was neither the requested active capture nor a terminal-closed capture. The strict clock prerequisite is **OPEN**: the complete application anchor is internally corroborated, but the provider server interval did not overlap either request envelope and the start OpenD-local interval also did not overlap. No skew tolerance was introduced. This is recorded as a contract-versus-observed-provider-shape blocker, not an adapter bug or a qualified clock contract.

The official Nasdaq historical endpoint returned exact dated close and volume rows for all 20 XNYS sessions from `2026-08-04` through `2026-08-31` for the stable `AAPL`, `NVDA`, and `MSFT` sample. The independent response/input hashes and arithmetic results were:

| Symbol | Nasdaq response SHA-256 | Selected 20-row input SHA-256 | Mean of daily close x volume (USD) |
|---|---|---|---:|
| `AAPL` | `d67cf87eadf114a9bc9939cb573a44933e04ddb354e81e642247c4c01813029e` | `1ff4a3490c79f26e23c20fff9069b8c4c08f63e2c0cf4b6c3eaacecd631b6241` | `12,847,481,901.315` |
| `NVDA` | `21bf0507c04b57712c4534cba101fdd1a81581e1986e38bdb3eceeaba03c1c22` | `9d95d6e36a074b1fde006bb3e25b39df029593dec41a3f74f9cb13465f9fff41` | `27,948,740,175.535` |
| `MSFT` | `e1cc541a33626ae0f1b32fa6ae904b6628473347ce18e6f6904c4696a1555de0` | `6b2495c667c692dc05b26690cd39fe1a1dfde70fb9cfe51105ed9c45c0bdb210` | `13,127,625,915.24` |

This is a reproducible independent `close x volume` arithmetic comparison, not direct consolidated dollar-turnover truth. It prepares the exact 20-completed-session comparison but does not qualify `AVG_TURNOVER=3105` until the matching Futu value is captured and its relationship to this calculation is established.

A read-only `get_market_snapshot()` listing-date projection for `US.AAPL`, `US.NVDA`, and `US.MSFT` had SHA-256 `c06ef96e42baa1736d8af275cab889b44427e2de3a7cd3f2c0a7c4117e0f3a5e`. It returned listing dates `1980-12-12`, `1999-01-22`, and `1986-03-14`, respectively. Apple and NVIDIA issuer materials independently report the same dates. Microsoft independently reports its IPO as `1986-03-13`, one day earlier than the Futu listing date, so no silent equivalence is claimed.

The real Futu US discovery set contained a safer near-threshold sample: `US.KLAR`, with Futu listing date `2025-09-10`, not delisted, and 245 inclusive XNYS sessions through `2026-08-31`. Klarna's issuer release and SEC exchange certification independently establish `2025-09-10` as the first-trading/listing date. At the time, `KLAR` was preselected for property `2307` extraction from a future full capture; it did not authorize an extra pagination run. Both-inclusive arithmetic would be 245 through `2026-08-31` and 246 through `2026-09-01`; exclude-listing arithmetic would be one less. The subsequent reconciliation retains this arithmetic evidence but rejects `LISTED_DAYS=2307`; the proposed `LISTED_TRADING_SESSIONS` derivation owns the inclusivity rule instead.

Sharadar's documented Daily Fundamentals table was investigated as a programmatic candidate for `MARKET_CAP` because it defines a primary-key price date and daily market capitalization in USD millions: <https://sharadar.com/docs/daily>. The unauthenticated Nasdaq Data Link request returned HTTP `403`, and no credential was requested, discovered, or exposed. Consequently no effective-dated Stock Screen market-cap comparison was acquired. The later reconciliation does not keep `MARKET_CAP=2301` as a FORMAL authority; it preserves this unsuccessful investigation as diagnostic history.

### 4.8 Premarket negative-boundary observation

At `2026-09-01T08:02:41.504422+00:00`, the next automatic read-only lifecycle check observed `PRE_MARKET_BEGIN` at both bookends for global US state and every selected code: `US.AAPL`, `US.NVDA`, and `US.MSFT`. XNYS independently identified the `2026-09-01` session with regular boundaries `2026-09-01T13:30:00+00:00` through `2026-09-01T20:00:00+00:00`. This is a genuine premarket negative boundary, not an eligible active full capture and not a terminal-closed relationship, so no Stock Screen request was issued.

The market-state start/end hashes were both `1ad991cb09b7da0c67918bb768ac5b1bfd86747c4e30046736d22217107e6226`. Global-state start/end hashes were `a544f152985cdfcc2b6a7a88196c6c08f01810cafc29bccda333772a2c8c0d5b` and `11972c0527709c28b61952e91aa862a22f8e9441cc9fcfc92001c706777fc6e9`. The complete diagnostic artifact hash was `352894d4ea49ca998585ceab28858c29c130f0652908119abea5d1c23251436d`.

The application raw-wall samples again overlapped their monotonic projections. The strict provider clock predicates again failed without tolerance: both server intervals were `[2026-09-01T08:02:40Z, 2026-09-01T08:02:41Z)` and did not overlap the corresponding request envelopes; both OpenD-local represented intervals also preceded and did not overlap their request envelopes. This independently reproduces the Section 4.7 contract-versus-provider clock blocker. Clock authority remains OPEN.

### 4.9 XNYS 2026-09-01 ACTIVE capture

#### 4.9.1 Scheduler actual status

The existing heartbeat remained configured `ACTIVE` and no duplicate automation was created. The Codex thread history exposes one completed automatic execution from `2026-09-01T08:01:55Z` through `2026-09-01T08:03:16Z`; it recorded the Section 4.8 `PRE_MARKET_BEGIN` negative boundary and returned `DONT_NOTIFY`. The automation metadata does not expose a next-run timestamp or a last-result field. No later automatic heartbeat turn exists before the manual continuation began at `2026-09-01T18:12:25Z`, despite the configured 22:00 Asia/Shanghai check. This establishes a scheduler invocation blocker for the expected ACTIVE check. Whether Codex session inactivity caused the miss is not exposed and is not asserted.

#### 4.9.2 ACTIVE lifecycle and clock evidence

The immediate manual check started at `2026-09-01T18:16:19.159489Z`. XNYS independently reported session `2026-09-01`, regular open `2026-09-01T13:30:00Z`, regular close `2026-09-01T20:00:00Z`, and `is_open=true`. Global US state was `AFTERNOON` at both bookends. `US.AAPL`, `US.SPY`, `US.NVDA`, and `US.MSFT` were all `AFTERNOON` at both per-code bookends. `qot_logined=true`, `program_status_type=READY`, and `server_ver=1010`.

The lifecycle artifact SHA-256 was `1eed0c3c889564cb07429e0401bcedb29dcd0914810a29276210fd10004f8902`. Global start/end response hashes were `49761505a13f59eceded3bbf761cb8d44c9b446ee8b590cd1e57661b0f94281a` and `e9e4dca18aa02a7f3693fb9a68612fea9ea1aa01bdad4124959f64f5e209a2fe`; both per-code market-state hashes were `5488c1786eea22e878510089caf27e994c63307d1b32c562f8dcdeedfad8ba80`.

Application wall samples overlapped their monotonic projections. Strict clock qualification nevertheless remained OPEN. The start server interval `[2026-09-01T18:16:18Z, 2026-09-01T18:16:19Z)` did not overlap its request envelope, and the end server interval `[2026-09-01T18:16:19Z, 2026-09-01T18:16:20Z)` did not overlap its request envelope. No tolerance was added.

The post-capture check at `2026-09-01T18:26:14.326170Z` still returned global and all four per-code states as `AFTERNOON`. Its artifact SHA-256 was `72560686fa5a12aaed824d2f9ab60eb8df5ca35e3831869e6b63a32923070a0c`; the strict whole-second server predicate again failed at both bookends. The full collection therefore remained inside one observed ACTIVE lifecycle relationship.

#### 4.9.3 Exact production pagination

The exact path was `FutuUniverseGateway._adapter() -> FutuProviderAdapter.screen_all_pages()` with `SCREEN_POLICY.max_requests=10`, `window_seconds=31.0`, and `page_size=200`. It started at `2026-09-01T18:18:54.347287Z` and completed at `2026-09-01T18:22:00.557769Z`; monotonic duration was `186.2104766` seconds. It completed 61 pages and terminated normally. The ordered request-hash tuple SHA-256 was `0d91f0e4f30b438c70776585279206e6c8e0f02d1cdc0adb1830a7bd84e418b3`; the ordered response-hash chain SHA-256 was `d9b88e44c3c561da8458fd1670bb60eda456d49148024d04f9b572d1c388b2b8`.

The initial in-memory summary incorrectly tested the frozen `Mapping` as an exact `dict`, so its row/target projection was empty. The production adapter itself was unaffected: deterministic offsets advanced by actual row counts, returned pages 1-60 at offsets `0..11800`, and terminated on page 61 at offset `12000`. Immediate exact-request corroboration returned stable `all_count=12101`, 200 rows on nonterminal pages, 101 rows on the terminal page, raw integer `last_page=0/1`, and normalized booleans `false/true`. No full pagination was repeated. Target values were recovered only through the smallest specific page calls and are labeled separately below.

Stock Screen supplied no provider timestamp, effective date, or session label for any factor: all three fields are `NONE`.

| Page | Offset | Size | Raw last_page | Normalized | Request SHA-256 | Response SHA-256 |
|---:|---:|---:|---:|---|---|---|
| 1 | 0 | 200 | 0 | false | `733a08c5ebe50ccbce1910736c51747a9386706484a39d89910df6aeb04f99ab` | `1e707bc52e5f386b33182e43652c1698c883e7fce39a196ca4629a31c1842423` |
| 2 | 200 | 200 | 0 | false | `891e21b151839cb88e9b7db8e121a06094c2b02321a92e412a4ac2e0c7ee9cb7` | `459dec82ca31cbd4e411a4668aa6ba0a5cb7cda2a15adc8d2adf58fdf65ec93f` |
| 3 | 400 | 200 | 0 | false | `e99bbd3fb6e1a5703b7909ca9025cab722a58a7aa00abed60c835122ab3ebbde` | `3734d86841a27963a27c9035f1dc62494e91e7f1fc8fe2acb6f5d84efe778a61` |
| 4 | 600 | 200 | 0 | false | `52dccedb13aafeba70f4ea4676fb32ef43eb5ddceab04a8cfc25bb35d011e869` | `3a285006637005a98186f876ab13e6348afbbefd655d4a297324d85d1c739b95` |
| 5 | 800 | 200 | 0 | false | `2a90edc659135fabb7d7619cdf4ec5219bef9501a16849f0259a9e7607dd172b` | `d7a2677869b92987e2c77eb1c7563c769477ae353387d7e4092542f9f4450f58` |
| 6 | 1000 | 200 | 0 | false | `9485579676f8ebc3333528bc93b34df5b69ea13a390d3d612d93ecf72a026747` | `34ef8026a2e3636b9ce28c589c5cf37a85ebcd6827c98eaf921bfc2a4effdf17` |
| 7 | 1200 | 200 | 0 | false | `8f06184b0efada390f3427ef92b89a364204e8da7cbc356132e9bd6ba70d0223` | `012aa558d9943684546ad0356745025422a70fd0cff9f4299866e0d905d21242` |
| 8 | 1400 | 200 | 0 | false | `c4813432bba3d88f3f486d0767c6ae62037b2526e5e92424642c99dc7df55bf4` | `8f3cee32b16fa32eb822e11ba1febde2d5cdc2fc928acbd1c1af9f6b786fa702` |
| 9 | 1600 | 200 | 0 | false | `d8b8371d0bd973183da3088331aa955a47556d883c30a70c6e1d55d7725bb9d4` | `e051235cb7fdfa00ff77a32cef3f309f23d3cc1f0cfbb0eafe191c1e92dc368e` |
| 10 | 1800 | 200 | 0 | false | `b4b3e9b086cc2498a11ffe3dfa7142f04fd863c7cd4eb6e5d9ad58dd8b215938` | `9b39134616633b974718283642ad33abf5a4c824f6119e7e12ca078e59f2b5f9` |
| 11 | 2000 | 200 | 0 | false | `13860a3c4356b2bf029c5738d0920182aea19441b7ee6b67183eb3c1ea2c6b04` | `b21bd98ab860b4a81c688c5ed68d4e5a54120eb1e1db579e34cade7b12bd0667` |
| 12 | 2200 | 200 | 0 | false | `c3ee4bd51d14f55188b4cc4786245b0cef0ca7cf625d1e7842e9c12a5ca80c0c` | `2403fa9e03ada10b27ad04ff00867b302ec204570620df11619d4c8c59f1b53d` |
| 13 | 2400 | 200 | 0 | false | `b856667e2624e1374eb2589bb6dfd1f14fa358bf85f9e8292c839825aee22889` | `6d070aaf052e0513e3a42af8a5e1f00a60715f6780ed20fce293b2f5ddecdfd3` |
| 14 | 2600 | 200 | 0 | false | `7dbfbfc90d08f3c0a9fd22f97f0c9f1c491349f9e2026ffb764e8599db0d5c82` | `eef1504cbe624b7143270b635a2066715a40548fc047cb7933362f9a30f4e697` |
| 15 | 2800 | 200 | 0 | false | `3cdeaa2c87e911dcf0d5943ff38b327abc3ee5d215f431248e583df4aa270346` | `cb16e1efe51a647eb26fca9d57049a2971bb8347319f73422d936d40483b7583` |
| 16 | 3000 | 200 | 0 | false | `0f4ab82dd50394aad977b7ce48b817df1795c07b00f07b659d4a8ad289d59832` | `535b1a41e5c5e45ea5d48e22f1637519e333bd7455cd75778ae2da97e1e058f4` |
| 17 | 3200 | 200 | 0 | false | `a03e8f9e206a73da53a2cda8ec67c93b0c510911da59b3ed6dddf01bf986110f` | `135eabede0631de65b6ea37fbb30546e6c0e040a071c822fd53b78293abcd997` |
| 18 | 3400 | 200 | 0 | false | `55025aa0de57e03abb1d9983497469dbabf5072bf1b134b952a98d345baf94cd` | `bcf7c81c7da60227b2454cb47cc70c1db8d341cb6cf0196534c19e4cf86460bf` |
| 19 | 3600 | 200 | 0 | false | `ad5392c25ebfaa9668d368c804b44a6d15253645e86550e474e17ecf3c046fb0` | `800cd7f8953493fac7d2c74a2628c033b28702d7343dbaf2bbd12a6270a948d9` |
| 20 | 3800 | 200 | 0 | false | `c3c71e28478869a2f558d6ba4ec0bca429e1f3e10b918c99d522f23de709660c` | `c06a5cbb643d05766a81c9258fb79284d2677f11055c12bff5f4af9247bbf188` |
| 21 | 4000 | 200 | 0 | false | `f752a608ceaa3a5f867fded073876d883b9b4f9e03900d9a35f8d40bb40c2882` | `9a0959970480a3be873396335548962f5ad65af15bcf96db5a2275a6a1c25c65` |
| 22 | 4200 | 200 | 0 | false | `47fc4104ab981fcd6459a66c6e2c09b734eefe7dc45d40912840af51b7be4bce` | `e819bcb2dbeb4aa2b8f6f7e33f28c82b07719c377ec071907402f77d5018a4a2` |
| 23 | 4400 | 200 | 0 | false | `15ec8934b0033a34086740c73a1018b3e4a39ddf55066e4998308586a4a6ba51` | `64fc09213b83e97f164b8c7f325094bf419db436b7bef04940cd80435cfd724d` |
| 24 | 4600 | 200 | 0 | false | `22d9368ac73926df52f134b203f42d67f997b9f0ddfa8728778e3902b651862a` | `40e2bb226eba2531c7be0b7cbe8c5c64f9cca07dbfc4b907454d94e4e76dc3c3` |
| 25 | 4800 | 200 | 0 | false | `859efaf4119bda231c47664216c4cc15f7605ee15315e9968492f69b88abeb45` | `82a75a1ad2c2608df1665dc5f30eb756ce4731722696099395857511b4290dc2` |
| 26 | 5000 | 200 | 0 | false | `c1cf7a9743fe5ccba7846b363ab01015316bf409c933ac5e05077504d2445c9d` | `5a7a72e48293f85dbf9d5862e1f7382c2312a9186611379a6a4f1adf845ecb26` |
| 27 | 5200 | 200 | 0 | false | `3dbfc12b58e3f9391fe87802480c7311099fecd05f6efbf0fefbd73d224e0f21` | `86f2764549a1331a4f3dac7c91aadd59538479e67e3702f62f483c124cd3d2db` |
| 28 | 5400 | 200 | 0 | false | `f0abaa28cceea7de9e045bd151d20a9990105723cdaf1fa63c8e92a56515c0ea` | `3771ffadce0d09cad32b6988486b4ac5efe12560100038a668359e444ed0f5de` |
| 29 | 5600 | 200 | 0 | false | `acab749eb543eb040f02afe880c740b24128a5c9659ca3e62abb9033f3a65d1e` | `fa3170e3c29da295c37130186220459a641f011ad62b2862fd798a7f60f56dc6` |
| 30 | 5800 | 200 | 0 | false | `38393c073cf14b4ec67bf51ad4671a0988077ddf94b19b1d9574526e80ef2a6a` | `16d7921547499d290ab87ee55b2199ea8844beadbb0554b7e5c60754f17607dd` |
| 31 | 6000 | 200 | 0 | false | `d14820f00e6e5f4b4a7d7271273039eeb6b7c36eaa51872cbec994b11d400f11` | `7c3656276908dacc9d1572d57136df76defefbc2dc80ccdfb03265a800e4c56e` |
| 32 | 6200 | 200 | 0 | false | `ceb38e3f89358a2d3d145f87ed6e06ef8ebd905b0315148c318351fb20247a3d` | `c1bf2a6c7c38f6d80aebab9f7b0788ddc1e9bf4334cc753023edc67458e236ef` |
| 33 | 6400 | 200 | 0 | false | `1d8a3514a395bd87324e69584c5f703a251cc8b9c522c66e5a43db4731b6b2eb` | `24680f2bb048f44781aef91bc2bff5663814d326660cac051fbe4d0e875c19f9` |
| 34 | 6600 | 200 | 0 | false | `76b3990724745782fcffc98544bdc4e9d8f16848c7c29c8b385a522403c80ebb` | `ab5e720104d836e64fd261fda6514d5080ff3938c9233dcdae182b21f1e2d223` |
| 35 | 6800 | 200 | 0 | false | `c59d8136a5060da2edfb37f8d3ae4a2c775b773677f5e8d2ad5274aa6572909c` | `1dffb11cfed2057251e48ae0315856861ca3037f79ff4ddab58a90d9cc734a43` |
| 36 | 7000 | 200 | 0 | false | `dd8bd73245a8542507756796bc93517010f0b7e898cb93bb37d5ad8ef0864b69` | `66d7f86a8fee8e3ad116289575c1dfa7a6d5d509efcba2a3670fec79967e6eef` |
| 37 | 7200 | 200 | 0 | false | `27babb932e04bc27db550d5fc66920a7086d69a5de669d81c376275ebd5cd15e` | `d0fe1f18db32a7d615a679c7703cd895390131e99a85d5b30f4fd6ed8815c603` |
| 38 | 7400 | 200 | 0 | false | `b0547fa9bb420c8e72a95147cbbedf15bbec41e6e40b478c4b8d5c91f7b47d01` | `d2084280729bc0fa63754c2b3ddd3de8a19e7799f1350edfb41b4106443ce8d3` |
| 39 | 7600 | 200 | 0 | false | `550b468cedabf04f3aadc329ccdda19e25ba83df4104a0cf5676b60a6b49b84e` | `b39735d89736ce46950acd0ab74c27d54cc7886f4ec031896e83d8771ba47ec8` |
| 40 | 7800 | 200 | 0 | false | `cd601b7c7139ec60e3107915ec8339613ec8157357c28588ecd2581b9fddf494` | `f64269f13c1ccaa093818c698b756b940444c7b2607b89e3330b71f831120d30` |
| 41 | 8000 | 200 | 0 | false | `e6806c0e3c449ee8de5c7da5fa7dbb604e3406f4a820d80ece561adcca449ae9` | `4b2929ee96df01a6aa94d770378400ea0b2e9231a4df1f5019b2385ef4a4f14f` |
| 42 | 8200 | 200 | 0 | false | `0787fddc82c12d9a09cb066ea5c862c409e84ed5006c4bd828a874b9e97f829f` | `d6ee225c3dd58260b4acf50cecafb50351746e9e1aff51f80607334a42d48c11` |
| 43 | 8400 | 200 | 0 | false | `d8ef858db3b122310ce5a758a5f57134bb33bb183a9cc9a5040e80e412b15eb0` | `648e6f5c58bf0136d1bc1054908bfe2952feba0de149b0ce53c92aba6dadbe47` |
| 44 | 8600 | 200 | 0 | false | `20c2017c794a73ad126305675e7a1213aa9adfeb15495b00102b78acac397ed9` | `e55230cf64fd83d4291e7a442d3a109c3196bd4f3dcabfa337309c4010107ecd` |
| 45 | 8800 | 200 | 0 | false | `226d97d5f7cd030ad06a6030db14b959520c2c5880b20072461eb04aa43a938c` | `f8ab9e4dce4f73863df936acf535951f081e0349e445e8968c32f556e550c271` |
| 46 | 9000 | 200 | 0 | false | `ab24c13efd221b9d22849191ebfd17c4ac2865bea4b6a1b95e2f105f2cb34b69` | `c58d40e095214857969e8063cbb36edd675030ae1874c75f724757a691df9fc9` |
| 47 | 9200 | 200 | 0 | false | `34c4d812c123872e685fa75bf32e77cc84cc6abe92882c298d277beb4c701d30` | `0506f486537ffbd73907fc7dd987374eca1ffc8a857a8af886fad61c201a525b` |
| 48 | 9400 | 200 | 0 | false | `1a3efb2f8477ad7887e4fb4129dfb095ffd1d6f2052e052cfdee58f5c4f10a44` | `64de0c293bc080c5ea41ec393bc1f32feb7f9be9e0997a758e13bd81650db06e` |
| 49 | 9600 | 200 | 0 | false | `bf60b9f058cfc0dc11a866006a7873fa61f66afcd25fe51f1fd2c16cbb090350` | `6949f4d76e2f19cdecc764708ae0c64d478baa0826b170969aeb5e23f880d8da` |
| 50 | 9800 | 200 | 0 | false | `3546ec0c8aa16b8cce22e807753f859acfbb7fb5519284e356d018dac145cacf` | `9ff359e8b523414538334712ecf9413ed3d92ebc6894ddd537f7c98cb0e2e948` |
| 51 | 10000 | 200 | 0 | false | `cc1400fdcabdf05d2835dc78943c7a08618353daae831483254d961b9515dc9b` | `cdc237342b1a7c303e619805977417fc5153397212ed517f9954ca229193f9e1` |
| 52 | 10200 | 200 | 0 | false | `38d8e5f8a8001ad282977ff70ed7fbe613e7f70e4109252f5ab427ff3b9315cb` | `09dd468e4146fb12b55f377573aba2ed0dd1565b2364f84c35f023d4f1e29af5` |
| 53 | 10400 | 200 | 0 | false | `62b7509721a56fdd1531f9a3030105e5ff42f510fcaeb5686c9555c1f63ef118` | `30aacb4e32a9c174dfa16bab85ef191172f43e674af50e6809344008baf29dfa` |
| 54 | 10600 | 200 | 0 | false | `2c2afc4fdfc02ea70a4b4350e72c2c5d6ec98ab89f17d5b842e9412d39cf20d7` | `d608df952ffcdabc6196655f76eba6f91f5efa2853cddaed747a5873e7993f85` |
| 55 | 10800 | 200 | 0 | false | `3ec606e73d5769ddb3ac2598da615108492dc039b3165042d4ac09266e469197` | `9621185cfbd127c48dc080363d080c0d88873442a2e133a5a7a8d8d345f00c99` |
| 56 | 11000 | 200 | 0 | false | `627365cff9bc5ba7d9db91620224fea0dab163d706092cb36ef128a6d069c5d3` | `878fbf0377d3ccb58f9131e0fec0edab298272f969599734cc9259319cc2fef6` |
| 57 | 11200 | 200 | 0 | false | `df3b681708cbe5ec37aa4e42c2e34190e38523b22522f8f5a9fa04a1d6bb35a7` | `c53ef9111d5eaaf03b201f5c11e460af121749e3a69e5f94c6c62290ba8761c0` |
| 58 | 11400 | 200 | 0 | false | `00ad3bc13bb2bb86f595d94259cee53e41f99bd4dd302b2fbe72bcce1809d8c6` | `04582d20e47acb50f5013c9208facc44aff225ce32414a38cdb69f9cc5523b75` |
| 59 | 11600 | 200 | 0 | false | `27c446f41546f44229554ae8db977bff708e4695c34a7ce63bd937fe916d45f2` | `8b8467a1d6bb110af18399ed8ae7e37c3647b1c6654d2f7a80f56b700e221768` |
| 60 | 11800 | 200 | 0 | false | `6192a43ef094fb2b91114ae511aca3ddf45c7a5e83f12e40d28cc94157725b38` | `0581a73371645388bae291c48ddc770132d6b2325481270cba130f6f8819516a` |
| 61 | 12000 | 101 | 1 | true | `d73af00271dd4556182fc9c56645ae9b1fccb354e8e9335794f7b43b17ab8a4b` | `fcb697ed6a13d6472706956eb24f4c85cbe8d8cb56020f1a6d40ab1c78996aae` |

#### 4.9.4 ACTIVE factor samples and independent comparisons

The following values came from the smallest post-capture page recoveries during the same observed `AFTERNOON` lifecycle. They are not relabeled as the exact original page payload. The page request hashes are the same deterministic production request hashes; recovery response hashes were `AAPL=ec6831a0e36d521acc7c67c87a0bc40530c3e086a28fe0ef50c5fbe3ed594803`, `NVDA=33bc03f6dce1ee16b43a1338f288bfe8733b0ee31570363f26a7b879be6879dd`, `MSFT=54e14faccf20405fbc275592e13276c26ed311a86ee2d3ff9dfc95eeef9ef4`, and latest `KLAR=98d311d0046bf7571f69c931c8ff6b0b3e7dceed5796a7f435a75a7fe0f4a3cc`.

| Symbol | PRICE 2201 USD | MARKET_CAP 2301 USD | LISTED_DAYS 2307 | AVG_TURNOVER 3105 days=20 USD |
|---|---:|---:|---:|---:|
| `AAPL` | `324.94` | `4,742,232,849,200.0` | `16700` | `246,808,476,224.889` |
| `NVDA` | `217.71` | `5,246,811,000,000.0` | `10085` | `545,966,786,067.674` |
| `MSFT` | `501.415` | `3,723,279,892,369.765` | `14782` | `243,267,076,814.795` |
| `KLAR` | `14.23` | `10,064,760,670.985` | `357` | `2,465,144,631.895` |

Active PRICE and MARKET_CAP values are observations only. PRICE awaits the matching terminal capture and completed-session close authority. MARKET_CAP has no acquired independent effective-date authority and remains OPEN.

| Symbol | Futu 3105 | Independent 20-session mean close x volume | Absolute difference | Difference vs independent | Futu / independent |
|---|---:|---:|---:|---:|---:|
| `AAPL` | `246,808,476,224.889` | `12,847,481,901.315` | `233,960,994,323.574` | `1821.064985%` | `19.210650` |
| `NVDA` | `545,966,786,067.674` | `27,948,740,175.535` | `518,018,045,892.139` | `1853.457589%` | `19.534576` |
| `MSFT` | `243,267,076,814.795` | `13,127,625,915.24` | `230,139,450,899.555` | `1753.092695%` | `18.530927` |

All values are USD. Dividing Futu by 20 moves the results within approximately `-2.33%` to `-7.35%` of the independent proxy, but the active request may include the incomplete `2026-09-01` session while the independent input ends on `2026-08-31`, and close-times-volume is not direct executed dollar turnover. The evidence establishes a scaling/window semantics difference; proximity after an uncontracted division is not qualification.

`KLAR LISTED_DAYS=357` does not equal the independently computed 245 inclusive XNYS sessions from `2025-09-10` through `2026-08-31` (or 246 through the current `2026-09-01` session). The returned value matches calendar-day scale, not CORE v1 trading-session semantics. The required immutable CORE v1 source cannot satisfy its listing-history contract on this exact provider request/version pair. `FUTU_STOCK_SCREEN_TEMPORAL_AUTHORITY_QUALIFICATION` is therefore `FAILED_FOR_EXACT_VERSION`; no CORE rule was changed and no alternate value was substituted.

#### 4.9.5 Active suspension/halt evidence

The official Nasdaq Trader halt feed retrieved at `2026-09-01T18:26:35.883255Z` had publication time `Tue, 01 Sep 2026 18:26:24 GMT`, 53 items, and SHA-256 `80088233ae4605329fc85b6310d87862f1249d7e8d6bde144e58170e24a1fbf3`. `NCSM` and `CRNX` remained listed with no resumption date or time and reason `T12`.

One-context Futu observation from `2026-09-01T18:26:48.652319Z` through `2026-09-01T18:26:48.874343Z` returned `AFTERNOON` at both bookends for both securities. `US.NCSM` returned `suspension=true`, `sec_status=SUSPENDED`, and `update_time=2026-08-31 19:54:59.306`; `US.CRNX` returned `suspension=true`, `sec_status=SUSPENDED`, and `update_time=2026-08-31 20:02:30.278`. The artifact SHA-256 was `156d9500c85bf95be0106b6f16a61afe2a736ae5bd448c936d5329338d2bd8f6` and the projection SHA-256 was `ccacae66cac0bb75826199cc5726d1a5619ca89463a73bc8bf1bb1d4e93b1d38`.

This proves current official halt truth agrees with Futu suspension/status while the price timestamp legitimately remains on the prior date during ACTIVE. The Design contract still requires terminal bookends, so the suspension qualification remains OPEN pending the matching terminal observation.

#### 4.9.6 Durable state and current verdicts

`ACTIVE_CAPTURE_COMPLETE_FOR_XNYS_2026-09-01`

No later scheduler or manual continuation may repeat the ACTIVE full pagination for this session. Only minimal lifecycle checks are permitted until a genuine terminal relationship is observed; at that point the matching terminal request may run once.

| Qualification | Verdict | Current reason |
|---|---|---|
| `FUTU_FORMAL_COLLECTION_WINDOW_REACHABILITY_QUALIFICATION` | OPEN | ACTIVE was observed, but no same-session terminal relationship or required reachability-regime set is complete; strict clock authority also remains OPEN |
| `FUTU_STOCK_SCREEN_TEMPORAL_AUTHORITY_QUALIFICATION` | FAILED_FOR_EXACT_VERSION | `LISTED_DAYS=357` contradicts required XNYS-session count `245/246`; ADV20 also shows unqualified scaling/window semantics, and PRICE/MARKET_CAP terminal authority is incomplete |
| `FUTU_SUSPENDED_SECURITY_FRESHNESS_QUALIFICATION` | OPEN | Current halt/status and stale price timestamp are corroborated during ACTIVE, but terminal lifecycle evidence is still absent |

`formal_ready=false`. No production code, SQLite, snapshot, profile, funnel, subscription, quote-right, trading, commit, push, PR, or merge operation occurred.

## 5. Suspension/halt freshness observation

### 5.1 Independent official source

Source: `https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts`

Retrieved: `2026-09-01T01:43:39.612286Z`

Feed publication time: `Tue, 01 Sep 2026 01:43:16 GMT`

Declared items: 58

Full RSS response SHA-256: `6edcad495c48ae1d8a21875424b80367ad004d33f684780199e558d6579cedfc`

The smallest selected official samples with no resumption fields were:

| Symbol | Halt date | Halt time ET | Reason | Resumption |
|---|---|---|---|---|
| `CRNX` | 2026-08-31 | 19:50:00 | `T12` | none reported |
| `HCHL` | 2026-06-11 | 19:50:00 | `T12` | none reported |

### 5.2 Futu observations

Each sample used one context and the order `market_state start -> market_snapshot -> market_state end`.

| Symbol | Start/end state | `suspension` | `sec_status` | `update_time` ET | Snapshot sanitized projection hash |
|---|---|---:|---|---|---|
| `US.CRNX` | `OVERNIGHT` / `OVERNIGHT` | true | `SUSPENDED` | `2026-08-31 20:02:30.278` | `2c118d018f22f59d957ae2c1850713621b36262ed64f889cd5407a294c6f9bda` |
| `US.HCHL` | `OVERNIGHT` / `OVERNIGHT` | true | `SUSPENDED` | `2026-08-31 19:54:59.300` | `735af73f4e241a48545669f213961d54eb4e5040e303d7661d3cab4d810e5e07` |

Market-state sanitized projection hashes:

- `US.CRNX`: `e9d5be8b0da84f2a751719e3f7cdb920395e79561d8a1b8c3c7764826f68f170`;
- `US.HCHL`: `2733a5ee56e19bf06a9c9fb2b154abb2e3761bb8699d76fdefc5ac888d406a10`.

The official halt truth and Futu `suspension/sec_status` values agreed for both samples. However, neither observation was terminal-closed, and both provider `update_time` values were on 2026-08-31. In particular, the long-halted `HCHL` sample did not exhibit an old price timestamp. Therefore the spike did not prove the narrow stale-current-price exception and `FUTU_SUSPENDED_SECURITY_FRESHNESS_QUALIFICATION` remains open.

## 6. Call and quota safety record

- No subscription was created or modified.
- No quote right was requested or escalated.
- No broker/trading endpoint was called.
- No database, snapshot store, profile, funnel, or hash persistence service was called.
- The remediated direct Stock Screen call returned one diagnostic page; the production adapter then failed closed on the integer `last_page` shape before completing pagination.
- OpenD did not expose a formal quota-status result through the approved call path, so no unsupported quota claim is made.

Validation after the approved dependency, pagination-shape, and screen-rate boundary changes:

- pagination RED: `1 failed, 7 passed` for the expected pre-fix reason;
- pagination GREEN: `8 passed`;
- rate-boundary RED: `1 failed` for the expected exact-30-second reason;
- rate-boundary GREEN: `1 passed`;
- complete adapter file: `37 passed`;
- focused Futu tests: `108 passed`;
- full repository: `1055 passed, 2 failed`;
- the two failures were pre-existing baseline-integrity assertions unrelated to Protobuf: a Phase 1 AST snapshot mismatch and tracked project skill `auto-model-routing` being absent from the test's expected set; and
- no failing test imported or exercised the changed Protobuf/Futu boundary.

## 7. Qualification verdicts

| Qualification | Verdict | Blocking evidence |
|---|---|---|
| `FUTU_FORMAL_COLLECTION_WINDOW_REACHABILITY_QUALIFICATION` | OPEN | Observed window was `OVERNIGHT`; the strict clock prerequisite was not established; other required window classes were not observed |
| `FUTU_STOCK_SCREEN_TEMPORAL_AUTHORITY_QUALIFICATION` | OPEN | Protobuf, integer `last_page=0/1`, and screen-rate boundary compatibility were repaired; complete 47-page pagination succeeded, but the payload has no temporal/effective-date authority and the required cross-window and independent factor comparisons remain unavailable |
| `FUTU_SUSPENDED_SECURITY_FRESHNESS_QUALIFICATION` | OPEN | Independent samples agreed on suspension, but were not terminal-closed and did not exhibit a stale current-price timestamp |

No version-bound contract hash is published because no contract was accepted. `formal_ready` remains false.

## 8. Locked-session terminal capture blocker

### 8.1 OpenD recovery observation

At `2026-09-04T11:33:07Z` through `2026-09-04T11:33:23Z`, three connection attempts to the approved local OpenD endpoint `127.0.0.1:11111` failed with `WSAECONNREFUSED`. No provider request completed during those attempts.

After OpenD was restarted, the minimum permitted lifecycle check completed at `2026-09-04T11:37:14Z`. Global US state was `PRE_MARKET_BEGIN` at both bookends, and `US.AAPL`, `US.SPY`, `US.NVDA`, and `US.MSFT` each returned `PRE_MARKET_BEGIN`. `qot_logined=true`, `program_status_type=READY`, and `server_ver=1010`.

The lifecycle artifact SHA-256 was `f81a31a0ba2eb17aa09807eac0b0600bb11ca6423001320cd04943b54bdccddf`. Global start/end response hashes were `9b8a0321c8805124e8f65e31327f6e70f06c1a4c1fc706aa6a208fa82468cf9a` and `ffadf703845575b1664f1a41e6bd16ced2d5b527d2af95af0606236a65d68cdd`; the per-code market-state response hash was `384dd3ce9ef04927672319571484e0309666e2249fc61697aa3ecd000888170e`.

### 8.2 Same-session relationship is no longer recoverable

The locked qualification session is `2026-09-01`. XNYS sessions `2026-09-02`, `2026-09-03`, and `2026-09-04` occurred before the recovered provider observation. The calendar relationship artifact SHA-256 was `66676bdfc49262b190f57fee870d163cde83df2f8147681651f58047df8e4df3`.

The recovered `2026-09-04 PRE_MARKET_BEGIN` observation cannot establish a `2026-09-01` TERMINAL relationship. A new Stock Screen or market-snapshot capture would contain later provider state and cannot be relabeled as the missing same-session terminal evidence. Historical daily bars can corroborate a completed close, but cannot reconstruct the required live provider lifecycle bookends, snapshot timestamps, suspension/status observation, or Section 6.5 clock relationship.

`TERMINAL_CAPTURE_UNAVAILABLE_FOR_XNYS_2026-09-01`

No ACTIVE pagination or terminal factor request was executed during this recovery check. The existing ACTIVE durable boundary remains unchanged.

### 8.3 Superseding current verdicts

| Qualification | Verdict | Current reason |
|---|---|---|
| `FUTU_FORMAL_COLLECTION_WINDOW_REACHABILITY_QUALIFICATION` | OPEN | ACTIVE was observed, but the required matching terminal relationship for the locked session was not captured and is no longer recoverable |
| `FUTU_STOCK_SCREEN_TEMPORAL_AUTHORITY_QUALIFICATION` | FAILED_FOR_EXACT_VERSION | `LISTED_DAYS=357` contradicts required XNYS-session count `245/246`; `AVG_TURNOVER` also has rejected rolling-sum/window semantics |
| `FUTU_SUSPENDED_SECURITY_FRESHNESS_QUALIFICATION` | OPEN | ACTIVE halt/status evidence exists, but the matching terminal suspension/status/timestamp observation was not captured and is no longer recoverable |

`formal_ready=false`. The terminal-wait automation may now stop because its locked temporal window has irreversibly expired. No production code, SQLite, snapshot, subscription, quote-right, trading, commit, push, PR, or merge operation occurred.

## 9. Authority rebind and fresh-session qualification

### 9.1 Scope and locked session

This follow-up does not attempt to recover, relabel, or reconstruct the unavailable `2026-09-01` terminal evidence. It opens a separate `1010` diagnostic qualification attempt for XNYS session `2026-09-04` and preserves all historical `CORE:v1` thresholds and Funnel semantics. It does not accept a `1010` contract, and it does not reuse legacy `1009` mappings or hashes.

Any future acceptance must independently bind: A business semantic; B metric identity; C evidence/source identity; D provider/version identity; E derivation version; F qualification-contract version; and G Profile Version. These observations identify possible future interfaces only; they are not the missing accepted A–G contract tuple.

`QUALIFICATION_SESSION_LOCKED_XNYS_2026-09-04`

The first recorded in-scope lifecycle observation ran from `2026-09-04T11:50:42.865898Z` through `2026-09-04T11:50:43.021567Z`. OpenD reported `qot_logined=true`, `program_status_type=READY`, and `server_ver=1010`. Global US state and the per-code states for `US.AAPL`, `US.NVDA`, and `US.MSFT` were all `PRE_MARKET_BEGIN` at the observed bookends. This is premarket evidence only; it is neither ACTIVE nor TERMINAL.

`PREMARKET_CAPTURE_COMPLETE_FOR_XNYS_2026-09-04`

The start/end `get_global_state()` response hashes were `4aa5b7126705e8c7dc20f78c0a372b7f5143a2a8147914a10d3974699596937f` and `9633b21675858c39b0e51c0cb8e30fba6f64028bee6bab3b5013ec39a0dc634e`. The per-code `get_market_state()` response hash was `b7c91b91953fd2bff18b33340b67177615429166111ed81af2000fe7aad1b6ab`. The compact capture artifact SHA-256 was `908c9f33ba7d6d0a7b724a2319ca6feeb81c1d637e06bd5dfab3a0de9f429bce`.

### 9.2 PRICE candidate authority

The proposed source-neutral metric is `PRICE_USD`, with `get_market_snapshot().last_price` as the candidate source field and `update_time` as current-price timing. Futu v10.10 documents those fields; for US securities the timestamp is US Eastern time: <https://openapi.futunn.com/futu-api-doc/en/quote/get-market-snapshot.html>. One request supports at most 400 codes. The current adapter preserves deterministic input chunks, canonicalized SDK-level request/response hashes and rows, and `acquired_at_utc`; this **does not** include full acquisition brackets or lossless wire bytes. The request envelopes below are qualification-harness-only. A future gateway must add the bracket/canonical-retention contract before this candidate can scale as FORMAL evidence.

The `2026-09-04` four-code request was exactly `US.AAPL`, `US.NVDA`, `US.MSFT`, and the listing cross-check `US.KLAR`. Its request hash was `feb130c7ebc7b23cd151598903a899315354d5b6bed93409325a3f7439e4f551` and response hash was `d74608555c3424dbc6c967b2d88facf0d299daaa5d61aee79325ca85e348d38b`. All four requested codes returned exactly once. The three stable equities returned:

| Code | `last_price` | `update_time` ET | `suspension` | `sec_status` |
|---|---:|---|---|---|
| `US.AAPL` | `328.21` | `2026-09-04 07:50:37.434` | false | `NORMAL` |
| `US.NVDA` | `228.45` | `2026-09-04 07:50:40.715` | false | `NORMAL` |
| `US.MSFT` | `510.12` | `2026-09-04 07:50:38.808` | false | `NORMAL` |

The targeted Stock Screen corroboration returned exactly the same `PRICE=2201` values for all three securities. This equality is a representative value/schema check, not a transfer of Stock Screen temporal authority. A FORMAL binding must require exactly one snapshot row per candidate, parseable positive `last_price`, parseable `update_time`, exact session/window validation, and the batch/request hashes. Missing, duplicate, non-positive, unparseable, future, or wrong-session evidence fails closed. A suspended row retains its real last price but may have an old current-price timestamp; it may use only the separately qualified narrow suspension exception and never refresh or invent a price.

Authority verdict: `UNACCEPTED_PROPOSED_INTERFACE_FOR_1010`.

### 9.3 MARKET_CAP candidate authority

The proposed source-neutral metric is `EQUITY_MARKET_CAP_USD`, with candidate fields `get_market_snapshot().equity_valid`, `issued_shares`, `last_price`, and `total_market_val`. Futu v10.10 says the equity-related fields are legal only when `equity_valid=true`; the underlying proto defines total market value as total issued shares multiplied by current price. Although the generic table labels the unit as `yuan`, the US live values establish the actual unit for this cohort as USD: each result equals `issued_shares * USD last_price` exactly. This is an unaccepted `1010` empirical indication, not a FORMAL authority.

| Code | `equity_valid` | `issued_shares` | `last_price` USD | `total_market_val` | Difference from shares x price |
|---|---|---:|---:|---:|---:|
| `US.AAPL` | true | `14,594,180,000` | `328.21` | `4,789,955,817,800.00` | `0.00` |
| `US.NVDA` | true | `24,100,000,000` | `228.45` | `5,505,645,000,000.00` | `0.00` |
| `US.MSFT` | true | `7,425,545,491` | `510.12` | `3,787,919,265,868.92` | `0.00` |

The targeted Stock Screen `MARKET_CAP=2301` result matched `total_market_val` exactly for every row. Snapshot `update_time` binds the current-price component and the same response binds `issued_shares`; no separate Stock Screen effective date is needed. The same exact-coverage, batching, acquisition, and hash requirements as PRICE apply. `equity_valid!=true`, missing/duplicate rows, missing/non-positive fields, arithmetic inconsistency, or failed session binding is fail-closed.

Authority verdict: `UNACCEPTED_PROPOSED_INTERFACE_FOR_1010`.

### 9.4 LISTED trading-session candidate authority

`Stock Screen LISTED_DAYS=2307` remains `REJECTED`: its prior `KLAR=357` value followed calendar-day scale and contradicted XNYS-session arithmetic. The proposed source-neutral metric is `LISTED_TRADING_SESSIONS`, using `get_market_snapshot().listing_date` plus the exact named/versioned XNYS calendar. It preserves threshold `Listed >= 250 trading days`; its accepted evidence identity and deterministic calculation require a new Evidence Version and Profile Version.

The live snapshot again returned `US.KLAR listing_date=2025-09-10`. With `exchange_calendars 4.13.2` / `XNYS`, that date and `2026-09-04` are both sessions. The binding rule is both-inclusive: include the listing session when the listing date is an XNYS session, and include `as_of_date` only after that session has completed. Weekends and exchange holidays are excluded by the calendar. The result is `249` sessions through completed session `2026-09-04`; excluding the listing session would be `248`. The calendar artifact SHA-256 is `ba1a0fc72350bcc3bf2120515e861fa5b0eeb3316caf17e71fe1002c78aad150`.

A production binding must require exactly one parseable listing date per candidate, a named/versioned XNYS calendar artifact, proof that the chosen `as_of_date` is completed, the explicit inclusion rule, the selected-session sequence/hash, and the snapshot batch hash. Missing/invalid/future listing dates or calendar failures produce unknown/incomplete evidence; they are not converted to zero days.

Authority verdict: `UNACCEPTED_PROPOSED_INTERFACE_FOR_1010`.

### 9.5 ADV20 three-mode probe

SDK `10.10.7008` implements `add_retrieve_cumulative(name, days=1, period_average=None)` as follows: `None` omits protobuf `periodAverage`; `True` serializes integer `1`; `False` serializes integer `0`. The official Stock Screen V2 schema declares `periodAverage` as optional `int32`, but does not define either value as the arithmetic-average operator required by CORE v1: <https://openapi.futunn.com/futu-api-doc/en/quote/get-stock-screen.html>.

The first attempted INDEX_ID restriction returned a successful empty response (`all_count=0`) for every mode and was not used as evidence for the target values. The accepted minimum probe instead used one page per target with `MARKET=[US]` plus narrow PRICE and MARKET_CAP intervals derived from the immediately preceding snapshot. Each request returned exactly one row, its intended AAPL/NVDA/MSFT target. No full-universe pagination was run.

| Target | `period_average=None` | `period_average=True` | `period_average=False` |
|---|---:|---:|---:|
| `AAPL` | `246,475,012,577.0` | `246,475,012,577.0` | `246,475,012,577.0` |
| `NVDA` | `561,630,785,008.0` | `561,630,785,008.0` | `561,630,785,008.0` |
| `MSFT` | `233,756,190,869.0` | `233,756,190,869.0` | `233,756,190,869.0` |

Raw target result descriptors preserved the requested difference (`periodAverage` absent, `1`, or `0`), but the returned values were identical. The accepted probe artifact SHA-256 was `137f5fed2de36b4157b30728bde62b70b8b287b899c9f39164553b36c2a0f66d`. Response-chain hashes were `f658f77cd841d5e8e9cda11756e31a7f4b4e2f704f447f8869279cc1eb3e7939` for None, `d48ca75473d971691022b6c087ebf01f892ef827e0635a30878abd4df1f8b7fd` for True, and `6f59019f04852c4fc68578c5a8be82b13f2c9497a18cd8042805c211d6849363` for False. No accepted request returned a provider error.

Compared with the existing independent 20-session Nasdaq close-times-volume evidence ending `2026-08-31`, the new Futu values are `19.1847x`, `20.0950x`, and `17.8064x` the respective arithmetic means. Dividing the Futu values by 20 produces differences of `-4.0765%`, `+0.4752%`, and `-10.9678%`; the comparison dates differ and close-times-volume is not direct consolidated turnover, so the division remains diagnostic only. The unchanged results across all three wire representations prove that `period_average=True` does not select the required arithmetic mean on this exact SDK/OpenD pair.

- ADV20 None authority: `REJECTED`.
- ADV20 `period_average=True` authority: `REJECTED`.
- ADV20 `period_average=False` authority: `REJECTED`.
- ADV20 final authority: `OPEN` — provider-neutral interface frozen; an alternate scalable authority is required and no provider implementation is selected here.

Historical Kline per-security reads were not promoted into a 12,000-security production design; no quota/scalability proof was attempted.

### 9.6 Clock-contract result

The new premarket bookends reproduce the prior clock shape without repeating an open-ended probe. Futu documents `get_global_state().timestamp` as current GMT epoch time in seconds and `local_timestamp` as the OpenD-machine epoch time in seconds: <https://openapi.futunn.com/futu-api-doc/en/quote/get-global-state.html>.

At the start bookend the application request envelope was `[2026-09-04T11:50:42.865898Z, 2026-09-04T11:50:42.866506Z]`, while server `timestamp=1788522641` represented `[11:50:41Z, 11:50:42Z)` and did not overlap. OpenD `local_timestamp=1788522642.865959` did overlap. At the end bookend the request envelope was `[11:50:43.020925Z, 11:50:43.021567Z]`; the unchanged server second again did not overlap, and `local_timestamp=1788522643.020906` preceded the send sample by approximately 19 microseconds. Application wall/monotonic ordering remained internally consistent.

Repeated observations show a precise, near-application OpenD local clock together with a whole-second provider/server value that can lag the request envelope by more than the represented second. This does not prove that all provider clocks are untrustworthy. It proves that the Design's zero-tolerance requirement that both timestamp representations overlap every sub-millisecond request envelope is incompatible with the observed provider timestamp precision/caching behavior.

Clock contract result: `DESIGN_CONTRACT_REVIEW_REQUIRED`. No tolerance, skew allowance, midpoint, or replacement clock rule is introduced here.

### 9.7 Current authority matrix and session evidence

| CORE v1 prerequisite | Candidate authority | Authority verdict |
|---|---|---|
| PRICE `>= USD 5` | proposed `PRICE_USD`: `get_market_snapshot().last_price` + per-row `update_time` + lifecycle/session contract | `UNACCEPTED_PROPOSED_INTERFACE_FOR_1010` |
| MARKET_CAP `>= USD 1B` | proposed `EQUITY_MARKET_CAP_USD`: equity-valid `total_market_val`, same-row shares/current-price identity and `update_time` binding | `UNACCEPTED_PROPOSED_INTERFACE_FOR_1010` |
| LISTED `>= 250 trading days` | proposed `LISTED_TRADING_SESSIONS`: `listing_date` + versioned XNYS both-inclusive completed-session count | `UNACCEPTED_PROPOSED_INTERFACE_FOR_1010` |
| ADV20 `>= USD 20M` | provider-neutral interface only; no scalable exact arithmetic-mean authority accepted | `OPEN` |

| Qualification/session evidence | Current result |
|---|---|
| XNYS `2026-09-04` locked | yes; dedicated durable marker exists |
| Premarket evidence | captured; `PRE_MARKET_BEGIN` at global and all three per-code observations |
| Active evidence | `OPEN` |
| Terminal evidence | `OPEN` |
| Suspension evidence | `OPEN` |
| Clock contract | `DESIGN_CONTRACT_REVIEW_REQUIRED` |

Because ADV20 remains `OPEN`, all four CORE v1 prerequisites lack accepted scalable authority. At the time of this capture the Design Spec was not amended and no independent spec review was dispatched. This later reconciliation still does not accept any `1010` factor contract. `FUTU_FORMAL_COLLECTION_WINDOW_REACHABILITY_QUALIFICATION`, `FUTU_SUSPENDED_SECURITY_FRESHNESS_QUALIFICATION`, and overall `formal_ready` remain `OPEN`, `OPEN`, and `false`. `FUTU_STOCK_SCREEN_TEMPORAL_AUTHORITY_QUALIFICATION` remains `FAILED_FOR_EXACT_VERSION`; the rejected screen properties are not relabeled as qualified authorities.

## 10. XNYS 2026-09-04 ACTIVE qualification capture

### 10.1 Lifecycle trigger and capture discipline

At `2026-09-04T18:08:49Z`, the minimal lifecycle check first observed `market_us=AFTERNOON` at both global bookends and `market_state=AFTERNOON` for `US.AAPL`, `US.NVDA`, and `US.MSFT` at both per-code bookends. The minimal trigger artifact SHA-256 was `e44966e78571123ab5334a679fd575f6bc96d4f0668a92d15278a65bb8b88cd5`. `exchange_calendars 4.13.2` identified the locked `XNYS` session as open from `2026-09-04T13:30:00Z` through `2026-09-04T20:00:00Z`, so this was the first Design-defined ACTIVE observation for the locked session.

The one-time exact capture began at `2026-09-04T18:10:08Z` and used only this sequence: global-state start, market-state start, exactly one `get_market_snapshot` request, market-state end, global-state end. The request covered `US.AAPL`, `US.NVDA`, `US.MSFT`, and the smallest current independently corroborated halted sample available, `US.LPSN`. Its canonical artifact SHA-256 was `98aa82afc9294cc0cfe9c2ae84eed2ebb9aa0935dc6e33419dff23a4400d56e1`.

Both global bookends returned `market_us=AFTERNOON`; all four securities returned `market_state=AFTERNOON` at both state bookends. The state-start response hash was `34ff15d4bbe3514d2135d8a666c8198c3c64c3361555bbdecad817d854b34391`, and the identical state-end payload had the same hash.

### 10.2 Independent halt corroboration

The official Nasdaq Trader halt feed at <https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts> was retrieved at `2026-09-04T18:09:32.4674893Z`. Its HTTP `Date` was `Fri, 04 Sep 2026 18:09:30 GMT`; `Last-Modified` and channel publication time were both `Fri, 04 Sep 2026 18:08:35 GMT`. The parsed feed contained 46 items, including 15 without a resumption trade time. The canonical accepted feed artifact SHA-256 was `6f9644535bb712ee02c4caf47100cc2dc773db6d9daa2668de61260ccc78dc3e`.

`LPSN` was the most recent suitable unresolved sample in that feed: halt date `09/03/2026`, halt time `19:50:00.000`, reason code `T12`. It was used only as independent corroboration for the narrow suspension/status observation; it does not transfer Nasdaq feed authority to any CORE v1 prerequisite.

### 10.3 Market Snapshot evidence

**Qualification-harness-only bracket observation — not a current production adapter field.** The single four-code snapshot request envelope was `[2026-09-04T18:10:08.321773Z, 2026-09-04T18:10:08.364569Z]`, with monotonic samples `227065098165100` through `227065140966100`. Its canonical response hash was `22344cae165c59f60beeeab49baa96d3f8c4d54118756396ea30a7d4b708ecf1`.

| Code | `update_time` | `last_price` | `volume` | `turnover` | `suspension` | `sec_status` | `equity_valid` | `issued_shares` | `total_market_val` |
|---|---|---:|---:|---:|---|---|---|---:|---:|
| `US.AAPL` | `2026-09-04 14:10:05` | `321.1501` | `23,458,382` | `7,546,995,900.914` | false | `NORMAL` | true | `14,594,180,000` | `4,686,922,366,418.00` |
| `US.NVDA` | `2026-09-04 14:10:05` | `230.3` | `94,561,260` | `21,972,811,813.173` | false | `NORMAL` | true | `24,100,000,000` | `5,550,230,000,000.00` |
| `US.MSFT` | `2026-09-04 14:10:00` | `500.08` | `8,312,179` | `4,181,061,390.95` | false | `NORMAL` | true | `7,425,545,491` | `3,713,366,789,139.28` |
| `US.LPSN` | `2026-09-03 19:54:59.301` | `3.1` | `0` | `0` | true | `SUSPENDED` | true | `12,337,297` | `38,245,620.70` |

For every row, `total_market_val = issued_shares * last_price` exactly. The three normal securities carried same-session update times. The independently corroborated halt sample carried the prior-session update time together with `suspension=true`, `sec_status=SUSPENDED`, zero volume, and zero turnover. This is direct narrow evidence that the snapshot path exposes a distinguishable suspended-security state without refreshing or inventing a current-session price.

### 10.4 Global-state and clock artifact

**Qualification-harness-only bracket observation — not a current production adapter field.** The start global-state request envelope was `[2026-09-04T18:10:08.282689Z, 2026-09-04T18:10:08.283265Z]`, monotonic `227065059080000` through `227065059660500`. It returned provider `timestamp=1788545406`, OpenD `local_timestamp=1788545408.282663`, `qot_logged=true`, program status `READY`, and server version `1010`; response hash `b2d0d93a10a60cedecb07ca21092c231674c422565f2ff47b55c83f718e4d6ff`.

The end request envelope was `[2026-09-04T18:10:08.394128Z, 2026-09-04T18:10:08.394792Z]`, monotonic `227065170521400` through `227065171187300`. It returned provider `timestamp=1788545407`, OpenD `local_timestamp=1788545408.394204`, and the same login/program/version state; response hash `229be1af856753a9f90aefaae6d8d396103889f30f0afafd5ff2a908a53a4456`.

Application wall and monotonic ordering was consistent. The start provider whole-second interval `[18:10:06Z, 18:10:07Z)` and end interval `[18:10:07Z, 18:10:08Z)` did not overlap their request envelopes. The start OpenD local timestamp preceded the sampled send wall time by approximately 26 microseconds, while the end OpenD local timestamp was inside its request envelope. This ACTIVE capture therefore reproduces the precision/caching incompatibility already classified as `DESIGN_CONTRACT_REVIEW_REQUIRED`; no arbitrary tolerance or replacement rule is introduced.

### 10.5 ACTIVE result

`ACTIVE_CAPTURE_COMPLETE_FOR_XNYS_2026-09-04`

The locked-session ACTIVE evidence, including lifecycle bookends, exact-coverage Market Snapshot data, suspension/status evidence, clock artifact, provenance, and canonical hashes, is captured exactly once. TERMINAL has not yet been observed or inferred. Subsequent automation runs must perform only minimal lifecycle checks until the first real Design-defined TERMINAL lifecycle in this same XNYS session.

## 11. XNYS 2026-09-04 terminal lifecycle capture

**Qualification-harness-only bracket observations — not current production adapter fields.** After the operator restarted OpenD, the minimal check at `2026-09-05T05:23:48.443529Z` returned global and AAPL/NVDA/MSFT states `AFTER_HOURS_END`. This is the first terminal observation by this attempt, not proof of the exact transition instant during the preceding monitoring gap. XNYS calendar lookup independently returned latest session `2026-09-04`, open `13:30Z`, close `20:00Z`. Section 6.3 permits the weekend civil-date change while the completed-session relationship remains unchanged.

One context then executed global start, four-code state start, exactly one four-code snapshot, state end, global end. Every call returned success (`0`). Both global states and every AAPL/NVDA/MSFT/LPSN state were `AFTER_HOURS_END`; OpenD reported `qot_logined=true`, `READY`, server `1010`. No terminal transition or newer active lifecycle was observed across these bookends.

| Call | UTC request before / response after | Monotonic ns before / after | Response SHA-256 |
|---|---|---|---|
| global start | `2026-09-05T05:24:06.919035Z` / `05:24:06.919760Z` | `2571630690600` / `2571631408200` | `109a50bbe0745cdb2d2a09ecf04d58c370d22123c7007091c9d247f8d3c9772e` |
| state start | `2026-09-05T05:24:06.920626Z` / `05:24:06.952283Z` | `2571632283700` / `2571663930900` | `5fae752abe004cb017a686d59808dc7c7e0e0a25f114a84919234fdf63245147` |
| snapshot | `2026-09-05T05:24:06.952915Z` / `05:24:06.979797Z` | `2571664569500` / `2571691445100` | `0336d2ba07082ecaac979a46c1e21323e0d281fbe04f856dd617d83c14e58c1a` |
| state end | `2026-09-05T05:24:06.982078Z` / `05:24:07.012022Z` | `2571693735100` / `2571723670100` | `5fae752abe004cb017a686d59808dc7c7e0e0a25f114a84919234fdf63245147` |
| global end | `2026-09-05T05:24:07.012403Z` / `05:24:07.013270Z` | `2571724056900` / `2571724918900` | `e5d69eda7a0dc4adf3da40f77a34f43f03abc09f780c33f44eeccf9fe26874fd` |

Artifact SHA-256: `12a8bff7adf12b27143fae391020bd17ace22e321e378431ab59c43e02a52148`. Hash representation: DataFrames converted with pandas `to_json(orient='records')` at its default numeric precision and parsed back into JSON; then UTF-8 `json.dumps(ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)`. All returned columns were included in the tool-output artifact. These are serialized SDK-response hashes, not original wire-byte hashes; default pandas numeric rounding prevents claiming lossless raw numeric fidelity. The table below is only a selected field projection. No contract requiring lossless raw-response persistence is declared satisfied by these hashes alone.

| Code | New York update_time | last_price | total_market_val | suspension / sec_status | volume / turnover |
|---|---|---:|---:|---|---|
| AAPL | `2026-09-04 19:59:58.110` | 319.97 | 4669699774600.0 | false / NORMAL | 39606884 / 12721009726 |
| NVDA | `2026-09-04 20:02:36.447` | 230.36 | 5551676000000.0 | false / NORMAL | 135352420 / 31373383823 |
| MSFT | `2026-09-04 20:01:06.562` | 499.7 | 3710545081852.7 | false / NORMAL | 18101758 / 9072373535 |
| LPSN | `2026-09-03 19:54:59.301` | 3.1 | 38245620.7 | true / SUSPENDED | 0 / 0 |

All four rows returned `equity_valid=true`, with issued shares respectively `14594180000`, `24100000000`, `7425545491`, `12337297`. The normal rows retain the locked-session date; LPSN retains its actual stale price timestamp. LPSN also returned `listing_date=1970-01-01`, which must not be silently accepted as qualified listing-date authority. This representative anomaly does not change CORE rules.

Current independent corroboration used the official Nasdaq Trader RSS halt feed, retrieved `2026-09-05T05:24:23.084911Z`, HTTP Date `Sat, 05 Sep 2026 05:24:21 GMT`, channel pubDate `Sat, 05 Sep 2026 05:23:56 GMT`. SHA-256 of the fetched response bytes: `dd3f3eb4f432032630721b5251ecf8303ab504ba754bf799fbbda55402667864`. The feed explicitly contained LPSN, halt `09/03/2026 19:50:00.000`, reason `T12`, with empty resumption date/quote/trade fields. This corroborates the observed suspended status; suspension was not inferred from an absent security.

Clock: both server timestamps were `1788585846`, representing `[05:24:06Z, 05:24:07Z)`. This overlaps the start request but not the end request. OpenD local timestamps `1788585846.919298` and `1788585847.012779` lie within their respective request envelopes. Wall/monotonic ordering is consistent. The strict contract still fails at the end bookend; `DESIGN_CONTRACT_REVIEW_REQUIRED` remains unchanged.

`TERMINAL_CAPTURE_COMPLETE_FOR_XNYS_2026-09-04`

This marker denotes completed one-time empirical capture, not accepted production qualification. Reachability and suspension qualifications remain `OPEN` pending contract review and complete qualification artifacts; ADV20 remains `OPEN`; Stock Screen qualification remains `FAILED_FOR_EXACT_VERSION`; `formal_ready=false`. No production code, Design, tests, SQLite, Snapshot, CORE, or Funnel changes occurred. The terminal-wait heartbeat can stop after marker and file-boundary verification.
