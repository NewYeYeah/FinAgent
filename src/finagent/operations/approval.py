from __future__ import annotations

from datetime import datetime
from typing import Mapping

from finagent.agents.supervisor import OperatingPolicyRegistry, SQLitePortfolioSupervisionStore

from .domain import HumanApproval, OperationalApplication
from .store import SQLitePaperBrokerStore


class OperationalApprovalService:
    """Apply human-approved Supervisor requests outside the Agent runtime."""

    def __init__(
        self,
        *,
        broker_store: SQLitePaperBrokerStore,
        supervision_store: SQLitePortfolioSupervisionStore,
        operating_policies: OperatingPolicyRegistry,
    ) -> None:
        self.broker_store = broker_store
        self.supervision_store = supervision_store
        self.operating_policies = operating_policies

    def apply(
        self,
        *,
        request_payload: Mapping[str, object],
        approval: HumanApproval,
        applied_at: datetime,
        applied_by: str,
    ) -> OperationalApplication:
        request_type = str(request_payload.get("request_type", ""))
        snapshot_id = str(request_payload.get("snapshot_id", ""))
        if request_type != approval.request_type:
            raise ValueError("approval request_type does not match request payload")
        if snapshot_id != approval.snapshot_id:
            raise ValueError("approval snapshot_id does not match request payload")
        if bool(request_payload.get("mutation_performed", True)):
            raise ValueError("Supervisor request payload must prove mutation_performed=false")
        self.supervision_store.get(snapshot_id)

        policy_id = ""
        if request_type == "operating_policy":
            if not bool(request_payload.get("requires_human_approval", False)):
                raise ValueError("operating-policy request must require human approval")
            policy_id = str(request_payload.get("policy_id", "")).strip()
            if not policy_id or policy_id != approval.policy_id:
                raise ValueError("approved policy_id does not match request payload")
            self.operating_policies.get(policy_id)
        elif request_type == "rebalance":
            if not bool(request_payload.get("requires_human_approval", False)):
                raise ValueError("rebalance request must require human approval")
            snapshot = self.supervision_store.get(snapshot_id)
            if not snapshot.rebalance_required:
                raise ValueError("rebalance is no longer justified by deterministic evidence")
        elif request_type == "human_review":
            pass
        else:
            raise ValueError(f"unsupported operational request_type {request_type!r}")

        self.broker_store.record_approval(approval)
        application = OperationalApplication(
            approval_id=approval.approval_id,
            request_type=request_type,
            snapshot_id=snapshot_id,
            applied_at=applied_at,
            applied_by=applied_by,
            policy_id=policy_id,
            mutation_performed=True,
        )
        self.broker_store.record_application(application)
        self.broker_store.record_event(
            "operational_application",
            applied_at,
            {
                "approval_id": approval.approval_id,
                "request_type": request_type,
                "snapshot_id": snapshot_id,
                "policy_id": policy_id,
                "applied_by": applied_by,
            },
        )
        return application
