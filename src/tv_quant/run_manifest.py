import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    spec,
    data_path,
    source_label,
    artifact_paths,
    code_commit,
    smoke_test_marker,
) -> dict[str, object]:
    return {
        "strategy_config_hash": canonical_hash(spec.raw),
        "data_hash": sha256_file(data_path),
        "code_commit": code_commit,
        "strategy_name": spec.strategy_name,
        "provider": source_label,
        "symbol": spec.symbol,
        "timeframe": spec.timeframe,
        "start_date": spec.start_date.isoformat(),
        "end_date": spec.end_date.isoformat(),
        "fill_timing": spec.fill_timing,
        "commission_bps": spec.commission_bps,
        "slippage_bps": spec.slippage_bps,
        "optimization_allowed": spec.optimization_allowed,
        "benchmark": spec.benchmark,
        "data_path": str(data_path),
        "artifact_paths": {
            name: str(path) for name, path in artifact_paths.items()
        },
        "smoke_test_marker": smoke_test_marker,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
