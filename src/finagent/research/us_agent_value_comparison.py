from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from finagent.research.us_agent_value_experiment import SearchArmResult
from finagent.research.us_agent_value_protocol import USAgentValueArm


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _candidate_ids(result: SearchArmResult) -> frozenset[str]:
    return frozenset(
        candidate.candidate_id
        for run in result.generation_runs
        for candidate in run.accepted_candidates
    )


@dataclass(frozen=True, slots=True)
class StructuralNoveltySummary:
    manual_candidate_ids: tuple[str, ...]
    programmatic_candidate_ids: tuple[str, ...]
    agent_candidate_ids: tuple[str, ...]
    programmatic_novel_vs_manual: tuple[str, ...]
    agent_novel_vs_manual: tuple[str, ...]
    agent_novel_vs_manual_and_programmatic: tuple[str, ...]
    programmatic_manual_overlap: tuple[str, ...]
    agent_manual_overlap: tuple[str, ...]
    agent_programmatic_overlap: tuple[str, ...]
    schema_version: str = "finagent.us-agent-value-structural-novelty-summary.v1"

    @property
    def summary_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-structural-novelty",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "manual_candidate_ids": list(self.manual_candidate_ids),
            "programmatic_candidate_ids": list(self.programmatic_candidate_ids),
            "agent_candidate_ids": list(self.agent_candidate_ids),
            "programmatic_novel_vs_manual": list(self.programmatic_novel_vs_manual),
            "agent_novel_vs_manual": list(self.agent_novel_vs_manual),
            "agent_novel_vs_manual_and_programmatic": list(
                self.agent_novel_vs_manual_and_programmatic
            ),
            "programmatic_manual_overlap": list(self.programmatic_manual_overlap),
            "agent_manual_overlap": list(self.agent_manual_overlap),
            "agent_programmatic_overlap": list(self.agent_programmatic_overlap),
            "manual_unique_count": len(self.manual_candidate_ids),
            "programmatic_unique_count": len(self.programmatic_candidate_ids),
            "agent_unique_count": len(self.agent_candidate_ids),
            "programmatic_novel_vs_manual_count": len(self.programmatic_novel_vs_manual),
            "agent_novel_vs_manual_count": len(self.agent_novel_vs_manual),
            "agent_novel_vs_manual_and_programmatic_count": len(
                self.agent_novel_vs_manual_and_programmatic
            ),
            "metric_scope": "structural_candidate_identity_only_no_financial_recomputation",
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["summary_id"] = self.summary_id
        return payload


def summarize_structural_novelty(
    manual: SearchArmResult,
    programmatic: SearchArmResult,
    agent: SearchArmResult,
) -> StructuralNoveltySummary:
    if manual.arm is not USAgentValueArm.MANUAL:
        raise ValueError("manual result must be the MANUAL arm")
    if programmatic.arm is not USAgentValueArm.PROGRAMMATIC:
        raise ValueError("programmatic result must be the PROGRAMMATIC arm")
    if agent.arm is not USAgentValueArm.AGENT:
        raise ValueError("agent result must be the AGENT arm")
    protocol_ids = {manual.protocol_id, programmatic.protocol_id, agent.protocol_id}
    if len(protocol_ids) != 1:
        raise ValueError("structural novelty comparison requires one experiment protocol")

    manual_ids = _candidate_ids(manual)
    programmatic_ids = _candidate_ids(programmatic)
    agent_ids = _candidate_ids(agent)
    return StructuralNoveltySummary(
        manual_candidate_ids=tuple(sorted(manual_ids)),
        programmatic_candidate_ids=tuple(sorted(programmatic_ids)),
        agent_candidate_ids=tuple(sorted(agent_ids)),
        programmatic_novel_vs_manual=tuple(sorted(programmatic_ids - manual_ids)),
        agent_novel_vs_manual=tuple(sorted(agent_ids - manual_ids)),
        agent_novel_vs_manual_and_programmatic=tuple(
            sorted(agent_ids - manual_ids - programmatic_ids)
        ),
        programmatic_manual_overlap=tuple(sorted(programmatic_ids & manual_ids)),
        agent_manual_overlap=tuple(sorted(agent_ids & manual_ids)),
        agent_programmatic_overlap=tuple(sorted(agent_ids & programmatic_ids)),
    )


@dataclass(frozen=True, slots=True)
class AgentValueComparisonSnapshot:
    protocol_id: str
    manual_result_id: str
    programmatic_result_id: str
    agent_result_id: str
    novelty: StructuralNoveltySummary
    schema_version: str = "finagent.us-agent-value-comparison-snapshot.v1"

    @property
    def snapshot_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-comparison",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "manual_result_id": self.manual_result_id,
            "programmatic_result_id": self.programmatic_result_id,
            "agent_result_id": self.agent_result_id,
            "novelty": self.novelty.to_dict(),
            "comparison_authority": "derived_from_content_addressed_generation_evidence",
            "agent_value_gate_decision": "UNDECIDED_REQUIRES_SEPARATE_REVIEW",
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["snapshot_id"] = self.snapshot_id
        return payload


def build_agent_value_comparison_snapshot(
    manual: SearchArmResult,
    programmatic: SearchArmResult,
    agent: SearchArmResult,
) -> AgentValueComparisonSnapshot:
    novelty = summarize_structural_novelty(manual, programmatic, agent)
    return AgentValueComparisonSnapshot(
        protocol_id=manual.protocol_id,
        manual_result_id=manual.result_id,
        programmatic_result_id=programmatic.result_id,
        agent_result_id=agent.result_id,
        novelty=novelty,
    )
