from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .base import LLMRequest, LLMResponse


@dataclass(frozen=True, slots=True)
class LLMCallRecord:
    request_id: str
    task_id: str
    provider: str
    model: str
    prompt_hash: str
    status: str
    response_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int
    latency_ms: float
    planning_valid: bool | None
    validation_error: str


class LLMCallStore:
    def record_response(
        self,
        task_id: str,
        request: LLMRequest,
        response: LLMResponse,
        *,
        planning_valid: bool,
        validation_error: str = "",
    ) -> None:
        raise NotImplementedError

    def record_failure(self, task_id: str, request: LLMRequest, provider: str, error: Exception) -> None:
        raise NotImplementedError


class SQLiteLLMCallStore(LLMCallStore):
    """Durable provider telemetry; no API keys or raw hidden reasoning are stored."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS llm_calls (
                    request_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    response_id TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    cached_input_tokens INTEGER NOT NULL,
                    latency_ms REAL NOT NULL,
                    planning_valid INTEGER,
                    validation_error TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def record_response(self, task_id, request, response, *, planning_valid, validation_error="") -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO llm_calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request.request_id, task_id, response.provider, response.model, request.prompt_hash,
                    response.status, response.response_id, response.usage.input_tokens,
                    response.usage.output_tokens, response.usage.total_tokens,
                    response.usage.cached_input_tokens, response.latency_ms, int(planning_valid),
                    str(validation_error), datetime.now(timezone.utc).isoformat(),
                ),
            )

    def record_failure(self, task_id, request, provider, error) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO llm_calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request.request_id, task_id, str(provider), request.model, request.prompt_hash,
                    "failed", "", 0, 0, 0, 0, 0.0, None,
                    f"{type(error).__name__}: {error}", datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get(self, request_id: str) -> LLMCallRecord:
        with self._connect() as con:
            row = con.execute(
                """SELECT request_id, task_id, provider, model, prompt_hash, status, response_id,
                          input_tokens, output_tokens, total_tokens, cached_input_tokens, latency_ms,
                          planning_valid, validation_error
                   FROM llm_calls WHERE request_id=?""",
                (request_id,),
            ).fetchone()
        if row is None:
            raise KeyError(request_id)
        return LLMCallRecord(
            request_id=row[0], task_id=row[1], provider=row[2], model=row[3],
            prompt_hash=row[4], status=row[5], response_id=row[6], input_tokens=row[7],
            output_tokens=row[8], total_tokens=row[9], cached_input_tokens=row[10],
            latency_ms=row[11], planning_valid=(None if row[12] is None else bool(row[12])),
            validation_error=row[13],
        )
