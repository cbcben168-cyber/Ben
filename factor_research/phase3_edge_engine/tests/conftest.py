from __future__ import annotations

import pytest

from factor_research.phase3_edge_engine.contracts import load_factor_registry, load_strategy_registry
from factor_research.phase3_edge_engine.data import load_and_qualify
from factor_research.phase3_edge_engine.factors import build_factor_events, build_features, compute_factor_matrix
from factor_research.phase3_edge_engine.pipeline import (
    DEFAULT_AUDIT_MANIFEST,
    DEFAULT_DATA,
    FACTOR_REGISTRY,
    STRATEGY_REGISTRY,
)
from factor_research.phase3_edge_engine.simulator import build_strategy_signals, replay_strategies


@pytest.fixture(scope="session")
def phase3_state():
    raw, qualification = load_and_qualify(DEFAULT_DATA, DEFAULT_AUDIT_MANIFEST)
    features = build_features(raw, DEFAULT_DATA.with_name("opend_rehab.csv"))
    matrix = compute_factor_matrix(features)
    events = build_factor_events(features, matrix)
    signals = build_strategy_signals(features, matrix)
    specs = load_strategy_registry(STRATEGY_REGISTRY)
    trades, audit = replay_strategies(features, signals, specs)
    return {
        "raw": raw,
        "qualification": qualification,
        "features": features,
        "matrix": matrix,
        "events": events,
        "signals": signals,
        "trades": trades,
        "audit": audit,
        "factor_specs": load_factor_registry(FACTOR_REGISTRY),
        "strategy_specs": specs,
    }
