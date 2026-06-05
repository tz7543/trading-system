from collections import defaultdict


class EventBus:
    def __init__(self):
        self._handlers = defaultdict(list)

    def subscribe(self, event_type, handler):
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type, handler):
        self._handlers[event_type].remove(handler)

    async def publish(self, event):
        for handler in self._handlers[type(event)]:
            await handler(event)
