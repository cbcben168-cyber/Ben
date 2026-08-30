---
name: m3c-runtime-recovery
description: Start, diagnose, or resume the local M3C Pattern Finder runtime and its Codex recovery workflow without bypassing ownership safeguards.
---

# M3C runtime recovery

Use for the local Pattern Finder launcher, runtime health, or temporary Codex
usage/model limits. Work from the M3C repository root.

- Start only through `scripts/start_pattern_finder.cmd` (or its desktop
  delegator). Do not replace the owned runtime with a direct `streamlit run`.
- Use `python -m tv_quant.pattern_finder.runtime health` before diagnosing a
  stopped service. Preserve the PID ownership check, start lock, database
  health check, and runtime logs.
- Treat usage/model limits as temporary. Preserve tracked work and the
  user-owned `data/` and `migration_backup/` directories; never reset, clean,
  archive, or merge to recover.
- For repeat recovery, create or update a Codex heartbeat. Hourly retry is a
  safe bound; it cannot detect an exact five-hour capacity reset.
- A heartbeat may continue only the named M3C task. It must not create
  unrelated work, merge a PR, or push new changes without the task's authority.
