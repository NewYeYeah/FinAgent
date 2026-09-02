from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.research.us_baseline_walkforward_evidence import (
    assemble_us_b0_walk_forward_evidence,
    validate_canonical_us_b0_protocol_document,
)


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _read_status(path: Path) -> Mapping[str, object]:
    with path.open("rb") as handle:
        value = tomllib.load(handle)
    return cast(Mapping[str, object], value)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return cast(Mapping[str, object], value)


def _require_us_b0_stage_authority(status: Mapping[str, object]) -> None:
    if str(status.get("current_stage", "")).strip() != "US-B0":
        raise SystemExit(
            "docs/status.toml has not advanced to US-B0; split-bound formal evidence "
            "assembly is unavailable while US-D3 remains pending"
        )
    stages = _mapping(status.get("stage"), "status.stage")
    us_d3 = _mapping(stages.get("us_d3"), "status.stage.us_d3")
    if str(us_d3.get("status", "")).strip() != "accepted":
        raise SystemExit("status.stage.us_d3 must be accepted before formal US-B0 assembly")
    if us_d3.get("stage_exit_gate_passed") is not True:
        raise SystemExit("status.stage.us_d3.stage_exit_gate_passed must be true")


def _writable(path: Path, *, overwrite: bool) -> Path:
    target = path.expanduser().resolve()
    if target.exists() and not overwrite:
        raise SystemExit(f"output already exists; pass --overwrite explicitly: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _fold_dir(root: Path, ordinal: int) -> Path:
    return root / f"fold_{ordinal:02d}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Assemble the three preregistered US-B0 MANUAL fold reports into a content-addressed "
            "aggregate and evidence graph without recomputing authoritative fold statistics."
        )
    )
    parser.add_argument(
        "--status",
        type=Path,
        default=Path("docs/status.toml"),
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("reports/us_b0/us_b0_pilot_walkforward_protocol.json"),
    )
    parser.add_argument(
        "--fold-report-root",
        type=Path,
        default=Path("reports/us_b0/folds"),
    )
    parser.add_argument(
        "--aggregate-output",
        type=Path,
        default=Path("reports/us_b0/us_b0_walkforward_aggregate.json"),
    )
    parser.add_argument(
        "--graph-output",
        type=Path,
        default=Path("reports/us_b0/us_b0_walkforward_evidence_graph.json"),
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    _require_us_b0_stage_authority(_read_status(args.status.expanduser().resolve()))

    protocol_document = _read_mapping(args.protocol.expanduser().resolve())
    protocol = validate_canonical_us_b0_protocol_document(protocol_document)
    report_root = args.fold_report_root.expanduser().resolve()

    materializations: list[Mapping[str, object]] = []
    evaluations: list[Mapping[str, object]] = []
    persisted_manifests: list[Mapping[str, object]] = []
    for fold in protocol.folds:
        directory = _fold_dir(report_root, fold.ordinal)
        materializations.append(
            _read_mapping(directory / "us_b0_baseline_materialization.json")
        )
        evaluations.append(_read_mapping(directory / "us_b0_baseline_evaluation.json"))
        persisted_manifests.append(_read_mapping(directory / "us_b0_fold_run_manifest.json"))

    manifests, aggregate, graph = assemble_us_b0_walk_forward_evidence(
        protocol,
        materializations,
        evaluations,
    )
    for manifest, persisted in zip(manifests, persisted_manifests, strict=True):
        if dict(persisted) != manifest.to_dict():
            raise SystemExit(
                "persisted fold manifest does not match revalidated materialization/evaluation evidence: "
                f"fold {manifest.execution_spec.fold_ordinal}"
            )

    aggregate_output = _writable(args.aggregate_output, overwrite=args.overwrite)
    graph_output = _writable(args.graph_output, overwrite=args.overwrite)
    aggregate_output.write_text(
        json.dumps(aggregate.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    graph_output.write_text(
        json.dumps(graph.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "graph_id": graph.graph_id,
                "passed": graph.passed,
                "ready_for_us_a0_candidate": graph.ready_for_us_a0_candidate,
                "blockers": list(graph.blockers),
                "protocol_id": graph.protocol_id,
                "run_spec_id": graph.run_spec_id,
                "denominator_id": graph.denominator_id,
                "fold_manifest_ids": [item.manifest_id for item in manifests],
                "aggregate_report_id": aggregate.report_id,
                "aggregate_candidate_count": len(aggregate.candidates),
                "aggregate_valid_candidate_count": sum(
                    item.valid for item in aggregate.candidates
                ),
                "status_authority": False,
                "stage_exit_authority": False,
                "factor_selection_authority": False,
                "alpha_authority": False,
                "aggregate_output": str(aggregate_output),
                "graph_output": str(graph_output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if graph.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
