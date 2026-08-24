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
    """Minimal durable registry for Phase 1 experiments and artifacts."""

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
                "INSERT OR REPLACE INTO runs (run_id, spec_fingerprint, payload_json) VALUES (?, ?, ?)",
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
