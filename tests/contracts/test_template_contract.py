"""Contract tests for deterministic read-only template lookup in V2.1."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import os
from pathlib import Path

import pytest

from tv_quant.contracts.template_contract import (
    TemplateEligibility,
    TemplateLookupKey,
    TemplateRecord,
    TemplateRegistry,
    find_latest_eligible,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


def _key(**changes: str) -> TemplateLookupKey:
    values = {
        "strategy_family": "ema_crossover",
        "symbol": "SPY",
        "timeframe": "1d",
        "schema_version": "v2.1",
        "dependency_hash": SHA_A,
    }
    values.update(changes)
    return TemplateLookupKey(**values)


def _record(**changes: object) -> TemplateRecord:
    values: dict[str, object] = {
        "template_id": "ema-spy-1",
        "immutable_version": "1.0.0",
        "strategy_family": "ema_crossover",
        "symbol": "SPY",
        "timeframe": "1d",
        "schema_version": "v2.1",
        "dependency_hash": SHA_A,
        "config_hash": SHA_B,
        "plugin_hash": None,
        "audit_eligibility": "PASS",
        "created_at": "2026-07-27T00:00:00Z",
        "supersedes": None,
        "active_version": True,
        "invalidation_reason": None,
    }
    values.update(changes)
    return TemplateRecord(**values)


def test_registry_path_is_injected(tmp_path: Path) -> None:
    registry_path = tmp_path / "custom" / "registry.json"

    registry = TemplateRegistry(registry_path, ())

    assert registry.registry_path == registry_path
    assert not registry_path.exists()
    with pytest.raises(TypeError):
        TemplateRegistry()  # type: ignore[call-arg]


def test_template_record_contains_immutable_version_and_hashes(tmp_path: Path) -> None:
    record = _record(plugin_hash=SHA_C)
    registry = TemplateRegistry(tmp_path / "registry.json", (record,))

    assert record.immutable_version == "1.0.0"
    assert (record.dependency_hash, record.config_hash, record.plugin_hash) == (
        SHA_A,
        SHA_B,
        SHA_C,
    )
    registry.validate_record(record, _key())
    with pytest.raises(FrozenInstanceError):
        record.config_hash = SHA_D  # type: ignore[misc]
    with pytest.raises(ValueError, match="config_hash"):
        _record(config_hash="")


def test_lookup_uses_key_not_file_mtime(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text("pre-existing registry sentinel", encoding="utf-8")
    older = _record(
        template_id="ema-spy-older",
        immutable_version="1.9.0",
        created_at="2026-07-29T00:00:00Z",
        active_version=False,
    )
    newer = _record(
        template_id="ema-spy-newer",
        immutable_version="1.10.0",
        config_hash=SHA_C,
        created_at="2026-07-27T00:00:00Z",
        active_version=False,
        supersedes=older.template_id,
    )
    config_tie_breaker = _record(
        template_id="ema-spy-config-tie",
        immutable_version="1.10.0",
        config_hash=SHA_D,
        created_at="2026-07-26T00:00:00Z",
        supersedes=older.template_id,
    )
    other_key = _record(
        template_id="ema-qqq-newest",
        immutable_version="9.0.0",
        symbol="QQQ",
        config_hash=SHA_E,
    )
    older_source = tmp_path / "ema-spy-older.json"
    newer_source = tmp_path / "ema-spy-config-tie.json"
    older_source.write_text(older.template_id, encoding="utf-8")
    newer_source.write_text(config_tie_breaker.template_id, encoding="utf-8")
    os.utime(older_source, (2_000_000_000, 2_000_000_000))
    os.utime(newer_source, (1, 1))
    registry = TemplateRegistry(
        registry_path,
        (other_key, newer, older, config_tie_breaker),
    )

    os.utime(registry_path, (1, 1))
    first = registry.lookup_latest(_key())
    os.utime(registry_path, (2_000_000_000, 2_000_000_000))
    second = registry.lookup_latest(_key())

    assert first is config_tie_breaker
    assert second is config_tie_breaker


def test_only_one_active_version_exists_per_key(tmp_path: Path) -> None:
    first = _record()
    second = _record(
        template_id="ema-spy-2",
        immutable_version="2.0.0",
        config_hash=SHA_C,
        supersedes=first.template_id,
    )

    with pytest.raises(ValueError, match="active"):
        TemplateRegistry(tmp_path / "registry.json", (first, second))


def test_supersedes_points_to_same_key_older_record(tmp_path: Path) -> None:
    older = _record(active_version=False)
    newer = _record(
        template_id="ema-spy-2",
        immutable_version="2.0.0",
        config_hash=SHA_C,
        supersedes=older.template_id,
    )

    registry = TemplateRegistry(tmp_path / "valid.json", (newer, older))
    assert registry.lookup_latest(_key()) is newer

    wrong_key = _record(
        template_id="ema-qqq-1",
        symbol="QQQ",
        active_version=False,
    )
    cross_key = _record(
        template_id="ema-spy-2",
        immutable_version="2.0.0",
        config_hash=SHA_C,
        supersedes=wrong_key.template_id,
    )
    with pytest.raises(ValueError, match="same key"):
        TemplateRegistry(tmp_path / "invalid.json", (wrong_key, cross_key))


def test_supersedes_cycles_and_non_monotonic_versions_are_rejected(
    tmp_path: Path,
) -> None:
    cycle_one = _record(
        template_id="cycle-1",
        immutable_version="1.0.0",
        supersedes="cycle-2",
        active_version=False,
    )
    cycle_two = _record(
        template_id="cycle-2",
        immutable_version="2.0.0",
        config_hash=SHA_C,
        supersedes="cycle-1",
    )
    with pytest.raises(ValueError, match="cycle"):
        TemplateRegistry(tmp_path / "cycle.json", (cycle_one, cycle_two))

    newer = _record(
        template_id="newer",
        immutable_version="2.0.0",
        active_version=False,
    )
    non_monotonic = _record(
        template_id="non-monotonic",
        immutable_version="1.0.0",
        config_hash=SHA_C,
        supersedes=newer.template_id,
    )
    with pytest.raises(ValueError, match="older"):
        TemplateRegistry(
            tmp_path / "non-monotonic.json",
            (newer, non_monotonic),
        )


def test_invalidated_record_cannot_be_active(tmp_path: Path) -> None:
    invalidated = _record(invalidation_reason="audit evidence withdrawn")

    with pytest.raises(ValueError, match="invalidated"):
        TemplateRegistry(tmp_path / "registry.json", (invalidated,))


def test_blocker_smoke_and_invalidated_records_are_ineligible(
    tmp_path: Path,
) -> None:
    passed = _record(active_version=False)
    conditional = _record(
        template_id="conditional",
        immutable_version="1.1.0",
        config_hash=SHA_C,
        audit_eligibility="CONDITIONAL_PASS",
        active_version=False,
        supersedes=passed.template_id,
    )
    blocker = _record(
        template_id="blocker",
        immutable_version="2.0.0",
        config_hash=SHA_D,
        audit_eligibility="STRATEGY_CAPABILITY_BLOCKER",
        active_version=False,
        supersedes=conditional.template_id,
    )
    smoke = _record(
        template_id="smoke",
        immutable_version="3.0.0",
        config_hash=SHA_E,
        audit_eligibility="SMOKE_TEST_DATA_ONLY",
        active_version=False,
        supersedes=blocker.template_id,
    )
    invalidated = _record(
        template_id="invalidated",
        immutable_version="4.0.0",
        config_hash="f" * 64,
        invalidation_reason="audit superseded",
        active_version=False,
        supersedes=smoke.template_id,
    )
    registry = TemplateRegistry(
        tmp_path / "registry.json",
        (invalidated, smoke, blocker, conditional, passed),
    )

    eligibility = find_latest_eligible(registry, _key())

    assert eligibility == TemplateEligibility(
        record=conditional,
        eligible=True,
        reason=None,
    )


def test_v21_formal_result_cannot_be_saved(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    registry = TemplateRegistry(registry_path, ())

    assert registry.save(_record()) == "NOT_IMPLEMENTED"
    assert registry.lookup_latest(_key()) is None
    assert not registry_path.exists()
