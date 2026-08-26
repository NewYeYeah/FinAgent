from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiment_family import CorrectionMethod
from finagent.domain.experiments import ArtifactRef, ArtifactType
from finagent.domain.model_registry import ModelStage
from finagent.research.agent_family_validation import (
    AgentCandidateStatisticalValidation,
    AgentFamilyStatisticalReport,
)
from finagent.research.final_strategy import FinalStrategySpec
from finagent.research.holdout_evaluation import (
    HoldoutEvaluationReport,
    HoldoutEvaluationStatus,
)
from finagent.research.market_validation import (
    AgentMarketValidationMode,
    AgentMarketValidationReport,
)
from finagent.research.programs import ResearchProgram, SQLiteResearchProgramStore
from finagent.research.promotion import (
    ResearchPromotionGate,
    ResearchPromotionService,
    ResearchPromotionStatus,
    SQLiteResearchPromotionStore,
)
from finagent.research.registry import SQLiteResearchRegistry
from finagent.research.validation import (
    DeflatedSharpeResult,
    MultipleTestingResult,
    PBOResult,
    RealityCheckResult,
)


NOW = datetime(2026, 8, 26, 7, 0, tzinfo=UTC)


def _family_report(*, passed: bool = True) -> AgentFamilyStatisticalReport:
    candidate = AgentCandidateStatisticalValidation(
        experiment_id="family-001:candidate:1",
        raw_pvalue=0.001 if passed else 0.8,
        adjusted_pvalue=0.001 if passed else 0.8,
        multiplicity_rejected=passed,
        deflated_sharpe=DeflatedSharpeResult(
            observed_sharpe=1.2,
            benchmark_sharpe=0.2,
            deflated_probability=0.99 if passed else 0.10,
            sample_size=80,
            n_trials=1,
            skewness=0.0,
            kurtosis=3.0,
        ),
        passed=passed,
    )
    return AgentFamilyStatisticalReport(
        family_id="family-001",
        experiment_order=(candidate.experiment_id,),
        observation_count=80,
        dataset_digest="d" * 64,
        multiple_testing=MultipleTestingResult(
            method=CorrectionMethod.HOLM,
            alpha=0.05,
            raw_pvalues=(candidate.raw_pvalue,),
            adjusted_pvalues=(candidate.adjusted_pvalue,),
            rejected=(passed,),
        ),
        pbo=PBOResult(
            probability_of_backtest_overfitting=0.10 if passed else 0.90,
            logits=(),
            combinations_evaluated=1,
            blocks=2,
        ),
        reality_check=RealityCheckResult(
            observed_statistic=1.0,
            pvalue=0.01 if passed else 0.80,
            bootstrap_samples=100,
            block_size=1,
        ),
        candidates=(candidate,),
        dsr_probability_threshold=0.95,
        pbo_threshold=0.50,
    )


def _strategy(report: AgentFamilyStatisticalReport) -> FinalStrategySpec:
    protocol = "{}"
    return FinalStrategySpec(
        program_id="program-001",
        family_id=report.family_id,
        family_validation_report_id=report.report_id,
        selected_experiment_id="family-001:candidate:1",
        selected_feature_digest="f" * 64,
        primary_dataset=ArtifactRef(
            "development-data",
            ArtifactType.DATASET,
            "v1",
            report.dataset_digest,
        ),
        universe=(AssetId("SPY", AssetType.ETF, venue="ARCX", currency="USD"),),
        research_protocol_json=protocol,
        research_protocol_digest=hashlib.sha256(protocol.encode()).hexdigest(),
        selection_rule="unit-test-selection-v1",
        created_at=NOW,
    )


def _holdout_report(
    strategy: FinalStrategySpec,
    *,
    status: HoldoutEvaluationStatus = HoldoutEvaluationStatus.PASSED,
) -> HoldoutEvaluationReport:
    return HoldoutEvaluationReport(
        evaluation_id="holdout-eval-001",
        program_id=strategy.program_id,
        holdout_id="holdout-001",
        holdout_spec_digest="h" * 64,
        eligibility_seal_id="seal-001",
        final_strategy_id=strategy.strategy_id,
        acceptance_policy_id="policy-001",
        acceptance_policy_digest="p" * 64,
        status=status,
        dataset_digest="o" * 64,
        metrics={
            "oos_periods": 40.0,
            "sharpe": 1.1,
            "total_return": 0.08,
            "max_drawdown": -0.07,
            "transaction_cost": 120.0,
            "gross_traded_weight": 4.0,
        },
        rejection_reasons=("holdout acceptance failed",) if status is not HoldoutEvaluationStatus.PASSED else (),
        evidence_key="result:holdout-eval-001",
        accessed_at=NOW + timedelta(minutes=1),
        finished_at=NOW + timedelta(minutes=2),
        error_type="RuntimeError" if status is HoldoutEvaluationStatus.ERROR else "",
        error_message="terminal evaluator error" if status is HoldoutEvaluationStatus.ERROR else "",
    )


def _closed_program_store(tmp_path) -> SQLiteResearchProgramStore:
    store = SQLiteResearchProgramStore(tmp_path / "programs.sqlite")
    store.register(
        ResearchProgram(
            program_id="program-001",
            alpha_budget=0.10,
            max_families=2,
            max_experiments=4,
            sealed_holdout_id="holdout-001",
        )
    )
    store.freeze_program(
        "program-001",
        actor="test",
        reason="final strategy frozen",
        occurred_at=NOW,
    )
    store.consume_sealed_holdout(
        "program-001",
        actor="test",
        accessed_at=NOW + timedelta(minutes=1),
    )
    store.close_program(
        "program-001",
        actor="test",
        reason="sealed holdout completed",
        occurred_at=NOW + timedelta(minutes=2),
    )
    return store


def _service(tmp_path):
    programs = _closed_program_store(tmp_path)
    registry = SQLiteResearchRegistry(tmp_path / "registry.sqlite")
    promotions = SQLiteResearchPromotionStore(tmp_path / "promotions.sqlite")
    return (
        ResearchPromotionService(
            gate=ResearchPromotionGate(program_store=programs),
            promotion_store=promotions,
            registry=registry,
        ),
        promotions,
        registry,
    )


def _provider_validation(*, passed: bool) -> AgentMarketValidationReport:
    return AgentMarketValidationReport(
        validation_id="provider-validation-001",
        mode=AgentMarketValidationMode.CROSS_PROVIDER,
        left_study_id="left",
        right_study_id="right",
        left_provider="primary",
        right_provider="secondary",
        left_data_version="v1",
        right_data_version="v2",
        task_match=True,
        program_match=True,
        family_match=True,
        candidate_family_match=True,
        universe_match=True,
        fold_boundary_match=True,
        provider_calendar_match=True,
        exact_payload_match=False,
        common_folds=4,
        selection_agreement=1.0,
        acceptance_agreement=1.0,
        aggregate_abs_differences={},
        policy_violations=() if passed else ("provider calendar mismatch",),
    )


def test_approved_research_promotion_materializes_validated_model_and_replays(tmp_path) -> None:
    service, promotions, registry = _service(tmp_path)
    family = _family_report(passed=True)
    strategy = _strategy(family)
    holdout = _holdout_report(strategy)

    first = service.promote(
        family_report=family,
        strategy=strategy,
        holdout_report=holdout,
        decided_at=NOW + timedelta(minutes=3),
    )
    assert first.decision.status is ResearchPromotionStatus.APPROVED
    assert first.model is not None
    assert first.model.stage is ModelStage.VALIDATED
    assert promotions.get_for_program("program-001") == first.decision
    assert registry.get_model(first.model.model_id).stage is ModelStage.VALIDATED

    replay = service.promote(
        family_report=family,
        strategy=strategy,
        holdout_report=holdout,
        decided_at=NOW + timedelta(hours=1),
    )
    assert replay.decision == first.decision
    assert replay.model == first.model
    assert len(registry.model_history(first.model.model_id)) == 1


def test_rejected_holdout_produces_terminal_rejection_without_model(tmp_path) -> None:
    service, promotions, registry = _service(tmp_path)
    family = _family_report(passed=True)
    strategy = _strategy(family)
    holdout = _holdout_report(strategy, status=HoldoutEvaluationStatus.REJECTED)

    result = service.promote(
        family_report=family,
        strategy=strategy,
        holdout_report=holdout,
        decided_at=NOW + timedelta(minutes=3),
    )
    assert result.decision.status is ResearchPromotionStatus.REJECTED
    assert result.model is None
    assert "sealed holdout status is rejected" in result.decision.reasons
    assert promotions.get_for_program("program-001") == result.decision
    with pytest.raises(KeyError):
        registry.get_model(f"validated-{strategy.strategy_id}")


def test_failed_provider_validation_rejects_otherwise_valid_promotion(tmp_path) -> None:
    service, _promotions, _registry = _service(tmp_path)
    family = _family_report(passed=True)
    strategy = _strategy(family)
    holdout = _holdout_report(strategy)

    result = service.promote(
        family_report=family,
        strategy=strategy,
        holdout_report=holdout,
        provider_validation=_provider_validation(passed=False),
        decided_at=NOW + timedelta(minutes=3),
    )
    assert result.decision.status is ResearchPromotionStatus.REJECTED
    assert "provider validation report did not pass" in result.decision.reasons


def test_identity_drift_fails_before_promotion_decision_is_persisted(tmp_path) -> None:
    service, promotions, _registry = _service(tmp_path)
    family = _family_report(passed=True)
    strategy = _strategy(family)
    holdout = _holdout_report(strategy)
    mismatched = HoldoutEvaluationReport(
        evaluation_id=holdout.evaluation_id,
        program_id=holdout.program_id,
        holdout_id=holdout.holdout_id,
        holdout_spec_digest=holdout.holdout_spec_digest,
        eligibility_seal_id=holdout.eligibility_seal_id,
        final_strategy_id="different-final-strategy",
        acceptance_policy_id=holdout.acceptance_policy_id,
        acceptance_policy_digest=holdout.acceptance_policy_digest,
        status=holdout.status,
        dataset_digest=holdout.dataset_digest,
        metrics=holdout.metrics,
        rejection_reasons=holdout.rejection_reasons,
        evidence_key=holdout.evidence_key,
        accessed_at=holdout.accessed_at,
        finished_at=holdout.finished_at,
    )

    with pytest.raises(ValueError, match="frozen final strategy"):
        service.promote(
            family_report=family,
            strategy=strategy,
            holdout_report=mismatched,
            decided_at=NOW + timedelta(minutes=3),
        )
    with pytest.raises(KeyError):
        promotions.get_for_program("program-001")
