from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from finagent.research.us_baselines import (
    USBaselineBar,
    USBaselineFeatureKind,
    USBaselineFeatureSpec,
    USBaselineProtocol,
    USBaselineUnavailableReason,
    canonical_us_baseline_denominator,
    evaluate_us_baseline_feature,
)


def _bars(
    closes: tuple[float, ...],
    *,
    session_id: str = "XNYS:2026-03-09",
    incomplete_index: int | None = None,
    volumes: tuple[float, ...] | None = None,
) -> tuple[USBaselineBar, ...]:
    start = datetime(2026, 3, 9, 13, 30, tzinfo=UTC)
    resolved_volumes = volumes or tuple(100.0 + index * 10.0 for index in range(len(closes)))
    return tuple(
        USBaselineBar(
            event_time=start + timedelta(minutes=15 * index),
            available_at=start + timedelta(minutes=15 * (index + 1)),
            session_id=session_id,
            open=close - 0.5,
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            volume=resolved_volumes[index],
            is_complete=index != incomplete_index,
        )
        for index, close in enumerate(closes)
    )


def _candidate(feature_id: str):
    denominator = canonical_us_baseline_denominator()
    return denominator.protocol, next(
        item for item in denominator.candidates if item.feature_id == feature_id
    )


def test_canonical_denominator_is_fixed_content_addressed_manual_arm() -> None:
    first = canonical_us_baseline_denominator()
    second = canonical_us_baseline_denominator()

    assert first.denominator_id == second.denominator_id
    assert first.generator_type == "MANUAL"
    assert len(first.candidates) == 8
    assert len({item.feature_id for item in first.candidates}) == 8
    assert len({item.spec_id for item in first.candidates}) == 8
    assert all(item.protocol_id == first.protocol.protocol_id for item in first.candidates)
    assert first.protocol.signal_interval.value == "15m"
    assert tuple(item.value for item in first.protocol.robustness_intervals) == ("5m", "30m")
    assert first.protocol.availability_policy.value == "available_at"
    assert first.protocol.price_basis.value == "raw"
    assert first.protocol.same_session_only is True
    assert first.protocol.require_complete_bars is True


def test_reversal_and_momentum_use_only_completed_same_session_history() -> None:
    bars = _bars((100.0, 102.0, 104.0, 108.0, 110.0))
    protocol, reversal = _candidate("manual_reversal_1bar")
    _, momentum = _candidate("manual_momentum_4bar")

    reversal_result = evaluate_us_baseline_feature(reversal, bars, protocol=protocol)
    momentum_result = evaluate_us_baseline_feature(momentum, bars, protocol=protocol)

    assert reversal_result.available
    assert reversal_result.value == pytest.approx(-(110.0 / 108.0 - 1.0))
    assert reversal_result.used_bar_count == 2
    assert momentum_result.available
    assert momentum_result.value == pytest.approx(110.0 / 100.0 - 1.0)
    assert momentum_result.used_bar_count == 5
    assert momentum_result.available_at == bars[-1].available_at
    assert momentum_result.event_time == bars[-1].event_time


def test_range_volatility_volume_surprise_and_close_location_are_deterministic() -> None:
    bars = _bars(
        (100.0, 101.0, 103.0, 102.0, 104.0, 105.0, 106.0, 107.0, 108.0),
        volumes=(100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 200.0),
    )
    protocol, range_spec = _candidate("manual_range_mean_4bar")
    _, volatility_spec = _candidate("manual_return_volatility_4bar")
    _, volume_spec = _candidate("manual_volume_surprise_8bar")
    _, close_location_spec = _candidate("manual_close_location_1bar")

    range_result = evaluate_us_baseline_feature(range_spec, bars, protocol=protocol)
    volatility_result = evaluate_us_baseline_feature(volatility_spec, bars, protocol=protocol)
    volume_result = evaluate_us_baseline_feature(volume_spec, bars, protocol=protocol)
    close_location_result = evaluate_us_baseline_feature(
        close_location_spec,
        bars,
        protocol=protocol,
    )

    expected_range = sum(2.0 / close for close in (105.0, 106.0, 107.0, 108.0)) / 4.0
    assert range_result.value == pytest.approx(expected_range)
    assert volatility_result.value is not None and volatility_result.value > 0
    assert volume_result.value == pytest.approx(1.0)
    assert close_location_result.value == pytest.approx(0.0)


def test_insufficient_history_cross_session_and_incomplete_bars_are_explicit() -> None:
    protocol, spec = _candidate("manual_momentum_4bar")

    insufficient = evaluate_us_baseline_feature(spec, _bars((100.0, 101.0)), protocol=protocol)
    assert insufficient.available is False
    assert insufficient.unavailable_reason is USBaselineUnavailableReason.INSUFFICIENT_HISTORY

    first_session = _bars((100.0, 101.0, 102.0), session_id="XNYS:2026-03-06")
    second_session = _bars((103.0, 104.0), session_id="XNYS:2026-03-09")
    shifted = tuple(
        USBaselineBar(
            event_time=bar.event_time + timedelta(days=3),
            available_at=bar.available_at + timedelta(days=3),
            session_id=bar.session_id,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            is_complete=bar.is_complete,
        )
        for bar in second_session
    )
    cross_session = evaluate_us_baseline_feature(
        spec,
        first_session + shifted,
        protocol=protocol,
    )
    assert cross_session.available is False
    assert cross_session.unavailable_reason is USBaselineUnavailableReason.CROSS_SESSION_WINDOW

    incomplete = evaluate_us_baseline_feature(
        spec,
        _bars((100.0, 101.0, 102.0, 103.0, 104.0), incomplete_index=2),
        protocol=protocol,
    )
    assert incomplete.available is False
    assert incomplete.unavailable_reason is USBaselineUnavailableReason.INCOMPLETE_BAR


def test_zero_reference_volume_is_not_silently_repaired() -> None:
    protocol, spec = _candidate("manual_volume_surprise_8bar")
    bars = _bars(
        (100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0),
        volumes=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 100.0),
    )

    result = evaluate_us_baseline_feature(spec, bars, protocol=protocol)

    assert result.available is False
    assert result.unavailable_reason is USBaselineUnavailableReason.ZERO_REFERENCE_VOLUME


def test_feature_protocol_identity_and_ordering_fail_closed() -> None:
    protocol = USBaselineProtocol()
    foreign = USBaselineFeatureSpec(
        feature_id="foreign",
        kind=USBaselineFeatureKind.MOMENTUM,
        window_bars=2,
        input_fields=("close",),
        hypothesis="test",
        description="test",
        protocol_id="different-protocol",
    )
    bars = _bars((100.0, 101.0))

    with pytest.raises(ValueError, match="identity mismatch"):
        evaluate_us_baseline_feature(foreign, bars, protocol=protocol)

    _, spec = _candidate("manual_reversal_1bar")
    with pytest.raises(ValueError, match="event_time"):
        evaluate_us_baseline_feature(spec, tuple(reversed(bars)), protocol=protocol)


def test_denominator_identity_changes_when_candidate_definition_changes() -> None:
    denominator = canonical_us_baseline_denominator()
    original = denominator.candidates[0]
    changed = USBaselineFeatureSpec(
        feature_id=original.feature_id,
        kind=original.kind,
        window_bars=original.window_bars + 1,
        input_fields=original.input_fields,
        hypothesis=original.hypothesis,
        description=original.description,
        protocol_id=original.protocol_id,
    )

    assert changed.spec_id != original.spec_id
