from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from finagent.brokers.mt5.clock import (
    MT5BrokerClockObservation,
    build_mt5_broker_clock_evidence,
)
from finagent.data.us_candidate_quotes_v2 import (
    DEFAULT_US_CANDIDATE_QUOTE_PROBE_POLICY_V2,
    USCandidateQuoteIssue,
    USCandidateQuoteProbeReportV2,
    USCandidateQuoteSnapshotV2,
)
from finagent.data.us_delayed_reference_quotes import (
    build_us_delayed_reference_quote_report,
)
from finagent.data.us_simulation_universe import (
    CANONICAL_US_SIMULATION_UNIVERSE_FINALIZATION_POLICY,
    USSimulationUniverseFinalizationPolicy,
    finalize_us_simulation_engineering_universe,
    us_simulation_universe_policy_from_document,
    validate_canonical_us_simulation_universe_policy,
)

RETRIEVED = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
OFFSET_SECONDS = 3 * 60 * 60
SEEDS = ("AMD", "INTC", "MSFT", "NVDA")


def _symbols(count: int = 30) -> tuple[str, ...]:
    return SEEDS + tuple(f"S{index:02d}" for index in range(count - len(SEEDS)))


def _candidate(
    *,
    count: int = 30,
    selection_id: str = "candidate-selection-test",
) -> dict[str, object]:
    symbols = _symbols(count)
    return {
        "selection_id": selection_id,
        "ready_for_spread_probe": True,
        "spread_probe_symbols": list(symbols),
        "mt5_probe_id": "p0-probe",
        "broker_server": "MetaQuotes-Demo",
        "policy": {
            "minimum_selected_count": 20,
            "seed_symbols": list(SEEDS),
        },
        "candidates": [
            {"rank": rank, "research_symbol": symbol}
            for rank, symbol in enumerate(symbols, start=1)
        ],
    }


def _raw_msc(normalized: datetime) -> int:
    broker_wall = normalized + timedelta(seconds=OFFSET_SECONDS)
    return int(broker_wall.timestamp() * 1000)


def _clock():
    observations = tuple(
        MT5BrokerClockObservation(
            symbol=symbol,
            raw_broker_time_msc=_raw_msc(RETRIEVED),
            retrieved_at_utc=RETRIEVED,
            bid=1.0 + index * 0.1,
            ask=1.0001 + index * 0.1,
        )
        for index, symbol in enumerate(("EURUSD", "GBPUSD", "USDJPY"))
    )
    evidence = build_mt5_broker_clock_evidence(
        "MetaQuotes-Demo",
        observations,
        generated_at=RETRIEVED,
    )
    assert evidence.passed
    return evidence


def _quote(
    symbol: str,
    *,
    age_seconds: float = 900.2,
    ask: float = 100.1,
) -> USCandidateQuoteSnapshotV2:
    clock = _clock()
    normalized = RETRIEVED - timedelta(seconds=age_seconds)
    return USCandidateQuoteSnapshotV2(
        symbol=symbol,
        raw_broker_time_msc=_raw_msc(normalized),
        broker_clock_offset_seconds=OFFSET_SECONDS,
        normalized_sampled_at_utc=clock.normalize_epoch_msc(_raw_msc(normalized)),
        retrieved_at_utc=RETRIEVED,
        bid=100.0,
        ask=ask,
        visible=True,
        tradable=True,
        clock_evidence_id=clock.evidence_id,
    )


def _raw_report(
    *,
    count: int = 30,
    visible_count: int | None = None,
    selection_id: str = "candidate-selection-test",
    wide_symbols: frozenset[str] = frozenset(),
) -> USCandidateQuoteProbeReportV2:
    symbols = _symbols(count)
    visible = count if visible_count is None else visible_count
    clock = _clock()
    quotes: list[USCandidateQuoteSnapshotV2] = []
    issues: list[USCandidateQuoteIssue] = []
    for index, symbol in enumerate(symbols):
        if index >= visible:
            issues.append(
                USCandidateQuoteIssue(symbol=symbol, reasons=("not_visible",))
            )
            continue
        quote = _quote(
            symbol,
            ask=102.0 if symbol in wide_symbols else 100.1,
        )
        quotes.append(
            USCandidateQuoteSnapshotV2(
                symbol=quote.symbol,
                raw_broker_time_msc=quote.raw_broker_time_msc,
                broker_clock_offset_seconds=quote.broker_clock_offset_seconds,
                normalized_sampled_at_utc=quote.normalized_sampled_at_utc,
                retrieved_at_utc=quote.retrieved_at_utc,
                bid=quote.bid,
                ask=quote.ask,
                visible=quote.visible,
                tradable=quote.tradable,
                clock_evidence_id=clock.evidence_id,
            )
        )
        issues.append(
            USCandidateQuoteIssue(symbol=symbol, reasons=("stale_quote",))
        )
    return USCandidateQuoteProbeReportV2(
        candidate_selection_id=selection_id,
        mt5_capability_probe_id="p0-probe",
        broker_server="MetaQuotes-Demo",
        policy=DEFAULT_US_CANDIDATE_QUOTE_PROBE_POLICY_V2,
        broker_clock_evidence=clock,
        requested_symbols=symbols,
        quotes=tuple(quotes),
        issues=tuple(issues),
        minimum_valid_quote_count=20,
        required_seed_symbols=SEEDS,
        generated_at=RETRIEVED,
    )


def _spec(
    symbol: str,
    *,
    visible: bool = True,
    tradable: bool = True,
) -> dict[str, object]:
    return {
        "spec_id": f"spec-{symbol}",
        "symbol": symbol,
        "path": f"Stocks\\{symbol}",
        "visible": visible,
        "tradable": tradable,
        "trade_mode": 4 if tradable else 0,
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


def _inventory(
    *,
    count: int = 30,
    probed_at: datetime | None = None,
    broker_server: str = "MetaQuotes-Demo",
) -> dict[str, object]:
    timestamp = probed_at or (RETRIEVED + timedelta(seconds=30))
    return {
        "probe_id": "inventory-probe-2",
        "probed_at": timestamp.isoformat(),
        "terminal": {
            "capability_id": "terminal-inventory-2",
            "broker_server": broker_server,
        },
        "symbols": [_spec(symbol) for symbol in _symbols(count)],
    }


def _finalize(
    raw: USCandidateQuoteProbeReportV2,
    *,
    candidate: dict[str, object] | None = None,
    inventory: dict[str, object] | None = None,
    operator_attested: bool = True,
):
    candidate_document = candidate or _candidate(
        selection_id=raw.candidate_selection_id
    )
    delayed = build_us_delayed_reference_quote_report(raw)
    return finalize_us_simulation_engineering_universe(
        candidate_document,
        raw.to_dict(),
        delayed.to_dict(),
        inventory or _inventory(count=len(raw.requested_symbols)),
        operator_attested=operator_attested,
        generated_at=RETRIEVED + timedelta(seconds=60),
    )


def test_canonical_simulation_universe_policy_round_trip() -> None:
    policy = CANONICAL_US_SIMULATION_UNIVERSE_FINALIZATION_POLICY
    assert policy.target_count == 25
    assert policy.minimum_count == 20
    assert policy.maximum_reference_spread_bps == 50.0
    parsed = us_simulation_universe_policy_from_document(policy.to_dict())
    assert parsed == policy
    assert validate_canonical_us_simulation_universe_policy(policy.to_dict()) == policy

    changed = USSimulationUniverseFinalizationPolicy(
        maximum_reference_spread_bps=51.0
    )
    with pytest.raises(ValueError, match="differs from canonical"):
        validate_canonical_us_simulation_universe_policy(changed.to_dict())


def test_simulation_finalizer_accepts_25_ranked_delayed_reference_names() -> None:
    raw = _raw_report()
    assert raw.ready_for_finalization is False
    assert raw.invalid_reason_counts["stale_quote"] == 30

    report = _finalize(raw)
    assert report.accepted_for_simulation_engineering
    assert report.simulation_universe_id is not None
    assert report.simulation_accepted_mapping_count == 25
    assert len(report.selected_symbols) == 25
    assert set(SEEDS).issubset(report.selected_symbols)
    assert report.inventory_age_seconds == pytest.approx(30.0)

    payload = report.to_dict()
    assert payload["simulation_engineering_universe_authority"] is True
    assert payload["live_market_data_authority"] is False
    assert payload["live_executable_spread_authority"] is False
    assert payload["stage_exit_authority"] is False
    assert payload["raw_live_current_v3_finalizer_unchanged"] is True
    assert "accepted" not in payload
    assert "universe_id" not in payload


def test_current_four_symbol_evidence_remains_blocked_without_partial_materialization() -> None:
    raw = _raw_report(visible_count=4)
    delayed = build_us_delayed_reference_quote_report(raw)
    assert delayed.valid_symbols == SEEDS
    assert delayed.blockers == (
        "simulation_quote_probe:insufficient_valid_quotes:4<20",
    )

    report = _finalize(raw)
    assert not report.accepted_for_simulation_engineering
    assert report.materialization is None
    assert report.selected_symbols == SEEDS
    assert (
        "simulation_universe:upstream:"
        "simulation_quote_probe:insufficient_valid_quotes:4<20"
    ) in report.blockers
    assert "simulation_universe:materialization_not_executed" in report.blockers


def test_reference_spread_is_diagnostic_filter_and_target_stays_frozen() -> None:
    symbols = _symbols()
    wide = frozenset(symbols[-6:])
    raw = _raw_report(wide_symbols=wide)
    report = _finalize(raw)

    assert not report.accepted_for_simulation_engineering
    assert len(report.selected_symbols) == 24
    assert set(report.excluded_by_reference_spread) == set(wide)
    assert any(
        item.startswith(
            "simulation_universe:insufficient_reference_spread_eligible:24<25"
        )
        for item in report.blockers
    )
    assert report.to_dict()["live_executable_spread_authority"] is False


def test_fresh_inventory_is_required_and_inventory_server_cannot_drift() -> None:
    raw = _raw_report()
    stale_inventory = _inventory(
        probed_at=RETRIEVED - timedelta(minutes=30)
    )
    stale = _finalize(raw, inventory=stale_inventory)
    assert not stale.accepted_for_simulation_engineering
    assert stale.materialization is None
    assert any("inventory_stale" in item for item in stale.blockers)

    other_server = _finalize(
        raw,
        inventory=_inventory(broker_server="Other-Demo"),
    )
    assert not other_server.accepted_for_simulation_engineering
    assert other_server.materialization is None
    assert (
        "simulation_universe:inventory_broker_server_mismatch"
        in other_server.blockers
    )


def test_operator_attestation_remains_required_for_simulation_mapping() -> None:
    raw = _raw_report()
    report = _finalize(raw, operator_attested=False)

    assert not report.accepted_for_simulation_engineering
    assert "simulation_universe:operator_attestation_required" in report.blockers
    assert report.materialization is not None
    assert report.simulation_accepted_mapping_count == 0


def test_cross_artifact_candidate_identity_mismatch_fails_closed() -> None:
    raw = _raw_report(selection_id="other-selection")
    with pytest.raises(ValueError, match="candidate selection"):
        _finalize(
            raw,
            candidate=_candidate(selection_id="candidate-selection-test"),
        )


def test_live_current_quotes_cannot_enter_simulation_universe() -> None:
    raw = _raw_report()
    clock = _clock()
    quotes: list[USCandidateQuoteSnapshotV2] = []
    for symbol in raw.requested_symbols:
        normalized = RETRIEVED - timedelta(seconds=0.2)
        quotes.append(
            USCandidateQuoteSnapshotV2(
                symbol=symbol,
                raw_broker_time_msc=_raw_msc(normalized),
                broker_clock_offset_seconds=OFFSET_SECONDS,
                normalized_sampled_at_utc=clock.normalize_epoch_msc(
                    _raw_msc(normalized)
                ),
                retrieved_at_utc=RETRIEVED,
                bid=100.0,
                ask=100.1,
                visible=True,
                tradable=True,
                clock_evidence_id=clock.evidence_id,
            )
        )
    live_raw = USCandidateQuoteProbeReportV2(
        candidate_selection_id=raw.candidate_selection_id,
        mt5_capability_probe_id=raw.mt5_capability_probe_id,
        broker_server=raw.broker_server,
        policy=raw.policy,
        broker_clock_evidence=clock,
        requested_symbols=raw.requested_symbols,
        quotes=tuple(quotes),
        issues=(),
        minimum_valid_quote_count=raw.minimum_valid_quote_count,
        required_seed_symbols=raw.required_seed_symbols,
        generated_at=raw.generated_at,
    )
    assert live_raw.ready_for_finalization

    report = _finalize(live_raw)
    assert not report.accepted_for_simulation_engineering
    assert report.materialization is None
    assert "simulation_universe:delayed_reference_not_ready" in report.blockers
