from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.agents.providers import load_llm_profile
from finagent.research.us_agent_value_assembly import parse_us_a0_run_evidence_bundle
from finagent.research.us_agent_value_authority import bind_authorized_us_a0_predecessor
from finagent.research.us_agent_value_execution import (
    parse_candidate_generation_run,
    validate_us_a0_execution_plan,
)
from finagent.research.us_agent_value_gate import validate_us_a0_agent_value_gate_policy
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
    validate_us_a0_pilot_experiment_documents,
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


def _write_or_validate(path: Path, expected: Mapping[str, object]) -> None:
    target = path.expanduser().resolve()
    if target.exists():
        actual = _read_json(target)
        if dict(actual) != dict(expected):
            raise SystemExit(f"existing orchestration artifact differs from deterministic evidence: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(dict(expected), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
    except FileExistsError as exc:
        raise SystemExit(f"orchestration artifact appeared concurrently: {target}") from exc


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
            "Resume-safe US-A0 PILOT experiment assembly. Reconstruct the exact three committed "
            "runs, assemble the three arms without row-level financial recomputation, apply the "
            "frozen deterministic Gate assessment, and append EXPERIMENT_ASSEMBLED checkpoint."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument("--launch-bundle", type=Path, required=True)
    parser.add_argument("--runtime-policy", type=Path, required=True)
    parser.add_argument("--run-evidence-checkpoint", type=Path, required=True)
    parser.add_argument("--run-progress", type=Path, required=True)
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
    parser.add_argument("--output-root", type=Path, default=Path("reports/us_a0/experiment"))
    parser.add_argument(
        "--checkpoint-output",
        type=Path,
        default=Path("reports/us_a0/pilot_launch/checkpoint_03_experiment_assembled.json"),
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
    if run_checkpoint.state is not USAgentValuePilotOrchestrationState.RUN_EVIDENCE_COMPLETE:
        raise SystemExit("PILOT experiment assembly requires RUN_EVIDENCE_COMPLETE checkpoint")
    if run_checkpoint.launch_bundle_id != launch_artifacts.launch_bundle.launch_bundle_id:
        raise SystemExit("RUN_EVIDENCE_COMPLETE checkpoint/launch identity mismatch")
    if run_checkpoint.runtime_policy_id != runtime_policy.runtime_policy_id:
        raise SystemExit("RUN_EVIDENCE_COMPLETE checkpoint/runtime-policy identity mismatch")
    run_progress = parse_us_a0_pilot_run_progress(_read_json(args.run_progress))

    manual_document = _read_json(args.manual_run)
    programmatic_document = _read_json(args.programmatic_run)
    agent_document = _read_json(args.agent_run)
    controls = validate_us_a0_pilot_control_documents(
        launch_artifacts,
        (manual_document, programmatic_document),
    )
    agent_generation = parse_candidate_generation_run(agent_document, execution_plan)
    if agent_generation.run_id != run_checkpoint.agent_generation_run_id:
        raise SystemExit("AGENT generation run differs from frozen orchestration checkpoint")
    generation_documents = {
        controls[0].spec.run_spec_id: manual_document,
        controls[1].spec.run_spec_id: programmatic_document,
        agent_generation.spec.run_spec_id: agent_document,
    }
    if set(generation_documents) != {spec.run_spec_id for spec in execution_plan.run_specs}:
        raise SystemExit("PILOT generation-run set differs from exact ExecutionPlan")

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
    output_root = args.output_root.expanduser().resolve()
    arm_paths = tuple(
        output_root / f"us_a0_{result.arm.value.lower()}_search_arm_result.json"
        for result in artifacts.arm_results
    )
    experiment_path = output_root / "us_a0_agent_value_experiment.json"
    comparison_path = output_root / "us_a0_agent_value_comparison.json"
    graph_path = output_root / "us_a0_agent_value_evidence_graph.json"
    assessment_path = output_root / "us_a0_pilot_gate_assessment.json"
    manifest_path = output_root / "us_a0_pilot_experiment_assembly_manifest.json"
    checkpoint_path = args.checkpoint_output.expanduser().resolve()

    for path, result in zip(arm_paths, artifacts.arm_results, strict=True):
        _write_or_validate(path, result.to_dict())
    _write_or_validate(experiment_path, artifacts.experiment.to_dict())
    _write_or_validate(comparison_path, artifacts.comparison.to_dict())
    _write_or_validate(graph_path, artifacts.evidence_graph.to_dict())
    _write_or_validate(assessment_path, artifacts.assessment.to_dict())
    _write_or_validate(manifest_path, artifacts.assembly_manifest.to_dict())
    _write_or_validate(checkpoint_path, artifacts.checkpoint.to_dict())

    validate_us_a0_pilot_experiment_documents(
        artifacts,
        arm_documents=tuple(_read_json(path) for path in arm_paths),
        experiment_document=_read_json(experiment_path),
        comparison_document=_read_json(comparison_path),
        graph_document=_read_json(graph_path),
        assessment_document=_read_json(assessment_path),
        manifest_document=_read_json(manifest_path),
        checkpoint_document=_read_json(checkpoint_path),
    )
    print(
        json.dumps(
            {
                "state": artifacts.checkpoint.state.value,
                "checkpoint_id": artifacts.checkpoint.checkpoint_id,
                "previous_checkpoint_id": artifacts.checkpoint.previous_checkpoint_id,
                "experiment_id": artifacts.experiment.experiment_id,
                "comparison_snapshot_id": artifacts.comparison.snapshot_id,
                "evidence_graph_id": artifacts.evidence_graph.graph_id,
                "assessment_id": artifacts.assessment.assessment_id,
                "machine_decision": artifacts.assessment.decision.value,
                "assembly_manifest_id": artifacts.assembly_manifest.manifest_id,
                "ready_for_independent_gate_review": True,
                "agent_value_gate_authority": False,
                "alpha_authority": False,
                "stage_exit_authority": False,
                "output_root": str(output_root),
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
