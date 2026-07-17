"""Windows-friendly command-line entry point for first-phase workflows."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from .data_quality import load_standardized_csv
from .downloader import SUPPORTED_TICKERS, default_date_range, download_daily, save_daily_csv
from .metrics import buy_and_hold_return, calculate_metrics
from .reporting import write_reports
from .strategy import run_backtest
from .futu_downloader import update_futu_csv
from .futu_quota import QuotaSnapshot, check_quota, read_quota_history, write_quota_log


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tv_quant")
    commands = parser.add_subparsers(dest="command", required=True)

    download = commands.add_parser("download", help="download standardized SPY/QQQ daily CSV files")
    download.add_argument("--tickers", nargs="*", default=list(SUPPORTED_TICKERS), choices=SUPPORTED_TICKERS)
    download.add_argument("--source", choices=("futu", "yfinance"), default="futu")
    download.add_argument("--years", type=int, default=10)
    download.add_argument("--start", type=date.fromisoformat)
    download.add_argument("--end", type=date.fromisoformat)
    download.add_argument("--out-dir", type=Path, default=Path("data/raw"))
    download.add_argument("--overwrite", action="store_true")

    backtest = commands.add_parser("backtest", help="run the fixed EMA50/EMA200 strategy")
    backtest.add_argument("--input", type=Path, required=True)
    backtest.add_argument("--out-dir", type=Path, required=True)
    backtest.add_argument("--initial-cash", type=float, default=100_000.0)
    backtest.add_argument("--commission-bps", type=float, default=5.0)
    backtest.add_argument("--slippage-bps", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "download":
        return _download(args)
    return _backtest(args)


def _download(args: argparse.Namespace) -> int:
    if args.years <= 0:
        raise ValueError("--years must be positive")
    default_start, default_end = default_date_range(args.years)
    start = args.start or default_start
    end = args.end or default_end
    if start >= end:
        raise ValueError("--start must precede --end")
    if args.source == "yfinance":
        for ticker in args.tickers:
            path = save_daily_csv(download_daily(ticker, start, end), args.out_dir, args.overwrite)
            print(path)
        return 0
    _download_futu(args, start, end)
    return 0


def _import_futu() -> tuple[object, object, object, object, object]:
    """Import Futu after directing its mandatory SDK log to the project workspace."""
    import os

    log_root = Path(__file__).resolve().parents[2] / "logs" / "futu_sdk_appdata"
    log_root.mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = str(log_root)
    try:
        from futu import AuType, KLType, OpenQuoteContext, ProgramStatusType, RET_OK
    except ImportError as error:
        raise RuntimeError("Futu source selected but futu-api is not installed") from error
    return AuType, KLType, OpenQuoteContext, ProgramStatusType, RET_OK


def _validate_opend(context: object, ret_ok: int, ready: object) -> None:
    ret, state = context.get_global_state()
    if ret != ret_ok:
        raise RuntimeError(f"Futu OpenD status request failed: {state}. 请启动 Futu OpenD 并登录")
    qot_logined = state.get("qot_logined") if isinstance(state, dict) else None
    program_status = state.get("program_status_type") if isinstance(state, dict) else None
    if str(qot_logined).lower() not in {"1", "true"} or program_status != ready:
        raise RuntimeError(
            "Futu OpenD is unavailable: "
            f"qot_logined={qot_logined!r}, program_status_type={program_status!r}. 请启动 Futu OpenD 并登录"
        )


def _download_futu(args: argparse.Namespace, requested_start: date, requested_end: date) -> None:
    try:
        AuType, KLType, OpenQuoteContext, ProgramStatusType, RET_OK = _import_futu()
    except RuntimeError:
        raise
    context = OpenQuoteContext(host="127.0.0.1", port=11111)
    log_path = Path(__file__).resolve().parents[2] / "logs" / "futu_quota.jsonl"
    try:
        _validate_opend(context, RET_OK, ProgramStatusType.READY)
        for ticker in args.tickers:
            code = f"US.{ticker}"
            history = read_quota_history(log_path)
            quota = _futu_quota(context, RET_OK)
            decision = check_quota(quota, code, datetime_now_utc(), history)
            write_quota_log(log_path, "pre", quota, code, decision, "allowed")
            destination = args.out_dir / f"{ticker}_daily.csv"
            start, end = (requested_start, requested_end) if args.start or args.end else _futu_range(destination)
            post_snapshot: QuotaSnapshot | None = None
            def verify_post_download(_: object) -> None:
                nonlocal post_snapshot
                post_snapshot = _futu_quota(context, RET_OK)
                write_quota_log(log_path, "post", post_snapshot, code, decision, "success")
            update = update_futu_csv(destination, code, start, end, context, ret_ok=RET_OK, ktype=KLType.K_DAY, autype=AuType.QFQ, before_replace=verify_post_download)
            print(f"{update.path} (new_rows={update.new_rows}, updated_rows={update.updated_rows}, total_rows={update.total_rows})")
    finally:
        context.close()


def _futu_quota(context: object, ret_ok: int) -> QuotaSnapshot:
    import time
    time.sleep(1)
    ret, data = context.get_history_kl_quota(get_detail=True)
    if ret != ret_ok:
        raise RuntimeError(f"Futu quota request failed: {data}")
    used, remain, detail = data
    return QuotaSnapshot(int(used), int(remain), list(detail))


def _futu_range(destination: Path) -> tuple[date, date]:
    end = date.today()
    if destination.exists():
        return end - timedelta(days=10), end
    try:
        return end.replace(year=end.year - 10), end
    except ValueError:  # February 29 has no equivalent in non-leap years.
        return end.replace(year=end.year - 10, day=28), end


def datetime_now_utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _backtest(args: argparse.Namespace) -> int:
    data, data_warnings = load_standardized_csv(args.input)
    tickers = set(data["ticker"].astype(str).str.upper())
    if len(tickers) != 1 or not tickers.issubset(SUPPORTED_TICKERS):
        raise ValueError("input must contain exactly one supported ticker")
    result = run_backtest(data, args.initial_cash, args.commission_bps, args.slippage_bps)
    metrics = calculate_metrics(result.equity, result.trades, args.initial_cash)
    ticker = next(iter(tickers))
    benchmark_return = buy_and_hold_return(data, args.initial_cash, args.commission_bps, args.slippage_bps)
    strategy_minus_buy_hold = metrics["total_return"] - benchmark_return
    summary: dict[str, object] = {
        "ticker": ticker,
        "data_start_utc": data["timestamp_utc"].iloc[0],
        "data_end_utc": data["timestamp_utc"].iloc[-1],
        "parameters": {
            "ema_fast": 50,
            "ema_slow": 200,
            "initial_cash": args.initial_cash,
            "commission_bps": args.commission_bps,
            "slippage_bps": args.slippage_bps,
        },
        **metrics,
        "buy_and_hold_return": benchmark_return,
        "strategy_minus_buy_hold": strategy_minus_buy_hold,
        "buy_and_hold_comparison": "BEAT_BUY_HOLD" if strategy_minus_buy_hold > 0 else "UNDERPERFORM_BUY_HOLD",
        "validation_warnings": data_warnings + result.warnings,
    }
    paths = write_reports(args.out_dir, summary, result.equity, result.trades)
    for path in paths.values():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
