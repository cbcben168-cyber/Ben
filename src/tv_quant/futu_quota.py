"""Futu historical-K-line quota protection."""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

class QuotaPolicyError(RuntimeError): pass

@dataclass(frozen=True)
class QuotaSnapshot:
    used_quota: int
    remain_quota: int
    detail_list: list[dict[str, Any]]

@dataclass(frozen=True)
class QuotaDecision:
    is_new_code: bool
    daily_new_code_count: int
    rolling_code_count: int

def check_quota(snapshot: QuotaSnapshot, code: str, now: datetime, history: list[dict[str, Any]]) -> QuotaDecision:
    known = {str(item.get("code", "")).upper() for item in snapshot.detail_list}
    is_new = code.upper() not in known
    daily = len({str(item["code"]).upper() for item in history if item.get("is_new_code") and _when(item).date() == now.date()})
    rolling = {str(item["code"]).upper() for item in history if item.get("is_new_code") and _when(item) >= now - timedelta(days=7)}
    if not is_new:
        return QuotaDecision(False, daily, len(rolling))
    if snapshot.remain_quota < 100: raise QuotaPolicyError(f"remain_quota {snapshot.remain_quota} is below 100")
    if daily >= 25: raise QuotaPolicyError("daily new-code limit of 25 reached")
    if code.upper() not in rolling and len(rolling) >= 200: raise QuotaPolicyError("rolling seven-day code limit of 200 reached")
    return QuotaDecision(True, daily, len(rolling))

def read_quota_history(path: str | Path) -> list[dict[str, Any]]:
    file = Path(path)
    return [] if not file.exists() else [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line]

def write_quota_log(path: str | Path, phase: str, snapshot: QuotaSnapshot, code: str, decision: QuotaDecision | None, outcome: str) -> None:
    record = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "phase": phase, "code": code, "used_quota": snapshot.used_quota, "remain_quota": snapshot.remain_quota, "detail_list": snapshot.detail_list, "is_new_code": decision.is_new_code if decision else None, "daily_new_code_count": decision.daily_new_code_count if decision else None, "rolling_code_count": decision.rolling_code_count if decision else None, "outcome": outcome}
    file = Path(path); file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("a", encoding="utf-8") as handle: handle.write(json.dumps(record, ensure_ascii=False) + "\n")

def _when(item: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(item["timestamp_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc)
