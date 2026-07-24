import argparse
from pathlib import Path

from . import cli as legacy_cli
from .research_pipeline import PipelineOptions, run_pipeline
from .strategy_spec import load_strategy_spec


def exit_code_for_status(status: str) -> int:
    return {
        "PASS": 0,
        "CONDITIONAL_PASS": 0,
        "STRATEGY_CAPABILITY_BLOCKER": 3,
        "DATA_CAPABILITY_BLOCKER": 4,
        "FAIL": 5,
    }.get(status, 5)


def _refresh_data(spec, data_root: Path) -> None:
    source = "yfinance" if spec.data_source == "yfinance" else "futu"
    argv = [
        "download",
        "--tickers", spec.symbol,
        "--source", source,
        "--start", spec.start_date.isoformat(),
        "--end", spec.end_date.isoformat(),
        "--out-dir", str(data_root),
    ]
    if source == "yfinance":
        argv.append("--overwrite")
    result = legacy_cli.main(argv)
    if result != 0:
        raise RuntimeError(f"data refresh failed with exit code {result}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tv_quant.pipeline")
    parser.add_argument("--strategy-config", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--report-root", type=Path, default=Path("reports/runs"))
    parser.add_argument("--run-directory", type=Path)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--skip-data-refresh", action="store_true")
    parser.add_argument("--smoke-test-data", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        spec = load_strategy_spec(args.strategy_config)
        options = PipelineOptions(
            data_root=args.data_root,
            report_root=args.report_root,
            run_directory=args.run_directory,
            quick=args.quick,
            audit_only=args.audit_only,
            skip_data_refresh=args.skip_data_refresh,
            allow_smoke_test_data=args.smoke_test_data,
        )
        refresh = None if args.skip_data_refresh else _refresh_data
        result = run_pipeline(args.strategy_config, options, refresh_data=refresh)
    except (OSError, ValueError) as error:
        print(f"configuration_error={error}")
        return 2
    print(f"status={result.status}")
    if result.run_directory is not None:
        print(f"report_directory={result.run_directory}")
    return exit_code_for_status(result.status)


if __name__ == "__main__":
    raise SystemExit(main())
