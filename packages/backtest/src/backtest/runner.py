from backtest.executor import SimulatedExecutor
from core.bus import EventBus
from core.clock import SimClock
from core.data_handler import DataHandler
from core.events import FillEvent, MarketEvent
from core.models import Contract


class BacktestRunner:
    def __init__(
        self,
        bus: EventBus,
        clock: SimClock,
        data_handler: DataHandler,
        executor: SimulatedExecutor,
        contracts: list[Contract],
    ) -> None:
        self._bus = bus
        self._clock = clock
        self._data_handler = data_handler
        self._executor = executor
        self._contracts = contracts

    async def run(self) -> list[FillEvent]:
        all_events: list[MarketEvent] = []
        for contract in self._contracts:
            async for event in self._data_handler.subscribe_quote(contract):
                all_events.append(event)
        all_events.sort(key=lambda e: e.timestamp)

        all_fills: list[FillEvent] = []
        market_snapshot: dict[str, MarketEvent] = {}
        for event in all_events:
            self._clock.advance_to(event.timestamp)
            market_snapshot[event.symbol] = event
            fills = await self._executor.fill_pending(market_snapshot)
            all_fills.extend(fills)
            await self._bus.publish(event)

        return all_fills
