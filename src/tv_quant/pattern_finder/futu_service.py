from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable

from tv_quant.futu_quota import (
    QuotaPolicyError,
    QuotaSnapshot,
    check_quota,
    write_quota_log,
)
from tv_quant.futu_downloader import FutuDownloadError

from .cache import (
    CacheEntry,
    DEFAULT_CACHE_ROOT,
    PatternCacheError,
    cached_symbols,
    load_cache_entry,
    refresh_cache_entry,
)
from .universe import M3B_SYMBOLS, PILOT_SYMBOLS, futu_code


M3B_TARGET_SIZES = (25, 50, 100)


@dataclass(frozen=True, slots=True)
class ExpansionResult:
    target_size: int
    starting_count: int
    completed_symbols: tuple[str, ...]
    final_count: int
    starting_quota: QuotaSnapshot | None
    ending_quota: QuotaSnapshot | None
    blocker: str | None


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
    """Refresh the fixed pilot symbols through the generic refresh service."""
    return refresh_symbols(
        PILOT_SYMBOLS,
        cache_root=cache_root,
        as_of_utc=as_of_utc,
        host=host,
        port=port,
        log_path=log_path,
        sdk=sdk,
        sleep=sleep,
    )


def refresh_symbols(
    symbols: Iterable[str],
    *,
    cache_root: str | Path = DEFAULT_CACHE_ROOT,
    as_of_utc: datetime,
    host: str = "127.0.0.1",
    port: int = 11111,
    log_path: str | Path = Path("logs/futu_quota.jsonl"),
    sdk: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[CacheEntry, ...]:
    """Refresh exactly the supplied symbols in order using OpenD quota authority."""
    ordered_symbols = tuple(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols))
    if not ordered_symbols or any(not symbol for symbol in ordered_symbols):
        raise ValueError("symbols must contain normalized non-empty tickers")

    runtime = _load_futu_sdk() if sdk is None else sdk
    context = runtime.OpenQuoteContext(host=host, port=port)
    entries: list[CacheEntry] = []
    try:
        _validate_opend(context, runtime.RET_OK, runtime.ProgramStatusType.READY)
        for symbol in ordered_symbols:
            code = futu_code(symbol)
            pre_snapshot = _quota_snapshot(context, runtime.RET_OK, sleep)
            decision = check_quota(pre_snapshot, code)
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


def stale_cached_symbols(
    *,
    cache_root: str | Path = DEFAULT_CACHE_ROOT,
    as_of_utc: datetime,
) -> tuple[str, ...]:
    """Return cached M3B symbols whose current quality report does not pass."""
    stale: list[str] = []
    for symbol in cached_symbols(cache_root):
        entry = load_cache_entry(symbol, cache_root=cache_root, as_of_utc=as_of_utc)
        if entry is not None and not entry.quality.passed:
            stale.append(symbol)
    return tuple(stale)


def _download_blocker(error: Exception) -> str:
    message = str(error)
    lowered = message.lower()
    if "permission" in lowered or "right" in lowered or "权限" in message:
        return f"FUTU_MARKET_PERMISSION_BLOCKER: {message}"
    return f"DATA_CAPABILITY_BLOCKER: {message}"


def refresh_universe_to_target(
    target_size: int,
    *,
    cache_root: str | Path = DEFAULT_CACHE_ROOT,
    as_of_utc: datetime,
    host: str = "127.0.0.1",
    port: int = 11111,
    log_path: str | Path = Path("logs/futu_quota.jsonl"),
    sdk: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ExpansionResult:
    """Add missing M3B caches until a milestone target or safety blocker."""
    if target_size not in M3B_TARGET_SIZES:
        raise ValueError("target_size must be 25, 50, or 100")

    starting_symbols = cached_symbols(cache_root)
    runtime = _load_futu_sdk() if sdk is None else sdk
    context = runtime.OpenQuoteContext(host=host, port=port)
    completed: list[str] = []
    starting_quota: QuotaSnapshot | None = None
    ending_quota: QuotaSnapshot | None = None
    blocker: str | None = None
    try:
        try:
            _validate_opend(context, runtime.RET_OK, runtime.ProgramStatusType.READY)
        except RuntimeError as error:
            blocker = f"FUTU_LOGIN_BLOCKER: {error}"
            return ExpansionResult(
                target_size,
                len(starting_symbols),
                (),
                len(starting_symbols),
                None,
                None,
                blocker,
            )

        starting_quota = _quota_snapshot(context, runtime.RET_OK, sleep)
        ending_quota = starting_quota
        if len(starting_symbols) >= target_size:
            return ExpansionResult(
                target_size,
                len(starting_symbols),
                (),
                len(starting_symbols),
                starting_quota,
                ending_quota,
                None,
            )

        missing = tuple(
            symbol for symbol in M3B_SYMBOLS if symbol not in set(starting_symbols)
        )
        needed = target_size - len(starting_symbols)
        for symbol in missing[:needed]:
            code = futu_code(symbol)
            try:
                pre_snapshot = _quota_snapshot(context, runtime.RET_OK, sleep)
                decision = check_quota(pre_snapshot, code)
            except (QuotaPolicyError, RuntimeError) as error:
                blocker = f"FUTU_QUOTA_BLOCKER: {error}"
                break

            write_quota_log(log_path, "pre", pre_snapshot, code, decision, "allowed")
            try:
                refresh_cache_entry(
                    symbol,
                    context,
                    cache_root=cache_root,
                    as_of_utc=as_of_utc,
                    ret_ok=runtime.RET_OK,
                    ktype=runtime.KLType.K_DAY,
                    autype=runtime.AuType.QFQ,
                    sleep=sleep,
                )
            except (FutuDownloadError, PatternCacheError) as error:
                write_quota_log(
                    log_path, "post", pre_snapshot, code, decision, "failed"
                )
                blocker = _download_blocker(error)
                break

            ending_quota = _quota_snapshot(context, runtime.RET_OK, sleep)
            write_quota_log(
                log_path, "post", ending_quota, code, decision, "success"
            )
            completed.append(symbol)

        final_count = len(cached_symbols(cache_root))
        return ExpansionResult(
            target_size=target_size,
            starting_count=len(starting_symbols),
            completed_symbols=tuple(completed),
            final_count=final_count,
            starting_quota=starting_quota,
            ending_quota=ending_quota,
            blocker=blocker,
        )
    finally:
        context.close()
