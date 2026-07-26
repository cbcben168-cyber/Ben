from collections.abc import Mapping

import pytest

from tv_quant.contracts.schema_contract import (
    AST_NODE_DEFINITIONS,
    ENUMS,
    ROOT_REQUIRED_FIELDS,
    render_json_schema,
    schema_contract_snapshot,
)


def test_python_contract_definitions_are_unique_source_of_truth():
    """A drift between the Python definitions and rendered schema is a contract bug."""
    snapshot = schema_contract_snapshot()
    schema = render_json_schema()

    assert isinstance(ROOT_REQUIRED_FIELDS, tuple)
    assert ROOT_REQUIRED_FIELDS == (
        "schema_version",
        "strategy_id",
        "strategy_family",
        "strategy_name",
        "symbol",
        "market",
        "timeframe",
        "session",
        "backtest_range",
        "initial_capital",
        "entry",
        "exit",
        "filters",
        "position_sizing",
        "stop",
        "target",
        "fill_timing",
        "data",
        "benchmark",
        "plugin",
        "optimization_allowed",
        "report_language",
    )
    assert isinstance(ENUMS, Mapping)
    assert isinstance(AST_NODE_DEFINITIONS, Mapping)
    assert schema["required"] == list(ROOT_REQUIRED_FIELDS)
    assert schema["properties"]["schema_version"]["enum"] == list(
        ENUMS["schema_version"]
    )
    assert schema["$defs"] == snapshot["ast_node_definitions"]

    with pytest.raises(TypeError):
        ENUMS["schema_version"] = ("v2.2",)
    with pytest.raises(TypeError):
        AST_NODE_DEFINITIONS["constant"] = {}
