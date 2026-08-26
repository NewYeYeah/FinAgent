from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from finagent.domain.experiments import ArtifactRef, ArtifactType
from finagent.domain.model_registry import ModelStage, RegisteredModel
from finagent.operations import HumanApproval, SQLitePaperBrokerStore
from finagent.operations.research_handoff import (
    RESEARCH_MODEL_PAPER_REQUEST,
    ResearchPaperHandoffService,
    SQLiteResearchPaperHandoffStore,
)
from finagent.research import SQLiteResearchRegistry
from finagent.research.promotion import (
    ResearchPromotionDecision,
    ResearchPromotionStatus,
    SQLiteResearchPromotionStore,
)


NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)


def _decision(*, approved: bool = True) -> ResearchPromotionDecision:
    return ResearchPromotionDecision(
        program_id="program-001",
        family_id="family-001",
        family_validation_report_id="family-report-001",
        final_strategy_id="final-strategy-001",
        selected_experiment_id="family-001:candidate:1",
        selected_feature_digest="f" * 64,
        holdout_evaluation_id="holdout-eval-001",
        holdout_dataset_digest="h" * 64,
        status=(
            ResearchPromotionStatus.APPROVED
            if approved
            else ResearchPromotionStatus.REJECTED
        ),
        reasons=() if approved else ("sealed holdout status is rejected",),
        decided_at=NOW,
    )


def _state(tmp_path, *, approved: bool = True):
    registry = SQLiteResearchRegistry(tmp_path / "registry.sqlite")
    promotions = SQLiteResearchPromotionStore(tmp_path / "promotions.sqlite")
    handoffs = SQLiteResearchPaperHandoffStore(tmp_path / "handoffs.sqlite")
    paper_store = SQLitePaperBrokerStore(tmp_path / "paper.sqlite")
    decision = _decision(approved=approved)
    promotions.register(decision)

    artifact = ArtifactRef(
        artifact_id="research-model:001",
        artifact_type=ArtifactType.MODEL,
        version="1.2.2",
        digest="m" * 64,
    )
    candidate = RegisteredModel(
        model_id="validated-final-strategy-001",
        family="generated-feature-strategy",
        artifact=artifact,
        stage=ModelStage.CANDIDATE,
        created_at=NOW,
        metrics={"sharpe": 1.0},
        metadata={
            "promotion_id": decision.promotion_id,
            "program_id": decision.program_id,
            "family_id": decision.family_id,
            "final_strategy_id": decision.final_strategy_id,
            "holdout_evaluation_id": decision.holdout_evaluation_id,
        },
    )
    registry.register_model(candidate)
    model = registry.promote_model(
        candidate.model_id,
        ModelStage.VALIDATED,
        changed_at=NOW,
        reason="research promotion approved",
        actor="research-promotion-gate",
    )
    service = ResearchPaperHandoffService(
        registry=registry,
        promotion_store=promotions,
        handoff_store=handoffs,
        paper_store=paper_store,
    )
    return service, registry, promotions, handoffs, paper_store, decision, model


def _approval(request_id: str, *, approval_id: str = "approval-001") -> HumanApproval:
    return HumanApproval(
        approval_id=approval_id,
        request_type=RESEARCH_MODEL_PAPER_REQUEST,
        snapshot_id=request_id,
        approved_by="human-reviewer",
        approved_at=NOW + timedelta(minutes=2),
        reason="approve validated research model for paper evaluation",
    )


def test_request_is_non_mutating_and_binds_validated_model(tmp_path) -> None:
    service, registry, _promotions, handoffs, _paper, decision, model = _state(tmp_path)
    result = service.request(
        decision=decision,
        model_id=model.model_id,
        created_at=NOW + timedelta(minutes=1),
    )

    assert result.request.to_dict()["mutation_performed"] is False
    assert result.request.to_dict()["requires_human_approval"] is True
    assert result.request.promotion_id == decision.promotion_id
    assert handoffs.get_request(result.request.request_id) == result.request
    assert registry.get_model(model.model_id).stage is ModelStage.VALIDATED


def test_exact_human_approval_promotes_validated_model_to_paper_and_replays(tmp_path) -> None:
    service, registry, _promotions, handoffs, paper_store, decision, model = _state(tmp_path)
    requested = service.request(
        decision=decision,
        model_id=model.model_id,
        created_at=NOW + timedelta(minutes=1),
    )
    approval = _approval(requested.request.request_id)

    applied = service.apply(
        request_id=requested.request.request_id,
        approval=approval,
        applied_at=NOW + timedelta(minutes=3),
        applied_by="human-reviewer",
    )
    assert applied.model.stage is ModelStage.PAPER
    assert applied.application is not None
    assert applied.application.approval_id == approval.approval_id
    assert handoffs.get_application(requested.request.request_id) == applied.application
    assert registry.get_model(model.model_id).stage is ModelStage.PAPER
    assert [event.to_stage for event in registry.model_history(model.model_id)] == [
        ModelStage.VALIDATED,
        ModelStage.PAPER,
    ]
    assert any(
        event["event_type"] == "research_model_promoted_to_paper"
        for event in paper_store.list_events()
    )

    replay = service.apply(
        request_id=requested.request.request_id,
        approval=approval,
        applied_at=NOW + timedelta(hours=1),
        applied_by="human-reviewer",
    )
    assert replay == applied
    assert [event.to_stage for event in registry.model_history(model.model_id)] == [
        ModelStage.VALIDATED,
        ModelStage.PAPER,
    ]


def test_wrong_approval_snapshot_or_type_cannot_mutate_model(tmp_path) -> None:
    service, registry, _promotions, _handoffs, _paper, decision, model = _state(tmp_path)
    requested = service.request(
        decision=decision,
        model_id=model.model_id,
        created_at=NOW + timedelta(minutes=1),
    )
    wrong_snapshot = HumanApproval(
        approval_id="wrong-snapshot",
        request_type=RESEARCH_MODEL_PAPER_REQUEST,
        snapshot_id="different-request",
        approved_by="human-reviewer",
        approved_at=NOW + timedelta(minutes=2),
    )
    with pytest.raises(ValueError, match="snapshot_id"):
        service.apply(
            request_id=requested.request.request_id,
            approval=wrong_snapshot,
            applied_at=NOW + timedelta(minutes=3),
            applied_by="human-reviewer",
        )

    wrong_type = HumanApproval(
        approval_id="wrong-type",
        request_type="rebalance",
        snapshot_id=requested.request.request_id,
        approved_by="human-reviewer",
        approved_at=NOW + timedelta(minutes=2),
    )
    with pytest.raises(ValueError, match="request_type"):
        service.apply(
            request_id=requested.request.request_id,
            approval=wrong_type,
            applied_at=NOW + timedelta(minutes=3),
            applied_by="human-reviewer",
        )
    assert registry.get_model(model.model_id).stage is ModelStage.VALIDATED


def test_rejected_research_cannot_enter_paper_handoff(tmp_path) -> None:
    service, registry, _promotions, _handoffs, _paper, decision, model = _state(
        tmp_path,
        approved=False,
    )
    with pytest.raises(PermissionError, match="rejected research"):
        service.request(
            decision=decision,
            model_id=model.model_id,
            created_at=NOW + timedelta(minutes=1),
        )
    assert registry.get_model(model.model_id).stage is ModelStage.VALIDATED


def test_second_approval_cannot_replace_terminal_handoff_application(tmp_path) -> None:
    service, _registry, _promotions, _handoffs, _paper, decision, model = _state(tmp_path)
    requested = service.request(
        decision=decision,
        model_id=model.model_id,
        created_at=NOW + timedelta(minutes=1),
    )
    first = _approval(requested.request.request_id, approval_id="approval-first")
    service.apply(
        request_id=requested.request.request_id,
        approval=first,
        applied_at=NOW + timedelta(minutes=3),
        applied_by="human-reviewer",
    )
    second = _approval(requested.request.request_id, approval_id="approval-second")
    with pytest.raises(PermissionError, match="different approval"):
        service.apply(
            request_id=requested.request.request_id,
            approval=second,
            applied_at=NOW + timedelta(minutes=4),
            applied_by="human-reviewer",
        )
