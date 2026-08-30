---
name: m3c-futu-quota-refresh
description: Safely inspect or refresh M3C Futu historical caches using current OpenD quota authority and explicit user-triggered actions.
---

# M3C Futu quota refresh

Use for M3C historical-cache refresh or quota-blocker diagnosis.

- `used_quota`, `remain_quota`, and `detail_list` from the current OpenD
  response are the only download authority. JSONL quota history is audit
  evidence, never a local admission policy.
- A code in `detail_list` remains refreshable when new-code quota is zero. A
  code absent from it is blocked only when `remain_quota <= 0`.
- Refresh only through the existing exact-symbol service and only after an
  explicit action. Preserve OpenD login checks, QFQ, K_DAY, cache-quality
  validation, deterministic order, and context cleanup.
- Report provider failures as blockers; do not infer permissions, invent quota
  values, or broaden a stale-only refresh into a bulk download.
- Never connect a broker account, place an order, or treat this data workflow
  as trading authorization.
