from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from finagent.domain.experiment_family import ExperimentFamily, ExperimentFamilyStatus
from finagent.domain.experiments import ExperimentResult, ExperimentRun, ExperimentSpec
from finagent.domain.model_registry import ModelStage, RegisteredModel
from finagent.research.registry import SQLiteResearchRegistry


@dataclass(frozen=True, slots=True)
class ExperimentQuerySnapshot:
    spec: ExperimentSpec
    runs: tuple[ExperimentRun, ...]
    latest_result: ExperimentResult | None


class SQLiteResearchQueryService:
    """Read-only query facade over the Phase 1/2 research registry.

    The Agent tool layer depends on this service rather than opening the registry's
    private connection helper.  Only stable ids are read directly from SQLite; typed
    domain objects are reconstructed by the registry's public getters.
    """

    def __init__(self, registry: SQLiteResearchRegistry) -> None:
        self.registry = registry

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.registry.path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def list_families(
        self,
        *,
        status: ExperimentFamilyStatus | None = None,
    ) -> tuple[ExperimentFamily, ...]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT family_id FROM experiment_families ORDER BY family_id"
            ).fetchall()
        families = tuple(self.registry.get_family(row[0]) for row in rows)
        if status is None:
            return families
        return tuple(family for family in families if family.status is status)

    def list_experiments(self) -> tuple[ExperimentSpec, ...]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT experiment_id FROM experiments ORDER BY experiment_id"
            ).fetchall()
        return tuple(self.registry.get_experiment(row[0]) for row in rows)

    def list_models(
        self,
        *,
        stage: ModelStage | None = None,
    ) -> tuple[RegisteredModel, ...]:
        with self._connect() as con:
            rows = con.execute("SELECT model_id FROM models ORDER BY model_id").fetchall()
        models = tuple(self.registry.get_model(row[0]) for row in rows)
        if stage is None:
            return models
        return tuple(model for model in models if model.stage is stage)

    def runs_for_experiment(self, experiment_id: str) -> tuple[ExperimentRun, ...]:
        spec = self.registry.get_experiment(experiment_id)
        with self._connect() as con:
            rows = con.execute(
                "SELECT run_id FROM runs WHERE spec_fingerprint=?",
                (spec.fingerprint,),
            ).fetchall()
        runs = [self.registry.get_run(row[0]) for row in rows]
        runs.sort(key=lambda run: (run.started_at, run.run_id))
        return tuple(runs)

    def latest_result_for_experiment(self, experiment_id: str) -> ExperimentResult | None:
        for run in reversed(self.runs_for_experiment(experiment_id)):
            try:
                return self.registry.get_result(run.run_id)
            except KeyError:
                continue
        return None

    def experiment_snapshot(self, experiment_id: str) -> ExperimentQuerySnapshot:
        spec = self.registry.get_experiment(experiment_id)
        runs = self.runs_for_experiment(experiment_id)
        latest_result = None
        for run in reversed(runs):
            try:
                latest_result = self.registry.get_result(run.run_id)
                break
            except KeyError:
                continue
        return ExperimentQuerySnapshot(spec=spec, runs=runs, latest_result=latest_result)
