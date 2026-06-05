import asyncio
import json
from pathlib import Path

import duckdb

from core.events import MarketEvent, SignalEvent
from core.models import Order, ValidationResult


class DecisionLogger:
    def __init__(self, db_path: str | Path) -> None:
        self._db = duckdb.connect(str(db_path))
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                timestamp TIMESTAMPTZ,
                strategy_id TEXT,
                symbol TEXT,
                bid DOUBLE,
                ask DOUBLE,
                last_price DOUBLE,
                iv DOUBLE,
                delta DOUBLE,
                underlying_price DOUBLE,
                direction TEXT,
                reason TEXT,
                context_json TEXT,
                order_json TEXT,
                risk_approved BOOLEAN,
                risk_reason TEXT
            )
        """)

    async def log(
        self,
        signal: SignalEvent,
        market: MarketEvent,
        result: ValidationResult,
    ) -> None:
        greeks = market.model_greeks
        params = [
            signal.timestamp,
            signal.strategy_id,
            market.symbol,
            market.bid,
            market.ask,
            market.last,
            greeks.implied_vol if greeks else None,
            greeks.delta if greeks else None,
            greeks.underlying_price if greeks else None,
            signal.direction,
            signal.reason,
            json.dumps(signal.context),
            json.dumps(_order_to_dict(signal.proposed_order)),
            result.approved,
            result.reason,
        ]
        await asyncio.to_thread(
            self._db.execute,
            "INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            params,
        )

    async def query(self, sql: str) -> list[dict]:
        result = await asyncio.to_thread(self._db.execute, sql)
        if result.description is None:
            return []
        cols = [d[0] for d in result.description]
        return [dict(zip(cols, row, strict=False)) for row in result.fetchall()]

    def close(self) -> None:
        self._db.close()


def _order_to_dict(order: Order) -> dict:
    return {
        "strategy_id": order.strategy_id,
        "order_type": order.order_type,
        "limit_price": order.limit_price,
        "time_in_force": order.time_in_force,
        "legs": [
            {
                "symbol": leg.contract.symbol,
                "sec_type": leg.contract.sec_type,
                "expiry": leg.contract.expiry,
                "strike": leg.contract.strike,
                "right": leg.contract.right,
                "quantity": leg.quantity,
            }
            for leg in order.legs
        ],
    }
