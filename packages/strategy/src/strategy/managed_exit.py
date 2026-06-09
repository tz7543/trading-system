from core.events import MarketEvent
from core.models import Leg


class ManagedExit:
    """Credit-strategy profit target: profit_pct = PnL / credit received."""

    def __init__(self, legs: list[Leg], profit_target: float = 0.50) -> None:
        self._legs = legs
        self._profit_target = profit_target
        self._entry_cost = sum(
            leg.entry_price * leg.quantity * leg.contract.multiplier for leg in legs
        )

    @property
    def entry_cost(self) -> float:
        return self._entry_cost

    def profit_pct(self, market: dict[str, MarketEvent]) -> float | None:
        current = 0.0
        for leg in self._legs:
            m = market.get(leg.contract.symbol)
            if m is None:
                return None
            mid = (m.bid + m.ask) / 2
            current += mid * leg.quantity * leg.contract.multiplier
        max_profit = abs(self._entry_cost)
        if max_profit < 0.01:
            return None
        return (current - self._entry_cost) / max_profit

    def should_exit(self, market: dict[str, MarketEvent]) -> bool:
        pct = self.profit_pct(market)
        if pct is None:
            return False
        return pct >= self._profit_target
