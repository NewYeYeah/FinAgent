from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np

from finagent.domain.market_bars import BarInterval
from finagent.research.us_a1_factor_materialization import compile_factor_graph_batch
from finagent.research.us_a1_factor_validation import validate_factor_graph
from finagent.research.us_a1_legacy_graphs import legacy_a0_factor_graph_with_window
from finagent.research.us_agent_value_protocol import canonical_us_a0_primitive_vocabulary
from finagent.research.us_baselines import USBaselineFeatureKind
from finagent.research.us_r1_materialization import effective_us_r1_window_bars
from finagent.research.us_r2_candidate_robustness import (
    USR2RobustnessBaseRow,
    USR2RobustnessCandidateBinding,
    USR2RobustnessCandidateExecution,
    _materialize_candidate_matrix,
)


def _candidate(kind: USBaselineFeatureKind, window: int):
    return canonical_us_a0_primitive_vocabulary().candidate(kind, window)


def _rows() -> tuple[USR2RobustnessBaseRow, ...]:
    start = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    result: list[USR2RobustnessBaseRow] = []
    for index in range(8):
        event_time = start + timedelta(minutes=30 * index)
        base = 100.0 + index * 0.3
        result.append(
            USR2RobustnessBaseRow(
                slice_id="frequency_30m_60m",
                research_asset_id="AAPL",
                session_date=date(2025, 1, 2),
                session_id="2025-01-02",
                event_time=event_time,
                available_at=event_time + timedelta(minutes=30),
                bar_index=index,
                open=base,
                high=base + 0.5,
                low=base - 0.4,
                close=base + 0.2,
                volume=1_000.0 + index,
                is_complete=True,
                label_value=0.01,
                label_available=True,
                unavailable_reason=None,
                label_row_present=True,
            )
        )
    return tuple(result)


def test_30m_elapsed_window_collision_shares_numeric_root_without_losing_r1_slots() -> None:
    momentum_2 = _candidate(USBaselineFeatureKind.MOMENTUM, 2)
    momentum_3 = _candidate(USBaselineFeatureKind.MOMENTUM, 3)
    window_2 = effective_us_r1_window_bars(momentum_2, BarInterval.MINUTE_30)
    window_3 = effective_us_r1_window_bars(momentum_3, BarInterval.MINUTE_30)
    assert window_2 == window_3 == 2

    graph_2 = legacy_a0_factor_graph_with_window(momentum_2, window_bars=window_2)
    graph_3 = legacy_a0_factor_graph_with_window(momentum_3, window_bars=window_3)
    evidence_2 = validate_factor_graph(graph_2)
    evidence_3 = validate_factor_graph(graph_3)
    assert evidence_2.valid and evidence_2.canonicalization is not None
    assert evidence_3.valid and evidence_3.canonicalization is not None
    assert evidence_2.canonicalization.candidate_id == evidence_3.canonicalization.candidate_id

    compiled = compile_factor_graph_batch((graph_2,))
    root = compiled.roots[0]
    bindings = tuple(
        USR2RobustnessCandidateBinding(
            slot=slot,
            r1_candidate_id=f"r1-slot-{slot:02d}",
            structural_key=f"synthetic:{slot:02d}",
            signal_interval=BarInterval.MINUTE_30,
            effective_window_bars=2,
            feature_spec_id=f"feature-{slot:02d}",
            a1_candidate_id=root.candidate_id,
            root_execution_id=root.root_execution_id,
        )
        for slot in range(37)
    )
    execution = USR2RobustnessCandidateExecution(
        signal_interval=BarInterval.MINUTE_30,
        compiled=compiled,
        bindings=bindings,
    )

    assert execution.numeric_graph_count == 1
    assert execution.collapsed_numeric_graph_count == 36
    assert len(execution.bindings) == 37

    values, node_evaluations = _materialize_candidate_matrix(_rows(), execution)
    assert values.shape == (8, 37)
    assert node_evaluations == compiled.unique_node_count
    for slot in range(1, 37):
        assert np.array_equal(values[:, 0], values[:, slot], equal_nan=True)
    assert np.isnan(values[0]).all()
    assert np.isfinite(values[1:]).all()
