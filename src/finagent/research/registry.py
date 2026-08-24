from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiments import (
    ArtifactRef,
    ArtifactType,
    ExperimentResult,
    ExperimentRun,
    ExperimentRunStatus,
    ExperimentSpec,
)
from finagent.domain.model_registry import (
    ModelStage,
    ModelStageEvent,
    RegisteredModel,
    validate_model_transition,
)


def _artifact_dict(ref: ArtifactRef) -> dict:
    return {
        "artifact_id": ref.artifact_id,
        "artifact_type": ref.artifact_type.value,
        "version": ref.version,
        "digest": ref.digest,
        "uri": ref.uri,
    }


def _artifact_from_dict(payload: dict) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=payload["artifact_id"],
        artifact_type=ArtifactType(payload["artifact_type"]),
        version=payload["version"],
        digest=payload["digest"],
        uri=payload.get("uri", ""),
    )


def _asset_dict(asset: AssetId) -> dict:
    return {
        "symbol": asset.symbol,
        "asset_type": asset.asset_type.value,
        "venue": asset.venue,
        "currency": asset.currency,
    }


def _asset_from_dict(payload: dict) -> AssetId:
    return AssetId(
        symbol=payload["symbol"],
        asset_type=AssetType(payload["asset_type"]),
        venue=payload.get("venue", ""),
        currency=payload.get("currency", "USD"),
    )


class SQLiteResearchRegistry:
    """Durable experiment, artifact and model-governance registry."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    PRIMARY KEY (artifact_id, version, digest)
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    spec_fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS results (
                    run_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS models (
                    model_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_stage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (model_id) REFERENCES models(model_id) ON DELETE CASCADE
                );
                """
            )

    def register_artifact(self, artifact: ArtifactRef) -> None:
        with self._connect() as con:
            con.execute(
                """INSERT OR REPLACE INTO artifacts
                   (artifact_id, version, artifact_type, digest, uri)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    artifact.artifact_id,
                    artifact.version,
                    artifact.artifact_type.value,
                    artifact.digest,
                    artifact.uri,
                ),
            )

    def get_artifact(self, artifact_id: str, version: str, digest: str) -> ArtifactRef:
        with self._connect() as con:
            row = con.execute(
                """SELECT artifact_type, uri FROM artifacts
                   WHERE artifact_id=? AND version=? AND digest=?""",
                (artifact_id, version, digest),
            ).fetchone()
        if row is None:
            raise KeyError((artifact_id, version, digest))
        return ArtifactRef(
            artifact_id=artifact_id,
            artifact_type=ArtifactType(row[0]),
            version=version,
            digest=digest,
            uri=row[1],
        )

    def register_experiment(self, spec: ExperimentSpec) -> None:
        payload = {
            "experiment_id": spec.experiment_id,
            "hypothesis": spec.hypothesis,
            "dataset": _artifact_dict(spec.dataset),
            "code": _artifact_dict(spec.code),
            "universe": [_asset_dict(asset) for asset in spec.universe],
            "parameters": dict(spec.parameters),
            "seed": spec.seed,
            "parent_artifacts": [_artifact_dict(ref) for ref in spec.parent_artifacts],
            "metadata": dict(spec.metadata),
        }
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO experiments (experiment_id, fingerprint, payload_json) VALUES (?, ?, ?)",
                (spec.experiment_id, spec.fingerprint, json.dumps(payload, sort_keys=True)),
            )

    def get_experiment(self, experiment_id: str) -> ExperimentSpec:
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM experiments WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            raise KeyError(experiment_id)
        payload = json.loads(row[0])
        return ExperimentSpec(
            experiment_id=payload["experiment_id"],
            hypothesis=payload["hypothesis"],
            dataset=_artifact_from_dict(payload["dataset"]),
            code=_artifact_from_dict(payload["code"]),
            universe=tuple(_asset_from_dict(item) for item in payload["universe"]),
            parameters=payload["parameters"],
            seed=int(payload["seed"]),
            parent_artifacts=tuple(_artifact_from_dict(item) for item in payload["parent_artifacts"]),
            metadata=payload["metadata"],
        )

    def register_run(self, run: ExperimentRun) -> None:
        payload = {
            "run_id": run.run_id,
            "spec_fingerprint": run.spec_fingerprint,
            "status": run.status.value,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "environment": dict(run.environment),
            "stdout_digest": run.stdout_digest,
        }
        with self._connect() as con:
            con.execute(
                """INSERT INTO runs (run_id, spec_fingerprint, payload_json) VALUES (?, ?, ?)
                   ON CONFLICT(run_id) DO UPDATE SET
                       spec_fingerprint=excluded.spec_fingerprint,
                       payload_json=excluded.payload_json""",
                (run.run_id, run.spec_fingerprint, json.dumps(payload, sort_keys=True)),
            )

    def get_run(self, run_id: str) -> ExperimentRun:
        from datetime import datetime

        with self._connect() as con:
            row = con.execute("SELECT payload_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        payload = json.loads(row[0])
        return ExperimentRun(
            run_id=payload["run_id"],
            spec_fingerprint=payload["spec_fingerprint"],
            status=ExperimentRunStatus(payload["status"]),
            started_at=datetime.fromisoformat(payload["started_at"]),
            finished_at=(
                datetime.fromisoformat(payload["finished_at"])
                if payload["finished_at"]
                else None
            ),
            environment=payload["environment"],
            stdout_digest=payload["stdout_digest"],
        )

    def register_result(self, result: ExperimentResult) -> None:
        payload = {
            "run_id": result.run_id,
            "metrics": dict(result.metrics),
            "passed": result.passed,
            "produced_artifacts": [_artifact_dict(ref) for ref in result.produced_artifacts],
            "notes": result.notes,
        }
        with self._connect() as con:
            if con.execute("SELECT 1 FROM runs WHERE run_id=?", (result.run_id,)).fetchone() is None:
                raise KeyError(f"run {result.run_id!r} must be registered before its result")
            con.execute(
                "INSERT OR REPLACE INTO results (run_id, payload_json) VALUES (?, ?)",
                (result.run_id, json.dumps(payload, sort_keys=True)),
            )

    def get_result(self, run_id: str) -> ExperimentResult:
        with self._connect() as con:
            row = con.execute("SELECT payload_json FROM results WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        payload = json.loads(row[0])
        return ExperimentResult(
            run_id=payload["run_id"],
            metrics=payload["metrics"],
            passed=bool(payload["passed"]),
            produced_artifacts=tuple(
                _artifact_from_dict(item) for item in payload["produced_artifacts"]
            ),
            notes=payload["notes"],
        )


    def register_model(self, model: RegisteredModel) -> None:
        self.register_artifact(model.artifact)
        payload = {
            "model_id": model.model_id,
            "family": model.family,
            "artifact": _artifact_dict(model.artifact),
            "stage": model.stage.value,
            "created_at": model.created_at.isoformat(),
            "metrics": dict(model.metrics),
            "metadata": dict(model.metadata),
        }
        with self._connect() as con:
            existing = con.execute(
                "SELECT payload_json FROM models WHERE model_id=?", (model.model_id,)
            ).fetchone()
            if existing is not None:
                existing_payload = json.loads(existing[0])
                if existing_payload["artifact"] != payload["artifact"]:
                    raise ValueError("model_id already exists with a different artifact")
                if existing_payload["stage"] != payload["stage"]:
                    raise ValueError("model stage changes must use promote_model")
            con.execute(
                "INSERT OR REPLACE INTO models (model_id, payload_json) VALUES (?, ?)",
                (model.model_id, json.dumps(payload, sort_keys=True)),
            )

    def get_model(self, model_id: str) -> RegisteredModel:
        from datetime import datetime

        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM models WHERE model_id=?", (model_id,)
            ).fetchone()
        if row is None:
            raise KeyError(model_id)
        payload = json.loads(row[0])
        return RegisteredModel(
            model_id=payload["model_id"],
            family=payload["family"],
            artifact=_artifact_from_dict(payload["artifact"]),
            stage=ModelStage(payload["stage"]),
            created_at=datetime.fromisoformat(payload["created_at"]),
            metrics=payload["metrics"],
            metadata=payload["metadata"],
        )

    def promote_model(
        self,
        model_id: str,
        to_stage: ModelStage,
        *,
        changed_at,
        reason: str,
        actor: str = "system",
    ) -> RegisteredModel:
        current = self.get_model(model_id)
        validate_model_transition(current.stage, to_stage)
        event = ModelStageEvent(
            model_id=model_id,
            from_stage=current.stage,
            to_stage=to_stage,
            changed_at=changed_at,
            reason=reason,
            actor=actor,
        )
        updated = RegisteredModel(
            model_id=current.model_id,
            family=current.family,
            artifact=current.artifact,
            stage=to_stage,
            created_at=current.created_at,
            metrics=current.metrics,
            metadata=current.metadata,
        )
        payload = {
            "model_id": updated.model_id,
            "family": updated.family,
            "artifact": _artifact_dict(updated.artifact),
            "stage": updated.stage.value,
            "created_at": updated.created_at.isoformat(),
            "metrics": dict(updated.metrics),
            "metadata": dict(updated.metadata),
        }
        event_payload = {
            "model_id": event.model_id,
            "from_stage": event.from_stage.value,
            "to_stage": event.to_stage.value,
            "changed_at": event.changed_at.isoformat(),
            "reason": event.reason,
            "actor": event.actor,
        }
        with self._connect() as con:
            con.execute(
                "UPDATE models SET payload_json=? WHERE model_id=?",
                (json.dumps(payload, sort_keys=True), model_id),
            )
            con.execute(
                "INSERT INTO model_stage_events (model_id, payload_json) VALUES (?, ?)",
                (model_id, json.dumps(event_payload, sort_keys=True)),
            )
        return updated

    def model_history(self, model_id: str) -> tuple[ModelStageEvent, ...]:
        from datetime import datetime

        self.get_model(model_id)
        with self._connect() as con:
            rows = con.execute(
                "SELECT payload_json FROM model_stage_events WHERE model_id=? ORDER BY id",
                (model_id,),
            ).fetchall()
        return tuple(
            ModelStageEvent(
                model_id=(payload := json.loads(row[0]))["model_id"],
                from_stage=ModelStage(payload["from_stage"]),
                to_stage=ModelStage(payload["to_stage"]),
                changed_at=datetime.fromisoformat(payload["changed_at"]),
                reason=payload["reason"],
                actor=payload["actor"],
            )
            for row in rows
        )
