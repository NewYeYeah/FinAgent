from __future__ import annotations

from datetime import UTC, datetime, timedelta

from finagent.brokers.mt5.clock import (
    MT5BrokerClockObservation,
    build_mt5_broker_clock_evidence,
    mt5_broker_clock_evidence_from_document,
)

NOW = datetime(2026, 9, 2, 2, 34, tzinfo=UTC)


def _observation(
    symbol: str,
    *,
    offset_seconds: int = 10_800,
    residual_seconds: float = 0.0,
) -> MT5BrokerClockObservation:
    retrieved = NOW
    raw = retrieved + timedelta(seconds=offset_seconds + residual_seconds)
    return MT5BrokerClockObservation(
        symbol=symbol,
        raw_broker_time_msc=int(raw.timestamp() * 1000),
        retrieved_at_utc=retrieved,
        bid=1.0,
        ask=1.0001,
    )


def test_clock_evidence_infers_observed_plus_three_hours_without_hardcoding() -> None:
    evidence = build_mt5_broker_clock_evidence(
        "MetaQuotes-Demo",
        (
            _observation("EURUSD", residual_seconds=-2.0),
            _observation("GBPUSD", residual_seconds=1.0),
            _observation("USDJPY", residual_seconds=3.0),
        ),
        generated_at=NOW,
    )

    assert evidence.passed
    assert evidence.inferred_offset_seconds == 10_800
    assert evidence.maximum_abs_residual_seconds == 3.0
    normalized = evidence.normalize_epoch_msc(
        int((NOW + timedelta(hours=3, seconds=15)).timestamp() * 1000)
    )
    assert normalized == NOW + timedelta(seconds=15)


def test_clock_evidence_can_infer_a_different_broker_offset() -> None:
    evidence = build_mt5_broker_clock_evidence(
        "Other-Demo",
        (
            _observation("EURUSD", offset_seconds=7200),
            _observation("GBPUSD", offset_seconds=7200),
            _observation("USDJPY", offset_seconds=7200),
        ),
        generated_at=NOW,
    )

    assert evidence.passed
    assert evidence.inferred_offset_seconds == 7200


def test_clock_evidence_fails_closed_on_reference_dispersion() -> None:
    evidence = build_mt5_broker_clock_evidence(
        "MetaQuotes-Demo",
        (
            _observation("EURUSD"),
            _observation("GBPUSD"),
            _observation("USDJPY", residual_seconds=90.0),
        ),
        generated_at=NOW,
    )

    assert not evidence.passed
    assert any(
        item.startswith("broker_clock:reference_residual_exceeded:USDJPY")
        for item in evidence.blockers
    )


def test_clock_evidence_requires_three_active_references() -> None:
    evidence = build_mt5_broker_clock_evidence(
        "MetaQuotes-Demo",
        (
            _observation("EURUSD"),
            _observation("GBPUSD"),
        ),
        generated_at=NOW,
    )

    assert not evidence.passed
    assert "broker_clock:insufficient_references:2<3" in evidence.blockers


def test_clock_evidence_document_round_trip_verifies_content_identity() -> None:
    evidence = build_mt5_broker_clock_evidence(
        "MetaQuotes-Demo",
        (
            _observation("EURUSD"),
            _observation("GBPUSD"),
            _observation("USDJPY"),
        ),
        generated_at=NOW,
    )

    loaded = mt5_broker_clock_evidence_from_document(evidence.to_dict())

    assert loaded.evidence_id == evidence.evidence_id
    assert loaded.passed

    tampered = evidence.to_dict()
    tampered["inferred_offset_seconds"] = 7200
    try:
        mt5_broker_clock_evidence_from_document(tampered)
    except ValueError as exc:
        assert "evidence_id" in str(exc)
    else:  # pragma: no cover - identity tampering must fail closed
        raise AssertionError("tampered broker clock evidence unexpectedly passed")
