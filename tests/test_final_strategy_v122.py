from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiment_family import CorrectionMethod, ExperimentFamily, ExperimentFamilyStatus
from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentSpec
from finagent.research import (
    AgentCandidateStatisticalValidation,
    AgentFamilyStatisticalReport,
    AgentMarketProgramPlan,
    AgentMarketResearchConfig,
    DeflatedSharpeResult,
    FINAL_STRATEGY_SELECTION_RULE,
    FinalStrategyFreezer,
    FinalStrategySelector,
    MultipleTestingResult,
    PBOResult,
    RealityCheckResult,
    ResearchProgram,
    ResearchProgramStatus,
    SQLiteFinalStrategyStore,
    SQLiteResearchProgramStore,
    SQLiteResearchRegistry,
)


NOW = datetime(2026, 8, 26, 7, 0, tzinfo=UTC)


def _universe() -> tuple[AssetId, ...]:
    return tuple(
        AssetId(symbol, AssetType.ETF, venue="ARCX", currency="USD")
        for symbol in ("SPY", "QQQ")
    )


def _setup(tmp_path):
    registry = SQLiteResearchRegistry(tmp_path / "registry.sqlite")
    programs = SQLiteResearchProgramStore(tmp_path / "programs.sqlite")
    programs.register(
        ResearchProgram(
            program_id="program-final",
            alpha_budget=0.05,
            max_families=3,
            max_experiments=8,
            sealed_holdout_id="holdout-final",
        )
    )
    dataset = ArtifactRef("dataset-primary", ArtifactType.DATASET, "v1", "d" * 64)
    experiment_ids = []
    digests = ("a" * 64, "b" * 64, "c" * 64)
    for index, digest in enumerate(digests, start=1):
        experiment_id = f"family-final:candidate:{index}"
        registry.register_experiment(
            ExperimentSpec(
                experiment_id=experiment_id,
                hypothesis=f"candidate {index}",
                dataset=dataset,
                code=ArtifactRef(f"code-{index}", ArtifactType.CODE, "v1", digest),
                universe=_universe(),
                parameters={"feature_digest": digest},
                seed=0,
                metadata={
                    "generated_feature_digest": digest,
                    "program_id": "program-final",
                    "family_id": "family-final",
                },
            )
        )
        experiment_ids.append(experiment_id)
    registry.register_family(
        ExperimentFamily(
            family_id="family-final",
            research_question="freeze one final development winner",
            primary_metric="net_sharpe",
            created_at=NOW,
            alpha=0.05,
            correction_method=CorrectionMethod.HOLM,
            metadata={
                "program_id": "program-final",
                "dataset_digest": dataset.digest,
            },
        )
    )
    for experiment_id in experiment_ids:
        registry.add_experiment_to_family("family-final", experiment_id, added_at=NOW)
    registry.transition_family("family-final", ExperimentFamilyStatus.FROZEN)
    programs.reserve_plan(
        AgentMarketProgramPlan(
            program_id="program-final",
            family_id="family-final",
            alpha=0.05,
            variants=digests,
        ),
        task_id="task-final",
        reserved_at=NOW,
    )
    return registry, programs, tuple(sorted(experiment_ids)), dataset


def _dsr(probability: float, sharpe: float) -> DeflatedSharpeResult:
    return DeflatedSharpeResult(
        observed_sharpe=sharpe,
        benchmark_sharpe=0.1,
        deflated_probability=probability,
        sample_size=80,
        n_trials=3,
        skewness=0.0,
        kurtosis=3.0,
    )


def _report(experiment_order: tuple[str, ...], *, no_eligible: bool = False):
    candidates = (
        AgentCandidateStatisticalValidation(
            experiment_order[0], 0.001, 0.003, True, _dsr(0.97, 0.8), not no_eligible
        ),
        AgentCandidateStatisticalValidation(
            experiment_order[1], 0.002, 0.004, True, _dsr(0.99, 0.7), not no_eligible
        ),
        AgentCandidateStatisticalValidation(
            experiment_order[2], 0.40, 0.40, False, _dsr(0.55, 0.1), False
        ),
    )
    return AgentFamilyStatisticalReport(
        family_id="family-final",
        experiment_order=experiment_order,
        observation_count=80,
        dataset_digest="d" * 64,
        multiple_testing=MultipleTestingResult(
            CorrectionMethod.HOLM,
            0.05,
            (0.001, 0.002, 0.40),
            (0.003, 0.004, 0.40),
            (True, True, False),
        ),
        pbo=PBOResult(0.10, (), 20, 8),
        reality_check=RealityCheckResult(2.0, 0.01, 100, 4),
        candidates=candidates,
        dsr_probability_threshold=0.95,
        pbo_threshold=0.50,
    )


def test_selector_uses_predeclared_dsr_adjusted_pvalue_tiebreak_and_freezes_protocol(tmp_path):
    registry, _programs, experiment_order, dataset = _setup(tmp_path)
    selector = FinalStrategySelector(registry)
    config = AgentMarketResearchConfig(max_candidates=3)
    strategy = selector.select(
        program_id="program-final",
        report=_report(experiment_order),
        config=config,
        created_at=NOW,
    )

    assert strategy.selected_experiment_id == experiment_order[1]
    assert strategy.selected_feature_digest == "b" * 64
    assert strategy.primary_dataset == dataset
    assert strategy.universe == _universe()
    assert strategy.selection_rule == FINAL_STRATEGY_SELECTION_RULE
    assert strategy.research_protocol_digest
    assert '"execution_price_field":"open"' in strategy.research_protocol_json
    assert '"execution_lag_events":1' in strategy.research_protocol_json


def test_selector_rejects_family_without_statistically_eligible_candidate(tmp_path):
    registry, _programs, experiment_order, _dataset = _setup(tmp_path)
    with pytest.raises(PermissionError, match="no statistically eligible"):
        FinalStrategySelector(registry).select(
            program_id="program-final",
            report=_report(experiment_order, no_eligible=True),
            config=AgentMarketResearchConfig(max_candidates=3),
            created_at=NOW,
        )


def test_final_strategy_is_persisted_before_research_program_is_frozen(tmp_path):
    registry, programs, experiment_order, _dataset = _setup(tmp_path)
    strategy_store = SQLiteFinalStrategyStore(tmp_path / "final-strategy.sqlite")
    freezer = FinalStrategyFreezer(
        selector=FinalStrategySelector(registry),
        strategy_store=strategy_store,
        program_store=programs,
    )
    frozen = freezer.freeze(
        program_id="program-final",
        report=_report(experiment_order),
        config=AgentMarketResearchConfig(max_candidates=3),
        actor="test-suite",
        frozen_at=NOW,
    )

    stored = strategy_store.for_family("program-final", "family-final")
    assert stored["strategy_id"] == frozen.strategy.strategy_id
    assert programs.get("program-final").status is ResearchProgramStatus.FROZEN
    assert frozen.lifecycle_event.to_status is ResearchProgramStatus.FROZEN

    with pytest.raises(PermissionError, match="open program"):
        programs.reserve_plan(
            AgentMarketProgramPlan(
                program_id="program-final",
                family_id="family-late",
                alpha=0.001,
                variants=("late",),
            ),
            task_id="late-task",
        )


def test_final_strategy_store_rejects_a_second_winner_for_same_family(tmp_path):
    registry, _programs, experiment_order, _dataset = _setup(tmp_path)
    selector = FinalStrategySelector(registry)
    store = SQLiteFinalStrategyStore(tmp_path / "final-strategy.sqlite")
    config = AgentMarketResearchConfig(max_candidates=3)
    first = selector.select(
        program_id="program-final",
        report=_report(experiment_order),
        config=config,
        created_at=NOW,
    )
    store.register(first)
    store.register(first)

    report = _report(experiment_order)
    changed_candidates = (
        replace(report.candidates[0], deflated_sharpe=_dsr(0.999, 0.8), passed=True),
        replace(report.candidates[1], deflated_sharpe=_dsr(0.96, 0.7), passed=True),
        report.candidates[2],
    )
    changed_report = replace(report, candidates=changed_candidates)
    second = selector.select(
        program_id="program-final",
        report=changed_report,
        config=config,
        created_at=NOW,
    )
    assert second.selected_experiment_id != first.selected_experiment_id
    with pytest.raises(ValueError, match="different final strategy"):
        store.register(second)


def test_protocol_change_changes_final_strategy_identity(tmp_path):
    registry, _programs, experiment_order, _dataset = _setup(tmp_path)
    selector = FinalStrategySelector(registry)
    report = _report(experiment_order)
    baseline = selector.select(
        program_id="program-final",
        report=report,
        config=AgentMarketResearchConfig(max_candidates=3),
        created_at=NOW,
    )
    changed = selector.select(
        program_id="program-final",
        report=report,
        config=AgentMarketResearchConfig(max_candidates=3, transaction_cost_bps=12.0),
        created_at=NOW,
    )
    assert changed.research_protocol_digest != baseline.research_protocol_digest
    assert changed.strategy_id != baseline.strategy_id
