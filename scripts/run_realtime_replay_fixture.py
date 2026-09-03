from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from finagent.realtime.events import (
    AccountStatusEvent,
    CanonicalRealtimeEvent,
    ConnectionEvent,
    ConnectionStatus,
    OrderEvent,
    OrderLifecycleStatus,
    OrderSide,
    QuoteEvent,
    TradeEvent,
)
from finagent.realtime.projections import rebuild_projection
from finagent.realtime.replay import ReplayGateway, ReplayScenario
from finagent.realtime.serialization import realtime_event_from_dict


def _fixture_events() -> tuple[CanonicalRealtimeEvent, ...]:
    start = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)
    return (
        QuoteEvent(
            source="fixture.market",
            source_event_id="quote-000",
            event_time=start,
            received_at=start + timedelta(seconds=1),
            sequence=0,
            symbol="US500.CFD",
            bid=100.0,
            ask=100.1,
            last=100.05,
        ),
        QuoteEvent(
            source="fixture.market",
            source_event_id="quote-001",
            event_time=start + timedelta(seconds=1),
            received_at=start + timedelta(seconds=2),
            sequence=1,
            symbol="US500.CFD",
            bid=100.2,
            ask=100.3,
            last=100.25,
        ),
        ConnectionEvent(
            source="fixture.connection",
            source_event_id="connection-000",
            event_time=start,
            received_at=start + timedelta(milliseconds=100),
            sequence=0,
            connection_id="fixture-mt5",
            status=ConnectionStatus.CONNECTED,
            reason="fixture connected",
        ),
        OrderEvent(
            source="fixture.execution",
            source_event_id="order-000",
            event_time=start + timedelta(minutes=1),
            received_at=start + timedelta(minutes=1, milliseconds=100),
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
            event_time=start + timedelta(minutes=1, seconds=1),
            received_at=start + timedelta(minutes=1, seconds=1, milliseconds=100),
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
        AccountStatusEvent(
            source="fixture.account",
            source_event_id="account-000",
            event_time=start + timedelta(minutes=1, seconds=2),
            received_at=start + timedelta(minutes=1, seconds=2, milliseconds=100),
            sequence=0,
            account_id="paper-account",
            balance=100_000.0,
            equity=100_010.0,
            margin_used=1000.0,
            free_margin=99_010.0,
            currency="USD",
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run provider-neutral realtime ReplayGateway and projection fixtures. "
            "This command is offline engineering validation only and grants no market-data, "
            "execution, PAPER, stage, or live-capital authority."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/development/realtime_replay_projection_fixture.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    events = _fixture_events()
    gateway = ReplayGateway(events)
    normal = rebuild_projection(gateway.build(ReplayScenario.NORMAL).events)
    persisted = [event.to_dict() for event in events]
    restored = tuple(realtime_event_from_dict(item) for item in persisted)
    restart = rebuild_projection(restored)

    scenarios: dict[str, object] = {}
    passed = restart.snapshot_id == normal.snapshot_id
    for scenario in ReplayScenario:
        batch = gateway.build(scenario)
        snapshot = rebuild_projection(batch.events)
        scenarios[scenario.value] = {
            "batch_id": batch.batch_id,
            "snapshot_id": snapshot.snapshot_id,
            "semantic_state_id": snapshot.semantic_state_id,
            "applied_event_count": snapshot.applied_event_count,
            "duplicate_event_count": snapshot.duplicate_event_count,
            "out_of_order_event_count": snapshot.out_of_order_event_count,
            "stale_event_count": snapshot.stale_event_count,
            "connection_states": [key for key, _value in snapshot.connections],
        }
        if scenario is ReplayScenario.DUPLICATE:
            passed = passed and snapshot.duplicate_event_count == 1
            passed = passed and snapshot.semantic_state_id == normal.semantic_state_id
        if scenario is ReplayScenario.OUT_OF_ORDER:
            passed = passed and snapshot.out_of_order_event_count == 1
            passed = passed and snapshot.semantic_state_id == normal.semantic_state_id
        if scenario is ReplayScenario.STALE_QUOTE:
            passed = passed and snapshot.stale_event_count == 1
            passed = passed and snapshot.semantic_state_id == normal.semantic_state_id
        if scenario is ReplayScenario.DISCONNECT_RECONNECT:
            passed = passed and "replay-connection" in dict(snapshot.connections)

    payload = {
        "schema_version": "finagent.realtime-replay-projection-fixture.v1",
        "passed": passed,
        "normal_snapshot_id": normal.snapshot_id,
        "normal_semantic_state_id": normal.semantic_state_id,
        "restart_snapshot_id": restart.snapshot_id,
        "restart_reconstruction_matches": restart.snapshot_id == normal.snapshot_id,
        "scenarios": scenarios,
        "scope": "offline_provider_neutral_replay_validation",
        "market_data_authority": False,
        "broker_account_authority": False,
        "execution_authority": False,
        "paper_authority": False,
        "status_authority": False,
        "stage_exit_authority": False,
        "live_capital_authority": False,
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if output.exists():
        if output.read_text(encoding="utf-8") != encoded:
            raise RuntimeError("existing replay fixture differs; do not overwrite divergent evidence")
    else:
        output.write_text(encoded, encoding="utf-8")
    print(json.dumps({**payload, "output": str(output)}, sort_keys=True, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
