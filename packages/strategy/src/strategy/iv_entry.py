from collections.abc import Callable

from core.bus import EventBus
from core.clock import Clock
from core.events import FillEvent, MarketEvent
from core.models import Order
from strategy.base import BaseStrategy
from strategy.iv_metrics import IVMetrics

MetricsProvider = Callable[[MarketEvent], IVMetrics | None]
OrderFactory = Callable[[MarketEvent, IVMetrics], Order]


class IVRankEntryStrategy(BaseStrategy):
    def __init__(
        self,
        strategy_id: str,
        bus: EventBus,
        clock: Clock,
        symbol: str,
        metrics_provider: MetricsProvider,
        order_factory: OrderFactory,
        *,
        entry_rank_threshold: float = 70.0,
    ) -> None:
        if not 0.0 <= entry_rank_threshold <= 100.0:
            raise ValueError("entry_rank_threshold must be between 0 and 100")
        super().__init__(strategy_id, bus, clock)
        self._symbol = symbol
        self._metrics_provider = metrics_provider
        self._order_factory = order_factory
        self._entry_rank_threshold = entry_rank_threshold
        self._entered = False

    async def on_market_event(self, event: MarketEvent) -> None:
        if event.symbol != self._symbol or self._entered:
            return

        metrics = self._metrics_provider(event)
        if metrics is None or metrics.iv_rank < self._entry_rank_threshold:
            return

        order = self._order_factory(event, metrics)
        await self.signal(
            "ENTER",
            order,
            "IV rank entry",
            context={
                "current_iv": metrics.current_iv,
                "iv_rank": metrics.iv_rank,
                "iv_percentile": metrics.iv_percentile,
                "history_count": metrics.history_count,
            },
        )
        self._entered = True

    async def on_fill(self, event: FillEvent) -> None:
        return None
