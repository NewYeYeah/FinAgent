from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from finagent.agents.providers import load_llm_profile
from finagent.research.us_agent_value_assembly import parse_us_a0_run_evidence_bundle
from finagent.research.us_agent_value_authority import bind_authorized_us_a0_predecessor
from finagent.research.us_agent_value_execution import (
    parse_candidate_generation_run,
    validate_us_a0_execution_plan,
)
from finagent.research.us_agent_value_formal_launch import validate_us_a0_formal_launch_bundle
from finagent.research.us_agent_value_formal_postrun import (
    build_us_a0_formal_experiment_artifacts,
    build_us_a0_formal_gate_reviewed_checkpoint,
    parse_us_a0_formal_experiment_assembly_manifest,
    validate_us_a0_formal_gate_review_document,
)
from finagent.research.us_agent_value_formal_run_orchestration import (
    parse_us_a0_formal_run_progress,
)
from finagent.research.us_agent_value_formal_runtime import (
    USAgentValueFormalOrchestrationState,
    parse_us_a0_formal_orchestration_checkpoint,
    validate_us_a0_formal_deepseek_runtime_policy,
)
from finagent.research.us_agent_value_gate import (
    USAgentValueGateDecision,
    finalize_us_a0_agent_value_gate_review,
    validate_us_a0_agent_value_gate_policy,
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


def _write_once(path: Path, document: Mapping[str, object] | dict[str, object]) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(dict(document), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
    except FileExistsError as exc:
        raise SystemExit(f"FORMAL review evidence already exists and cannot be overwritten: {target}") from exc


def _require_equal(path: Path, expected: Mapping[str, object] | dict[str, object], label: str) -> None:
    if dict(_read_json(path)) != dict(expected):
        raise SystemExit(f"stored FORMAL {label} differs from deterministic reconstruction: {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Independently review the deterministic US-A0 FORMAL Agent Value Gate assessment, "
            "reuse only exact existing review evidence, and append GATE_REVIEWED checkpoint."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument("--pilot-gate-review", type=Path, required=True)
    parser.add_argument("--launch-bundle", type=Path, required=True)
    parser.add_argument("--runtime-policy", type=Path, required=True)
    parser.add_argument("--run-evidence-checkpoint", type=Path, required=True)
    parser.add_argument("--run-progress", type=Path, required=True)
    parser.add_argument("--generation-run", type=Path, action="append", required=True)
    parser.add_argument("--experiment-checkpoint", type=Path, required=True)
    parser.add_argument("--llm-config", type=Path, default=Path("configs/llm.toml"))
    parser.add_argument("--llm-profile", default="deepseek_official_v4_flash")
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    parser.add_argument(
        "--us-b0-evidence-graph",
        type=Path,
        default=Path("reports/us_b0/us_b0_walkforward_evidence_graph.json"),
    )
    parser.add_argument("--run-report-root", type=Path, default=Path("reports/us_a0/runs"))
    parser.add_argument("--experiment-root", type=Path, default=Path("reports/us_a0/formal_experiment"))
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--review-notes", required=True)
    parser.add_argument("--downgrade-to-inconclusive", action="store_true")
    parser.add_argument("--attest-thresholds-unchanged", action="store_true")
    parser.add_argument("--attest-evidence-lineage", action="store_true")
    parser.add_argument("--ack-alpha-gate-separate", action="store_true")
    parser.add_argument("--ack-stage-authority-separate", action="store_true")
    parser.add_argument(
        "--review-output",
        type=Path,
        default=Path("reports/us_a0/formal_gate/us_a0_formal_gate_review.json"),
    )
    parser.add_argument(
        "--checkpoint-output",
        type=Path,
        default=Path("reports/us_a0/formal_launch/checkpoint_04_gate_reviewed.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    preregistration = _read_json(args.preregistration)
    execution_plan_document = _read_json(args.execution_plan)
    protocol, execution_plan = validate_us_a0_execution_plan(
        execution_plan_document,
        preregistration,
    )
    if protocol.phase is not USAgentValuePhase.FORMAL:
        raise SystemExit("FORMAL Gate orchestration requires FORMAL preregistration")
    status = _read_status(args.status)
    gate_document = _read_json(args.gate_policy)
    gate_policy = validate_us_a0_agent_value_gate_policy(
        dict(gate_document),
        USAgentValuePhase.FORMAL,
    )
    pilot_review_document = _read_json(args.pilot_gate_review)
    launch = validate_us_a0_formal_launch_bundle(
        _read_json(args.launch_bundle),
        preregistration_document=preregistration,
        execution_plan_document=execution_plan_document,
        gate_policy_document=gate_document,
        status_document=status,
        pilot_gate_review_document=pilot_review_document,
    )
    profile = load_llm_profile(args.llm_config.expanduser().resolve(), args.llm_profile)
    runtime = validate_us_a0_formal_deepseek_runtime_policy(
        _read_json(args.runtime_policy),
        profile=profile,
        launch_artifacts=launch,
    )
    run_checkpoint = parse_us_a0_formal_orchestration_checkpoint(
        _read_json(args.run_evidence_checkpoint)
    )
    run_progress = parse_us_a0_formal_run_progress(_read_json(args.run_progress))
    predecessor = bind_authorized_us_a0_predecessor(
        status,
        _read_json(args.us_b0_evidence_graph),
        protocol,
    )
    if run_checkpoint.launch_bundle_id != launch.launch_bundle.launch_bundle_id:
        raise SystemExit("FORMAL run checkpoint/launch identity mismatch")
    if run_checkpoint.runtime_policy_id != runtime.runtime_policy_id:
        raise SystemExit("FORMAL run checkpoint/runtime identity mismatch")

    if len(args.generation_run) != 7:
        raise SystemExit("FORMAL Gate orchestration requires exactly seven --generation-run files")
    by_spec: dict[str, Mapping[str, object]] = {}
    for path in args.generation_run:
        document = _read_json(path)
        run = parse_candidate_generation_run(document, execution_plan)
        by_spec[run.spec.run_spec_id] = document
    expected_specs = tuple(spec.run_spec_id for spec in execution_plan.run_specs)
    if len(by_spec) != 7 or set(by_spec) != set(expected_specs):
        raise SystemExit("FORMAL Gate generation-run set differs from ExecutionPlan")

    parsed = []
    report_root = args.run_report_root.expanduser().resolve()
    for spec in execution_plan.run_specs:
        generation_document = by_spec[spec.run_spec_id]
        generation_run = parse_candidate_generation_run(generation_document, execution_plan)
        run_dir = report_root / generation_run.run_id
        parsed.append(
            parse_us_a0_run_evidence_bundle(
                execution_plan=execution_plan,
                predecessor=predecessor,
                generation_document=generation_document,
                run_evaluation_document=_read_json(run_dir / "us_a0_run_evaluation.json"),
                evaluation_link_document=_read_json(run_dir / "us_a0_run_evaluation_link.json"),
                run_manifest_document=_read_json(run_dir / "us_a0_run_evidence_manifest.json"),
            )
        )
    artifacts = build_us_a0_formal_experiment_artifacts(
        protocol=protocol,
        execution_plan=execution_plan,
        predecessor=predecessor,
        run_evidence=tuple(parsed),
        gate_policy=gate_policy,
        run_checkpoint=run_checkpoint,
        run_progress=run_progress,
    )

    experiment_checkpoint = parse_us_a0_formal_orchestration_checkpoint(
        _read_json(args.experiment_checkpoint)
    )
    if experiment_checkpoint.state is not USAgentValueFormalOrchestrationState.EXPERIMENT_ASSEMBLED:
        raise SystemExit("FORMAL Gate review requires EXPERIMENT_ASSEMBLED checkpoint")
    if experiment_checkpoint != artifacts.checkpoint:
        raise SystemExit("FORMAL experiment checkpoint differs from deterministic reconstruction")

    experiment_root = args.experiment_root.expanduser().resolve()
    for result in artifacts.arm_results:
        _require_equal(
            experiment_root / f"us_a0_formal_{result.arm.value.lower()}_search_arm_result.json",
            result.to_dict(),
            f"{result.arm.value} arm result",
        )
    _require_equal(
        experiment_root / "us_a0_formal_agent_value_experiment.json",
        artifacts.experiment.to_dict(),
        "experiment",
    )
    _require_equal(
        experiment_root / "us_a0_formal_agent_value_comparison.json",
        artifacts.comparison.to_dict(),
        "comparison",
    )
    _require_equal(
        experiment_root / "us_a0_formal_agent_value_evidence_graph.json",
        artifacts.evidence_graph.to_dict(),
        "evidence graph",
    )
    _require_equal(
        experiment_root / "us_a0_formal_gate_assessment.json",
        artifacts.assessment.to_dict(),
        "Gate assessment",
    )
    manifest_document = _read_json(
        experiment_root / "us_a0_formal_experiment_assembly_manifest.json"
    )
    manifest = parse_us_a0_formal_experiment_assembly_manifest(manifest_document)
    if manifest != artifacts.assembly_manifest:
        raise SystemExit("FORMAL assembly manifest differs from deterministic reconstruction")

    desired_decision = (
        USAgentValueGateDecision.INCONCLUSIVE
        if args.downgrade_to_inconclusive
        else artifacts.assessment.decision
    )
    review_path = args.review_output.expanduser().resolve()
    if review_path.exists():
        review = validate_us_a0_formal_gate_review_document(
            _read_json(review_path),
            assessment=artifacts.assessment,
        )
        if (
            review.reviewer_id != args.reviewer_id.strip()
            or review.review_notes != args.review_notes.strip()
            or review.decision is not desired_decision
            or not all(
                (
                    args.attest_thresholds_unchanged,
                    args.attest_evidence_lineage,
                    args.ack_alpha_gate_separate,
                    args.ack_stage_authority_separate,
                )
            )
        ):
            raise SystemExit("existing FORMAL Gate review differs from requested immutable review")
        resumed = True
    else:
        review = finalize_us_a0_agent_value_gate_review(
            artifacts.assessment,
            reviewer_id=args.reviewer_id,
            reviewed_at=datetime.now(UTC),
            review_notes=args.review_notes,
            decision=(
                USAgentValueGateDecision.INCONCLUSIVE
                if args.downgrade_to_inconclusive
                else None
            ),
            thresholds_unchanged_attested=args.attest_thresholds_unchanged,
            evidence_lineage_attested=args.attest_evidence_lineage,
            alpha_gate_separation_attested=args.ack_alpha_gate_separate,
            stage_authority_separation_attested=args.ack_stage_authority_separate,
        )
        _write_once(review_path, review.to_dict())
        resumed = False

    completed = build_us_a0_formal_gate_reviewed_checkpoint(
        experiment_checkpoint=experiment_checkpoint,
        assembly_manifest=manifest,
        review=review,
    )
    checkpoint_path = args.checkpoint_output.expanduser().resolve()
    if checkpoint_path.exists():
        stored = parse_us_a0_formal_orchestration_checkpoint(_read_json(checkpoint_path))
        if stored != completed:
            raise SystemExit("existing FORMAL GATE_REVIEWED checkpoint differs from review")
    else:
        _write_once(checkpoint_path, completed.to_dict())
    print(
        json.dumps(
            {
                "phase": "FORMAL",
                "state": completed.state.value,
                "checkpoint_id": completed.checkpoint_id,
                "assessment_id": artifacts.assessment.assessment_id,
                "machine_decision": artifacts.assessment.decision.value,
                "review_id": review.review_id,
                "review_decision": review.decision.value,
                "agent_value_gate_authority": review.agent_value_gate_authority,
                "supports_agent_retention_for_us_r1": review.supports_agent_retention_for_us_r1,
                "supports_agent_scope_contraction": review.supports_agent_scope_contraction,
                "alpha_authority": False,
                "stage_exit_authority": False,
                "resumed_existing_review": resumed,
                "review_output": str(review_path),
                "checkpoint_output": str(checkpoint_path),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
