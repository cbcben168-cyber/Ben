import argparse
from pathlib import Path
import sys

from . import cli as legacy_cli
from .contracts.runner_protocol import RunnerMode, RunnerRequest, run_v2
from .research_pipeline import (
    PipelineOptions,
    clear_data_provenance_pending,
    mark_data_provenance_pending,
    run_pipeline,
    write_data_provenance,
)
from .strategy_spec import load_strategy_spec


class _RefreshDelegationFailure(RuntimeError):
    pass


def exit_code_for_status(status: str) -> int:
    return {
        "PASS": 0,
        "CONDITIONAL_PASS": 0,
        "STRATEGY_CAPABILITY_BLOCKER": 3,
        "DATA_CAPABILITY_BLOCKER": 4,
        "FAIL": 5,
    }.get(status, 5)


def _refresh_data(spec, target_path: Path) -> None:
    source = "yfinance" if spec.data_source == "yfinance" else "futu"
    argv = [
        "download",
        "--tickers", spec.symbol,
        "--source", source,
        "--start", spec.start_date.isoformat(),
        "--end", spec.end_date.isoformat(),
        "--out-dir", str(target_path.parent),
    ]
    if source == "yfinance":
        argv.append("--overwrite")
        try:
            mark_data_provenance_pending(target_path)
        except OSError as error:
            raise RuntimeError(
                f"data provenance publication failed: {error}"
            ) from error
    result = legacy_cli.main(argv)
    if result != 0:
        raise RuntimeError(f"data refresh failed with exit code {result}")
    if target_path.is_file():
        try:
            write_data_provenance(target_path, source)
            if source == "yfinance":
                clear_data_provenance_pending(target_path, source)
        except (OSError, ValueError) as error:
            raise RuntimeError(
                f"data provenance publication failed: {error}"
            ) from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tv_quant.pipeline")
    parser.add_argument("--strategy-config", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--report-root", type=Path, default=Path("reports/runs"))
    parser.add_argument("--run-directory", type=Path)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--skip-data-refresh", action="store_true")
    parser.add_argument("--smoke-test-data", action="store_true")
    return parser


def _readable_config_path(value: str) -> Path:
    path = Path(value)
    try:
        with path.open("rb") as handle:
            handle.read(1)
    except OSError as error:
        raise argparse.ArgumentTypeError(
            "config path must be a readable file"
        ) from error
    return path


def _nonempty_confirmation_token(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("non-empty token required")
    return value


def build_v2_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tv_quant.pipeline v2",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", allow_abbrev=False)
    validate.add_argument(
        "--config",
        type=_readable_config_path,
        required=True,
    )
    validate.set_defaults(mode=RunnerMode.VALIDATE)

    prepare = commands.add_parser(
        "prepare-confirmation",
        allow_abbrev=False,
    )
    prepare.add_argument(
        "--config",
        type=_readable_config_path,
        required=True,
    )
    prepare.add_argument("--evidence-root", type=Path, required=True)
    prepare.set_defaults(mode=RunnerMode.PREPARE_CONFIRMATION)

    grant = commands.add_parser(
        "grant-confirmation",
        allow_abbrev=False,
    )
    grant.add_argument(
        "--config",
        type=_readable_config_path,
        required=True,
    )
    grant.add_argument("--request", type=Path, required=True)
    grant.add_argument("--approval-record", type=Path, required=True)
    grant.add_argument("--evidence-root", type=Path, required=True)
    grant.set_defaults(mode=RunnerMode.GRANT_CONFIRMATION)

    execute = commands.add_parser("execute", allow_abbrev=False)
    execute.add_argument(
        "--config",
        type=_readable_config_path,
        required=True,
    )
    execute.add_argument(
        "--confirmation-token",
        type=_nonempty_confirmation_token,
        required=True,
    )
    execute.add_argument("--request", type=Path, required=True)
    execute.add_argument("--evidence-root", type=Path, required=True)
    execute.set_defaults(mode=RunnerMode.EXECUTE)
    return parser


def _v2_exit_code(status: str) -> int:
    return {
        "SUCCESS": 0,
        "CONDITIONAL_SUCCESS": 0,
        "BLOCKED": 3,
        "FAILED": 4,
        "NOT_IMPLEMENTED": 5,
    }.get(status, 4)


def main_v2(argv: list[str] | None = None) -> int:
    args = build_v2_parser().parse_args(argv)
    request = RunnerRequest(
        config_path=args.config,
        mode=args.mode,
        confirmation_token=getattr(args, "confirmation_token", None),
        confirmation_request_path=getattr(args, "request", None),
        approval_record_path=getattr(args, "approval_record", None),
        evidence_root=getattr(args, "evidence_root", None),
    )
    response = run_v2(request)
    print(response.to_json())
    exit_code = _v2_exit_code(response.status)
    if exit_code != 0:
        print(
            f"status={response.status} blocker_code={response.blocker_code}",
            file=sys.stderr,
        )
    return exit_code


def main(argv: list[str] | None = None) -> int:
    explicit_argv = sys.argv[1:] if argv is None else argv
    if explicit_argv[:1] == ["v2"]:
        return main_v2(explicit_argv[1:])
    args = build_parser().parse_args(argv)
    try:
        options = PipelineOptions(
            data_root=args.data_root,
            report_root=args.report_root,
            run_directory=args.run_directory,
            audit_only=args.audit_only,
            skip_data_refresh=args.skip_data_refresh,
            allow_smoke_test_data=args.smoke_test_data,
        )
        refresh = None
        if not args.audit_only and not args.skip_data_refresh:
            def refresh(pipeline_spec, target_path):
                try:
                    _refresh_data(pipeline_spec, target_path)
                except RuntimeError as error:
                    raise _RefreshDelegationFailure(str(error)) from error

        result = run_pipeline(args.strategy_config, options, refresh_data=refresh)
    except _RefreshDelegationFailure as error:
        print(f"data_refresh_error={error}")
        return exit_code_for_status("DATA_CAPABILITY_BLOCKER")
    except (OSError, ValueError) as error:
        print(f"configuration_error={error}")
        return 2
    if getattr(result, "error_code", None) == "DATA_REFRESH_FAILURE":
        print(f"data_refresh_error={result.message}")
        if result.failure_record_path is not None:
            print(f"failure_record={result.failure_record_path}")
        return exit_code_for_status(result.status)
    print(f"status={result.status}")
    if result.run_directory is not None:
        print(f"report_directory={result.run_directory}")
    if getattr(result, "failure_record_path", None) is not None:
        print(f"failure_record={result.failure_record_path}")
    return exit_code_for_status(result.status)


if __name__ == "__main__":
    raise SystemExit(main())
