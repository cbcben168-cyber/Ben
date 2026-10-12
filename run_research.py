from __future__ import annotations

import argparse
import json
from pathlib import Path

from factor_research.phase3_edge_engine.pipeline import (
    DEFAULT_AUDIT_MANIFEST,
    DEFAULT_DATA,
    DEFAULT_RUNLOG,
    PHASE3_V3_OUTPUT,
    run_pipeline,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the C1 Phase 3 offline TRAIN research engine.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--audit-manifest", type=Path, default=DEFAULT_AUDIT_MANIFEST)
    parser.add_argument("--v311-runlog", type=Path, default=DEFAULT_RUNLOG)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PHASE3_V3_OUTPUT,
    )
    args = parser.parse_args(argv)
    output_dir = args.output_dir.resolve()
    if output_dir != PHASE3_V3_OUTPUT.resolve():
        print(json.dumps({
            "status": "CLI_FAIL",
            "reason": "PHASE3_V3_OUTPUT_REQUIRED",
            "expected_output_dir": str(PHASE3_V3_OUTPUT.resolve()),
            "requested_output_dir": str(output_dir),
        }, ensure_ascii=False, sort_keys=True))
        return 2
    try:
        manifest = run_pipeline(
            args.data.resolve(),
            args.audit_manifest.resolve(),
            output_dir,
            args.v311_runlog.resolve(),
        )
    except RuntimeError as error:
        print(json.dumps({
            "status": "CLI_FAIL",
            "reason": str(error),
            "output_dir": str(output_dir),
        }, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps({
        "status": manifest["acceptance_status"],
        "data_qualification_status": manifest["data_qualification"]["status"],
        "engine_status": manifest["engine_status"],
        "statistics_status": manifest["statistics_status"],
        "trade_parity_status": manifest["trade_parity"]["status"],
        "research_status": manifest["research_status"],
        "factor_count": manifest["registry"]["factor_count"],
        "output_dir": str(args.output_dir.resolve()),
        "total_seconds": manifest["timings"]["total_seconds"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if manifest["acceptance_status"] == "ACCEPTANCE_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
