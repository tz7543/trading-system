from dataclasses import dataclass, field
from math import inf

from core.events import FillEvent
from core.models import Contract


@dataclass
class Trade:
    symbol: str
    quantity: int
    entry_price: float
    exit_price: float
    multiplier: int
    pnl: float


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    total_pnl: float = 0.0
    total_commission: float = 0.0
    net_pnl: float = 0.0
    total_return: float = 0.0
    realized_max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0


def compute_metrics(
    fills: list[FillEvent],
    initial_equity: float,
) -> BacktestResult:
    if not fills:
        return BacktestResult()

    trades = _match_trades(fills)
    total_commission = sum(f.commission for f in fills)
    total_pnl = sum(t.pnl for t in trades)
    net_pnl = total_pnl - total_commission

    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl < 0]
    win_rate = len(winners) / len(trades) if trades else 0.0
    gross_profit = sum(t.pnl for t in winners)
    gross_loss = abs(sum(t.pnl for t in losers))
    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else (inf if gross_profit > 0 else 0.0)
    )

    realized_max_drawdown = _realized_drawdown(trades)

    return BacktestResult(
        trades=trades,
        total_pnl=total_pnl,
        total_commission=total_commission,
        net_pnl=net_pnl,
        total_return=net_pnl / initial_equity if initial_equity > 0 else 0.0,
        realized_max_drawdown=realized_max_drawdown,
        win_rate=win_rate,
        profit_factor=profit_factor,
    )


def _match_trades(fills: list[FillEvent]) -> list[Trade]:
    open_positions: dict[str, list[tuple[int, float, int]]] = {}
    trades: list[Trade] = []

    for fill in fills:
        for leg in fill.legs_filled:
            key = _contract_key(leg.contract)
            qty = leg.quantity
            price = leg.entry_price
            mult = leg.contract.multiplier if leg.contract.sec_type == "OPT" else 1

            if key not in open_positions:
                open_positions[key] = []
            opens = open_positions[key]

            if opens and _is_closing(opens[0][0], qty):
                remaining = abs(qty)
                while remaining > 0 and opens:
                    open_qty, open_price, open_mult = opens[0]
                    match_qty = min(remaining, abs(open_qty))
                    direction = 1 if open_qty > 0 else -1
                    pnl = (price - open_price) * match_qty * direction * mult
                    trades.append(
                        Trade(
                            symbol=key,
                            quantity=match_qty,
                            entry_price=open_price,
                            exit_price=price,
                            multiplier=mult,
                            pnl=pnl,
                        )
                    )
                    remaining -= match_qty
                    if match_qty == abs(open_qty):
                        opens.pop(0)
                    else:
                        new_open_qty = open_qty + (
                            match_qty if open_qty < 0 else -match_qty
                        )
                        opens[0] = (new_open_qty, open_price, open_mult)
                if remaining > 0:
                    opens.append((qty // abs(qty) * remaining, price, mult))
            else:
                opens.append((qty, price, mult))

    return trades


def _contract_key(contract: Contract) -> str:
    if contract.sec_type == "OPT":
        return f"{contract.symbol}_{contract.expiry}_{contract.strike}_{contract.right}"
    return contract.symbol


def _is_closing(open_qty: int, new_qty: int) -> bool:
    return (open_qty > 0 and new_qty < 0) or (open_qty < 0 and new_qty > 0)


def _realized_drawdown(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for trade in trades:
        cumulative += trade.pnl
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    return max_dd
