from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .query import MinuteQueryPlan


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


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


@dataclass(frozen=True, slots=True)
class MinuteMaterialization:
    plan_id: str
    data_version: str
    row_count: int
    size_bytes: int
    output_filename: str
    schema_version: str = "finagent.minute-materialization.v1"

    @property
    def materialization_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "plan_id": self.plan_id,
                "data_version": self.data_version,
                "row_count": self.row_count,
                "size_bytes": self.size_bytes,
                "output_filename": self.output_filename,
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
            "output_filename": self.output_filename,
        }


def count_plan_rows(plan: MinuteQueryPlan) -> int:
    connection = _duckdb().connect(database=":memory:")
    try:
        row = connection.execute(f"SELECT COUNT(*) FROM ({plan.sql}) AS bounded_query").fetchone()
        if row is None:
            raise RuntimeError("DuckDB count query returned no result")
        return int(row[0])
    finally:
        connection.close()


def fetch_plan_rows(
    plan: MinuteQueryPlan,
    *,
    limit: int = 1000,
) -> tuple[dict[str, object], ...]:
    if not 1 <= limit <= 100_000:
        raise ValueError("fetch limit must be in 1..100000")
    connection = _duckdb().connect(database=":memory:")
    try:
        cursor = connection.execute(f"SELECT * FROM ({plan.sql}) AS bounded_query LIMIT {limit}")
        columns = tuple(str(item[0]) for item in cursor.description)
        return tuple(dict(zip(columns, row, strict=True)) for row in cursor.fetchall())
    finally:
        connection.close()


def copy_plan_to_parquet(
    plan: MinuteQueryPlan,
    output: str | Path,
    *,
    overwrite: bool = False,
) -> MinuteMaterialization:
    output_path = Path(output).expanduser().resolve()
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"minute materialization already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    connection = _duckdb().connect(database=":memory:")
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
        output_filename=output_path.name,
    )
