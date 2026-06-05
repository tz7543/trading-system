import asyncio
from collections.abc import AsyncIterator

import ib_async as ibi

from core.events import MarketEvent
from core.models import Contract
from tws_client.converters import ticker_to_market_event, to_ib_contract


class SubscriptionLimitError(Exception):
    pass


class MarketDataFeed:
    def __init__(self, ib: ibi.IB, max_subscriptions: int = 100) -> None:
        self._ib = ib
        self._max_subscriptions = max_subscriptions
        self._active_count = 0

    @property
    def subscription_count(self) -> int:
        return self._active_count

    def subscribe(self, contract: Contract) -> AsyncIterator[MarketEvent]:
        if self._active_count >= self._max_subscriptions:
            raise SubscriptionLimitError(
                f"Max {self._max_subscriptions} subscriptions exceeded"
            )
        self._active_count += 1
        return self._subscribe_inner(contract)

    async def _subscribe_inner(self, contract: Contract) -> AsyncIterator[MarketEvent]:
        try:
            ib_contract = to_ib_contract(contract)
            await self._ib.qualifyContractsAsync(ib_contract)
            ticker = self._ib.reqMktData(ib_contract, "", False, False)
            queue: asyncio.Queue[MarketEvent] = asyncio.Queue()

            def on_update(t: ibi.Ticker) -> None:
                event = ticker_to_market_event(t, contract.symbol)
                queue.put_nowait(event)

            ticker.updateEvent += on_update
            try:
                while True:
                    yield await queue.get()
            finally:
                ticker.updateEvent -= on_update
                self._ib.cancelMktData(ib_contract)
        finally:
            self._active_count -= 1
