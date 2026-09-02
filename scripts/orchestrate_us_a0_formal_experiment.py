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
from finagent.research.us_agent_value_formal_launch import validate_us_a0_formal_launch_bundle
from finagent.research.us_agent_value_formal_postrun import (
    build_us_a0_formal_experiment_artifacts,
)
from finagent.research.us_agent_value_formal_run_orchestration import (
    parse_us_a0_formal_run_progress,
)
from finagent.research.us_agent_value_formal_runtime import (
    USAgentValueFormalOrchestrationState,
    parse_us_a0_formal_orchestration_checkpoint,
    validate_us_a0_formal_deepseek_runtime_policy,
)
from finagent.research.us_agent_value_gate import validate_us_a0_agent_value_gate_policy
from finagent.research.us_agent_value_protocol import USAgentValuePhase


def _read_json(path: Path) -> Mapping[str, object]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _read_status(path: Path) -> Mapping[str, object]:
    with path.expanduser().resolve().open("rb") as handle:
        return cast(Mapping[str, object], tomllib.load(handle))


def _write_or_validate(path: Path, document: Mapping[str, object] | dict[str, object]) -> None:
    target = path.expanduser().resolve()
    expected = dict(document)
    if target.exists():
        if dict(_read_json(target)) != expected:
            raise SystemExit(f"existing FORMAL experiment evidence differs from reconstruction: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(expected, sort_keys=True, indent=2, ensure_ascii=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministically assemble the exact seven-run US-A0 FORMAL experiment after "
            "RUN_EVIDENCE_COMPLETE. No row-level financial statistics are recomputed."
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
    parser.add_argument("--llm-config", type=Path, default=Path("configs/llm.toml"))
    parser.add_argument("--llm-profile", default="deepseek_official_v4_flash")
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    parser.add_argument(
        "--us-b0-evidence-graph",
        type=Path,
        default=Path("reports/us_b0/us_b0_walkforward_evidence_graph.json"),
    )
    parser.add_argument("--run-report-root", type=Path, default=Path("reports/us_a0/runs"))
    parser.add_argument("--output-root", type=Path, default=Path("reports/us_a0/formal_experiment"))
    parser.add_argument(
        "--checkpoint-output",
        type=Path,
        default=Path("reports/us_a0/formal_launch/checkpoint_03_experiment_assembled.json"),
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
        raise SystemExit("FORMAL experiment orchestration requires FORMAL preregistration")
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
    if run_checkpoint.state is not USAgentValueFormalOrchestrationState.RUN_EVIDENCE_COMPLETE:
        raise SystemExit("FORMAL experiment assembly requires RUN_EVIDENCE_COMPLETE checkpoint")
    if run_checkpoint.launch_bundle_id != launch.launch_bundle.launch_bundle_id:
        raise SystemExit("FORMAL run checkpoint/launch identity mismatch")
    if run_checkpoint.runtime_policy_id != runtime.runtime_policy_id:
        raise SystemExit("FORMAL run checkpoint/runtime identity mismatch")
    run_progress = parse_us_a0_formal_run_progress(_read_json(args.run_progress))
    predecessor = bind_authorized_us_a0_predecessor(
        status,
        _read_json(args.us_b0_evidence_graph),
        protocol,
    )

    if len(args.generation_run) != 7:
        raise SystemExit("FORMAL experiment assembly requires exactly seven --generation-run files")
    by_spec: dict[str, tuple[Mapping[str, object], object]] = {}
    for path in args.generation_run:
        document = _read_json(path)
        run = parse_candidate_generation_run(document, execution_plan)
        by_spec[run.spec.run_spec_id] = (document, run)
    expected_specs = tuple(spec.run_spec_id for spec in execution_plan.run_specs)
    if len(by_spec) != 7 or set(by_spec) != set(expected_specs):
        raise SystemExit("FORMAL experiment generation-run set differs from ExecutionPlan")

    parsed = []
    report_root = args.run_report_root.expanduser().resolve()
    for spec in execution_plan.run_specs:
        generation_document, run_object = by_spec[spec.run_spec_id]
        generation_run = parse_candidate_generation_run(generation_document, execution_plan)
        if generation_run != run_object:
            raise RuntimeError("FORMAL generation-run parse instability")
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
    output_root = args.output_root.expanduser().resolve()
    for result in artifacts.arm_results:
        _write_or_validate(
            output_root / f"us_a0_formal_{result.arm.value.lower()}_search_arm_result.json",
            result.to_dict(),
        )
    _write_or_validate(
        output_root / "us_a0_formal_agent_value_experiment.json",
        artifacts.experiment.to_dict(),
    )
    _write_or_validate(
        output_root / "us_a0_formal_agent_value_comparison.json",
        artifacts.comparison.to_dict(),
    )
    _write_or_validate(
        output_root / "us_a0_formal_agent_value_evidence_graph.json",
        artifacts.evidence_graph.to_dict(),
    )
    _write_or_validate(
        output_root / "us_a0_formal_gate_assessment.json",
        artifacts.assessment.to_dict(),
    )
    _write_or_validate(
        output_root / "us_a0_formal_experiment_assembly_manifest.json",
        artifacts.assembly_manifest.to_dict(),
    )
    _write_or_validate(args.checkpoint_output, artifacts.checkpoint.to_dict())
    print(
        json.dumps(
            {
                "phase": "FORMAL",
                "state": artifacts.checkpoint.state.value,
                "checkpoint_id": artifacts.checkpoint.checkpoint_id,
                "experiment_id": artifacts.experiment.experiment_id,
                "evidence_graph_id": artifacts.evidence_graph.graph_id,
                "assessment_id": artifacts.assessment.assessment_id,
                "machine_decision": artifacts.assessment.decision.value,
                "required_paired_quality_win_count": (
                    artifacts.assessment.required_paired_quality_win_count
                ),
                "paired_quality_win_count": artifacts.assessment.paired_quality_win_count,
                "agent_value_gate_authority": False,
                "alpha_authority": False,
                "stage_exit_authority": False,
                "output_root": str(output_root),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
