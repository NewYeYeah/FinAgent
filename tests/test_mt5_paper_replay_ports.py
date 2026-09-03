from __future__ import annotations

from finagent.brokers.mt5.paper_replay import MT5PaperReplayBroker


def test_replay_broker_satisfies_plan_level_port_surface() -> None:
    broker = MT5PaperReplayBroker()
    assert callable(broker.submit)
    assert callable(broker.cancel)
    assert callable(broker.events)
    assert callable(broker.snapshot)
