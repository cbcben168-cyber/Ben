# M3C Resilience Blueprint

## Purpose

Keep the local Pattern Finder deployment safe to restart, make Codex work
recoverable after temporary usage/model limits, and select the lowest capable
model profile without claiming control that the project does not have.

## Model-routing boundary

`src/tv_quant/model_routing.py` remains a deterministic recommendation
component. It returns the lowest sufficient `(model, reasoning_effort)` from
the task text and affected paths, preserving hard floors for persistence,
security, and trading-domain risk.

It does not and cannot mutate the model or reasoning setting of an already
running Codex task. The caller must apply a recommendation when creating a
future worker/task. No token-price or token-saving amount is asserted.

## Deployment boundary

The desktop launcher remains `K线形态研究系统.cmd`, which delegates to
`scripts/start_pattern_finder.cmd`. That owned launcher sets the repository
environment and invokes `python -m tv_quant.pattern_finder.runtime start`.

The runtime owns its PID record, verifies repository ownership before stopping
a process, serializes starts, validates database health, and records the
Streamlit child process. A launcher must not bypass this runtime with a direct
`streamlit run` command.

## Rate-limit recovery

A Codex heartbeat checks this M3C task hourly. It treats usage/model limits as
temporary: it leaves the task active, preserves uncommitted tracked changes and
the user-owned `data/` and `migration_backup/` directories, and retries on a
later heartbeat after capacity is available.

The scheduler cannot detect the exact five-hour reset instant, so hourly is the
safe recovery bound. The heartbeat only continues this project task; it does
not create unrelated tasks, reset history, or merge pull requests.

## Provider-quota authority

Futu OpenD's current `used_quota`, `remain_quota`, and `detail_list` are the
only authorization source for historical-K-line downloads. JSONL history is
audit evidence only. Existing codes remain refreshable at zero new-code slots;
a new code is blocked only when OpenD reports zero remaining slots.

Expansion tests must therefore assert provider exhaustion, not retired local
daily/rolling counters. The Phase 1 AST guard is refreshed whenever an
intentional Phase 1 test-contract change is committed, so it continues to
detect unreviewed mutation.

## Confirmation-token transport

Confirmation tokens are passed to the V2 CLI as the value of
`--confirmation-token`. A token beginning with `-` is ambiguous to argparse,
so issuance retries that rare value and persists only the hash of the safe
replacement. This preserves randomness, token secrecy, expiry, and single-use
semantics while preventing an intermittent command-line parsing failure.

## Verification and handoff

Each change requires focused tests, the full pytest suite, `git diff --check`,
and a remote SHA check after push. The repository's current branch remains
`codex/pattern-finder-m3c-bcd-local-runtime`; no merge is performed by this
blueprint or by the heartbeat.
