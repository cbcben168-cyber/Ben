---
name: auto-model-routing
description: Use when any project task may require repository reading, tool calls, code or configuration edits, debugging, tests, review, planning, or a multi-step answer and model or reasoning selection must happen automatically.
metadata:
  short-description: Automatically route work by complexity and risk
---

# Automatic model routing

Select a route before substantive work on every task. Optimize total token use;
ignore latency. Do not ask the user to choose a model or reasoning effort.

## Automatic policy

1. Inspect only the request and known paths first. If this repository exposes
   `scripts/recommend_coding_model.py`, run it with the task and expected
   paths; otherwise use the table below.
2. Split only genuinely independent work with non-overlapping ownership. Route
   each owned unit separately; never apply one expensive profile to every unit.
3. Execute under the selected profile when the runtime supports it. If the
   current agent cannot change profile, automatically dispatch one bounded
   worker with the selected `model` and `reasoning_effort`; do not require user
   input. If delegation is unavailable, continue with the current agent and
   record the selected profile as a runtime limitation.
4. Re-route automatically when evidence adds a persistence, transaction,
   security, credential, broker/order, or real-money boundary. Do not escalate
   merely because the task is long, a test exists, or speed is unimportant.

| Signal score | Route |
| --- | --- |
| 0–19 | `gpt-5.6-luna` / `low` |
| 20–39 | `gpt-5.6-luna` / `medium` |
| 40–59 | `gpt-5.6-terra` / `medium` |
| 60–74 | `gpt-5.6-terra` / `high` |
| 75–89 | `gpt-5.6-terra` / `xhigh` |
| 90–100 | `gpt-5.6-sol` / `xhigh` |

Score a base task at 5. Add 40 for an external API or integration, 15 for a
bug/regression, 15 for a public programmatic API, CLI, or configuration
contract (not a visual UI label), 25 for architecture/unknown scope, and
`5 × (distinct affected paths − 1)`, capped at 20, for multiple affected
paths. A migration, schema, transaction, or
persistence change has a hard floor of Sol/xhigh. Security, credentials,
broker/order, P&L, or money logic has a hard floor of Terra/xhigh.

## Token guardrails

- Use targeted reads; never scan a repository merely to decide a route.
- Keep the routing notice to one line: `[auto-route] model/effort — reason`.
- Keep simple answers and mechanical checks root-direct; delegation has a
  token cost.
- Escalate only the failing or newly risky slice after two unexplained failed
  investigations, not the entire task.
- Never select the `ultra` reasoning effort automatically, with any model. It
  requires an explicit human request; Sol/xhigh remains an automatic route for
  a persistence-integrity boundary.

For coupled, high-risk, or independently parallel work, use the installed
`multi-model-orchestrator` skill for ownership and integration contracts. Its
plan-only mode is not a reason to stop: this Skill has automatic execution
authority for internal routing only. External, destructive, or protected
actions still follow the user’s authorization and platform policy.
