from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from finagent.domain.market_bars import BarInterval
from finagent.research.us_agent_value_experiment import (
    RunEvaluationLink,
    SearchArmResult,
    build_search_arm_result,
)
from finagent.research.us_agent_value_generation import (
    CandidateGenerationRun,
    CandidateGenerationUsage,
    ProposalSlot,
    StructuredCandidateProposal,
    agent_run_spec,
    build_candidate_generation_run,
    canonical_manual_run_spec,
    deterministic_programmatic_proposal_slots,
    manual_proposal_slots,
    programmatic_run_spec,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_baseline_evaluation import (
    USBaselineEvaluationReport,
    USBaselineObservation,
    USBaselineRunSpec,
    evaluate_us_baseline_denominator,
)
from finagent.research.us_baselines import canonical_us_baseline_denominator
from finagent.research.us_r1_gate import (
    USR1AlphaGateAssessment,
    assess_us_r1_alpha_gate,
    build_us_r1_family_evidence,
    build_us_r1_raw_candidate_evidence,
)
from finagent.research.us_r1_inference import USR1FoldSeries, USR1PeriodMetricPoint
from finagent.research.us_r1_protocol import (
    USR1AgentScope,
    USR1CandidateDenominator,
    USR1CandidateProvenance,
    USR1Terminal,
    canonical_us_r1_research_protocol,
)
from finagent.research.us_agent_value_gate import USAgentValueGateDecision


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


class USResearchFixtureScenario(StrEnum):
    KNOWN_ALPHA = "KNOWN_ALPHA"
    KNOWN_NULL = "KNOWN_NULL"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"


class USA0FixtureOutcome(StrEnum):
    AGENT_BETTER = "AGENT_BETTER_FIXTURE"
    NO_AGENT_ADVANTAGE = "NO_AGENT_ADVANTAGE_FIXTURE"
    SYSTEM_FAILURE = "SYSTEM_FAILURE_FIXTURE"


@dataclass(frozen=True, slots=True)
class USB0FixtureSummary:
    scenario: USResearchFixtureScenario
    report_id: str
    candidate_count: int
    valid_candidate_count: int
    anchor_candidate_id: str
    anchor_mean_rank_ic: float | None
    blocker_count: int
    expectation_met: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario.value,
            "report_id": self.report_id,
            "candidate_count": self.candidate_count,
            "valid_candidate_count": self.valid_candidate_count,
            "anchor_candidate_id": self.anchor_candidate_id,
            "anchor_mean_rank_ic": self.anchor_mean_rank_ic,
            "blocker_count": self.blocker_count,
            "expectation_met": self.expectation_met,
            "authority": "development_fixture_only",
            "status_authority": False,
            "stage_exit_authority": False,
            "factor_selection_authority": False,
            "alpha_authority": False,
        }


@dataclass(frozen=True, slots=True)
class USA0FixtureSummary:
    scenario: USResearchFixtureScenario
    manual_result_id: str
    programmatic_result_id: str
    agent_result_id: str
    manual_best_worst_fold_rank_ic: float | None
    programmatic_best_worst_fold_rank_ic: float | None
    agent_best_worst_fold_rank_ic: float | None
    agent_novel_candidate_count: int
    agent_llm_calls: int
    outcome: USA0FixtureOutcome
    expectation_met: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario.value,
            "manual_result_id": self.manual_result_id,
            "programmatic_result_id": self.programmatic_result_id,
            "agent_result_id": self.agent_result_id,
            "manual_best_worst_fold_rank_ic": self.manual_best_worst_fold_rank_ic,
            "programmatic_best_worst_fold_rank_ic": self.programmatic_best_worst_fold_rank_ic,
            "agent_best_worst_fold_rank_ic": self.agent_best_worst_fold_rank_ic,
            "agent_novel_candidate_count": self.agent_novel_candidate_count,
            "agent_llm_calls": self.agent_llm_calls,
            "outcome": self.outcome.value,
            "expectation_met": self.expectation_met,
            "authority": "development_fixture_only",
            "agent_value_gate_authority": False,
            "status_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
        }


@dataclass(frozen=True, slots=True)
class USR1FixtureSummary:
    scenario: USResearchFixtureScenario
    family_evidence_id: str
    assessment_id: str
    terminal: USR1Terminal
    robust_candidate_ids: tuple[str, ...]
    expectation_met: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario.value,
            "family_evidence_id": self.family_evidence_id,
            "assessment_id": self.assessment_id,
            "terminal": self.terminal.value,
            "robust_candidate_ids": list(self.robust_candidate_ids),
            "expectation_met": self.expectation_met,
            "authority": "development_fixture_only",
            "alpha_gate_review_authority": False,
            "status_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
        }


@dataclass(frozen=True, slots=True)
class USResearchFixtureScenarioResult:
    scenario: USResearchFixtureScenario
    b0: USB0FixtureSummary
    a0: USA0FixtureSummary
    r1: USR1FixtureSummary

    @property
    def passed(self) -> bool:
        return self.b0.expectation_met and self.a0.expectation_met and self.r1.expectation_met

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario.value,
            "passed": self.passed,
            "b0": self.b0.to_dict(),
            "a0": self.a0.to_dict(),
            "r1": self.r1.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class USResearchFixtureCampaignReport:
    scenarios: tuple[USResearchFixtureScenarioResult, ...]
    generated_at: datetime
    schema_version: str = "finagent.us-research-fixture-campaign.v1"

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        object.__setattr__(self, "generated_at", self.generated_at.astimezone(UTC))
        expected = tuple(USResearchFixtureScenario)
        if tuple(item.scenario for item in self.scenarios) != expected:
            raise ValueError("fixture campaign must contain KNOWN_ALPHA/KNOWN_NULL/TECHNICAL_FAILURE in order")

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.scenarios)

    @property
    def campaign_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-research-fixture-campaign")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.isoformat(),
            "passed": self.passed,
            "scenario_results": [item.to_dict() for item in self.scenarios],
            "implementation_maturity": {
                "US-B0": "FIXTURE_VALIDATED" if self.passed else "IMPLEMENTED",
                "US-A0": "FIXTURE_VALIDATED" if self.passed else "IMPLEMENTED",
                "US-R1": "FIXTURE_VALIDATED" if self.passed else "IMPLEMENTED",
            },
            "scope": "offline_deterministic_engineering_validation_only",
            "real_us_market_evidence_substituted": False,
            "status_toml_authority": False,
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["campaign_id"] = self.campaign_id
        return payload


def _b0_observations(
    scenario: USResearchFixtureScenario,
) -> tuple[USBaselineEvaluationReport, str]:
    denominator = canonical_us_baseline_denominator()
    run_spec = USBaselineRunSpec(
        certification_report_id="fixture-us-d3-certification",
        certification_outcome="CERTIFIED_FOR_RESEARCH_UNDER_LIMITATIONS",
        engineering_universe_id="fixture-engineering-universe-12",
        denominator_id=denominator.denominator_id,
        minimum_cross_section=10,
        minimum_evaluated_periods=20,
        minimum_ic_periods=20,
    )
    asset_count = 4 if scenario is USResearchFixtureScenario.TECHNICAL_FAILURE else 12
    assets = tuple(f"FIX{index:02d}" for index in range(asset_count))
    start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    observations: dict[str, list[USBaselineObservation]] = {
        candidate.feature_id: [] for candidate in denominator.candidates
    }
    for period in range(24):
        event_time = start + timedelta(minutes=15 * period)
        formation_at = event_time + timedelta(minutes=15)
        label_at = formation_at + timedelta(minutes=60)
        direction = 1.0 if scenario is USResearchFixtureScenario.KNOWN_ALPHA else (1.0 if period % 2 == 0 else -1.0)
        for asset_index, asset in enumerate(assets):
            anchor_value = float(asset_index) - (asset_count - 1) / 2.0
            realized_label = direction * anchor_value * 0.001
            for candidate_index, candidate in enumerate(denominator.candidates):
                if candidate_index == 0:
                    feature_value = anchor_value
                else:
                    feature_value = float(
                        (asset_index * (candidate_index + 2) + period * (candidate_index + 1)) % 17
                    )
                observations[candidate.feature_id].append(
                    USBaselineObservation(
                        feature_id=candidate.feature_id,
                        feature_spec_id=candidate.spec_id,
                        asset=asset,
                        event_time=event_time,
                        feature_available_at=formation_at,
                        eligible_at_formation=True,
                        feature_value=feature_value,
                        realized_label=realized_label,
                        label_available_at=label_at,
                    )
                )
    report = evaluate_us_baseline_denominator(
        denominator,
        observations,
        run_spec=run_spec,
    )
    return report, denominator.candidates[0].feature_id


def _summarize_b0(scenario: USResearchFixtureScenario) -> USB0FixtureSummary:
    report, anchor_id = _b0_observations(scenario)
    anchor = next(item for item in report.candidates if item.feature_id == anchor_id)
    if scenario is USResearchFixtureScenario.KNOWN_ALPHA:
        expectation = anchor.valid and anchor.mean_rank_ic is not None and anchor.mean_rank_ic > 0.95
    elif scenario is USResearchFixtureScenario.KNOWN_NULL:
        expectation = anchor.valid and anchor.mean_rank_ic is not None and abs(anchor.mean_rank_ic) < 0.05
    else:
        expectation = report.valid_candidate_count == 0 and bool(report.blockers)
    return USB0FixtureSummary(
        scenario=scenario,
        report_id=report.report_id,
        candidate_count=len(report.candidates),
        valid_candidate_count=report.valid_candidate_count,
        anchor_candidate_id=anchor.feature_id,
        anchor_mean_rank_ic=anchor.mean_rank_ic,
        blocker_count=len(report.blockers),
        expectation_met=expectation,
    )


def _agent_slots(
    *,
    manual_run: CandidateGenerationRun,
    programmatic_run: CandidateGenerationRun,
    generated_at: datetime,
) -> tuple[ProposalSlot, ...]:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    vocabulary = canonical_us_a0_primitive_vocabulary()
    excluded = {
        candidate.candidate_id
        for run in (manual_run, programmatic_run)
        for candidate in run.accepted_candidates
    }
    selected = [candidate for candidate in vocabulary.all_candidates() if candidate.candidate_id not in excluded]
    if len(selected) < protocol.candidate_budget_per_run:
        raise RuntimeError("fixture vocabulary cannot provide enough structurally novel AGENT candidates")
    usage = CandidateGenerationUsage(
        llm_calls=1,
        input_tokens=64,
        output_tokens=16,
        latency_ms=5.0,
        cost_usd=0.0001,
    )
    return tuple(
        ProposalSlot(
            initial=StructuredCandidateProposal(
                kind=candidate.kind.value,
                window_bars=candidate.window_bars,
                hypothesis_summary="Deterministic fixture proposal for Agent orchestration validation.",
                generated_at=generated_at,
                usage=usage,
            )
        )
        for candidate in selected[: protocol.candidate_budget_per_run]
    )


def _link(
    run: CandidateGenerationRun,
    *,
    evidence_id: str,
    mean_rank_ic: float | None,
    worst_rank_ic: float | None,
    blockers: tuple[str, ...] = (),
) -> RunEvaluationLink:
    return RunEvaluationLink(
        generation_run_id=run.run_id,
        authoritative_evidence_id=evidence_id,
        evaluated_candidate_count=len(run.accepted_candidates),
        valid_candidate_count=0 if blockers else len(run.accepted_candidates),
        best_mean_rank_ic=mean_rank_ic,
        best_worst_fold_rank_ic=worst_rank_ic,
        blockers=blockers,
    )


def _a0_fixture(
    scenario: USResearchFixtureScenario,
) -> tuple[USA0FixtureSummary, CandidateGenerationRun]:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    generated_at = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    manual_run = build_candidate_generation_run(
        protocol,
        canonical_manual_run_spec(protocol),
        manual_proposal_slots(protocol, generated_at=generated_at),
    )
    programmatic_run = build_candidate_generation_run(
        protocol,
        programmatic_run_spec(protocol, run_ordinal=1, random_seed=1729),
        deterministic_programmatic_proposal_slots(
            protocol,
            random_seed=1729,
            generated_at=generated_at,
        ),
    )
    agent_run = build_candidate_generation_run(
        protocol,
        agent_run_spec(
            protocol,
            run_ordinal=1,
            provider_id="fixture-provider",
            model_id="fixture-model",
            prompt_template_id="fixture-prompt-v1",
        ),
        _agent_slots(
            manual_run=manual_run,
            programmatic_run=programmatic_run,
            generated_at=generated_at,
        ),
    )

    if scenario is USResearchFixtureScenario.KNOWN_ALPHA:
        manual_quality = (0.025, 0.015)
        programmatic_quality = (0.040, 0.025)
        agent_quality = (0.075, 0.060)
        agent_blockers: tuple[str, ...] = ()
        expected_outcome = USA0FixtureOutcome.AGENT_BETTER
    elif scenario is USResearchFixtureScenario.KNOWN_NULL:
        manual_quality = (0.025, 0.015)
        programmatic_quality = (0.040, 0.025)
        agent_quality = (0.020, 0.010)
        agent_blockers = ()
        expected_outcome = USA0FixtureOutcome.NO_AGENT_ADVANTAGE
    else:
        manual_quality = (0.025, 0.015)
        programmatic_quality = (0.040, 0.025)
        agent_quality = (None, None)
        agent_blockers = ("fixture:synthetic_evaluation_failure",)
        expected_outcome = USA0FixtureOutcome.SYSTEM_FAILURE

    manual_link = _link(
        manual_run,
        evidence_id="fixture-manual-evidence",
        mean_rank_ic=manual_quality[0],
        worst_rank_ic=manual_quality[1],
    )
    programmatic_link = _link(
        programmatic_run,
        evidence_id="fixture-programmatic-evidence",
        mean_rank_ic=programmatic_quality[0],
        worst_rank_ic=programmatic_quality[1],
    )
    agent_link = _link(
        agent_run,
        evidence_id="fixture-agent-evidence",
        mean_rank_ic=agent_quality[0],
        worst_rank_ic=agent_quality[1],
        blockers=agent_blockers,
    )
    manual_result = build_search_arm_result(
        protocol,
        USAgentValueArm.MANUAL,
        (manual_run,),
        (manual_link,),
    )
    programmatic_result = build_search_arm_result(
        protocol,
        USAgentValueArm.PROGRAMMATIC,
        (programmatic_run,),
        (programmatic_link,),
    )
    agent_result = build_search_arm_result(
        protocol,
        USAgentValueArm.AGENT,
        (agent_run,),
        (agent_link,),
    )
    manual_ids = {item.candidate_id for item in manual_run.accepted_candidates}
    programmatic_ids = {item.candidate_id for item in programmatic_run.accepted_candidates}
    agent_ids = {item.candidate_id for item in agent_run.accepted_candidates}
    novel = len(agent_ids.difference(manual_ids.union(programmatic_ids)))

    if not agent_result.passed:
        observed = USA0FixtureOutcome.SYSTEM_FAILURE
    elif (
        agent_link.best_worst_fold_rank_ic is not None
        and programmatic_link.best_worst_fold_rank_ic is not None
        and manual_link.best_worst_fold_rank_ic is not None
        and agent_link.best_worst_fold_rank_ic
        > max(programmatic_link.best_worst_fold_rank_ic, manual_link.best_worst_fold_rank_ic) + 0.01
        and novel >= 1
    ):
        observed = USA0FixtureOutcome.AGENT_BETTER
    else:
        observed = USA0FixtureOutcome.NO_AGENT_ADVANTAGE

    return (
        USA0FixtureSummary(
            scenario=scenario,
            manual_result_id=manual_result.result_id,
            programmatic_result_id=programmatic_result.result_id,
            agent_result_id=agent_result.result_id,
            manual_best_worst_fold_rank_ic=manual_link.best_worst_fold_rank_ic,
            programmatic_best_worst_fold_rank_ic=programmatic_link.best_worst_fold_rank_ic,
            agent_best_worst_fold_rank_ic=agent_link.best_worst_fold_rank_ic,
            agent_novel_candidate_count=novel,
            agent_llm_calls=agent_run.usage.llm_calls,
            outcome=observed,
            expectation_met=observed is expected_outcome,
        ),
        manual_run,
    )


def _r1_fold_series(
    scenario: USResearchFixtureScenario,
) -> tuple[USR1FoldSeries, ...]:
    folds: list[USR1FoldSeries] = []
    base = datetime(2026, 2, 2, 15, 0, tzinfo=UTC)
    for fold_index in range(3):
        points: list[USR1PeriodMetricPoint] = []
        for index in range(30):
            if scenario is USResearchFixtureScenario.KNOWN_ALPHA:
                rank_ic = 0.045 + ((index % 5) - 2) * 0.002
                long_short = 2.5 + (index % 3) * 0.2
                monotonicity = 0.70
            else:
                sign = 1.0 if index % 2 == 0 else -1.0
                rank_ic = sign * 0.015
                long_short = sign * 0.4
                monotonicity = sign * 0.10
            points.append(
                USR1PeriodMetricPoint(
                    event_time=base + timedelta(days=fold_index * 40, minutes=15 * index),
                    session_id=f"F{fold_index + 1}-S{index // 3:02d}",
                    rank_ic=rank_ic,
                    long_short_return_bps=long_short,
                    one_way_turnover=0.40,
                    coverage=0.95,
                    quantile_monotonicity=monotonicity,
                )
            )
        folds.append(USR1FoldSeries(fold_id=f"fixture-fold-{fold_index + 1}", points=tuple(points)))
    return tuple(folds)


def _r1_fixture(
    scenario: USResearchFixtureScenario,
    manual_run: CandidateGenerationRun,
) -> USR1FixtureSummary:
    candidate = manual_run.accepted_candidates[0]
    protocol = canonical_us_r1_research_protocol()
    denominator = USR1CandidateDenominator(
        protocol_id=protocol.protocol_id,
        a0_phase=USAgentValuePhase.PILOT,
        a0_experiment_id="fixture-a0-experiment",
        a0_gate_review_id="fixture-a0-review",
        a0_gate_decision=USAgentValueGateDecision.INCONCLUSIVE,
        agent_scope=USR1AgentScope.CONTRACTED,
        candidates=(
            USR1CandidateProvenance(
                candidate=candidate,
                source_arms=(USAgentValueArm.MANUAL,),
                source_run_ids=(manual_run.run_id,),
            ),
        ),
    )
    statistical_scenario = (
        USResearchFixtureScenario.KNOWN_NULL
        if scenario is USResearchFixtureScenario.TECHNICAL_FAILURE
        else scenario
    )
    folds = _r1_fold_series(statistical_scenario)
    if statistical_scenario is USResearchFixtureScenario.KNOWN_ALPHA:
        robustness = {BarInterval.MINUTE_5: 0.038, BarInterval.MINUTE_30: 0.032}
        decay = {30: 0.050, 120: 0.022}
    else:
        robustness = {BarInterval.MINUTE_5: 0.0, BarInterval.MINUTE_30: 0.0}
        decay = {30: 0.0, 120: 0.0}
    raw = build_us_r1_raw_candidate_evidence(
        candidate_id=candidate.candidate_id,
        dominant_direction=1,
        primary_folds=folds,
        robustness_rank_ic=robustness,
        decay_rank_ic=decay,
        protocol=protocol,
    )
    blockers = (
        ("fixture:missing_required_fold_bundle",)
        if scenario is USResearchFixtureScenario.TECHNICAL_FAILURE
        else ()
    )
    family = build_us_r1_family_evidence(
        denominator,
        (raw,),
        technical_blockers=blockers,
    )
    assessment: USR1AlphaGateAssessment = assess_us_r1_alpha_gate(family)
    expected = {
        USResearchFixtureScenario.KNOWN_ALPHA: USR1Terminal.ROBUST_FACTOR_FAMILY,
        USResearchFixtureScenario.KNOWN_NULL: USR1Terminal.NO_ROBUST_FACTOR_FAMILY,
        USResearchFixtureScenario.TECHNICAL_FAILURE: USR1Terminal.SYSTEM_FAILURE,
    }[scenario]
    return USR1FixtureSummary(
        scenario=scenario,
        family_evidence_id=family.evidence_id,
        assessment_id=assessment.assessment_id,
        terminal=assessment.terminal,
        robust_candidate_ids=assessment.robust_candidate_ids,
        expectation_met=assessment.terminal is expected,
    )


def run_us_research_fixture_scenario(
    scenario: USResearchFixtureScenario,
) -> USResearchFixtureScenarioResult:
    b0 = _summarize_b0(scenario)
    a0, manual_run = _a0_fixture(scenario)
    r1 = _r1_fixture(scenario, manual_run)
    return USResearchFixtureScenarioResult(scenario=scenario, b0=b0, a0=a0, r1=r1)


def run_us_research_fixture_campaign(
    *,
    generated_at: datetime | None = None,
) -> USResearchFixtureCampaignReport:
    timestamp = generated_at or datetime.now(UTC)
    return USResearchFixtureCampaignReport(
        scenarios=tuple(run_us_research_fixture_scenario(scenario) for scenario in USResearchFixtureScenario),
        generated_at=timestamp,
    )
