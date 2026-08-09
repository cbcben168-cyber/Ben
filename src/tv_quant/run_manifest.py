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


def validate_canonical_json_value(value: object, path: str = "payload") -> None:
    """Reject values that cannot be represented by canonical JSON."""
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float:
        raise TypeError(f"{path}: canonical JSON does not allow float values")
    if type(value) is list:
        for index, item in enumerate(value):
            validate_canonical_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError(f"{path}: canonical JSON mapping keys must be strings")
            validate_canonical_json_value(item, f"{path}.{key}")
        return
    raise TypeError(f"{path}: canonical JSON value required")


def canonical_hash(value: Mapping[str, Any]) -> str:
    validate_canonical_json_value(value)
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
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
    *,
    persisted_refs: Mapping[str, str] | None = None,
    hashed_names: tuple[str, ...] = HASHED_ARTIFACT_NAMES,
) -> dict[str, object]:
    names = tuple(hashed_names)
    missing = tuple(name for name in names if name not in artifact_paths)
    if missing:
        raise ValueError(f"artifact_paths: missing {missing!r}")
    bound = dict(manifest)
    bound["artifact_hashes"] = {
        name: sha256_file(Path(artifact_paths[name])) for name in names
    }
    if persisted_refs is None:
        bound["artifact_paths"] = {
            name: str(artifact_paths[name]) for name in sorted(artifact_paths)
        }
        if "strategy_config" in artifact_paths:
            strategy_config_path = Path(artifact_paths["strategy_config"])
            bound["strategy_config_path"] = str(strategy_config_path)
            bound["strategy_config_file_hash"] = sha256_file(strategy_config_path)
    else:
        if set(persisted_refs) != set(artifact_paths):
            raise ValueError("persisted_refs: exact artifact key set required")
        bound["artifact_refs"] = {
            name: validate_persisted_relative_ref(
                persisted_refs[name], f"artifact_refs.{name}"
            )
            for name in sorted(persisted_refs)
        }
    return bound


def validate_persisted_relative_ref(value: object, path: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{path}: relative path string required")
    from tv_quant.contracts.path_safety import _validated_relative_path

    try:
        _validated_relative_path(value)
    except ValueError as exc:
        raise ValueError(f"{path}: validated relative path required") from exc
    return value


def write_canonical_json_artifact(path: Path, payload: Mapping[str, Any]) -> None:
    validate_canonical_json_value(payload)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    validate_canonical_json_value(manifest)
    path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
