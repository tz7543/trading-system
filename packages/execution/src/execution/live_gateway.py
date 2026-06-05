import asyncio
import logging

import ib_async as ibi

from core.bus import EventBus
from core.clock import Clock
from core.events import FillEvent, OrderEvent
from core.models import Contract, Leg

logger = logging.getLogger(__name__)


class LiveGateway:
    def __init__(self, bus: EventBus, clock: Clock, ib: ibi.IB) -> None:
        self._bus = bus
        self._clock = clock
        self._ib = ib
        self._pending_fills: set[asyncio.Task] = set()

    async def on_order(self, event: OrderEvent) -> None:
        order = event.order
        if len(order.legs) == 1:
            ib_contract, ib_order = _build_single_leg(order)
        else:
            ib_contract, ib_order = _build_bag(order)

        trade = self._ib.placeOrder(ib_contract, ib_order)
        logger.info(
            "Placed order %s for %s", trade.orderStatus.orderId, order.strategy_id
        )
        trade.filledEvent += lambda t: self._on_filled(t)

    def _on_filled(self, trade: ibi.Trade) -> None:
        task = asyncio.ensure_future(self._publish_fill(trade))
        self._pending_fills.add(task)
        task.add_done_callback(self._on_fill_done)

    def _on_fill_done(self, task: asyncio.Task) -> None:
        self._pending_fills.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.critical(
                "Fill publication failed: %s",
                task.exception(),
                exc_info=task.exception(),
            )

    async def _publish_fill(self, trade: ibi.Trade) -> None:
        legs_filled: list[Leg] = []
        total_commission = 0.0
        for fill in trade.fills:
            contract = _from_ib_contract(fill.contract)
            qty = int(fill.execution.shares)
            if fill.execution.side == "SLD":
                qty = -qty
            legs_filled.append(
                Leg(
                    contract=contract, quantity=qty, entry_price=fill.execution.avgPrice
                )
            )
            if fill.commissionReport:
                total_commission += fill.commissionReport.commission

        fill_event = FillEvent(
            order_id=str(trade.orderStatus.orderId),
            legs_filled=legs_filled,
            timestamp=self._clock.now(),
            commission=total_commission,
        )
        await self._bus.publish(fill_event)


def _build_single_leg(order) -> tuple[ibi.Contract, ibi.Order]:
    leg = order.legs[0]
    ib_contract = _to_ib_contract_with_conid(leg.contract)
    action = "BUY" if leg.quantity > 0 else "SELL"
    qty = abs(leg.quantity)

    if order.order_type == "MKT":
        ib_order = ibi.MarketOrder(action, qty)
    else:
        ib_order = ibi.LimitOrder(action, qty, order.limit_price or 0.0)

    ib_order.tif = order.time_in_force
    return ib_contract, ib_order


def _build_bag(order) -> tuple[ibi.Contract, ibi.Order]:
    underlying = order.legs[0].contract.symbol
    bag = ibi.Contract(
        secType="BAG",
        symbol=underlying,
        currency=order.legs[0].contract.currency,
        exchange="SMART",
    )
    bag.comboLegs = []
    for leg in order.legs:
        if not leg.contract.con_id:
            raise ValueError(
                f"BAG leg {leg.contract.symbol} has no con_id — "
                "call OptionChainService.qualify() first"
            )
        combo = ibi.ComboLeg(
            conId=leg.contract.con_id,
            ratio=abs(leg.quantity),
            action="BUY" if leg.quantity > 0 else "SELL",
            exchange=leg.contract.exchange,
        )
        bag.comboLegs.append(combo)

    if order.order_type == "MKT":
        ib_order = ibi.MarketOrder("BUY", 1)
    else:
        ib_order = ibi.LimitOrder("BUY", 1, order.limit_price or 0.0)

    ib_order.tif = order.time_in_force
    return bag, ib_order


def _to_ib_contract_with_conid(contract: Contract) -> ibi.Contract:
    if contract.sec_type == "STK":
        c = ibi.Stock(contract.symbol, contract.exchange, contract.currency)
    elif contract.sec_type == "OPT":
        c = ibi.Option(
            contract.symbol,
            contract.expiry,
            contract.strike,
            contract.right,
            contract.exchange,
            currency=contract.currency,
        )
    else:
        raise ValueError(f"Unsupported sec_type: {contract.sec_type}")
    if contract.con_id:
        c.conId = contract.con_id
    return c


def _from_ib_contract(ib_contract: ibi.Contract) -> Contract:
    sec_type = "OPT" if ib_contract.secType == "OPT" else "STK"
    return Contract(
        symbol=ib_contract.symbol,
        sec_type=sec_type,
        exchange=ib_contract.exchange or "SMART",
        currency=ib_contract.currency or "USD",
        expiry=getattr(ib_contract, "lastTradeDateOrContractMonth", ""),
        strike=getattr(ib_contract, "strike", 0.0),
        right=getattr(ib_contract, "right", ""),
        con_id=ib_contract.conId,
    )
