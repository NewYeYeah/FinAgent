from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
    USBaselineFeatureKind,
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
            volume = (
                0.0
                if session_number == 3 and bar_index < 12
                else 1_000.0 + global_index * 11.0
            )
            is_complete = not (session_number == 2 and bar_index == 12)
            rows.append(
                USBaselineBar(
                    asset="SYNTH",
                    event_time=event_time,
                    available_at=event_time + timedelta(minutes=15),
                    session_id=session_id,
                    bar_index=bar_index,
                    open=open_value,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    observed_minute_count=15 if is_complete else 14,
                    expected_minute_count=15,
                    is_complete=is_complete,
                )
            )
            global_index += 1
    return tuple(rows)


def _assert_family_parity(kind: USBaselineFeatureKind) -> None:
    candidates = tuple(
        candidate
        for candidate in canonical_us_a0_primitive_vocabulary().all_candidates()
        if candidate.kind is kind
    )
    graphs = tuple(legacy_a0_candidate_factor_graph(candidate).graph for candidate in candidates)
    compiled = compile_factor_graph_batch(graphs)
    bars = _bars()
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
        USBaselineUnavailableReason.INCOMPLETE_BAR: (
            FactorMaterializationUnavailableReason.INCOMPLETE_BAR
        ),
        USBaselineUnavailableReason.ZERO_REFERENCE_VOLUME: (
            FactorMaterializationUnavailableReason.NUMERIC_UNAVAILABLE
        ),
    }

    for candidate in candidates:
        binding = legacy_a0_candidate_factor_graph(candidate)
        validation = validate_factor_graph(binding.graph)
        assert validation.valid
        assert validation.canonicalization is not None
        actual = actual_by_candidate[validation.canonicalization.candidate_id]
        expected_spec = candidate.compile_feature_spec()
        for index in range(len(bars)):
            expected = evaluate_us_baseline_feature(
                expected_spec,
                bars[: index + 1],
                protocol=protocol,
            )
            actual_value = actual.values[index]
            actual_reason = actual.unavailable_reasons[index]
            if expected.value is None:
                assert actual_value is None, (candidate.structural_key, index, expected)
                assert expected.unavailable_reason is not None
                assert actual_reason is reason_map[expected.unavailable_reason], (
                    candidate.structural_key,
                    index,
                    expected.unavailable_reason,
                    actual_reason,
                )
            else:
                assert actual_reason is None
                assert actual_value is not None
                assert actual_value.hex() == expected.value.hex(), (
                    candidate.structural_key,
                    index,
                    actual_value,
                    expected.value,
                )


def test_reversal_parity() -> None:
    _assert_family_parity(USBaselineFeatureKind.REVERSAL)


def test_momentum_parity() -> None:
    _assert_family_parity(USBaselineFeatureKind.MOMENTUM)


def test_range_mean_parity() -> None:
    _assert_family_parity(USBaselineFeatureKind.RANGE_MEAN)


def test_return_volatility_parity() -> None:
    _assert_family_parity(USBaselineFeatureKind.RETURN_VOLATILITY)


def test_volume_surprise_parity() -> None:
    _assert_family_parity(USBaselineFeatureKind.VOLUME_SURPRISE)


def test_close_location_parity() -> None:
    _assert_family_parity(USBaselineFeatureKind.CLOSE_LOCATION)
