from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from finagent.brokers.mt5.paper_replay import (
    MT5PaperExecutionPolicy,
    MT5PaperOrderCommand,
    MT5PaperReconciliationState,
    MT5PaperReplayBroker,
    reconcile_mt5_paper_projection,
)
from finagent.realtime.events import OrderSide, QuoteEvent
from finagent.realtime.projections import RealtimeProjector

ANCHOR = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic MT5-E1/O1 replay-first PAPER lifecycle validation. "
            "No MetaTrader5 package, broker mutation, order_send, PAPER account, or live "
            "capital authority is required or granted."
        )
    )
    parser.add_argument("--output", type=Path)
    return parser


def _quote() -> QuoteEvent:
    return QuoteEvent(
        source="fixture.quote",
        source_event_id="eurusd-fixture-1",
        event_time=ANCHOR,
        received_at=ANCHOR + timedelta(milliseconds=10),
        sequence=0,
        symbol="EURUSD",
        bid=1.1000,
        ask=1.1002,
        last=0.0,
    )


def _run() -> dict[str, object]:
    policy = MT5PaperExecutionPolicy(
        maximum_order_notional=200_000.0,
        maximum_gross_notional=300_000.0,
    )
    broker = MT5PaperReplayBroker(policy=policy, session_start_equity=100_000.0)
    broker.observe_quote(_quote())
    command = MT5PaperOrderCommand(
        client_order_id="smoke-order-1",
        symbol="EURUSD",
        side=OrderSide.BUY,
        lots=1.0,
        contract_size=100_000.0,
        created_at=ANCHOR,
    )
    submit_events = broker.submit(command, at=ANCHOR)
    broker.apply_fill(
        command.client_order_id,
        broker_deal_id="smoke-deal-1",
        lots=0.4,
        price=1.1002,
        at=ANCHOR + timedelta(seconds=1),
        commission=1.0,
    )
    broker.apply_fill(
        command.client_order_id,
        broker_deal_id="smoke-deal-2",
        lots=0.6,
        price=1.1003,
        at=ANCHOR + timedelta(seconds=2),
        commission=1.5,
    )
    broker.mark_equity(99_750.0, at=ANCHOR + timedelta(seconds=3))

    projector = RealtimeProjector()
    projector.apply_all(broker.events())
    projection = projector.snapshot()
    snapshot = broker.snapshot()
    reconciliation = reconcile_mt5_paper_projection(
        projection,
        snapshot,
        generated_at=ANCHOR + timedelta(seconds=4),
    )
    if reconciliation.state is not MT5PaperReconciliationState.CONSISTENT:
        raise RuntimeError(
            "fixture reconciliation failed: " + ", ".join(reconciliation.issues)
        )

    with tempfile.TemporaryDirectory() as directory:
        journal = Path(directory) / "mt5-paper-replay.jsonl"
        broker.write_journal(journal)
        recovered = MT5PaperReplayBroker.recover_from_journal(
            journal,
            policy=policy,
            session_start_equity=100_000.0,
        )
        recovered_snapshot = recovered.snapshot()
        recovery_match = recovered_snapshot.snapshot_id == snapshot.snapshot_id
        retry_event_count = len(
            recovered.submit(command, at=ANCHOR + timedelta(seconds=5))
        )

    stale_broker = MT5PaperReplayBroker(policy=policy)
    stale_broker.observe_quote(
        QuoteEvent(
            source="fixture.quote",
            source_event_id="stale-eurusd",
            event_time=ANCHOR - timedelta(minutes=5),
            received_at=ANCHOR - timedelta(minutes=5),
            sequence=0,
            symbol="EURUSD",
            bid=1.1000,
            ask=1.1002,
            last=0.0,
        )
    )
    stale_command = MT5PaperOrderCommand(
        client_order_id="stale-order",
        symbol="EURUSD",
        side=OrderSide.BUY,
        lots=0.1,
        contract_size=100_000.0,
        created_at=ANCHOR,
    )
    stale_events = stale_broker.submit(stale_command, at=ANCHOR)

    kill_broker = MT5PaperReplayBroker(policy=policy)
    kill_broker.observe_quote(_quote())
    kill_broker.trip_kill_switch(
        at=ANCHOR,
        actor="fixture",
        reason="deterministic kill switch validation",
    )
    kill_command = MT5PaperOrderCommand(
        client_order_id="kill-order",
        symbol="EURUSD",
        side=OrderSide.BUY,
        lots=0.1,
        contract_size=100_000.0,
        created_at=ANCHOR,
    )
    kill_events = kill_broker.submit(kill_command, at=ANCHOR)

    return {
        "schema_version": "finagent.mt5-paper-replay-smoke.v1",
        "policy_id": policy.policy_id,
        "submit_event_count": len(submit_events),
        "broker_event_count": len(broker.events()),
        "broker_snapshot_id": snapshot.snapshot_id,
        "projection_semantic_state_id": projection.semantic_state_id,
        "reconciliation_report_id": reconciliation.report_id,
        "reconciliation_state": reconciliation.state.value,
        "recovery_snapshot_match": recovery_match,
        "idempotent_retry_event_count": retry_event_count,
        "stale_quote_rejected": bool(stale_events),
        "kill_switch_rejected": bool(kill_events),
        "paper_only": True,
        "order_send_authority": False,
        "broker_account_authority": False,
        "live_market_data_authority": False,
        "execution_authority": False,
        "live_capital_authority": False,
        "status_authority": False,
        "stage_exit_authority": False,
    }


def main() -> int:
    args = build_parser().parse_args()
    result = _run()
    if not result["recovery_snapshot_match"]:
        raise SystemExit("recovery snapshot identity mismatch")
    if result["idempotent_retry_event_count"] != 0:
        raise SystemExit("idempotent retry emitted new broker events")
    if not result["stale_quote_rejected"] or not result["kill_switch_rejected"]:
        raise SystemExit("safety fixture did not reject as expected")
    if args.output is not None:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
