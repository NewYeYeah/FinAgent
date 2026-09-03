from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from finagent.brokers.mt5.paper_replay import (
    MT5PaperExecutionPolicy,
    MT5PaperOrderCommand,
    MT5PaperReconciliationState,
    MT5PaperReplayBroker,
    reconcile_mt5_paper_projection,
)
from finagent.realtime.events import (
    OrderErrorEvent,
    OrderEvent,
    OrderLifecycleStatus,
    OrderSide,
    QuoteEvent,
    TradeEvent,
)
from finagent.realtime.projections import RealtimeProjector

NOW = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)


def _quote(
    *,
    symbol: str = "EURUSD",
    at: datetime = NOW,
    bid: float = 1.1000,
    ask: float = 1.1002,
    sequence: int = 0,
) -> QuoteEvent:
    return QuoteEvent(
        source="fixture.quote",
        source_event_id=f"{symbol}:{sequence}:{at.isoformat()}",
        event_time=at,
        received_at=at + timedelta(milliseconds=20),
        sequence=sequence,
        symbol=symbol,
        bid=bid,
        ask=ask,
        last=0.0,
    )


def _command(
    *,
    client_order_id: str = "client-1",
    symbol: str = "EURUSD",
    side: OrderSide = OrderSide.BUY,
    lots: float = 1.0,
    contract_size: float = 100_000.0,
    created_at: datetime = NOW,
) -> MT5PaperOrderCommand:
    return MT5PaperOrderCommand(
        client_order_id=client_order_id,
        symbol=symbol,
        side=side,
        lots=lots,
        contract_size=contract_size,
        created_at=created_at,
    )


def _projection(broker: MT5PaperReplayBroker) -> RealtimeProjector:
    projector = RealtimeProjector()
    projector.apply_all(broker.events())
    return projector


def test_submit_retry_is_idempotent_and_client_identity_conflict_fails() -> None:
    broker = MT5PaperReplayBroker(
        policy=MT5PaperExecutionPolicy(maximum_order_notional=200_000.0)
    )
    broker.observe_quote(_quote())
    command = _command()

    events = broker.submit(command, at=NOW)
    assert len(events) == 2
    assert isinstance(events[0], OrderEvent)
    assert events[0].status is OrderLifecycleStatus.SUBMITTED
    assert isinstance(events[1], OrderEvent)
    assert events[1].status is OrderLifecycleStatus.ACKNOWLEDGED
    assert broker.submit(command, at=NOW + timedelta(seconds=1)) == ()
    assert len(broker.snapshot().orders) == 1

    conflicting = replace(command, lots=0.5)
    with pytest.raises(ValueError, match="client_order_id conflict"):
        broker.submit(conflicting, at=NOW + timedelta(seconds=2))


def test_partial_fill_full_fill_deal_idempotency_and_reconciliation() -> None:
    broker = MT5PaperReplayBroker(
        policy=MT5PaperExecutionPolicy(maximum_order_notional=200_000.0)
    )
    broker.observe_quote(_quote())
    command = _command()
    broker.submit(command, at=NOW)

    first = broker.apply_fill(
        command.client_order_id,
        broker_deal_id="deal-1",
        lots=0.4,
        price=1.1002,
        at=NOW + timedelta(seconds=1),
        commission=1.0,
    )
    assert isinstance(first[0], TradeEvent)
    assert isinstance(first[1], OrderEvent)
    assert first[1].status is OrderLifecycleStatus.PARTIALLY_FILLED
    assert broker.apply_fill(
        command.client_order_id,
        broker_deal_id="deal-1",
        lots=0.4,
        price=1.1002,
        at=NOW + timedelta(seconds=2),
        commission=1.0,
    ) == ()

    second = broker.apply_fill(
        command.client_order_id,
        broker_deal_id="deal-2",
        lots=0.6,
        price=1.1003,
        at=NOW + timedelta(seconds=3),
        commission=1.5,
    )
    assert isinstance(second[1], OrderEvent)
    assert second[1].status is OrderLifecycleStatus.FILLED
    broker.publish_account_status(at=NOW + timedelta(seconds=4))

    snapshot = broker.snapshot()
    assert snapshot.positions == (("EURUSD", 1.0),)
    assert snapshot.broker_deal_ids == ("deal-1", "deal-2")

    projection = _projection(broker).snapshot()
    report = reconcile_mt5_paper_projection(
        projection,
        snapshot,
        generated_at=NOW + timedelta(seconds=5),
    )
    assert report.state is MT5PaperReconciliationState.CONSISTENT
    assert report.issues == ()


def test_stale_quote_daily_loss_and_kill_switch_fail_closed() -> None:
    policy = MT5PaperExecutionPolicy(
        maximum_order_notional=200_000.0,
        maximum_quote_age_seconds=30.0,
        maximum_daily_loss_fraction=0.05,
    )
    stale_broker = MT5PaperReplayBroker(policy=policy)
    stale_broker.observe_quote(_quote(at=NOW - timedelta(minutes=2)))
    stale_events = stale_broker.submit(_command(), at=NOW)
    assert isinstance(stale_events[0], OrderErrorEvent)
    assert stale_events[0].code == "QUOTE_GATE"
    assert stale_broker.order("client-1").status is OrderLifecycleStatus.REJECTED

    loss_broker = MT5PaperReplayBroker(policy=policy, session_start_equity=100_000.0)
    loss_broker.observe_quote(_quote())
    loss_broker.mark_equity(94_000.0, at=NOW)
    loss_events = loss_broker.submit(
        _command(client_order_id="loss-order"),
        at=NOW + timedelta(seconds=1),
    )
    assert isinstance(loss_events[0], OrderErrorEvent)
    assert loss_events[0].code == "DAILY_LOSS_LIMIT"

    kill_broker = MT5PaperReplayBroker(policy=policy)
    kill_broker.observe_quote(_quote())
    incident = kill_broker.trip_kill_switch(
        at=NOW,
        reason="operator emergency stop",
        actor="operator",
    )
    assert incident.incident_type == "KILL_SWITCH_TRIPPED"
    kill_events = kill_broker.submit(
        _command(client_order_id="kill-order"),
        at=NOW + timedelta(seconds=1),
    )
    assert isinstance(kill_events[0], OrderErrorEvent)
    assert kill_events[0].code == "KILL_SWITCH_HALTED"
    kill_broker.reset_kill_switch(
        at=NOW + timedelta(seconds=2),
        actor="operator",
        reason="fixture reset",
    )
    assert not kill_broker.kill_switch_halted
    assert len(kill_broker.incidents) == 2


def test_reject_cancel_and_expire_lifecycle() -> None:
    broker = MT5PaperReplayBroker(
        policy=MT5PaperExecutionPolicy(maximum_order_notional=200_000.0)
    )
    broker.observe_quote(_quote())

    reject_command = _command(client_order_id="reject-order")
    broker.submit(reject_command, at=NOW)
    rejected = broker.reject(
        reject_command.client_order_id,
        code="FIXTURE_REJECT",
        message="synthetic broker rejection",
        at=NOW + timedelta(seconds=1),
    )
    assert isinstance(rejected[0], OrderErrorEvent)
    assert isinstance(rejected[1], OrderEvent)
    assert rejected[1].status is OrderLifecycleStatus.REJECTED

    cancel_command = _command(client_order_id="cancel-order")
    broker.submit(cancel_command, at=NOW + timedelta(seconds=2))
    cancelled = broker.cancel(
        cancel_command.client_order_id,
        at=NOW + timedelta(seconds=3),
    )
    assert len(cancelled) == 1
    assert isinstance(cancelled[0], OrderEvent)
    assert cancelled[0].status is OrderLifecycleStatus.CANCELLED
    assert broker.cancel(
        cancel_command.client_order_id,
        at=NOW + timedelta(seconds=4),
    ) == ()

    expire_command = _command(client_order_id="expire-order")
    broker.submit(expire_command, at=NOW + timedelta(seconds=5))
    expired = broker.expire(
        expire_command.client_order_id,
        at=NOW + timedelta(seconds=6),
    )
    assert len(expired) == 1
    assert isinstance(expired[0], OrderEvent)
    assert expired[0].status is OrderLifecycleStatus.EXPIRED


def test_reconciliation_reports_unknown_and_drift() -> None:
    broker = MT5PaperReplayBroker(
        policy=MT5PaperExecutionPolicy(maximum_order_notional=200_000.0)
    )
    broker.observe_quote(_quote())
    broker.submit(_command(), at=NOW)
    broker.publish_account_status(at=NOW + timedelta(seconds=1))
    projection = _projection(broker).snapshot()

    unknown = reconcile_mt5_paper_projection(
        projection,
        None,
        generated_at=NOW + timedelta(seconds=2),
    )
    assert unknown.state is MT5PaperReconciliationState.UNKNOWN
    assert unknown.issues == ("broker_snapshot:unavailable",)

    snapshot = broker.snapshot()
    drifted = replace(snapshot, positions=(("EURUSD", 1.0),))
    drift = reconcile_mt5_paper_projection(
        projection,
        drifted,
        generated_at=NOW + timedelta(seconds=3),
    )
    assert drift.state is MT5PaperReconciliationState.DRIFT
    assert "positions:symbol_set_mismatch" in drift.issues


def test_append_only_journal_recovery_reproduces_state_and_retry(tmp_path) -> None:
    policy = MT5PaperExecutionPolicy(maximum_order_notional=200_000.0)
    broker = MT5PaperReplayBroker(policy=policy)
    broker.observe_quote(_quote())
    command = _command()
    broker.submit(command, at=NOW)
    broker.apply_fill(
        command.client_order_id,
        broker_deal_id="deal-recovery",
        lots=1.0,
        price=1.1002,
        at=NOW + timedelta(seconds=1),
    )
    broker.mark_equity(99_500.0, at=NOW + timedelta(seconds=2))
    broker.trip_kill_switch(
        at=NOW + timedelta(seconds=3),
        actor="system",
        reason="fixture incident",
    )
    before = broker.snapshot()

    journal = tmp_path / "paper-replay.jsonl"
    broker.write_journal(journal)
    recovered = MT5PaperReplayBroker.recover_from_journal(
        journal,
        policy=policy,
        session_start_equity=100_000.0,
    )
    after = recovered.snapshot()

    assert after.snapshot_id == before.snapshot_id
    assert tuple(event.event_id for event in recovered.events()) == before.event_ids
    assert recovered.submit(command, at=NOW + timedelta(seconds=4)) == ()
    assert recovered.kill_switch_halted


def test_gross_notional_guard_uses_current_exposure() -> None:
    policy = MT5PaperExecutionPolicy(
        maximum_order_notional=200_000.0,
        maximum_gross_notional=150_000.0,
    )
    broker = MT5PaperReplayBroker(policy=policy)
    broker.observe_quote(_quote(bid=1.0, ask=1.0))
    first = _command(client_order_id="first", contract_size=100_000.0)
    broker.submit(first, at=NOW)
    broker.apply_fill(
        first.client_order_id,
        broker_deal_id="gross-1",
        lots=1.0,
        price=1.0,
        at=NOW + timedelta(seconds=1),
    )

    second = _command(
        client_order_id="second",
        lots=1.0,
        contract_size=100_000.0,
    )
    rejected = broker.submit(second, at=NOW + timedelta(seconds=2))
    assert isinstance(rejected[0], OrderErrorEvent)
    assert rejected[0].code == "GROSS_NOTIONAL_LIMIT"


def test_authority_flags_remain_false() -> None:
    policy = MT5PaperExecutionPolicy()
    policy_doc = policy.to_dict()
    assert policy_doc["paper_only"] is True
    assert policy_doc["order_send_authority"] is False
    assert policy_doc["live_capital_authority"] is False
    assert policy_doc["stage_exit_authority"] is False

    broker = MT5PaperReplayBroker(policy=policy)
    snapshot_doc = broker.snapshot().to_dict()
    assert snapshot_doc["paper_only"] is True
    assert snapshot_doc["order_send_authority"] is False
    assert snapshot_doc["live_capital_authority"] is False
    assert snapshot_doc["stage_exit_authority"] is False
