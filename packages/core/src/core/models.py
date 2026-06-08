from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass
class Bar:
    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class Greeks:
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0
    implied_vol: float = 0.0
    underlying_price: float = 0.0


@dataclass
class Contract:
    symbol: str
    sec_type: Literal["STK", "OPT"]
    currency: str = "USD"
    exchange: str = "SMART"
    expiry: str = ""
    strike: float = 0.0
    right: Literal["C", "P", ""] = ""
    multiplier: int = 100
    con_id: int = 0


@dataclass
class Leg:
    contract: Contract
    quantity: int
    entry_price: float = 0.0


@dataclass
class OptionChain:
    exchange: str
    trading_class: str
    multiplier: int
    expirations: list[str]
    strikes: list[float]


@dataclass
class RiskLimits:
    max_delta: float
    max_vega: float
    max_drawdown: float
    max_position_size: int
    max_margin_utilization: float


@dataclass
class ValidationResult:
    approved: bool
    reason: str | None = None


@dataclass
class Position:
    legs: list[Leg]
    strategy_id: str
    greeks: Greeks | None = None
    unrealized_pnl: float = 0.0


@dataclass
class Order:
    legs: list[Leg]
    strategy_id: str
    order_type: Literal["MKT", "LMT", "STP"] = "LMT"
    limit_price: float | None = None
    time_in_force: Literal["DAY", "GTC"] = "DAY"


def assignment_stock_quantity(
    assigned_contract: Contract,
    contracts_assigned: int,
) -> int:
    if assigned_contract.sec_type != "OPT":
        raise ValueError("assigned_contract must be an option")
    if contracts_assigned < 1:
        raise ValueError("contracts_assigned must be >= 1")
    shares = contracts_assigned * assigned_contract.multiplier
    if assigned_contract.right == "P":
        return shares
    if assigned_contract.right == "C":
        return -shares
    raise ValueError("assigned_contract right must be C or P")
