from datetime import UTC, datetime

import pytest

from core.bus import EventBus
from core.clock import SimClock
from core.events import FillEvent, MarketEvent, SignalEvent
from core.models import Contract, Leg, Order
from strategy.base import BaseStrategy


class DummyStrategy(BaseStrategy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.received_events: list[MarketEvent] = []
        self.received_fills: list[FillEvent] = []

    async def on_market_event(self, event: MarketEvent) -> None:
        self.received_events.append(event)

    async def on_fill(self, event: FillEvent) -> None:
        self.received_fills.append(event)


def _make_order():
    c = Contract(symbol="AAPL", sec_type="STK")
    return Order(legs=[Leg(contract=c, quantity=100)], strategy_id="test_strat")


@pytest.mark.asyncio
async def test_signal_publishes_to_bus():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    strat = DummyStrategy("test_strat", bus, clock)
    received: list[SignalEvent] = []

    async def capture(e: SignalEvent) -> None:
        received.append(e)

    bus.subscribe(SignalEvent, capture)
    await strat.signal("ENTER", _make_order(), "Test reason")
    assert len(received) == 1
    assert received[0].direction == "ENTER"
    assert received[0].reason == "Test reason"
    assert received[0].proposed_order.strategy_id == "test_strat"


@pytest.mark.asyncio
async def test_signal_uses_clock_timestamp():
    bus = EventBus()
    ts = datetime(2026, 6, 4, 15, 0, 0, tzinfo=UTC)
    clock = SimClock(ts)
    strat = DummyStrategy("test_strat", bus, clock)
    received: list[SignalEvent] = []

    async def capture(e: SignalEvent) -> None:
        received.append(e)

    bus.subscribe(SignalEvent, capture)
    await strat.signal("EXIT", _make_order(), "Close position")
    assert received[0].timestamp == ts


@pytest.mark.asyncio
async def test_signal_includes_strategy_id():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    strat = DummyStrategy("my_ic_strategy", bus, clock)
    received: list[SignalEvent] = []

    async def capture(e: SignalEvent) -> None:
        received.append(e)

    bus.subscribe(SignalEvent, capture)
    await strat.signal("ENTER", _make_order(), "IV spike")
    assert received[0].strategy_id == "my_ic_strategy"


def test_cannot_instantiate_base_strategy():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    with pytest.raises(TypeError):
        BaseStrategy("test", bus, clock)
