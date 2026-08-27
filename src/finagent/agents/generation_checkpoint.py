from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FeatureGenerationCheckpoint:
    logical_task_id: str
    scope_hash: str
    artifact_digest: str
    prompt_hash: str
    recorded_at: str


class SQLiteFeatureGenerationCheckpointStore:
    """Resume accepted logical Agent candidates without another LLM call.

    A stable logical task id is not sufficient on its own because a user may reuse it
    after changing the research question, approved fields or model policy. ``scope_hash``
    binds the checkpoint to those non-market generation inputs and prevents stale reuse.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS feature_generation_checkpoints (
                    logical_task_id TEXT PRIMARY KEY,
                    scope_hash TEXT NOT NULL,
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
                "SELECT logical_task_id, scope_hash, artifact_digest, prompt_hash, recorded_at "
                "FROM feature_generation_checkpoints WHERE logical_task_id=?",
                (logical_task_id,),
            ).fetchone()
        if row is None:
            return None
        return FeatureGenerationCheckpoint(
            logical_task_id=str(row[0]),
            scope_hash=str(row[1]),
            artifact_digest=str(row[2]),
            prompt_hash=str(row[3]),
            recorded_at=str(row[4]),
        )

    def register(
        self,
        logical_task_id: str,
        scope_hash: str,
        artifact_digest: str,
        prompt_hash: str,
    ) -> None:
        values = tuple(value.strip() for value in (logical_task_id, scope_hash, artifact_digest, prompt_hash))
        if any(not value for value in values):
            raise ValueError("checkpoint identity fields cannot be empty")
        logical_task_id, scope_hash, artifact_digest, prompt_hash = values
        existing = self.get(logical_task_id)
        if existing is not None:
            if (
                existing.scope_hash != scope_hash
                or existing.artifact_digest != artifact_digest
                or existing.prompt_hash != prompt_hash
            ):
                raise ValueError(
                    f"logical candidate {logical_task_id!r} already has a different checkpoint"
                )
            return
        with self._connect() as con:
            con.execute(
                "INSERT INTO feature_generation_checkpoints VALUES (?, ?, ?, ?, ?)",
                (
                    logical_task_id,
                    scope_hash,
                    artifact_digest,
                    prompt_hash,
                    datetime.now(UTC).isoformat(),
                ),
            )
