"""Focused contract tests for typed, immutable V2 AST validation."""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from tv_quant.contracts.ast_contract import (
    MAX_AST_DEPTH,
    MAX_AST_NODES,
    AstValidationError,
    PredicateExpression,
    ValueExpression,
    node_id,
    validate_ast,
)


def _price() -> dict[str, object]:
    return {"node_type": "price_ref", "field": "close", "unit": "USD"}


def _constant(value: object = "1") -> dict[str, object]:
    return {"node_type": "constant", "value": value, "unit": "USD"}


def _compare() -> dict[str, object]:
    return {
        "node_type": "compare",
        "operator": "gt",
        "left": _price(),
        "right": _constant(),
    }


def _issue(node: object, expected_type: object, path: str):
    with pytest.raises(AstValidationError) as error:
        validate_ast(node, expected_type, path)
    assert isinstance(error.value.issues, tuple)
    assert error.value.issues
    return error.value.issues[0]


def test_entry_exit_and_filter_roots_require_predicates():
    """A value root must never become an entry, exit, or filter condition."""
    for path in ("entry", "exit", "filters[0]"):
        issue = _issue(_price(), PredicateExpression, path)

        assert issue.path == path
        assert "PredicateExpression" in issue.message

    expression = validate_ast(_compare(), PredicateExpression, "entry")
    assert isinstance(expression, PredicateExpression)


def test_bare_indicator_or_constant_root_is_rejected():
    """Bare value nodes cannot satisfy the boolean root contract."""
    indicator = {
        "node_type": "indicator_ref",
        "name": "EMA",
        "parameters": {"period": 50},
        "output": "series",
        "unit": "USD",
    }

    for node in (indicator, _constant()):
        issue = _issue(node, "PredicateExpression", "entry")

        assert issue.path == "entry"
        assert issue.code == "CONFIG_VALIDATION_BLOCKER"


@pytest.mark.parametrize("node_type", ["compare", "cross_above", "cross_below"])
def test_compare_and_cross_operands_require_value_expressions(node_type):
    """A predicate nested as a compare/cross operand is a type-boundary bug."""
    node = {
        "node_type": node_type,
        "left": _compare(),
        "right": _price(),
    }
    if node_type == "compare":
        node["operator"] = "gt"

    issue = _issue(node, PredicateExpression, "entry")

    assert issue.path == "entry.left"
    assert "ValueExpression" in issue.message


def test_mixed_value_predicate_types_are_rejected():
    """Boolean combinators accept predicates only and value validation rejects predicates."""
    issue = _issue(
        {"node_type": "all", "children": [_compare(), _price()]},
        PredicateExpression,
        "entry",
    )
    assert issue.path == "entry.children[1]"
    assert "PredicateExpression" in issue.message

    issue = _issue(_compare(), ValueExpression, "operand")
    assert issue.path == "operand"
    assert "ValueExpression" in issue.message


def test_node_schemas_are_sealed_and_reject_executable_or_dynamic_fields():
    """Unknown fields cannot carry Python, filesystem, or network behavior."""
    for field, value in (
        ("expression", "__import__('os')"),
        ("callable", lambda: None),
        ("path", "C:/secret"),
        ("url", "https://example.invalid"),
    ):
        node = _constant()
        node[field] = value

        issue = _issue(node, ValueExpression, "operand")

        assert issue.path == "operand"
        assert "unknown field" in issue.message


def test_indicator_parameters_reject_dynamic_fields_and_non_string_keys():
    """Indicator parameters cannot hide path/network behavior or non-JSON keys."""
    for parameters in (
        {"path": "C:/secret"},
        {"url": "https://example.invalid"},
        {"callback": lambda: None},
        {1: 50},
    ):
        indicator = {
            "node_type": "indicator_ref",
            "name": "EMA",
            "parameters": parameters,
            "output": "series",
            "unit": "USD",
        }

        issue = _issue(indicator, ValueExpression, "operand")

        assert issue.path.startswith("operand.parameters")


def test_indicator_parameters_reject_compound_dynamic_terms_without_blocking_period():
    """Compound executable/path/network keys are unsafe, while period remains valid."""
    valid = {
        "node_type": "indicator_ref",
        "name": "EMA",
        "parameters": {"period": 50},
        "output": "series",
        "unit": "USD",
    }
    assert isinstance(validate_ast(valid, ValueExpression, "operand"), ValueExpression)

    for key in (
        "file_path",
        "python_code",
        "callback_url",
        "filepath",
        "FILEPath",
        "file.path",
        "file/path",
        "python.code",
        "URLCallback",
        "urls",
        "broker_account",
        "order-id",
        "hostName",
        "my.file_path",
        "account_id",
        "order_type",
        "source_code",
        "callback",
        "myCallback",
        "backup_urls",
        "cache_filepath",
        "primary_accountid",
        "remote_urlcallback",
        "brokeraccount",
        "hostname",
        "ordertype",
        "pythoncode",
        "sourcecode",
        "uricallback",
        "uris",
    ):
        invalid = {**valid, "parameters": {key: "unsafe"}}

        issue = _issue(invalid, ValueExpression, "operand")

        assert issue.path == f"operand.parameters.{key}"
        assert "dynamic/path/network" in issue.message

    for key in (
        "border",
        "profile",
        "classification",
        "borderid",
        "ghostname",
        "resourcecode",
        "myfilepath",
        "filepathcache",
        "filepathology",
    ):
        allowed = {**valid, "parameters": {key: "safe"}}

        assert isinstance(
            validate_ast(allowed, ValueExpression, "operand"), ValueExpression
        )


@pytest.mark.parametrize(
    "parameters",
    [
        {"period": [1, Decimal("1.5")]},
        {"period": (1, "2.5")},
    ],
)
def test_period_parameter_containers_preserve_integer_validation(parameters):
    """A period list or tuple cannot bypass integer-period validation for its items."""
    indicator = {
        "node_type": "indicator_ref",
        "name": "EMA",
        "parameters": parameters,
        "output": "series",
        "unit": "USD",
    }

    issue = _issue(indicator, ValueExpression, "operand")

    assert issue.path.endswith("[1]")
    assert issue.code == "CONFIG_VALIDATION_BLOCKER"


def test_indicator_parameter_numeric_errors_return_ast_validation_issues():
    """Invalid Decimal and integer-period values cannot escape as raw ValueError."""
    for parameters in (
        {"threshold": Decimal("NaN")},
        {"period": Decimal("1.5")},
    ):
        indicator = {
            "node_type": "indicator_ref",
            "name": "EMA",
            "parameters": parameters,
            "output": "series",
            "unit": "USD",
        }

        issue = _issue(indicator, ValueExpression, "operand")

        assert issue.path.startswith("operand.parameters")
        assert issue.code == "CONFIG_VALIDATION_BLOCKER"


def test_values_are_canonical_immutable_and_units_are_explicitly_compatible():
    """Numeric semantics, output shape, and compatible units are part of the AST."""
    canonical = validate_ast(_constant(Decimal("1.00")), ValueExpression, "operand")

    assert canonical.payload["value"] == "1"
    assert canonical.unit == "USD"
    with pytest.raises(TypeError):
        canonical.payload["value"] = "2"
    with pytest.raises(FrozenInstanceError):
        canonical.unit = "ratio"  # type: ignore[misc]

    for value in (1.0, "NaN", "Infinity", "-Infinity"):
        issue = _issue(_constant(value), ValueExpression, "operand")
        assert issue.path == "operand.value"

    incompatible = _compare()
    incompatible["right"] = {
        "node_type": "constant",
        "value": "1",
        "unit": "percentage",
    }
    issue = _issue(incompatible, PredicateExpression, "entry")
    assert issue.path == "entry"
    assert "incompatible units" in issue.message

    compatible = {
        "node_type": "compare",
        "operator": "gte",
        "left": {
            "node_type": "indicator_ref",
            "name": "RSI",
            "parameters": {"period": 14},
            "output": "series",
            "unit": "ratio",
        },
        "right": {"node_type": "constant", "value": "0.5", "unit": "ratio"},
    }
    assert isinstance(
        validate_ast(compatible, PredicateExpression, "filters[0]"),
        PredicateExpression,
    )


@pytest.mark.parametrize(
    ("value", "unit"),
    [
        ("regime:bull", "string"),
        ("00123", "string"),
        ("NaN", "string"),
        ("Infinity", "string"),
        (True, "boolean"),
    ],
)
def test_constant_uses_declared_string_or_boolean_unit_before_value_shape(value, unit):
    """String literals remain unchanged and booleans require the boolean unit."""
    constant = {"node_type": "constant", "value": value, "unit": unit}

    expression = validate_ast(constant, ValueExpression, "operand")
    assert expression.payload["value"] == value
    assert expression.unit == unit

    for operator in ("eq", "neq"):
        predicate = {
            "node_type": "compare",
            "operator": operator,
            "left": constant,
            "right": constant,
        }
        assert isinstance(
            validate_ast(predicate, PredicateExpression, "entry"),
            PredicateExpression,
        )


def test_boolean_unit_rejects_non_boolean_and_string_unit_rejects_boolean():
    """Declared scalar units are exact type declarations, not value guesses."""
    for constant in (
        {"node_type": "constant", "value": 1, "unit": "boolean"},
        {"node_type": "constant", "value": True, "unit": "string"},
    ):
        issue = _issue(constant, ValueExpression, "operand")

        assert issue.path in {"operand.value", "operand.unit"}


@pytest.mark.parametrize("unit", ["string", "boolean"])
@pytest.mark.parametrize("operator", ["gt", "gte", "lt", "lte"])
def test_string_boolean_comparisons_reject_ordering_operators(unit, operator):
    """Non-numeric scalar units have equality semantics only."""
    value = "label" if unit == "string" else True
    constant = {"node_type": "constant", "value": value, "unit": unit}
    predicate = {
        "node_type": "compare",
        "operator": operator,
        "left": constant,
        "right": constant,
    }

    issue = _issue(predicate, PredicateExpression, "entry")

    assert issue.path == "entry"
    assert "eq or neq" in issue.message


def test_cross_rejects_string_series_even_when_units_match():
    """Cross nodes remain available only to comparable numeric series values."""
    indicator = {
        "node_type": "indicator_ref",
        "name": "EMA",
        "parameters": {"period": 20},
        "output": "series",
        "unit": "string",
    }
    cross = {"node_type": "cross_above", "left": indicator, "right": indicator}

    issue = _issue(cross, PredicateExpression, "entry")

    assert issue.path == "entry"
    assert "not comparable" in issue.message


@pytest.mark.parametrize(
    ("unit", "value"),
    [
        ("USD", "10.00"),
        ("percentage", "10.00"),
        ("ratio", "1.00"),
        ("integer-period", 20),
    ],
)
def test_compare_accepts_only_explicit_same_unit_pairs(unit, value):
    """Price, percentage, ratio, and integer-period comparisons require same units."""
    node = {
        "node_type": "compare",
        "operator": "eq",
        "left": {
            "node_type": "indicator_ref",
            "name": "SMA",
            "parameters": {"period": 20},
            "output": "series",
            "unit": unit,
        },
        "right": {"node_type": "constant", "value": value, "unit": unit},
    }

    assert isinstance(
        validate_ast(node, PredicateExpression, "entry"),
        PredicateExpression,
    )


def test_cross_requires_series_and_refs_have_frozen_fields_and_units():
    """Crossing a scalar or relabeling price/volume data changes AST meaning."""
    scalar_cross = {
        "node_type": "cross_above",
        "left": _price(),
        "right": _constant(),
    }
    issue = _issue(scalar_cross, PredicateExpression, "entry")
    assert issue.path == "entry"
    assert "series" in issue.message

    for node in (
        {"node_type": "price_ref", "field": "close", "unit": "shares"},
        {"node_type": "price_ref", "field": "secret", "unit": "USD"},
        {"node_type": "volume_ref", "field": "volume", "unit": "USD"},
        {"node_type": "volume_ref", "field": "close", "unit": "shares"},
    ):
        _issue(node, ValueExpression, "operand")


@pytest.mark.parametrize("node_type", ["compare", "cross_above"])
def test_volume_shares_value_expressions_are_not_comparable(node_type):
    """Volume remains a legal value but shares are outside frozen predicate unit pairs."""
    volume = {"node_type": "volume_ref", "field": "volume", "unit": "shares"}
    volume_indicator = {
        "node_type": "indicator_ref",
        "name": "VOLUME_SMA",
        "parameters": {"period": 20},
        "output": "series",
        "unit": "shares",
    }
    assert isinstance(validate_ast(volume, ValueExpression, "operand"), ValueExpression)

    predicate = {"node_type": node_type, "left": volume, "right": volume_indicator}
    if node_type == "compare":
        predicate["operator"] = "gt"
    issue = _issue(predicate, PredicateExpression, "entry")
    assert issue.path == "entry"
    assert "not comparable" in issue.message


def test_node_id_depth_and_node_count_limits_are_deterministic():
    """Mapping order cannot change IDs, and exact complexity limits are stable."""
    left_order = {"node_type": "constant", "value": "1.00", "unit": "USD"}
    right_order = {"unit": "USD", "value": "1.00", "node_type": "constant"}

    assert node_id(left_order, (7, 2)) == node_id(right_order, (7, 2))
    assert node_id(left_order, (7, 2)) != node_id(left_order, (7, 3))
    assert MAX_AST_DEPTH == 16
    assert MAX_AST_NODES == 128

    preorder = validate_ast(_compare(), PredicateExpression, "entry")
    assert preorder.node_id == "compare@0"
    assert preorder.payload["left"].node_id == "price_ref@1"
    assert preorder.payload["right"].node_id == "constant@2"

    depth_16 = _compare()
    for _ in range(14):
        depth_16 = {"node_type": "not", "child": depth_16}
    assert isinstance(
        validate_ast(depth_16, PredicateExpression, "entry"),
        PredicateExpression,
    )

    depth_17 = {"node_type": "not", "child": depth_16}
    first = _issue(depth_17, PredicateExpression, "entry")
    second = _issue(depth_17, PredicateExpression, "entry")
    assert first == second
    assert first.code == "AST_COMPLEXITY_BLOCKER"
    assert first.path.endswith(".left")
    assert "depth 16" in first.message

    children_128 = [{"node_type": "not", "child": _compare()}]
    children_128.extend(_compare() for _ in range(41))
    nodes_128 = {"node_type": "all", "children": children_128}
    assert isinstance(
        validate_ast(nodes_128, PredicateExpression, "entry"),
        PredicateExpression,
    )

    children_129 = [
        {"node_type": "not", "child": {"node_type": "not", "child": _compare()}}
    ]
    children_129.extend(_compare() for _ in range(41))
    nodes_129 = {"node_type": "all", "children": children_129}
    first = _issue(nodes_129, PredicateExpression, "entry")
    second = _issue(nodes_129, PredicateExpression, "entry")
    assert first == second
    assert first.code == "AST_COMPLEXITY_BLOCKER"
    assert "node count 128" in first.message
    with pytest.raises(FrozenInstanceError):
        first.path = "different"  # type: ignore[misc]
