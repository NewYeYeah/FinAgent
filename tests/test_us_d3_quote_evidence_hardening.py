from __future__ import annotations

from datetime import UTC, datetime, timedelta

from finagent.data.us_universe_finalization_v2 import (
    USUniverseFinalizationPolicyV2,
    finalize_us_engineering_universe_v2,
)

NOW = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)
SEEDS = ("AMD", "INTC", "MSFT", "NVDA")


def _symbols(count: int = 30) -> list[str]:
    return list(SEEDS) + [f"S{index:02d}" for index in range(count - len(SEEDS))]


def _candidate_report(count: int = 30, *, mt5_probe_id: str = "p0-probe") -> dict[str, object]:
    symbols = _symbols(count)
    return {
        "selection_id": "selection-1",
        "mt5_probe_id": mt5_probe_id,
        "broker_server": "MetaQuotes-Demo",
        "policy": {
            "seed_symbols": list(SEEDS),
            "minimum_selected_count": 20,
        },
        "candidates": [
            {"rank": rank, "research_symbol": symbol}
            for rank, symbol in enumerate(symbols, start=1)
        ],
    }


def _quote_report(
    *,
    count: int = 30,
    mt5_probe_id: str = "p0-probe",
    broker_server: str = "MetaQuotes-Demo",
    stale_symbols: frozenset[str] = frozenset(),
) -> dict[str, object]:
    return {
        "report_id": "quote-report-1",
        "candidate_selection_id": "selection-1",
        "mt5_capability_probe_id": mt5_probe_id,
        "broker_server": broker_server,
        "ready_for_finalization": True,
        "quotes": [
            {
                "symbol": symbol,
                "sampled_at": (
                    NOW - timedelta(hours=2)
                    if symbol in stale_symbols
                    else NOW - timedelta(seconds=30)
                ).isoformat(),
                "spread_bps": 10.0,
                "tradable": True,
            }
            for symbol in _symbols(count)
        ],
    }


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


def _inventory(count: int = 30, *, broker_server: str = "MetaQuotes-Demo") -> dict[str, object]:
    symbols = _symbols(count)
    return {
        "probe_id": "fresh-inventory-1",
        "probed_at": NOW.isoformat(),
        "terminal": {
            "capability_id": "terminal-1",
            "broker_server": broker_server,
        },
        "symbols": [_spec(symbol) for symbol in symbols],
    }


def _policy() -> USUniverseFinalizationPolicyV2:
    return USUniverseFinalizationPolicyV2(
        target_count=25,
        minimum_count=20,
        maximum_count=30,
        maximum_current_spread_bps=50.0,
        maximum_quote_age_seconds=900,
        maximum_future_quote_skew_seconds=60,
    )


def test_v2_finalization_accepts_fresh_identity_bound_quotes() -> None:
    report = finalize_us_engineering_universe_v2(
        _candidate_report(),
        _quote_report(),
        _inventory(),
        policy=_policy(),
        operator_attested=True,
        generated_at=NOW,
    )

    assert report.accepted
    assert report.quote_evidence.passed
    assert report.accepted_mapping_count == 25
    assert set(SEEDS).issubset(report.selected_symbols)
    assert report.universe_id is not None
    assert report.to_dict()["schema_version"] == (
        "finagent.us-engineering-universe-finalization-report.v2"
    )


def test_stale_seed_quote_fails_closed_before_base_materialization() -> None:
    report = finalize_us_engineering_universe_v2(
        _candidate_report(),
        _quote_report(stale_symbols=frozenset({"MSFT"})),
        _inventory(),
        policy=_policy(),
        operator_attested=True,
        generated_at=NOW,
    )

    assert not report.accepted
    assert report.base_finalization is None
    assert "MSFT" in report.quote_evidence.stale_quote_symbols
    assert "quote_evidence:seed_quote_not_fresh:MSFT" in report.blockers


def test_candidate_and_quote_must_bind_same_accepted_p0_probe() -> None:
    report = finalize_us_engineering_universe_v2(
        _candidate_report(mt5_probe_id="p0-probe-a"),
        _quote_report(mt5_probe_id="p0-probe-b"),
        _inventory(),
        policy=_policy(),
        operator_attested=True,
        generated_at=NOW,
    )

    assert not report.accepted
    assert report.base_finalization is None
    assert "quote_evidence:mt5_probe_identity_mismatch" in report.blockers


def test_quote_and_fresh_inventory_must_share_broker_server() -> None:
    report = finalize_us_engineering_universe_v2(
        _candidate_report(),
        _quote_report(),
        _inventory(broker_server="Other-Demo"),
        policy=_policy(),
        operator_attested=True,
        generated_at=NOW,
    )

    assert not report.accepted
    assert report.base_finalization is None
    assert "quote_evidence:broker_server_mismatch" in report.blockers


def test_v2_requires_accepted_seed_retention_in_final_25() -> None:
    candidate = _candidate_report(count=30)
    candidate["candidates"] = [
        {"rank": rank, "research_symbol": symbol}
        for rank, symbol in enumerate(
            [item for item in _symbols(30) if item != "NVDA"] + ["NVDA"],
            start=1,
        )
    ]
    report = finalize_us_engineering_universe_v2(
        candidate,
        _quote_report(),
        _inventory(),
        policy=_policy(),
        operator_attested=True,
        generated_at=NOW,
    )

    assert not report.accepted
    assert "NVDA" in report.missing_seed_symbols
    assert "universe:required_seed_missing:NVDA" in report.blockers
