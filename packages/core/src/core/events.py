import uuid
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
    contract: Contract | None = None


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
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class FillEvent:
    order_id: str
    legs_filled: list[Leg]
    timestamp: datetime
    commission: float
    strategy_id: str = ""


@dataclass
class OrderStatusEvent:
    order_id: str
    status: Literal["SUBMITTED", "PARTIAL", "FILLED", "CANCELLED", "REJECTED"]
    timestamp: datetime
    broker_order_id: str = ""
    filled_quantity: int = 0
    remaining_quantity: int = 0
    reason: str = ""


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
