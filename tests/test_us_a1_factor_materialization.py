from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from finagent.research.us_a1_factor_graph import (
    FactorGraphSpec,
    FactorInputField,
    FactorNode,
    FactorOperator,
)
from finagent.research.us_a1_factor_materialization import (
    FactorMaterializationUnavailableReason,
    compile_factor_graph_batch,
    materialize_compiled_factor_batch,
)
from finagent.research.us_a1_factor_validation import validate_factor_graph
from finagent.research.us_a1_legacy_graphs import legacy_a0_candidate_factor_graph
from finagent.research.us_agent_value_protocol import canonical_us_a0_primitive_vocabulary
from finagent.research.us_baselines import (
    USBaselineBar,
    USBaselineProtocol,
    USBaselineUnavailableReason,
    evaluate_us_baseline_feature,
)


def _bars() -> tuple[USBaselineBar, ...]:
    session_starts = (
        datetime(2026, 1, 2, 14, 30, tzinfo=UTC),
        datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
        datetime(2026, 1, 6, 14, 30, tzinfo=UTC),
    )
    rows: list[USBaselineBar] = []
    global_index = 0
    for session_number, session_start in enumerate(session_starts, start=1):
        session_id = session_start.date().isoformat()
        for bar_index in range(26):
            event_time = session_start + timedelta(minutes=15 * bar_index)
            base = 100.0 + session_number * 7.0 + bar_index * 0.35
            close = base + ((bar_index % 5) - 2) * 0.07
            if session_number == 2 and bar_index == 5:
                open_value = close
                high = close
                low = close
            else:
                open_value = base - 0.04
                high = max(open_value, close) + 0.22
                low = min(open_value, close) - 0.19
            volume = 0.0 if session_number == 3 and bar_index < 12 else 1_000.0 + global_index * 11.0
            is_complete = not (session_number == 2 and bar_index == 12)
            rows.append(
                USBaselineBar(
                    event_time=event_time,
                    available_at=event_time + timedelta(minutes=15),
                    session_id=session_id,
                    open=open_value,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    is_complete=is_complete,
                )
            )
            global_index += 1
    return tuple(rows)


def _legacy_graphs() -> tuple[FactorGraphSpec, ...]:
    return tuple(
        legacy_a0_candidate_factor_graph(candidate).graph
        for candidate in canonical_us_a0_primitive_vocabulary().all_candidates()
    )


def _a1_candidate_id(candidate) -> str:
    binding = legacy_a0_candidate_factor_graph(candidate)
    evidence = validate_factor_graph(binding.graph)
    assert evidence.valid
    assert evidence.canonicalization is not None
    return evidence.canonicalization.candidate_id


def test_all_62_legacy_candidates_are_bitwise_equal_to_a0_per_formation() -> None:
    vocabulary = canonical_us_a0_primitive_vocabulary()
    candidates = vocabulary.all_candidates()
    bars = _bars()
    compiled = compile_factor_graph_batch(_legacy_graphs())
    materialized = materialize_compiled_factor_batch(compiled, bars)
    actual_by_candidate = {item.candidate_id: item for item in materialized.candidates}
    protocol = USBaselineProtocol()

    reason_map = {
        USBaselineUnavailableReason.INSUFFICIENT_HISTORY: (
            FactorMaterializationUnavailableReason.INSUFFICIENT_HISTORY
        ),
        USBaselineUnavailableReason.CROSS_SESSION_WINDOW: (
            FactorMaterializationUnavailableReason.CROSS_SESSION_WINDOW
        ),
        USBaselineUnavailableReason.INCOMPLETE_BAR: FactorMaterializationUnavailableReason.INCOMPLETE_BAR,
        USBaselineUnavailableReason.ZERO_REFERENCE_VOLUME: (
            FactorMaterializationUnavailableReason.NUMERIC_UNAVAILABLE
        ),
    }

    for candidate in candidates:
        a1_candidate_id = _a1_candidate_id(candidate)
        actual = actual_by_candidate[a1_candidate_id]
        feature_spec = candidate.compile_feature_spec()
        assert actual.lookback_bars == candidate.window_bars
        for index in range(len(bars)):
            expected = evaluate_us_baseline_feature(
                feature_spec,
                bars[: index + 1],
                protocol=protocol,
            )
            actual_value = actual.values[index]
            actual_reason = actual.unavailable_reasons[index]
            if expected.value is None:
                assert actual_value is None, (candidate.structural_key, index, expected)
                assert expected.unavailable_reason is not None
                assert actual_reason is reason_map[expected.unavailable_reason]
            else:
                assert actual_reason is None
                assert actual_value is not None
                assert actual_value.hex() == expected.value.hex(), (
                    candidate.structural_key,
                    index,
                    actual_value,
                    expected.value,
                )


def test_batch_compiler_reuses_canonical_subexpressions_and_is_order_independent() -> None:
    graphs = _legacy_graphs()
    compiled = compile_factor_graph_batch(graphs)
    reversed_compiled = compile_factor_graph_batch(tuple(reversed(graphs)))

    assert len(compiled.roots) == 62
    assert compiled.unique_node_count < compiled.naive_node_count
    assert compiled.reused_node_count > 0
    assert compiled.reuse_ratio > 0.25
    assert compiled.batch_id == reversed_compiled.batch_id

    materialized = materialize_compiled_factor_batch(compiled, _bars())
    assert materialized.node_series_evaluation_count == compiled.unique_node_count
    assert materialized.node_series_evaluation_count < compiled.naive_node_count


def test_materializer_rejects_cross_sectional_or_regime_operators_until_explicit_extension() -> None:
    graph = FactorGraphSpec(
        nodes=(
            FactorNode(
                node_id="close",
                operator=FactorOperator.INPUT,
                input_field=FactorInputField.CLOSE,
            ),
            FactorNode(
                node_id="return",
                operator=FactorOperator.SIMPLE_RETURN,
                inputs=("close",),
                window_bars=2,
            ),
            FactorNode(
                node_id="rank",
                operator=FactorOperator.CROSS_SECTION_RANK,
                inputs=("return",),
            ),
        ),
        output_node_id="rank",
    )

    with pytest.raises(ValueError, match="does not yet admit operators: CROSS_SECTION_RANK"):
        compile_factor_graph_batch((graph,))


def test_materialization_batch_size_is_bounded() -> None:
    compiled = compile_factor_graph_batch((_legacy_graphs()[0],))
    with pytest.raises(ValueError, match="bounded bar count"):
        materialize_compiled_factor_batch(compiled, _bars(), maximum_bars_per_batch=10)


def test_materializer_rejects_non_increasing_bar_order() -> None:
    compiled = compile_factor_graph_batch((_legacy_graphs()[0],))
    bars = _bars()
    malformed = (bars[1], bars[0])
    with pytest.raises(ValueError, match="strictly ordered by event_time"):
        materialize_compiled_factor_batch(compiled, malformed)
