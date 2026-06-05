from core.bus import EventBus
from core.events import FillEvent, MarketEvent, OrderEvent
from core.models import Contract
from storage.tick_writer import TickWriter
from storage.trade_store import TradeStore


class StorageSubscriber:
    def __init__(
        self,
        bus: EventBus,
        tick_writer: TickWriter,
        trade_store: TradeStore,
    ) -> None:
        self._bus = bus
        self._tick_writer = tick_writer
        self._trade_store = trade_store
        self._contract_map: dict[str, Contract] = {}
        self._last_market: dict[str, MarketEvent] = {}

    def register_contract(self, symbol: str, contract: Contract) -> None:
        self._contract_map[symbol] = contract

    def last_market(self, symbol: str) -> MarketEvent | None:
        return self._last_market.get(symbol)

    async def start(self) -> None:
        self._bus.subscribe(MarketEvent, self._on_market)
        self._bus.subscribe(OrderEvent, self._on_order)
        self._bus.subscribe(FillEvent, self._on_fill)

    async def stop(self) -> None:
        self._bus.unsubscribe(MarketEvent, self._on_market)
        self._bus.unsubscribe(OrderEvent, self._on_order)
        self._bus.unsubscribe(FillEvent, self._on_fill)
        self._tick_writer.close()
        await self._trade_store.close()

    async def _on_market(self, event: MarketEvent) -> None:
        self._last_market[event.symbol] = event
        contract = self._contract_map.get(event.symbol)
        if contract:
            self._tick_writer.write(event, contract)

    async def _on_order(self, event: OrderEvent) -> None:
        await self._trade_store.log_order(event)

    async def _on_fill(self, event: FillEvent) -> None:
        await self._trade_store.log_fill(event)
