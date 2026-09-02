from __future__ import annotations

from datetime import UTC, datetime, timedelta

from finagent.brokers.mt5.clock import (
    MT5BrokerClockObservation,
    build_mt5_broker_clock_evidence,
)
from finagent.data.us_candidate_quotes_v2 import build_candidate_quote_probe_report_v2
from finagent.data.us_universe_finalization_v3 import (
    USUniverseFinalizationPolicyV3,
    finalize_us_engineering_universe_v3,
)

NOW = datetime(2026, 9, 2, 14, 0, tzinfo=UTC)
SEEDS = ("AMD", "INTC", "MSFT", "NVDA")


def _symbols(count: int = 30) -> list[str]:
    return list(SEEDS) + [f"S{index:02d}" for index in range(count - len(SEEDS))]


def _candidate(count: int = 30, *, broker_server: str = "MetaQuotes-Demo") -> dict[str, object]:
    symbols = _symbols(count)
    return {
        "selection_id": "selection-1",
        "ready_for_spread_probe": True,
        "spread_probe_symbols": symbols,
        "mt5_probe_id": "p0-probe",
        "broker_server": broker_server,
        "policy": {
            "minimum_selected_count": 20,
            "seed_symbols": list(SEEDS),
        },
        "candidates": [
            {"rank": rank, "research_symbol": symbol}
            for rank, symbol in enumerate(symbols, start=1)
        ],
    }


def _p0_probe() -> dict[str, object]:
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


def _quote_inventory(count: int = 30) -> list[dict[str, object]]:
    return [
        {"name": symbol, "visible": True, "trade_mode": 4}
        for symbol in _symbols(count)
    ]


def _quote_report(
    count: int = 30,
    *,
    wide_symbol: str | None = None,
    stale_symbols: frozenset[str] = frozenset(),
):
    fresh_raw_time = NOW - timedelta(seconds=30) + timedelta(hours=3)
    stale_raw_time = NOW - timedelta(hours=2) + timedelta(hours=3)
    ticks: dict[str, dict[str, object] | None] = {}
    retrieved: dict[str, datetime] = {}
    for symbol in _symbols(count):
        raw_time = stale_raw_time if symbol in stale_symbols else fresh_raw_time
        ticks[symbol] = {
            "time_msc": int(raw_time.timestamp() * 1000),
            "time": int(raw_time.timestamp()),
            "bid": 100.0,
            "ask": 102.0 if symbol == wide_symbol else 100.1,
        }
        retrieved[symbol] = NOW
    return build_candidate_quote_probe_report_v2(
        _candidate(count),
        _p0_probe(),
        _quote_inventory(count),
        ticks,
        retrieved,
        _clock(),
        generated_at=NOW,
    )


def _spec(symbol: str) -> dict[str, object]:
    return {
        "spec_id": f"spec-{symbol}",
        "symbol": symbol,
        "path": f"Nasdaq\\Stock\\{symbol}",
        "visible": True,
        "tradable": True,
        "trade_mode": 4,
        "trade_calc_mode": 32,
        "point": 0.01,
        "tick_size": 0.01,
        "tick_value": 0.01,
        "contract_size": 1.0,
        "volume_min": 1.0,
        "volume_max": 100000.0,
        "volume_step": 1.0,
        "margin_initial": 0.0,
        "margin_maintenance": 0.0,
        "swap_mode": 0,
        "swap_long": 0.0,
        "swap_short": 0.0,
        "filling_mode": 1,
        "order_mode": 127,
        "currency_base": "USD",
        "currency_profit": "USD",
        "currency_margin": "USD",
    }


def _final_inventory(
    count: int = 30,
    *,
    broker_server: str = "MetaQuotes-Demo",
) -> dict[str, object]:
    return {
        "probe_id": "fresh-inventory-1",
        "probed_at": NOW.isoformat(),
        "terminal": {
            "capability_id": "terminal-1",
            "broker_server": broker_server,
        },
        "symbols": [_spec(symbol) for symbol in _symbols(count)],
    }


def _policy(**overrides: object) -> USUniverseFinalizationPolicyV3:
    values: dict[str, object] = {
        "target_count": 25,
        "minimum_count": 20,
        "maximum_count": 30,
        "maximum_current_spread_bps": 50.0,
        "maximum_quote_age_seconds": 900,
        "maximum_future_quote_skew_seconds": 60,
    }
    values.update(overrides)
    return USUniverseFinalizationPolicyV3(**values)  # type: ignore[arg-type]


def test_v3_accepts_clock_normalized_fresh_quote_report() -> None:
    quote = _quote_report()
    report = finalize_us_engineering_universe_v3(
        _candidate(),
        quote.to_dict(),
        _final_inventory(),
        policy=_policy(),
        operator_attested=True,
        generated_at=NOW,
    )

    assert report.accepted
    assert report.quote_evidence.passed
    assert report.quote_evidence.clock_evidence_passed
    assert report.accepted_mapping_count == 25
    assert set(SEEDS).issubset(report.selected_symbols)
    assert report.to_dict()["schema_version"] == (
        "finagent.us-engineering-universe-finalization-report.v3"
    )


def test_v3_rechecks_normalized_freshness_at_finalization_time() -> None:
    quote = _quote_report()
    report = finalize_us_engineering_universe_v3(
        _candidate(),
        quote.to_dict(),
        _final_inventory(),
        policy=_policy(),
        operator_attested=True,
        generated_at=NOW + timedelta(seconds=901),
    )

    assert not report.accepted
    assert len(report.quote_evidence.stale_quote_symbols) == 30
    assert report.quote_evidence.future_quote_symbols == ()
    assert "quote_evidence:insufficient_fresh_quotes:0<20" in report.blockers


def test_v3_preserves_probe_time_stale_symbols_in_final_assessment() -> None:
    quote = _quote_report(stale_symbols=frozenset({"AMD", "INTC"}))
    assert not quote.ready_for_finalization
    assert quote.issue_by_symbol["AMD"] == ("stale_quote",)
    assert quote.issue_by_symbol["INTC"] == ("stale_quote",)

    report = finalize_us_engineering_universe_v3(
        _candidate(),
        quote.to_dict(),
        _final_inventory(),
        policy=_policy(),
        operator_attested=True,
        generated_at=NOW,
    )

    assert not report.accepted
    assert set(report.quote_evidence.stale_quote_symbols) == {"AMD", "INTC"}
    assert report.quote_evidence.future_quote_symbols == ()
    assert set(report.to_dict()["excluded_by_quote_quality"]) == {"AMD", "INTC"}


def test_v3_rejects_quote_probe_and_finalizer_freshness_policy_drift() -> None:
    quote = _quote_report()
    report = finalize_us_engineering_universe_v3(
        _candidate(),
        quote.to_dict(),
        _final_inventory(),
        policy=_policy(maximum_quote_age_seconds=1200),
        operator_attested=True,
        generated_at=NOW,
    )

    assert not report.accepted
    assert "quote_evidence:quote_probe_policy_mismatch" in report.blockers


def test_v3_binds_clock_and_inventory_to_same_broker_server() -> None:
    quote = _quote_report()
    report = finalize_us_engineering_universe_v3(
        _candidate(),
        quote.to_dict(),
        _final_inventory(broker_server="Other-Demo"),
        policy=_policy(),
        operator_attested=True,
        generated_at=NOW,
    )

    assert not report.accepted
    assert "quote_evidence:broker_server_mismatch" in report.blockers


def test_v3_required_seed_still_fails_when_current_spread_is_too_wide() -> None:
    quote = _quote_report(wide_symbol="INTC")
    report = finalize_us_engineering_universe_v3(
        _candidate(),
        quote.to_dict(),
        _final_inventory(),
        policy=_policy(),
        operator_attested=True,
        generated_at=NOW,
    )

    assert not report.accepted
    assert "INTC" in report.excluded_by_spread
    assert "INTC" in report.missing_seed_symbols
    assert "universe:required_seed_missing:INTC" in report.blockers
