from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from finagent.research.us_r1_gate import USR1AlphaGateAssessment
from finagent.research.us_r1_protocol import USR1Terminal


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class USR1AlphaGateReview:
    assessment: USR1AlphaGateAssessment
    reviewer_id: str
    reviewed_at: datetime
    terminal: USR1Terminal
    review_notes: str
    thresholds_unchanged_attested: bool
    evidence_lineage_attested: bool
    agent_value_gate_separation_attested: bool
    execution_gate_separation_attested: bool
    live_capital_separation_attested: bool
    schema_version: str = "finagent.us-r1-alpha-gate-review.v1"

    def __post_init__(self) -> None:
        reviewer = self.reviewer_id.strip()
        notes = self.review_notes.strip()
        if not reviewer:
            raise ValueError("reviewer_id must be non-empty")
        if not notes or len(notes) > 2000:
            raise ValueError("review_notes must contain 1..2000 characters")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        object.__setattr__(self, "reviewer_id", reviewer)
        object.__setattr__(self, "review_notes", notes)
        object.__setattr__(self, "reviewed_at", self.reviewed_at.astimezone(UTC))
        if not all(
            (
                self.thresholds_unchanged_attested,
                self.evidence_lineage_attested,
                self.agent_value_gate_separation_attested,
                self.execution_gate_separation_attested,
                self.live_capital_separation_attested,
            )
        ):
            raise ValueError("all US-R1 Alpha Gate review attestations must be true")
        allowed = {self.assessment.terminal, USR1Terminal.SYSTEM_FAILURE}
        if self.terminal not in allowed:
            raise ValueError(
                "US-R1 reviewer may accept the assessment or downgrade to SYSTEM_FAILURE only"
            )
        if (
            self.terminal is USR1Terminal.SYSTEM_FAILURE
            and self.assessment.terminal is not USR1Terminal.SYSTEM_FAILURE
            and len(notes) < 20
        ):
            raise ValueError(
                "downgrading US-R1 review to SYSTEM_FAILURE requires substantive notes"
            )

    @property
    def review_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-r1-alpha-gate-review",
        )

    @property
    def alpha_gate_authority(self) -> bool:
        return True

    @property
    def alpha_authority(self) -> bool:
        return self.terminal is USR1Terminal.ROBUST_FACTOR_FAMILY

    @property
    def supports_us_x0_progression(self) -> bool:
        return self.alpha_authority

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "assessment": self.assessment.to_dict(),
            "assessment_id": self.assessment.assessment_id,
            "reviewer_id": self.reviewer_id,
            "reviewed_at": self.reviewed_at.isoformat(),
            "terminal": self.terminal.value,
            "review_notes": self.review_notes,
            "attestations": {
                "thresholds_unchanged_after_results": self.thresholds_unchanged_attested,
                "evidence_lineage_verified": self.evidence_lineage_attested,
                "agent_value_gate_is_separate": self.agent_value_gate_separation_attested,
                "cfd_execution_gate_is_separate": self.execution_gate_separation_attested,
                "live_capital_gate_is_separate": self.live_capital_separation_attested,
            },
            "alpha_gate_authority": self.alpha_gate_authority,
            "alpha_authority": self.alpha_authority,
            "supports_us_x0_progression": self.supports_us_x0_progression,
            "status_authority": False,
            "stage_exit_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["review_id"] = self.review_id
        return payload


def finalize_us_r1_alpha_gate_review(
    assessment: USR1AlphaGateAssessment,
    *,
    reviewer_id: str,
    reviewed_at: datetime,
    review_notes: str,
    terminal: USR1Terminal | None = None,
    thresholds_unchanged_attested: bool,
    evidence_lineage_attested: bool,
    agent_value_gate_separation_attested: bool,
    execution_gate_separation_attested: bool,
    live_capital_separation_attested: bool,
) -> USR1AlphaGateReview:
    return USR1AlphaGateReview(
        assessment=assessment,
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
        terminal=assessment.terminal if terminal is None else terminal,
        review_notes=review_notes,
        thresholds_unchanged_attested=thresholds_unchanged_attested,
        evidence_lineage_attested=evidence_lineage_attested,
        agent_value_gate_separation_attested=agent_value_gate_separation_attested,
        execution_gate_separation_attested=execution_gate_separation_attested,
        live_capital_separation_attested=live_capital_separation_attested,
    )
