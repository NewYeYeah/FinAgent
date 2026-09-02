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
from finagent.research.us_agent_value_gate import (
    USAgentValueGateDecision,
    finalize_us_a0_agent_value_gate_review,
    validate_us_a0_agent_value_gate_policy,
)
from finagent.research.us_agent_value_launch import (
    validate_us_a0_pilot_control_documents,
    validate_us_a0_pilot_launch_bundle,
)
from finagent.research.us_agent_value_orchestration import (
    USAgentValuePilotOrchestrationState,
    parse_us_a0_pilot_orchestration_checkpoint,
)
from finagent.research.us_agent_value_postrun_orchestration import (
    build_us_a0_pilot_experiment_artifacts,
    build_us_a0_pilot_gate_reviewed_checkpoint,
    parse_us_a0_pilot_experiment_assembly_manifest,
    validate_us_a0_pilot_experiment_documents,
    validate_us_a0_pilot_gate_review_document,
)
from finagent.research.us_agent_value_run_orchestration import parse_us_a0_pilot_run_progress
from finagent.research.us_agent_value_runtime import validate_us_a0_deepseek_runtime_policy


def _read_json(path: Path) -> Mapping[str, object]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _read_status(path: Path) -> Mapping[str, object]:
    with path.expanduser().resolve().open("rb") as handle:
        return cast(Mapping[str, object], tomllib.load(handle))


def _write_once(path: Path, document: Mapping[str, object]) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(dict(document), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
    except FileExistsError as exc:
        raise SystemExit(f"review/checkpoint evidence already exists and cannot be replaced: {target}") from exc


def _run_report_documents(report_dir: Path) -> tuple[Mapping[str, object], ...]:
    paths = (
        report_dir / "us_a0_run_evaluation.json",
        report_dir / "us_a0_run_evaluation_link.json",
        report_dir / "us_a0_run_evidence_manifest.json",
    )
    missing = tuple(path.name for path in paths if not path.exists())
    if missing:
        raise SystemExit(f"committed A0 run report is incomplete: {report_dir}; missing={list(missing)}")
    return tuple(_read_json(path) for path in paths)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resume-safe independent US-A0 PILOT Agent Value Gate review. Reconstruct the exact "
            "committed experiment and deterministic assessment, then bind one immutable reviewer "
            "attestation to the EXPERIMENT_ASSEMBLED checkpoint."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument("--launch-bundle", type=Path, required=True)
    parser.add_argument("--runtime-policy", type=Path, required=True)
    parser.add_argument("--run-evidence-checkpoint", type=Path, required=True)
    parser.add_argument("--run-progress", type=Path, required=True)
    parser.add_argument("--experiment-checkpoint", type=Path, required=True)
    parser.add_argument("--manual-run", type=Path, required=True)
    parser.add_argument("--programmatic-run", type=Path, required=True)
    parser.add_argument("--agent-run", type=Path, required=True)
    parser.add_argument("--llm-config", type=Path, default=Path("configs/llm.toml"))
    parser.add_argument("--llm-profile", default="deepseek_official_v4_flash")
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    parser.add_argument(
        "--us-b0-evidence-graph",
        type=Path,
        default=Path("reports/us_b0/us_b0_walkforward_evidence_graph.json"),
    )
    parser.add_argument("--run-report-root", type=Path, default=Path("reports/us_a0/runs"))
    parser.add_argument("--experiment-output-root", type=Path, default=Path("reports/us_a0/experiment"))
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
        default=Path("reports/us_a0/gate/us_a0_pilot_gate_review.json"),
    )
    parser.add_argument(
        "--checkpoint-output",
        type=Path,
        default=Path("reports/us_a0/pilot_launch/checkpoint_04_gate_reviewed.json"),
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
    gate_policy_document = dict(_read_json(args.gate_policy))
    gate_policy = validate_us_a0_agent_value_gate_policy(gate_policy_document, protocol.phase)
    launch_document = _read_json(args.launch_bundle)
    launch_artifacts = validate_us_a0_pilot_launch_bundle(
        launch_document,
        preregistration_document=preregistration,
        execution_plan_document=execution_plan_document,
        gate_policy_document=gate_policy_document,
    )
    profile = load_llm_profile(args.llm_config.expanduser().resolve(), args.llm_profile)
    _, runtime_policy = validate_us_a0_deepseek_runtime_policy(
        _read_json(args.runtime_policy),
        profile=profile,
        preregistration_document=preregistration,
        execution_plan_document=execution_plan_document,
        gate_policy_document=gate_policy_document,
        launch_bundle_document=launch_document,
    )
    run_checkpoint = parse_us_a0_pilot_orchestration_checkpoint(
        _read_json(args.run_evidence_checkpoint)
    )
    run_progress = parse_us_a0_pilot_run_progress(_read_json(args.run_progress))
    experiment_checkpoint = parse_us_a0_pilot_orchestration_checkpoint(
        _read_json(args.experiment_checkpoint)
    )
    if experiment_checkpoint.state is not USAgentValuePilotOrchestrationState.EXPERIMENT_ASSEMBLED:
        raise SystemExit("PILOT Gate review requires EXPERIMENT_ASSEMBLED checkpoint")
    if experiment_checkpoint.previous_checkpoint_id != run_checkpoint.checkpoint_id:
        raise SystemExit("EXPERIMENT_ASSEMBLED checkpoint does not descend from RUN_EVIDENCE_COMPLETE")
    if experiment_checkpoint.launch_bundle_id != launch_artifacts.launch_bundle.launch_bundle_id:
        raise SystemExit("EXPERIMENT_ASSEMBLED checkpoint/launch identity mismatch")
    if experiment_checkpoint.runtime_policy_id != runtime_policy.runtime_policy_id:
        raise SystemExit("EXPERIMENT_ASSEMBLED checkpoint/runtime-policy identity mismatch")

    manual_document = _read_json(args.manual_run)
    programmatic_document = _read_json(args.programmatic_run)
    agent_document = _read_json(args.agent_run)
    controls = validate_us_a0_pilot_control_documents(
        launch_artifacts,
        (manual_document, programmatic_document),
    )
    agent_generation = parse_candidate_generation_run(agent_document, execution_plan)
    if agent_generation.run_id != experiment_checkpoint.agent_generation_run_id:
        raise SystemExit("AGENT generation run differs from frozen experiment checkpoint")
    generation_documents = {
        controls[0].spec.run_spec_id: manual_document,
        controls[1].spec.run_spec_id: programmatic_document,
        agent_generation.spec.run_spec_id: agent_document,
    }

    status = _read_status(args.status)
    predecessor = bind_authorized_us_a0_predecessor(
        status,
        _read_json(args.us_b0_evidence_graph),
        protocol,
    )
    run_report_root = args.run_report_root.expanduser().resolve()
    parsed = []
    for spec in execution_plan.run_specs:
        generation_document = generation_documents[spec.run_spec_id]
        generation_run = parse_candidate_generation_run(generation_document, execution_plan)
        evaluation, link, manifest = _run_report_documents(run_report_root / generation_run.run_id)
        parsed.append(
            parse_us_a0_run_evidence_bundle(
                execution_plan=execution_plan,
                predecessor=predecessor,
                generation_document=generation_document,
                run_evaluation_document=evaluation,
                evaluation_link_document=link,
                run_manifest_document=manifest,
            )
        )
    artifacts = build_us_a0_pilot_experiment_artifacts(
        protocol=protocol,
        execution_plan=execution_plan,
        predecessor=predecessor,
        run_evidence=tuple(parsed),
        gate_policy=gate_policy,
        run_checkpoint=run_checkpoint,
        run_progress=run_progress,
    )
    if experiment_checkpoint.to_dict() != artifacts.checkpoint.to_dict():
        raise SystemExit("stored EXPERIMENT_ASSEMBLED checkpoint differs from deterministic reconstruction")

    output_root = args.experiment_output_root.expanduser().resolve()
    arm_paths = tuple(
        output_root / f"us_a0_{result.arm.value.lower()}_search_arm_result.json"
        for result in artifacts.arm_results
    )
    validate_us_a0_pilot_experiment_documents(
        artifacts,
        arm_documents=tuple(_read_json(path) for path in arm_paths),
        experiment_document=_read_json(output_root / "us_a0_agent_value_experiment.json"),
        comparison_document=_read_json(output_root / "us_a0_agent_value_comparison.json"),
        graph_document=_read_json(output_root / "us_a0_agent_value_evidence_graph.json"),
        assessment_document=_read_json(output_root / "us_a0_pilot_gate_assessment.json"),
        manifest_document=_read_json(output_root / "us_a0_pilot_experiment_assembly_manifest.json"),
        checkpoint_document=_read_json(args.experiment_checkpoint),
    )
    assembly_manifest = parse_us_a0_pilot_experiment_assembly_manifest(
        _read_json(output_root / "us_a0_pilot_experiment_assembly_manifest.json")
    )

    review_path = args.review_output.expanduser().resolve()
    desired_decision = (
        USAgentValueGateDecision.INCONCLUSIVE
        if args.downgrade_to_inconclusive
        else artifacts.assessment.decision
    )
    if review_path.exists():
        review = validate_us_a0_pilot_gate_review_document(
            _read_json(review_path),
            assessment=artifacts.assessment,
        )
        if review.reviewer_id != args.reviewer_id.strip():
            raise SystemExit("existing Gate review belongs to a different reviewer")
        if review.review_notes != args.review_notes.strip():
            raise SystemExit("existing Gate review notes differ from requested immutable review")
        if review.decision is not desired_decision:
            raise SystemExit("existing Gate review decision differs from requested immutable review")
        requested_attestations = (
            args.attest_thresholds_unchanged,
            args.attest_evidence_lineage,
            args.ack_alpha_gate_separate,
            args.ack_stage_authority_separate,
        )
        actual_attestations = (
            review.thresholds_unchanged_attested,
            review.evidence_lineage_attested,
            review.alpha_gate_separation_attested,
            review.stage_authority_separation_attested,
        )
        if requested_attestations != actual_attestations:
            raise SystemExit("existing Gate review attestations differ from requested immutable review")
        resumed_review = True
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
        resumed_review = False

    reviewed_checkpoint = build_us_a0_pilot_gate_reviewed_checkpoint(
        experiment_checkpoint=experiment_checkpoint,
        assembly_manifest=assembly_manifest,
        review=review,
    )
    checkpoint_path = args.checkpoint_output.expanduser().resolve()
    if checkpoint_path.exists():
        existing_checkpoint = parse_us_a0_pilot_orchestration_checkpoint(_read_json(checkpoint_path))
        if existing_checkpoint.to_dict() != reviewed_checkpoint.to_dict():
            raise SystemExit("existing GATE_REVIEWED checkpoint differs from immutable review lineage")
        resumed_checkpoint = True
    else:
        _write_once(checkpoint_path, reviewed_checkpoint.to_dict())
        resumed_checkpoint = False

    print(
        json.dumps(
            {
                "state": reviewed_checkpoint.state.value,
                "checkpoint_id": reviewed_checkpoint.checkpoint_id,
                "previous_checkpoint_id": reviewed_checkpoint.previous_checkpoint_id,
                "evidence_graph_id": assembly_manifest.evidence_graph_id,
                "assessment_id": artifacts.assessment.assessment_id,
                "machine_decision": artifacts.assessment.decision.value,
                "review_id": review.review_id,
                "review_decision": review.decision.value,
                "formal_progression_authority": review.formal_progression_authority,
                "agent_value_gate_authority": review.agent_value_gate_authority,
                "alpha_authority": False,
                "stage_exit_authority": False,
                "status_authority": False,
                "resumed_review": resumed_review,
                "resumed_checkpoint": resumed_checkpoint,
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
