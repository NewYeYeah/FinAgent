from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from finagent.realtime.events import (
    AccountStatusEvent,
    BarEvent,
    CanonicalRealtimeEvent,
    ConnectionEvent,
    ConnectionStatus,
    MarketSessionStatus,
    MarketStatusEvent,
    OrderErrorEvent,
    OrderEvent,
    OrderLifecycleStatus,
    OrderSide,
    QuoteEvent,
    TradeEvent,
)
from finagent.realtime.projections import RealtimeProjector, rebuild_projection
from finagent.realtime.replay import ReplayGateway, ReplayScenario
from finagent.realtime.serialization import realtime_event_from_dict

START = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)


def _base_events() -> tuple[CanonicalRealtimeEvent, ...]:
    return (
        QuoteEvent(
            source="fixture.market",
            source_event_id="quote-000",
            event_time=START,
            received_at=START + timedelta(seconds=1),
            sequence=0,
            symbol="US500.CFD",
            bid=100.0,
            ask=100.1,
            last=100.05,
        ),
        QuoteEvent(
            source="fixture.market",
            source_event_id="quote-001",
            event_time=START + timedelta(seconds=1),
            received_at=START + timedelta(seconds=2),
            sequence=1,
            symbol="US500.CFD",
            bid=100.2,
            ask=100.3,
            last=100.25,
        ),
        BarEvent(
            source="fixture.bar",
            source_event_id="bar-000",
            event_time=START + timedelta(minutes=1),
            received_at=START + timedelta(minutes=1, seconds=1),
            sequence=0,
            symbol="US500.CFD",
            interval_seconds=60,
            open=100.0,
            high=100.4,
            low=99.9,
            close=100.25,
            volume=1000.0,
            complete=True,
        ),
        MarketStatusEvent(
            source="fixture.market-status",
            source_event_id="market-000",
            event_time=START,
            received_at=START + timedelta(milliseconds=100),
            sequence=0,
            market="XNYS",
            status=MarketSessionStatus.OPEN,
        ),
        ConnectionEvent(
            source="fixture.connection",
            source_event_id="connection-000",
            event_time=START,
            received_at=START + timedelta(milliseconds=100),
            sequence=0,
            connection_id="fixture-mt5",
            status=ConnectionStatus.CONNECTED,
            reason="fixture connected",
        ),
        OrderEvent(
            source="fixture.execution",
            source_event_id="order-000",
            event_time=START + timedelta(minutes=2),
            received_at=START + timedelta(minutes=2, milliseconds=100),
            sequence=0,
            client_order_id="client-1",
            broker_order_id="broker-1",
            symbol="US500.CFD",
            side=OrderSide.BUY,
            requested_lots=1.0,
            filled_lots=0.0,
            status=OrderLifecycleStatus.ACKNOWLEDGED,
        ),
        TradeEvent(
            source="fixture.execution",
            source_event_id="trade-000",
            event_time=START + timedelta(minutes=2, seconds=1),
            received_at=START + timedelta(minutes=2, seconds=1, milliseconds=100),
            sequence=1,
            client_order_id="client-1",
            broker_order_id="broker-1",
            broker_deal_id="deal-1",
            symbol="US500.CFD",
            side=OrderSide.BUY,
            lots=1.0,
            price=100.3,
            commission=0.1,
        ),
        OrderEvent(
            source="fixture.execution",
            source_event_id="order-001",
            event_time=START + timedelta(minutes=2, seconds=2),
            received_at=START + timedelta(minutes=2, seconds=2, milliseconds=100),
            sequence=2,
            client_order_id="client-1",
            broker_order_id="broker-1",
            symbol="US500.CFD",
            side=OrderSide.BUY,
            requested_lots=1.0,
            filled_lots=1.0,
            status=OrderLifecycleStatus.FILLED,
        ),
        AccountStatusEvent(
            source="fixture.account",
            source_event_id="account-000",
            event_time=START + timedelta(minutes=2, seconds=3),
            received_at=START + timedelta(minutes=2, seconds=3, milliseconds=100),
            sequence=0,
            account_id="paper-account",
            balance=100_000.0,
            equity=100_010.0,
            margin_used=1000.0,
            free_margin=99_010.0,
            currency="USD",
        ),
        OrderErrorEvent(
            source="fixture.errors",
            source_event_id="error-000",
            event_time=START + timedelta(minutes=3),
            received_at=START + timedelta(minutes=3, milliseconds=100),
            sequence=0,
            client_order_id="client-2",
            symbol="US500.CFD",
            code="FIXTURE_REJECT",
            message="deterministic replay rejection",
            retryable=False,
        ),
    )


def test_event_identity_separates_source_time_from_receive_time() -> None:
    quote = _base_events()[0]
    assert quote.event_time == START
    assert quote.received_at == START + timedelta(seconds=1)
    assert quote.latency_seconds == pytest.approx(1.0)
    assert quote.event_id.startswith("realtime-event-")
    assert quote.source_key == "fixture.market:quote-000"


def test_all_event_types_round_trip_through_strict_json_parser() -> None:
    for event in _base_events():
        encoded = json.loads(json.dumps(event.to_dict()))
        rebuilt = realtime_event_from_dict(encoded)
        assert type(rebuilt) is type(event)
        assert rebuilt.to_dict() == event.to_dict()
        assert rebuilt.event_id == event.event_id


def test_serialization_rejects_tampered_event_identity() -> None:
    document = _base_events()[0].to_dict()
    payload = dict(document["payload"])  # type: ignore[arg-type]
    payload["bid"] = 99.9
    document["payload"] = payload
    with pytest.raises(ValueError, match="content identity"):
        realtime_event_from_dict(document)


def test_duplicate_replay_is_semantically_idempotent_and_diagnostic() -> None:
    gateway = ReplayGateway(_base_events())
    normal = rebuild_projection(gateway.build(ReplayScenario.NORMAL).events)
    duplicate = rebuild_projection(gateway.build(ReplayScenario.DUPLICATE).events)

    assert duplicate.semantic_state_id == normal.semantic_state_id
    assert duplicate.applied_event_count == normal.applied_event_count
    assert duplicate.duplicate_event_count == 1
    assert duplicate.snapshot_id != normal.snapshot_id


def test_out_of_order_replay_does_not_regress_latest_quote() -> None:
    gateway = ReplayGateway(_base_events())
    normal = rebuild_projection(gateway.build(ReplayScenario.NORMAL).events)
    out_of_order = rebuild_projection(gateway.build(ReplayScenario.OUT_OF_ORDER).events)

    assert out_of_order.semantic_state_id == normal.semantic_state_id
    assert out_of_order.out_of_order_event_count == 1
    quote_payload = dict(out_of_order.quotes)["US500.CFD"]
    quote = dict(quote_payload["payload"])  # type: ignore[arg-type]
    assert quote["bid"] == pytest.approx(100.2)


def test_stale_quote_replay_counts_latency_without_regressing_semantic_state() -> None:
    gateway = ReplayGateway(_base_events())
    normal = rebuild_projection(gateway.build(ReplayScenario.NORMAL).events)
    stale = rebuild_projection(
        gateway.build(ReplayScenario.STALE_QUOTE, stale_delay_seconds=120).events
    )

    assert stale.stale_event_count == 1
    assert stale.semantic_state_id == normal.semantic_state_id


def test_disconnect_reconnect_replay_finishes_connected() -> None:
    batch = ReplayGateway(_base_events()).build(ReplayScenario.DISCONNECT_RECONNECT)
    snapshot = rebuild_projection(batch.events)

    connections = dict(snapshot.connections)
    assert "replay-connection" in connections
    replay_connection = dict(connections["replay-connection"]["payload"])  # type: ignore[arg-type]
    assert replay_connection["status"] == ConnectionStatus.CONNECTED.value
    assert batch.to_dict()["execution_authority"] is False


def test_source_event_id_content_conflict_fails_closed() -> None:
    quote = _base_events()[0]
    conflict = replace(quote, bid=99.0)
    projector = RealtimeProjector()
    assert projector.apply(quote)
    with pytest.raises(ValueError, match="source_event_id conflict"):
        projector.apply(conflict)


def test_trade_duplicate_never_double_counts_portfolio_lots() -> None:
    events = _base_events()
    trade = next(event for event in events if isinstance(event, TradeEvent))
    projector = RealtimeProjector()
    projector.apply_all(events)
    before = projector.snapshot()
    assert dict(before.portfolio_lots)["US500.CFD"] == pytest.approx(1.0)

    assert not projector.apply(trade)
    after = projector.snapshot()
    assert dict(after.portfolio_lots)["US500.CFD"] == pytest.approx(1.0)
    assert after.duplicate_event_count == before.duplicate_event_count + 1


def test_restart_reconstruction_from_persisted_json_has_identical_state_hash() -> None:
    events = _base_events()
    before = rebuild_projection(events)
    persisted = [json.loads(json.dumps(event.to_dict())) for event in events]
    restored = tuple(realtime_event_from_dict(document) for document in persisted)
    after = rebuild_projection(restored)

    assert after.semantic_state_id == before.semantic_state_id
    assert after.snapshot_id == before.snapshot_id
    assert after.event_log_digest == before.event_log_digest


def test_replay_batches_are_content_addressed_and_non_authoritative() -> None:
    gateway = ReplayGateway(_base_events())
    first = gateway.build(ReplayScenario.NORMAL)
    second = gateway.build(ReplayScenario.NORMAL)
    assert first.batch_id == second.batch_id
    assert first.to_dict() == second.to_dict()
    payload = first.to_dict()
    assert payload["replay_only"] is True
    assert payload["market_data_authority"] is False
    assert payload["execution_authority"] is False
    assert payload["status_authority"] is False
    assert payload["stage_exit_authority"] is False
