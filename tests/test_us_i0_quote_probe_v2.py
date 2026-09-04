from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from finagent.brokers.mt5.clock import (
    MT5BrokerClockObservation,
    build_mt5_broker_clock_evidence,
)
from finagent.data.us_candidate_quotes_v2 import (
    build_candidate_quote_probe_report_v2,
    candidate_quote_probe_report_v2_from_document,
)

NOW = datetime(2026, 9, 2, 2, 34, tzinfo=UTC)
SEEDS = ("AMD", "INTC", "MSFT", "NVDA")


def _symbols(count: int = 24) -> list[str]:
    return list(SEEDS) + [f"S{index:02d}" for index in range(count - len(SEEDS))]


def _candidate(count: int = 24) -> dict[str, object]:
    symbols = _symbols(count)
    return {
        "selection_id": "selection-1",
        "ready_for_spread_probe": True,
        "spread_probe_symbols": symbols,
        "mt5_probe_id": "p0-probe",
        "broker_server": "MetaQuotes-Demo",
        "policy": {
            "minimum_selected_count": 20,
            "seed_symbols": list(SEEDS),
        },
    }


def _probe() -> dict[str, object]:
    return {
        "probe_id": "p0-probe",
        "terminal": {"broker_server": "MetaQuotes-Demo"},
    }


def _clock():
    observations = tuple(
        MT5BrokerClockObservation(
            symbol=symbol,
            raw_broker_time_msc=int((NOW + timedelta(hours=3)).timestamp() * 1000),
            retrieved_at_utc=NOW,
            bid=1.0,
            ask=1.0001,
        )
        for symbol in ("EURUSD", "GBPUSD", "USDJPY")
    )
    return build_mt5_broker_clock_evidence(
        "MetaQuotes-Demo",
        observations,
        generated_at=NOW,
    )


def _inventory(count: int = 24, *, invisible: frozenset[str] = frozenset()):
    return [
        {
            "name": symbol,
            "visible": symbol not in invisible,
            "trade_mode": 4,
        }
        for symbol in _symbols(count)
    ]


def _ticks(
    count: int = 24,
    *,
    normalized_time: datetime | None = None,
) -> tuple[dict[str, dict[str, object] | None], dict[str, datetime]]:
    target = normalized_time or (NOW - timedelta(seconds=30))
    raw = target + timedelta(hours=3)
    rows: dict[str, dict[str, object] | None] = {}
    retrieved: dict[str, datetime] = {}
    for symbol in _symbols(count):
        rows[symbol] = {
            "time_msc": int(raw.timestamp() * 1000),
            "time": int(raw.timestamp()),
            "bid": 100.0,
            "ask": 100.1,
        }
        retrieved[symbol] = NOW
    return rows, retrieved


def test_quote_probe_v2_normalizes_broker_clock_before_freshness() -> None:
    ticks, retrieved = _ticks()
    report = build_candidate_quote_probe_report_v2(
        _candidate(),
        _probe(),
        _inventory(),
        ticks,
        retrieved,
        _clock(),
        generated_at=NOW,
    )

    assert report.ready_for_finalization
    assert len(report.valid_quote_symbols) == 24
    assert report.broker_clock_evidence.inferred_offset_seconds == 10_800
    assert all(
        item.normalized_sampled_at_utc == NOW - timedelta(seconds=30)
        for item in report.quotes
    )
    assert all(item.quote_age_at_retrieval_seconds == 30 for item in report.quotes)


def test_stale_broker_quote_is_classified_stale_not_future_after_normalization() -> None:
    ticks, retrieved = _ticks(normalized_time=NOW - timedelta(hours=2))
    report = build_candidate_quote_probe_report_v2(
        _candidate(),
        _probe(),
        _inventory(),
        ticks,
        retrieved,
        _clock(),
        generated_at=NOW,
    )

    assert not report.ready_for_finalization
    assert report.valid_quote_symbols == ()
    assert report.invalid_reason_counts["stale_quote"] == 24
    assert "future_quote" not in report.invalid_reason_counts


def test_visibility_failure_has_specific_reason_and_does_not_need_tick_repair() -> None:
    invisible = frozenset({"S00"})
    ticks, retrieved = _ticks()
    ticks["S00"] = None
    retrieved.pop("S00")
    report = build_candidate_quote_probe_report_v2(
        _candidate(),
        _probe(),
        _inventory(invisible=invisible),
        ticks,
        retrieved,
        _clock(),
        generated_at=NOW,
    )

    assert report.issue_by_symbol["S00"] == ("not_visible",)
    assert "S00" not in report.valid_quote_symbols


def test_quote_probe_v2_round_trip_verifies_normalized_clock_identity() -> None:
    ticks, retrieved = _ticks()
    report = build_candidate_quote_probe_report_v2(
        _candidate(),
        _probe(),
        _inventory(),
        ticks,
        retrieved,
        _clock(),
        generated_at=NOW,
    )
    payload = report.to_dict()

    loaded = candidate_quote_probe_report_v2_from_document(payload)
    assert loaded.report_id == report.report_id
    assert loaded.ready_for_finalization

    quotes = payload["quotes"]
    assert isinstance(quotes, list)
    first = quotes[0]
    assert isinstance(first, dict)
    first["normalized_sampled_at_utc"] = (NOW + timedelta(hours=1)).isoformat()

    with pytest.raises(ValueError, match="normalized timestamp"):
        candidate_quote_probe_report_v2_from_document(payload)


def test_broker_clock_failure_blocks_all_quote_admission() -> None:
    bad_clock = build_mt5_broker_clock_evidence(
        "MetaQuotes-Demo",
        (
            MT5BrokerClockObservation(
                symbol="EURUSD",
                raw_broker_time_msc=int((NOW + timedelta(hours=3)).timestamp() * 1000),
                retrieved_at_utc=NOW,
                bid=1.0,
                ask=1.0001,
            ),
            MT5BrokerClockObservation(
                symbol="GBPUSD",
                raw_broker_time_msc=int((NOW + timedelta(hours=3)).timestamp() * 1000),
                retrieved_at_utc=NOW,
                bid=1.0,
                ask=1.0001,
            ),
        ),
        generated_at=NOW,
    )
    ticks, retrieved = _ticks()
    report = build_candidate_quote_probe_report_v2(
        _candidate(),
        _probe(),
        _inventory(),
        ticks,
        retrieved,
        bad_clock,
        generated_at=NOW,
    )

    assert not report.ready_for_finalization
    assert "quote_probe:broker_clock_evidence_failed" in report.blockers
    assert report.invalid_reason_counts["broker_clock_unavailable"] == 24


def test_quote_probe_uses_mapped_broker_symbols_for_required_seeds() -> None:
    candidate = _candidate()
    mapped = {symbol: f"{symbol}.NAS" for symbol in _symbols()}
    candidate["spread_probe_symbols"] = list(mapped.values())
    candidate["candidates"] = [
        {
            "rank": rank,
            "research_symbol": research,
            "broker_symbol": broker,
        }
        for rank, (research, broker) in enumerate(mapped.items(), start=1)
    ]
    inventory = [
        {"name": broker, "visible": True, "trade_mode": 4}
        for broker in mapped.values()
    ]
    raw = NOW - timedelta(seconds=30) + timedelta(hours=3)
    ticks = {
        broker: {
            "time_msc": int(raw.timestamp() * 1000),
            "time": int(raw.timestamp()),
            "bid": 100.0,
            "ask": 100.1,
        }
        for broker in mapped.values()
    }
    retrieved = {broker: NOW for broker in mapped.values()}

    report = build_candidate_quote_probe_report_v2(
        candidate,
        _probe(),
        inventory,
        ticks,
        retrieved,
        _clock(),
        generated_at=NOW,
    )

    assert report.ready_for_finalization
    assert report.required_seed_symbols == tuple(f"{symbol}.NAS" for symbol in sorted(SEEDS))
