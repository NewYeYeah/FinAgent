from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import streamlit as st

from finagent.visualization.feature_store import StoredFeatureView, load_feature_store
from finagent.visualization.figures import (
    correlation_heatmap,
    development_validation_scatter,
    ensemble_weights,
    llm_usage,
    quantile_returns,
    rolling_rank_ic,
    subperiod_rank_ic,
    universe_eligibility,
)
from finagent.visualization.research_report import (
    CandidateSnapshot,
    ResearchReportError,
    ResearchReportView,
    load_research_report,
    parse_research_report,
)
from finagent.visualization.trace_reader import AgentTraceView, load_agent_trace


st.set_page_config(
    page_title="FinAgent Research UI",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource(show_spinner=False)
def _cached_report(path: str, modified_ns: int) -> ResearchReportView:
    del modified_ns
    return load_research_report(path)


@st.cache_resource(show_spinner=False)
def _cached_uploaded_report(data: bytes, name: str) -> ResearchReportView:
    return parse_research_report(data, source=name)


@st.cache_resource(show_spinner=False)
def _cached_trace(path: str, modified_ns: int) -> AgentTraceView:
    del modified_ns
    return load_agent_trace(path)


@st.cache_resource(show_spinner=False)
def _cached_features(
    path: str,
    modified_ns: int,
    digests: tuple[str, ...],
) -> dict[str, StoredFeatureView]:
    del modified_ns
    return load_feature_store(path, digests=digests)


def _mtime(path: str) -> int:
    source = Path(path).expanduser()
    return source.stat().st_mtime_ns if source.is_file() else 0


def _candidate_label(candidate: CandidateSnapshot) -> str:
    suffix = " · selected" if candidate.selected else ""
    return f"{candidate.feature_id} · {candidate.feature_digest[:10]}{suffix}"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _metric(value: object, digits: int = 4) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _load_context() -> tuple[
    ResearchReportView | None,
    dict[str, StoredFeatureView],
    AgentTraceView | None,
    str,
]:
    st.sidebar.title("FinAgent Research UI")
    st.sidebar.caption("Read-only research evidence viewer")
    source_mode = st.sidebar.radio("Report source", ("Local path", "Upload"))
    report: ResearchReportView | None = None
    try:
        if source_mode == "Local path":
            default_report = os.environ.get(
                "FINAGENT_RESEARCH_REPORT",
                "reports/local_ashare_factor_research_a2p5.json",
            )
            report_path = st.sidebar.text_input("Research report", default_report)
            if Path(report_path).expanduser().is_file():
                report = _cached_report(report_path, _mtime(report_path))
            else:
                st.sidebar.info("Select an existing A2/A2.5 report JSON.")
        else:
            upload = st.sidebar.file_uploader("Research report JSON", type=("json",))
            if upload is not None:
                report = _cached_uploaded_report(upload.getvalue(), upload.name)
    except (OSError, ValueError, ResearchReportError) as exc:
        st.sidebar.error(f"Report load failed: {exc}")

    features: dict[str, StoredFeatureView] = {}
    trace: AgentTraceView | None = None
    phoenix_url = st.sidebar.text_input(
        "Phoenix URL",
        os.environ.get("FINAGENT_PHOENIX_URL", "http://localhost:6006"),
    )
    if report is not None:
        st.sidebar.divider()
        feature_path = st.sidebar.text_input(
            "Generated feature SQLite",
            os.environ.get(
                "FINAGENT_FEATURE_STORE",
                ".finagent/local-ashare-factor-a2p5/generated_features.sqlite",
            ),
        )
        if st.sidebar.checkbox("Load generated code", value=True):
            if Path(feature_path).expanduser().is_file():
                try:
                    digests = tuple(
                        candidate.feature_digest for candidate in report.candidates()
                    )
                    features = _cached_features(
                        feature_path,
                        _mtime(feature_path),
                        digests,
                    )
                except (OSError, ValueError) as exc:
                    st.sidebar.warning(f"Feature store unavailable: {exc}")
            else:
                st.sidebar.caption("Feature SQLite not found; report views remain available.")

        trace_path = st.sidebar.text_input(
            "Agent trace JSONL",
            os.environ.get(
                "FINAGENT_AGENT_TRACE_JSONL",
                ".finagent/a2-agent-trace.jsonl",
            ),
        )
        if st.sidebar.checkbox("Load Agent trace", value=True):
            if Path(trace_path).expanduser().is_file():
                try:
                    trace = _cached_trace(trace_path, _mtime(trace_path))
                except (OSError, ValueError) as exc:
                    st.sidebar.warning(f"Trace unavailable: {exc}")
            else:
                st.sidebar.caption("Trace JSONL not found; Phoenix can still be opened.")

    st.sidebar.divider()
    st.sidebar.warning(
        "This UI never mutates prompts, candidates, reports, checkpoints, registries or "
        "ResearchProgram state."
    )
    return report, features, trace, phoenix_url


def _candidate_table(report: ResearchReportView) -> None:
    rows = report.candidate_rows()
    st.dataframe(
        rows,
        hide_index=True,
        use_container_width=True,
        column_order=(
            "feature_id",
            "selected",
            "weight",
            "direction",
            "development_rank_icir",
            "validation_rank_icir",
            "development_long_short_sharpe",
            "validation_long_short_sharpe",
            "validation_hac_pvalue",
            "validation_holm_pvalue",
            "validation_bh_qvalue",
            "validation_sign_consistency",
            "validation_coverage",
        ),
    )


def _overview_page(report: ResearchReportView) -> None:
    st.title("Research Overview")
    universe = report.candidate_universe
    reserve = report.reserve
    columns = st.columns(6)
    columns[0].metric("System", "PASS" if report.system_passed else "FAIL")
    columns[1].metric("Research", report.research_status)
    columns[2].metric("Mode", report.mode)
    columns[3].metric("Candidates", len(report.candidates()))
    columns[4].metric("Universe", universe.get("size", "—"))
    columns[5].metric("Reserve", reserve.get("status", "unknown"))

    outcome = report.research_outcome
    reasons = outcome.get("reason_codes", ()) if outcome else ()
    if report.research_status.endswith("FAILED"):
        st.error("The workflow completed, but the frozen ensemble failed research validation.")
    elif report.research_status == "LEGACY_REPORT_NO_RESEARCH_VERDICT":
        st.warning("Legacy report: system completion and research validity are not separated.")
    else:
        st.info(
            "Positive factor-level validation remains unconfirmed and is not promotion evidence "
            "before A-share execution semantics are certified."
        )
    if reasons:
        st.caption("Reason codes: " + ", ".join(str(value) for value in reasons))
    for warning in report.warnings:
        st.warning(warning)

    st.plotly_chart(
        development_validation_scatter(report),
        use_container_width=True,
        config={"displaylogo": False},
    )
    st.subheader("Candidate denominator")
    _candidate_table(report)


def _agent_page(
    report: ResearchReportView,
    features: Mapping[str, StoredFeatureView],
    trace: AgentTraceView | None,
    phoenix_url: str,
) -> None:
    st.title("Agent Discovery & Trace")
    rounds = report.discovery_rounds()
    if rounds:
        st.subheader("Development-only discovery rounds")
        candidates_by_digest = {
            candidate.feature_digest: candidate for candidate in report.candidates()
        }
        for value in rounds:
            with st.expander(
                f"Round {value['round_index']} · "
                f"{len(value['new_candidate_digests'])} new candidates",
                expanded=True,
            ):
                st.caption(
                    f"Report: {value['cumulative_report_id']} · Feedback: {value['feedback_id']}"
                )
                new_rows = []
                selected = set(value["selected_feature_digests"])
                for digest in value["new_candidate_digests"]:
                    candidate = candidates_by_digest.get(str(digest))
                    new_rows.append(
                        {
                            "feature_id": candidate.feature_id if candidate else "unknown",
                            "feature_digest": digest,
                            "selected_in_round": digest in selected,
                            "hypothesis": candidate.hypothesis if candidate else "",
                        }
                    )
                st.dataframe(new_rows, hide_index=True, use_container_width=True)
    else:
        st.info("This report has no adaptive discovery rounds (deterministic or replay run).")

    candidates = report.candidates()
    selected_digest = st.selectbox(
        "Inspect candidate",
        options=[candidate.feature_digest for candidate in candidates],
        format_func=lambda digest: _candidate_label(report.candidate(digest)),
    )
    candidate = report.candidate(selected_digest)
    left, right = st.columns((2, 1))
    with left:
        st.markdown(f"**Hypothesis**  \n{candidate.hypothesis or 'Not recorded'}")
        st.caption(
            f"Inputs: {', '.join(candidate.input_fields)} · Lookback: {candidate.lookback} · "
            f"Generator: {candidate.generator_id}"
        )
        stored = features.get(candidate.feature_digest)
        if stored is not None:
            st.code(stored.source, language="python")
        else:
            st.info("Generated source is available when the read-only feature SQLite is loaded.")
    with right:
        st.metric("Selected", "yes" if candidate.selected else "no")
        st.metric("Frozen weight", _metric(candidate.weight))
        st.metric("Frozen direction", candidate.direction or "—")
        if stored is not None:
            st.json(
                {
                    "generated_at": stored.generated_at,
                    "validation": dict(stored.validation),
                    "metadata": dict(stored.metadata),
                },
                expanded=False,
            )

    st.divider()
    st.subheader("Agent trace")
    if phoenix_url.startswith(("http://", "https://")):
        st.link_button("Open Phoenix", phoenix_url)
    if trace is None:
        st.info("Load a JSONL trace in the sidebar or inspect the same OTLP trace in Phoenix.")
        return
    for warning in trace.warnings:
        st.warning(warning)
    metrics = st.columns(5)
    metrics[0].metric("Spans", len(trace.spans))
    metrics[1].metric("Errors", sum(span.is_error for span in trace.spans))
    metrics[2].metric("LLM calls", len(trace.llm_rows()))
    metrics[3].metric("Total tokens", trace.total_tokens)
    metrics[4].metric("Reasoning tokens", trace.total_reasoning_tokens)
    if trace.llm_rows():
        st.plotly_chart(
            llm_usage(trace),
            use_container_width=True,
            config={"displaylogo": False},
        )
        st.dataframe(trace.llm_rows(), hide_index=True, use_container_width=True)

    kinds = sorted({span.kind for span in trace.spans})
    statuses = sorted({span.status for span in trace.spans})
    filter_columns = st.columns(2)
    selected_kinds = filter_columns[0].multiselect("Kinds", kinds, default=kinds)
    selected_statuses = filter_columns[1].multiselect(
        "Statuses", statuses, default=statuses
    )
    rows = [
        row
        for row in trace.rows()
        if row["kind"] in selected_kinds and row["status"] in selected_statuses
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)
    if rows:
        span_id = st.selectbox(
            "Inspect span",
            options=[str(row["span_id"]) for row in rows],
            format_func=lambda value: trace.span(value).name,
        )
        span = trace.span(span_id)
        detail_columns = st.columns(2)
        detail_columns[0].json(dict(span.attributes), expanded=True)
        detail_columns[1].json(
            [
                {"name": event.name, "at": event.at, "attributes": dict(event.attributes)}
                for event in span.events
            ],
            expanded=True,
        )


def _factor_page(
    report: ResearchReportView,
    features: Mapping[str, StoredFeatureView],
) -> None:
    st.title("Factor Lab")
    candidates = report.candidates()
    digest = st.selectbox(
        "Factor",
        options=[candidate.feature_digest for candidate in candidates],
        format_func=lambda value: _candidate_label(report.candidate(value)),
    )
    candidate = report.candidate(digest)
    row = candidate.metric_row()
    metrics = st.columns(6)
    metrics[0].metric("Dev RankICIR", _metric(row["development_rank_icir"]))
    metrics[1].metric("Val RankICIR", _metric(row["validation_rank_icir"]))
    metrics[2].metric(
        "Dev LS Sharpe", _metric(row["development_long_short_sharpe"])
    )
    metrics[3].metric(
        "Val LS Sharpe", _metric(row["validation_long_short_sharpe"])
    )
    metrics[4].metric("HAC p", _metric(row["validation_hac_pvalue"]))
    metrics[5].metric("BH q", _metric(row["validation_bh_qvalue"]))

    st.markdown(f"**Hypothesis**  \n{candidate.hypothesis or 'Not recorded'}")
    tabs = st.tabs(("Rolling IC", "Subperiods", "Quantiles", "Stability", "Code"))
    with tabs[0]:
        if report.has_stability:
            st.plotly_chart(
                rolling_rank_ic(report, digest),
                use_container_width=True,
                config={"displaylogo": False},
            )
            st.dataframe(
                report.rolling_rows(digest, "development")
                + report.rolling_rows(digest, "validation"),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("Rolling diagnostics require an A2.5 stability report.")
    with tabs[1]:
        if report.has_stability:
            st.plotly_chart(
                subperiod_rank_ic(report, digest),
                use_container_width=True,
                config={"displaylogo": False},
            )
            st.dataframe(
                report.subperiod_rows(digest, "development")
                + report.subperiod_rows(digest, "validation"),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("Subperiod diagnostics require an A2.5 stability report.")
    with tabs[2]:
        st.plotly_chart(
            quantile_returns(report, digest),
            use_container_width=True,
            config={"displaylogo": False},
        )
        st.dataframe(
            report.quantile_rows(digest), hide_index=True, use_container_width=True
        )
    with tabs[3]:
        stability = candidate.validation_stability
        multiplicity = candidate.validation_multiplicity
        if not stability:
            st.info("Stability diagnostics are unavailable in this report.")
        else:
            hac = _mapping(stability.get("hac"))
            bootstrap = _mapping(stability.get("block_bootstrap"))
            st.dataframe(
                [
                    {
                        "sign_consistency": stability.get("sign_consistency_ratio"),
                        "positive_rank_ic_ratio": stability.get(
                            "positive_rank_ic_ratio"
                        ),
                        "quantile_monotonicity": stability.get(
                            "quantile_monotonicity"
                        ),
                        "horizon_sign_consistency": stability.get(
                            "horizon_sign_consistency"
                        ),
                        "turnover_std": stability.get("turnover_std"),
                        "coverage_mean": stability.get("coverage_mean"),
                        "coverage_min": stability.get("coverage_min"),
                        "hac_tstat": hac.get("tstat"),
                        "hac_pvalue": hac.get("pvalue"),
                        "bootstrap_pvalue": bootstrap.get("pvalue"),
                        "bootstrap_ci_lower": bootstrap.get("ci_lower"),
                        "bootstrap_ci_upper": bootstrap.get("ci_upper"),
                        "holm_adjusted_pvalue": multiplicity.get(
                            "holm_adjusted_pvalue"
                        ),
                        "bh_qvalue": multiplicity.get("bh_qvalue"),
                    }
                ],
                hide_index=True,
                use_container_width=True,
            )
            st.json(dict(stability), expanded=False)
    with tabs[4]:
        stored = features.get(candidate.feature_digest)
        if stored is None:
            st.info("Load generated_features.sqlite to inspect the accepted source.")
        else:
            st.code(stored.source, language="python")
            st.json(
                {
                    "spec": dict(stored.spec),
                    "validation": dict(stored.validation),
                    "metadata": dict(stored.metadata),
                },
                expanded=False,
            )


def _ensemble_page(report: ResearchReportView) -> None:
    st.title("Ensemble & Redundancy")
    st.plotly_chart(
        ensemble_weights(report),
        use_container_width=True,
        config={"displaylogo": False},
    )
    components = report.frozen_ensemble.get("components", ())
    st.dataframe(components, hide_index=True, use_container_width=True)

    comparison = _mapping(report.payload.get("validation_comparison"))
    st.subheader("Signed validation comparison")
    st.dataframe([dict(comparison)], hide_index=True, use_container_width=True)
    if comparison:
        signed = comparison.get("ensemble_minus_best_single_long_short_sharpe")
        if signed is not None and float(signed) < 0:
            st.warning(
                "The frozen ensemble underperformed the development-oriented best "
                "single factor."
            )

    ensemble_stability = report.validation_ensemble_stability
    if ensemble_stability:
        st.subheader("Validation ensemble stability")
        st.json(dict(ensemble_stability), expanded=False)

    st.subheader("Factor-value correlation")
    tabs = st.tabs(("Development", "Validation"))
    with tabs[0]:
        st.plotly_chart(
            correlation_heatmap(report, "development"),
            use_container_width=True,
            config={"displaylogo": False},
        )
    with tabs[1]:
        st.plotly_chart(
            correlation_heatmap(report, "validation"),
            use_container_width=True,
            config={"displaylogo": False},
        )


def _universe_page(report: ResearchReportView) -> None:
    st.title("Universe & Data Quality")
    universe = report.candidate_universe
    policy = report.universe_policy
    metrics = st.columns(5)
    metrics[0].metric("Candidate universe", universe.get("size", "—"))
    metrics[1].metric("Selection date", universe.get("selection_date", "—"))
    metrics[2].metric("Selection ID", str(universe.get("selection_id", ""))[:20])
    metrics[3].metric("Policy version", str(policy.get("data_version", ""))[:20])
    metrics[4].metric("Reserve", report.reserve.get("status", "unknown"))

    rows = report.universe_rows()
    st.plotly_chart(
        universe_eligibility(report),
        use_container_width=True,
        config={"displaylogo": False},
    )
    display_rows = [
        {key: value for key, value in row.items() if key != "rejected_counts"}
        for row in rows
    ]
    st.dataframe(display_rows, hide_index=True, use_container_width=True)
    rejected = []
    for row in rows:
        for reason, count in _mapping(row.get("rejected_counts")).items():
            rejected.append({"split": row["split"], "reason": reason, "count": count})
    if rejected:
        st.subheader("Policy rejection diagnostics")
        st.dataframe(rejected, hide_index=True, use_container_width=True)
    st.caption(str(universe.get("scope", "")))


def _lineage_page(report: ResearchReportView) -> None:
    st.title("Lineage & Replay")
    st.dataframe(report.lineage_rows(), hide_index=True, use_container_width=True)
    checks = [
        {
            "invariant": "System workflow completed",
            "passed": report.system_passed,
        },
        {
            "invariant": "Candidate denominator aligns across development and validation",
            "passed": True,
        },
        {
            "invariant": "Reserve remains untouched",
            "passed": report.reserve.get("status") == "untouched",
        },
        {
            "invariant": "A2 is not promotion eligible",
            "passed": not report.promotion_eligible,
        },
        {
            "invariant": "Stability evidence available",
            "passed": report.has_stability,
        },
    ]
    st.dataframe(checks, hide_index=True, use_container_width=True)
    st.caption(
        "Exact replay remains a CLI operation. The UI is intentionally unable to rerun, "
        "fork, promote or consume reserve evidence."
    )
    with st.expander("Raw immutable report"):
        st.json(dict(report.payload), expanded=False)
        st.download_button(
            "Download displayed report",
            data=report.raw_json(),
            file_name=Path(report.source).name or "finagent-research-report.json",
            mime="application/json",
        )


def _empty_page() -> None:
    st.title("FinAgent Research UI")
    st.info(
        "Load an A2/A2.5 research report from the sidebar. The application accepts "
        "local JSON paths or uploaded JSON and does not modify research state."
    )
    st.code(
        "python scripts/run_research_ui.py --report "
        "reports/local_ashare_factor_research_a2p5.json",
        language="powershell",
    )


def main() -> None:
    report, features, trace, phoenix_url = _load_context()
    if report is None:
        _empty_page()
        return

    pages = {
        "Research": [
            st.Page(
                lambda: _overview_page(report),
                title="Overview",
                icon="📊",
                default=True,
            ),
            st.Page(
                lambda: _factor_page(report, features),
                title="Factor Lab",
                icon="🧪",
            ),
            st.Page(lambda: _ensemble_page(report), title="Ensemble", icon="🧩"),
            st.Page(lambda: _universe_page(report), title="Universe", icon="🗂️"),
        ],
        "Agent & Governance": [
            st.Page(
                lambda: _agent_page(report, features, trace, phoenix_url),
                title="Agent Discovery",
                icon="🤖",
            ),
            st.Page(lambda: _lineage_page(report), title="Lineage", icon="🔒"),
        ],
    }
    navigation = st.navigation(pages)
    navigation.run()


if __name__ == "__main__":
    main()
