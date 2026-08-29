# Codex Model Routing — Design

**Date:** 2026-08-29
**Status:** IMPLEMENTATION AUTHORIZED

## Outcome

Add a deterministic local task router that recommends the lowest sufficient Codex
model and reasoning level for a coding task. The objective is token efficiency;
runtime latency is not a decision factor.

The router only recommends. It cannot silently change the model of the current
ChatGPT/Codex session or claim unmeasured token prices and savings.

## Inputs and decision boundary

`recommend_model(task_text, changed_paths=())` requires a task description and
optional repository-relative paths. It scores five explainable signals:

| Signal | Evidence |
|---|---|
| Scope | files, modules, public interfaces |
| State risk | persistence, migration, schema, transaction, destructive action |
| Domain risk | orders, broker, money/PnL, credentials, security |
| Integration | API, OpenD/Futu, network, deployment, external provider |
| Uncertainty | redesign, unknown root cause, performance, architecture |

Hard-risk words and paths impose a minimum tier. This prevents the false
economy of using low reasoning for a short database migration or trading
calculation.

## Profiles

| Score / floor | Recommendation | Intended work |
|---|---|---|
| 0–19 | `gpt-5.6-luna`, low | isolated rename, copy, one known test |
| 20–39 | `gpt-5.6-luna`, medium | bounded one-module implementation |
| 40–59 | `gpt-5.6-terra`, medium | known multi-module work or debugging |
| 60–74 | `gpt-5.6-terra`, high | integration, interfaces, significant tests |
| 75–89 | `gpt-5.6-terra`, xhigh | broad refactor or multi-boundary work |
| 90–100 | `gpt-5.6-sol`, xhigh | persistence/security/trading-critical architecture |

`sol/ultra` is never automatically selected. It remains a deliberate escalation
after evidence shows xhigh is insufficient, protecting against runaway
reasoning-token use.

## Output and verification

The immutable decision exposes `model`, `reasoning_effort`, `complexity_score`,
`reasons`, `hard_floor`, and `escalate_when`. A pure CLI emits stable JSON; a
Streamlit page displays the recommendation and current Git changed-path summary.
Neither can execute code, change Codex settings, contact a provider, or write
project data. Tests cover thresholds, hard floors, path normalization, empty
input, deterministic reasons, JSON validity, and the page's no-side-effect
default.
