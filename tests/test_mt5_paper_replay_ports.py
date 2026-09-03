from __future__ import annotations

from finagent.brokers.mt5.paper_replay import (
    BrokerEventSource,
    BrokerQueryPort,
    MT5PaperReplayBroker,
    OrderCommandPort,
)


def test_replay_broker_satisfies_plan_level_ports() -> None:
    broker = MT5PaperReplayBroker()
    assert isinstance(broker, OrderCommandPort)
    assert isinstance(broker, BrokerEventSource)
    assert isinstance(broker, BrokerQueryPort)
