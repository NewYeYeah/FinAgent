from __future__ import annotations

import importlib
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .execution import (
    DEFAULT_DUCKDB_EXECUTION_POLICY,
    DuckDBExecutionPolicy,
    configure_duckdb_connection,
)
from .materialize import ExecutableQueryPlan

_TEMPORAL_DATETIME_COLUMNS = {
    "event_time",
    "available_at",
    "session_open",
    "session_close",
    "source_event_time",
    "source_available_at",
    "target_event_time",
    "target_available_at",
}
_TEMPORAL_DATE_COLUMNS = {"session_date"}


def _duckdb() -> Any:
    try:
        return importlib.import_module("duckdb")
    except ImportError as exc:  # pragma: no cover - optional dependency path
        raise RuntimeError(
            "minute-store streaming requires DuckDB; install the local-parquet extra "
            "or use the canonical development environment"
        ) from exc


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def iter_plan_rows(
    plan: ExecutableQueryPlan,
    *,
    batch_size: int = 4096,
    policy: DuckDBExecutionPolicy = DEFAULT_DUCKDB_EXECUTION_POLICY,
    temp_directory: str | Path | None = None,
) -> Iterator[dict[str, object]]:
    """Yield a bounded DuckDB plan without materializing the full result in Python.

    The query plan remains responsible for deterministic ordering. Temporal values are
    cast through ISO strings at the Python boundary for the same reason as
    ``fetch_plan_rows``: this avoids depending on DuckDB's optional timezone bridge.
    """

    if not 1 <= batch_size <= 100_000:
        raise ValueError("batch_size must be in 1..100000")

    projections: list[str] = []
    for column in plan.output_columns:
        identifier = _quoted_identifier(column)
        if column in _TEMPORAL_DATETIME_COLUMNS or column in _TEMPORAL_DATE_COLUMNS:
            projections.append(f"CAST({identifier} AS VARCHAR) AS {identifier}")
        else:
            projections.append(identifier)

    connection = _duckdb().connect(database=":memory:")
    try:
        configure_duckdb_connection(
            connection,
            policy,
            temp_directory=temp_directory,
        )
        cursor = connection.execute(
            "SELECT "
            + ", ".join(projections)
            + f" FROM ({plan.sql}) AS bounded_query"
        )
        columns = tuple(str(item[0]) for item in cursor.description)
        while True:
            raw_rows = cursor.fetchmany(batch_size)
            if not raw_rows:
                break
            for raw_row in raw_rows:
                row = dict(zip(columns, raw_row, strict=True))
                for column in _TEMPORAL_DATETIME_COLUMNS:
                    value = row.get(column)
                    if value is not None:
                        row[column] = datetime.fromisoformat(str(value))
                for column in _TEMPORAL_DATE_COLUMNS:
                    value = row.get(column)
                    if value is not None:
                        row[column] = date.fromisoformat(str(value))
                yield row
    finally:
        connection.close()
