from pathlib import Path
from datetime import date, datetime, timezone
from decimal import Decimal
import json

from streamlit.testing.v1 import AppTest

from tv_quant.pattern_finder.universe_foundation import (
    ClassificationResult,
    Decision,
    EvidenceProvenance,
    EvidenceReference,
    LiquidityEvidence,
    ListingHistoryEvidence,
    NormalizedPrerequisiteDecision,
    ProfileRegistry,
    RawIndustryEvidence,
    SecurityEvaluationPrerequisites,
    UniverseSecurityEvidence,
    core_v1,
)
from tv_quant.pattern_finder.universe_foundation.ui_read_model import (
    EvaluationUiState,
    build_evaluation_ui_state,
)


ROOT = Path(__file__).resolve().parents[2]


def _visible_text(app: AppTest) -> str:
    element_types = (
        "title",
        "header",
        "subheader",
        "caption",
        "markdown",
        "info",
        "success",
        "warning",
        "error",
    )
    return "\n".join(
        str(element.value)
        for element_type in element_types
        for element in app.get(element_type)
    )


def _registry_containing_only_draft_core_v1(tmp_path) -> ProfileRegistry:
    registry = ProfileRegistry(tmp_path)
    registry.bootstrap(core_v1())
    published_path = tmp_path / "published.jsonl"
    payload = json.loads(published_path.read_text(encoding="utf-8"))
    payload["record_state"] = "DRAFT"
    published_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return registry


def _evaluation_state(*, identity: Decision) -> EvaluationUiState:
    reference = EvidenceReference("FUTU", "futu://screening/US.AAPL", "a" * 64)
    provenance = EvidenceProvenance(
        provider="FUTU",
        provider_version="futu-api/9.4",
        source_version="opend/9.4",
        schema_version="futu-screening/v2",
        observed_at_utc=datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc),
        references=(reference,),
    )
    evidence = UniverseSecurityEvidence(
        schema_version="universe-security-evidence/v1",
        stock_id="1001",
        futu_code="US.AAPL",
        symbol="AAPL",
        name="Apple Inc.",
        exchange_raw="NASDAQ",
        security_type_raw="STOCK",
        delisting=None,
        suspension=None,
        security_status_raw=None,
        price_usd=Decimal("5.00"),
        market_cap_usd=Decimal("1000000000.00"),
        provenance=provenance,
        raw_industry=RawIndustryEvidence("Technology", provenance),
        raw_plates=(),
        classification_evidence=(),
        liquidity=LiquidityEvidence(
            metric_id="FUTU_AVG_TURNOVER_20D",
            evidence_version="futu-screening-liquidity/v1",
            avg_turnover_20d_usd=Decimal("20000000.00"),
            avg_volume_20d_shares=None,
            window_days=20,
            currency="USD",
            raw_value="20000000.00",
            provenance=provenance,
            reason_codes=(),
        ),
        listing_history=ListingHistoryEvidence(
            metric_id="FUTU_LISTED_DAYS",
            evidence_version="futu-screening-listing-history/v1",
            listed_days=250,
            listing_date=date(1980, 12, 12),
            raw_value="250",
            provenance=provenance,
            reason_codes=(),
        ),
        reason_codes=(),
    )
    classification = ClassificationResult(
        decision=Decision.PASS,
        normalized_class="COMMON_STOCK",
        reason_code="CLASSIFICATION_COMMON_STOCK",
        evidence=(),
    )
    prerequisites = SecurityEvaluationPrerequisites(
        stock_id="1001",
        futu_code="US.AAPL",
        active_status=NormalizedPrerequisiteDecision(Decision.PASS, "ACTIVE", (reference,)),
        identity=NormalizedPrerequisiteDecision(
            identity,
            "IDENTITY_VERIFIED" if identity is Decision.PASS else "UNIVERSE_IDENTITY_BLOCKER",
            (reference,),
        ),
    )
    return build_evaluation_ui_state(
        profile=core_v1(),
        evidence=evidence,
        classification=classification,
        prerequisites=prerequisites,
    )


def test_universe_settings_renders_initialized_core_profile_only(tmp_path) -> None:
    registry = ProfileRegistry(tmp_path)
    registry.bootstrap(core_v1())
    app = AppTest.from_file(ROOT / "app/pages/3_Universe_Settings.py")
    app.session_state["universe_profile_registry"] = registry
    app.run()

    visible = _visible_text(app)

    assert not app.exception
    assert app.title[0].value == "股票池设置"
    for expected in (
        "CORE:v1",
        "CORE v1",
        "PUBLISHED",
        "Frozen default US common-stock universe.",
        "AMEX, NASDAQ, NYSE",
        "COMMON_STOCK",
        "FUTU_AVG_TURNOVER_20D",
        "FUTU_LISTED_DAYS",
        core_v1().content_sha256,
        core_v1().filter_content_sha256,
    ):
        assert expected in visible
    for forbidden in ("PASS", "FAIL", "UNKNOWN", "Quarantine", "member count"):
        assert forbidden not in visible


def test_universe_settings_surfaces_non_published_profile_failure(tmp_path) -> None:
    app = AppTest.from_file(ROOT / "app/pages/3_Universe_Settings.py")
    app.session_state["universe_profile_registry"] = _registry_containing_only_draft_core_v1(
        tmp_path
    )
    app.run()

    visible = _visible_text(app)

    assert not app.exception
    assert "no current published profile: CORE:v1" in visible
    for official_profile_content in (
        "当前正式版本",
        "CORE v1",
        "PUBLISHED",
        core_v1().content_sha256,
        core_v1().filter_content_sha256,
    ):
        assert official_profile_content not in visible


def test_universe_settings_renders_prebuilt_pass_and_quarantine_evaluations(tmp_path) -> None:
    registry = ProfileRegistry(tmp_path)
    registry.bootstrap(core_v1())
    app = AppTest.from_file(ROOT / "app/pages/3_Universe_Settings.py")
    app.session_state["universe_profile_registry"] = registry
    app.session_state["universe_evaluation_state"] = _evaluation_state(identity=Decision.PASS)
    app.run()

    visible = _visible_text(app)

    assert not app.exception
    for expected in (
        "AAPL",
        "CORE:v1",
        "CORE Member: YES",
        "Quarantine: NO",
        core_v1().content_sha256,
    ):
        assert expected in visible
    table = app.dataframe[0].value
    assert tuple(table.columns) == (
        "Decision item",
        "Status",
        "Actual value",
        "Normalized value",
        "Operator",
        "Threshold",
        "Reason",
        "Why",
        "Evidence source",
        "Evidence reference",
        "Evidence version",
    )
    assert len(table) == 9
    assert "Share price (S5_PRICE_ALLOWED)" in table["Decision item"].tolist()
    assert "5.00" in table["Actual value"].tolist()
    assert "5.00" in table["Normalized value"].tolist()
    assert "5.00" in table["Threshold"].tolist()
    assert "FUTU" in table["Evidence source"].tolist()
    assert all(table["Evidence reference"] != "Not available")
    assert "opend/9.4" in table["Evidence version"].tolist()
    assert "Not available" in table["Evidence version"].tolist()

    app.session_state["universe_evaluation_state"] = _evaluation_state(identity=Decision.UNKNOWN)
    app.run()
    visible = _visible_text(app)

    for expected in (
        "CORE Member: NO",
        "Quarantine: YES",
        "S1_IDENTITY_VALID",
        "UNIVERSE_IDENTITY_BLOCKER",
        "Identity verification",
        "identity record could not be reconciled",
    ):
        assert expected in visible
