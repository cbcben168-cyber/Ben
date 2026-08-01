"""Stable public contracts for pipeline integrations."""

from .artifact_contract import (
    ArtifactContract,
    DependencyFingerprint,
    FormalResultContract,
    ProvisionalEvidence,
)
from .capability_registry import CapabilityRegistry
from .confirmation import AuthorizedExecutionContext, ConfirmationGrant, ConfirmationRequest
from .data_plan import DataPlan, DatasetRequirement
from .execution_assumptions import ExecutionAssumptions
from .normalized_ir import NormalizedStrategyIR
from .numeric import canonical_decimal, canonical_integer
from .runner_protocol import RunnerMode, RunnerRequest, RunnerResponse, run_v2
from .schema_contract import (
    AST_NODE_DEFINITIONS,
    ENUMS,
    ROOT_REQUIRED_FIELDS,
    render_json_schema,
    schema_contract_snapshot,
)
from .strategy_v2 import StrategySpecV2
from .status_codes import StatusCodeRegistry
from .template_contract import TemplateLookupKey, TemplateRecord

__all__ = (
    "AST_NODE_DEFINITIONS",
    "ArtifactContract",
    "AuthorizedExecutionContext",
    "CapabilityRegistry",
    "ConfirmationGrant",
    "ConfirmationRequest",
    "DataPlan",
    "DatasetRequirement",
    "DependencyFingerprint",
    "ENUMS",
    "ExecutionAssumptions",
    "FormalResultContract",
    "NormalizedStrategyIR",
    "ProvisionalEvidence",
    "ROOT_REQUIRED_FIELDS",
    "RunnerMode",
    "RunnerRequest",
    "RunnerResponse",
    "StrategySpecV2",
    "StatusCodeRegistry",
    "TemplateLookupKey",
    "TemplateRecord",
    "canonical_decimal",
    "canonical_integer",
    "render_json_schema",
    "run_v2",
    "schema_contract_snapshot",
)
