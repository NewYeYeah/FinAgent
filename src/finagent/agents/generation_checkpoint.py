from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FeatureGenerationCheckpoint:
    logical_task_id: str
    artifact_digest: str
    prompt_hash: str
    recorded_at: str


class SQLiteFeatureGenerationCheckpointStore:
    """Resume accepted logical Agent candidates without another LLM call."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_generation_checkpoints (
                    logical_task_id TEXT PRIMARY KEY,
                    artifact_digest TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def get(self, logical_task_id: str) -> FeatureGenerationCheckpoint | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT logical_task_id, artifact_digest, prompt_hash, recorded_at "
                "FROM feature_generation_checkpoints WHERE logical_task_id=?",
                (logical_task_id,),
            ).fetchone()
        if row is None:
            return None
        return FeatureGenerationCheckpoint(
            logical_task_id=str(row[0]),
            artifact_digest=str(row[1]),
            prompt_hash=str(row[2]),
            recorded_at=str(row[3]),
        )

    def register(self, logical_task_id: str, artifact_digest: str, prompt_hash: str) -> None:
        logical_task_id = logical_task_id.strip()
        artifact_digest = artifact_digest.strip()
        prompt_hash = prompt_hash.strip()
        if not logical_task_id or not artifact_digest or not prompt_hash:
            raise ValueError("checkpoint identity fields cannot be empty")
        existing = self.get(logical_task_id)
        if existing is not None:
            if (
                existing.artifact_digest != artifact_digest
                or existing.prompt_hash != prompt_hash
            ):
                raise ValueError(
                    f"logical candidate {logical_task_id!r} already has a different checkpoint"
                )
            return
        with self._connect() as con:
            con.execute(
                "INSERT INTO feature_generation_checkpoints VALUES (?, ?, ?, ?)",
                (
                    logical_task_id,
                    artifact_digest,
                    prompt_hash,
                    datetime.now(UTC).isoformat(),
                ),
            )
