from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from finagent.research.us_r1_evaluation_policy import USR1StatisticalEvaluationPolicy
from finagent.research.us_r1_final import (
    USR1FinalInferenceArtifacts,
    build_us_r1_final_inference_artifacts,
)
from finagent.research.us_r1_gate import USR1AlphaGatePolicy
from finagent.research.us_r1_materialization import canonical_us_r1_feature_formation_policy
from finagent.research.us_r1_pipeline import (
    build_reconstructed_period_metric_artifact,
    load_us_r1_fold_materialization,
    reconstruct_us_r1_statistics,
    serialize_us_r1_period_metric_records,
)
from finagent.research.us_r1_protocol import USR1CandidateDenominator
from finagent.research.us_r1_statistics import USR1FoldStatisticsReport


def _read_mapping(path: Path) -> Mapping[str, object]:
    loaded = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return loaded



def validate_persisted_us_r1_final_evidence(
    denominator: USR1CandidateDenominator,
    *,
    research_protocol_id: str,
    walk_forward_protocol_id: str,
    evaluation_policy: USR1StatisticalEvaluationPolicy,
    alpha_gate_policy: USR1AlphaGatePolicy,
    fold_report_root: str | Path,
    fold_data_root: str | Path,
    final_report_root: str | Path,
    final_metric_root: str | Path,
) -> USR1FinalInferenceArtifacts:
    loaded = (
        load_us_r1_fold_materialization(
            fold_ordinal=1,
            report_root=fold_report_root,
            data_root=fold_data_root,
            denominator=denominator,
        ),
        load_us_r1_fold_materialization(
            fold_ordinal=2,
            report_root=fold_report_root,
            data_root=fold_data_root,
            denominator=denominator,
        ),
        load_us_r1_fold_materialization(
            fold_ordinal=3,
            report_root=fold_report_root,
            data_root=fold_data_root,
            denominator=denominator,
        ),
    )
    reconstructed = reconstruct_us_r1_statistics(loaded, denominator, evaluation_policy)
    report_root = Path(final_report_root).expanduser().resolve()
    metric_root = Path(final_metric_root).expanduser().resolve()
    if dict(_read_mapping(report_root / "us_r1_direction_evidence.json")) != (
        reconstructed.direction_evidence.to_dict()
    ):
        raise ValueError("persisted US-R1 direction evidence differs from replay")

    fold_reports: list[USR1FoldStatisticsReport] = []
    metric_artifacts = []
    fold_records = []
    for fold in reconstructed.folds:
        payload = serialize_us_r1_period_metric_records(fold.records)
        metric_path = metric_root / f"fold_{fold.fold_ordinal:02d}" / "us_r1_period_metrics.jsonl"
        if metric_path.read_bytes() != payload:
            raise ValueError("persisted US-R1 period metrics differ from replay")
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
        fold_dir = report_root / f"fold_{fold.fold_ordinal:02d}"
        if dict(_read_mapping(fold_dir / "us_r1_period_metric_artifact.json")) != artifact.to_dict():
            raise ValueError("persisted US-R1 period metric artifact differs from replay")
        if dict(_read_mapping(fold_dir / "us_r1_fold_statistics.json")) != report.to_dict():
            raise ValueError("persisted US-R1 fold statistics differ from replay")
        metric_artifacts.append(artifact)
        fold_reports.append(report)
        fold_records.append(fold.records)

    formation = canonical_us_r1_feature_formation_policy()
    artifacts = build_us_r1_final_inference_artifacts(
        denominator,
        reconstructed.direction_evidence,
        fold_records,
        fold_reports,
        metric_artifacts,
        research_protocol_id=research_protocol_id,
        walk_forward_protocol_id=walk_forward_protocol_id,
        formation_policy_id=formation.policy_id,
        evaluation_policy=evaluation_policy,
        alpha_gate_policy=alpha_gate_policy,
        fold_materialization_manifest_ids=(
            loaded[0].manifest.manifest_id,
            loaded[1].manifest.manifest_id,
            loaded[2].manifest.manifest_id,
        ),
    )
    expected = (
        (
            report_root / "us_r1_family_evidence.json",
            artifacts.family.to_dict(),
            "family evidence",
        ),
        (
            report_root / "us_r1_alpha_gate_assessment.json",
            artifacts.assessment.to_dict(),
            "Alpha Gate assessment",
        ),
        (
            report_root / "us_r1_inference_evidence_graph.json",
            artifacts.graph.to_dict(),
            "inference evidence graph",
        ),
    )
    for path, document, label in expected:
        if dict(_read_mapping(path)) != document:
            raise ValueError(f"persisted US-R1 {label} differs from replay")
    return artifacts
