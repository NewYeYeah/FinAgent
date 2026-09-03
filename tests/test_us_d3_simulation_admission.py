from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from finagent.brokers.mt5.clock import (
    MT5BrokerClockObservation,
    build_mt5_broker_clock_evidence,
)
from finagent.brokers.mt5.continuous_quote_smoke import (
    MT5ContinuousQuoteSmokePolicy,
    build_mt5_continuous_quote_smoke_report,
)
from finagent.brokers.mt5.simulation_all_day_preflight import (
    CANONICAL_MT5_SIMULATION_ALL_DAY_PREFLIGHT_POLICY,
    build_mt5_simulation_all_day_preflight_report,
)
from finagent.data.us_candidate_quotes_v2 import (
    DEFAULT_US_CANDIDATE_QUOTE_PROBE_POLICY_V2,
    USCandidateQuoteIssue,
    USCandidateQuoteProbeReportV2,
    USCandidateQuoteSnapshotV2,
)
from finagent.data.us_delayed_reference_quotes import build_us_delayed_reference_quote_report
from finagent.data.us_minute.reconciliation import (
    MinuteReferenceReconciliationPolicy,
    MinuteReferenceReconciliationReport,
    MinuteReferenceSymbolCheck,
)
from finagent.data.us_minute.simulation_certification import (
    CANONICAL_US_SIMULATION_D3_CERTIFICATION_POLICY,
    USSimulationD3Review,
    USSimulationD3ReviewDecision,
    build_us_simulation_d3_certification,
    validate_us_simulation_universe_document,
)
from finagent.data.us_simulation_universe import finalize_us_simulation_engineering_universe

NOW = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
OFFSET = 3 * 60 * 60
SEEDS = ("AMD", "INTC", "MSFT", "NVDA")
CONTINUOUS = ("EURUSD", "GBPUSD", "USDJPY")
SOURCE_REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"
INVENTORY_ID = "us-minute-inventory-c2cbf682b456f97eb613ed65"
CALENDAR_ID = "trading-calendar-03a9c29f566d6634aedbbbdc"


def _raw_msc(normalized: datetime) -> int:
    return int((normalized + timedelta(seconds=OFFSET)).timestamp() * 1000)


def _clock(server: str = "MetaQuotes-Demo"):
    observations = tuple(
        MT5BrokerClockObservation(
            symbol=symbol,
            raw_broker_time_msc=_raw_msc(NOW),
            retrieved_at_utc=NOW,
            bid=1.0 + index * 0.1,
            ask=1.0001 + index * 0.1,
        )
        for index, symbol in enumerate(CONTINUOUS)
    )
    evidence = build_mt5_broker_clock_evidence(server, observations, generated_at=NOW)
    assert evidence.passed
    return evidence


def _continuous_smoke(
    *,
    server: str = "MetaQuotes-Demo",
    symbols: tuple[str, ...] = CONTINUOUS,
):
    clock = _clock(server)
    inventory = [
        {"name": symbol, "visible": True, "trade_mode": 4} for symbol in symbols
    ]
    ticks = {
        symbol: {
            "time_msc": _raw_msc(NOW - timedelta(seconds=1)),
            "bid": 1.1,
            "ask": 1.1001,
        }
        for symbol in symbols
    }
    retrieved = {symbol: NOW for symbol in symbols}
    return build_mt5_continuous_quote_smoke_report(
        server,
        symbols,
        inventory,
        ticks,
        retrieved,
        clock,
        policy=MT5ContinuousQuoteSmokePolicy(
            minimum_symbol_count=min(3, len(symbols)),
            maximum_quote_age_seconds=60,
            maximum_future_quote_skew_seconds=5,
        ),
        generated_at=NOW,
    )


def test_all_day_preflight_uses_continuous_products_without_us_authority() -> None:
    report = build_mt5_simulation_all_day_preflight_report(_continuous_smoke())
    assert report.passed
    assert report.passed_symbols == CONTINUOUS
    payload = report.to_dict()
    assert payload["engineering_fixture_authority"] is True
    assert payload["us_research_universe_authority"] is False
    assert payload["us_d3_certification_authority"] is False
    assert payload["stage_exit_authority"] is False


def test_all_day_preflight_rejects_wrong_server_or_incomplete_symbol_fixture() -> None:
    wrong_server = build_mt5_simulation_all_day_preflight_report(
        _continuous_smoke(server="Other-Demo")
    )
    assert not wrong_server.passed
    assert "simulation_all_day:broker_server_mismatch" in wrong_server.blockers

    incomplete = build_mt5_simulation_all_day_preflight_report(
        _continuous_smoke(symbols=("EURUSD", "GBPUSD"))
    )
    assert not incomplete.passed
    assert "simulation_all_day:required_symbol_set_mismatch" in incomplete.blockers


def _symbols(count: int = 25) -> tuple[str, ...]:
    return SEEDS + tuple(f"S{index:02d}" for index in range(count - len(SEEDS)))


def _candidate() -> dict[str, object]:
    symbols = _symbols()
    return {
        "selection_id": "candidate-selection-test",
        "ready_for_spread_probe": True,
        "spread_probe_symbols": list(symbols),
        "mt5_probe_id": "p0-probe",
        "broker_server": "MetaQuotes-Demo",
        "policy": {"minimum_selected_count": 20, "seed_symbols": list(SEEDS)},
        "candidates": [
            {"rank": index, "research_symbol": symbol}
            for index, symbol in enumerate(symbols, start=1)
        ],
    }


def _raw_quote_report() -> USCandidateQuoteProbeReportV2:
    clock = _clock()
    quotes: list[USCandidateQuoteSnapshotV2] = []
    issues: list[USCandidateQuoteIssue] = []
    for symbol in _symbols():
        normalized = NOW - timedelta(seconds=900.2)
        quotes.append(
            USCandidateQuoteSnapshotV2(
                symbol=symbol,
                raw_broker_time_msc=_raw_msc(normalized),
                broker_clock_offset_seconds=OFFSET,
                normalized_sampled_at_utc=clock.normalize_epoch_msc(_raw_msc(normalized)),
                retrieved_at_utc=NOW,
                bid=100.0,
                ask=100.1,
                visible=True,
                tradable=True,
                clock_evidence_id=clock.evidence_id,
            )
        )
        issues.append(USCandidateQuoteIssue(symbol=symbol, reasons=("stale_quote",)))
    return USCandidateQuoteProbeReportV2(
        candidate_selection_id="candidate-selection-test",
        mt5_capability_probe_id="p0-probe",
        broker_server="MetaQuotes-Demo",
        policy=DEFAULT_US_CANDIDATE_QUOTE_PROBE_POLICY_V2,
        broker_clock_evidence=clock,
        requested_symbols=_symbols(),
        quotes=tuple(quotes),
        issues=tuple(issues),
        minimum_valid_quote_count=20,
        required_seed_symbols=SEEDS,
        generated_at=NOW,
    )


def _spec(symbol: str) -> dict[str, object]:
    return {
        "spec_id": f"spec-{symbol}",
        "symbol": symbol,
        "path": f"Stocks\\{symbol}",
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


def _inventory() -> dict[str, object]:
    return {
        "probe_id": "simulation-inventory",
        "probed_at": (NOW + timedelta(seconds=30)).isoformat(),
        "terminal": {
            "capability_id": "terminal-2",
            "broker_server": "MetaQuotes-Demo",
        },
        "symbols": [_spec(symbol) for symbol in _symbols()],
    }


def _simulation_universe() -> dict[str, object]:
    raw = _raw_quote_report()
    delayed = build_us_delayed_reference_quote_report(raw)
    assert delayed.ready_for_simulation_reference
    report = finalize_us_simulation_engineering_universe(
        _candidate(),
        raw.to_dict(),
        delayed.to_dict(),
        _inventory(),
        operator_attested=True,
        generated_at=NOW + timedelta(seconds=60),
    )
    assert report.accepted_for_simulation_engineering
    return report.to_dict()


def _source() -> dict[str, object]:
    return {
        "admission": {
            "admission_id": "us-minute-local-admission-test",
            "source_identity": {"revision": SOURCE_REVISION},
            "source_authority_status": "reference_only",
            "inventory_id": INVENTORY_ID,
        },
        "certification": {"passed": True},
        "local_research_admitted": True,
    }


def _d1() -> dict[str, object]:
    return {
        "report_id": "us-d1-test",
        "passed": True,
        "blockers": [],
        "replay_match": True,
        "asset_count": 25,
        "partition_count": 3,
    }


def _d2() -> dict[str, object]:
    return {
        "report_id": "us-d2-test",
        "passed": True,
        "blockers": [],
        "calendar_id": CALENDAR_ID,
        "scenarios": [
            {"name": name, "labels": {"other_unavailable_count": 0}}
            for name in ("half_day", "pre_dst", "post_dst")
        ],
        "action_authority": {
            "same_session_raw_allowed": True,
            "cross_session_raw_denied": True,
            "split_adjusted_denied": True,
            "total_return_adjusted_denied": True,
        },
    }


def _reconciliation(*, outside_symbol: bool = False) -> dict[str, object]:
    policy = MinuteReferenceReconciliationPolicy(
        start=datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
        end=datetime(2026, 3, 9, 20, 0, tzinfo=UTC),
        required_symbol_count=4,
        minimum_rows_per_symbol=100,
        minimum_aligned_overlap_ratio=0.8,
        maximum_abs_offset_minutes=360,
    )
    symbols = list(SEEDS)
    if outside_symbol:
        symbols[-1] = "OUTSIDE"
    checks = tuple(
        MinuteReferenceSymbolCheck(
            research_symbol=symbol,
            broker_symbol=symbol,
            research_row_count=200,
            broker_row_count=200,
            exact_overlap_count=180,
            best_broker_to_research_offset_minutes=0,
            aligned_overlap_count=180,
            aligned_overlap_ratio=0.9,
            median_close_relative_difference=0.001,
            maximum_close_relative_difference=0.005,
            research_volume_sum=1000.0,
            broker_tick_volume_sum=1100.0,
            broker_real_volume_sum=None,
        )
        for symbol in symbols
    )
    report = MinuteReferenceReconciliationReport(
        policy=policy,
        source_revision=SOURCE_REVISION,
        source_data_version="minute-data-version-test",
        calendar_id=CALENDAR_ID,
        mt5_probe_id="p0-probe",
        broker_server="MetaQuotes-Demo",
        symbol_checks=checks,
        retrieved_at=NOW,
    )
    assert report.passed
    return report.to_dict()


def test_simulation_d3_bridge_certifies_without_consuming_all_day_fixture() -> None:
    universe_document = _simulation_universe()
    binding = validate_us_simulation_universe_document(universe_document)
    assert binding.accepted
    assert binding.accepted_mapping_count == 25

    report = build_us_simulation_d3_certification(
        source_document=_source(),
        d1_document=_d1(),
        d2_document=_d2(),
        simulation_universe_document=universe_document,
        reconciliation_document=_reconciliation(),
    )
    assert report.certified
    assert report.supports_us_b0_progression if hasattr(report, "supports_us_b0_progression") else True
    payload = report.to_dict()
    assert payload["supports_us_b0_progression"] is True
    assert payload["all_day_preflight_in_certification_denominator"] is False
    assert payload["live_market_data_authority"] is False
    assert payload["live_executable_spread_authority"] is False
    assert "all_day_products:engineering_preflight_only_not_us_research_evidence" in payload["limitations"]


def test_simulation_d3_bridge_rejects_reconciliation_outside_us_universe() -> None:
    report = build_us_simulation_d3_certification(
        source_document=_source(),
        d1_document=_d1(),
        d2_document=_d2(),
        simulation_universe_document=_simulation_universe(),
        reconciliation_document=_reconciliation(outside_symbol=True),
    )
    assert not report.certified
    assert "reconciliation:symbol_outside_simulation_universe" in report.blockers


def test_simulation_universe_live_authority_tamper_fails_closed() -> None:
    document = _simulation_universe()
    document["live_market_data_authority"] = True
    with pytest.raises(ValueError, match="live_market_data_authority"):
        validate_us_simulation_universe_document(document)


def test_independent_review_cannot_upgrade_rejected_machine_certification() -> None:
    rejected = build_us_simulation_d3_certification(
        source_document=_source(),
        d1_document=_d1(),
        d2_document=_d2(),
        simulation_universe_document=_simulation_universe(),
        reconciliation_document=_reconciliation(outside_symbol=True),
    )
    with pytest.raises(ValueError, match="cannot upgrade"):
        USSimulationD3Review(
            certification=rejected,
            reviewer_id="reviewer-1",
            reviewed_at=NOW,
            decision=USSimulationD3ReviewDecision.ACCEPT,
            notes="must fail",
        )


def test_independent_review_accepts_passing_cert_but_keeps_stage_authority_false() -> None:
    certification = build_us_simulation_d3_certification(
        source_document=_source(),
        d1_document=_d1(),
        d2_document=_d2(),
        simulation_universe_document=_simulation_universe(),
        reconciliation_document=_reconciliation(),
    )
    review = USSimulationD3Review(
        certification=certification,
        reviewer_id="reviewer-1",
        reviewed_at=NOW,
        decision=USSimulationD3ReviewDecision.ACCEPT,
        notes="simulation-limited evidence accepted",
    )
    payload = review.to_dict()
    assert review.accepted
    assert payload["supports_us_b0_progression"] is True
    assert payload["status_authority"] is False
    assert payload["stage_exit_authority"] is False
    assert payload["live_market_data_authority"] is False
