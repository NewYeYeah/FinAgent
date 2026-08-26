from __future__ import annotations

from datetime import UTC, datetime

import pytest

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiment_family import CorrectionMethod, ExperimentFamily, ExperimentFamilyStatus
from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentResult, ExperimentSpec
from finagent.memory import (
    AgentResearchMemoryView,
    AtomicScopedEvidenceWriter,
    EvidenceVisibility,
    MemoryNode,
    MemoryNodeType,
    ResearchMemoryService,
    SQLiteMemoryVisibilityStore,
    SQLiteResearchMemoryStore,
)
from finagent.research import (
    AgentCandidateStatisticalValidation,
    AgentFamilyStatisticalReport,
    AgentMarketProgramPlan,
    AgentMarketResearchConfig,
    DeflatedSharpeResult,
    FinalStrategyFreezer,
    FinalStrategySelector,
    FunctionSealedHoldoutBackend,
    MultipleTestingResult,
    PBOResult,
    RealityCheckResult,
    ResearchProgram,
    SQLiteAgentFamilyValidationStore,
    SQLiteFinalStrategyStore,
    SQLiteResearchProgramStore,
    SQLiteResearchRegistry,
    SealedHoldoutEvaluator,
)


NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)


def _universe() -> tuple[AssetId, ...]:
    return tuple(
        AssetId(symbol, AssetType.ETF, venue="ARCX", currency="USD")
        for symbol in ("SPY", "QQQ")
    )


def _dsr(probability: float) -> DeflatedSharpeResult:
    return DeflatedSharpeResult(
        observed_sharpe=0.8,
        benchmark_sharpe=0.1,
        deflated_probability=probability,
        sample_size=80,
        n_trials=2,
        skewness=0.0,
        kurtosis=3.0,
    )


def _governed_state(tmp_path):
    registry = SQLiteResearchRegistry(tmp_path / "research.sqlite")
    programs = SQLiteResearchProgramStore(tmp_path / "programs.sqlite")
    strategies = SQLiteFinalStrategyStore(tmp_path / "strategies.sqlite")
    validations = SQLiteAgentFamilyValidationStore(tmp_path / "validations.sqlite")
    programs.register(
        ResearchProgram(
            program_id="program-holdout",
            alpha_budget=0.05,
            max_families=2,
            max_experiments=4,
            sealed_holdout_id="sealed-dataset-v1",
        )
    )
    dataset = ArtifactRef("dataset-primary", ArtifactType.DATASET, "v1", "d" * 64)
    digests = ("a" * 64, "b" * 64)
    experiment_ids = []
    for index, digest in enumerate(digests, start=1):
        experiment_id = f"family-holdout:candidate:{index}"
        registry.register_experiment(
            ExperimentSpec(
                experiment_id=experiment_id,
                hypothesis=f"candidate {index}",
                dataset=dataset,
                code=ArtifactRef(f"code-{index}", ArtifactType.CODE, "v1", digest),
                universe=_universe(),
                parameters={"candidate": index},
                seed=0,
                metadata={
                    "generated_feature_digest": digest,
                    "program_id": "program-holdout",
                    "family_id": "family-holdout",
                },
            )
        )
        experiment_ids.append(experiment_id)
    registry.register_family(
        ExperimentFamily(
            family_id="family-holdout",
            research_question="sealed holdout test",
            primary_metric="net_sharpe",
            created_at=NOW,
            alpha=0.05,
            correction_method=CorrectionMethod.HOLM,
            metadata={
                "program_id": "program-holdout",
                "dataset_digest": dataset.digest,
            },
        )
    )
    for experiment_id in experiment_ids:
        registry.add_experiment_to_family("family-holdout", experiment_id, added_at=NOW)
    registry.transition_family("family-holdout", ExperimentFamilyStatus.FROZEN)
    experiment_order = tuple(sorted(experiment_ids))
    programs.reserve_plan(
        AgentMarketProgramPlan(
            program_id="program-holdout",
            family_id="family-holdout",
            alpha=0.05,
            variants=digests,
        ),
        task_id="task-holdout",
        reserved_at=NOW,
    )
    family_report = AgentFamilyStatisticalReport(
        family_id="family-holdout",
        experiment_order=experiment_order,
        observation_count=80,
        dataset_digest=dataset.digest,
        multiple_testing=MultipleTestingResult(
            CorrectionMethod.HOLM,
            0.05,
            (0.001, 0.20),
            (0.002, 0.20),
            (True, False),
        ),
        pbo=PBOResult(0.10, (), 20, 8),
        reality_check=RealityCheckResult(2.0, 0.01, 100, 4),
        candidates=(
            AgentCandidateStatisticalValidation(
                experiment_order[0], 0.001, 0.002, True, _dsr(0.99), True
            ),
            AgentCandidateStatisticalValidation(
                experiment_order[1], 0.20, 0.20, False, _dsr(0.60), False
            ),
        ),
        dsr_probability_threshold=0.95,
        pbo_threshold=0.50,
    )
    validations.register(family_report)
    strategy = FinalStrategyFreezer(
        selector=FinalStrategySelector(registry),
        strategy_store=strategies,
        program_store=programs,
    ).freeze(
        program_id="program-holdout",
        report=family_report,
        config=AgentMarketResearchConfig(max_candidates=2),
        actor="test-suite",
        frozen_at=NOW,
    ).strategy
    memory = SQLiteResearchMemoryStore(tmp_path / "memory.sqlite")
    visibility = SQLiteMemoryVisibilityStore(tmp_path / "memory.sqlite")
    return registry, programs, strategies, validations, strategy, memory, visibility


def test_sealed_holdout_is_consumed_once_and_numeric_result_is_never_agent_visible(tmp_path):
    registry, programs, strategies, validations, strategy, memory, visibility = _governed_state(
        tmp_path
    )
    calls = []

    def evaluate(_strategy, holdout_id):
        calls.append(holdout_id)
        return {"net_sharpe": 1.15, "max_drawdown": -0.08}

    evaluator = SealedHoldoutEvaluator(
        program_store=programs,
        research_registry=registry,
        strategy_store=strategies,
        family_validation_store=validations,
        memory_store=memory,
        visibility_store=visibility,
        backend=FunctionSealedHoldoutBackend(evaluate, version="unit-holdout-v1"),
    )
    report = evaluator.evaluate(strategy, actor="test-suite", accessed_at=NOW)

    assert calls == ["sealed-dataset-v1"]
    assert report.metrics["net_sharpe"] == pytest.approx(1.15)
    scope = visibility.get(report.evidence_key)
    assert scope is not None
    assert scope.visibility is EvidenceVisibility.SEALED_HOLDOUT
    assert scope.program_id == "program-holdout"
    assert memory.get_node(report.evidence_key).metadata["strategy_id"] == strategy.strategy_id

    source_key = f"artifact:{strategy.strategy_id}"
    agent_view = AgentResearchMemoryView(
        ResearchMemoryService(memory), visibility, program_id="program-holdout"
    )
    graph = agent_view.traverse(source_key, max_depth=2, max_nodes=20)
    assert report.evidence_key not in {node.key for node in graph.nodes}
    assert graph.truncated is True

    with pytest.raises(PermissionError, match="already been consumed"):
        evaluator.evaluate(strategy, actor="test-suite", accessed_at=NOW)
    assert calls == ["sealed-dataset-v1"]


def test_backend_failure_burns_holdout_and_records_only_sealed_failure(tmp_path):
    registry, programs, strategies, validations, strategy, memory, visibility = _governed_state(
        tmp_path
    )
    calls = 0

    def fail(_strategy, _holdout_id):
        nonlocal calls
        calls += 1
        raise RuntimeError("backend should not be retried after seeing holdout")

    evaluator = SealedHoldoutEvaluator(
        program_store=programs,
        research_registry=registry,
        strategy_store=strategies,
        family_validation_store=validations,
        memory_store=memory,
        visibility_store=visibility,
        backend=FunctionSealedHoldoutBackend(fail, version="failing-backend-v1"),
    )
    with pytest.raises(RuntimeError, match="should not be retried"):
        evaluator.evaluate(strategy, actor="test-suite", accessed_at=NOW)

    failures = memory.failures()
    assert len(failures) == 1
    failure_key = f"failure:{failures[0].failure_id}"
    scope = visibility.get(failure_key)
    assert scope is not None and scope.visibility is EvidenceVisibility.SEALED_HOLDOUT
    agent_view = AgentResearchMemoryView(
        ResearchMemoryService(memory), visibility, program_id="program-holdout"
    )
    assert agent_view.failures() == ()

    with pytest.raises(PermissionError, match="already been consumed"):
        evaluator.evaluate(strategy, actor="test-suite", accessed_at=NOW)
    assert calls == 1


def test_atomic_writer_refuses_retroactive_sensitive_scope_on_legacy_result(tmp_path):
    memory = SQLiteResearchMemoryStore(tmp_path / "memory.sqlite")
    visibility = SQLiteMemoryVisibilityStore(tmp_path / "memory.sqlite")
    memory.register_node(MemoryNode(MemoryNodeType.EXPERIMENT, "exp-1", "exp-1", NOW))
    result = ExperimentResult("legacy-run", {"sharpe": 0.4}, True)
    ResearchMemoryService(memory).register_result("exp-1", result, NOW)

    writer = AtomicScopedEvidenceWriter(memory, visibility)
    with pytest.raises(ValueError, match="retroactively classify"):
        writer.register_result(
            experiment_id="exp-1",
            result=result,
            created_at=NOW,
            visibility=EvidenceVisibility.SEALED_HOLDOUT,
            program_id="program-1",
        )
    assert visibility.get("result:legacy-run") is None


def test_atomic_writer_rolls_back_result_when_source_lineage_is_missing(tmp_path):
    memory = SQLiteResearchMemoryStore(tmp_path / "memory.sqlite")
    visibility = SQLiteMemoryVisibilityStore(tmp_path / "memory.sqlite")
    writer = AtomicScopedEvidenceWriter(memory, visibility)
    result = ExperimentResult("orphan-run", {"sharpe": 0.1}, True)

    with pytest.raises(KeyError, match="source memory node"):
        writer.register_result_from_source(
            source_key="artifact:missing",
            result=result,
            created_at=NOW,
            visibility=EvidenceVisibility.SEALED_HOLDOUT,
            program_id="program-1",
        )
    with pytest.raises(KeyError):
        memory.get_node("result:orphan-run")
    assert visibility.get("result:orphan-run") is None
