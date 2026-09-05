"""Offline capability-loop acceptance. Synthetic feedback, no external model or broker."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from finagent.agents.r3_contracts import (
    DevelopmentRecord,
    DevelopmentScope,
    ResearchRuntimePolicy,
    ResearchTool,
    canonical_json,
    identity,
    proposal_action,
)
from finagent.agents.r3_runtime import (
    ResearchCapabilityRuntime,
    ResearchReply,
    ResearchRequest,
)
from finagent.research.us_a1_factor_graph import FactorGraphSpec
from finagent.research.us_a1_factor_validation import validate_factor_graph
from finagent.research.us_r3_alpha_catalog import build_us_r3_executable_frontier_candidates
from finagent.research.us_r3_usability import write_immutable_json


def _action(tool: str, **arguments: object) -> str:
    return canonical_json(
        {"schema_version": "finagent.us-r3-agent-action.v2", "tool": tool, "arguments": arguments}
    )


def _scope() -> DevelopmentScope:
    return DevelopmentScope(
        "synthetic-development",
        (
            DevelopmentRecord(
                "synthetic-development",
                "synthetic-literature",
                "literature",
                canonical_json(
                    {
                        "title": "Synthetic mechanism note, not a research citation",
                        "url": "https://example.invalid/synthetic",
                        "summary": "A fixture for bounded retrieval; not evidence of predictability.",
                    }
                ),
            ),
            DevelopmentRecord(
                "synthetic-development",
                "synthetic-bars",
                "coverage",
                canonical_json({"row_count": 100, "available_count": 90}),
            ),
        ),
        "synthetic-bars",
        "synthetic-evaluator",
    )


class ScriptedProvider:
    """Deterministic harness only; deliberately does not instantiate any LLM adapter."""

    def __init__(self, scope: DevelopmentScope) -> None:
        self.calls = 0
        candidates = build_us_r3_executable_frontier_candidates()
        proposals = []
        for candidate in candidates:
            hypothesis = replace(
                candidate.hypothesis,
                falsification=replace(
                    candidate.hypothesis.falsification,
                    invalidating_conditions=(
                        "Any outer/final data exposure invalidates this run.",
                    ),
                ),
            )
            proposals.append((candidate.graph, hypothesis))
        first_graph, first_hypothesis = proposals[0]
        self.actions = {
            (0, 1): _action("read_literature", record_id=scope.records[0].record_id),
            (0, 2): _action("read_development", record_id=scope.records[1].record_id),
            (0, 3): proposal_action(first_graph, first_hypothesis, ResearchTool.VALIDATE_FACTOR),
            (0, 4): _action("evaluate_development", candidate_id=candidates[0].candidate_id),
            (0, 5): proposal_action(first_graph, first_hypothesis),
            (1, 1): _action("submit_factor", unexpected_field="invalid fixture"),
            (1, 2): proposal_action(first_graph, first_hypothesis),
            (2, 1): _action("read_file", path="final/denied.json"),
            (2, 2): proposal_action(*proposals[1]),
        }

    def respond(self, request: ResearchRequest) -> ResearchReply:
        self.calls += 1
        context = json.loads(request.context_json)
        key = (context["slot"], context["attempt"])
        if key == (0, 5) and not any(
            item["outcome"] == "DEVELOPMENT_EVALUATED" for item in context["feedback"]
        ):
            raise RuntimeError("synthetic_feedback_loop_broken")
        # Simulated accounting, not an assertion of actual API token/cost usage.
        return ResearchReply(self.actions[key], 100, 10)


class SyntheticEvaluator:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, graph: FactorGraphSpec) -> DevelopmentRecord:
        self.calls += 1
        canonical = validate_factor_graph(graph).canonicalization
        if canonical is None:
            raise ValueError("invalid_synthetic_candidate")
        return DevelopmentRecord(
            "synthetic-development",
            "synthetic-bars",
            "evaluation",
            canonical_json(
                {
                    "candidate_id": canonical.candidate_id,
                    "evaluator_id": "synthetic-evaluator",
                    "metrics": {"rank_ic": 0.01, "valid_count": 100},
                }
            ),
        )


def run_smoke(
    output_root: Path,
    progress: Callable[[str, Mapping[str, object]], None] | None = None,
) -> dict[str, Any]:
    policy = ResearchRuntimePolicy()
    scope = _scope()
    provider, evaluator = ScriptedProvider(scope), SyntheticEvaluator()
    write_immutable_json(
        output_root / "us_r3_agent_runtime_policy_v2.json",
        {**policy.to_dict(), "policy_id": policy.policy_id},
    )
    runtime = ResearchCapabilityRuntime(
        output_root / "us_r3_agent_runtime.sqlite",
        run_id="offline-capability-smoke",
        scope=scope,
        provider=provider,
        provider_id="scripted-offline",
        model_id="synthetic-fixture",
        evaluator=evaluator,
        policy=policy,
    )
    expected = [
        (0, 1, "EVIDENCE_READ"),
        (0, 2, "EVIDENCE_READ"),
        (0, 3, "VALIDATED"),
        (0, 4, "DEVELOPMENT_EVALUATED"),
        (0, 5, "SUBMITTED"),
        (1, 1, "REJECTED"),
        (1, 2, "DUPLICATE"),
        (2, 1, "REJECTED"),
        (2, 2, "SUBMITTED"),
    ]
    outcomes = []
    for slot, attempt, expected_outcome in expected:
        result = runtime.step(f"slot-{slot}-attempt-{attempt}", slot)
        if progress:
            progress("agent_step", {"slot": slot, "attempt": attempt, "outcome": result["outcome"]})
        if result["outcome"] != expected_outcome:
            raise RuntimeError("offline_acceptance_mismatch")
        outcomes.append(result["outcome"])
    report: dict[str, object] = {
        "schema_version": "finagent.us-r3-agent-runtime-smoke.v2",
        "passed": True,
        "scope_manifest_id": scope.manifest_id,
        "policy_id": policy.policy_id,
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "ledger": runtime.ledger.snapshot(),
        "outcomes": outcomes,
        "synthetic_development_evaluation": True,
        "simulated_provider_accounting": True,
        "external_model_called": False,
        "financial_data_read": False,
        "mt5_accessed": False,
        "alpha_gate_evaluated": False,
        "alpha_authority": False,
        "execution_authority": False,
        "order_authority": False,
        "live_capital_authority": False,
    }
    report["evidence_id"] = identity(report, "us-r3-agent-runtime-smoke")
    write_immutable_json(output_root / "us_r3_agent_runtime_smoke.json", report)
    return {
        "passed": True,
        "evidence_id": report["evidence_id"],
        "policy_id": policy.policy_id,
        "provider_calls_this_invocation": provider.calls,
        "evaluator_calls_this_invocation": evaluator.calls,
        "external_model_called": False,
        "alpha_authority": False,
    }


def _progress(event: str, fields: Mapping[str, object]) -> None:
    print(json.dumps({"event": event, **fields}), file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_smoke(args.output_root, _progress)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except KeyboardInterrupt:
        _progress("interrupted", {"ledger_preserved": True})
        return 130
    except Exception:  # noqa: BLE001 -- never log raw provider/callback content or sealed paths.
        _progress("failed", {"code": "offline_smoke_failed", "ledger_preserved": True})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
