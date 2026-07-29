"""Behavior tests for the local V2.1 runner gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


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
            "cost_profile": "cost.bps.v1",
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
def evidence_root(tmp_path: Path) -> Path:
    root = tmp_path / "evidence"
    root.mkdir()
    return root


def _runner():
    from tv_quant.contracts import runner_protocol

    return runner_protocol


def _request(config_path: Path, mode, evidence_root: Path, **changes: object):
    runner = _runner()
    values: dict[str, object] = {
        "config_path": config_path,
        "mode": mode,
        "evidence_root": evidence_root,
    }
    values.update(changes)
    return runner.RunnerRequest(**values)


def _prepare(config_path: Path, evidence_root: Path):
    runner = _runner()
    response = runner.run_v2(
        _request(config_path, runner.RunnerMode.PREPARE_CONFIRMATION, evidence_root)
    )
    request_path = evidence_root / response.run_id / "confirmation-request.json"
    return response, request_path


def _approval_path(request_path: Path) -> Path:
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    path = request_path.with_name("approval-record.json")
    path.write_text(
        json.dumps(
            {
                "approval_id": "approval-task14",
                "confirmation_request_id": request_payload[
                    "confirmation_request_id"
                ],
                "decision": "CONFIRMED_EXECUTE",
                "recorded_at_utc": request_payload["generated_at"],
                "actor": "dialogue.user",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _grant(config_path: Path, evidence_root: Path):
    runner = _runner()
    prepared, request_path = _prepare(config_path, evidence_root)
    approval_path = _approval_path(request_path)
    granted = runner.run_v2(
        _request(
            config_path,
            runner.RunnerMode.GRANT_CONFIRMATION,
            evidence_root,
            confirmation_request_path=request_path,
            approval_record_path=approval_path,
        )
    )
    return prepared, request_path, approval_path, granted


def test_validate_mode_returns_compact_success_json(
    config_path: Path,
    evidence_root: Path,
) -> None:
    """Calling a provider or returning padded JSON would break validate's local contract."""
    runner = _runner()

    response = runner.run_v2(
        _request(config_path, runner.RunnerMode.VALIDATE, evidence_root)
    )
    payload = json.loads(response.to_json())

    assert response.status == "SUCCESS"
    assert response.blocker_code is None
    assert response.confirmation_token is None
    assert response.formal_result_published is False
    assert response.to_json() == json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def test_prepare_confirmation_writes_only_provisional_evidence(
    config_path: Path,
    evidence_root: Path,
) -> None:
    """A formal artifact or extra file during prepare would cross the publication gate."""
    response, request_path = _prepare(config_path, evidence_root)
    run_directory = request_path.parent

    assert response.status == "SUCCESS"
    assert response.confirmation_request_id
    assert response.next_action == "AWAIT_USER_CONFIRMATION"
    assert response.confirmation_token is None
    assert response.formal_result_published is False
    assert sorted(path.name for path in run_directory.iterdir()) == [
        "confirmation-request.json",
        "data-plan.json",
        "normalized-ir.json",
    ]
    assert response.run_directory is None
    assert response.audit_status is None
    assert response.report_summary_path is None


def test_grant_confirmation_returns_token_once(
    config_path: Path,
    evidence_root: Path,
) -> None:
    """Reissuing a plaintext token from persisted state would violate one-time handoff."""
    runner = _runner()
    _, request_path, approval_path, first = _grant(config_path, evidence_root)
    second = runner.run_v2(
        _request(
            config_path,
            runner.RunnerMode.GRANT_CONFIRMATION,
            evidence_root,
            confirmation_request_path=request_path,
            approval_record_path=approval_path,
        )
    )

    assert first.status == "SUCCESS"
    assert isinstance(first.confirmation_token, str)
    assert first.confirmation_token
    assert second.status == "BLOCKED"
    assert second.confirmation_token is None
    persisted = request_path.with_name("confirmation-state.json").read_text(
        encoding="utf-8"
    )
    assert first.confirmation_token not in persisted


def test_non_grant_modes_never_return_plaintext_token(
    config_path: Path,
    evidence_root: Path,
) -> None:
    """Adding token output to validate, prepare, or execute errors would leak authority."""
    runner = _runner()
    validated = runner.run_v2(
        _request(config_path, runner.RunnerMode.VALIDATE, evidence_root)
    )
    prepared, request_path = _prepare(config_path, evidence_root)
    missing = runner.run_v2(
        _request(
            config_path,
            runner.RunnerMode.EXECUTE,
            evidence_root,
            confirmation_request_path=request_path,
        )
    )

    tokens = (
        validated.confirmation_token,
        prepared.confirmation_token,
        missing.confirmation_token,
    )
    assert tokens == (
        None,
        None,
        None,
    )


def test_execute_without_token_returns_confirmation_required(
    config_path: Path,
    evidence_root: Path,
) -> None:
    """Dispatching without explicit authority would bypass the confirmation gate."""
    runner = _runner()
    _, request_path = _prepare(config_path, evidence_root)

    response = runner.run_v2(
        _request(
            config_path,
            runner.RunnerMode.EXECUTE,
            evidence_root,
            confirmation_request_path=request_path,
        )
    )

    assert response.status == "BLOCKED"
    assert response.blocker_code == "CONFIRMATION_REQUIRED"
    assert response.confirmation_token is None
    assert response.formal_result_published is False


def test_execute_with_invalid_token_returns_confirmation_invalid(
    config_path: Path,
    evidence_root: Path,
) -> None:
    """Accepting a wrong token would let an unbound caller consume the grant."""
    runner = _runner()
    _, request_path, _, _ = _grant(config_path, evidence_root)

    response = runner.run_v2(
        _request(
            config_path,
            runner.RunnerMode.EXECUTE,
            evidence_root,
            confirmation_request_path=request_path,
            confirmation_token="wrong-token",
        )
    )

    assert response.status == "BLOCKED"
    assert response.blocker_code == "CONFIRMATION_INVALID"
    assert response.confirmation_token is None


def test_execute_with_valid_token_consumes_once_and_returns_not_implemented(
    config_path: Path,
    evidence_root: Path,
) -> None:
    """A valid token must be consumed before the V2.1 engine blocker is returned."""
    runner = _runner()
    _, request_path, _, granted = _grant(config_path, evidence_root)
    token = granted.confirmation_token
    assert token is not None
    execute_request = _request(
        config_path,
        runner.RunnerMode.EXECUTE,
        evidence_root,
        confirmation_request_path=request_path,
        confirmation_token=token,
    )

    first = runner.run_v2(execute_request)
    second = runner.run_v2(execute_request)

    assert first.status == "NOT_IMPLEMENTED"
    assert first.blocker_code == "EXECUTION_CAPABILITY_NOT_IMPLEMENTED"
    assert first.confirmation_token is None
    assert first.formal_result_published is False
    assert second.status == "BLOCKED"
    assert second.blocker_code == "CONFIRMATION_ALREADY_USED"
    assert second.confirmation_token is None


def test_runner_response_contains_required_short_json_fields() -> None:
    """Renaming, reordering, or expanding the protocol payload would break consumers."""
    runner = _runner()
    response = runner.RunnerResponse(
        protocol_version="v2.1",
        status="BLOCKED",
        blocker_code="CONFIRMATION_REQUIRED",
        run_id="run-abc",
        confirmation_request_id=None,
        confirmation_token=None,
        run_directory=None,
        audit_status=None,
        formal_result_published=False,
        report_summary_path=None,
        next_action="AWAIT_USER_CONFIRMATION",
    )

    assert response.to_json() == (
        '{"protocol_version":"v2.1","status":"BLOCKED",'
        '"blocker_code":"CONFIRMATION_REQUIRED","run_id":"run-abc",'
        '"confirmation_request_id":null,"confirmation_token":null,'
        '"run_directory":null,"audit_status":null,'
        '"formal_result_published":false,"report_summary_path":null,'
        '"next_action":"AWAIT_USER_CONFIRMATION"}'
    )


def test_runner_does_not_call_pipeline_backtest_or_provider(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
    evidence_root: Path,
) -> None:
    """Every mode must stop at the local gate even when legacy execution would crash."""
    import tv_quant.downloader as downloader
    import tv_quant.futu_downloader as futu_downloader
    import tv_quant.pipeline_cli as pipeline_cli
    import tv_quant.research_pipeline as research_pipeline
    import tv_quant.strategy as strategy

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("runner crossed the V2.1 local gate")

    monkeypatch.setattr(research_pipeline, "run_pipeline", forbidden)
    monkeypatch.setattr(strategy, "run_backtest", forbidden)
    monkeypatch.setattr(pipeline_cli, "_refresh_data", forbidden)
    monkeypatch.setattr(downloader, "download_daily", forbidden)
    monkeypatch.setattr(futu_downloader, "download_futu_daily", forbidden)

    runner = _runner()
    validated = runner.run_v2(
        _request(config_path, runner.RunnerMode.VALIDATE, evidence_root)
    )
    prepared, request_path = _prepare(config_path, evidence_root)
    approval_path = _approval_path(request_path)
    granted = runner.run_v2(
        _request(
            config_path,
            runner.RunnerMode.GRANT_CONFIRMATION,
            evidence_root,
            confirmation_request_path=request_path,
            approval_record_path=approval_path,
        )
    )
    executed = runner.run_v2(
        _request(
            config_path,
            runner.RunnerMode.EXECUTE,
            evidence_root,
            confirmation_request_path=request_path,
            confirmation_token=granted.confirmation_token,
        )
    )

    assert [validated.status, prepared.status, granted.status, executed.status] == [
        "SUCCESS",
        "SUCCESS",
        "SUCCESS",
        "NOT_IMPLEMENTED",
    ]
