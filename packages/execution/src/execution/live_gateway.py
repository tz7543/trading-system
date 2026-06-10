import asyncio
import logging

import ib_async as ibi

from core.bus import EventBus
from core.clock import Clock
from core.events import AssignmentEvent, FillEvent, OrderEvent, OrderStatusEvent
from core.models import Contract, Leg, assignment_stock_quantity

logger = logging.getLogger(__name__)

_TERMINAL_CANCEL_STATES = {"Cancelled", "ApiCancelled", "Inactive"}


class LiveGateway:
    def __init__(self, bus: EventBus, clock: Clock, ib: ibi.IB) -> None:
        self._bus = bus
        self._clock = clock
        self._ib = ib
        self._pending_tasks: set[asyncio.Task] = set()
        self._status_memo: dict[str, tuple[str, int]] = {}
        # order_id → (trade, on_status, on_fill)
        self._live_orders: dict[str, tuple] = {}

    async def on_order(self, event: OrderEvent) -> None:
        order = event.order
        try:
            if len(order.legs) == 1:
                ib_contract, ib_order = _build_single_leg(order)
            else:
                ib_contract, ib_order = _build_bag(order)
            trade = self._ib.placeOrder(ib_contract, ib_order)
        except Exception as exc:
            logger.error("Order build/place failed for %s: %s", order.strategy_id, exc)
            await self._publish_status(event.order_id, "REJECTED", reason=str(exc))
            return

        broker_id = str(trade.orderStatus.orderId)
        logger.info(
            "Placed order %s (broker %s) for %s",
            event.order_id,
            broker_id,
            order.strategy_id,
        )
        # Seed the memo BEFORE publishing: IB's subsequent echoed
        # statusEvent("Submitted", filled=0) is deduped in _on_status,
        # so no second SUBMITTED is published (plan review finding).
        self._status_memo[event.order_id] = ("SUBMITTED", 0)
        await self._publish_status(
            event.order_id, "SUBMITTED", broker_order_id=broker_id
        )

        def on_status(t: ibi.Trade) -> None:
            self._spawn(self._on_status(t, event.order_id, broker_id))

        def on_fill(t: ibi.Trade, f: ibi.Fill) -> None:
            self._spawn(
                self._on_fill(t, f, event.order_id, order.strategy_id, broker_id)
            )

        trade.statusEvent += on_status
        trade.fillEvent += on_fill
        # Keep handler references for terminal-state cleanup (IB holds the
        # Trade long-term; without disconnecting we would receive late
        # callbacks after shutdown — plan review finding).
        self._live_orders[event.order_id] = (trade, on_status, on_fill)

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._pending_tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._pending_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.critical(
                "Gateway event task failed: %s",
                task.exception(),
                exc_info=task.exception(),
            )

    async def _on_status(self, trade: ibi.Trade, order_id: str, broker_id: str) -> None:
        ib_status = trade.orderStatus.status
        filled = int(trade.orderStatus.filled)
        remaining = int(trade.orderStatus.remaining)
        status, reason = _derive_status(ib_status, filled, trade)
        if status is None:
            return
        memo_key = (status, filled)
        if self._status_memo.get(order_id) == memo_key:
            return
        self._status_memo[order_id] = memo_key
        await self._publish_status(
            order_id,
            status,
            broker_order_id=broker_id,
            filled_quantity=filled,
            remaining_quantity=remaining,
            reason=reason,
        )
        if status in ("FILLED", "CANCELLED", "REJECTED"):
            self._cleanup_order(order_id)

    def _cleanup_order(self, order_id: str) -> None:
        # Terminal-state cleanup: avoid memo leaks and detach eventkit
        # handlers to prevent late callbacks.
        self._status_memo.pop(order_id, None)
        entry = self._live_orders.pop(order_id, None)
        if entry is not None:
            trade, on_status, on_fill = entry
            trade.statusEvent -= on_status
            trade.fillEvent -= on_fill

    async def _on_fill(
        self,
        trade: ibi.Trade,
        fill: ibi.Fill,
        order_id: str,
        strategy_id: str,
        broker_id: str,
    ) -> None:
        contract = _from_ib_contract(fill.contract)
        qty = int(fill.execution.shares)
        if fill.execution.side == "SLD":
            qty = -qty
        commission = fill.commissionReport.commission if fill.commissionReport else 0.0
        await self._bus.publish(
            FillEvent(
                order_id=order_id,
                legs_filled=[
                    Leg(
                        contract=contract,
                        quantity=qty,
                        entry_price=fill.execution.avgPrice,
                    )
                ],
                timestamp=self._clock.now(),
                commission=commission,
                strategy_id=strategy_id,
            )
        )
        # execDetails (fillEvent) and orderStatus (statusEvent) are independent TWS
        # callbacks with no guaranteed ordering; a stale `remaining` here only affects
        # the synthesised PARTIAL's counts — the authoritative status still arrives via
        # statusEvent and the memo deduplicates it.
        remaining = int(trade.orderStatus.remaining)
        if remaining > 0:
            await self._on_status(trade, order_id, broker_id)

    async def _publish_status(
        self,
        order_id: str,
        status: str,
        *,
        broker_order_id: str = "",
        filled_quantity: int = 0,
        remaining_quantity: int = 0,
        reason: str = "",
    ) -> None:
        await self._bus.publish(
            OrderStatusEvent(
                order_id=order_id,
                status=status,
                timestamp=self._clock.now(),
                broker_order_id=broker_order_id,
                filled_quantity=filled_quantity,
                remaining_quantity=remaining_quantity,
                reason=reason,
            )
        )

    async def on_assignment(
        self,
        strategy_id: str,
        assigned_contract: Contract,
        contracts_assigned: int,
        account: str = "",
        underlying_price: float = 0.0,
    ) -> None:
        event = AssignmentEvent(
            strategy_id=strategy_id,
            timestamp=self._clock.now(),
            assigned_contract=assigned_contract,
            contracts_assigned=contracts_assigned,
            stock_quantity=assignment_stock_quantity(
                assigned_contract,
                contracts_assigned,
            ),
            account=account,
            underlying_price=underlying_price,
        )
        await self._bus.publish(event)


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


def _combo_limit_price(order) -> float:
    price = order.limit_price or 0.0
    if order.is_credit is True and price > 0:
        return -price
    if order.is_credit is False and price < 0:
        return abs(price)
    return price


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
        ib_order = ibi.LimitOrder("BUY", 1, _combo_limit_price(order))

    ib_order.tif = order.time_in_force
    ib_order.smartComboRoutingParams = [ibi.TagValue("NonGuaranteed", "1")]
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


def _derive_status(
    ib_status: str, filled: int, trade: ibi.Trade
) -> tuple[str | None, str]:
    if ib_status == "Filled":
        return "FILLED", ""
    if ib_status in _TERMINAL_CANCEL_STATES:
        last = trade.log[-1] if trade.log else None
        if last is not None and last.errorCode:
            return "REJECTED", last.message
        return "CANCELLED", ""
    if ib_status in ("PendingSubmit", "PreSubmitted", "Submitted"):
        return ("PARTIAL", "") if filled > 0 else ("SUBMITTED", "")
    return None, ""
