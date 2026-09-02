from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from finagent.domain.market_bars import BarInterval
from finagent.research.us_r1_evaluation_policy import USR1StatisticalEvaluationPolicy
from finagent.research.us_r1_materialization import (
    USR1CandidateObservation,
    USR1FoldMaterializationManifest,
    USR1ObservationRole,
)
from finagent.research.us_r1_materialization_bundle import (
    parse_us_r1_materialization_slice_bundle,
)
from finagent.research.us_r1_materialization_evidence import (
    parse_us_r1_fold_materialization_manifest,
)
from finagent.research.us_r1_observation_io import read_us_r1_observation_file
from finagent.research.us_r1_protocol import USR1CandidateDenominator
from finagent.research.us_r1_statistics import (
    USR1CandidateSliceStatistics,
    USR1DirectionEvidenceSet,
    USR1PeriodMetricArtifact,
    USR1PeriodMetricRecord,
    build_us_r1_direction_evidence,
    build_us_r1_fold_statistics,
)


_EXPECTED_SLICES = (
    (USR1ObservationRole.TRAIN, BarInterval.MINUTE_15, 60),
    (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_5, 60),
    (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_15, 30),
    (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_15, 60),
    (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_15, 120),
    (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_30, 60),
)


def _read_mapping(path: Path) -> Mapping[str, object]:
    loaded = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return loaded


def _slice_name(role: USR1ObservationRole, interval: BarInterval, horizon: int) -> str:
    return f"{role.value.lower()}_{interval.value}_{horizon}m"


@dataclass(frozen=True, slots=True)
class LoadedUSR1FoldMaterialization:
    manifest: USR1FoldMaterializationManifest
    train_observations: tuple[USR1CandidateObservation, ...]
    evaluation_observations: Mapping[
        tuple[BarInterval, int], tuple[USR1CandidateObservation, ...]
    ]


def load_us_r1_fold_materialization(
    *,
    fold_ordinal: int,
    report_root: str | Path,
    data_root: str | Path,
    denominator: USR1CandidateDenominator,
) -> LoadedUSR1FoldMaterialization:
    if fold_ordinal not in {1, 2, 3}:
        raise ValueError("US-R1 fold ordinal must be 1,2,3")
    report_base = Path(report_root).expanduser().resolve() / f"fold_{fold_ordinal:02d}"
    data_base = Path(data_root).expanduser().resolve() / f"fold_{fold_ordinal:02d}"
    manifest = parse_us_r1_fold_materialization_manifest(
        _read_mapping(report_base / "us_r1_fold_materialization_manifest.json")
    )
    if manifest.fold_ordinal != fold_ordinal:
        raise ValueError("US-R1 fold manifest ordinal/path mismatch")
    if manifest.denominator_id != denominator.denominator_id:
        raise ValueError("US-R1 fold manifest/denominator identity mismatch")

    train: tuple[USR1CandidateObservation, ...] | None = None
    evaluation: dict[tuple[BarInterval, int], tuple[USR1CandidateObservation, ...]] = {}
    for index, (role, interval, horizon) in enumerate(_EXPECTED_SLICES):
        name = _slice_name(role, interval, horizon)
        report_dir = report_base / name
        bundle = parse_us_r1_materialization_slice_bundle(
            input_plan_document=_read_mapping(report_dir / "us_r1_input_plan.json"),
            input_materialization_document=_read_mapping(
                report_dir / "us_r1_input_materialization.json"
            ),
            observation_artifact_document=_read_mapping(
                report_dir / "us_r1_observation_artifact.json"
            ),
            diagnostics_document=_read_mapping(
                report_dir / "us_r1_observation_diagnostics.json"
            ),
            slice_document=_read_mapping(report_dir / "us_r1_materialization_slice.json"),
        )
        if bundle.materialization_slice.to_dict() != manifest.slices[index].to_dict():
            raise ValueError("US-R1 persisted slice bundle differs from fold manifest")
        observations = read_us_r1_observation_file(
            data_base / name / "us_r1_observations.jsonl",
            bundle.observation_artifact,
            denominator,
        )
        if role is USR1ObservationRole.TRAIN:
            if train is not None:
                raise ValueError("US-R1 fold contains multiple TRAIN observation slices")
            train = observations
        else:
            evaluation[(interval, horizon)] = observations
    if train is None or len(evaluation) != 5:
        raise ValueError("US-R1 fold materialization is missing frozen observation slices")
    return LoadedUSR1FoldMaterialization(
        manifest=manifest,
        train_observations=train,
        evaluation_observations=evaluation,
    )


@dataclass(frozen=True, slots=True)
class ReconstructedUSR1FoldStatistics:
    fold_id: str
    fold_ordinal: int
    materialization_manifest_id: str
    records: tuple[USR1PeriodMetricRecord, ...]
    candidate_slices: tuple[USR1CandidateSliceStatistics, ...]


@dataclass(frozen=True, slots=True)
class ReconstructedUSR1Statistics:
    direction_evidence: USR1DirectionEvidenceSet
    folds: tuple[ReconstructedUSR1FoldStatistics, ...]


def reconstruct_us_r1_statistics(
    loaded_folds: tuple[
        LoadedUSR1FoldMaterialization,
        LoadedUSR1FoldMaterialization,
        LoadedUSR1FoldMaterialization,
    ],
    denominator: USR1CandidateDenominator,
    policy: USR1StatisticalEvaluationPolicy,
) -> ReconstructedUSR1Statistics:
    if tuple(item.manifest.fold_ordinal for item in loaded_folds) != (1, 2, 3):
        raise ValueError("US-R1 reconstruction requires folds ordered 1,2,3")
    first = loaded_folds[0]
    direction = build_us_r1_direction_evidence(
        first.train_observations,
        denominator,
        fold_id=first.manifest.fold_id,
        fold_materialization_manifest_id=first.manifest.manifest_id,
        policy=policy,
    )
    folds: list[ReconstructedUSR1FoldStatistics] = []
    for loaded in loaded_folds:
        records, candidate_slices = build_us_r1_fold_statistics(
            loaded.evaluation_observations,
            denominator,
            fold_id=loaded.manifest.fold_id,
            fold_ordinal=loaded.manifest.fold_ordinal,
            fold_materialization_manifest_id=loaded.manifest.manifest_id,
            policy=policy,
        )
        folds.append(
            ReconstructedUSR1FoldStatistics(
                fold_id=loaded.manifest.fold_id,
                fold_ordinal=loaded.manifest.fold_ordinal,
                materialization_manifest_id=loaded.manifest.manifest_id,
                records=records,
                candidate_slices=candidate_slices,
            )
        )
    return ReconstructedUSR1Statistics(
        direction_evidence=direction,
        folds=tuple(folds),
    )


def serialize_us_r1_period_metric_records(
    records: tuple[USR1PeriodMetricRecord, ...],
) -> bytes:
    ordered = sorted(
        records,
        key=lambda item: (
            item.candidate_id,
            item.signal_interval.value,
            item.label_horizon_trading_minutes,
            item.point.event_time,
        ),
    )
    return b"".join(
        json.dumps(
            record.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
        for record in ordered
    )


def build_reconstructed_period_metric_artifact(
    fold: ReconstructedUSR1FoldStatistics,
    denominator: USR1CandidateDenominator,
    policy: USR1StatisticalEvaluationPolicy,
    *,
    output_filename: str = "us_r1_period_metrics.jsonl",
) -> USR1PeriodMetricArtifact:
    payload = serialize_us_r1_period_metric_records(fold.records)
    return USR1PeriodMetricArtifact(
        fold_id=fold.fold_id,
        fold_ordinal=fold.fold_ordinal,
        denominator_id=denominator.denominator_id,
        evaluation_policy_id=policy.policy_id,
        row_count=len(fold.records),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        output_filename=output_filename,
    )
