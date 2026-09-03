from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb

from finagent.data.minute_store import (
    DuckDBParquetMinuteStore,
    fetch_plan_rows,
    manifest_from_directory,
)
from finagent.data.minute_transform import (
    CalendarSessionizedMinuteStore,
    SessionResampledMinuteStore,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.realtime import (
    AlgorithmRunner,
    AlgorithmRunReport,
    BarEvent,
    DatabaseReplaySource,
    FeedTimingClass,
    FeedTimingProfile,
    MarketDataSubscription,
    QuoteEvent,
    RealtimeEventKind,
    RealtimeProjector,
    ReplayPacingMode,
    StrategyFreshnessBudget,
    StreamingResampledBar,
    StreamingResearchUpdate,
    USBaselineStreamingAlgorithm,
)
from finagent.research.us_baselines import canonical_us_baseline_denominator

BASE = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
SYMBOLS = ("AAA", "BBB")


def _calendar(*, minutes: int = 150) -> TradingCalendarEvidence:
    return TradingCalendarEvidence(
        market_id="XNYS",
        timezone="America/New_York",
        source="fixture-calendar",
        source_revision="fixture-calendar-v1",
        sessions=(
            TradingSession(
                session_date=date(2026, 1, 5),
                open_at=BASE,
                close_at=BASE + timedelta(minutes=minutes),
                is_half_day=False,
            ),
        ),
        regular_session_minutes=minutes,
    )


def _fixture_store(
    root: Path,
    *,
    minutes: int = 150,
    missing: tuple[str, int] | None = None,
) -> DuckDBParquetMinuteStore:
    data_dir = root / "minute"
    data_dir.mkdir(parents=True)
    output = data_dir / "ohlcv_2026-01.parquet"
    rows: list[tuple[object, ...]] = []
    for minute in range(minutes):
        for symbol_index, symbol in enumerate(SYMBOLS):
            if missing == (symbol, minute):
                continue
            base_price = 100.0 + 100.0 * symbol_index + 0.2 * minute
            rows.append(
                (
                    BASE + timedelta(minutes=minute),
                    base_price,
                    base_price + 1.0,
                    base_price - 0.5,
                    base_price + 0.25,
                    1000.0 + 10.0 * minute + 100.0 * symbol_index,
                    symbol,
                )
            )
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE bars (
                timestamp TIMESTAMPTZ,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                ticker VARCHAR
            )
            """
        )
        connection.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        connection.execute(f"COPY bars TO '{output.as_posix()}' (FORMAT PARQUET)")
    finally:
        connection.close()
    return DuckDBParquetMinuteStore(
        manifest_from_directory(
            data_dir,
            source_id="fixture-us-minute",
            source_revision="fixture-revision",
            cleaning_identity="fixture-cleaning",
            inventory_id="fixture-inventory",
        )
    )


def _subscription(
    *,
    minutes: int = 150,
    pacing_mode: ReplayPacingMode = ReplayPacingMode.FAST,
) -> MarketDataSubscription:
    return MarketDataSubscription(
        symbols=SYMBOLS,
        event_kinds=(RealtimeEventKind.BAR,),
        start=BASE + timedelta(minutes=1),
        end=BASE + timedelta(minutes=minutes + 1),
        interval_seconds=60,
        pacing_mode=pacing_mode,
        speed=60.0 if pacing_mode is ReplayPacingMode.ACCELERATED else 1.0,
    )


def _updates(report: AlgorithmRunReport) -> tuple[StreamingResearchUpdate, ...]:
    return tuple(
        item for item in report.outputs if isinstance(item, StreamingResearchUpdate)
    )


def _flatten_resampled(
    updates: tuple[StreamingResearchUpdate, ...],
    interval_seconds: int,
) -> tuple[StreamingResampledBar, ...]:
    return tuple(
        item
        for update in updates
        for item in update.resampled_bars
        if item.bar.interval_seconds == interval_seconds
    )


def test_streaming_resample_matches_accepted_us_d2_batch_semantics(tmp_path: Path) -> None:
    store = _fixture_store(tmp_path)
    calendar = _calendar()
    algorithm = USBaselineStreamingAlgorithm(calendar, required_symbols=SYMBOLS)
    report = asyncio.run(
        AlgorithmRunner().run(
            DatabaseReplaySource(store),
            _subscription(),
            algorithm,
            freshness_budget=StrategyFreshnessBudget(
                maximum_source_delay_seconds=60.0,
                maximum_event_age_seconds=120.0,
                allow_replay=True,
            ),
        )
    )
    updates = _updates(report)
    streamed_5m = _flatten_resampled(updates, 5 * 60)
    streamed_15m = _flatten_resampled(updates, 15 * 60)
    streamed_30m = _flatten_resampled(updates, 30 * 60)
    assert len(streamed_5m) == 60
    assert len(streamed_15m) == 20
    assert len(streamed_30m) == 10

    batch_store = SessionResampledMinuteStore(CalendarSessionizedMinuteStore(store, calendar))
    batch_query = MarketDataQuery(
        market_id="XNYS",
        assets=SYMBOLS,
        start=BASE,
        end=BASE + timedelta(minutes=151),
        interval=BarInterval.MINUTE_15,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )
    batch_plan, evidence = batch_store.plan(batch_query)
    batch_rows = fetch_plan_rows(batch_plan, limit=1000)
    assert len(batch_rows) == 20
    assert streamed_15m[0].resampling_spec_id == evidence.spec_id

    streamed = {
        (item.bar.symbol, item.bar.event_time): item
        for item in streamed_15m
    }
    for row in batch_rows:
        key = (str(row["research_asset_id"]), row["event_time"])
        item = streamed[key]
        assert item.available_at == row["available_at"]
        assert item.bar.open == row["open"]
        assert item.bar.high == row["high"]
        assert item.bar.low == row["low"]
        assert item.bar.close == row["close"]
        assert item.bar.volume == row["volume"]
        assert item.observed_minute_count == row["observed_minute_count"]
        assert item.expected_minute_count == row["expected_minute_count"]
        assert item.coverage_ratio == row["coverage_ratio"]
        assert item.bar.complete is row["is_complete"]
        assert item.bar.event_time == row["event_time"]


def test_streaming_feature_engine_reuses_b0_denominator_and_full_symbol_barrier(
    tmp_path: Path,
) -> None:
    store = _fixture_store(tmp_path)
    algorithm = USBaselineStreamingAlgorithm(_calendar(), required_symbols=SYMBOLS)
    report = asyncio.run(
        AlgorithmRunner().run(
            DatabaseReplaySource(store),
            _subscription(),
            algorithm,
            freshness_budget=StrategyFreshnessBudget(
                maximum_source_delay_seconds=60.0,
                maximum_event_age_seconds=120.0,
                allow_replay=True,
            ),
        )
    )
    updates = _updates(report)
    feature_snapshots = tuple(
        item for update in updates for item in update.feature_snapshots
    )
    cross_sections = tuple(
        item for update in updates for item in update.cross_section_snapshots
    )
    denominator = canonical_us_baseline_denominator()

    assert len(feature_snapshots) == 20
    assert len(cross_sections) == 10
    assert all(item.denominator_id == denominator.denominator_id for item in feature_snapshots)
    assert all(item.required_symbols == SYMBOLS for item in cross_sections)
    assert all(len(item.feature_snapshots) == 2 for item in cross_sections)
    assert len(cross_sections[-1].fully_available_feature_ids) == len(denominator.candidates)
    assert set(cross_sections[-1].fully_available_feature_ids) == {
        item.feature_id for item in denominator.candidates
    }


def test_missing_minute_is_preserved_as_incomplete_streaming_bucket(tmp_path: Path) -> None:
    store = _fixture_store(tmp_path, minutes=20, missing=("AAA", 7))
    calendar = _calendar(minutes=30)
    algorithm = USBaselineStreamingAlgorithm(calendar, required_symbols=SYMBOLS)
    report = asyncio.run(
        AlgorithmRunner().run(
            DatabaseReplaySource(store),
            _subscription(minutes=20),
            algorithm,
            freshness_budget=StrategyFreshnessBudget(
                maximum_source_delay_seconds=60.0,
                maximum_event_age_seconds=120.0,
                allow_replay=True,
            ),
        )
    )
    streamed_5m = _flatten_resampled(_updates(report), 5 * 60)
    incomplete = tuple(
        item
        for item in streamed_5m
        if item.bar.symbol == "AAA" and item.bar.event_time == BASE + timedelta(minutes=5)
    )
    assert len(incomplete) == 1
    assert incomplete[0].observed_minute_count == 4
    assert incomplete[0].expected_minute_count == 5
    assert incomplete[0].coverage_ratio == 0.8
    assert incomplete[0].bar.complete is False


def test_fast_and_accelerated_pacing_preserve_streaming_feature_identities(
    tmp_path: Path,
) -> None:
    store = _fixture_store(tmp_path, minutes=30)
    calendar = _calendar(minutes=30)

    async def no_sleep(_: float) -> None:
        return None

    async def run(mode: ReplayPacingMode) -> tuple[str, ...]:
        source = DatabaseReplaySource(store, sleeper=no_sleep)
        report = await AlgorithmRunner().run(
            source,
            _subscription(minutes=30, pacing_mode=mode),
            USBaselineStreamingAlgorithm(calendar, required_symbols=SYMBOLS),
            freshness_budget=StrategyFreshnessBudget(
                maximum_source_delay_seconds=60.0,
                maximum_event_age_seconds=120.0,
                allow_replay=True,
            ),
        )
        return tuple(item.update_id for item in _updates(report))

    assert asyncio.run(run(ReplayPacingMode.FAST)) == asyncio.run(
        run(ReplayPacingMode.ACCELERATED)
    )


def test_delayed_source_remains_visible_but_cannot_update_feature_algorithm(
    tmp_path: Path,
) -> None:
    store = _fixture_store(tmp_path, minutes=30)
    source = DatabaseReplaySource(
        store,
        timing_profile=FeedTimingProfile(
            source_id="fixture.delayed.us",
            timing_class=FeedTimingClass.DELAYED,
            progressing=True,
            observed_delay_seconds=900.0,
            freshness_policy_id="fixture-delay-policy",
        ),
    )
    algorithm = USBaselineStreamingAlgorithm(_calendar(minutes=30), required_symbols=SYMBOLS)
    report = asyncio.run(
        AlgorithmRunner().run(
            source,
            _subscription(minutes=30),
            algorithm,
            freshness_budget=StrategyFreshnessBudget(
                maximum_source_delay_seconds=60.0,
                maximum_event_age_seconds=120.0,
                allow_delayed=True,
            ),
        )
    )
    assert report.processed_event_count == 60
    assert report.algorithm_event_count == 0
    assert report.blocked_event_count == 60
    assert report.output_count == 0
    assert report.final_projection.bars
    assert all(
        "freshness:source_delay_exceeded" in decision.reasons
        for decision in report.blocked_decisions
    )
    assert all("source:not_progressing" not in decision.reasons for decision in report.blocked_decisions)


def test_fx_quote_can_share_algorithm_runner_without_creating_us_ohlcv_features() -> None:
    algorithm = USBaselineStreamingAlgorithm(_calendar(minutes=30), required_symbols=SYMBOLS)
    quote = QuoteEvent(
        source="fixture.fx",
        source_event_id="eurusd-1",
        event_time=BASE,
        received_at=BASE + timedelta(milliseconds=20),
        sequence=0,
        symbol="EURUSD",
        bid=1.1000,
        ask=1.1002,
        last=1.1001,
    )
    assert algorithm.on_event(quote, RealtimeProjector().snapshot()) is None


def test_outside_regular_session_bar_does_not_enter_streaming_features() -> None:
    algorithm = USBaselineStreamingAlgorithm(_calendar(minutes=30), required_symbols=SYMBOLS)
    event = BarEvent(
        source="fixture",
        source_event_id="preopen",
        event_time=BASE - timedelta(minutes=1),
        received_at=BASE,
        sequence=0,
        symbol="AAA",
        interval_seconds=60,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1000.0,
        complete=True,
    )
    assert algorithm.resampler.on_event(event) == ()
