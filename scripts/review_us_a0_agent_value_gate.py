from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from finagent.research.us_agent_value_assembly import (
    assemble_us_a0_experiment_evidence,
    parse_us_a0_run_evidence_bundle,
)
from finagent.research.us_agent_value_authority import bind_authorized_us_a0_predecessor
from finagent.research.us_agent_value_execution import (
    parse_candidate_generation_run,
    validate_us_a0_execution_plan,
)
from finagent.research.us_agent_value_gate import (
    USAgentValueGateDecision,
    assess_us_a0_agent_value_gate,
    finalize_us_a0_agent_value_gate_review,
    validate_us_a0_agent_value_gate_policy,
)
from finagent.research.us_agent_value_gate_authority import (
    require_us_a0_pilot_formal_progression_authority,
)
from finagent.research.us_agent_value_protocol import USAgentValuePhase


def _read_json(path: Path) -> Mapping[str, object]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _read_status(path: Path) -> Mapping[str, object]:
    with path.expanduser().resolve().open("rb") as handle:
        return cast(Mapping[str, object], tomllib.load(handle))


def _write_json(path: Path, payload: Mapping[str, object], *, overwrite: bool) -> Path:
    target = path.expanduser().resolve()
    if target.exists() and not overwrite:
        raise SystemExit(f"output already exists; pass --overwrite explicitly: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(dict(payload), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reassemble the exact preregistered US-A0 experiment evidence, apply the frozen "
            "Agent Value Gate policy, and emit an independently attested review. Reviewers may "
            "accept the deterministic assessment or downgrade it to INCONCLUSIVE, never upgrade it."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument(
        "--generation-run",
        type=Path,
        action="append",
        required=True,
        help="Repeat once for every exact run in the frozen ExecutionPlan.",
    )
    parser.add_argument("--run-report-root", type=Path, default=Path("reports/us_a0/runs"))
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    parser.add_argument(
        "--us-b0-evidence-graph",
        type=Path,
        default=Path("reports/us_b0/us_b0_walkforward_evidence_graph.json"),
    )
    parser.add_argument(
        "--pilot-gate-review",
        type=Path,
        default=None,
        help=(
            "Required for FORMAL review. The exact PILOT review ID must already be accepted "
            "in docs/status.toml and authorize PILOT_PROCEED_TO_FORMAL."
        ),
    )
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--review-notes", required=True)
    parser.add_argument(
        "--downgrade-to-inconclusive",
        action="store_true",
        help="A reviewer may conservatively downgrade the deterministic recommendation only.",
    )
    parser.add_argument("--attest-thresholds-unchanged", action="store_true")
    parser.add_argument("--attest-evidence-lineage", action="store_true")
    parser.add_argument("--ack-alpha-gate-separate", action="store_true")
    parser.add_argument("--ack-stage-authority-separate", action="store_true")
    parser.add_argument("--output-root", type=Path, default=Path("reports/us_a0/gate"))
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    preregistration = _read_json(args.preregistration)
    execution_plan_document = _read_json(args.execution_plan)
    protocol, execution_plan = validate_us_a0_execution_plan(
        execution_plan_document,
        preregistration,
    )
    policy_document = dict(_read_json(args.gate_policy))
    policy = validate_us_a0_agent_value_gate_policy(policy_document, protocol.phase)

    status = _read_status(args.status)
    if protocol.phase is USAgentValuePhase.FORMAL:
        if args.pilot_gate_review is None:
            raise SystemExit("FORMAL Agent Value Gate review requires --pilot-gate-review")
        require_us_a0_pilot_formal_progression_authority(
            status,
            _read_json(args.pilot_gate_review),
        )
    elif args.pilot_gate_review is not None:
        raise SystemExit("PILOT Gate review must not consume --pilot-gate-review")

    predecessor_graph = _read_json(args.us_b0_evidence_graph)
    predecessor = bind_authorized_us_a0_predecessor(status, predecessor_graph, protocol)

    generation_documents = tuple(_read_json(path) for path in args.generation_run)
    if len(generation_documents) != len(execution_plan.run_specs):
        raise SystemExit(
            "generation-run input count must equal the exact frozen ExecutionPlan run count: "
            f"{len(generation_documents)} != {len(execution_plan.run_specs)}"
        )
    parsed = []
    run_report_root = args.run_report_root.expanduser().resolve()
    for generation_document in generation_documents:
        generation_run = parse_candidate_generation_run(generation_document, execution_plan)
        report_root = run_report_root / generation_run.run_id
        parsed.append(
            parse_us_a0_run_evidence_bundle(
                execution_plan=execution_plan,
                predecessor=predecessor,
                generation_document=generation_document,
                run_evaluation_document=_read_json(report_root / "us_a0_run_evaluation.json"),
                evaluation_link_document=_read_json(
                    report_root / "us_a0_run_evaluation_link.json"
                ),
                run_manifest_document=_read_json(
                    report_root / "us_a0_run_evidence_manifest.json"
                ),
            )
        )
    _, experiment, comparison, graph = assemble_us_a0_experiment_evidence(
        protocol=protocol,
        execution_plan=execution_plan,
        predecessor=predecessor,
        run_evidence=tuple(parsed),
    )
    assessment = assess_us_a0_agent_value_gate(
        policy=policy,
        execution_plan=execution_plan,
        experiment=experiment,
        comparison=comparison,
        evidence_graph=graph,
    )
    decision = (
        USAgentValueGateDecision.INCONCLUSIVE
        if args.downgrade_to_inconclusive
        else None
    )
    review = finalize_us_a0_agent_value_gate_review(
        assessment,
        reviewer_id=args.reviewer_id,
        reviewed_at=datetime.now(UTC),
        review_notes=args.review_notes,
        decision=decision,
        thresholds_unchanged_attested=args.attest_thresholds_unchanged,
        evidence_lineage_attested=args.attest_evidence_lineage,
        alpha_gate_separation_attested=args.ack_alpha_gate_separate,
        stage_authority_separation_attested=args.ack_stage_authority_separate,
    )

    output_root = args.output_root.expanduser().resolve()
    assessment_output = _write_json(
        output_root / f"us_a0_{protocol.phase.value.lower()}_gate_assessment.json",
        assessment.to_dict(),
        overwrite=args.overwrite,
    )
    review_output = _write_json(
        output_root / f"us_a0_{protocol.phase.value.lower()}_gate_review.json",
        review.to_dict(),
        overwrite=args.overwrite,
    )
    print(
        json.dumps(
            {
                "phase": protocol.phase.value,
                "policy_id": policy.policy_id,
                "assessment_id": assessment.assessment_id,
                "machine_decision": assessment.decision.value,
                "review_id": review.review_id,
                "review_decision": review.decision.value,
                "formal_progression_authority": review.formal_progression_authority,
                "agent_value_gate_authority": review.agent_value_gate_authority,
                "supports_agent_retention_for_us_r1": review.supports_agent_retention_for_us_r1,
                "supports_agent_scope_contraction": review.supports_agent_scope_contraction,
                "alpha_authority": False,
                "stage_exit_authority": False,
                "assessment_output": str(assessment_output),
                "review_output": str(review_output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
