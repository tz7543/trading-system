from datetime import UTC, datetime

import pytest

from core.bus import EventBus
from core.events import FillEvent, MarketEvent


def _make_market_event(symbol="AAPL"):
    return MarketEvent(
        symbol=symbol,
        timestamp=datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        bid=150.0,
        ask=150.05,
        last=150.02,
        volume=100,
    )


@pytest.mark.asyncio
async def test_publish_calls_subscriber():
    bus = EventBus()
    received = []

    async def handler(event):
        received.append(event)

    bus.subscribe(MarketEvent, handler)
    await bus.publish(_make_market_event())

    assert len(received) == 1
    assert received[0].symbol == "AAPL"


@pytest.mark.asyncio
async def test_type_routing_only_matching_type():
    bus = EventBus()
    market_received = []
    fill_received = []

    async def market_handler(event):
        market_received.append(event)

    async def fill_handler(event):
        fill_received.append(event)

    bus.subscribe(MarketEvent, market_handler)
    bus.subscribe(FillEvent, fill_handler)

    await bus.publish(_make_market_event())

    assert len(market_received) == 1
    assert len(fill_received) == 0


@pytest.mark.asyncio
async def test_multiple_subscribers_same_type():
    bus = EventBus()
    received_a = []
    received_b = []

    async def handler_a(event):
        received_a.append(event)

    async def handler_b(event):
        received_b.append(event)

    bus.subscribe(MarketEvent, handler_a)
    bus.subscribe(MarketEvent, handler_b)

    await bus.publish(_make_market_event())

    assert len(received_a) == 1
    assert len(received_b) == 1


@pytest.mark.asyncio
async def test_no_subscribers_does_not_raise():
    bus = EventBus()
    await bus.publish(_make_market_event())


@pytest.mark.asyncio
async def test_unsubscribe():
    bus = EventBus()
    received = []

    async def handler(event):
        received.append(event)

    bus.subscribe(MarketEvent, handler)
    bus.unsubscribe(MarketEvent, handler)

    await bus.publish(_make_market_event())

    assert len(received) == 0
