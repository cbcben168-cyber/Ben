import json

import pytest

from scripts.recommend_coding_model import main
from tv_quant.model_routing import recommend_model


def test_simple_local_task_uses_luna_low() -> None:
    decision = recommend_model("rename one label in Chart Review")

    assert (decision.model, decision.reasoning_effort) == (
        "gpt-5.6-luna",
        "low",
    )
    assert decision.hard_floor is None


def test_futu_integration_uses_terra_without_claiming_price() -> None:
    decision = recommend_model(
        "debug Futu API integration and add regression coverage",
        ("src/tv_quant/pattern_finder/futu_service.py",),
    )

    assert decision.model == "gpt-5.6-terra"
    assert decision.reasoning_effort == "high"
    assert any("integration" in reason.lower() for reason in decision.reasons)


def test_persistence_migration_forces_sol_xhigh() -> None:
    decision = recommend_model(
        "migrate the SQLite schema and preserve transaction integrity",
        ("src/tv_quant/pattern_finder/persistence/migrations.py",),
    )

    assert (decision.model, decision.reasoning_effort) == (
        "gpt-5.6-sol",
        "xhigh",
    )
    assert decision.hard_floor == "SOL_XHIGH"


def test_empty_task_is_rejected() -> None:
    with pytest.raises(ValueError, match="task_text must be non-empty"):
        recommend_model("   ")


def test_cli_emits_json_for_task_and_paths(capsys) -> None:
    main(
        [
            "--task",
            "debug Futu API integration",
            "--path",
            "src/tv_quant/pattern_finder/futu_service.py",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["model"] == "gpt-5.6-terra"
    assert payload["reasoning_effort"] == "high"
