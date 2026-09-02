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
    CANONICAL_US_SIMULATION_QUOTE_TIMING_POLICY,
    build_us_delayed_reference_quote_report,
    us_delayed_reference_quote_report_from_document,
    us_simulation_quote_timing_policy_from_document,
    validate_canonical_us_simulation_quote_timing_policy,
)


RETRIEVED = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
OFFSET_SECONDS = 3 * 60 * 60


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
    assert evidence.inferred_offset_seconds == OFFSET_SECONDS
    return evidence


def _quote(symbol: str, *, age_seconds: float):
    clock = _clock()
    normalized = RETRIEVED - timedelta(seconds=age_seconds)
    return USCandidateQuoteSnapshotV2(
        symbol=symbol,
        raw_broker_time_msc=_raw_msc(normalized),
        broker_clock_offset_seconds=OFFSET_SECONDS,
        normalized_sampled_at_utc=clock.normalize_epoch_msc(_raw_msc(normalized)),
        retrieved_at_utc=RETRIEVED,
        bid=100.0,
        ask=100.1,
        visible=True,
        tradable=True,
        clock_evidence_id=clock.evidence_id,
    )


def _raw_report(
    *,
    quote: USCandidateQuoteSnapshotV2 | None,
    issues: tuple[USCandidateQuoteIssue, ...],
) -> USCandidateQuoteProbeReportV2:
    clock = _clock()
    quotes = () if quote is None else (quote,)
    if quote is not None:
        quote = USCandidateQuoteSnapshotV2(
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
        quotes = (quote,)
    return USCandidateQuoteProbeReportV2(
        candidate_selection_id="candidate-selection-test",
        mt5_capability_probe_id="mt5-probe-test",
        broker_server="MetaQuotes-Demo",
        policy=DEFAULT_US_CANDIDATE_QUOTE_PROBE_POLICY_V2,
        broker_clock_evidence=clock,
        requested_symbols=("AMD",),
        quotes=quotes,
        issues=issues,
        minimum_valid_quote_count=1,
        required_seed_symbols=("AMD",),
        generated_at=RETRIEVED,
    )


def test_canonical_simulation_policy_round_trip() -> None:
    policy = CANONICAL_US_SIMULATION_QUOTE_TIMING_POLICY
    assert policy.expected_source_delay_seconds == 900
    assert policy.broker_account_required is False
    parsed = us_simulation_quote_timing_policy_from_document(policy.to_dict())
    assert parsed == policy
    assert validate_canonical_us_simulation_quote_timing_policy(policy.to_dict()) == policy


def test_delayed_quote_preserves_raw_live_failure_but_passes_simulation_reference() -> None:
    quote = _quote("AMD", age_seconds=900.2)
    raw = _raw_report(
        quote=quote,
        issues=(USCandidateQuoteIssue(symbol="AMD", reasons=("stale_quote",)),),
    )
    assert raw.ready_for_finalization is False
    assert raw.invalid_reason_counts == {"stale_quote": 1}

    delayed = build_us_delayed_reference_quote_report(raw)
    assert delayed.ready_for_simulation_reference is True
    assert delayed.valid_symbols == ("AMD",)
    assessment = delayed.assessments[0]
    assert assessment.raw_issue_reasons == ("stale_quote",)
    assert assessment.eligible_for_delay_reinterpretation is True
    assert assessment.anchor_age_seconds == pytest.approx(0.2, abs=0.002)
    assert assessment.valid_for_simulation_reference is True
    assert delayed.to_dict()["live_market_data_authority"] is False
    assert delayed.to_dict()["live_executable_spread_authority"] is False


def test_live_current_quote_is_not_silently_admitted_under_delayed_policy() -> None:
    quote = _quote("AMD", age_seconds=0.2)
    raw = _raw_report(quote=quote, issues=())
    assert raw.ready_for_finalization is True

    delayed = build_us_delayed_reference_quote_report(raw)
    assert delayed.ready_for_simulation_reference is False
    assessment = delayed.assessments[0]
    assert assessment.valid_for_simulation_reference is False
    assert "quote_ahead_of_delayed_reference_anchor" in assessment.reasons


def test_quote_too_old_for_delayed_anchor_fails() -> None:
    quote = _quote("AMD", age_seconds=970.0)
    raw = _raw_report(
        quote=quote,
        issues=(USCandidateQuoteIssue(symbol="AMD", reasons=("stale_quote",)),),
    )
    delayed = build_us_delayed_reference_quote_report(raw)
    assert delayed.ready_for_simulation_reference is False
    assert "quote_behind_delayed_reference_anchor" in delayed.assessments[0].reasons


def test_non_delay_raw_issue_cannot_be_reinterpreted() -> None:
    raw = _raw_report(
        quote=None,
        issues=(USCandidateQuoteIssue(symbol="AMD", reasons=("not_visible",)),),
    )
    delayed = build_us_delayed_reference_quote_report(raw)
    assessment = delayed.assessments[0]
    assert assessment.raw_quote_present is False
    assert assessment.eligible_for_delay_reinterpretation is False
    assert assessment.valid_for_simulation_reference is False
    assert "raw_issue:not_visible" in assessment.reasons
    assert delayed.blockers == (
        "simulation_quote_probe:insufficient_valid_quotes:0<1",
        "simulation_quote_probe:seed_quote_invalid:AMD",
    )


def test_delayed_report_parser_rejects_tampering() -> None:
    raw = _raw_report(
        quote=_quote("AMD", age_seconds=900.2),
        issues=(USCandidateQuoteIssue(symbol="AMD", reasons=("stale_quote",)),),
    )
    report = build_us_delayed_reference_quote_report(raw)
    document = report.to_dict()
    assert us_delayed_reference_quote_report_from_document(document).to_dict() == document

    tampered = dict(document)
    tampered["report_id"] = "us-delayed-reference-quote-report-tampered"
    with pytest.raises(ValueError, match="report_id"):
        us_delayed_reference_quote_report_from_document(tampered)


def test_simulation_policy_is_bound_to_metaquotes_demo() -> None:
    quote = _quote("AMD", age_seconds=900.2)
    raw = _raw_report(
        quote=quote,
        issues=(USCandidateQuoteIssue(symbol="AMD", reasons=("stale_quote",)),),
    )
    raw_other_server = USCandidateQuoteProbeReportV2(
        candidate_selection_id=raw.candidate_selection_id,
        mt5_capability_probe_id=raw.mt5_capability_probe_id,
        broker_server="Other-Demo",
        policy=raw.policy,
        broker_clock_evidence=build_mt5_broker_clock_evidence(
            "Other-Demo",
            tuple(
                MT5BrokerClockObservation(
                    symbol=item.symbol,
                    raw_broker_time_msc=item.raw_broker_time_msc,
                    retrieved_at_utc=item.retrieved_at_utc,
                    bid=item.bid,
                    ask=item.ask,
                )
                for item in raw.broker_clock_evidence.observations
            ),
            generated_at=RETRIEVED,
        ),
        requested_symbols=raw.requested_symbols,
        quotes=raw.quotes,
        issues=raw.issues,
        minimum_valid_quote_count=raw.minimum_valid_quote_count,
        required_seed_symbols=raw.required_seed_symbols,
        generated_at=raw.generated_at,
    )
    delayed = build_us_delayed_reference_quote_report(raw_other_server)
    assert any("broker_server_mismatch" in item for item in delayed.blockers)
