from finagent.domain.experiments import (
    ArtifactRef,
    ArtifactType,
    ExperimentResult,
    ExperimentRun,
    ExperimentRunStatus,
    ExperimentSpec,
)
from finagent.research import SQLiteResearchRegistry


def test_sqlite_registry_roundtrip(tmp_path, now, assets):
    registry = SQLiteResearchRegistry(tmp_path / "registry.db")
    dataset = ArtifactRef("dataset", ArtifactType.DATASET, "1", "a" * 64)
    code = ArtifactRef("code", ArtifactType.CODE, "1", "b" * 64)
    spec = ExperimentSpec(
        experiment_id="exp-1",
        hypothesis="AR(1) contains predictive information",
        dataset=dataset,
        code=code,
        universe=assets,
        parameters={"order": 1},
        seed=42,
    )
    run = ExperimentRun(
        run_id="run-1",
        spec_fingerprint=spec.fingerprint,
        status=ExperimentRunStatus.SUCCEEDED,
        started_at=now,
        finished_at=now,
        environment={"python": "3.11"},
    )
    model = ArtifactRef("model:ar", ArtifactType.MODEL, "phase1", "c" * 64)
    result = ExperimentResult(
        run_id="run-1",
        metrics={"sharpe": 0.8},
        passed=True,
        produced_artifacts=(model,),
    )
    registry.register_artifact(dataset)
    registry.register_experiment(spec)
    registry.register_run(run)
    registry.register_result(result)

    assert registry.get_artifact("dataset", "1", "a" * 64) == dataset
    assert registry.get_experiment("exp-1").fingerprint == spec.fingerprint
    assert registry.get_run("run-1") == run
    assert registry.get_result("run-1").metrics["sharpe"] == 0.8
