from datetime import datetime, timedelta, timezone

import pytest

from finagent.agents.supervisor import (
    OperatingPolicyRegistry,
    PortfolioBenchmarkSummary,
    PortfolioHealthSnapshot,
    SQLitePortfolioSupervisionStore,
)
from finagent.operations import (
    ApprovalControl,
    ApprovalRevocation,
    HumanApproval,
    OperationalApprovalService,
    OperationalDrillResult,
    OperationalDrillType,
    OperationalIncident,
    OperationalIncidentCategory,
    OperationalIncidentSeverity,
    OperationalJournal,
    OperationalSession,
    PaperAcceptanceEvaluator,
    PaperAcceptancePolicy,
    SQLiteOperationalEvidenceStore,
    SQLitePaperBrokerStore,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 25, 13, 0, tzinfo=UTC)


def _health_snapshot(snapshot_id="health-v1"):
    return PortfolioHealthSnapshot(
        snapshot_id=snapshot_id,
        asof=NOW,
        observed_at=NOW,
        data_asof=NOW,
        selected_constructor="mean_variance",
        checks=(),
        benchmarks=(
            PortfolioBenchmarkSummary("mean_variance", 0.01, 0.009, 0.1, 0.05, 1.0, 1.0),
        ),
        stresses=(),
        weight_drifts=(),
        rebalance_required=False,
        rebalance_turnover=0.0,
        rebalance_max_weight_drift=0.0,
        rebalance_reasons=(),
    )


def test_operational_evidence_is_immutable_and_round_trips(tmp_path):
    store = SQLiteOperationalEvidenceStore(tmp_path / "evidence.db")
    session = OperationalSession("session-1", NOW, NOW + timedelta(hours=6), 10_000.0, 10_100.0)
    store.register_session(session)
    store.register_session(session)
    assert store.list_sessions() == (session,)

    conflicting = OperationalSession("session-1", NOW, NOW + timedelta(hours=6), 10_000.0, 9_900.0)
    with pytest.raises(ValueError, match="immutable"):
        store.register_session(conflicting)

    drill = OperationalDrillResult(
        "restart-1",
        OperationalDrillType.RESTART_RECOVERY,
        NOW + timedelta(hours=7),
        True,
        "operator",
    )
    store.register_drill(drill)
    assert store.list_drills() == (drill,)


def test_operational_journal_and_acceptance_gate(tmp_path):
    broker_store = SQLitePaperBrokerStore(tmp_path / "paper.db")
    evidence = SQLiteOperationalEvidenceStore(tmp_path / "evidence.db")
    for index in range(2):
        start = NOW + timedelta(days=index)
        evidence.register_session(
            OperationalSession(f"session-{index}", start, start + timedelta(hours=6), 10_000.0, 10_010.0)
        )
        broker_store.record_event(
            "order_registered",
            start + timedelta(minutes=1),
            {"client_order_id": f"o-{index}", "status": "new"},
        )
        broker_store.record_event(
            "fill",
            start + timedelta(minutes=2),
            {"client_order_id": f"o-{index}", "quantity": 1.0, "price": 100.0},
        )
        broker_store.record_event(
            "reconciliation",
            start + timedelta(minutes=3),
            {"snapshot_id": f"s-{index}", "critical_count": 0, "issue_codes": []},
        )
    evidence.register_drill(
        OperationalDrillResult(
            "restart-ok",
            OperationalDrillType.RESTART_RECOVERY,
            NOW + timedelta(hours=8),
            True,
            "operator",
        )
    )
    evidence.register_drill(
        OperationalDrillResult(
            "kill-ok",
            OperationalDrillType.KILL_SWITCH,
            NOW + timedelta(hours=9),
            True,
            "operator",
        )
    )

    journal = OperationalJournal(broker_store=broker_store, evidence_store=evidence)
    policy = PaperAcceptancePolicy(
        min_sessions=2,
        min_reconciliations=2,
        max_rejected_order_rate=0.0,
        max_critical_reconciliation_rate=0.0,
        max_kill_switch_trips=0,
        min_restart_recovery_drills=1,
        min_kill_switch_drills=1,
        max_critical_incidents=0,
        max_idempotency_failures=0,
    )
    evaluator = PaperAcceptanceEvaluator(journal=journal, evidence_store=evidence, policy=policy)
    report = evaluator.evaluate(
        period_start=NOW - timedelta(minutes=1),
        period_end=NOW + timedelta(days=2),
        evaluated_at=NOW + timedelta(days=2, minutes=1),
    )
    assert report.accepted
    assert report.metrics.session_count == 2
    assert report.metrics.fill_count == 2
    assert report.metrics.reconciliation_count == 2


def test_acceptance_gate_rejects_idempotency_incident(tmp_path):
    broker_store = SQLitePaperBrokerStore(tmp_path / "paper.db")
    evidence = SQLiteOperationalEvidenceStore(tmp_path / "evidence.db")
    evidence.register_session(OperationalSession("session", NOW, NOW + timedelta(hours=6), 100.0, 100.0))
    broker_store.record_event("reconciliation", NOW + timedelta(minutes=1), {"critical_count": 0})
    evidence.register_drill(
        OperationalDrillResult("restart", OperationalDrillType.RESTART_RECOVERY, NOW + timedelta(minutes=2), True, "operator")
    )
    evidence.register_drill(
        OperationalDrillResult("kill", OperationalDrillType.KILL_SWITCH, NOW + timedelta(minutes=3), True, "operator")
    )
    evidence.register_incident(
        OperationalIncident(
            "incident-1",
            OperationalIncidentCategory.IDEMPOTENCY,
            OperationalIncidentSeverity.CRITICAL,
            NOW + timedelta(minutes=4),
            "duplicate order changed financial state",
        )
    )
    evaluator = PaperAcceptanceEvaluator(
        journal=OperationalJournal(broker_store=broker_store, evidence_store=evidence),
        evidence_store=evidence,
        policy=PaperAcceptancePolicy(
            min_sessions=1,
            min_reconciliations=1,
            min_restart_recovery_drills=1,
            min_kill_switch_drills=1,
        ),
    )
    report = evaluator.evaluate(
        period_start=NOW - timedelta(minutes=1),
        period_end=NOW + timedelta(hours=7),
        evaluated_at=NOW + timedelta(hours=8),
    )
    assert not report.accepted
    failed = {check.name for check in report.checks if not check.passed}
    assert "critical_incidents" in failed
    assert "idempotency_failures" in failed


def test_approval_expiry_and_revocation_are_enforced_when_evidence_store_is_enabled(tmp_path):
    broker_store = SQLitePaperBrokerStore(tmp_path / "paper.db")
    supervision_store = SQLitePortfolioSupervisionStore(tmp_path / "supervision.db")
    supervision_store.register(_health_snapshot())
    evidence = SQLiteOperationalEvidenceStore(tmp_path / "evidence.db")
    service = OperationalApprovalService(
        broker_store=broker_store,
        supervision_store=supervision_store,
        operating_policies=OperatingPolicyRegistry.reference(),
        approval_evidence_store=evidence,
    )
    request = {
        "request_type": "human_review",
        "snapshot_id": "health-v1",
        "mutation_performed": False,
    }

    expired = HumanApproval(
        "approval-expired",
        "human_review",
        "health-v1",
        "operator",
        NOW + timedelta(minutes=1),
    )
    evidence.register_approval_control(
        ApprovalControl("approval-expired", NOW, NOW + timedelta(minutes=2))
    )
    with pytest.raises(PermissionError, match="expired"):
        service.apply(
            request_payload=request,
            approval=expired,
            applied_at=NOW + timedelta(minutes=3),
            applied_by="controller",
        )

    revoked = HumanApproval(
        "approval-revoked",
        "human_review",
        "health-v1",
        "operator",
        NOW + timedelta(minutes=1),
    )
    evidence.register_approval_control(
        ApprovalControl("approval-revoked", NOW, NOW + timedelta(hours=1))
    )
    evidence.revoke_approval(
        ApprovalRevocation(
            "approval-revoked",
            NOW + timedelta(minutes=2),
            "operator",
            "request superseded",
        )
    )
    with pytest.raises(PermissionError, match="revoked"):
        service.apply(
            request_payload=request,
            approval=revoked,
            applied_at=NOW + timedelta(minutes=3),
            applied_by="controller",
        )


def test_valid_controlled_approval_can_be_applied(tmp_path):
    broker_store = SQLitePaperBrokerStore(tmp_path / "paper.db")
    supervision_store = SQLitePortfolioSupervisionStore(tmp_path / "supervision.db")
    supervision_store.register(_health_snapshot())
    evidence = SQLiteOperationalEvidenceStore(tmp_path / "evidence.db")
    service = OperationalApprovalService(
        broker_store=broker_store,
        supervision_store=supervision_store,
        operating_policies=OperatingPolicyRegistry.reference(),
        approval_evidence_store=evidence,
    )
    approval = HumanApproval(
        "approval-valid",
        "human_review",
        "health-v1",
        "operator",
        NOW + timedelta(minutes=1),
    )
    evidence.register_approval_control(
        ApprovalControl(
            "approval-valid",
            NOW + timedelta(minutes=1, seconds=15),
            NOW + timedelta(hours=1),
        )
    )
    application = service.apply(
        request_payload={
            "request_type": "human_review",
            "snapshot_id": "health-v1",
            "mutation_performed": False,
        },
        approval=approval,
        applied_at=NOW + timedelta(minutes=2),
        applied_by="controller",
    )
    assert application.approval_id == "approval-valid"
    assert application.mutation_performed
