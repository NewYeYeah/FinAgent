from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.research.us_r1_authority import require_us_r1_stage_authority
from finagent.research.us_r1_contracts import (
    validate_us_r1_alpha_gate_policy,
    validate_us_r1_protocol_document,
)
from finagent.research.us_r1_evaluation_policy import (
    validate_us_r1_statistical_evaluation_policy,
)
from finagent.research.us_r1_final import build_us_r1_final_inference_artifacts
from finagent.research.us_r1_handoff import (
    parse_us_r1_candidate_denominator,
    validate_terminal_a0_review_document,
)
from finagent.research.us_r1_materialization import canonical_us_r1_feature_formation_policy
from finagent.research.us_r1_pipeline import (
    build_reconstructed_period_metric_artifact,
    load_us_r1_fold_materialization,
    reconstruct_us_r1_statistics,
    serialize_us_r1_period_metric_records,
)
from finagent.research.us_r1_statistics import (
    USR1FoldStatisticsReport,
    USR1PeriodMetricArtifact,
    USR1PeriodMetricRecord,
)
from finagent.research.us_r1_walkforward import validate_us_r1_walk_forward_document


def _read_mapping(path: Path) -> Mapping[str, object]:
    loaded = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], loaded)


def _read_status(path: Path) -> Mapping[str, object]:
    with path.expanduser().resolve().open("rb") as handle:
        return cast(Mapping[str, object], tomllib.load(handle))


def _write_or_validate_json(
    path: Path,
    document: Mapping[str, object] | dict[str, object],
) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = dict(document)
    if target.exists():
        actual = json.loads(target.read_text(encoding="utf-8"))
        if actual != expected:
            raise SystemExit(
                f"existing immutable US-R1 evidence differs from reconstruction: {target}"
            )
        return
    target.write_text(
        json.dumps(expected, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_or_validate_bytes(path: Path, payload: bytes) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != payload:
            raise SystemExit(f"existing immutable US-R1 metric artifact differs: {target}")
        return
    target.write_bytes(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruct the complete US-R1 three-fold OOS statistics, dependence-aware "
            "family evidence and deterministic Alpha Gate assessment from authoritative "
            "materialized observations. No market-data query is performed by this assembler."
        )
    )
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    parser.add_argument("--a0-gate-review", type=Path, required=True)
    parser.add_argument(
        "--research-protocol",
        type=Path,
        default=Path("reports/us_r1/us_r1_research_protocol.json"),
    )
    parser.add_argument(
        "--walk-forward",
        type=Path,
        default=Path("reports/us_r1/us_r1_walk_forward.json"),
    )
    parser.add_argument(
        "--formation-policy",
        type=Path,
        default=Path("reports/us_r1/us_r1_feature_formation_policy.json"),
    )
    parser.add_argument(
        "--evaluation-policy",
        type=Path,
        default=Path("reports/us_r1/us_r1_statistical_evaluation_policy.json"),
    )
    parser.add_argument(
        "--alpha-gate-policy",
        type=Path,
        default=Path("reports/us_r1/us_r1_alpha_gate_policy.json"),
    )
    parser.add_argument(
        "--candidate-denominator",
        type=Path,
        default=Path("reports/us_r1/us_r1_candidate_denominator.json"),
    )
    parser.add_argument("--fold-report-root", type=Path, default=Path("reports/us_r1/folds"))
    parser.add_argument("--fold-data-root", type=Path, default=Path("data/us_r1/folds"))
    parser.add_argument("--output-root", type=Path, default=Path("reports/us_r1/final"))
    parser.add_argument("--metric-output-root", type=Path, default=Path("data/us_r1/final"))
    return parser


def main() -> int:
    args = build_parser().parse_args()

    status = _read_status(args.status)
    authority = require_us_r1_stage_authority(status)
    review_id, review_phase, review_decision, review_experiment_id = (
        validate_terminal_a0_review_document(
            _read_mapping(args.a0_gate_review),
            authority=authority,
        )
    )
    research_protocol = validate_us_r1_protocol_document(
        dict(_read_mapping(args.research_protocol))
    )
    walk_forward = validate_us_r1_walk_forward_document(
        dict(_read_mapping(args.walk_forward))
    )
    formation = canonical_us_r1_feature_formation_policy()
    if dict(_read_mapping(args.formation_policy)) != formation.to_dict():
        raise SystemExit("US-R1 feature-formation policy differs from canonical preregistration")
    evaluation_policy = validate_us_r1_statistical_evaluation_policy(
        dict(_read_mapping(args.evaluation_policy))
    )
    alpha_gate_policy = validate_us_r1_alpha_gate_policy(
        dict(_read_mapping(args.alpha_gate_policy))
    )
    denominator = parse_us_r1_candidate_denominator(
        _read_mapping(args.candidate_denominator)
    )
    if denominator.protocol_id != research_protocol.protocol_id:
        raise SystemExit("US-R1 denominator/research-protocol identity mismatch")
    if denominator.a0_gate_review_id != review_id:
        raise SystemExit("US-R1 denominator/A0 terminal review identity mismatch")
    if denominator.a0_experiment_id != review_experiment_id:
        raise SystemExit("US-R1 denominator/A0 experiment identity mismatch")
    if (
        denominator.a0_phase is not review_phase
        or denominator.a0_gate_decision is not review_decision
    ):
        raise SystemExit("US-R1 denominator/A0 terminal phase or decision mismatch")

    loaded = (
        load_us_r1_fold_materialization(
            fold_ordinal=1,
            report_root=args.fold_report_root,
            data_root=args.fold_data_root,
            denominator=denominator,
        ),
        load_us_r1_fold_materialization(
            fold_ordinal=2,
            report_root=args.fold_report_root,
            data_root=args.fold_data_root,
            denominator=denominator,
        ),
        load_us_r1_fold_materialization(
            fold_ordinal=3,
            report_root=args.fold_report_root,
            data_root=args.fold_data_root,
            denominator=denominator,
        ),
    )
    reconstructed = reconstruct_us_r1_statistics(
        loaded,
        denominator,
        evaluation_policy,
    )

    output_root = args.output_root.expanduser().resolve()
    metric_root = args.metric_output_root.expanduser().resolve()
    _write_or_validate_json(
        output_root / "us_r1_direction_evidence.json",
        reconstructed.direction_evidence.to_dict(),
    )

    fold_reports: list[USR1FoldStatisticsReport] = []
    metric_artifacts: list[USR1PeriodMetricArtifact] = []
    fold_records: list[tuple[USR1PeriodMetricRecord, ...]] = []
    for fold in reconstructed.folds:
        payload = serialize_us_r1_period_metric_records(fold.records)
        metric_path = (
            metric_root
            / f"fold_{fold.fold_ordinal:02d}"
            / "us_r1_period_metrics.jsonl"
        )
        _write_or_validate_bytes(metric_path, payload)
        artifact = build_reconstructed_period_metric_artifact(
            fold,
            denominator,
            evaluation_policy,
            output_filename=metric_path.name,
        )
        report = USR1FoldStatisticsReport(
            fold_id=fold.fold_id,
            fold_ordinal=fold.fold_ordinal,
            fold_materialization_manifest_id=fold.materialization_manifest_id,
            denominator_id=denominator.denominator_id,
            evaluation_policy_id=evaluation_policy.policy_id,
            period_metric_artifact_id=artifact.artifact_id,
            candidate_slices=fold.candidate_slices,
        )
        fold_report_dir = output_root / f"fold_{fold.fold_ordinal:02d}"
        _write_or_validate_json(
            fold_report_dir / "us_r1_period_metric_artifact.json",
            artifact.to_dict(),
        )
        _write_or_validate_json(
            fold_report_dir / "us_r1_fold_statistics.json",
            report.to_dict(),
        )
        fold_reports.append(report)
        metric_artifacts.append(artifact)
        fold_records.append(fold.records)

    artifacts = build_us_r1_final_inference_artifacts(
        denominator,
        reconstructed.direction_evidence,
        fold_records,
        fold_reports,
        metric_artifacts,
        research_protocol_id=research_protocol.protocol_id,
        walk_forward_protocol_id=walk_forward.protocol_id,
        formation_policy_id=formation.policy_id,
        evaluation_policy=evaluation_policy,
        alpha_gate_policy=alpha_gate_policy,
        fold_materialization_manifest_ids=(
            loaded[0].manifest.manifest_id,
            loaded[1].manifest.manifest_id,
            loaded[2].manifest.manifest_id,
        ),
    )
    _write_or_validate_json(
        output_root / "us_r1_family_evidence.json",
        artifacts.family.to_dict(),
    )
    _write_or_validate_json(
        output_root / "us_r1_alpha_gate_assessment.json",
        artifacts.assessment.to_dict(),
    )
    _write_or_validate_json(
        output_root / "us_r1_inference_evidence_graph.json",
        artifacts.graph.to_dict(),
    )

    print(
        json.dumps(
            {
                "family_evidence_id": artifacts.family.evidence_id,
                "alpha_gate_assessment_id": artifacts.assessment.assessment_id,
                "inference_graph_id": artifacts.graph.graph_id,
                "terminal": artifacts.assessment.terminal.value,
                "robust_candidate_ids": list(artifacts.assessment.robust_candidate_ids),
                "technical_blockers": list(artifacts.assessment.technical_blockers),
                "direction_evidence_id": reconstructed.direction_evidence.evidence_id,
                "fold_statistics_report_ids": [item.report_id for item in fold_reports],
                "period_metric_artifact_ids": [item.artifact_id for item in metric_artifacts],
                "market_data_read": False,
                "statistics_reconstructed_from_materialized_observations": True,
                "alpha_gate_reviewed": False,
                "status_authority": False,
                "stage_exit_authority": False,
                "alpha_authority": False,
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if artifacts.assessment.terminal.value != "SYSTEM_FAILURE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
