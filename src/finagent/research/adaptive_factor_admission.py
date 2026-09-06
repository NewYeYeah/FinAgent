"""Separate historical factor existence from retrospective development admission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from finagent.domain._validation import require_aware_datetime
from finagent.research.factor_library import FactorOrigin, FactorRegistration
from finagent.research.market_state import utc_text
from finagent.research.us_baselines import _canonical_hash


class FactorEvidenceMode(StrEnum):
    PREDECLARED_STATIC = "PREDECLARED_STATIC"
    ADAPTIVE_RETROSPECTIVE = "ADAPTIVE_RETROSPECTIVE"


def evidence_semantics(mode: FactorEvidenceMode) -> dict[str, Any]:
    adaptive = mode is FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE
    return {
        "admission_semantics": mode.value,
        "evaluation_mode": "adaptive_development_retrospective"
        if adaptive
        else "predeclared_static",
        "historically_predeclared": not adaptive,
        "adaptive_search_exposed": adaptive,
        "factor_was_known_at_historical_market_time": not adaptive,
        "retrospective": adaptive,
        "development_only": True,
        "independent_confirmation": False,
        "alpha_authority": False,
        "paper_authority": False,
        "live_authority": False,
    }


def factor_definition_digest(factor: FactorRegistration) -> str:
    """Hash the definition and real creation provenance without a circular envelope hash."""
    content = factor.to_dict()
    content["provenance"] = {k: v for k, v in factor.provenance if k != "proposal_envelope"}
    return str(_canonical_hash(content, prefix="r4-factor-definition"))


def proposal_id(envelope: dict[str, Any]) -> str:
    return str(
        _canonical_hash(
            {k: v for k, v in envelope.items() if k != "proposal_id"}, prefix="r4-factor-proposal"
        )
    )


@dataclass(frozen=True)
class AdaptiveDevelopmentAdmission:
    """Host-frozen research request. Market clocks and calculations are unchanged."""

    requested_at: datetime
    agent_run_id: str
    research_scope_id: str
    factor_definition_ids: tuple[tuple[str, str], ...]
    proposal_envelopes_json: str

    def to_dict(self) -> dict[str, Any]:
        import json

        return {
            **evidence_semantics(FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE),
            "requested_at": utc_text(self.requested_at),
            "agent_run_id": self.agent_run_id,
            "research_scope_id": self.research_scope_id,
            "factor_definition_ids": dict(self.factor_definition_ids),
            "proposal_envelopes": json.loads(self.proposal_envelopes_json),
        }

    def validate(self, factors: tuple[FactorRegistration, ...], evaluation_end: datetime) -> None:
        import json

        require_aware_datetime(self.requested_at, "research evaluation request time")
        if (
            not self.agent_run_id
            or not self.research_scope_id
            or self.requested_at < evaluation_end
        ):
            raise ValueError(
                "retrospective request requires an available historical development scope"
            )
        expected = tuple(
            sorted(
                (f.factor_id, str(_canonical_hash(f.to_dict(), prefix="factor-definition")))
                for f in factors
            )
        )
        if self.factor_definition_ids != expected:
            raise ValueError("retrospective factor definition binding mismatch")
        envelopes = self.to_dict()["proposal_envelopes"]
        if not isinstance(envelopes, dict) or set(envelopes) != {
            f.factor_id for f in factors if f.origin is FactorOrigin.AGENT
        }:
            raise ValueError("proposal envelope factor set mismatch")
        for factor in factors:
            if factor.created_at > self.requested_at:
                raise ValueError("factor proposal must be frozen before evaluation request")
            if factor.origin is not FactorOrigin.AGENT:
                continue
            envelope = envelopes.get(factor.factor_id)
            if not isinstance(envelope, dict) or set(envelope) != {
                "proposal_id",
                "factor_id",
                "factor_definition_digest",
                "visible_history_id",
                "proposed_at",
                "agent_run_id",
                "actor",
                "proposal_context_id",
                "visible_experiment_ids",
                "history_cutoff",
                "research_scope_id",
            }:
                raise ValueError("Agent factor requires an explicit proposal envelope")
            if (
                envelope["factor_id"] != factor.factor_id
                or envelope["proposal_id"] != proposal_id(envelope)
                or envelope["factor_definition_digest"] != factor_definition_digest(factor)
                or envelope["visible_history_id"] != envelope["proposal_context_id"]
                or envelope != json.loads(dict(factor.provenance).get("proposal_envelope", "null"))
                or datetime.fromisoformat(envelope["proposed_at"]) != factor.created_at
                or factor.created_at >= self.requested_at
                or envelope["research_scope_id"] != self.research_scope_id
                or not envelope["proposal_context_id"]
                or not envelope["agent_run_id"]
                or not envelope["actor"]
                or not isinstance(envelope["visible_experiment_ids"], list)
                or any(not isinstance(v, str) or not v for v in envelope["visible_experiment_ids"])
                or (
                    envelope["history_cutoff"] is not None
                    and not isinstance(envelope["history_cutoff"], str)
                )
            ):
                raise ValueError("invalid proposal clock/context provenance")
