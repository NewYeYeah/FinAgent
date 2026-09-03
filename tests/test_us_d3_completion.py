from __future__ import annotations

from datetime import timedelta

import pytest

from finagent.data.us_minute.simulation_certification import (
    CANONICAL_US_SIMULATION_D3_CERTIFICATION_POLICY,
    USSimulationD3Review,
    USSimulationD3ReviewDecision,
    build_us_simulation_d3_certification,
)
from finagent.data.us_minute.simulation_completion import (
    build_us_simulation_d3_completion_bundle,
    validate_us_simulation_d3_completion_bundle,
)
from finagent.research.us_baseline_authority import bind_simulation_us_b0_run_spec
from finagent.research.us_baselines import canonical_us_baseline_denominator
from tests.test_us_d3_simulation_admission import (
    NOW,
    _d1,
    _d2,
    _reconciliation,
    _simulation_universe,
    _source,
    _symbols,
)

CODE_FENCE = "a" * 40


def _accepted_chain():
    universe = _simulation_universe()
    reconciliation = _reconciliation()
    certification = build_us_simulation_d3_certification(
        source_document=_source(),
        d1_document=_d1(),
        d2_document=_d2(),
        simulation_universe_document=universe,
        reconciliation_document=reconciliation,
    )
    assert certification.certified
    review = USSimulationD3Review(
        certification=certification,
        reviewer_id="reviewer-1",
        reviewed_at=NOW + timedelta(minutes=1),
        decision=USSimulationD3ReviewDecision.ACCEPT,
        notes="accepted synthetic closure",
    )
    bundle = build_us_simulation_d3_completion_bundle(
        source_document=_source(),
        d1_document=_d1(),
        d2_document=_d2(),
        simulation_universe_document=universe,
        reconciliation_document=reconciliation,
        policy_document=CANONICAL_US_SIMULATION_D3_CERTIFICATION_POLICY.to_dict(),
        certification_document=certification.to_dict(),
        review_document=review.to_dict(),
        code_fence_sha=CODE_FENCE,
        assembled_at=NOW + timedelta(minutes=2),
    )
    return universe, certification, review, bundle


def test_completion_bundle_rebuilds_exact_reviewed_chain_without_stage_authority() -> None:
    universe, certification, review, bundle = _accepted_chain()
    parsed = validate_us_simulation_d3_completion_bundle(bundle.to_dict())

    assert parsed.bundle_id == bundle.bundle_id
    assert parsed.simulation_universe_id == universe["simulation_universe_id"]
    assert parsed.certification_report_id == certification.report_id
    assert parsed.review_id == review.review_id
    payload = bundle.to_dict()
    assert payload["governance_ready"] is True
    assert payload["supports_us_b0_progression"] is True
    assert payload["live_market_data_authority"] is False
    assert payload["execution_authority"] is False
    assert payload["status_authority"] is False
    assert payload["stage_exit_authority"] is False


def test_completion_bundle_rejects_review_or_authority_tamper() -> None:
    universe, certification, review, _bundle = _accepted_chain()
    tampered_review = dict(review.to_dict())
    tampered_review["notes"] = "changed after review"
    with pytest.raises(ValueError, match="review differs"):
        build_us_simulation_d3_completion_bundle(
            source_document=_source(),
            d1_document=_d1(),
            d2_document=_d2(),
            simulation_universe_document=universe,
            reconciliation_document=_reconciliation(),
            policy_document=CANONICAL_US_SIMULATION_D3_CERTIFICATION_POLICY.to_dict(),
            certification_document=certification.to_dict(),
            review_document=tampered_review,
            code_fence_sha=CODE_FENCE,
            assembled_at=NOW + timedelta(minutes=2),
        )

    _universe, _certification, _review, bundle = _accepted_chain()
    tampered_bundle = dict(bundle.to_dict())
    tampered_bundle["live_market_data_authority"] = True
    with pytest.raises(ValueError, match="live_market_data_authority"):
        validate_us_simulation_d3_completion_bundle(tampered_bundle)


def test_simulation_b0_adapter_consumes_reviewed_completion_without_live_promotion() -> None:
    universe, certification, _review, bundle = _accepted_chain()
    run_spec, selected, limitations = bind_simulation_us_b0_run_spec(
        bundle.to_dict(),
        certification.to_dict(),
        universe,
        denominator=canonical_us_baseline_denominator(),
    )

    assert selected == _symbols()
    assert run_spec.engineering_universe_id == universe["simulation_universe_id"]
    assert "us_b0:simulation_engineering_universe_only" in limitations
    assert "us_b0:no_live_market_data_authority" in limitations
    assert "us_b0:no_execution_authority" in limitations


def test_simulation_b0_adapter_rejects_completion_certification_drift() -> None:
    universe, certification, _review, bundle = _accepted_chain()
    tampered_certification = dict(certification.to_dict())
    tampered_certification["report_id"] = "us-simulation-d3-certification-forged"

    with pytest.raises(ValueError, match="completion/certification"):
        bind_simulation_us_b0_run_spec(
            bundle.to_dict(),
            tampered_certification,
            universe,
            denominator=canonical_us_baseline_denominator(),
        )
