# Codex Model Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recommend the lowest sufficient Codex model and reasoning tier from task complexity and repository risk signals.

**Architecture:** A pure module scores task/path evidence and returns an immutable decision. A no-write CLI produces JSON and a Streamlit page displays the recommendation; neither changes the active Codex session.

**Tech Stack:** Python, dataclasses, argparse, Streamlit, pytest, Streamlit AppTest.

**Spec:** `docs/superpowers/specs/2026-08-29-codex-model-routing-design.md`

## Global Constraints

- Recommend only `gpt-5.6-luna`, `gpt-5.6-terra`, or `gpt-5.6-sol`.
- Optimize minimum sufficient capability; do not score latency or claim token prices.
- Do not change active Codex settings, write data, or use network.

---

### Task 1: Implement and test the pure router

**Files:**
- Create: `src/tv_quant/model_routing.py`
- Create: `tests/test_model_routing.py`

**Interfaces:**
- Produces `RoutingDecision(model, reasoning_effort, complexity_score, reasons, hard_floor, escalate_when)`.
- Produces `recommend_model(task_text: str, changed_paths: Iterable[str] = ()) -> RoutingDecision`.

- [ ] **Step 1: Write failing tests**

```python
def test_simple_local_task_uses_luna_low():
    decision = recommend_model("rename one label in Chart Review")
    assert (decision.model, decision.reasoning_effort) == ("gpt-5.6-luna", "low")

def test_persistence_migration_forces_sol_xhigh():
    decision = recommend_model("migrate SQLite schema and preserve transactions")
    assert (decision.model, decision.reasoning_effort) == ("gpt-5.6-sol", "xhigh")
```

- [ ] **Step 2: Verify the test fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_model_routing.py -q`

- [ ] **Step 3: Add deterministic scorer**

```python
def recommend_model(task_text: str, changed_paths: Iterable[str] = ()) -> RoutingDecision:
    normalized = task_text.strip().lower()
    if not normalized:
        raise ValueError("task_text must be non-empty")
```

- [ ] **Step 4: Verify router tests pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_model_routing.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/tv_quant/model_routing.py tests/test_model_routing.py
git commit -m "feat: route coding tasks by complexity"
```

### Task 2: Expose read-only CLI and dashboard page

**Files:**
- Create: `scripts/recommend_coding_model.py`
- Create: `app/pages/6_Codex_Model_Router.py`
- Modify: `tests/test_model_routing.py`
- Modify: `tests/pattern_finder/test_pages.py`

**Interfaces:**
- Consumes `recommend_model(task_text, changed_paths)`.
- Produces JSON from `recommend_coding_model.py --task <text> [--path <path> ...]`.

- [ ] **Step 1: Write failing CLI/page tests**

```python
def test_cli_emits_json_for_task_and_paths(capsys):
    main(["--task", "debug Futu API integration"])
    assert json.loads(capsys.readouterr().out)["model"] == "gpt-5.6-terra"
```

- [ ] **Step 2: Verify the tests fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_model_routing.py tests/pattern_finder/test_pages.py -q`

- [ ] **Step 3: Implement no-side-effect interfaces**

Render task input, optional paths, profile, score, reasons, and escalation
conditions. Do not call subprocess, OpenD, a network client, or a model API.

- [ ] **Step 4: Verify focused tests pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_model_routing.py tests/pattern_finder/test_pages.py -q`

- [ ] **Step 5: Commit**

```bash
git add scripts/recommend_coding_model.py app/pages/6_Codex_Model_Router.py tests/test_model_routing.py tests/pattern_finder/test_pages.py
git commit -m "feat: expose Codex model routing guidance"
```
