from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from tv_quant.futu_quota import (
    QuotaSnapshot,
    check_quota,
    read_quota_history,
    write_quota_log,
)

from .cache import CacheEntry, DEFAULT_CACHE_ROOT, refresh_cache_entry
from .universe import PILOT_SYMBOLS, futu_code


def _load_futu_sdk() -> object:
    log_root = Path(__file__).resolve().parents[3] / "logs" / "futu_sdk_appdata"
    log_root.mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = str(log_root)
    try:
        from futu import AuType, KLType, OpenQuoteContext, ProgramStatusType, RET_OK
    except ImportError as error:
        raise RuntimeError("未安装 futu-api，无法连接 Futu OpenD") from error
    return SimpleNamespace(
        AuType=AuType,
        KLType=KLType,
        OpenQuoteContext=OpenQuoteContext,
        ProgramStatusType=ProgramStatusType,
        RET_OK=RET_OK,
    )


def _validate_opend(context: object, ret_ok: int, ready: object) -> None:
    ret, state = context.get_global_state()  # type: ignore[attr-defined]
    if ret != ret_ok:
        raise RuntimeError(f"Futu OpenD 状态读取失败：{state}。请启动 OpenD 并登录")
    qot_logined = state.get("qot_logined") if isinstance(state, dict) else None
    program_status = state.get("program_status_type") if isinstance(state, dict) else None
    if str(qot_logined).lower() not in {"1", "true"} or program_status != ready:
        raise RuntimeError(
            "Futu OpenD 不可用或尚未登录："
            f"qot_logined={qot_logined!r}, program_status_type={program_status!r}。"
            "请启动 OpenD 并登录"
        )


def _quota_snapshot(
    context: object,
    ret_ok: int,
    sleep: Callable[[float], None],
) -> QuotaSnapshot:
    sleep(1)
    ret, data = context.get_history_kl_quota(get_detail=True)  # type: ignore[attr-defined]
    if ret != ret_ok:
        raise RuntimeError(f"Futu 历史 K 线额度读取失败：{data}")
    used, remain, detail = data
    return QuotaSnapshot(int(used), int(remain), list(detail))


def refresh_pilot_universe(
    *,
    cache_root: str | Path = DEFAULT_CACHE_ROOT,
    as_of_utc: datetime,
    host: str = "127.0.0.1",
    port: int = 11111,
    log_path: str | Path = Path("logs/futu_quota.jsonl"),
    sdk: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[CacheEntry, ...]:
    runtime = _load_futu_sdk() if sdk is None else sdk
    context = runtime.OpenQuoteContext(host=host, port=port)
    entries: list[CacheEntry] = []
    try:
        _validate_opend(context, runtime.RET_OK, runtime.ProgramStatusType.READY)
        for symbol in PILOT_SYMBOLS:
            code = futu_code(symbol)
            pre_snapshot = _quota_snapshot(context, runtime.RET_OK, sleep)
            decision = check_quota(
                pre_snapshot,
                code,
                as_of_utc,
                read_quota_history(log_path),
            )
            write_quota_log(log_path, "pre", pre_snapshot, code, decision, "allowed")
            try:
                entry = refresh_cache_entry(
                    symbol,
                    context,
                    cache_root=cache_root,
                    as_of_utc=as_of_utc,
                    ret_ok=runtime.RET_OK,
                    ktype=runtime.KLType.K_DAY,
                    autype=runtime.AuType.QFQ,
                    sleep=sleep,
                )
            except Exception:
                write_quota_log(log_path, "post", pre_snapshot, code, decision, "failed")
                raise
            post_snapshot = _quota_snapshot(context, runtime.RET_OK, sleep)
            write_quota_log(log_path, "post", post_snapshot, code, decision, "success")
            entries.append(entry)
        return tuple(entries)
    finally:
        context.close()
