from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
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


def _read_json(path: Path) -> Mapping[str, object]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _read_status(path: Path) -> Mapping[str, object]:
    with path.expanduser().resolve().open("rb") as handle:
        return cast(Mapping[str, object], tomllib.load(handle))


def _write_json(path: Path, payload: Mapping[str, object] | dict[str, object], *, overwrite: bool) -> None:
    target = path.expanduser().resolve()
    if target.exists() and not overwrite:
        raise SystemExit(f"output already exists; pass --overwrite explicitly: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(dict(payload), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Assemble all preregistered US-A0 run evidence into MANUAL/PROGRAMMATIC/AGENT "
            "SearchArmResult objects, AgentValueExperiment, structural comparison and a final "
            "content-addressed experiment evidence graph. No financial statistics are recomputed."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument(
        "--generation-run",
        type=Path,
        action="append",
        required=True,
        help="Repeat once for every run authorized by the frozen ExecutionPlan.",
    )
    parser.add_argument(
        "--run-report-root",
        type=Path,
        default=Path("reports/us_a0/runs"),
    )
    parser.add_argument(
        "--status",
        type=Path,
        default=Path("docs/status.toml"),
    )
    parser.add_argument(
        "--us-b0-evidence-graph",
        type=Path,
        default=Path("reports/us_b0/us_b0_walkforward_evidence_graph.json"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("reports/us_a0/experiment"),
    )
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
    status = _read_status(args.status)
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
        run_evaluation = _read_json(report_root / "us_a0_run_evaluation.json")
        evaluation_link = _read_json(report_root / "us_a0_run_evaluation_link.json")
        run_manifest = _read_json(report_root / "us_a0_run_evidence_manifest.json")
        parsed.append(
            parse_us_a0_run_evidence_bundle(
                execution_plan=execution_plan,
                predecessor=predecessor,
                generation_document=generation_document,
                run_evaluation_document=run_evaluation,
                evaluation_link_document=evaluation_link,
                run_manifest_document=run_manifest,
            )
        )

    arm_results, experiment, comparison, graph = assemble_us_a0_experiment_evidence(
        protocol=protocol,
        execution_plan=execution_plan,
        predecessor=predecessor,
        run_evidence=tuple(parsed),
    )
    output_root = args.output_root.expanduser().resolve()
    for result in arm_results:
        _write_json(
            output_root / f"us_a0_{result.arm.value.lower()}_search_arm_result.json",
            result.to_dict(),
            overwrite=args.overwrite,
        )
    _write_json(
        output_root / "us_a0_agent_value_experiment.json",
        experiment.to_dict(),
        overwrite=args.overwrite,
    )
    _write_json(
        output_root / "us_a0_agent_value_comparison.json",
        comparison.to_dict(),
        overwrite=args.overwrite,
    )
    _write_json(
        output_root / "us_a0_agent_value_evidence_graph.json",
        graph.to_dict(),
        overwrite=args.overwrite,
    )
    print(
        json.dumps(
            {
                "execution_plan_id": execution_plan.plan_id,
                "experiment_id": experiment.experiment_id,
                "comparison_snapshot_id": comparison.snapshot_id,
                "evidence_graph_id": graph.graph_id,
                "evidence_complete": graph.evidence_complete,
                "ready_for_agent_value_gate_review": graph.ready_for_agent_value_gate_review,
                "agent_value_gate_decision": "UNDECIDED_REQUIRES_SEPARATE_REVIEW",
                "agent_value_gate_authority": False,
                "alpha_authority": False,
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
