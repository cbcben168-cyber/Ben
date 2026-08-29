"""Futu historical-K-line quota protection."""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

class QuotaPolicyError(RuntimeError): pass

@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    used_quota: int
    remain_quota: int
    detail_list: list[dict[str, Any]]

@dataclass(frozen=True, slots=True)
class QuotaDecision:
    is_new_code: bool
    known_code_count: int
    server_used_quota: int
    server_remain_quota: int

def check_quota(snapshot: QuotaSnapshot, code: str) -> QuotaDecision:
    """Accept a download when Futu's current quota response permits it."""
    normalized = code.strip().upper()
    if not normalized:
        raise ValueError("code must be non-empty")

    known_codes = {
        str(item.get("code", "")).strip().upper()
        for item in snapshot.detail_list
        if str(item.get("code", "")).strip()
    }
    is_new_code = normalized not in known_codes
    if is_new_code and snapshot.remain_quota <= 0:
        raise QuotaPolicyError("no remaining historical-K-line quota for a new code")

    return QuotaDecision(
        is_new_code=is_new_code,
        known_code_count=len(known_codes),
        server_used_quota=snapshot.used_quota,
        server_remain_quota=snapshot.remain_quota,
    )

def read_quota_history(path: str | Path) -> list[dict[str, Any]]:
    file = Path(path)
    return [] if not file.exists() else [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line]

def write_quota_log(path: str | Path, phase: str, snapshot: QuotaSnapshot, code: str, decision: QuotaDecision | None, outcome: str) -> None:
    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "code": code,
        "used_quota": snapshot.used_quota,
        "remain_quota": snapshot.remain_quota,
        "detail_list": snapshot.detail_list,
        "is_new_code": decision.is_new_code if decision else None,
        "known_code_count": decision.known_code_count if decision else None,
        "server_used_quota": decision.server_used_quota if decision else None,
        "server_remain_quota": decision.server_remain_quota if decision else None,
        "outcome": outcome,
    }
    file = Path(path); file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
