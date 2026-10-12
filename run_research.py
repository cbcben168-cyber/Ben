from __future__ import annotations

import argparse
import json
from pathlib import Path

from factor_research.phase3_edge_engine.pipeline import (
    DEFAULT_AUDIT_MANIFEST,
    DEFAULT_DATA,
    REPO_ROOT,
    run_pipeline,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the C1 Phase 3 offline TRAIN research engine.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--audit-manifest", type=Path, default=DEFAULT_AUDIT_MANIFEST)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "factor_research" / "phase3_edge_engine" / "outputs" / "phase3_train_v1",
    )
    args = parser.parse_args()
    manifest = run_pipeline(args.data.resolve(), args.audit_manifest.resolve(), args.output_dir.resolve())
    print(json.dumps({
        "status": manifest["state_machine_consistency"]["status"],
        "factor_count": manifest["registry"]["factor_count"],
        "output_dir": str(args.output_dir.resolve()),
        "total_seconds": manifest["timings"]["total_seconds"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if manifest["state_machine_consistency"]["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
