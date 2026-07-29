"""Behavior tests for the explicit V2 CLI confirmation gate."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tv_quant import pipeline_cli
from tv_quant.contracts import runner_protocol
from tv_quant.research_pipeline import PipelineOptions


def _strategy_mapping() -> dict[str, object]:
    fast = {
        "node_type": "indicator_ref",
        "name": "EMA",
        "parameters": {"period": 50},
        "output": "series",
        "unit": "USD",
    }
    slow = {
        "node_type": "indicator_ref",
        "name": "EMA",
        "parameters": {"period": 200},
        "output": "series",
        "unit": "USD",
    }
    return {
        "schema_version": "v2.1",
        "strategy_id": "ema-cross-spy",
        "strategy_family": "ema_crossover",
        "strategy_name": "SPY EMA crossover",
        "symbol": "SPY",
        "market": "US_EQUITY",
        "timeframe": "1d",
        "session": {
            "timezone": "America/New_York",
            "regular_hours_only": True,
            "calendar_id": "XNYS",
        },
        "backtest_range": {"start": "2024-01-02", "end": "2024-12-31"},
        "initial_capital": {"amount": 100000, "currency": "USD"},
        "entry": {"node_type": "cross_above", "left": fast, "right": slow},
        "exit": {"node_type": "cross_below", "left": fast, "right": slow},
        "filters": [],
        "position_sizing": {"type": "full_capital"},
        "stop": {"enabled": False},
        "target": {"enabled": False},
        "fill_timing": "next_bar_open",
        "data": {
            "source": "validated_local_cache_first",
            "legacy_costs": {
                "commission_bps": "5",
                "slippage_bps": "5",
            },
        },
        "benchmark": {"type": "buy_and_hold", "symbol": "same_as_strategy"},
        "plugin": None,
        "optimization_allowed": False,
        "report_language": "zh-CN",
    }


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "strategy-v2.yaml"
    path.write_text(
        json.dumps(_strategy_mapping(), sort_keys=True),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def evidence_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    trusted_repository = tmp_path / "trusted-repository"
    root = trusted_repository / "reports" / "v2-runner-evidence"
    root.mkdir(parents=True)
    monkeypatch.setattr(
        runner_protocol,
        "_TRUSTED_REPOSITORY_ROOT",
        trusted_repository.resolve(),
        raising=False,
    )
    return root


def _read_one_response(stdout: str) -> dict[str, object]:
    assert stdout.endswith("\n")
    assert len(stdout.splitlines()) == 1
    payload = json.loads(stdout)
    assert isinstance(payload, dict)
    return payload


def _prepare(
    config_path: Path,
    evidence_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> tuple[dict[str, object], Path]:
    exit_code = pipeline_cli.main_v2(
        [
            "prepare-confirmation",
            "--config",
            str(config_path),
            "--evidence-root",
            str(evidence_root),
        ]
    )
    captured = capsys.readouterr()
    payload = _read_one_response(captured.out)
    assert captured.err == ""
    assert exit_code == 0
    assert payload["status"] == "SUCCESS"
    run_id = payload["run_id"]
    assert isinstance(run_id, str)
    return payload, evidence_root / run_id / "confirmation-request.json"


def _approval_path(request_path: Path) -> Path:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    path = request_path.with_name("approval-record.json")
    path.write_text(
        json.dumps(
            {
                "approval_id": "approval-task15",
                "confirmation_request_id": request["confirmation_request_id"],
                "decision": "CONFIRMED_EXECUTE",
                "recorded_at_utc": request["generated_at"],
                "actor": "dialogue.user",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _grant(
    config_path: Path,
    evidence_root: Path,
    request_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> tuple[dict[str, object], str, str]:
    approval_path = _approval_path(request_path)
    exit_code = pipeline_cli.main_v2(
        [
            "grant-confirmation",
            "--config",
            str(config_path),
            "--request",
            str(request_path),
            "--approval-record",
            str(approval_path),
            "--evidence-root",
            str(evidence_root),
        ]
    )
    captured = capsys.readouterr()
    payload = _read_one_response(captured.out)
    token = payload["confirmation_token"]
    assert exit_code == 0
    assert captured.err == ""
    assert payload["status"] == "SUCCESS"
    assert isinstance(token, str)
    assert token
    return payload, token, captured.out


def test_legacy_pipeline_cli_flags_remain_compatible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Routing support must not reinterpret or drop any Phase 1 flag."""
    config_path = tmp_path / "legacy.yaml"
    run_directory = tmp_path / "existing-run"
    captured_call: dict[str, object] = {}

    def fake_run_pipeline(path, options, refresh_data):
        captured_call.update(
            path=path,
            options=options,
            refresh_data=refresh_data,
        )
        return SimpleNamespace(
            status="CONDITIONAL_PASS",
            run_directory=run_directory,
        )

    monkeypatch.setattr(pipeline_cli, "run_pipeline", fake_run_pipeline)

    exit_code = pipeline_cli.main(
        [
            "--strategy-config",
            str(config_path),
            "--data-root",
            str(tmp_path / "data"),
            "--report-root",
            str(tmp_path / "reports"),
            "--run-directory",
            str(run_directory),
            "--audit-only",
            "--skip-data-refresh",
            "--smoke-test-data",
        ]
    )

    assert exit_code == 0
    assert captured_call == {
        "path": config_path,
        "options": PipelineOptions(
            data_root=tmp_path / "data",
            report_root=tmp_path / "reports",
            run_directory=run_directory,
            audit_only=True,
            skip_data_refresh=True,
            allow_smoke_test_data=True,
        ),
        "refresh_data": None,
    }
    assert capsys.readouterr().out == (
        "status=CONDITIONAL_PASS\n"
        f"report_directory={run_directory}\n"
    )


def test_v2_validate_command_emits_json_only(
    config_path: Path,
    evidence_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing v2 dispatch or non-JSON stdout would break the public namespace."""
    exit_code = pipeline_cli.main(
        ["v2", "validate", "--config", str(config_path)]
    )

    captured = capsys.readouterr()
    payload = _read_one_response(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert payload["status"] == "SUCCESS"
    assert payload["blocker_code"] is None
    assert payload["confirmation_token"] is None
    assert payload["formal_result_published"] is False


def test_v2_prepare_confirmation_and_grant_confirmation(
    config_path: Path,
    evidence_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Wrong command-to-mode wiring would prevent the typed confirmation handoff."""
    prepared, request_path = _prepare(config_path, evidence_root, capsys)
    granted, _token, _stdout = _grant(
        config_path,
        evidence_root,
        request_path,
        capsys,
    )

    assert request_path.is_file()
    assert prepared["next_action"] == "AWAIT_USER_CONFIRMATION"
    assert prepared["confirmation_token"] is None
    assert granted["confirmation_request_id"] == prepared[
        "confirmation_request_id"
    ]
    assert granted["next_action"] == "EXECUTE_WITH_CONFIRMATION_TOKEN"


def test_v2_execute_without_token_has_nonzero_exit(
    config_path: Path,
    evidence_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Making the token flag optional would expose an unauthorised execute request."""
    _prepared, request_path = _prepare(config_path, evidence_root, capsys)

    with pytest.raises(SystemExit) as error:
        pipeline_cli.main_v2(
            [
                "execute",
                "--config",
                str(config_path),
                "--request",
                str(request_path),
                "--evidence-root",
                str(evidence_root),
            ]
        )

    captured = capsys.readouterr()
    assert error.value.code == 2
    assert captured.out == ""
    assert "--confirmation-token" in captured.err

    with pytest.raises(SystemExit) as empty_error:
        pipeline_cli.main_v2(
            [
                "execute",
                "--config",
                str(config_path),
                "--confirmation-token",
                "",
                "--request",
                str(request_path),
                "--evidence-root",
                str(evidence_root),
            ]
        )

    empty_captured = capsys.readouterr()
    assert empty_error.value.code == 2
    assert empty_captured.out == ""
    assert "--confirmation-token" in empty_captured.err


def test_v2_execute_with_mismatched_token_has_nonzero_exit(
    config_path: Path,
    evidence_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Accepting an unbound token would bypass Task 14's grant validation."""
    _prepared, request_path = _prepare(config_path, evidence_root, capsys)
    _grant(config_path, evidence_root, request_path, capsys)
    mismatched_token = "mismatched-token"

    exit_code = pipeline_cli.main_v2(
        [
            "execute",
            "--config",
            str(config_path),
            "--confirmation-token",
            mismatched_token,
            "--request",
            str(request_path),
            "--evidence-root",
            str(evidence_root),
        ]
    )

    captured = capsys.readouterr()
    payload = _read_one_response(captured.out)
    assert exit_code == 3
    assert payload["status"] == "BLOCKED"
    assert payload["blocker_code"] == "CONFIRMATION_INVALID"
    assert payload["confirmation_token"] is None
    assert mismatched_token not in captured.out
    assert mismatched_token not in captured.err


def test_v2_execute_with_valid_token_returns_exit_5_not_implemented(
    config_path: Path,
    evidence_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Returning success after the gate would falsely claim a V2.1 engine exists."""
    _prepared, request_path = _prepare(config_path, evidence_root, capsys)
    _granted, token, _stdout = _grant(
        config_path,
        evidence_root,
        request_path,
        capsys,
    )

    exit_code = pipeline_cli.main_v2(
        [
            "execute",
            "--config",
            str(config_path),
            "--confirmation-token",
            token,
            "--request",
            str(request_path),
            "--evidence-root",
            str(evidence_root),
        ]
    )

    captured = capsys.readouterr()
    payload = _read_one_response(captured.out)
    assert exit_code == 5
    assert payload["status"] == "NOT_IMPLEMENTED"
    assert payload["blocker_code"] == "EXECUTION_CAPABILITY_NOT_IMPLEMENTED"
    assert payload["confirmation_token"] is None
    assert payload["formal_result_published"] is False
    assert token not in captured.out
    assert token not in captured.err


def test_v2_stdout_has_one_json_object_and_diagnostics_are_stderr(
    config_path: Path,
    evidence_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A blocker diagnostic on stdout would corrupt the machine-readable response."""
    _prepared, request_path = _prepare(config_path, evidence_root, capsys)
    unissued_token = "not-issued"

    exit_code = pipeline_cli.main_v2(
        [
            "execute",
            "--config",
            str(config_path),
            "--confirmation-token",
            unissued_token,
            "--request",
            str(request_path),
            "--evidence-root",
            str(evidence_root),
        ]
    )

    captured = capsys.readouterr()
    payload = _read_one_response(captured.out)
    assert exit_code == 3
    assert payload["status"] == "BLOCKED"
    assert payload["blocker_code"] == "CONFIRMATION_INVALID"
    assert "status=BLOCKED" in captured.err
    assert "blocker_code=CONFIRMATION_INVALID" in captured.err
    assert unissued_token not in captured.out
    assert unissued_token not in captured.err


def test_v2_command_never_calls_legacy_run_pipeline_or_refresh(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Any legacy dispatch from v2 would cross the frozen local-only gate."""

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("V2 CLI crossed into the legacy pipeline")

    monkeypatch.setattr(pipeline_cli, "run_pipeline", forbidden)
    monkeypatch.setattr(pipeline_cli, "_refresh_data", forbidden)

    exit_code = pipeline_cli.main_v2(
        ["validate", "--config", str(config_path)]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert _read_one_response(captured.out)["status"] == "SUCCESS"
    assert captured.err == ""


def test_grant_confirmation_stdout_delivers_token_once_and_no_file_contains_plaintext(
    config_path: Path,
    evidence_root: Path,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Duplicating or persisting the plaintext token would leak execute authority."""
    _prepared, request_path = _prepare(config_path, evidence_root, capsys)
    _granted, token, stdout = _grant(
        config_path,
        evidence_root,
        request_path,
        capsys,
    )

    assert stdout.count(token) == 1
    assert all(
        token not in path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*")
        if path.is_file()
    )

    approval_path = request_path.with_name("approval-record.json")
    repeated_exit_code = pipeline_cli.main_v2(
        [
            "grant-confirmation",
            "--config",
            str(config_path),
            "--request",
            str(request_path),
            "--approval-record",
            str(approval_path),
            "--evidence-root",
            str(evidence_root),
        ]
    )

    repeated = capsys.readouterr()
    repeated_payload = _read_one_response(repeated.out)
    assert repeated_exit_code == 3
    assert repeated_payload["status"] == "BLOCKED"
    assert repeated_payload["confirmation_token"] is None
    assert token not in repeated.out
    assert token not in repeated.err
