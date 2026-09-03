from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from finagent.data.minute_store.manifest import manifest_from_directory
from finagent.data.minute_store.parquet_store import DuckDBParquetMinuteStore
from finagent.realtime.algorithm import AlgorithmRunner
from finagent.realtime.database_replay import DatabaseReplaySource
from finagent.realtime.events import (
    BarEvent,
    CanonicalRealtimeEvent,
    QuoteEvent,
    RealtimeEventKind,
)
from finagent.realtime.mt5_source import MT5RealtimeSource
from finagent.realtime.sources import (
    FeedTimingClass,
    FeedTimingProfile,
    MarketDataSource,
    MarketDataSubscription,
    ReplayPacingMode,
    StrategyFreshnessBudget,
)

BASE = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)


def _store(tmp_path: Path) -> DuckDBParquetMinuteStore:
    data_dir = tmp_path / "minute"
    data_dir.mkdir()
    output = data_dir / "ohlcv_2026-01.parquet"
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
        rows = [
            (BASE, 100.0, 101.0, 99.0, 100.5, 1000.0, "AAA"),
            (BASE, 200.0, 201.0, 199.0, 200.5, 2000.0, "BBB"),
            (BASE + timedelta(minutes=1), 100.5, 102.0, 100.0, 101.5, 1100.0, "AAA"),
            (BASE + timedelta(minutes=1), 200.5, 202.0, 200.0, 201.5, 2100.0, "BBB"),
            (BASE + timedelta(minutes=2), 101.5, 103.0, 101.0, 102.5, 1200.0, "AAA"),
            (BASE + timedelta(minutes=2), 201.5, 203.0, 201.0, 202.5, 2200.0, "BBB"),
        ]
        connection.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        connection.execute(f"COPY bars TO '{output.as_posix()}' (FORMAT PARQUET)")
    finally:
        connection.close()
    manifest = manifest_from_directory(
        data_dir,
        source_id="fixture-us-minute",
        source_revision="fixture-revision",
        cleaning_identity="fixture-cleaning",
        inventory_id="fixture-inventory",
    )
    return DuckDBParquetMinuteStore(manifest)


async def _collect(source: MarketDataSource, subscription: MarketDataSubscription) -> list[CanonicalRealtimeEvent]:
    events: list[CanonicalRealtimeEvent] = []
    async for event in source.subscribe(subscription):
        events.append(event)
    return events


def _bar_subscription(
    *,
    symbols: tuple[str, ...] = ("AAA", "BBB"),
    mode: ReplayPacingMode = ReplayPacingMode.FAST,
    speed: float = 1.0,
    maximum_events: int | None = None,
) -> MarketDataSubscription:
    return MarketDataSubscription(
        symbols=symbols,
        event_kinds=(RealtimeEventKind.BAR,),
        start=BASE + timedelta(minutes=1),
        end=BASE + timedelta(minutes=4),
        interval_seconds=60,
        pacing_mode=mode,
        speed=speed,
        maximum_events=maximum_events,
    )


def test_database_replay_preserves_market_time_and_available_at(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = DatabaseReplaySource(store)
    subscription = _bar_subscription()

    first = asyncio.run(_collect(source, subscription))
    second = asyncio.run(_collect(DatabaseReplaySource(store), subscription))

    assert len(first) == 6
    assert all(isinstance(item, BarEvent) for item in first)
    assert [item.symbol for item in first[:2]] == ["AAA", "BBB"]
    first_bar = first[0]
    assert first_bar.event_time == BASE
    assert first_bar.received_at == BASE + timedelta(minutes=1)
    assert first_bar.latency_seconds == 60.0
    assert first_bar.complete is True
    assert tuple(item.event_id for item in first) == tuple(item.event_id for item in second)


def test_accelerated_and_step_pacing_do_not_change_event_identity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    accelerated = DatabaseReplaySource(store, sleeper=fake_sleep)
    accelerated_subscription = _bar_subscription(
        symbols=("AAA",),
        mode=ReplayPacingMode.ACCELERATED,
        speed=60.0,
        maximum_events=2,
    )
    accelerated_events = asyncio.run(_collect(accelerated, accelerated_subscription))
    assert sleeps == [1.0]

    step = DatabaseReplaySource(store)
    step_subscription = _bar_subscription(
        symbols=("AAA",),
        mode=ReplayPacingMode.STEP,
        maximum_events=2,
    )

    async def run_step() -> list[CanonicalRealtimeEvent]:
        task = asyncio.create_task(_collect(step, step_subscription))
        await asyncio.sleep(0)
        assert not task.done()
        step.advance(2)
        return await task

    step_events = asyncio.run(run_step())
    assert tuple(item.event_id for item in accelerated_events) == tuple(
        item.event_id for item in step_events
    )


def test_progressing_delayed_profile_is_distinct_from_frozen_source(tmp_path: Path) -> None:
    store = _store(tmp_path)
    delayed_profile = FeedTimingProfile(
        source_id="fixture.delayed.us",
        timing_class=FeedTimingClass.DELAYED,
        progressing=True,
        observed_delay_seconds=900.0,
        freshness_policy_id="fixture-delay-policy",
    )
    delayed = DatabaseReplaySource(store, timing_profile=delayed_profile)
    subscription = _bar_subscription(symbols=("AAA",), maximum_events=1)
    event = asyncio.run(_collect(delayed, subscription))[0]
    assert event.latency_seconds == 960.0

    budget = StrategyFreshnessBudget(
        maximum_source_delay_seconds=60.0,
        maximum_event_age_seconds=120.0,
        allow_delayed=True,
    )
    decision = budget.assess(delayed_profile, event)
    assert decision.allowed is False
    assert "freshness:source_delay_exceeded" in decision.reasons
    assert "freshness:event_age_exceeded" in decision.reasons
    assert "source:not_progressing" not in decision.reasons

    frozen_profile = FeedTimingProfile(
        source_id="fixture.frozen.us",
        timing_class=FeedTimingClass.DELAYED,
        progressing=False,
        observed_delay_seconds=900.0,
        freshness_policy_id="fixture-delay-policy",
    )
    frozen_decision = budget.assess(frozen_profile, event)
    assert "source:not_progressing" in frozen_decision.reasons


def test_algorithm_runner_gates_actions_but_keeps_projection_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    delayed_profile = FeedTimingProfile(
        source_id="fixture.delayed.us",
        timing_class=FeedTimingClass.DELAYED,
        progressing=True,
        observed_delay_seconds=900.0,
        freshness_policy_id="fixture-delay-policy",
    )
    source = DatabaseReplaySource(store, timing_profile=delayed_profile)
    subscription = _bar_subscription(symbols=("AAA",), maximum_events=2)

    class CloseRecorder:
        def __init__(self) -> None:
            self.calls = 0

        def on_event(self, event: CanonicalRealtimeEvent, state: object) -> object:
            del state
            self.calls += 1
            assert isinstance(event, BarEvent)
            return event.close

    algorithm = CloseRecorder()
    report = asyncio.run(
        AlgorithmRunner().run(
            source,
            subscription,
            algorithm,
            freshness_budget=StrategyFreshnessBudget(
                maximum_source_delay_seconds=60.0,
                maximum_event_age_seconds=120.0,
                allow_delayed=True,
            ),
        )
    )
    assert report.processed_event_count == 2
    assert report.algorithm_event_count == 0
    assert report.blocked_event_count == 2
    assert report.output_count == 0
    assert report.final_projection.applied_event_count == 2
    assert len(report.final_projection.bars) == 1
    assert algorithm.calls == 0


class _FakeMT5Client:
    package_version = "fixture"
    timeframe_m1 = 1
    copy_ticks_all = 0

    def __init__(self) -> None:
        self.initialized = False
        self.shutdown_called = False
        self.counter = 0

    def initialize(self) -> None:
        self.initialized = True

    def shutdown(self) -> None:
        self.shutdown_called = True
        self.initialized = False

    def version(self) -> object:
        return ()

    def terminal_info(self) -> object:
        return object()

    def account_info(self) -> object:
        return object()

    def symbols_get(self, group: str = "") -> object:
        del group
        return ()

    def symbol_info_tick(self, symbol: str) -> object:
        assert self.initialized
        self.counter += 1
        return {"symbol": symbol, "counter": self.counter}

    def copy_rates_range(self, symbol: str, date_from: object, date_to: object) -> object:
        del symbol, date_from, date_to
        return ()

    def copy_ticks_range(self, symbol: str, date_from: object, date_to: object) -> object:
        del symbol, date_from, date_to
        return ()


class _FakeQuoteAdapter:
    def quote_event(self, symbol: str, tick: object, *, received_at: datetime) -> QuoteEvent:
        assert isinstance(tick, dict)
        counter = int(tick["counter"])
        return QuoteEvent(
            source="mt5.fixture.quote",
            source_event_id=f"{symbol}:{counter}",
            event_time=received_at - timedelta(milliseconds=20),
            received_at=received_at,
            sequence=counter,
            symbol=symbol,
            bid=1.0 + counter / 10000.0,
            ask=1.0002 + counter / 10000.0,
            last=0.0,
        )


def test_mt5_live_source_uses_same_source_and_runner_contract() -> None:
    client = _FakeMT5Client()
    adapter = _FakeQuoteAdapter()
    clock_values = iter(
        (
            datetime(2026, 9, 3, 10, 0, 0, tzinfo=UTC),
            datetime(2026, 9, 3, 10, 0, 1, tzinfo=UTC),
        )
    )

    async def no_sleep(seconds: float) -> None:
        assert seconds == 0.5

    source = MT5RealtimeSource(
        client,
        adapter,
        timing_profile=FeedTimingProfile(
            source_id="mt5.fx.fixture",
            timing_class=FeedTimingClass.CURRENT,
            progressing=True,
            observed_delay_seconds=0.02,
            freshness_policy_id="fx-current-fixture",
        ),
        poll_interval_seconds=0.5,
        sleeper=no_sleep,
        clock=lambda: next(clock_values),
    )
    assert isinstance(source, MarketDataSource)
    subscription = MarketDataSubscription(
        symbols=("EURUSD",),
        event_kinds=(RealtimeEventKind.QUOTE,),
        maximum_events=2,
    )

    class QuoteRecorder:
        def on_event(self, event: CanonicalRealtimeEvent, state: object) -> object:
            del state
            assert isinstance(event, QuoteEvent)
            return event.bid

    report = asyncio.run(
        AlgorithmRunner().run(
            source,
            subscription,
            QuoteRecorder(),
            freshness_budget=StrategyFreshnessBudget(
                maximum_source_delay_seconds=1.0,
                maximum_event_age_seconds=1.0,
                allow_replay=False,
            ),
        )
    )
    assert report.processed_event_count == 2
    assert report.algorithm_event_count == 2
    assert report.blocked_event_count == 0
    assert report.output_count == 2
    assert client.shutdown_called is True


def test_algorithm_module_contains_no_provider_specific_imports() -> None:
    path = Path("src/finagent/realtime/algorithm.py")
    text = path.read_text(encoding="utf-8").lower()
    assert "duckdb" not in text
    assert "metatrader5" not in text
    assert "database_replay" not in text
    assert "mt5_source" not in text
