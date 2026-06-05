from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from core.events import MarketEvent
from core.models import Bar, Contract


class DataHandler(ABC):
    @abstractmethod
    async def subscribe_quote(
        self, contract: Contract
    ) -> AsyncIterator[MarketEvent]: ...

    @abstractmethod
    async def fetch_history(
        self, contract: Contract, duration: str, bar_size: str
    ) -> list[Bar]: ...
