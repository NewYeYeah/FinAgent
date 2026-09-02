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
    USAgentValueExecutionPlan,
    parse_candidate_generation_run,
    validate_us_a0_execution_plan,
)
from finagent.research.us_agent_value_experiment import USAgentValuePredecessorBinding
from finagent.research.us_agent_value_formal_launch import validate_us_a0_formal_launch_bundle
from finagent.research.us_agent_value_formal_run_orchestration import (
    USAgentValueFormalRunProgress,
    advance_us_a0_formal_run_progress,
    build_formal_run_evidence_complete_checkpoint,
    parse_us_a0_formal_run_progress,
    parse_us_a0_formal_run_promotion_intent,
    promotion_intent_from_parsed_evidence,
)
from finagent.research.us_agent_value_formal_runtime import (
    USAgentValueFormalOrchestrationState,
    parse_us_a0_formal_orchestration_checkpoint,
    validate_us_a0_formal_deepseek_runtime_policy,
)


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
        raise SystemExit(f"authoritative FORMAL orchestration evidence already exists: {target}") from exc


def _run_report_documents(report_dir: Path) -> tuple[Mapping[str, object], ...]:
    required = (
        report_dir / "us_a0_run_evaluation.json",
        report_dir / "us_a0_run_evaluation_link.json",
        report_dir / "us_a0_run_evidence_manifest.json",
    )
    missing = tuple(path.name for path in required if not path.exists())
    if missing:
        raise ValueError(f"incomplete FORMAL A0 run report directory {report_dir}; missing={list(missing)}")
    return tuple(_read_json(path) for path in required)


def _parse_run_report(
    *,
    report_dir: Path,
    generation_document: Mapping[str, object],
    execution_plan: USAgentValueExecutionPlan,
    predecessor: USAgentValuePredecessorBinding,
) -> ParsedUSAgentValueRunEvidence:
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
            "committed FORMAL EVALUATED run evidence is missing canonical supporting data: "
            f"{data_dir}"
        )


def _promotion_matches_parsed(
    intent_document: Mapping[str, object],
    parsed: ParsedUSAgentValueRunEvidence,
    execution_plan_id: str,
) -> None:
    intent = parse_us_a0_formal_run_promotion_intent(intent_document)
    pairs = (
        (intent.execution_plan_id, execution_plan_id),
        (intent.run_spec_id, parsed.run_spec_id),
        (intent.generation_run_id, parsed.run_id),
        (intent.run_evidence_manifest_id, parsed.run_evidence_manifest_id),
        (intent.run_evaluation_report_id, parsed.run_evaluation_report_id),
        (intent.run_evaluation_link_id, parsed.evaluation_link.link_id),
    )
    if any(left != right for left, right in pairs):
        raise ValueError("FORMAL promotion intent differs from validated run evidence")


def _recover_or_promote(
    *,
    work_dir: Path,
    final_data_dir: Path,
    final_report_dir: Path,
    generation_document: Mapping[str, object],
    execution_plan: USAgentValueExecutionPlan,
    predecessor: USAgentValuePredecessorBinding,
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
        raise ValueError("FORMAL promotion intent exists but staged/canonical reports are missing")
    parsed = _parse_run_report(
        report_dir=final_report_dir,
        generation_document=generation_document,
        execution_plan=execution_plan,
        predecessor=predecessor,
    )
    _promotion_matches_parsed(intent_document, parsed, execution_plan.plan_id)
    _require_supporting_data(parsed, final_data_dir)
    shutil.rmtree(work_dir, ignore_errors=True)
    return parsed


def _materializer_command(
    *,
    root: Path,
    preregistration: Path,
    execution_plan: Path,
    generation_run: Path,
    pilot_gate_review: Path,
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
        "--pilot-gate-review",
        str(pilot_gate_review),
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
            "Resume-safe US-A0 FORMAL financial orchestration. Materialize the exact seven "
            "ExecutionPlan runs through the existing A0/B0 evaluator, stage each run, validate "
            "content-addressed evidence, promote once, and append immutable run progress."
        )
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument("--pilot-gate-review", type=Path, required=True)
    parser.add_argument("--launch-bundle", type=Path, required=True)
    parser.add_argument("--runtime-policy", type=Path, required=True)
    parser.add_argument("--agent-generation-checkpoint", type=Path, required=True)
    parser.add_argument(
        "--generation-run",
        type=Path,
        action="append",
        required=True,
        help="Repeat exactly seven times; order is ignored and rebound to the ExecutionPlan.",
    )
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
        default=Path("data/us_a0/formal_orchestration_work"),
    )
    parser.add_argument(
        "--progress-root",
        type=Path,
        default=Path("reports/us_a0/formal_launch/financial_progress"),
    )
    parser.add_argument(
        "--checkpoint-output",
        type=Path,
        default=Path("reports/us_a0/formal_launch/checkpoint_02_run_evidence_complete.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    prereg_path = args.preregistration.expanduser().resolve()
    plan_path = args.execution_plan.expanduser().resolve()
    gate_path = args.gate_policy.expanduser().resolve()
    pilot_review_path = args.pilot_gate_review.expanduser().resolve()
    launch_path = args.launch_bundle.expanduser().resolve()
    runtime_path = args.runtime_policy.expanduser().resolve()
    checkpoint_path = args.agent_generation_checkpoint.expanduser().resolve()
    status_path = args.status.expanduser().resolve()
    b0_graph_path = args.us_b0_evidence_graph.expanduser().resolve()

    preregistration = _read_json(prereg_path)
    execution_plan_document = _read_json(plan_path)
    protocol, execution_plan = validate_us_a0_execution_plan(execution_plan_document, preregistration)
    status = _read_status(status_path)
    gate_document = _read_json(gate_path)
    pilot_review_document = _read_json(pilot_review_path)
    launch = validate_us_a0_formal_launch_bundle(
        _read_json(launch_path),
        preregistration_document=preregistration,
        execution_plan_document=execution_plan_document,
        gate_policy_document=gate_document,
        status_document=status,
        pilot_gate_review_document=pilot_review_document,
    )
    profile = load_llm_profile(args.llm_config.expanduser().resolve(), args.llm_profile)
    runtime = validate_us_a0_formal_deepseek_runtime_policy(
        _read_json(runtime_path),
        profile=profile,
        launch_artifacts=launch,
    )
    agent_checkpoint = parse_us_a0_formal_orchestration_checkpoint(_read_json(checkpoint_path))
    if agent_checkpoint.state is not USAgentValueFormalOrchestrationState.AGENT_GENERATION_COMPLETE:
        raise SystemExit("FORMAL financial orchestration requires AGENT_GENERATION_COMPLETE")
    if agent_checkpoint.launch_bundle_id != launch.launch_bundle.launch_bundle_id:
        raise SystemExit("FORMAL Agent checkpoint/launch identity mismatch")
    if agent_checkpoint.runtime_policy_id != runtime.runtime_policy_id:
        raise SystemExit("FORMAL Agent checkpoint/runtime identity mismatch")
    if agent_checkpoint.pilot_gate_review_id != launch.pilot_gate_review_id:
        raise SystemExit("FORMAL Agent checkpoint/PILOT review identity mismatch")

    if len(args.generation_run) != 7:
        raise SystemExit("FORMAL financial orchestration requires exactly seven --generation-run files")
    input_pairs = []
    for path in args.generation_run:
        resolved = path.expanduser().resolve()
        document = _read_json(resolved)
        run = parse_candidate_generation_run(document, execution_plan)
        input_pairs.append((run, resolved, document))
    by_spec = {run.spec.run_spec_id: (run, path, document) for run, path, document in input_pairs}
    expected_specs = tuple(spec.run_spec_id for spec in execution_plan.run_specs)
    if len(by_spec) != 7 or set(by_spec) != set(expected_specs):
        raise SystemExit("FORMAL generation-run set does not match the exact seven-run ExecutionPlan")

    controls_by_spec = {run.spec.run_spec_id: run for run in launch.control_runs}
    for spec in execution_plan.run_specs[:4]:
        run = by_spec[spec.run_spec_id][0]
        expected = controls_by_spec.get(spec.run_spec_id)
        if expected is None or run.run_id != expected.run_id:
            raise SystemExit("FORMAL control generation run differs from frozen launch evidence")
    agent_specs = tuple(spec for spec in execution_plan.run_specs if spec.arm.value == "AGENT")
    for index, spec in enumerate(agent_specs):
        if by_spec[spec.run_spec_id][0].run_id != agent_checkpoint.agent_generation_run_ids[index]:
            raise SystemExit("FORMAL AGENT generation run differs from frozen checkpoint")

    predecessor = bind_authorized_us_a0_predecessor(status, _read_json(b0_graph_path), protocol)
    final_data_parent = args.data_output_root.expanduser().resolve()
    final_report_parent = args.report_output_root.expanduser().resolve()
    work_parent = args.work_root.expanduser().resolve()
    progress_root = args.progress_root.expanduser().resolve()
    progress_paths = tuple(
        progress_root / f"run_progress_{index:02d}_{spec.arm.value.lower()}_{spec.run_ordinal:02d}.json"
        for index, spec in enumerate(execution_plan.run_specs, start=1)
    )
    seen_missing = False
    for path in progress_paths:
        if not path.exists():
            seen_missing = True
        elif seen_missing:
            raise SystemExit("FORMAL financial progress files must form a contiguous ordered prefix")

    previous_progress: USAgentValueFormalRunProgress | None = None
    for run_order, spec in enumerate(execution_plan.run_specs, start=1):
        generation_run, generation_path, generation_document = by_spec[spec.run_spec_id]
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
            if work_dir.exists():
                shutil.rmtree(work_dir)
            staged_data_root = work_dir / "data"
            staged_report_root = work_dir / "reports"
            temp_dir = work_dir / "duckdb_temp"
            command = _materializer_command(
                root=args.root.expanduser().resolve(),
                preregistration=prereg_path,
                execution_plan=plan_path,
                generation_run=generation_path,
                pilot_gate_review=pilot_review_path,
                status=status_path,
                us_b0_evidence_graph=b0_graph_path,
                calendar=args.calendar.expanduser().resolve(),
                certification=args.certification.expanduser().resolve(),
                engineering_universe=args.engineering_universe.expanduser().resolve(),
                memory_limit=args.memory_limit,
                threads=args.threads,
                max_temp_directory_size=args.max_temp_directory_size,
                temp_directory=temp_dir,
                data_output_root=staged_data_root,
                report_output_root=staged_report_root,
            )
            subprocess.run(command, check=True)
            staged_report_dir = staged_report_root / run_id
            staged_data_dir = staged_data_root / run_id
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
                final_data_parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staged_data_dir), str(final_data_dir))
            final_report_parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staged_report_dir), str(final_report_dir))
            shutil.rmtree(work_dir, ignore_errors=True)
            parsed = _parse_run_report(
                report_dir=final_report_dir,
                generation_document=generation_document,
                execution_plan=execution_plan,
                predecessor=predecessor,
            )
            _require_supporting_data(parsed, final_data_dir)

        expected_progress = advance_us_a0_formal_run_progress(
            previous=previous_progress,
            execution_plan=execution_plan,
            agent_checkpoint=agent_checkpoint,
            predecessor=predecessor,
            parsed_run=parsed,
        )
        progress_path = progress_paths[run_order - 1]
        if progress_path.exists():
            stored = parse_us_a0_formal_run_progress(_read_json(progress_path))
            if stored != expected_progress:
                raise SystemExit("stored FORMAL financial progress differs from committed evidence")
            previous_progress = stored
        else:
            _write_once(progress_path, expected_progress.to_dict())
            previous_progress = expected_progress

    assert previous_progress is not None
    completed = build_formal_run_evidence_complete_checkpoint(
        agent_checkpoint=agent_checkpoint,
        execution_plan=execution_plan,
        progress=previous_progress,
    )
    checkpoint_target = args.checkpoint_output.expanduser().resolve()
    if checkpoint_target.exists():
        stored_checkpoint = parse_us_a0_formal_orchestration_checkpoint(_read_json(checkpoint_target))
        if stored_checkpoint != completed:
            raise SystemExit("existing FORMAL RUN_EVIDENCE_COMPLETE checkpoint differs from reconstruction")
        resumed = True
    else:
        _write_once(checkpoint_target, completed.to_dict())
        resumed = False
    print(
        json.dumps(
            {
                "phase": "FORMAL",
                "state": completed.state.value,
                "checkpoint_id": completed.checkpoint_id,
                "run_evidence_manifest_ids": list(completed.run_evidence_manifest_ids),
                "completed_run_count": previous_progress.progress_ordinal,
                "resumed": resumed,
                "financial_statistics_recomputed_in_orchestrator": False,
                "status_authority": False,
                "stage_exit_authority": False,
                "agent_value_gate_authority": False,
                "alpha_authority": False,
                "checkpoint_output": str(checkpoint_target),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
