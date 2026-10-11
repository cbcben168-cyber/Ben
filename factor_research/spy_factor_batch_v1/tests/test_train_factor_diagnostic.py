import hashlib
import json

import pytest

from factor_research.spy_factor_batch_v1 import train_factor_diagnostic as diagnostic
from factor_research.spy_factor_batch_v1.train_ema_supplement_audit import sha256_file
from quant_workflow.factor_research.progress_dashboard.ingest import BATCH_FACTORS


def _synthetic_events():
    events = []
    for day_index, day in enumerate(("2025-10-01", "2025-10-02", "2025-10-03")):
        for position in range(12):
            minute = 35 + position * 5
            event = {
                "signal_id": f"{day_index}-{position}",
                "signal_time_et": f"{day}T{9 + minute // 60:02d}:{minute % 60:02d}:00",
                "r3": (position - 5) / 10000,
                "r6": (position - 4) / 10000,
                "r12": (position - 3) / 10000,
            }
            for factor_index, (_, prefix, _) in enumerate(BATCH_FACTORS):
                event[prefix + "_state"] = "PASS" if (position + factor_index) % 3 == 0 else "FAIL"
            events.append(event)
    return events


def _write_verified_fixture(tmp_path):
    payload = {"event_type": "RUN_END", "status": "INCOMPLETE"}
    raw = (
        "2026/10/11 11:00:00 (北京),INFO,列印日誌,FUTU_FACTOR_BATCH_V1|"
        + json.dumps(payload, separators=(",", ":"))
        + "\n"
    ).encode()
    runlog = tmp_path / "RunLog.csv"
    runlog.write_bytes(raw)
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    summary = {
        "status": "SUPPORTED",
        "raw_run_status_preserved": "INCOMPLETE",
        "raw_run_sha256": hashlib.sha256(raw).hexdigest(),
    }
    summary_path = audit_dir / "audit_summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    manifest = {
        "raw_run_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_run_status_preserved": "INCOMPLETE",
        "dashboard_validation_upgrade": "PROHIBITED",
        "edge_claim": "PROHIBITED",
        "artifacts": {
            "audit_summary.json": {
                "sha256": sha256_file(summary_path),
                "bytes": summary_path.stat().st_size,
            }
        },
    }
    manifest_path = audit_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return runlog, audit_dir, raw, sha256_file(manifest_path)


def test_verify_inputs_checks_raw_and_every_audit_artifact(tmp_path):
    runlog, audit_dir, raw, manifest_sha = _write_verified_fixture(tmp_path)

    verified_raw, events, evidence = diagnostic.verify_inputs(
        runlog,
        audit_dir,
        expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
        expected_manifest_sha256=manifest_sha,
    )
    assert verified_raw == raw
    assert events[0]["status"] == "INCOMPLETE"
    assert evidence["summary"]["status"] == "SUPPORTED"

    (audit_dir / "audit_summary.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="AUDIT_ARTIFACT_SHA256_MISMATCH"):
        diagnostic.verify_inputs(
            runlog,
            audit_dir,
            expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
            expected_manifest_sha256=manifest_sha,
        )


def test_verify_inputs_fails_closed_on_wrong_raw_sha(tmp_path):
    runlog, audit_dir, _, manifest_sha = _write_verified_fixture(tmp_path)

    with pytest.raises(ValueError, match="RUNLOG_SHA256_MISMATCH"):
        diagnostic.verify_inputs(
            runlog,
            audit_dir,
            expected_raw_sha256="0" * 64,
            expected_manifest_sha256=manifest_sha,
        )


def test_analysis_covers_six_factors_three_windows_all_phases_and_pairs():
    events = _synthetic_events()

    first = diagnostic.analyze_factor_events(events, seed_key="TEST", bootstrap_replicates=50)
    second = diagnostic.analyze_factor_events(events, seed_key="TEST", bootstrap_replicates=50)

    assert first == second
    assert len(first["summary_rows"]) == 18
    assert len(first["factor_decisions"]) == 6
    assert len(first["phase_rows"]) == 6 * (3 + 6 + 12)
    assert len(first["redundancy_rows"]) == 15
    assert {row["horizon_minutes"] for row in first["summary_rows"]} == {15, 30, 60}


def test_build_factor_inputs_rejects_bad_state():
    events = _synthetic_events()
    events[0]["f001_state"] = "UNKNOWN"

    with pytest.raises(ValueError, match="INVALID_FACTOR_STATE"):
        diagnostic.build_factor_inputs(events)


def test_written_report_preserves_research_boundaries(tmp_path):
    result = diagnostic.analyze_factor_events(
        _synthetic_events(), seed_key="TEST", bootstrap_replicates=20
    )
    diagnostic.write_outputs(
        tmp_path,
        result,
        raw_sha256="a" * 64,
        audit_manifest_sha256="b" * 64,
        script_path=diagnostic.Path(diagnostic.__file__),
    )

    report = (tmp_path / "REPORT_CN.md").read_text(encoding="utf-8")
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert "原始运行未正式验收" in report
    assert "Validation/OOS：未运行" in report
    assert "可执行策略" in report
    assert manifest["boundaries"]["raw_run_status"] == "INCOMPLETE"
    assert manifest["boundaries"]["dashboard_gate_upgrade"] == "PROHIBITED"
