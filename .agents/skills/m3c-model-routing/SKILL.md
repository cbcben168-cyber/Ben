---
name: m3c-model-routing
description: Recommend the lowest sufficient Codex model and reasoning tier for an M3C task without claiming to change an active session.
---

# M3C model routing

Use this only when selecting a model profile for M3C repository work. Run
`scripts/recommend_coding_model.py --task <description>` and add one `--path`
for every affected repository path.

- Treat the result as a recommendation for a future worker or task. It cannot
  change a running Codex session's model or reasoning effort.
- Use the lowest recommended profile. Preserve hard floors for persistence,
  security, and trading-domain risk; do not downgrade them to save tokens.
- Do not claim a token price or a measured saving unless verified separately.
- For an unlisted task, keep the recommendation and state its reasons rather
  than inventing a model override.
