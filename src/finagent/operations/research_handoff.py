from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from finagent.domain._validation import require_aware_datetime, require_non_empty
from finagent.domain.model_registry import ModelStage, RegisteredModel
from finagent.research.promotion import (
    ResearchPromotionDecision,
    SQLiteResearchPromotionStore,
)
from finagent.research.registry import SQLiteResearchRegistry

from .domain import HumanApproval, OperationalApplication
from .store import SQLitePaperBrokerStore


RESEARCH_MODEL_PAPER_REQUEST = "research_model_paper"


@dataclass(frozen=True, slots=True)
class ResearchPaperHandoffRequest:
    """Immutable, non-mutating request to move one validated research model to PAPER."""

    model_id: str
    model_artifact_digest: str
    promotion_id: str
    program_id: str
    final_strategy_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "model_id",
            "model_artifact_digest",
            "promotion_id",
            "program_id",
            "final_strategy_id",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        object.__setattr__(
            self,
            "created_at",
            require_aware_datetime(self.created_at, "created_at"),
        )

    @property
    def request_id(self) -> str:
        payload = {
            "model_id": self.model_id,
            "model_artifact_digest": self.model_artifact_digest,
            "promotion_id": self.promotion_id,
            "program_id": self.program_id,
            "final_strategy_id": self.final_strategy_id,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return f"paper-handoff-{hashlib.sha256(encoded).hexdigest()[:24]}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.research-paper-handoff-request.v1",
            "request_id": self.request_id,
            "request_type": RESEARCH_MODEL_PAPER_REQUEST,
            "model_id": self.model_id,
            "model_artifact_digest": self.model_artifact_digest,
            "promotion_id": self.promotion_id,
            "program_id": self.program_id,
            "final_strategy_id": self.final_strategy_id,
            "created_at": self.created_at.isoformat(),
            "mutation_performed": False,
            "requires_human_approval": True,
        }


@dataclass(frozen=True, slots=True)
class ResearchPaperHandoffApplication:
    request_id: str
    approval_id: str
    model_id: str
    promotion_id: str
    applied_at: datetime
    applied_by: str

    def __post_init__(self) -> None:
        for name in ("request_id", "approval_id", "model_id", "promotion_id", "applied_by"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        object.__setattr__(self, "applied_at", require_aware_datetime(self.applied_at, "applied_at"))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.research-paper-handoff-application.v1",
            "request_id": self.request_id,
            "approval_id": self.approval_id,
            "model_id": self.model_id,
            "promotion_id": self.promotion_id,
            "applied_at": self.applied_at.isoformat(),
            "applied_by": self.applied_by,
        }


class SQLiteResearchPaperHandoffStore:
    """Immutable handoff requests with at most one terminal application per request."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_paper_handoff_requests (
                    request_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL UNIQUE,
                    promotion_id TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_paper_handoff_applications (
                    request_id TEXT PRIMARY KEY,
                    approval_id TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(request_id) REFERENCES research_paper_handoff_requests(request_id)
                );
                """
            )

    def register_request(self, request: ResearchPaperHandoffRequest) -> None:
        encoded = json.dumps(
            request.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        with sqlite3.connect(self.path) as con:
            existing = con.execute(
                "SELECT model_id, promotion_id, payload_json "
                "FROM research_paper_handoff_requests WHERE request_id=?",
                (request.request_id,),
            ).fetchone()
            candidate = (request.model_id, request.promotion_id, encoded)
            if existing is not None:
                if tuple(existing) != candidate:
                    raise ValueError("paper handoff request identity is immutable")
                return
            if con.execute(
                "SELECT 1 FROM research_paper_handoff_requests "
                "WHERE model_id=? OR promotion_id=?",
                (request.model_id, request.promotion_id),
            ).fetchone():
                raise ValueError("model/promotion already has a different paper handoff request")
            con.execute(
                "INSERT INTO research_paper_handoff_requests VALUES (?, ?, ?, ?)",
                (request.request_id, request.model_id, request.promotion_id, encoded),
            )

    def get_request(self, request_id: str) -> ResearchPaperHandoffRequest:
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT payload_json FROM research_paper_handoff_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
        if row is None:
            raise KeyError(request_id)
        payload = json.loads(row[0])
        return ResearchPaperHandoffRequest(
            model_id=payload["model_id"],
            model_artifact_digest=payload["model_artifact_digest"],
            promotion_id=payload["promotion_id"],
            program_id=payload["program_id"],
            final_strategy_id=payload["final_strategy_id"],
            created_at=datetime.fromisoformat(payload["created_at"]),
        )

    def register_application(self, application: ResearchPaperHandoffApplication) -> None:
        encoded = json.dumps(
            application.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        with sqlite3.connect(self.path) as con:
            if con.execute(
                "SELECT 1 FROM research_paper_handoff_requests WHERE request_id=?",
                (application.request_id,),
            ).fetchone() is None:
                raise KeyError(application.request_id)
            existing = con.execute(
                "SELECT approval_id, payload_json FROM research_paper_handoff_applications "
                "WHERE request_id=?",
                (application.request_id,),
            ).fetchone()
            candidate = (application.approval_id, encoded)
            if existing is not None:
                if tuple(existing) != candidate:
                    raise ValueError("paper handoff request already has a different application")
                return
            con.execute(
                "INSERT INTO research_paper_handoff_applications VALUES (?, ?, ?)",
                (application.request_id, application.approval_id, encoded),
            )

    def get_application(self, request_id: str) -> ResearchPaperHandoffApplication:
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT payload_json FROM research_paper_handoff_applications WHERE request_id=?",
                (request_id,),
            ).fetchone()
        if row is None:
            raise KeyError(request_id)
        payload = json.loads(row[0])
        return ResearchPaperHandoffApplication(
            request_id=payload["request_id"],
            approval_id=payload["approval_id"],
            model_id=payload["model_id"],
            promotion_id=payload["promotion_id"],
            applied_at=datetime.fromisoformat(payload["applied_at"]),
            applied_by=payload["applied_by"],
        )


@dataclass(frozen=True, slots=True)
class ResearchPaperHandoffResult:
    request: ResearchPaperHandoffRequest
    model: RegisteredModel
    application: ResearchPaperHandoffApplication | None = None


class ResearchPaperHandoffService:
    """Human-controlled transition from research VALIDATED to operational PAPER stage."""

    def __init__(
        self,
        *,
        registry: SQLiteResearchRegistry,
        promotion_store: SQLiteResearchPromotionStore,
        handoff_store: SQLiteResearchPaperHandoffStore,
        paper_store: SQLitePaperBrokerStore,
    ) -> None:
        self.registry = registry
        self.promotion_store = promotion_store
        self.handoff_store = handoff_store
        self.paper_store = paper_store

    def request(
        self,
        *,
        decision: ResearchPromotionDecision,
        model_id: str,
        created_at: datetime,
    ) -> ResearchPaperHandoffResult:
        if not decision.passed:
            raise PermissionError("rejected research cannot request PAPER promotion")
        persisted = self.promotion_store.get_for_program(decision.program_id)
        if persisted != decision:
            raise ValueError("paper handoff requires the exact persisted research promotion decision")
        model = self.registry.get_model(model_id)
        if model.stage is not ModelStage.VALIDATED:
            raise PermissionError("paper handoff request requires a VALIDATED model")
        if model.metadata.get("promotion_id") != decision.promotion_id:
            raise ValueError("validated model is not bound to the research promotion decision")
        if model.metadata.get("program_id") != decision.program_id:
            raise ValueError("validated model ResearchProgram identity mismatch")
        if model.metadata.get("final_strategy_id") != decision.final_strategy_id:
            raise ValueError("validated model final strategy identity mismatch")

        request = ResearchPaperHandoffRequest(
            model_id=model.model_id,
            model_artifact_digest=model.artifact.digest,
            promotion_id=decision.promotion_id,
            program_id=decision.program_id,
            final_strategy_id=decision.final_strategy_id,
            created_at=created_at,
        )
        self.handoff_store.register_request(request)
        return ResearchPaperHandoffResult(request=request, model=model)

    def apply(
        self,
        *,
        request_id: str,
        approval: HumanApproval,
        applied_at: datetime,
        applied_by: str,
    ) -> ResearchPaperHandoffResult:
        request = self.handoff_store.get_request(request_id)
        applied_at = require_aware_datetime(applied_at, "applied_at")
        applied_by = require_non_empty(applied_by, "applied_by")

        try:
            existing = self.handoff_store.get_application(request_id)
        except KeyError:
            existing = None
        if existing is not None:
            if existing.approval_id != approval.approval_id:
                raise PermissionError("paper handoff was already applied under a different approval")
            model = self.registry.get_model(request.model_id)
            if model.stage is not ModelStage.PAPER:
                raise RuntimeError("persisted paper handoff application disagrees with model stage")
            return ResearchPaperHandoffResult(request, model, existing)

        if approval.request_type != RESEARCH_MODEL_PAPER_REQUEST:
            raise ValueError("approval request_type does not authorize research model PAPER promotion")
        if approval.snapshot_id != request.request_id:
            raise ValueError("approval snapshot_id does not match immutable paper handoff request")
        if approval.approved_at < request.created_at:
            raise ValueError("approval cannot predate paper handoff request")
        if applied_at < approval.approved_at:
            raise ValueError("applied_at cannot precede approved_at")

        decision = self.promotion_store.get_for_program(request.program_id)
        if not decision.passed or decision.promotion_id != request.promotion_id:
            raise PermissionError("paper handoff promotion decision is no longer admissible")
        model = self.registry.get_model(request.model_id)
        if model.artifact.digest != request.model_artifact_digest:
            raise ValueError("validated model artifact drifted after paper handoff request")
        if model.stage is not ModelStage.VALIDATED:
            raise PermissionError("paper handoff can only mutate a VALIDATED model")

        self.paper_store.record_approval(approval)
        paper_model = self.registry.promote_model(
            model.model_id,
            ModelStage.PAPER,
            changed_at=applied_at,
            reason=f"human approval {approval.approval_id} applied to {request.request_id}",
            actor=applied_by,
        )
        operational_application = OperationalApplication(
            approval_id=approval.approval_id,
            request_type=RESEARCH_MODEL_PAPER_REQUEST,
            snapshot_id=request.request_id,
            applied_at=applied_at,
            applied_by=applied_by,
            policy_id=approval.policy_id,
            mutation_performed=True,
        )
        self.paper_store.record_application(operational_application)
        application = ResearchPaperHandoffApplication(
            request_id=request.request_id,
            approval_id=approval.approval_id,
            model_id=paper_model.model_id,
            promotion_id=request.promotion_id,
            applied_at=applied_at,
            applied_by=applied_by,
        )
        self.handoff_store.register_application(application)
        self.paper_store.record_event(
            "research_model_promoted_to_paper",
            applied_at,
            {
                "request_id": request.request_id,
                "approval_id": approval.approval_id,
                "model_id": paper_model.model_id,
                "promotion_id": request.promotion_id,
            },
        )
        return ResearchPaperHandoffResult(request, paper_model, application)
