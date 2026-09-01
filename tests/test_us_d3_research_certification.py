from __future__ import annotations

from copy import deepcopy

from finagent.data.us_minute.research_certification import (
    USMinuteCertificationOutcome,
    USMinuteCertificationPolicy,
    evaluate_us_minute_certification,
    load_us_minute_certification_inputs,
)


def _source(*, authority: str = "reference_only") -> dict[str, object]:
    return {
        "local_research_admitted": True,
        "admission": {
            "admission_id": "us-minute-local-admission-test",
            "inventory_id": "us-minute-inventory-c2cbf682b456f97eb613ed65",
            "source_authority_status": authority,
            "source_identity": {
                "revision": "776328445b7ac6e7815ef3a483e9c8ded1eb6d56",
            },
        },
        "certification": {"passed": True},
    }


def _d1() -> dict[str, object]:
    return {
        "report_id": "minute-store-smoke-test",
        "passed": True,
        "blockers": [],
        "replay_match": True,
        "asset_count": 4,
        "partition_count": 3,
    }


def _scenario(name: str, *, other_unavailable: int = 0) -> dict[str, object]:
    return {
        "name": name,
        "labels": {"other_unavailable_count": other_unavailable},
    }


def _d2(*, other_unavailable: int = 0) -> dict[str, object]:
    return {
        "report_id": "us-d2-transform-smoke-test",
        "passed": True,
        "blockers": [],
        "calendar_id": "trading-calendar-03a9c29f566d6634aedbbbdc",
        "scenarios": [
            _scenario("half_day", other_unavailable=other_unavailable),
            _scenario("pre_dst"),
            _scenario("post_dst"),
        ],
        "action_authority": {
            "same_session_raw_allowed": True,
            "cross_session_raw_denied": True,
            "split_adjusted_denied": True,
            "total_return_adjusted_denied": True,
        },
    }


def _universe(*, count: int = 25) -> dict[str, object]:
    return {
        "universe_id": "engineering-universe-test",
        "accepted": True,
        "accepted_mapping_count": count,
    }


def _reconciliation(*, passed: bool = True) -> dict[str, object]:
    return {
        "report_id": "minute-reference-reconciliation-test",
        "passed": passed,
        "blockers": [] if passed else ["sample_mismatch_unclassified"],
    }


def _inputs(
    *,
    source: dict[str, object] | None = None,
    d1: dict[str, object] | None = None,
    d2: dict[str, object] | None = None,
    universe: dict[str, object] | None = None,
    reconciliation: dict[str, object] | None = None,
    pit_master: bool = False,
):
    return load_us_minute_certification_inputs(
        source_document=source or _source(),
        d1_document=d1 or _d1(),
        d2_document=_d2() if d2 is None else d2,
        universe_document=_universe() if universe is None else universe,
        reconciliation_document=(
            _reconciliation() if reconciliation is None else reconciliation
        ),
        point_in_time_security_master_available=pit_master,
    )


def test_complete_current_scope_certifies_engineering_research_only() -> None:
    report = evaluate_us_minute_certification(_inputs())

    assert report.certified
    assert (
        report.outcome
        is USMinuteCertificationOutcome.CERTIFIED_FOR_ENGINEERING_RESEARCH
    )
    assert report.blockers == ()
    assert "source_authority:reference_only" in report.limitations
    assert "identity:no_point_in_time_security_master" in report.limitations
    assert "claim:no_survivorship_unbiased_market_wide_alpha" in report.limitations


def test_broad_research_terminal_requires_pit_master_and_accepted_source() -> None:
    report = evaluate_us_minute_certification(
        _inputs(source=_source(authority="accepted_for_research"), pit_master=True)
    )

    assert report.certified
    assert (
        report.outcome
        is USMinuteCertificationOutcome.CERTIFIED_FOR_RESEARCH_UNDER_LIMITATIONS
    )
    assert "identity:no_point_in_time_security_master" not in report.limitations


def test_four_asset_seed_is_not_a_final_engineering_universe() -> None:
    report = evaluate_us_minute_certification(_inputs(universe=_universe(count=4)))

    assert not report.certified
    assert report.outcome is USMinuteCertificationOutcome.REJECTED
    assert "us_i0:engineering_universe_below_minimum" in report.blockers


def test_missing_real_d2_smoke_and_reconciliation_fail_closed() -> None:
    inputs = load_us_minute_certification_inputs(
        source_document=_source(),
        d1_document=_d1(),
        d2_document=None,
        universe_document=_universe(),
        reconciliation_document=None,
    )
    report = evaluate_us_minute_certification(inputs)

    assert not report.certified
    assert "us_d2:smoke_missing" in report.blockers
    assert "us_d2:calendar_identity_mismatch" in report.blockers
    assert "us_d2:corporate_action_authority_failed" in report.blockers
    assert "reconciliation:report_missing" in report.blockers


def test_unknown_label_unavailability_is_a_data_certification_blocker() -> None:
    report = evaluate_us_minute_certification(
        _inputs(d2=_d2(other_unavailable=1))
    )

    assert not report.certified
    assert "us_d2:unknown_label_unavailability" in report.blockers


def test_d1_replay_mismatch_is_not_hidden_by_other_passing_evidence() -> None:
    d1 = _d1()
    d1["replay_match"] = False
    report = evaluate_us_minute_certification(_inputs(d1=d1))

    assert not report.certified
    assert "us_d1:replay_mismatch" in report.blockers


def test_policy_can_change_universe_bounds_without_silent_identity_drift() -> None:
    default = USMinuteCertificationPolicy()
    wider = USMinuteCertificationPolicy(
        minimum_engineering_universe_size=15,
        maximum_engineering_universe_size=35,
    )

    assert default.policy_id != wider.policy_id
    assert evaluate_us_minute_certification(
        _inputs(universe=_universe(count=18)),
        policy=wider,
    ).certified


def test_report_identity_is_deterministic_and_changes_with_evidence() -> None:
    first = evaluate_us_minute_certification(_inputs())
    second = evaluate_us_minute_certification(_inputs())
    changed_d2 = deepcopy(_d2())
    changed_d2["report_id"] = "us-d2-transform-smoke-changed"
    changed = evaluate_us_minute_certification(_inputs(d2=changed_d2))

    assert first.report_id == second.report_id
    assert first.inputs.inputs_id == second.inputs.inputs_id
    assert changed.report_id != first.report_id
