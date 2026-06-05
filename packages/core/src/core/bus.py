import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

Handler = Callable[[Any], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: type, handler: Handler) -> None:
        self._handlers[event_type].remove(handler)

    async def publish(self, event: object) -> None:
        for handler in self._handlers[type(event)]:
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    "Handler %s failed for %s", handler, type(event).__name__
                )
