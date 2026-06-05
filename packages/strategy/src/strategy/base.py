from abc import ABC, abstractmethod
from typing import Literal

from core.bus import EventBus
from core.clock import Clock
from core.events import FillEvent, MarketEvent, SignalEvent
from core.models import Order


class BaseStrategy(ABC):
    def __init__(self, strategy_id: str, bus: EventBus, clock: Clock) -> None:
        self.strategy_id = strategy_id
        self._bus = bus
        self._clock = clock

    @abstractmethod
    async def on_market_event(self, event: MarketEvent) -> None: ...

    @abstractmethod
    async def on_fill(self, event: FillEvent) -> None: ...

    async def signal(
        self,
        direction: Literal["ENTER", "EXIT", "ADJUST"],
        order: Order,
        reason: str,
        context: dict | None = None,
    ) -> None:
        event = SignalEvent(
            strategy_id=self.strategy_id,
            timestamp=self._clock.now(),
            direction=direction,
            proposed_order=order,
            reason=reason,
            context=context or {},
        )
        await self._bus.publish(event)
