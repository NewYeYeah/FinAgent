from __future__ import annotations

from collections.abc import Mapping

from finagent.research.us_baseline_evaluation import USBaselineRunSpec
from finagent.research.us_baseline_materialization import bind_us_b0_run_spec
from finagent.research.us_baselines import USBaselineCandidateDenominator

_FINAL_UNIVERSE_V2 = "finagent.us-engineering-universe-finalization-report.v2"
_FINAL_UNIVERSE_V3 = "finagent.us-engineering-universe-finalization-report.v3"


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
