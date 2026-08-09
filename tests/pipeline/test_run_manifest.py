from copy import deepcopy
from datetime import datetime

from tv_quant.run_manifest import (
    bind_artifact_hashes,
    build_manifest,
    canonical_hash,
    sha256_bytes,
    sha256_file,
    write_manifest,
)
from tv_quant.strategy_spec import validate_strategy_mapping

from tests.pipeline.helpers import valid_payload


def test_canonical_hash_is_stable_for_mapping_order():
    left = {"b": 2, "a": {"d": 4, "c": 3}}
    right = {"a": {"c": 3, "d": 4}, "b": 2}

    assert canonical_hash(left) == canonical_hash(right)


def test_sha256_file_changes_with_file_content(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("one\n", encoding="utf-8")
    first = sha256_file(path)

    path.write_text("two\n", encoding="utf-8")

    assert sha256_file(path) != first


def test_sha256_bytes_matches_known_digest():
    assert sha256_bytes(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223"
        "b00361a396177a9cb410ff61f20015ad"
    )


def test_existing_manifest_hash_functions_keep_behavior(tmp_path):
    path = tmp_path / "payload.bin"
    path.write_bytes(b"abc")

    assert canonical_hash({"b": 2, "a": 1}) == (
        "43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777"
    )
    assert sha256_file(path) == sha256_bytes(b"abc")


def test_build_manifest_records_reproducibility_evidence(tmp_path):
    spec = validate_strategy_mapping(valid_payload())
    data_path = tmp_path / "SPY_daily.csv"
    data_path.write_text("deterministic-data\n", encoding="utf-8")
    strategy_config_path = tmp_path / "strategy_config.yaml"
    strategy_config_path.write_text("strategy_name: ema_baseline\n", encoding="utf-8")
    artifact_paths = {
        "summary": tmp_path / "summary.json",
        "equity": tmp_path / "equity.csv",
        "trades": tmp_path / "trades.csv",
    }

    manifest = build_manifest(
        spec,
        data_path,
        "Futu_LOCAL_CACHE",
        artifact_paths,
        "abc123",
        None,
        strategy_config_path=strategy_config_path,
    )

    assert manifest["strategy_config_hash"] == canonical_hash(spec.raw)
    assert manifest["strategy_config_path"] == str(strategy_config_path)
    assert manifest["strategy_config_file_hash"] == sha256_file(
        strategy_config_path
    )
    assert manifest["data_hash"] == sha256_file(data_path)
    assert manifest["code_commit"] == "abc123"
    assert manifest["provider"] == "Futu_LOCAL_CACHE"
    assert manifest["benchmark"] == spec.benchmark
    assert manifest["smoke_test_marker"] is None
    assert manifest["fill_timing"] == "next_bar"
    assert manifest["commission_bps"] == "5"
    assert manifest["slippage_bps"] == "5"
    assert manifest["optimization_allowed"] is False
    assert manifest["artifact_paths"]["summary"] == str(artifact_paths["summary"])
    assert datetime.fromisoformat(manifest["generated_at_utc"]).tzinfo is not None


def test_build_manifest_canonicalizes_finite_legacy_float_costs_and_raw_hash(tmp_path):
    payload = valid_payload()
    payload["commission_model"]["value"] = 0.5
    payload["slippage_model"]["value"] = 1e-7
    spec = validate_strategy_mapping(payload)
    data_path = tmp_path / "SPY_daily.csv"
    data_path.write_text("deterministic-data\n", encoding="utf-8")

    manifest = build_manifest(spec, data_path, "cache", {}, "abc", None)
    canonical_payload = deepcopy(dict(spec.raw))
    canonical_payload["commission_model"]["value"] = "0.5"
    canonical_payload["slippage_model"]["value"] = "0.0000001"

    assert spec.raw["commission_model"]["value"] == 0.5
    assert spec.raw["slippage_model"]["value"] == 1e-7
    assert manifest["commission_bps"] == "0.5"
    assert manifest["slippage_bps"] == "0.0000001"
    assert manifest["strategy_config_hash"] == canonical_hash(canonical_payload)


def test_build_manifest_binds_report_paths_and_smoke_provenance(tmp_path):
    spec = validate_strategy_mapping(valid_payload())
    data_path = tmp_path / "SPY_daily.csv"
    data_path.write_text("deterministic-data\n", encoding="utf-8")
    strategy_config_path = tmp_path / "strategy_config.yaml"
    strategy_config_path.write_text("strategy_name: ema_baseline\n", encoding="utf-8")
    artifact_paths = {
        "summary": tmp_path / "summary.json",
        "equity": tmp_path / "equity.csv",
        "trades": tmp_path / "trades.csv",
    }

    manifest = build_manifest(
        spec,
        data_path,
        "SMOKE_TEST_DATA_ONLY",
        artifact_paths,
        "abc123",
        "SMOKE_TEST_DATA_ONLY",
        strategy_config_path=strategy_config_path,
    )

    assert manifest["artifact_paths"] == {
        name: str(path) for name, path in artifact_paths.items()
    }
    assert manifest["provider"] == "SMOKE_TEST_DATA_ONLY"
    assert manifest["smoke_test_marker"] == "SMOKE_TEST_DATA_ONLY"


def test_bind_artifact_hashes_records_generated_output_evidence(tmp_path):
    artifact_paths = {
        "summary": tmp_path / "summary.json",
        "equity": tmp_path / "equity.csv",
        "trades": tmp_path / "trades.csv",
        "manifest": tmp_path / "run_manifest.json",
        "audit": tmp_path / "audit.json",
        "report_zh": tmp_path / "report_zh.md",
        "strategy_config": tmp_path / "strategy_config.yaml",
    }
    for name in ("summary", "equity", "trades", "report_zh", "strategy_config"):
        artifact_paths[name].write_text(f"{name}\n", encoding="utf-8")

    manifest = bind_artifact_hashes({"provider": "test"}, artifact_paths)

    assert manifest["artifact_paths"] == {
        name: str(path) for name, path in artifact_paths.items()
    }
    assert manifest["artifact_hashes"] == {
        name: sha256_file(artifact_paths[name])
        for name in (
            "summary",
            "equity",
            "trades",
            "report_zh",
            "strategy_config",
        )
    }
    assert manifest["strategy_config_path"] == str(
        artifact_paths["strategy_config"]
    )
    assert manifest["strategy_config_file_hash"] == sha256_file(
        artifact_paths["strategy_config"]
    )


def test_write_manifest_is_sorted_utf8_json_with_trailing_newline(tmp_path):
    path = tmp_path / "run_manifest.json"

    write_manifest(path, {"z": "中文", "a": 1})

    assert path.read_text(encoding="utf-8") == (
        '{\n  "a": 1,\n  "z": "中文"\n}\n'
    )
