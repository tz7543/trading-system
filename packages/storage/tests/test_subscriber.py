from datetime import UTC, datetime

import pytest

from core.bus import EventBus
from core.events import FillEvent, MarketEvent, OrderEvent
from core.models import Contract, Leg, Order
from storage.subscriber import StorageSubscriber
from storage.tick_writer import TickWriter
from storage.trade_store import TradeStore


def _stk_contract():
    return Contract(symbol="AAPL", sec_type="STK")


def _stk_event():
    return MarketEvent(
        symbol="AAPL",
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        bid=150.10,
        ask=150.20,
        last=150.15,
        volume=100,
    )


def _order_event():
    c = Contract(symbol="AAPL", sec_type="STK")
    order = Order(legs=[Leg(contract=c, quantity=100)], strategy_id="test")
    return OrderEvent(
        order=order,
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        approved_by="PreTradeValidator",
    )


def _fill_event():
    c = Contract(symbol="AAPL", sec_type="STK")
    return FillEvent(
        order_id="ORD-001",
        legs_filled=[Leg(contract=c, quantity=100, entry_price=150.0)],
        timestamp=datetime(2026, 6, 4, 14, 30, 1, tzinfo=UTC),
        commission=1.0,
    )


@pytest.mark.asyncio
async def test_routes_market_event_to_writer(tmp_path):
    bus = EventBus()
    writer = TickWriter(tmp_path / "data", flush_interval=1)
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    sub = StorageSubscriber(bus, writer, store)
    sub.register_contract("AAPL", _stk_contract())
    await sub.start()
    await bus.publish(_stk_event())
    await sub.stop()
    files = list((tmp_path / "data").rglob("*.parquet"))
    assert len(files) == 1


@pytest.mark.asyncio
async def test_caches_latest_market_event(tmp_path):
    bus = EventBus()
    writer = TickWriter(tmp_path / "data", flush_interval=100)
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    sub = StorageSubscriber(bus, writer, store)
    sub.register_contract("AAPL", _stk_contract())
    await sub.start()
    await bus.publish(_stk_event())
    assert sub.last_market("AAPL") is not None
    assert sub.last_market("AAPL").bid == 150.10
    await sub.stop()


@pytest.mark.asyncio
async def test_routes_order_event(tmp_path):
    bus = EventBus()
    writer = TickWriter(tmp_path / "data", flush_interval=100)
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    sub = StorageSubscriber(bus, writer, store)
    await sub.start()
    await bus.publish(_order_event())
    rows = await store.query_orders()
    assert len(rows) == 1
    await sub.stop()


@pytest.mark.asyncio
async def test_routes_fill_event(tmp_path):
    bus = EventBus()
    writer = TickWriter(tmp_path / "data", flush_interval=100)
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    sub = StorageSubscriber(bus, writer, store)
    await sub.start()
    await bus.publish(_fill_event())
    rows = await store.query_fills()
    assert len(rows) == 1
    assert rows[0]["order_id"] == "ORD-001"
    await sub.stop()


@pytest.mark.asyncio
async def test_two_opt_contracts_write_to_separate_partitions(tmp_path):
    bus = EventBus()
    writer = TickWriter(tmp_path / "data", flush_interval=1)
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    sub = StorageSubscriber(bus, writer, store)

    c150 = Contract(
        symbol="AAPL260620C00150000",
        sec_type="OPT",
        expiry="20260620",
        strike=150.0,
        right="C",
    )
    c155 = Contract(
        symbol="AAPL260620C00155000",
        sec_type="OPT",
        expiry="20260620",
        strike=155.0,
        right="C",
    )
    sub.register_contract("AAPL260620C00150000", c150)
    sub.register_contract("AAPL260620C00155000", c155)
    await sub.start()

    await bus.publish(
        MarketEvent(
            symbol="AAPL260620C00150000",
            timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
            bid=5.10,
            ask=5.30,
            last=5.20,
            volume=50,
        )
    )
    await bus.publish(
        MarketEvent(
            symbol="AAPL260620C00155000",
            timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
            bid=3.10,
            ask=3.30,
            last=3.20,
            volume=30,
        )
    )
    await sub.stop()

    files = list((tmp_path / "data").rglob("*.parquet"))
    assert len(files) == 2
    paths_str = [str(f) for f in files]
    assert any("strike=150.0" in p for p in paths_str)
    assert any("strike=155.0" in p for p in paths_str)
