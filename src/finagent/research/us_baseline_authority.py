from __future__ import annotations

from collections.abc import Mapping

from finagent.data.us_minute.simulation_certification import (
    validate_us_simulation_universe_document,
)
from finagent.data.us_minute.simulation_completion import (
    validate_us_simulation_d3_completion_bundle,
)
from finagent.research.us_baseline_evaluation import USBaselineRunSpec
from finagent.research.us_baseline_materialization import bind_us_b0_run_spec
from finagent.research.us_baselines import USBaselineCandidateDenominator

_FINAL_UNIVERSE_V2 = "finagent.us-engineering-universe-finalization-report.v2"
_FINAL_UNIVERSE_V3 = "finagent.us-engineering-universe-finalization-report.v3"
_SIMULATION_CERTIFICATION_V1 = "finagent.us-simulation-d3-certification-report.v1"


def bind_current_us_b0_run_spec(
    certification_document: Mapping[str, object],
    universe_document: Mapping[str, object],
    *,
    denominator: USBaselineCandidateDenominator,
    minimum_cross_section: int = 10,
    minimum_evaluated_periods: int = 20,
    minimum_ic_periods: int = 20,
) -> tuple[USBaselineRunSpec, tuple[str, ...]]:
    """Bind US-B0 to the current accepted final-universe schema without widening authority.

    The original materializer binder was frozen against the v2 final-universe report. US-I0
    now emits v3 after broker-clock hardening. v3 retains the accepted/materialization/
    quote-evidence fields consumed by US-B0, so this adapter verifies v3-specific clock and
    policy evidence, then presents only the already-consumed structural fields to the frozen
    v2 binder. It does not synthesize acceptance or weaken any US-D3 requirement.
    """

    schema = str(universe_document.get("schema_version", "")).strip()
    if schema == _FINAL_UNIVERSE_V2:
        normalized = universe_document
    elif schema == _FINAL_UNIVERSE_V3:
        quote_evidence = universe_document.get("quote_evidence")
        if not isinstance(quote_evidence, Mapping):
            raise TypeError("v3 final universe requires quote_evidence mapping")
        if quote_evidence.get("clock_evidence_passed") is not True:
            raise ValueError("US-B0 v3 final universe requires passing broker-clock evidence")
        if quote_evidence.get("quote_probe_policy_matches") is not True:
            raise ValueError("US-B0 v3 final universe requires matching quote-probe policy")
        normalized = dict(universe_document)
        normalized["schema_version"] = _FINAL_UNIVERSE_V2
    else:
        raise ValueError("US-B0 requires final US-I0 EngineeringUniverse report schema v2 or v3")

    return bind_us_b0_run_spec(
        certification_document,
        normalized,
        denominator=denominator,
        minimum_cross_section=minimum_cross_section,
        minimum_evaluated_periods=minimum_evaluated_periods,
        minimum_ic_periods=minimum_ic_periods,
    )


def bind_simulation_us_b0_run_spec(
    completion_document: Mapping[str, object],
    certification_document: Mapping[str, object],
    universe_document: Mapping[str, object],
    *,
    denominator: USBaselineCandidateDenominator,
    minimum_cross_section: int = 10,
    minimum_evaluated_periods: int = 20,
    minimum_ic_periods: int = 20,
) -> tuple[USBaselineRunSpec, tuple[str, ...], tuple[str, ...]]:
    """Bind reviewed simulation-limited US-D3 evidence into the frozen US-B0 evaluator.

    This is an additive compatibility adapter. It validates the real S2 simulation-universe
    document and a content-addressed US-D3 completion bundle, then creates an in-memory v2
    structural view solely for the already-frozen B0 binder. The compatibility view is never
    serialized as live/current US-I0 evidence and never grants live, PAPER or execution authority.
    """

    completion = validate_us_simulation_d3_completion_bundle(completion_document)
    universe = validate_us_simulation_universe_document(universe_document)
    if not universe.accepted:
        raise ValueError("US-B0 simulation path requires an accepted simulation universe")
    if completion.simulation_universe_report_id != universe.report_id:
        raise ValueError("US-D3 completion/universe report identity mismatch")
    if completion.simulation_universe_id != universe.simulation_universe_id:
        raise ValueError("US-D3 completion/universe identity mismatch")
    if completion.simulation_universe_count != universe.accepted_mapping_count:
        raise ValueError("US-D3 completion/universe count mismatch")
    if completion.broker_server != universe.broker_server:
        raise ValueError("US-D3 completion/universe broker server mismatch")

    schema = str(certification_document.get("schema_version", "")).strip()
    if schema != _SIMULATION_CERTIFICATION_V1:
        raise ValueError("US-B0 simulation path requires simulation D3 certification v1")
    if certification_document.get("certified") is not True:
        raise ValueError("US-B0 simulation path requires certified simulation D3 evidence")
    if certification_document.get("supports_us_b0_progression") is not True:
        raise ValueError("simulation D3 certification does not support US-B0 progression")
    if certification_document.get("live_market_data_authority") is not False:
        raise ValueError("simulation D3 certification must not assert live market-data authority")
    if certification_document.get("execution_authority") is not False:
        raise ValueError("simulation D3 certification must not assert execution authority")
    if str(certification_document.get("report_id", "")).strip() != completion.certification_report_id:
        raise ValueError("US-D3 completion/certification report identity mismatch")
    if str(certification_document.get("simulation_universe_report_id", "")).strip() != universe.report_id:
        raise ValueError("certification/simulation-universe report identity mismatch")
    if str(certification_document.get("simulation_universe_id", "")).strip() != universe.simulation_universe_id:
        raise ValueError("certification/simulation-universe identity mismatch")

    core_report = certification_document.get("core_report")
    if not isinstance(core_report, Mapping):
        raise TypeError("simulation D3 certification requires core_report mapping")

    selected = tuple(pair[0] for pair in universe.selected_pairs)
    normalized_universe: dict[str, object] = {
        "schema_version": _FINAL_UNIVERSE_V2,
        "accepted": True,
        "blockers": [],
        "universe_id": universe.simulation_universe_id,
        "accepted_mapping_count": universe.accepted_mapping_count,
        "selected_symbols": list(selected),
        "quote_evidence": {"passed": True},
        "materialization": {
            "mappings": [
                {
                    "status": "accepted_for_engineering",
                    "research": {"source_symbol": research_symbol},
                    "broker": {"broker_symbol": broker_symbol},
                }
                for research_symbol, broker_symbol in universe.selected_pairs
            ]
        },
    }
    run_spec, bound_selected = bind_us_b0_run_spec(
        core_report,
        normalized_universe,
        denominator=denominator,
        minimum_cross_section=minimum_cross_section,
        minimum_evaluated_periods=minimum_evaluated_periods,
        minimum_ic_periods=minimum_ic_periods,
    )
    if bound_selected != selected:
        raise ValueError("US-B0 compatibility binder changed simulation universe ordering")
    limitations = tuple(
        dict.fromkeys(
            (
                *universe.limitations,
                "us_b0:simulation_engineering_universe_only",
                "us_b0:no_live_market_data_authority",
                "us_b0:no_execution_authority",
            )
        )
    )
    return run_spec, bound_selected, limitations
