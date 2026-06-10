import json
from pathlib import Path

import aiosqlite

from core.events import FillEvent, OrderEvent, OrderStatusEvent


class TradeStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                strategy_id TEXT NOT NULL,
                approved_by TEXT NOT NULL,
                order_type TEXT NOT NULL,
                limit_price REAL,
                time_in_force TEXT NOT NULL,
                legs_json TEXT NOT NULL,
                broker_order_id TEXT
            )
        """)
        # Migrate old DBs that lack broker_order_id
        cursor = await self._db.execute("PRAGMA table_info(orders)")
        cols = [row[1] for row in await cursor.fetchall()]
        if "broker_order_id" not in cols:
            await self._db.execute("ALTER TABLE orders ADD COLUMN broker_order_id TEXT")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                commission REAL NOT NULL,
                legs_json TEXT NOT NULL
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS order_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                status TEXT NOT NULL,
                broker_order_id TEXT,
                timestamp TEXT NOT NULL,
                reason TEXT
            )
        """)
        await self._db.commit()

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("TradeStore not initialized; call await init() first")
        return self._db

    async def log_order(self, event: OrderEvent) -> str:
        db = self._require_db()
        legs = [
            {
                "symbol": leg.contract.symbol,
                "sec_type": leg.contract.sec_type,
                "expiry": leg.contract.expiry,
                "strike": leg.contract.strike,
                "right": leg.contract.right,
                "quantity": leg.quantity,
            }
            for leg in event.order.legs
        ]
        await db.execute(
            """INSERT INTO orders
               (id, timestamp, strategy_id, approved_by, order_type,
                limit_price, time_in_force, legs_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.order_id,
                event.timestamp.isoformat(),
                event.order.strategy_id,
                event.approved_by,
                event.order.order_type,
                event.order.limit_price,
                event.order.time_in_force,
                json.dumps(legs),
            ),
        )
        await db.commit()
        return event.order_id

    async def log_fill(self, event: FillEvent) -> None:
        db = self._require_db()
        legs = [
            {
                "symbol": leg.contract.symbol,
                "sec_type": leg.contract.sec_type,
                "quantity": leg.quantity,
                "entry_price": leg.entry_price,
            }
            for leg in event.legs_filled
        ]
        await db.execute(
            "INSERT INTO fills (order_id, timestamp, commission, legs_json) VALUES (?, ?, ?, ?)",
            (
                event.order_id,
                event.timestamp.isoformat(),
                event.commission,
                json.dumps(legs),
            ),
        )
        await db.commit()

    async def log_status(self, event: OrderStatusEvent) -> None:
        db = self._require_db()
        await db.execute(
            """INSERT INTO order_status
               (order_id, status, broker_order_id, timestamp, reason)
               VALUES (?, ?, ?, ?, ?)""",
            (
                event.order_id,
                event.status,
                event.broker_order_id,
                event.timestamp.isoformat(),
                event.reason,
            ),
        )
        if event.status == "SUBMITTED" and event.broker_order_id:
            await db.execute(
                "UPDATE orders SET broker_order_id = ? WHERE id = ?",
                (event.broker_order_id, event.order_id),
            )
        await db.commit()

    async def query_orders(self, strategy_id: str | None = None) -> list[dict]:
        db = self._require_db()
        if strategy_id:
            cursor = await db.execute(
                "SELECT * FROM orders WHERE strategy_id = ?", (strategy_id,)
            )
        else:
            cursor = await db.execute("SELECT * FROM orders")
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row, strict=False)) for row in rows]

    async def query_fills(self, order_id: str | None = None) -> list[dict]:
        db = self._require_db()
        if order_id:
            cursor = await db.execute(
                "SELECT * FROM fills WHERE order_id = ?", (order_id,)
            )
        else:
            cursor = await db.execute("SELECT * FROM fills")
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row, strict=False)) for row in rows]

    async def query_statuses(self, order_id: str) -> list[dict]:
        db = self._require_db()
        cursor = await db.execute(
            "SELECT * FROM order_status WHERE order_id = ? ORDER BY id",
            (order_id,),
        )
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row, strict=False)) for row in rows]

    async def close(self) -> None:
        if self._db:
            await self._db.close()
