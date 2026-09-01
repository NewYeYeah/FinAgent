from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .local_snapshot import (
    HuggingFaceSnapshotLayout,
    LocalMinuteInventory,
    inventory_monthly_parquet,
)


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
        import duckdb
    except ImportError as exc:  # pragma: no cover - optional dependency boundary
        raise RuntimeError(
            "local U.S. minute conflict diagnostics require duckdb in the active Conda environment"
        ) from exc
    return duckdb


def _quote_path(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


def _month_file(inventory: LocalMinuteInventory, month: str) -> Path:
    for item in inventory.files:
        if item.month == month:
            return item.path
    raise ValueError(f"month {month!r} is not present in the local minute inventory")


def _group_cte(path_literal: str) -> str:
    return f"""
        WITH base AS (
            SELECT timestamp, open, high, low, close, volume, ticker
            FROM read_parquet({path_literal})
        ),
        duplicate_groups AS (
            SELECT
                ticker,
                timestamp,
                COUNT(*) AS group_rows,
                COUNT(DISTINCT struct_pack(
                    open := open,
                    high := high,
                    low := low,
                    close := close,
                    volume := volume
                )) AS distinct_variant_count,
                COUNT(DISTINCT open) + CASE WHEN COUNT(open) < COUNT(*) THEN 1 ELSE 0 END
                    AS open_variant_count,
                COUNT(DISTINCT high) + CASE WHEN COUNT(high) < COUNT(*) THEN 1 ELSE 0 END
                    AS high_variant_count,
                COUNT(DISTINCT low) + CASE WHEN COUNT(low) < COUNT(*) THEN 1 ELSE 0 END
                    AS low_variant_count,
                COUNT(DISTINCT close) + CASE WHEN COUNT(close) < COUNT(*) THEN 1 ELSE 0 END
                    AS close_variant_count,
                COUNT(DISTINCT volume) + CASE WHEN COUNT(volume) < COUNT(*) THEN 1 ELSE 0 END
                    AS volume_variant_count,
                MIN(open) AS min_open,
                MAX(open) AS max_open,
                MIN(high) AS min_high,
                MAX(high) AS max_high,
                MIN(low) AS min_low,
                MAX(low) AS max_low,
                MIN(close) AS min_close,
                MAX(close) AS max_close,
                MIN(volume) AS min_volume,
                MAX(volume) AS max_volume
            FROM base
            GROUP BY ticker, timestamp
            HAVING COUNT(*) > 1
        ),
        classified AS (
            SELECT
                *,
                open_variant_count > 1 AS open_conflict,
                high_variant_count > 1 AS high_conflict,
                low_variant_count > 1 AS low_conflict,
                close_variant_count > 1 AS close_conflict,
                volume_variant_count > 1 AS volume_conflict,
                (
                    open_variant_count > 1
                    OR high_variant_count > 1
                    OR low_variant_count > 1
                    OR close_variant_count > 1
                    OR volume_variant_count > 1
                ) AS conflicting
            FROM duplicate_groups
        )
    """


@dataclass(frozen=True, slots=True)
class DuplicateConflictExample:
    ticker: str
    timestamp: str
    group_rows: int
    distinct_variant_count: int
    differing_fields: tuple[str, ...]
    open_range: tuple[float | None, float | None]
    high_range: tuple[float | None, float | None]
    low_range: tuple[float | None, float | None]
    close_range: tuple[float | None, float | None]
    volume_range: tuple[float | None, float | None]

    def to_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "timestamp": self.timestamp,
            "group_rows": self.group_rows,
            "distinct_variant_count": self.distinct_variant_count,
            "differing_fields": list(self.differing_fields),
            "open_range": list(self.open_range),
            "high_range": list(self.high_range),
            "low_range": list(self.low_range),
            "close_range": list(self.close_range),
            "volume_range": list(self.volume_range),
        }


@dataclass(frozen=True, slots=True)
class LocalMinuteConflictDiagnostic:
    revision: str
    inventory_id: str
    month: str
    duplicate_key_count: int
    exact_duplicate_key_count: int
    exact_duplicate_extra_row_count: int
    conflicting_duplicate_key_count: int
    conflicting_duplicate_extra_row_count: int
    conflicting_raw_row_count: int
    conflicting_ticker_count: int
    min_conflict_timestamp: str
    max_conflict_timestamp: str
    max_rows_per_conflicting_key: int
    conflicting_keys_over_two_rows: int
    field_conflict_counts: tuple[tuple[str, int], ...]
    pattern_counts: tuple[tuple[str, int], ...]
    examples: tuple[DuplicateConflictExample, ...]
    diagnosed_at: datetime
    rows_output: str | None = None
    schema_version: str = "finagent.us-minute-conflict-diagnostic.v1"

    @property
    def unresolved(self) -> bool:
        return self.conflicting_duplicate_key_count > 0

    @property
    def diagnostic_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "inventory_id": self.inventory_id,
            "month": self.month,
            "duplicate_key_count": self.duplicate_key_count,
            "exact_duplicate_key_count": self.exact_duplicate_key_count,
            "exact_duplicate_extra_row_count": self.exact_duplicate_extra_row_count,
            "conflicting_duplicate_key_count": self.conflicting_duplicate_key_count,
            "conflicting_duplicate_extra_row_count": self.conflicting_duplicate_extra_row_count,
            "conflicting_raw_row_count": self.conflicting_raw_row_count,
            "conflicting_ticker_count": self.conflicting_ticker_count,
            "min_conflict_timestamp": self.min_conflict_timestamp,
            "max_conflict_timestamp": self.max_conflict_timestamp,
            "max_rows_per_conflicting_key": self.max_rows_per_conflicting_key,
            "conflicting_keys_over_two_rows": self.conflicting_keys_over_two_rows,
            "field_conflict_counts": dict(self.field_conflict_counts),
            "pattern_counts": dict(self.pattern_counts),
            "examples": [item.to_dict() for item in self.examples],
        }
        return _canonical_hash(payload, prefix="us-minute-conflict-diagnostic")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "diagnostic_id": self.diagnostic_id,
            "revision": self.revision,
            "inventory_id": self.inventory_id,
            "month": self.month,
            "unresolved": self.unresolved,
            "duplicate_key_count": self.duplicate_key_count,
            "exact_duplicate_key_count": self.exact_duplicate_key_count,
            "exact_duplicate_extra_row_count": self.exact_duplicate_extra_row_count,
            "conflicting_duplicate_key_count": self.conflicting_duplicate_key_count,
            "conflicting_duplicate_extra_row_count": self.conflicting_duplicate_extra_row_count,
            "conflicting_raw_row_count": self.conflicting_raw_row_count,
            "conflicting_ticker_count": self.conflicting_ticker_count,
            "min_conflict_timestamp": self.min_conflict_timestamp,
            "max_conflict_timestamp": self.max_conflict_timestamp,
            "max_rows_per_conflicting_key": self.max_rows_per_conflicting_key,
            "conflicting_keys_over_two_rows": self.conflicting_keys_over_two_rows,
            "field_conflict_counts": dict(self.field_conflict_counts),
            "pattern_counts": dict(self.pattern_counts),
            "examples": [item.to_dict() for item in self.examples],
            "rows_output": self.rows_output,
            "diagnosed_at": self.diagnosed_at.astimezone(UTC).isoformat(),
        }


def _summary_row(connection: Any, path_literal: str) -> tuple[Any, ...]:
    query = (
        _group_cte(path_literal)
        + """
        SELECT
            COUNT(*) AS duplicate_key_count,
            COALESCE(SUM(CASE WHEN NOT conflicting THEN 1 ELSE 0 END), 0)
                AS exact_duplicate_key_count,
            COALESCE(SUM(CASE WHEN NOT conflicting THEN group_rows - 1 ELSE 0 END), 0)
                AS exact_duplicate_extra_row_count,
            COALESCE(SUM(CASE WHEN conflicting THEN 1 ELSE 0 END), 0)
                AS conflicting_duplicate_key_count,
            COALESCE(SUM(CASE WHEN conflicting THEN group_rows - 1 ELSE 0 END), 0)
                AS conflicting_duplicate_extra_row_count,
            COALESCE(SUM(CASE WHEN conflicting THEN group_rows ELSE 0 END), 0)
                AS conflicting_raw_row_count,
            COUNT(DISTINCT CASE WHEN conflicting THEN ticker END) AS conflicting_ticker_count,
            MIN(CASE WHEN conflicting THEN epoch(timestamp) END) AS min_conflict_epoch,
            MAX(CASE WHEN conflicting THEN epoch(timestamp) END) AS max_conflict_epoch,
            COALESCE(MAX(CASE WHEN conflicting THEN group_rows END), 0)
                AS max_rows_per_conflicting_key,
            COALESCE(SUM(CASE WHEN conflicting AND group_rows > 2 THEN 1 ELSE 0 END), 0)
                AS conflicting_keys_over_two_rows,
            COALESCE(SUM(CASE WHEN conflicting AND open_conflict THEN 1 ELSE 0 END), 0)
                AS open_conflict_count,
            COALESCE(SUM(CASE WHEN conflicting AND high_conflict THEN 1 ELSE 0 END), 0)
                AS high_conflict_count,
            COALESCE(SUM(CASE WHEN conflicting AND low_conflict THEN 1 ELSE 0 END), 0)
                AS low_conflict_count,
            COALESCE(SUM(CASE WHEN conflicting AND close_conflict THEN 1 ELSE 0 END), 0)
                AS close_conflict_count,
            COALESCE(SUM(CASE WHEN conflicting AND volume_conflict THEN 1 ELSE 0 END), 0)
                AS volume_conflict_count,
            COALESCE(SUM(CASE
                WHEN conflicting
                  AND NOT (open_conflict OR high_conflict OR low_conflict OR close_conflict)
                  AND volume_conflict
                THEN 1 ELSE 0 END), 0) AS volume_only_count,
            COALESCE(SUM(CASE
                WHEN conflicting
                  AND (open_conflict OR high_conflict OR low_conflict OR close_conflict)
                  AND NOT volume_conflict
                THEN 1 ELSE 0 END), 0) AS price_only_count,
            COALESCE(SUM(CASE
                WHEN conflicting
                  AND (open_conflict OR high_conflict OR low_conflict OR close_conflict)
                  AND volume_conflict
                THEN 1 ELSE 0 END), 0) AS price_and_volume_count
        FROM classified
        """
    )
    row = connection.execute(query).fetchone()
    assert row is not None
    return tuple(row)


def _examples(connection: Any, path_literal: str, *, limit: int) -> tuple[DuplicateConflictExample, ...]:
    if limit < 0:
        raise ValueError("example limit must be non-negative")
    if limit == 0:
        return ()
    query = (
        _group_cte(path_literal)
        + f"""
        SELECT
            ticker,
            CAST(timestamp AS VARCHAR) AS timestamp_text,
            group_rows,
            distinct_variant_count,
            open_conflict,
            high_conflict,
            low_conflict,
            close_conflict,
            volume_conflict,
            min_open,
            max_open,
            min_high,
            max_high,
            min_low,
            max_low,
            min_close,
            max_close,
            min_volume,
            max_volume
        FROM classified
        WHERE conflicting
        ORDER BY group_rows DESC, ticker, timestamp
        LIMIT {int(limit)}
        """
    )
    values: list[DuplicateConflictExample] = []
    for row in connection.execute(query).fetchall():
        flags = (
            ("open", bool(row[4])),
            ("high", bool(row[5])),
            ("low", bool(row[6])),
            ("close", bool(row[7])),
            ("volume", bool(row[8])),
        )
        values.append(
            DuplicateConflictExample(
                ticker=str(row[0]),
                timestamp=str(row[1]),
                group_rows=int(row[2]),
                distinct_variant_count=int(row[3]),
                differing_fields=tuple(name for name, active in flags if active),
                open_range=(row[9], row[10]),
                high_range=(row[11], row[12]),
                low_range=(row[13], row[14]),
                close_range=(row[15], row[16]),
                volume_range=(row[17], row[18]),
            )
        )
    return tuple(values)


def _write_conflicting_rows_csv(connection: Any, path_literal: str, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output_literal = _quote_path(output.resolve())
    query = (
        _group_cte(path_literal)
        + """
        SELECT
            b.ticker,
            b.timestamp,
            b.open,
            b.high,
            b.low,
            b.close,
            b.volume,
            c.group_rows AS duplicate_group_rows,
            c.distinct_variant_count,
            c.open_conflict,
            c.high_conflict,
            c.low_conflict,
            c.close_conflict,
            c.volume_conflict,
            ROW_NUMBER() OVER (
                PARTITION BY b.ticker, b.timestamp
                ORDER BY b.open NULLS FIRST,
                         b.high NULLS FIRST,
                         b.low NULLS FIRST,
                         b.close NULLS FIRST,
                         b.volume NULLS FIRST
            ) AS diagnostic_variant_rank
        FROM base AS b
        INNER JOIN classified AS c
            ON b.ticker IS NOT DISTINCT FROM c.ticker
           AND b.timestamp IS NOT DISTINCT FROM c.timestamp
        WHERE c.conflicting
        ORDER BY b.ticker, b.timestamp, diagnostic_variant_rank
        """
    )
    connection.execute(
        f"COPY ({query}) TO {output_literal} (FORMAT CSV, HEADER TRUE)"
    )
    return output


def diagnose_local_minute_conflicts(
    root: str | Path,
    *,
    expected_revision: str,
    month: str,
    examples: int = 20,
    rows_output: str | Path | None = None,
    diagnosed_at: datetime | None = None,
) -> LocalMinuteConflictDiagnostic:
    layout = HuggingFaceSnapshotLayout.resolve(root, expected_revision=expected_revision)
    inventory = inventory_monthly_parquet(layout)
    path = _month_file(inventory, month)
    path_literal = _quote_path(path)
    duckdb = _duckdb()
    connection = duckdb.connect(database=":memory:")

    try:
        row = _summary_row(connection, path_literal)
        sample = _examples(connection, path_literal, limit=examples)
        rendered_rows_output: str | None = None
        if rows_output is not None:
            rendered = _write_conflicting_rows_csv(connection, path_literal, Path(rows_output))
            rendered_rows_output = str(rendered)
    finally:
        connection.close()

    min_timestamp = (
        datetime.fromtimestamp(float(row[7]), tz=UTC).isoformat()
        if row[7] is not None
        else ""
    )
    max_timestamp = (
        datetime.fromtimestamp(float(row[8]), tz=UTC).isoformat()
        if row[8] is not None
        else ""
    )
    field_counts = (
        ("open", int(row[11] or 0)),
        ("high", int(row[12] or 0)),
        ("low", int(row[13] or 0)),
        ("close", int(row[14] or 0)),
        ("volume", int(row[15] or 0)),
    )
    pattern_counts = (
        ("volume_only", int(row[16] or 0)),
        ("price_only", int(row[17] or 0)),
        ("price_and_volume", int(row[18] or 0)),
    )
    return LocalMinuteConflictDiagnostic(
        revision=layout.revision,
        inventory_id=inventory.inventory_id,
        month=month,
        duplicate_key_count=int(row[0] or 0),
        exact_duplicate_key_count=int(row[1] or 0),
        exact_duplicate_extra_row_count=int(row[2] or 0),
        conflicting_duplicate_key_count=int(row[3] or 0),
        conflicting_duplicate_extra_row_count=int(row[4] or 0),
        conflicting_raw_row_count=int(row[5] or 0),
        conflicting_ticker_count=int(row[6] or 0),
        min_conflict_timestamp=min_timestamp,
        max_conflict_timestamp=max_timestamp,
        max_rows_per_conflicting_key=int(row[9] or 0),
        conflicting_keys_over_two_rows=int(row[10] or 0),
        field_conflict_counts=field_counts,
        pattern_counts=pattern_counts,
        examples=sample,
        rows_output=rendered_rows_output,
        diagnosed_at=diagnosed_at or datetime.now(UTC),
    )
