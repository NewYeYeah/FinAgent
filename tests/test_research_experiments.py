from datetime import timedelta

import pytest

from finagent.domain.experiments import (
    ArtifactRef,
    ArtifactType,
    ExperimentResult,
    ExperimentRun,
    ExperimentRunStatus,
    ExperimentSpec,
)
from finagent.domain.research import ResearchDataset, TimeRange


def artifact(artifact_id: str, artifact_type: ArtifactType, digest: str) -> ArtifactRef:
    return ArtifactRef(artifact_id, artifact_type, version="1", digest=digest)


def test_research_dataset_is_schema_contract_not_dataframe(now, assets):
    dataset = ResearchDataset(
        artifact=artifact("prices-v1", ArtifactType.DATASET, "a" * 64),
        universe=assets,
        features=("ret_1", "vol_20"),
        labels=("fwd_ret_1",),
        splits={
            "train": TimeRange(now - timedelta(days=100), now - timedelta(days=30)),
            "valid": TimeRange(now - timedelta(days=30), now - timedelta(days=10)),
            "test": TimeRange(now - timedelta(days=10), now),
        },
    )
    assert dataset.point_in_time is True
    assert dataset.artifact.artifact_type is ArtifactType.DATASET
    with pytest.raises(TypeError):
        dataset.splits["x"] = dataset.splits["test"]  # type: ignore[index]


def test_research_dataset_rejects_non_dataset_artifact(now, assets):
    with pytest.raises(ValueError, match="artifact_type=DATASET"):
        ResearchDataset(
            artifact=artifact("model", ArtifactType.MODEL, "b" * 64),
            universe=assets,
            features=("x",),
            labels=("y",),
            splits={"train": TimeRange(now - timedelta(days=1), now)},
        )


def test_experiment_fingerprint_tracks_reproducibility_inputs(assets):
    dataset = artifact("dataset", ArtifactType.DATASET, "a" * 64)
    code = artifact("code", ArtifactType.CODE, "b" * 64)
    spec1 = ExperimentSpec(
        experiment_id="exp-001",
        hypothesis="Short-horizon reversal exists.",
        dataset=dataset,
        code=code,
        universe=assets,
        parameters={"lag": 1, "window": 20},
        seed=42,
    )
    spec2 = ExperimentSpec(
        experiment_id="exp-001",
        hypothesis="Short-horizon reversal exists.",
        dataset=dataset,
        code=code,
        universe=tuple(reversed(assets)),
        parameters={"window": 20, "lag": 1},
        seed=42,
    )
    spec3 = ExperimentSpec(
        experiment_id="exp-001",
        hypothesis="Short-horizon reversal exists.",
        dataset=dataset,
        code=code,
        universe=assets,
        parameters={"lag": 2, "window": 20},
        seed=42,
    )

    assert spec1.fingerprint == spec2.fingerprint
    assert spec1.fingerprint != spec3.fingerprint


def test_terminal_experiment_run_requires_finished_at(now):
    with pytest.raises(ValueError, match="require finished_at"):
        ExperimentRun(
            run_id="run-1",
            spec_fingerprint="f" * 64,
            status=ExperimentRunStatus.SUCCEEDED,
            started_at=now,
        )


def test_experiment_result_metrics_must_be_finite():
    with pytest.raises(ValueError, match="finite"):
        ExperimentResult(run_id="run-1", metrics={"sharpe": float("nan")}, passed=False)
