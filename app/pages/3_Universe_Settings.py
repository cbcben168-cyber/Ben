"""Initialized published universe profile and persisted Snapshot evidence page."""

from dataclasses import asdict
import json
from uuid import UUID

import streamlit as st

from tv_quant.pattern_finder.universe_foundation import ProfileRegistry
from tv_quant.pattern_finder.universe_foundation.snapshots import (
    SnapshotCorruptError,
    SnapshotNotFoundError,
    SnapshotStoreError,
    SnapshotValidationError,
)
from tv_quant.pattern_finder.universe_foundation.ui_read_model import (
    EvaluationUiState,
    SnapshotUiState,
    find_security_decision,
    load_snapshot_ui_state,
    render_profile_status,
    render_security_evaluation,
    snapshot_ui_download_json,
)


def _security_rows(items):
    return [
        {
            "Symbol": item.symbol,
            "Stock ID": item.stock_id,
            "Futu code": item.futu_code,
            "Status": item.evaluation_status,
            "First exit": item.first_exit_stage or "None",
            "Reason": item.first_exit_reason_code or "MEMBER",
            "Quarantine": item.is_quarantined,
        }
        for item in items
    ]


def _download_payload(items) -> str:
    return json.dumps(
        [asdict(item) for item in items],
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def render_snapshot_evidence(*, state: SnapshotUiState) -> None:
    """Render only the supplied persisted-Snapshot projection."""

    st.header("Snapshot evidence")
    st.markdown(f"**Snapshot ID:** {state.snapshot_id}")
    st.markdown(
        f"**Kind / completeness:** {state.snapshot_kind} / {state.completeness}"
    )
    st.markdown(f"**As-of session:** {state.as_of_session}")
    st.markdown(f"**Created at (UTC):** {state.created_at_utc}")
    st.markdown(
        f"**Profile binding:** {state.profile_version_id or 'None'} / "
        f"{state.profile_content_sha256 or 'None'}"
    )
    st.markdown(
        f"**Draft binding:** {state.draft_id or 'None'} / "
        f"{state.draft_content_sha256 or 'None'}"
    )
    st.markdown(
        f"**Candidate count: {state.candidate_count} · Member count: "
        f"{state.member_count} · Quarantine count: {state.quarantine_count}**"
    )
    st.markdown(
        f"**Gateway attempt:** {state.gateway_attempt_id} / "
        f"{state.gateway_attempt_status} / {state.gateway_attempt_observed_at_utc}"
    )
    if state.gateway_attempt_reason_codes:
        st.warning(
            "Persisted attempt reasons: "
            + ", ".join(state.gateway_attempt_reason_codes)
        )
    st.subheader("Gateway preflight")
    st.markdown(f"**Gateway attempt SHA-256:** {state.gateway_attempt_sha256}")
    st.dataframe(
        [
            {
                "As-of session": state.gateway_preflight_as_of_session,
                "Observed at UTC": state.gateway_preflight_observed_at_utc,
                "Provider update time": (
                    state.gateway_preflight_provider_update_time or "Not available"
                ),
                "Delay class": state.gateway_preflight_market_data_delay_class,
                "Formal ready": state.gateway_preflight_formal_ready,
                "Reason codes": ", ".join(state.gateway_preflight_reason_codes)
                or "None",
                "Runtime evidence window seconds": (
                    state.gateway_runtime_evidence_window_seconds
                ),
                "Gateway attempt SHA-256": state.gateway_attempt_sha256,
            }
        ],
        hide_index=True,
        width="stretch",
    )
    st.subheader("Gateway batches")
    st.dataframe(
        [asdict(item) for item in state.gateway_batches],
        hide_index=True,
        width="stretch",
    )
    st.subheader("Identity ledger")
    st.dataframe(
        [asdict(item) for item in state.gateway_identity_ledger],
        hide_index=True,
        width="stretch",
    )
    st.subheader("Market-data delay evidence")
    st.dataframe(
        [asdict(item) for item in state.market_data_delay_evidence],
        hide_index=True,
        width="stretch",
    )
    st.subheader("Realtime capability probes")
    st.dataframe(
        [asdict(item) for item in state.realtime_capability_probes],
        hide_index=True,
        width="stretch",
    )
    st.markdown(
        "**Persisted metric/evidence bindings:** "
        f"{state.liquidity_metric_id} / {state.liquidity_evidence_version}; "
        f"{state.listing_history_metric_id} / "
        f"{state.listing_history_evidence_version}; sector mapping "
        f"{state.sector_mapping_version or 'None'}; classification versions "
        f"{', '.join(state.classification_source_versions) or 'None'}"
    )
    st.markdown(
        "**Market-state consistency SHA-256:** "
        f"{state.market_state_consistency_sha256}"
    )

    st.subheader("Persisted funnel")
    st.dataframe(
        [
            {
                "Stage": stage.stage_id,
                "Input": stage.input_count,
                "PASS": stage.pass_count,
                "FAIL": stage.fail_count,
                "UNKNOWN": stage.unknown_count,
                "Quarantine": stage.quarantine_count,
                "Output": stage.output_count,
                "Reasons": ", ".join(
                    f"{reason}={count}" for reason, count in stage.reason_counts
                ),
            }
            for stage in state.funnel_stages
        ],
        hide_index=True,
        width="stretch",
    )

    for title, items, file_name in (
        ("MEMBER", state.members, "universe-members.json"),
        ("Fail / non-member", state.failures, "universe-failures.json"),
        ("Quarantine / unknown", state.quarantined, "universe-quarantine.json"),
    ):
        st.subheader(title)
        st.dataframe(_security_rows(items), hide_index=True, width="stretch")
        st.download_button(
            f"Download {title}",
            data=_download_payload(items),
            file_name=file_name,
            mime="application/json",
        )

    st.download_button(
        "Download complete Snapshot projection",
        data=snapshot_ui_download_json(state),
        file_name=f"universe-snapshot-{state.snapshot_id}.json",
        mime="application/json",
    )

    st.subheader("Security decision search")
    query = st.text_input(
        "Security search",
        help="Exact, case-insensitive symbol, Futu code, or stock ID.",
    )
    if not query.strip():
        st.info("Enter an exact symbol, Futu code, or stock ID to inspect evidence.")
    else:
        detail = find_security_decision(state, query)
        if detail is None:
            st.error("No security record exists in this persisted Snapshot.")
        else:
            st.subheader(f"{detail.symbol} — {detail.name}")
            st.markdown(
                f"**Security:** {detail.stock_id} / {detail.futu_code} / "
                f"{detail.evaluation_status}"
            )
            st.markdown(
                f"**Member / Quarantine:** {detail.is_member} / "
                f"{detail.is_quarantined}"
            )
            st.markdown(
                f"**First exit:** {detail.first_exit_stage or 'None'} / "
                f"{detail.first_exit_reason_code or 'MEMBER'}"
            )
            st.markdown(
                "**Persisted decision reasons:** "
                + ", ".join(item.reason_code for item in detail.decisions)
            )
            st.markdown(
                f"**Identity:** {detail.identity_decision} / "
                f"{detail.identity_reason_code} / "
                f"{'; '.join(detail.identity_evidence_references)}"
            )
            st.markdown(
                f"**Active:** {detail.active_status_decision} / "
                f"{detail.active_status_reason_code} / "
                f"{'; '.join(detail.active_status_evidence_references)}"
            )
            st.subheader("Persisted security audit fields")
            st.dataframe(
                [
                    {
                        "Exchange raw / normalized": (
                            f"{detail.exchange_raw} / {detail.exchange_normalized}"
                        ),
                        "Security type raw / class": (
                            f"{detail.security_type_raw} / "
                            f"{detail.security_class_normalized}"
                        ),
                        "Delisting / suspension / status": (
                            f"{detail.delisting} / {detail.suspension} / "
                            f"{detail.security_status_raw}"
                        ),
                        "Price / observed UTC": (
                            f"{detail.price_usd} / {detail.price_observed_at_utc}"
                        ),
                        "Market cap / observed UTC": (
                            f"{detail.market_cap_usd} / "
                            f"{detail.market_cap_observed_at_utc}"
                        ),
                        "Liquidity metric / version": (
                            f"{detail.liquidity_metric_id} / "
                            f"{detail.liquidity_evidence_version}"
                        ),
                        "Turnover / window / volume": (
                            f"{detail.avg_turnover_20d_usd} / "
                            f"{detail.liquidity_window_end} / "
                            f"{detail.avg_volume_20d_shares}"
                        ),
                        "Listing metric / version": (
                            f"{detail.listing_history_metric_id} / "
                            f"{detail.listing_history_evidence_version}"
                        ),
                        "Listing date / days": (
                            f"{detail.listing_date} / {detail.listed_days}"
                        ),
                        "Sector mapping": detail.sector_mapping_version or "None",
                    }
                ],
                hide_index=True,
                width="stretch",
            )
            st.dataframe(
                [
                    {
                        "Decision item": item.field_id,
                        "Status": item.decision,
                        "Authoritative metric": item.authoritative_metric,
                        "Actual value": item.actual_value,
                        "Normalized value": item.normalized_value,
                        "Operator": item.operator or "Not applicable",
                        "Threshold": item.threshold,
                        "Reason": item.reason_code,
                        "Evidence source": item.evidence_source or "Not available",
                        "Evidence time": item.evidence_observed_at_utc
                        or "Not available",
                        "Evidence reference": "\n".join(item.evidence_references)
                        or "Not available",
                        "Evidence version": item.evidence_version
                        or "Not available",
                    }
                    for item in detail.decisions
                ],
                hide_index=True,
                width="stretch",
            )
            st.markdown(
                f"**Raw Industry:** {detail.raw_industry or 'Not available'} / "
                f"{detail.raw_industry_source or 'Not available'} / "
                f"{detail.raw_industry_provider_version or 'Not available'} / "
                f"{detail.raw_industry_source_version or 'Not available'} / "
                f"{detail.raw_industry_schema_version or 'Not available'} / "
                f"{detail.raw_industry_observed_at_utc or 'Not available'}"
            )
            st.markdown(
                "**Raw Industry references:** "
                + ("; ".join(detail.raw_industry_references) or "Not available")
            )
            st.markdown(
                "**Listing auxiliary/cross-check:** "
                + (", ".join(detail.listing_history_cross_check) or "None")
            )
            st.subheader("Classification evidence")
            st.dataframe(
                [asdict(item) for item in detail.classification_evidence],
                hide_index=True,
                width="stretch",
            )
            st.subheader("All owner Plates")
            st.dataframe(
                [asdict(item) for item in detail.raw_plates],
                hide_index=True,
                width="stretch",
            )
            st.markdown(
                f"**Raw evidence SHA-256:** {detail.raw_evidence_sha256}"
            )
            st.markdown(
                "**Raw evidence references:** "
                + ("; ".join(detail.raw_evidence_references) or "Not available")
            )
            st.markdown(
                f"**Member / Snapshot hashes:** {detail.members_sha256} / "
                f"{detail.snapshot_content_sha256} / "
                f"{detail.snapshot_record_sha256}"
            )

    st.subheader("Hashes and provenance")
    for label, value in (
        ("Members SHA-256", state.members_sha256),
        ("Snapshot content SHA-256", state.snapshot_content_sha256),
        ("Snapshot record SHA-256", state.snapshot_record_sha256),
        ("Funnel SHA-256", state.funnel_sha256),
        ("Prerequisites SHA-256", state.prerequisites_sha256),
        ("Active mapping SHA-256", state.active_status_mapping_sha256),
    ):
        st.markdown(f"**{label}:** {value}")
    st.markdown(
        f"**Provider / versions:** {state.provider} / "
        f"{state.provider_sdk_version} / {state.opend_server_version}"
    )
    st.markdown(
        f"**Active mapping:** {state.active_status_mapping_provider} / "
        f"{state.active_status_mapping_provider_sdk_version} / "
        f"{state.active_status_mapping_opend_server_version} / "
        f"{state.active_status_mapping_version} / "
        f"{state.active_status_mapping_qualified_at_utc}"
    )
    st.markdown(
        "**Active mapping qualification references:** "
        + "; ".join(state.active_status_mapping_qualification_references)
    )


st.set_page_config(page_title="股票池设置", page_icon="📋", layout="wide")
st.title("股票池设置")

registry = st.session_state.get("universe_profile_registry")
if not isinstance(registry, ProfileRegistry):
    st.error("Universe profile registry must be initialized before rendering.")
    st.stop()

try:
    render_profile_status(registry=registry, profile_version_id="CORE:v1")
except RuntimeError as exc:
    st.error(str(exc))

evaluation_state = st.session_state.get("universe_evaluation_state")
if evaluation_state is not None:
    if not isinstance(evaluation_state, EvaluationUiState):
        st.error("Universe evaluation state must be produced by the read model.")
    else:
        render_security_evaluation(state=evaluation_state)

snapshot_store = st.session_state.get("universe_snapshot_store")
snapshot_id_value = st.session_state.get("universe_snapshot_id")
if snapshot_store is not None or snapshot_id_value is not None:
    if snapshot_store is None or snapshot_id_value is None:
        st.error("Snapshot invalid: both store and snapshot ID are required.")
    else:
        try:
            snapshot_id = (
                snapshot_id_value
                if type(snapshot_id_value) is UUID
                else UUID(str(snapshot_id_value))
            )
            snapshot_state = load_snapshot_ui_state(snapshot_store, snapshot_id)
        except SnapshotNotFoundError as exc:
            st.error(f"Snapshot not found: {exc}")
        except SnapshotCorruptError as exc:
            st.error(f"Snapshot corrupt: {exc}")
        except SnapshotValidationError as exc:
            st.error(f"Snapshot invalid: {exc}")
        except SnapshotStoreError as exc:
            st.error(f"Snapshot store error: {exc}")
        except (TypeError, ValueError) as exc:
            st.error(f"Snapshot invalid: {exc}")
        else:
            render_snapshot_evidence(state=snapshot_state)
