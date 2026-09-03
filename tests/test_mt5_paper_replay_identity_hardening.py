from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from finagent.brokers.mt5.paper_replay import (
    MT5PaperExecutionPolicy,
    MT5PaperOrderCommand,
    MT5PaperReplayBroker,
)
from finagent.realtime.events import OrderSide, QuoteEvent

NOW = datetime(2026, 9, 3, 8, 30, tzinfo=UTC)


def _quote() -> QuoteEvent:
    return QuoteEvent(
        source="fixture.quote",
        source_event_id="identity-hardening-quote",
        event_time=NOW,
        received_at=NOW + timedelta(milliseconds=10),
        sequence=0,
        symbol="EURUSD",
        bid=1.0,
        ask=1.0,
        last=0.0,
    )


def _command(client_order_id: str, *, contract_size: float = 100_000.0) -> MT5PaperOrderCommand:
    return MT5PaperOrderCommand(
        client_order_id=client_order_id,
        symbol="EURUSD",
        side=OrderSide.BUY,
        lots=1.0,
        contract_size=contract_size,
        created_at=NOW,
    )


def test_exact_final_deal_retry_is_idempotent_after_order_is_filled() -> None:
    broker = MT5PaperReplayBroker(
        policy=MT5PaperExecutionPolicy(maximum_order_notional=200_000.0)
    )
    broker.observe_quote(_quote())
    command = _command("final-fill")
    broker.submit(command, at=NOW)
    broker.apply_fill(
        command.client_order_id,
        broker_deal_id="deal-final",
        lots=1.0,
        price=1.0,
        commission=1.0,
        at=NOW + timedelta(seconds=1),
    )
    event_count = len(broker.events())

    assert broker.apply_fill(
        command.client_order_id,
        broker_deal_id="deal-final",
        lots=1.0,
        price=1.0,
        commission=1.0,
        at=NOW + timedelta(seconds=2),
    ) == ()
    assert len(broker.events()) == event_count

    with pytest.raises(ValueError, match="broker_deal_id conflict"):
        broker.apply_fill(
            command.client_order_id,
            broker_deal_id="deal-final",
            lots=1.0,
            price=1.01,
            commission=1.0,
            at=NOW + timedelta(seconds=3),
        )


def test_contract_size_conflict_fails_before_command_journal_mutation(tmp_path) -> None:
    broker = MT5PaperReplayBroker(
        policy=MT5PaperExecutionPolicy(maximum_order_notional=200_000.0)
    )
    broker.observe_quote(_quote())
    first = _command("first-contract")
    broker.submit(first, at=NOW)

    conflicting = _command("conflicting-contract", contract_size=50_000.0)
    with pytest.raises(ValueError, match="contract_size changed"):
        broker.submit(conflicting, at=NOW + timedelta(seconds=1))

    assert tuple(item.client_order_id for item in broker.snapshot().orders) == (
        "first-contract",
    )
    journal = tmp_path / "identity-hardening.jsonl"
    broker.write_journal(journal)
    text = journal.read_text(encoding="utf-8")
    assert "first-contract" in text
    assert "conflicting-contract" not in text
