import asyncio
from collections.abc import AsyncIterator

import ib_async as ibi

from core.data_handler import DataHandler
from core.events import MarketEvent
from core.models import Bar, Contract
from tws_client.converters import ib_bar_to_bar, to_ib_contract
from tws_client.market_feed import MarketDataFeed


class LiveDataHandler(DataHandler):
    def __init__(self, ib: ibi.IB, max_subscriptions: int = 100) -> None:
        self._ib = ib
        self._feed = MarketDataFeed(ib, max_subscriptions)

    async def subscribe_quote(self, contract: Contract) -> AsyncIterator[MarketEvent]:
        async for event in self._feed.subscribe(contract):
            yield event

    async def fetch_history(
        self, contract: Contract, duration: str, bar_size: str
    ) -> list[Bar]:
        ib_contract = to_ib_contract(contract)
        await self._ib.qualifyContractsAsync(ib_contract)
        bars = await self._ib.reqHistoricalDataAsync(
            ib_contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=True,
        )
        await asyncio.sleep(15)
        if not bars:
            return []
        return [ib_bar_to_bar(b, contract.symbol) for b in bars]
