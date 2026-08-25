# Pattern Finder Local Runtime, SQLite, and Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a double-clickable local Pattern Finder with versioned SQLite persistence and a real system dashboard.

**Architecture:** Runtime configuration and service ownership are isolated from the Streamlit UI. Application read models query Repository objects; Repository implementations own all SQLite access and preserve exact Profile/Snapshot semantics.

**Tech Stack:** Python 3.12+, standard-library `sqlite3`, Streamlit 1.59.1, PyYAML 6.0.3, Windows cmd, pytest 9.1.1.

**Spec:** `docs/superpowers/specs/2026-08-25-pattern-finder-local-runtime-sqlite-dashboard-design.md`

## Global Constraints

- Preserve existing Profile and Universe Snapshot files.
- Do not change Snapshot/Profile hashes or deterministic decision semantics.
- UI and business modules must not import `sqlite3`.
- Default database is `data/db/pattern_finder.db`; default host is `127.0.0.1`.
- Do not terminate a process unless its PID record and command line identify this repository and `app/Home.py`.
- Use `PYTHONPATH=src` for repository test commands.

---

### Task 1: M3C-B runtime

**Files:**
- Create: `src/tv_quant/pattern_finder/runtime/config.py`
- Create: `src/tv_quant/pattern_finder/runtime/service.py`
- Create: `src/tv_quant/pattern_finder/runtime/__main__.py`
- Create: `scripts/start_pattern_finder.cmd`
- Create: `scripts/stop_pattern_finder.cmd`
- Create: `scripts/install_desktop_launcher.cmd`
- Test: `tests/pattern_finder/test_local_runtime.py`

**Interfaces:** Produces `RuntimeConfig`, `ServiceHealth`, `start_service`, `stop_service`, and CLI commands `migrate`, `health`, `start`, `stop`.

- [x] Write configuration, owned-process, duplicate-start, unrelated-port, database-health, and launcher contract tests.
- [x] Run the focused test and confirm missing modules/contracts fail.
- [x] Implement the minimum runtime code and Windows scripts.
- [x] Run the focused tests and Pattern Finder regression.
- [x] Commit M3C-B independently.

### Task 2: M3C-C SQLite data foundation

**Files:**
- Create: `src/tv_quant/pattern_finder/persistence/database.py`
- Create: `src/tv_quant/pattern_finder/persistence/migrations.py`
- Create: `src/tv_quant/pattern_finder/persistence/repositories.py`
- Create: `src/tv_quant/pattern_finder/persistence/legacy_import.py`
- Test: `tests/pattern_finder/test_sqlite_persistence.py`

**Interfaces:** Produces `SqliteDatabase`, repository classes, `MigrationReport`, and `migrate_snapshot_store`.

- [x] Write initialization, idempotency, rollback, foreign-key, immutability, duplicate, Snapshot round-trip, S0-S10, Profile version, and legacy dry-run/import tests.
- [x] Run focused tests and confirm missing modules/contracts fail.
- [x] Implement schema migration v1 and Repository persistence.
- [x] Run focused tests, Snapshot regression, and Pattern Finder regression.
- [x] Commit M3C-C independently.

### Task 3: M3C-D system dashboard

**Files:**
- Create: `src/tv_quant/pattern_finder/application/system_dashboard.py`
- Create: `config/project_progress.yaml`
- Modify: `app/Home.py`
- Create: `app/pages/4_Project_Progress.py`
- Create: `app/pages/5_Diagnostics.py`
- Test: `tests/pattern_finder/test_system_dashboard.py`

**Interfaces:** Produces `DashboardState`, `DiagnosticsState`, `ProjectProgress`, and display-only render functions.

- [x] Write progress computation, real repository status, stale-data, no-secret diagnostics, and Streamlit navigation/render tests.
- [x] Run focused tests and confirm missing application/UI contracts fail.
- [x] Implement application read models, YAML source-of-truth, and Streamlit pages.
- [x] Run focused tests and Pattern Finder regression.
- [x] Commit M3C-D independently.

### Task 4: Acceptance and handoff

**Files:**
- Modify only files required by defects demonstrated by the acceptance commands.

- [x] Run `PYTHONPATH=src .venv/bin/python -m pytest tests/pattern_finder -q -p no:cacheprovider`.
- [x] Run `PYTHONPATH=src .venv/bin/python -m pytest tests -q -p no:cacheprovider`.
- [x] Run `.venv/bin/python -m compileall -q src tests`.
- [x] Run `git diff --check` and inspect `git status --short`.
- [x] Verify a temporary database migration and Dashboard read model against real repository code.
- [x] Report Windows-only manual acceptance separately from automated evidence.
