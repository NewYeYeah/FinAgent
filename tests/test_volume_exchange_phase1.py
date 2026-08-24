import pytest

from finagent.domain.orders import OrderIntent, OrderSide
from finagent.services import VolumeAwareSimulatedExchange


def test_volume_aware_exchange_clips_and_charges_impact(snapshot, assets, now):
    asset = assets[0]
    order = OrderIntent(asset=asset, side=OrderSide.BUY, quantity=500_000, created_at=now)
    exchange = VolumeAwareSimulatedExchange(
        commission_bps=1.0,
        base_slippage_bps=1.0,
        impact_bps=20.0,
        max_participation_rate=0.10,
    )
    report = exchange.execute((order,), snapshot)
    fill = report.fills[0]
    assert fill.quantity == pytest.approx(snapshot.bars[asset].volume * 0.10)
    assert fill.price > snapshot.price(asset)
    assert fill.commission > 0
    assert fill.slippage > 0
