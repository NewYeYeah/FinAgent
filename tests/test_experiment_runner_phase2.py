from datetime import timedelta

import pytest

from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentRunStatus, ExperimentSpec
from finagent.research import ExperimentEvaluation, ExperimentRunner, SQLiteResearchRegistry


def _spec(now, assets):
    return ExperimentSpec(
        experiment_id="phase2-exp",
        hypothesis="walk-forward validation is stable",
        dataset=ArtifactRef("dataset", ArtifactType.DATASET, "1", "a" * 64),
        code=ArtifactRef("code", ArtifactType.CODE, "1", "b" * 64),
        universe=assets,
        parameters={"purge": 1},
        seed=7,
    )


def test_experiment_runner_records_success_and_artifacts(tmp_path, now, assets):
    registry = SQLiteResearchRegistry(tmp_path / "registry.db")
    times = iter([now, now + timedelta(seconds=2)])
    runner = ExperimentRunner(
        registry,
        clock=lambda: next(times),
        run_id_factory=lambda: "run-phase2-success",
        environment={"python": "test"},
    )
    model = ArtifactRef("model:ar", ArtifactType.MODEL, "phase2", "c" * 64)
    result = runner.run(
        _spec(now, assets),
        lambda spec: ExperimentEvaluation(
            metrics={"sharpe": 1.1, "max_drawdown": -0.08},
            passed=True,
            produced_artifacts=(model,),
            notes="accepted",
        ),
    )
    run = registry.get_run(result.run_id)
    assert run.status is ExperimentRunStatus.SUCCEEDED
    assert run.finished_at == now + timedelta(seconds=2)
    assert registry.get_result(result.run_id) == result
    assert registry.get_artifact(model.artifact_id, model.version, model.digest) == model


def test_experiment_runner_records_terminal_failure(tmp_path, now, assets):
    registry = SQLiteResearchRegistry(tmp_path / "registry.db")
    times = iter([now, now + timedelta(seconds=1)])
    runner = ExperimentRunner(
        registry,
        clock=lambda: next(times),
        run_id_factory=lambda: "run-phase2-failure",
    )

    def fail(_):
        raise RuntimeError("numerical failure")

    with pytest.raises(RuntimeError, match="numerical failure"):
        runner.run(_spec(now, assets), fail)
    run = registry.get_run("run-phase2-failure")
    assert run.status is ExperimentRunStatus.FAILED
    assert run.finished_at == now + timedelta(seconds=1)
    with pytest.raises(KeyError):
        registry.get_result("run-phase2-failure")
