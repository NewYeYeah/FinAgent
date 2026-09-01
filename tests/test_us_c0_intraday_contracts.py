from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from finagent.data.capabilities import AdapterCapabilities
from finagent.data.ingestion import MarketRegion, ProviderCapabilities
from finagent.data.query import MarketDataField, MarketDataQuery, MarketDataView, SessionPolicy
from finagent.domain.corporate_actions import CorporateActionEvent, CorporateActionEventType
from finagent.domain.labels import (
    AvailabilityPolicy,
    LabelHorizonUnit,
    LabelMetric,
    LabelSpec,
    ResearchPriceBasis,
)
from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _xnys_calendar_fixture() -> TradingCalendarEvidence:
    return TradingCalendarEvidence(
        market_id="XNYS",
        timezone="America/New_York",
        source="us-c0-golden-fixture",
        source_revision="v1",
        sessions=(
            TradingSession(
                session_date=date(2026, 3, 6),
                open_at=_utc(2026, 3, 6, 14, 30),
                close_at=_utc(2026, 3, 6, 21, 0),
            ),
            TradingSession(
                session_date=date(2026, 3, 9),
                open_at=_utc(2026, 3, 9, 13, 30),
                close_at=_utc(2026, 3, 9, 20, 0),
            ),
        ),
    )


def _raw_query() -> MarketDataQuery:
    return MarketDataQuery(
        market_id="XNYS",
        assets=("MSFT", "AAPL"),
        start=_utc(2026, 3, 9, 13, 30),
        end=_utc(2026, 3, 9, 20, 0),
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.VOLUME, MarketDataField.CLOSE),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )


def test_trading_calendar_requires_aware_times_and_hashes_materialized_schedule() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        TradingSession(
            session_date=date(2026, 3, 9),
            open_at=datetime(2026, 3, 9, 9, 30),  # noqa: DTZ001 - intentional naive fixture
            close_at=datetime(2026, 3, 9, 16, 0),  # noqa: DTZ001 - intentional naive fixture
        )

    calendar = _xnys_calendar_fixture()
    changed = replace(calendar, source_revision="v2")

    assert calendar.calendar_id.startswith("trading-calendar-")
    assert calendar.calendar_id != changed.calendar_id
    assert calendar.to_dict()["coverage_start"] == "2026-03-06"


def test_xnys_dst_transition_preserves_local_open_close_clock() -> None:
    calendar = _xnys_calendar_fixture()
    new_york = ZoneInfo("America/New_York")
    before = calendar.require_session(date(2026, 3, 6))
    after = calendar.require_session(date(2026, 3, 9))

    assert before.open_at.astimezone(new_york).strftime("%H:%M") == "09:30"
    assert after.open_at.astimezone(new_york).strftime("%H:%M") == "09:30"
    assert before.close_at.astimezone(new_york).strftime("%H:%M") == "16:00"
    assert after.close_at.astimezone(new_york).strftime("%H:%M") == "16:00"
    assert before.open_at.utcoffset() == after.open_at.utcoffset()
    assert before.open_at.astimezone(new_york).utcoffset() != after.open_at.astimezone(new_york).utcoffset()


def test_materialized_calendar_represents_holiday_absence_and_half_day() -> None:
    holiday_window = TradingCalendarEvidence(
        market_id="XNYS",
        timezone="America/New_York",
        source="us-c0-golden-fixture",
        source_revision="v1",
        sessions=(
            TradingSession(
                session_date=date(2026, 7, 2),
                open_at=_utc(2026, 7, 2, 13, 30),
                close_at=_utc(2026, 7, 2, 20, 0),
            ),
            TradingSession(
                session_date=date(2026, 7, 6),
                open_at=_utc(2026, 7, 6, 13, 30),
                close_at=_utc(2026, 7, 6, 20, 0),
            ),
        ),
    )
    assert holiday_window.covers(date(2026, 7, 3))
    assert not holiday_window.is_session(date(2026, 7, 3))

    half_day = TradingCalendarEvidence(
        market_id="XNYS",
        timezone="America/New_York",
        source="us-c0-golden-fixture",
        source_revision="v1",
        sessions=(
            TradingSession(
                session_date=date(2026, 11, 27),
                open_at=_utc(2026, 11, 27, 14, 30),
                close_at=_utc(2026, 11, 27, 18, 0),
                is_half_day=True,
            ),
        ),
    )
    session = half_day.require_session(date(2026, 11, 27))
    assert session.regular_minutes == 210
    assert session.is_half_day is True


def test_label_spec_freezes_horizon_price_and_availability_semantics() -> None:
    spec = LabelSpec(
        metric=LabelMetric.SIMPLE_RETURN,
        horizon=60,
        horizon_unit=LabelHorizonUnit.TRADING_MINUTES,
        allow_cross_session=False,
        price_basis=ResearchPriceBasis.SPLIT_ADJUSTED,
    )
    same_length_bars = replace(spec, horizon_unit=LabelHorizonUnit.BARS)

    assert spec.label_id != same_length_bars.label_id
    assert spec.compute(100.0, 102.0) == pytest.approx(0.02)
    spec.validate_target_session(date(2026, 3, 9), date(2026, 3, 9))
    with pytest.raises(ValueError, match="crosses session boundary"):
        spec.validate_target_session(date(2026, 3, 9), date(2026, 3, 10))

    log_spec = replace(spec, metric=LabelMetric.LOG_RETURN)
    assert log_spec.compute(100.0, 102.0) == pytest.approx(math.log(1.02))


def test_trading_day_label_must_explicitly_allow_cross_session() -> None:
    with pytest.raises(ValueError, match="trading-day labels require"):
        LabelSpec(
            metric=LabelMetric.SIMPLE_RETURN,
            horizon=1,
            horizon_unit=LabelHorizonUnit.TRADING_DAYS,
            allow_cross_session=False,
            price_basis=ResearchPriceBasis.RAW,
        )


def test_corporate_action_event_keeps_split_and_cash_semantics_distinct() -> None:
    split = CorporateActionEvent(
        event_id="split-aapl-test",
        asset="AAPL",
        action_type=CorporateActionEventType.SPLIT,
        effective_at=_utc(2026, 8, 31, 13, 30),
        available_at=_utc(2026, 8, 1, 12, 0),
        source="fixture",
        source_revision="v1",
        split_ratio=4.0,
    )
    dividend = CorporateActionEvent(
        event_id="dividend-aapl-test",
        asset="AAPL",
        action_type=CorporateActionEventType.CASH_DIVIDEND,
        effective_at=_utc(2026, 11, 6, 14, 30),
        available_at=_utc(2026, 10, 20, 12, 0),
        source="fixture",
        source_revision="v1",
        cash_amount=0.25,
    )

    assert split.split_price_factor == pytest.approx(0.25)
    assert dividend.split_price_factor is None
    assert split.known_by(_utc(2026, 8, 2, 0, 0))
    assert not split.known_by(_utc(2026, 7, 31, 23, 59))
    assert split.evidence_id != dividend.evidence_id


def test_market_data_query_is_bounded_canonical_and_half_open() -> None:
    query = _raw_query()
    reordered = replace(
        query,
        assets=("AAPL", "MSFT"),
        fields=(MarketDataField.CLOSE, MarketDataField.VOLUME),
    )

    assert query.assets == ("AAPL", "MSFT")
    assert query.query_id == reordered.query_id
    payload = query.to_dict()
    assert payload["start_inclusive"] == "2026-03-09T13:30:00+00:00"
    assert payload["end_exclusive"] == "2026-03-09T20:00:00+00:00"

    with pytest.raises(ValueError, match="end must be later"):
        replace(query, end=query.start)
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(
            query,
            start=datetime(2026, 3, 9, 13, 30),  # noqa: DTZ001 - intentional naive fixture
        )


def test_adapter_capabilities_do_not_inherit_provider_claims() -> None:
    provider = ProviderCapabilities(
        provider="example",
        markets=frozenset({MarketRegion.US_EQUITY}),
        historical_minute=True,
        corporate_actions=True,
    )
    adapter = AdapterCapabilities(
        adapter_id="example-local-v1",
        provider=provider.provider,
        market_ids=frozenset({"XNYS"}),
        intervals=frozenset({BarInterval.MINUTE_1}),
        fields=frozenset(MarketDataField),
        session_policies=frozenset({SessionPolicy.REGULAR}),
        adjustment_policies=frozenset({ResearchPriceBasis.RAW}),
        availability_policies=frozenset({AvailabilityPolicy.AVAILABLE_AT}),
        supports_corporate_actions=False,
    )

    adapter.require(_raw_query())
    adjusted = replace(_raw_query(), adjustment_policy=ResearchPriceBasis.SPLIT_ADJUSTED)
    assert provider.historical_minute is True
    assert provider.corporate_actions is True
    assert adapter.supports_corporate_actions is False
    assert "adjustment_policy:split_adjusted" in adapter.gaps(adjusted)
    with pytest.raises(ValueError, match="cannot satisfy"):
        adapter.require(adjusted)


def test_market_data_view_remains_lazy_and_identity_bound() -> None:
    query = _raw_query()
    view = MarketDataView(
        query=query,
        adapter_id="hf-local-minute-v1",
        data_version="776328445b7ac6e7815ef3a483e9c8ded1eb6d56",
        estimated_rows=10_000,
    )
    changed = replace(view, data_version="other-revision")

    assert view.lazy is True
    assert view.view_id != changed.view_id
    with pytest.raises(ValueError, match="must remain lazy"):
        replace(view, lazy=False)
