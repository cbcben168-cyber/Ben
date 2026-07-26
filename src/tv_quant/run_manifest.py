import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


HASHED_ARTIFACT_NAMES = (
    "summary",
    "equity",
    "trades",
    "report_zh",
    "strategy_config",
)


def canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return sha256_bytes(payload.encode("utf-8"))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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
    *,
    strategy_config_path: Path | None = None,
) -> dict[str, object]:
    manifest = {
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
    if strategy_config_path is not None:
        manifest["strategy_config_path"] = str(strategy_config_path)
        manifest["strategy_config_file_hash"] = sha256_file(
            strategy_config_path
        )
    return manifest


def bind_artifact_hashes(
    manifest: Mapping[str, Any],
    artifact_paths: Mapping[str, Path],
) -> dict[str, object]:
    bound = dict(manifest)
    bound["artifact_paths"] = {
        name: str(path) for name, path in artifact_paths.items()
    }
    bound["artifact_hashes"] = {
        name: sha256_file(Path(artifact_paths[name]))
        for name in HASHED_ARTIFACT_NAMES
    }
    strategy_config_path = Path(artifact_paths["strategy_config"])
    bound["strategy_config_path"] = str(strategy_config_path)
    bound["strategy_config_file_hash"] = sha256_file(strategy_config_path)
    return bound


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
