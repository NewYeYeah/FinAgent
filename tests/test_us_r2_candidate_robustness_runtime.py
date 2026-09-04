from __future__ import annotations

import gc
import weakref
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import duckdb
import numpy as np

import finagent.research.us_r2_candidate_robustness as robustness
from finagent.data.minute_store.execution import DuckDBExecutionPolicy
from finagent.domain.market_bars import BarInterval
from finagent.research.us_r2_candidate_robustness import (
    FROZEN_CANDIDATE_COUNT,
    USR2RobustnessBaseRow,
    evaluate_us_r2_annual_candidate_robustness_streaming,
)
from finagent.research.us_r2_frozen_protocol import FROZEN_ASSETS
from finagent.research.us_r2_primary_statistics import METRIC_AVAILABLE
from finagent.research.us_r2_robustness_base import (
    ROBUSTNESS_BASE_FILENAME,
    canonical_us_r2_robustness_slices,
)
from scripts.evaluate_us_r2_candidate_robustness import _iter_annual_robustness_slices


def _row(slice_id: str, *, offset: int = 0) -> USR2RobustnessBaseRow:
    event_time = datetime(2006, 1, 3, 14, 30, tzinfo=UTC) + timedelta(minutes=offset)
    return USR2RobustnessBaseRow(
        slice_id=slice_id,
        research_asset_id=FROZEN_ASSETS[0],
        session_date=date(2006, 1, 3),
        session_id="2006-01-03",
        event_time=event_time,
        available_at=event_time + timedelta(minutes=5),
        bar_index=offset,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1_000.0,
        is_complete=True,
        label_value=0.01,
        label_available=True,
        unavailable_reason=None,
        label_row_present=True,
    )


def test_duckdb_runtime_reads_bounded_batches_in_canonical_slice_order(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    parquet_path = tmp_path / ROBUSTNESS_BASE_FILENAME
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE robustness_rows (
                slice_id VARCHAR,
                research_asset_id VARCHAR,
                session_date DATE,
                session_id VARCHAR,
                event_time TIMESTAMPTZ,
                available_at TIMESTAMPTZ,
                bar_index BIGINT,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                is_complete BOOLEAN,
                label_value DOUBLE,
                label_available BOOLEAN,
                unavailable_reason VARCHAR,
                label_row_present BOOLEAN
            )
            """
        )
        rows = []
        for spec in reversed(canonical_us_r2_robustness_slices()):
            for offset in (5, 0):
                row = _row(spec.slice_id, offset=offset)
                rows.append(
                    (
                        row.slice_id,
                        row.research_asset_id,
                        row.session_date,
                        row.session_id,
                        row.event_time,
                        row.available_at,
                        row.bar_index,
                        row.open,
                        row.high,
                        row.low,
                        row.close,
                        row.volume,
                        row.is_complete,
                        row.label_value,
                        row.label_available,
                        row.unavailable_reason,
                        row.label_row_present,
                    )
                )
        connection.executemany(
            "INSERT INTO robustness_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute(
            f"COPY robustness_rows TO '{parquet_path.as_posix()}' (FORMAT PARQUET)"
        )
    finally:
        connection.close()

    real_connect = duckdb.connect
    fetchmany_sizes: list[int] = []

    class CursorProxy:
        def __init__(self, cursor: Any) -> None:
            self._cursor = cursor

        def __getattr__(self, name: str) -> Any:
            return getattr(self._cursor, name)

        def fetchmany(self, size: int) -> Any:
            fetchmany_sizes.append(size)
            return self._cursor.fetchmany(size)

        def fetchall(self) -> Any:
            raise AssertionError("annual robustness rows must not use fetchall")

    class ConnectionProxy:
        def __init__(self) -> None:
            self._connection = real_connect(database=":memory:")

        def execute(self, *args: Any, **kwargs: Any) -> CursorProxy:
            return CursorProxy(self._connection.execute(*args, **kwargs))

        def close(self) -> None:
            self._connection.close()

    monkeypatch.setattr(duckdb, "connect", lambda **_kwargs: ConnectionProxy())
    slices = tuple(
        _iter_annual_robustness_slices(
            parquet_path,
            batch_size=2,
            execution_policy=DuckDBExecutionPolicy(memory_limit="64MB"),
            temp_directory=tmp_path / "duckdb-temp",
        )
    )
    assert tuple(slice_id for slice_id, _rows in slices) == tuple(
        spec.slice_id for spec in canonical_us_r2_robustness_slices()
    )
    assert all(len(rows) == 2 for _slice_id, rows in slices)
    assert all(rows[0].available_at < rows[1].available_at for _slice_id, rows in slices)
    assert fetchmany_sizes
    assert set(fetchmany_sizes) == {2}


def test_streaming_evaluator_never_retains_5m_and_30m_matrices_together(
    monkeypatch: Any,
) -> None:
    matrix_refs: list[weakref.ReferenceType[np.ndarray]] = []
    live_before_materialize: list[int] = []
    materialized_intervals: list[BarInterval] = []

    def fake_materialize(
        rows: tuple[USR2RobustnessBaseRow, ...],
        execution: Any,
        **_kwargs: Any,
    ) -> tuple[np.ndarray, int]:
        gc.collect()
        live_before_materialize.append(sum(item() is not None for item in matrix_refs))
        materialized_intervals.append(cast(BarInterval, execution.signal_interval))
        matrix = np.zeros((len(rows), FROZEN_CANDIDATE_COUNT), dtype=np.float64)
        matrix_refs.append(weakref.ref(matrix))
        return matrix, 1

    def fake_evaluate(*_args: Any, **_kwargs: Any) -> tuple[Any, ...]:
        return (
            [1],
            [2],
            [0],
            [[0.01] * FROZEN_CANDIDATE_COUNT],
            [[METRIC_AVAILABLE] * FROZEN_CANDIDATE_COUNT],
        )

    monkeypatch.setattr(robustness, "_materialize_candidate_matrix", fake_materialize)
    monkeypatch.setattr(robustness, "_evaluate_slice_metrics", fake_evaluate)
    executions = tuple(
        SimpleNamespace(signal_interval=interval)
        for interval in (BarInterval.MINUTE_5, BarInterval.MINUTE_15, BarInterval.MINUTE_30)
    )
    plan = cast(Any, SimpleNamespace(interval_executions=executions))
    slices = tuple(
        (spec.slice_id, (_row(spec.slice_id),))
        for spec in canonical_us_r2_robustness_slices()
    )

    arrays, stats = evaluate_us_r2_annual_candidate_robustness_streaming(
        iter(slices),
        year=2006,
        plan=plan,
        regime_sessions=cast(Any, object()),
    )

    assert arrays.row_count == 4
    assert stats.feature_interval_evaluation_count == 3
    assert materialized_intervals == [
        BarInterval.MINUTE_5,
        BarInterval.MINUTE_30,
        BarInterval.MINUTE_15,
    ]
    assert live_before_materialize == [0, 0, 0]
    gc.collect()
    assert all(item() is None for item in matrix_refs)
