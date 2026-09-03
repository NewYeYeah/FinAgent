from __future__ import annotations

from datetime import UTC, datetime

from finagent.research.us_fixture_campaign import (
    USA0FixtureOutcome,
    USResearchFixtureScenario,
    run_us_research_fixture_campaign,
)
from finagent.research.us_r1_protocol import USR1Terminal

GENERATED_AT = datetime(2026, 9, 3, 6, 30, tzinfo=UTC)


def _by_scenario():
    report = run_us_research_fixture_campaign(generated_at=GENERATED_AT)
    return report, {item.scenario: item for item in report.scenarios}


def test_fixture_campaign_recovers_known_alpha_null_and_failure_terminals() -> None:
    report, scenarios = _by_scenario()

    alpha = scenarios[USResearchFixtureScenario.KNOWN_ALPHA]
    assert alpha.b0.anchor_mean_rank_ic is not None
    assert alpha.b0.anchor_mean_rank_ic > 0.95
    assert alpha.a0.outcome is USA0FixtureOutcome.AGENT_BETTER
    assert alpha.a0.agent_novel_candidate_count >= 1
    assert alpha.a0.agent_llm_calls == 16
    assert alpha.r1.terminal is USR1Terminal.ROBUST_FACTOR_FAMILY
    assert alpha.r1.robust_candidate_ids

    null = scenarios[USResearchFixtureScenario.KNOWN_NULL]
    assert null.b0.anchor_mean_rank_ic is not None
    assert abs(null.b0.anchor_mean_rank_ic) < 0.05
    assert null.a0.outcome is USA0FixtureOutcome.NO_AGENT_ADVANTAGE
    assert null.r1.terminal is USR1Terminal.NO_ROBUST_FACTOR_FAMILY
    assert not null.r1.robust_candidate_ids

    failure = scenarios[USResearchFixtureScenario.TECHNICAL_FAILURE]
    assert failure.b0.valid_candidate_count == 0
    assert failure.b0.blocker_count > 0
    assert failure.a0.outcome is USA0FixtureOutcome.SYSTEM_FAILURE
    assert failure.r1.terminal is USR1Terminal.SYSTEM_FAILURE
    assert not failure.r1.robust_candidate_ids

    assert report.passed


def test_fixture_campaign_is_content_addressed_and_deterministic() -> None:
    first = run_us_research_fixture_campaign(generated_at=GENERATED_AT)
    second = run_us_research_fixture_campaign(generated_at=GENERATED_AT)

    assert first.to_dict() == second.to_dict()
    assert first.campaign_id == second.campaign_id


def test_fixture_campaign_never_claims_real_research_or_market_authority() -> None:
    report = run_us_research_fixture_campaign(generated_at=GENERATED_AT)
    payload = report.to_dict()

    assert payload["real_us_market_evidence_substituted"] is False
    assert payload["status_toml_authority"] is False
    assert payload["status_authority"] is False
    assert payload["stage_exit_authority"] is False
    assert payload["agent_value_gate_authority"] is False
    assert payload["alpha_authority"] is False
    assert payload["execution_authority"] is False
    assert payload["live_capital_authority"] is False
    assert payload["implementation_maturity"] == {
        "US-B0": "FIXTURE_VALIDATED",
        "US-A0": "FIXTURE_VALIDATED",
        "US-R1": "FIXTURE_VALIDATED",
    }

    for scenario in payload["scenario_results"]:
        assert scenario["b0"]["authority"] == "development_fixture_only"
        assert scenario["a0"]["authority"] == "development_fixture_only"
        assert scenario["r1"]["authority"] == "development_fixture_only"
        assert scenario["b0"]["alpha_authority"] is False
        assert scenario["a0"]["agent_value_gate_authority"] is False
        assert scenario["r1"]["alpha_authority"] is False
