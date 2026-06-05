from datetime import UTC, datetime

import pytest

from core.events import FillEvent, OrderEvent
from core.models import Contract, Leg, Order
from storage.trade_store import TradeStore


def _make_order_event():
    c = Contract(symbol="AAPL", sec_type="STK")
    order = Order(legs=[Leg(contract=c, quantity=100)], strategy_id="momentum_1")
    return OrderEvent(
        order=order,
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        approved_by="PreTradeValidator",
    )


def _make_fill_event():
    c = Contract(symbol="AAPL", sec_type="STK")
    leg = Leg(contract=c, quantity=100, entry_price=150.0)
    return FillEvent(
        order_id="ORD-001",
        legs_filled=[leg],
        timestamp=datetime(2026, 6, 4, 14, 30, 1, tzinfo=UTC),
        commission=1.0,
    )


@pytest.mark.asyncio
async def test_log_order(tmp_path):
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    order_id = await store.log_order(_make_order_event())
    assert order_id is not None
    rows = await store.query_orders()
    assert len(rows) == 1
    assert rows[0]["strategy_id"] == "momentum_1"
    assert rows[0]["approved_by"] == "PreTradeValidator"
    await store.close()


@pytest.mark.asyncio
async def test_log_fill(tmp_path):
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    await store.log_fill(_make_fill_event())
    rows = await store.query_fills()
    assert len(rows) == 1
    assert rows[0]["order_id"] == "ORD-001"
    assert rows[0]["commission"] == 1.0
    await store.close()


@pytest.mark.asyncio
async def test_query_orders_by_strategy(tmp_path):
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    await store.log_order(_make_order_event())
    rows = await store.query_orders(strategy_id="momentum_1")
    assert len(rows) == 1
    empty = await store.query_orders(strategy_id="nonexistent")
    assert len(empty) == 0
    await store.close()


@pytest.mark.asyncio
async def test_query_fills_by_order_id(tmp_path):
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    await store.log_fill(_make_fill_event())
    rows = await store.query_fills(order_id="ORD-001")
    assert len(rows) == 1
    empty = await store.query_fills(order_id="ORD-999")
    assert len(empty) == 0
    await store.close()
