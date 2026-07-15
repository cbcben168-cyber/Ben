"""Report file generation for a single backtest run."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def write_reports(
    output_parent: str | Path,
    summary: dict[str, object],
    equity: pd.DataFrame,
    trades: pd.DataFrame,
) -> dict[str, Path]:
    """Write a unique run directory containing the required JSON and CSV reports."""
    run_name = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%S%fZ")
    run_directory = Path(output_parent) / run_name
    run_directory.mkdir(parents=True, exist_ok=False)
    summary_path = run_directory / "summary.json"
    equity_path = run_directory / "equity.csv"
    trades_path = run_directory / "trades.csv"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    equity.to_csv(equity_path, index=False, date_format="%Y-%m-%dT%H:%M:%SZ")
    trades.to_csv(trades_path, index=False, date_format="%Y-%m-%dT%H:%M:%SZ")
    return {"summary": summary_path, "equity": equity_path, "trades": trades_path}
