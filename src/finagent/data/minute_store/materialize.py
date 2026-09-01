from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from .execution import (
    DEFAULT_DUCKDB_EXECUTION_POLICY,
    DuckDBExecutionPolicy,
    DuckDBExecutionSettings,
    configure_duckdb_connection,
)


class ExecutableQueryPlan(Protocol):
    """Minimal read-only SQL plan surface accepted by Data Plane executors."""

    @property
    def plan_id(self) -> str: ...

    @property
    def data_version(self) -> str: ...

    @property
    def sql(self) -> str: ...

    @property
    def output_columns(self) -> tuple[str, ...]: ...


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duckdb() -> Any:
    try:
        return importlib.import_module("duckdb")
    except ImportError as exc:  # pragma: no cover - exercised without local-parquet extra
        raise RuntimeError(
            "minute-store execution requires DuckDB; install the local-parquet extra "
            "or use the canonical development environment"
        ) from exc


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _connect(
    policy: DuckDBExecutionPolicy,
    *,
    temp_directory: str | Path | None,
) -> tuple[Any, DuckDBExecutionSettings]:
    connection = _duckdb().connect(database=":memory:")
    try:
        settings = configure_duckdb_connection(
            connection,
            policy,
            temp_directory=temp_directory,
        )
    except Exception:
        connection.close()
        raise
    return connection, settings


@dataclass(frozen=True, slots=True)
class MinuteMaterialization:
    plan_id: str
    data_version: str
    row_count: int
    size_bytes: int
    content_sha256: str
    output_filename: str
    schema_version: str = "finagent.minute-materialization.v2"

    def __post_init__(self) -> None:
        if self.row_count < 0 or self.size_bytes < 0:
            raise ValueError("minute materialization counts/sizes must be >= 0")
        digest = self.content_sha256.strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("content_sha256 must be a 64-character hexadecimal SHA-256")
        object.__setattr__(self, "content_sha256", digest)

    @property
    def materialization_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "plan_id": self.plan_id,
                "data_version": self.data_version,
                "row_count": self.row_count,
                "content_sha256": self.content_sha256,
            },
            prefix="minute-materialization",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "materialization_id": self.materialization_id,
            "plan_id": self.plan_id,
            "data_version": self.data_version,
            "row_count": self.row_count,
            "size_bytes": self.size_bytes,
            "content_sha256": self.content_sha256,
            "output_filename": self.output_filename,
        }


def inspect_execution_settings(
    *,
    policy: DuckDBExecutionPolicy = DEFAULT_DUCKDB_EXECUTION_POLICY,
    temp_directory: str | Path | None = None,
) -> DuckDBExecutionSettings:
    connection, settings = _connect(policy, temp_directory=temp_directory)
    connection.close()
    return settings


def count_plan_rows(
    plan: ExecutableQueryPlan,
    *,
    policy: DuckDBExecutionPolicy = DEFAULT_DUCKDB_EXECUTION_POLICY,
    temp_directory: str | Path | None = None,
) -> int:
    connection, _settings = _connect(policy, temp_directory=temp_directory)
    try:
        row = connection.execute(f"SELECT COUNT(*) FROM ({plan.sql}) AS bounded_query").fetchone()
        if row is None:
            raise RuntimeError("DuckDB count query returned no result")
        return int(row[0])
    finally:
        connection.close()


def fetch_plan_rows(
    plan: ExecutableQueryPlan,
    *,
    limit: int = 1000,
    policy: DuckDBExecutionPolicy = DEFAULT_DUCKDB_EXECUTION_POLICY,
    temp_directory: str | Path | None = None,
) -> tuple[dict[str, object], ...]:
    """Fetch a bounded Python preview without requiring DuckDB's optional pytz bridge.

    DuckDB keeps TIMESTAMPTZ/DATE authoritative inside SQL and Parquet. Only this
    interactive Python boundary casts temporal columns to ISO text before `fetchall`,
    then reconstructs standard-library datetime/date objects. Transform-specific
    source/target/session clocks use the same boundary.
    """

    if not 1 <= limit <= 100_000:
        raise ValueError("fetch limit must be in 1..100000")
    temporal_datetime = {
        "event_time",
        "available_at",
        "session_open",
        "session_close",
        "source_event_time",
        "source_available_at",
        "target_event_time",
        "target_available_at",
    }
    temporal_date = {"session_date"}
    projections: list[str] = []
    for column in plan.output_columns:
        identifier = _quoted_identifier(column)
        if column in temporal_datetime or column in temporal_date:
            projections.append(f"CAST({identifier} AS VARCHAR) AS {identifier}")
        else:
            projections.append(identifier)

    connection, _settings = _connect(policy, temp_directory=temp_directory)
    try:
        cursor = connection.execute(
            "SELECT "
            + ", ".join(projections)
            + f" FROM ({plan.sql}) AS bounded_query LIMIT {limit}"
        )
        columns = tuple(str(item[0]) for item in cursor.description)
        converted: list[dict[str, object]] = []
        for raw_row in cursor.fetchall():
            row = dict(zip(columns, raw_row, strict=True))
            for column in temporal_datetime:
                value = row.get(column)
                if value is not None:
                    row[column] = datetime.fromisoformat(str(value))
            for column in temporal_date:
                value = row.get(column)
                if value is not None:
                    row[column] = date.fromisoformat(str(value))
            converted.append(row)
        return tuple(converted)
    finally:
        connection.close()


def copy_plan_to_parquet(
    plan: ExecutableQueryPlan,
    output: str | Path,
    *,
    overwrite: bool = False,
    policy: DuckDBExecutionPolicy = DEFAULT_DUCKDB_EXECUTION_POLICY,
    temp_directory: str | Path | None = None,
) -> MinuteMaterialization:
    output_path = Path(output).expanduser().resolve()
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"minute materialization already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    connection, _settings = _connect(policy, temp_directory=temp_directory)
    try:
        connection.execute(
            f"COPY ({plan.sql}) TO {_sql_string(output_path.as_posix())} "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        row = connection.execute(
            f"SELECT COUNT(*) FROM read_parquet({_sql_string(output_path.as_posix())})"
        ).fetchone()
        if row is None:
            raise RuntimeError("DuckDB materialized row count returned no result")
        row_count = int(row[0])
    finally:
        connection.close()

    return MinuteMaterialization(
        plan_id=plan.plan_id,
        data_version=plan.data_version,
        row_count=row_count,
        size_bytes=output_path.stat().st_size,
        content_sha256=_file_sha256(output_path),
        output_filename=output_path.name,
    )
