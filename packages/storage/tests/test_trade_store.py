from datetime import UTC, datetime

import aiosqlite
import pytest

from core.events import FillEvent, OrderEvent, OrderStatusEvent
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
    event = _make_order_event()
    order_id = await store.log_order(event)
    assert order_id == event.order_id
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


@pytest.mark.asyncio
async def test_order_fill_join_by_canonical_id(tmp_path):
    store = TradeStore(tmp_path / "t.db")
    await store.init()
    order_event = _make_order_event()
    await store.log_order(order_event)
    fill = FillEvent(
        order_id=order_event.order_id,
        legs_filled=[],
        timestamp=datetime.now(UTC),
        commission=1.0,
        strategy_id="s1",
    )
    await store.log_fill(fill)
    fills = await store.query_fills(order_id=order_event.order_id)
    assert len(fills) == 1
    await store.close()


@pytest.mark.asyncio
async def test_migration_adds_broker_order_id(tmp_path):
    db_path = tmp_path / "old.db"
    conn = await aiosqlite.connect(db_path)
    await conn.execute(
        """CREATE TABLE orders (
            id TEXT PRIMARY KEY, timestamp TEXT NOT NULL,
            strategy_id TEXT NOT NULL, approved_by TEXT NOT NULL,
            order_type TEXT NOT NULL, limit_price REAL,
            time_in_force TEXT NOT NULL, legs_json TEXT NOT NULL)"""
    )
    await conn.commit()
    await conn.close()
    store = TradeStore(db_path)
    await store.init()  # must ALTER old schema
    cursor = await store._db.execute("PRAGMA table_info(orders)")
    cols = [row[1] for row in await cursor.fetchall()]
    assert "broker_order_id" in cols
    await store.close()


@pytest.mark.asyncio
async def test_log_status_records_and_backfills(tmp_path):
    store = TradeStore(tmp_path / "t.db")
    await store.init()
    order_event = _make_order_event()
    await store.log_order(order_event)
    status = OrderStatusEvent(
        order_id=order_event.order_id,
        status="SUBMITTED",
        timestamp=datetime.now(UTC),
        broker_order_id="42",
    )
    await store.log_status(status)
    orders = await store.query_orders()
    assert orders[0]["broker_order_id"] == "42"
    statuses = await store.query_statuses(order_event.order_id)
    assert statuses[0]["status"] == "SUBMITTED"
    await store.close()
