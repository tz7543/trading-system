from datetime import UTC, datetime

import pytest

from backtest.executor import SimulatedExecutor
from backtest.runner import BacktestRunner
from core.bus import EventBus
from core.clock import SimClock
from core.events import FillEvent, MarketEvent, OrderEvent
from core.models import Contract, Leg, Order


class _FakeDataHandler:
    """Minimal DataHandler that yields pre-loaded events."""

    def __init__(self, events_by_contract: dict[str, list[MarketEvent]]) -> None:
        self._events = events_by_contract

    async def subscribe_quote(self, contract):
        for event in self._events.get(contract.symbol, []):
            yield event

    async def fetch_history(self, contract, duration, bar_size):
        return []


def _stk_event(ts, last=150.0):
    return MarketEvent(
        symbol="AAPL",
        timestamp=ts,
        bid=last - 0.10,
        ask=last + 0.10,
        last=last,
        volume=1000,
    )


@pytest.mark.asyncio
async def test_replays_in_timestamp_order():
    """Events from multiple contracts are merged by timestamp."""
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 0, 0, tzinfo=UTC))
    executor = SimulatedExecutor(bus, clock)
    t1 = datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC)
    t2 = datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC)
    t3 = datetime(2026, 6, 4, 14, 32, 0, tzinfo=UTC)
    data = _FakeDataHandler(
        {
            "AAPL": [_stk_event(t1, 100.0), _stk_event(t3, 102.0)],
            "MSFT": [
                MarketEvent(
                    symbol="MSFT",
                    timestamp=t2,
                    bid=299.0,
                    ask=301.0,
                    last=300.0,
                    volume=500,
                )
            ],
        }
    )
    received: list[MarketEvent] = []

    async def capture(event: MarketEvent) -> None:
        received.append(event)

    bus.subscribe(MarketEvent, capture)
    contracts = [
        Contract(symbol="AAPL", sec_type="STK"),
        Contract(symbol="MSFT", sec_type="STK"),
    ]
    runner = BacktestRunner(bus, clock, data, executor, contracts)
    await runner.run()
    assert len(received) == 3
    assert received[0].symbol == "AAPL" and received[0].last == 100.0
    assert received[1].symbol == "MSFT" and received[1].last == 300.0
    assert received[2].symbol == "AAPL" and received[2].last == 102.0


@pytest.mark.asyncio
async def test_look_ahead_guard():
    """Order placed at T=0 (price=100) must fill at T=1 (price=110), NOT T=0."""
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 0, 0, tzinfo=UTC))
    executor = SimulatedExecutor(bus, clock)
    t0 = datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC)
    t1 = datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC)
    data = _FakeDataHandler(
        {"AAPL": [_stk_event(t0, last=100.0), _stk_event(t1, last=110.0)]}
    )
    fills: list[FillEvent] = []

    async def on_market(event: MarketEvent) -> None:
        if event.last == 100.0:
            order = Order(
                legs=[
                    Leg(contract=Contract(symbol="AAPL", sec_type="STK"), quantity=100)
                ],
                strategy_id="test",
            )
            order_event = OrderEvent(
                order=order,
                timestamp=clock.now(),
                approved_by="test",
            )
            await executor.on_order(order_event)

    async def on_fill(event: FillEvent) -> None:
        fills.append(event)

    bus.subscribe(MarketEvent, on_market)
    bus.subscribe(FillEvent, on_fill)
    contracts = [Contract(symbol="AAPL", sec_type="STK")]
    runner = BacktestRunner(bus, clock, data, executor, contracts)
    await runner.run()
    assert len(fills) == 1
    assert fills[0].legs_filled[0].entry_price == 110.0


@pytest.mark.asyncio
async def test_advances_clock():
    """Clock advances to each event's timestamp."""
    bus = EventBus()
    t0 = datetime(2026, 6, 4, 14, 0, 0, tzinfo=UTC)
    clock = SimClock(t0)
    executor = SimulatedExecutor(bus, clock)
    t1 = datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC)
    t2 = datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC)
    data = _FakeDataHandler({"AAPL": [_stk_event(t1, 100.0), _stk_event(t2, 105.0)]})
    timestamps: list[datetime] = []

    async def capture_time(event: MarketEvent) -> None:
        timestamps.append(clock.now())

    bus.subscribe(MarketEvent, capture_time)
    contracts = [Contract(symbol="AAPL", sec_type="STK")]
    runner = BacktestRunner(bus, clock, data, executor, contracts)
    await runner.run()
    assert timestamps == [t1, t2]
