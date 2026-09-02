from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.agents.providers import load_llm_profile
from finagent.research.us_agent_value_assembly import (
    ParsedUSAgentValueRunEvidence,
    parse_us_a0_run_evidence_bundle,
)
from finagent.research.us_agent_value_authority import bind_authorized_us_a0_predecessor
from finagent.research.us_agent_value_execution import (
    parse_candidate_generation_run,
    validate_us_a0_execution_plan,
)
from finagent.research.us_agent_value_launch import (
    validate_us_a0_pilot_control_documents,
    validate_us_a0_pilot_launch_bundle,
)
from finagent.research.us_agent_value_orchestration import (
    USAgentValuePilotOrchestrationState,
    parse_us_a0_pilot_orchestration_checkpoint,
)
from finagent.research.us_agent_value_run_orchestration import (
    USAgentValuePilotRunProgress,
    advance_us_a0_pilot_run_progress,
    build_run_evidence_complete_checkpoint,
    parse_us_a0_pilot_run_progress,
    parse_us_a0_pilot_run_promotion_intent,
    promotion_intent_from_parsed_evidence,
)
from finagent.research.us_agent_value_runtime import validate_us_a0_deepseek_runtime_policy


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
        raise SystemExit(f"authoritative orchestration evidence already exists: {target}") from exc


def _run_report_documents(report_dir: Path) -> tuple[Mapping[str, object], ...]:
    required = (
        report_dir / "us_a0_run_evaluation.json",
        report_dir / "us_a0_run_evaluation_link.json",
        report_dir / "us_a0_run_evidence_manifest.json",
    )
    missing = tuple(path.name for path in required if not path.exists())
    if missing:
        raise ValueError(f"incomplete A0 run report directory {report_dir}; missing={list(missing)}")
    return tuple(_read_json(path) for path in required)


def _parse_run_report(
    *,
    report_dir: Path,
    generation_document: Mapping[str, object],
    execution_plan: object,
    predecessor: object,
) -> ParsedUSAgentValueRunEvidence:
    from finagent.research.us_agent_value_execution import USAgentValueExecutionPlan
    from finagent.research.us_agent_value_experiment import USAgentValuePredecessorBinding

    if not isinstance(execution_plan, USAgentValueExecutionPlan):
        raise TypeError("execution_plan must be USAgentValueExecutionPlan")
    if not isinstance(predecessor, USAgentValuePredecessorBinding):
        raise TypeError("predecessor must be USAgentValuePredecessorBinding")
    evaluation, link, manifest = _run_report_documents(report_dir)
    return parse_us_a0_run_evidence_bundle(
        execution_plan=execution_plan,
        predecessor=predecessor,
        generation_document=generation_document,
        run_evaluation_document=evaluation,
        evaluation_link_document=link,
        run_manifest_document=manifest,
    )


def _require_supporting_data(parsed: ParsedUSAgentValueRunEvidence, data_dir: Path) -> None:
    if parsed.run_evaluation_status == "EVALUATED" and not data_dir.exists():
        raise ValueError(
            "committed EVALUATED A0 run evidence is missing its canonical supporting data directory: "
            f"{data_dir}"
        )


def _validate_intent_matches(
    parsed: ParsedUSAgentValueRunEvidence,
    intent_document: Mapping[str, object],
) -> None:
    intent = parse_us_a0_pilot_run_promotion_intent(intent_document)
    expected = promotion_intent_from_parsed_evidence(
        parsed,
        execution_plan=parsed_execution_plan_placeholder(parsed),
    )
    if intent.run_spec_id != expected.run_spec_id:
        raise ValueError("promotion intent/run-spec identity mismatch")
    if intent.generation_run_id != expected.generation_run_id:
        raise ValueError("promotion intent/generation-run identity mismatch")
    if intent.run_evidence_manifest_id != expected.run_evidence_manifest_id:
        raise ValueError("promotion intent/run-manifest identity mismatch")
    if intent.run_evaluation_report_id != expected.run_evaluation_report_id:
        raise ValueError("promotion intent/run-evaluation identity mismatch")
    if intent.run_evaluation_link_id != expected.run_evaluation_link_id:
        raise ValueError("promotion intent/evaluation-link identity mismatch")


def parsed_execution_plan_placeholder(parsed: ParsedUSAgentValueRunEvidence) -> object:
    """Never called for plan identity; retained only to keep intent comparison local."""
    return _IntentPlanAdapter(parsed)


class _IntentPlanAdapter:
    def __init__(self, parsed: ParsedUSAgentValueRunEvidence) -> None:
        self.plan_id = "unused"
        self.parsed = parsed


def _promotion_matches_parsed(
    intent_document: Mapping[str, object],
    parsed: ParsedUSAgentValueRunEvidence,
    execution_plan_id: str,
) -> None:
    intent = parse_us_a0_pilot_run_promotion_intent(intent_document)
    if intent.execution_plan_id != execution_plan_id:
        raise ValueError("promotion intent/execution-plan identity mismatch")
    pairs = (
        (intent.run_spec_id, parsed.run_spec_id),
        (intent.generation_run_id, parsed.run_id),
        (intent.run_evidence_manifest_id, parsed.run_evidence_manifest_id),
        (intent.run_evaluation_report_id, parsed.run_evaluation_report_id),
        (intent.run_evaluation_link_id, parsed.evaluation_link.link_id),
    )
    if any(left != right for left, right in pairs):
        raise ValueError("promotion intent differs from validated staged run evidence")


def _recover_or_promote(
    *,
    work_dir: Path,
    final_data_dir: Path,
    final_report_dir: Path,
    generation_document: Mapping[str, object],
    execution_plan: object,
    predecessor: object,
) -> ParsedUSAgentValueRunEvidence | None:
    intent_path = work_dir / "promotion_intent.json"
    if not intent_path.exists():
        return None
    intent_document = _read_json(intent_path)
    staged_data_dir = work_dir / "data" / final_data_dir.name
    staged_report_dir = work_dir / "reports" / final_report_dir.name

    if not final_data_dir.exists() and staged_data_dir.exists():
        final_data_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged_data_dir), str(final_data_dir))
    if not final_report_dir.exists() and staged_report_dir.exists():
        final_report_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged_report_dir), str(final_report_dir))
    if not final_report_dir.exists():
        raise ValueError("promotion intent exists but neither staged nor canonical report evidence exists")

    parsed = _parse_run_report(
        report_dir=final_report_dir,
        generation_document=generation_document,
        execution_plan=execution_plan,
        predecessor=predecessor,
    )
    plan_id = str(getattr(execution_plan, "plan_id"))
    _promotion_matches_parsed(intent_document, parsed, plan_id)
    _require_supporting_data(parsed, final_data_dir)
    shutil.rmtree(work_dir, ignore_errors=True)
    return parsed


def _build_materializer_command(
    *,
    root: Path,
    preregistration: Path,
    execution_plan: Path,
    generation_run: Path,
    status: Path,
    us_b0_evidence_graph: Path,
    calendar: Path,
    certification: Path,
    engineering_universe: Path,
    memory_limit: str,
    threads: int,
    max_temp_directory_size: str,
    temp_directory: Path,
    data_output_root: Path,
    report_output_root: Path,
) -> tuple[str, ...]:
    materializer = Path(__file__).resolve().with_name("materialize_us_a0_run.py")
    return (
        sys.executable,
        str(materializer),
        str(root),
        "--preregistration",
        str(preregistration),
        "--execution-plan",
        str(execution_plan),
        "--generation-run",
        str(generation_run),
        "--status",
        str(status),
        "--us-b0-evidence-graph",
        str(us_b0_evidence_graph),
        "--calendar",
        str(calendar),
        "--certification",
        str(certification),
        "--engineering-universe",
        str(engineering_universe),
        "--memory-limit",
        memory_limit,
        "--threads",
        str(threads),
        "--max-temp-directory-size",
        max_temp_directory_size,
        "--temp-directory",
        str(temp_directory),
        "--data-output-root",
        str(data_output_root),
        "--report-output-root",
        str(report_output_root),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resume-safe US-A0 PILOT financial orchestration. Validate the frozen launch/runtime "
            "and AGENT_GENERATED checkpoint, then materialize MANUAL, PROGRAMMATIC and AGENT in "
            "exact ExecutionPlan order. Each run is staged, strictly parsed and committed once."
        )
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument("--launch-bundle", type=Path, required=True)
    parser.add_argument("--runtime-policy", type=Path, required=True)
    parser.add_argument("--agent-generated-checkpoint", type=Path, required=True)
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
    parser.add_argument("--calendar", type=Path, default=Path("reports/us_calendar/xnys_1992_2026.json"))
    parser.add_argument(
        "--certification",
        type=Path,
        default=Path("reports/us_d3/us_minute_research_certification.json"),
    )
    parser.add_argument(
        "--engineering-universe",
        type=Path,
        default=Path("reports/us_instruments/us_i0_final_engineering_universe.json"),
    )
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--max-temp-directory-size", default="4GB")
    parser.add_argument("--data-output-root", type=Path, default=Path("data/us_a0/runs"))
    parser.add_argument("--report-output-root", type=Path, default=Path("reports/us_a0/runs"))
    parser.add_argument(
        "--work-root",
        type=Path,
        default=Path("data/us_a0/orchestration_work"),
        help="Non-authoritative staging; safe to discard only before promotion intent exists.",
    )
    parser.add_argument(
        "--progress-root",
        type=Path,
        default=Path("reports/us_a0/pilot_launch/run_progress"),
    )
    parser.add_argument(
        "--checkpoint-output",
        type=Path,
        default=Path("reports/us_a0/pilot_launch/checkpoint_02_run_evidence_complete.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    prereg_path = args.preregistration.expanduser().resolve()
    plan_path = args.execution_plan.expanduser().resolve()
    gate_path = args.gate_policy.expanduser().resolve()
    launch_path = args.launch_bundle.expanduser().resolve()
    runtime_path = args.runtime_policy.expanduser().resolve()
    checkpoint_path = args.agent_generated_checkpoint.expanduser().resolve()
    status_path = args.status.expanduser().resolve()
    b0_graph_path = args.us_b0_evidence_graph.expanduser().resolve()

    preregistration = _read_json(prereg_path)
    execution_plan_document = _read_json(plan_path)
    protocol, execution_plan = validate_us_a0_execution_plan(execution_plan_document, preregistration)
    gate_document = _read_json(gate_path)
    launch_document = _read_json(launch_path)
    launch_artifacts = validate_us_a0_pilot_launch_bundle(
        launch_document,
        preregistration_document=preregistration,
        execution_plan_document=execution_plan_document,
        gate_policy_document=gate_document,
    )
    profile = load_llm_profile(args.llm_config.expanduser().resolve(), args.llm_profile)
    _, runtime_policy = validate_us_a0_deepseek_runtime_policy(
        _read_json(runtime_path),
        profile=profile,
        preregistration_document=preregistration,
        execution_plan_document=execution_plan_document,
        gate_policy_document=gate_document,
        launch_bundle_document=launch_document,
    )
    agent_checkpoint = parse_us_a0_pilot_orchestration_checkpoint(_read_json(checkpoint_path))
    if agent_checkpoint.state is not USAgentValuePilotOrchestrationState.AGENT_GENERATED:
        raise SystemExit("run-evidence orchestration requires AGENT_GENERATED checkpoint")
    if agent_checkpoint.launch_bundle_id != launch_artifacts.launch_bundle.launch_bundle_id:
        raise SystemExit("AGENT_GENERATED checkpoint/launch identity mismatch")
    if agent_checkpoint.runtime_policy_id != runtime_policy.runtime_policy_id:
        raise SystemExit("AGENT_GENERATED checkpoint/runtime-policy identity mismatch")

    manual_path = args.manual_run.expanduser().resolve()
    programmatic_path = args.programmatic_run.expanduser().resolve()
    agent_path = args.agent_run.expanduser().resolve()
    manual_document = _read_json(manual_path)
    programmatic_document = _read_json(programmatic_path)
    agent_document = _read_json(agent_path)
    controls = validate_us_a0_pilot_control_documents(
        launch_artifacts,
        (manual_document, programmatic_document),
    )
    agent_generation = parse_candidate_generation_run(agent_document, execution_plan)
    if agent_generation.run_id != agent_checkpoint.agent_generation_run_id:
        raise SystemExit("AGENT generation run differs from AGENT_GENERATED checkpoint")

    by_spec = {run.spec.run_spec_id: run for run in (*controls, agent_generation)}
    path_by_spec = {
        controls[0].spec.run_spec_id: manual_path,
        controls[1].spec.run_spec_id: programmatic_path,
        agent_generation.spec.run_spec_id: agent_path,
    }
    if set(by_spec) != {spec.run_spec_id for spec in execution_plan.run_specs}:
        raise SystemExit("PILOT generation-run set does not match exact ExecutionPlan")

    status = _read_status(status_path)
    predecessor = bind_authorized_us_a0_predecessor(status, _read_json(b0_graph_path), protocol)

    final_data_parent = args.data_output_root.expanduser().resolve()
    final_report_parent = args.report_output_root.expanduser().resolve()
    work_parent = args.work_root.expanduser().resolve()
    progress_root = args.progress_root.expanduser().resolve()
    progress_paths = tuple(
        progress_root / f"run_progress_{index:02d}_{spec.arm.value.lower()}.json"
        for index, spec in enumerate(execution_plan.run_specs, start=1)
    )
    seen_missing = False
    for path in progress_paths:
        if not path.exists():
            seen_missing = True
        elif seen_missing:
            raise SystemExit("PILOT run-progress files must form a contiguous ordered prefix")

    previous_progress: USAgentValuePilotRunProgress | None = None
    committed: list[ParsedUSAgentValueRunEvidence] = []
    for run_order, spec in enumerate(execution_plan.run_specs, start=1):
        generation_run = by_spec[spec.run_spec_id]
        generation_document = _read_json(path_by_spec[spec.run_spec_id])
        run_id = generation_run.run_id
        final_data_dir = final_data_parent / run_id
        final_report_dir = final_report_parent / run_id
        work_dir = work_parent / run_id

        parsed: ParsedUSAgentValueRunEvidence | None = None
        if final_report_dir.exists():
            parsed = _parse_run_report(
                report_dir=final_report_dir,
                generation_document=generation_document,
                execution_plan=execution_plan,
                predecessor=predecessor,
            )
            _require_supporting_data(parsed, final_data_dir)
            if work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)
        else:
            parsed = _recover_or_promote(
                work_dir=work_dir,
                final_data_dir=final_data_dir,
                final_report_dir=final_report_dir,
                generation_document=generation_document,
                execution_plan=execution_plan,
                predecessor=predecessor,
            )

        if parsed is None:
            if final_data_dir.exists():
                raise SystemExit(
                    "canonical A0 data exists without committed run report/promotion intent; "
                    f"refuse destructive recovery: {final_data_dir}"
                )
            if work_dir.exists():
                shutil.rmtree(work_dir)
            stage_data_parent = work_dir / "data"
            stage_report_parent = work_dir / "reports"
            command = _build_materializer_command(
                root=args.root.expanduser().resolve(),
                preregistration=prereg_path,
                execution_plan=plan_path,
                generation_run=path_by_spec[spec.run_spec_id],
                status=status_path,
                us_b0_evidence_graph=b0_graph_path,
                calendar=args.calendar.expanduser().resolve(),
                certification=args.certification.expanduser().resolve(),
                engineering_universe=args.engineering_universe.expanduser().resolve(),
                memory_limit=args.memory_limit,
                threads=args.threads,
                max_temp_directory_size=args.max_temp_directory_size,
                temp_directory=work_dir / "duckdb_temp",
                data_output_root=stage_data_parent,
                report_output_root=stage_report_parent,
            )
            completed = subprocess.run(command, check=False)
            if completed.returncode != 0:
                raise SystemExit(
                    f"A0 materializer failed for run {run_id} with exit code {completed.returncode}; "
                    "staging is non-authoritative and will be replaced on the next retry"
                )
            staged_report_dir = stage_report_parent / run_id
            staged_data_dir = stage_data_parent / run_id
            parsed = _parse_run_report(
                report_dir=staged_report_dir,
                generation_document=generation_document,
                execution_plan=execution_plan,
                predecessor=predecessor,
            )
            _require_supporting_data(parsed, staged_data_dir)
            intent = promotion_intent_from_parsed_evidence(parsed, execution_plan=execution_plan)
            _write_once(work_dir / "promotion_intent.json", intent.to_dict())
            if staged_data_dir.exists():
                final_data_dir.parent.mkdir(parents=True, exist_ok=True)
                if final_data_dir.exists():
                    raise SystemExit(f"canonical A0 data appeared during promotion: {final_data_dir}")
                shutil.move(str(staged_data_dir), str(final_data_dir))
            final_report_dir.parent.mkdir(parents=True, exist_ok=True)
            if final_report_dir.exists():
                raise SystemExit(f"canonical A0 report appeared during promotion: {final_report_dir}")
            shutil.move(str(staged_report_dir), str(final_report_dir))
            parsed = _parse_run_report(
                report_dir=final_report_dir,
                generation_document=generation_document,
                execution_plan=execution_plan,
                predecessor=predecessor,
            )
            _promotion_matches_parsed(_read_json(work_dir / "promotion_intent.json"), parsed, execution_plan.plan_id)
            _require_supporting_data(parsed, final_data_dir)
            shutil.rmtree(work_dir, ignore_errors=True)

        assert parsed is not None
        progress_path = progress_paths[run_order - 1]
        if progress_path.exists():
            progress = parse_us_a0_pilot_run_progress(_read_json(progress_path))
            expected_previous = None if previous_progress is None else previous_progress.progress_id
            if progress.previous_progress_id != expected_previous:
                raise SystemExit("PILOT run-progress chain predecessor mismatch")
            if progress.completed_runs[-1].generation_run_id != parsed.run_id:
                raise SystemExit("PILOT run-progress/generation-run identity mismatch")
            if progress.completed_runs[-1].run_evidence_manifest_id != parsed.run_evidence_manifest_id:
                raise SystemExit("PILOT run-progress/run-manifest identity mismatch")
        else:
            progress = advance_us_a0_pilot_run_progress(
                previous=previous_progress,
                execution_plan=execution_plan,
                agent_checkpoint=agent_checkpoint,
                predecessor=predecessor,
                parsed_run=parsed,
            )
            _write_once(progress_path, progress.to_dict())
        previous_progress = progress
        committed.append(parsed)

    if previous_progress is None:
        raise RuntimeError("PILOT orchestration completed no runs")
    completed_checkpoint = build_run_evidence_complete_checkpoint(
        agent_checkpoint=agent_checkpoint,
        execution_plan=execution_plan,
        progress=previous_progress,
    )
    checkpoint_output = args.checkpoint_output.expanduser().resolve()
    if checkpoint_output.exists():
        existing = parse_us_a0_pilot_orchestration_checkpoint(_read_json(checkpoint_output))
        if existing != completed_checkpoint:
            raise SystemExit("existing RUN_EVIDENCE_COMPLETE checkpoint differs from validated evidence")
    else:
        _write_once(checkpoint_output, completed_checkpoint.to_dict())

    print(
        json.dumps(
            {
                "state": completed_checkpoint.state.value,
                "checkpoint_id": completed_checkpoint.checkpoint_id,
                "previous_checkpoint_id": completed_checkpoint.previous_checkpoint_id,
                "execution_plan_id": execution_plan.plan_id,
                "predecessor_binding_id": predecessor.binding_id,
                "generation_run_ids": [item.run_id for item in committed],
                "run_evidence_manifest_ids": [
                    item.run_evidence_manifest_id for item in committed
                ],
                "run_progress_id": previous_progress.progress_id,
                "run_count": len(committed),
                "folds_per_evaluated_run": 3,
                "resume_safe": True,
                "committed_evidence_overwrite_allowed": False,
                "agent_value_gate_authority": False,
                "alpha_authority": False,
                "checkpoint_output": str(checkpoint_output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
