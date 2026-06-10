import logging

from core import AlertEvent, MarketEvent
from core.clock import LiveClock, SimClock

logger = logging.getLogger(__name__)


class MarketDataWatchdog:
    def __init__(
        self, clock: LiveClock | SimClock, stale_seconds: float = 60.0
    ) -> None:
        self._clock = clock
        self._stale_seconds = stale_seconds
        self._last_seen: dict[str, object] = {}
        self._alerted: set[str] = set()

    async def on_market(self, event: MarketEvent) -> None:
        self._last_seen[event.symbol] = self._clock.now()
        self._alerted.discard(event.symbol)

    def check_now(self) -> list[AlertEvent]:
        now = self._clock.now()
        alerts = []
        for symbol, last in self._last_seen.items():
            age = (now - last).total_seconds()
            if age > self._stale_seconds and symbol not in self._alerted:
                self._alerted.add(symbol)
                alerts.append(
                    AlertEvent(
                        message=f"Market data stale for {symbol}: {age:.0f}s",
                        value=age,
                        timestamp=now,
                    )
                )
        return alerts
