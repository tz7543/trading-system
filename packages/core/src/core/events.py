from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from core.models import Bar, Contract, Greeks, Leg, Order


@dataclass
class MarketEvent:
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    last: float
    volume: int
    bid_greeks: Greeks | None = None
    ask_greeks: Greeks | None = None
    last_greeks: Greeks | None = None
    model_greeks: Greeks | None = None
    bar: Bar | None = None


@dataclass
class SignalEvent:
    strategy_id: str
    timestamp: datetime
    direction: Literal["ENTER", "EXIT", "ADJUST"]
    proposed_order: Order
    reason: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderEvent:
    order: Order
    timestamp: datetime
    approved_by: str


@dataclass
class FillEvent:
    order_id: str
    legs_filled: list[Leg]
    timestamp: datetime
    commission: float


@dataclass
class AssignmentEvent:
    strategy_id: str
    timestamp: datetime
    assigned_contract: Contract
    contracts_assigned: int
    stock_quantity: int
    account: str = ""
    underlying_price: float = 0.0


@dataclass
class AlertEvent:
    message: str
    value: float
    timestamp: datetime
