from __future__ import annotations

from datetime import UTC, datetime, timedelta

from finagent.brokers.mt5.clock import (
    MT5BrokerClockObservation,
    build_mt5_broker_clock_evidence,
)
from finagent.brokers.mt5.continuous_quote_smoke import (
    MT5ContinuousQuoteSmokePolicy,
    build_mt5_continuous_quote_smoke_report,
)

NOW = datetime(2026, 9, 2, 4, 0, tzinfo=UTC)
SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY")


def _clock():
    observations = tuple(
        MT5BrokerClockObservation(
            symbol=symbol,
            raw_broker_time_msc=int((NOW + timedelta(hours=3)).timestamp() * 1000),
            retrieved_at_utc=NOW,
            bid=1.0,
            ask=1.0001,
        )
        for symbol in SYMBOLS
    )
    return build_mt5_broker_clock_evidence(
        "MetaQuotes-Demo",
        observations,
        generated_at=NOW,
    )


def _inventory() -> list[dict[str, object]]:
    return [
        {"name": symbol, "visible": True, "trade_mode": 4}
        for symbol in SYMBOLS
    ]


def _ticks(*, stale: str | None = None) -> tuple[
    dict[str, dict[str, object] | None],
    dict[str, datetime],
]:
    ticks: dict[str, dict[str, object] | None] = {}
    retrieved: dict[str, datetime] = {}
    for symbol in SYMBOLS:
        normalized = NOW - timedelta(seconds=120 if symbol == stale else 1)
        raw = normalized + timedelta(hours=3)
        ticks[symbol] = {
            "time_msc": int(raw.timestamp() * 1000),
            "bid": 1.0,
            "ask": 1.0001,
        }
        retrieved[symbol] = NOW
    return ticks, retrieved


def test_continuous_quote_smoke_accepts_fresh_clock_normalized_quotes() -> None:
    ticks, retrieved = _ticks()
    report = build_mt5_continuous_quote_smoke_report(
        "MetaQuotes-Demo",
        SYMBOLS,
        _inventory(),
        ticks,
        retrieved,
        _clock(),
        generated_at=NOW,
    )

    assert report.passed
    assert report.passed_symbol_count == 3
    assert report.clock_evidence.inferred_offset_seconds == 10_800
    assert all(check.quote_age_seconds == 1.0 for check in report.checks)
    assert report.to_dict()["stage_exit_authority"] is False
    assert report.to_dict()["scope"] == "engineering_smoke_only_not_us_i0_or_us_d3_evidence"


def test_continuous_quote_smoke_fails_closed_on_stale_symbol() -> None:
    ticks, retrieved = _ticks(stale="USDJPY")
    report = build_mt5_continuous_quote_smoke_report(
        "MetaQuotes-Demo",
        SYMBOLS,
        _inventory(),
        ticks,
        retrieved,
        _clock(),
        policy=MT5ContinuousQuoteSmokePolicy(
            minimum_symbol_count=3,
            maximum_quote_age_seconds=60,
        ),
        generated_at=NOW,
    )

    assert not report.passed
    assert report.passed_symbol_count == 2
    usd_jpy = next(item for item in report.checks if item.symbol == "USDJPY")
    assert "stale_quote" in usd_jpy.blockers
    assert "continuous_quote_smoke:insufficient_fresh_symbols:2<3" in report.blockers


def test_continuous_quote_smoke_does_not_mutate_or_claim_us_authority() -> None:
    ticks, retrieved = _ticks()
    inventory = _inventory()
    inventory[0]["visible"] = False
    report = build_mt5_continuous_quote_smoke_report(
        "MetaQuotes-Demo",
        SYMBOLS,
        inventory,
        ticks,
        retrieved,
        _clock(),
        generated_at=NOW,
    )

    assert not report.passed
    assert "not_visible" in report.checks[0].blockers
    payload = report.to_dict()
    assert payload["research_universe_authority"] is False
    assert payload["execution_authority"] is False
