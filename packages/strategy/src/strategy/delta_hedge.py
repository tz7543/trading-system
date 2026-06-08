from collections.abc import Callable
from datetime import datetime

from core.bus import EventBus
from core.clock import Clock
from core.events import FillEvent, MarketEvent
from core.models import Contract, Greeks, Leg, Order
from strategy.base import BaseStrategy


class DeltaHedgeStrategy(BaseStrategy):
    def __init__(
        self,
        strategy_id: str,
        bus: EventBus,
        clock: Clock,
        hedge_symbol: str,
        greeks_provider: Callable[[], Greeks],
        *,
        target_delta: float = 0.0,
        delta_threshold: float = 0.0,
        min_rebalance_seconds: int = 300,
        high_gamma_threshold: float = 0.10,
        high_gamma_min_rebalance_seconds: int = 60,
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> None:
        _validate_config(
            delta_threshold=delta_threshold,
            min_rebalance_seconds=min_rebalance_seconds,
            high_gamma_threshold=high_gamma_threshold,
            high_gamma_min_rebalance_seconds=high_gamma_min_rebalance_seconds,
        )
        super().__init__(strategy_id, bus, clock)
        self._hedge_symbol = hedge_symbol
        self._greeks_provider = greeks_provider
        self._target_delta = target_delta
        self._delta_threshold = delta_threshold
        self._min_rebalance_seconds = min_rebalance_seconds
        self._high_gamma_threshold = high_gamma_threshold
        self._high_gamma_min_rebalance_seconds = high_gamma_min_rebalance_seconds
        self._exchange = exchange
        self._currency = currency
        self._last_rebalance_at: datetime | None = None

    async def on_market_event(self, event: MarketEvent) -> None:
        if event.symbol != self._hedge_symbol:
            return

        portfolio_greeks = self._greeks_provider()
        hedge_quantity = round(self._target_delta - portfolio_greeks.delta)
        if not self._should_rebalance(portfolio_greeks, hedge_quantity):
            return

        await self._publish_adjustment(portfolio_greeks, hedge_quantity)
        self._last_rebalance_at = self._clock.now()

    async def on_fill(self, event: FillEvent) -> None:
        return None

    def _should_rebalance(
        self,
        portfolio_greeks: Greeks,
        hedge_quantity: int,
    ) -> bool:
        delta_drift = abs(portfolio_greeks.delta - self._target_delta)
        if delta_drift <= self._delta_threshold or hedge_quantity == 0:
            return False

        if self._last_rebalance_at is None:
            return True

        elapsed = (self._clock.now() - self._last_rebalance_at).total_seconds()
        return elapsed >= self._active_cooldown_seconds(portfolio_greeks)

    def _active_cooldown_seconds(self, portfolio_greeks: Greeks) -> int:
        if abs(portfolio_greeks.gamma) >= self._high_gamma_threshold:
            return self._high_gamma_min_rebalance_seconds
        return self._min_rebalance_seconds

    async def _publish_adjustment(
        self,
        portfolio_greeks: Greeks,
        hedge_quantity: int,
    ) -> None:
        contract = Contract(
            symbol=self._hedge_symbol,
            sec_type="STK",
            exchange=self._exchange,
            currency=self._currency,
        )
        order = Order(
            legs=[Leg(contract=contract, quantity=hedge_quantity)],
            strategy_id=self.strategy_id,
            order_type="MKT",
        )
        await self.signal(
            "ADJUST",
            order,
            "Delta hedge rebalance",
            context={
                "portfolio_greeks": _greeks_context(portfolio_greeks),
                "proposed_greeks": {"delta": float(hedge_quantity)},
                "target_delta": self._target_delta,
                "hedge_quantity": hedge_quantity,
            },
        )


def _validate_config(
    *,
    delta_threshold: float,
    min_rebalance_seconds: int,
    high_gamma_threshold: float,
    high_gamma_min_rebalance_seconds: int,
) -> None:
    if delta_threshold < 0:
        raise ValueError("delta_threshold must be >= 0")
    if min_rebalance_seconds < 0:
        raise ValueError("min_rebalance_seconds must be >= 0")
    if high_gamma_threshold < 0:
        raise ValueError("high_gamma_threshold must be >= 0")
    if high_gamma_min_rebalance_seconds < 0:
        raise ValueError("high_gamma_min_rebalance_seconds must be >= 0")
    if high_gamma_min_rebalance_seconds > min_rebalance_seconds:
        raise ValueError(
            "high_gamma_min_rebalance_seconds must be <= min_rebalance_seconds"
        )


def _greeks_context(greeks: Greeks) -> dict[str, float]:
    return {
        "delta": greeks.delta,
        "gamma": greeks.gamma,
        "vega": greeks.vega,
        "theta": greeks.theta,
        "implied_vol": greeks.implied_vol,
        "underlying_price": greeks.underlying_price,
    }
