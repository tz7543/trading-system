from core.bus import EventBus
from core.clock import Clock
from core.events import FillEvent, MarketEvent, OrderEvent
from core.models import Leg


class SimulatedExecutor:
    def __init__(self, bus: EventBus, clock: Clock) -> None:
        self._bus = bus
        self._clock = clock
        self._pending: list[OrderEvent] = []
        self._fill_counter = 0

    async def on_order(self, event: OrderEvent) -> None:
        self._pending.append(event)

    async def fill_pending(
        self, market_snapshot: dict[str, MarketEvent]
    ) -> list[FillEvent]:
        fills: list[FillEvent] = []
        still_pending: list[OrderEvent] = []
        for order_event in self._pending:
            if not _can_fill(order_event, market_snapshot):
                still_pending.append(order_event)
                continue
            legs_filled: list[Leg] = []
            total_commission = 0.0
            for leg in order_event.order.legs:
                market = market_snapshot[leg.contract.symbol]
                price = _fill_price(leg, market)
                legs_filled.append(
                    Leg(
                        contract=leg.contract,
                        quantity=leg.quantity,
                        entry_price=price,
                    )
                )
                total_commission += _commission(leg)
            total_commission = max(total_commission, 1.0)
            self._fill_counter += 1
            fill = FillEvent(
                order_id=f"sim-{self._fill_counter}",
                legs_filled=legs_filled,
                timestamp=self._clock.now(),
                commission=total_commission,
            )
            fills.append(fill)
            await self._bus.publish(fill)
        self._pending = still_pending
        return fills


def _can_fill(order_event: OrderEvent, snapshot: dict[str, MarketEvent]) -> bool:
    order = order_event.order
    if not all(leg.contract.symbol in snapshot for leg in order.legs):
        return False
    if order.order_type == "LMT" and order.limit_price is not None:
        for leg in order.legs:
            market = snapshot[leg.contract.symbol]
            price = _mid_price(leg, market)
            if leg.quantity > 0 and price > order.limit_price:
                return False
            if leg.quantity < 0 and price < order.limit_price:
                return False
    return True


def _mid_price(leg: Leg, market: MarketEvent) -> float:
    if leg.contract.sec_type == "OPT":
        return (market.bid + market.ask) / 2
    return market.last


def _fill_price(leg: Leg, market: MarketEvent) -> float:
    return _mid_price(leg, market)


def _commission(leg: Leg) -> float:
    qty = abs(leg.quantity)
    if leg.contract.sec_type == "OPT":
        return 0.65 * qty
    return 0.005 * qty
