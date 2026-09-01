from __future__ import annotations

from datetime import UTC, datetime

from finagent.data.us_universe_finalization import (
    USUniverseFinalizationPolicy,
    build_candidate_quote_probe_report,
    finalize_us_engineering_universe,
)


def _candidate_report(count: int = 30) -> dict[str, object]:
    symbols = ["AMD", "INTC", "MSFT", "NVDA"] + [f"S{index:02d}" for index in range(count - 4)]
    return {
        "selection_id": "selection-1",
        "ready_for_spread_probe": True,
        "spread_probe_symbols": symbols,
        "policy": {
            "minimum_selected_count": 20,
            "seed_symbols": ["AMD", "INTC", "MSFT", "NVDA"],
        },
        "candidates": [
            {
                "rank": index,
                "research_symbol": symbol,
            }
            for index, symbol in enumerate(symbols, start=1)
        ],
    }


def _spec(symbol: str, *, visible: bool = True) -> dict[str, object]:
    return {
        "spec_id": f"spec-{symbol}",
        "symbol": symbol,
        "path": f"Nasdaq\\Stock\\{symbol}",
        "visible": visible,
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


def _probe(symbols: list[str]) -> dict[str, object]:
    return {
        "probe_id": "mt5-probe-1",
        "probed_at": "2026-09-01T12:00:00+00:00",
        "terminal": {
            "capability_id": "terminal-1",
            "broker_server": "MetaQuotes-Demo",
        },
        "symbols": [_spec(symbol) for symbol in symbols],
    }


def _symbol_rows(symbols: list[str], *, wide_symbol: str | None = None) -> list[dict[str, object]]:
    return [
        {
            "name": symbol,
            "time": 1788264000,
            "bid": 100.0,
            "ask": 102.0 if symbol == wide_symbol else 100.1,
            "visible": True,
            "trade_mode": 4,
        }
        for symbol in symbols
    ]


def test_quote_probe_and_attested_finalization_build_25_name_universe() -> None:
    candidate = _candidate_report()
    symbols = list(candidate["spread_probe_symbols"])  # type: ignore[arg-type]
    probe = _probe(symbols)
    quotes = build_candidate_quote_probe_report(
        candidate,
        probe,
        _symbol_rows(symbols),
        generated_at=datetime(2026, 9, 1, 12, 5, tzinfo=UTC),
    )

    assert quotes.ready_for_finalization
    assert quotes.blockers == ()

    report = finalize_us_engineering_universe(
        candidate,
        quotes.to_dict(),
        probe,
        policy=USUniverseFinalizationPolicy(target_count=25),
        operator_attested=True,
        generated_at=datetime(2026, 9, 1, 12, 6, tzinfo=UTC),
    )
    assert report.accepted
    assert report.accepted_mapping_count == 25
    assert report.universe_id is not None
    assert len(report.selected_symbols) == 25


def test_finalization_requires_explicit_operator_attestation() -> None:
    candidate = _candidate_report()
    symbols = list(candidate["spread_probe_symbols"])  # type: ignore[arg-type]
    probe = _probe(symbols)
    quotes = build_candidate_quote_probe_report(candidate, probe, _symbol_rows(symbols))
    report = finalize_us_engineering_universe(
        candidate,
        quotes.to_dict(),
        probe,
        operator_attested=False,
    )

    assert not report.accepted
    assert "universe:operator_attestation_required" in report.blockers


def test_spread_filter_is_identity_bound_and_fails_if_target_cannot_be_filled() -> None:
    candidate = _candidate_report(count=25)
    symbols = list(candidate["spread_probe_symbols"])  # type: ignore[arg-type]
    probe = _probe(symbols)
    quotes = build_candidate_quote_probe_report(
        candidate,
        probe,
        _symbol_rows(symbols, wide_symbol=symbols[-1]),
    )
    report = finalize_us_engineering_universe(
        candidate,
        quotes.to_dict(),
        probe,
        policy=USUniverseFinalizationPolicy(
            target_count=25,
            maximum_current_spread_bps=50.0,
        ),
        operator_attested=True,
    )

    assert not report.accepted
    assert symbols[-1] in report.excluded_by_spread
    assert any(item.startswith("universe:insufficient_spread_eligible") for item in report.blockers)
