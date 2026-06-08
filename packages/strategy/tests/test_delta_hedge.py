from datetime import UTC, datetime, timedelta

import pytest

from core.bus import EventBus
from core.clock import SimClock
from core.events import MarketEvent, SignalEvent
from core.models import Greeks
from strategy import DeltaHedgeStrategy as ExportedDeltaHedgeStrategy
from strategy.delta_hedge import DeltaHedgeStrategy


def _market(symbol: str = "AAPL") -> MarketEvent:
    return MarketEvent(
        symbol=symbol,
        timestamp=datetime(2026, 6, 8, 14, 30, tzinfo=UTC),
        bid=149.95,
        ask=150.05,
        last=150.0,
        volume=1000,
    )


async def _capture_signals(bus: EventBus) -> list[SignalEvent]:
    signals: list[SignalEvent] = []

    async def capture(event: SignalEvent) -> None:
        signals.append(event)

    bus.subscribe(SignalEvent, capture)
    return signals


@pytest.mark.asyncio
async def test_delta_drift_emits_adjust_signal_with_stock_hedge_order():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 8, 14, 30, tzinfo=UTC))
    signals = await _capture_signals(bus)
    strategy = DeltaHedgeStrategy(
        strategy_id="delta-hedge",
        bus=bus,
        clock=clock,
        hedge_symbol="AAPL",
        greeks_provider=lambda: Greeks(delta=125.4, gamma=0.02, vega=-8.0),
        delta_threshold=25.0,
    )

    await strategy.on_market_event(_market())

    assert len(signals) == 1
    signal = signals[0]
    assert signal.direction == "ADJUST"
    assert signal.reason == "Delta hedge rebalance"
    assert signal.proposed_order.strategy_id == "delta-hedge"
    assert signal.proposed_order.order_type == "MKT"
    assert signal.proposed_order.limit_price is None
    assert signal.proposed_order.legs[0].contract.symbol == "AAPL"
    assert signal.proposed_order.legs[0].contract.sec_type == "STK"
    assert signal.proposed_order.legs[0].quantity == -125
    assert signal.context["portfolio_greeks"]["delta"] == 125.4
    assert signal.context["portfolio_greeks"]["gamma"] == 0.02
    assert signal.context["proposed_greeks"]["delta"] == -125.0
    assert signal.context["target_delta"] == 0.0


@pytest.mark.asyncio
async def test_delta_inside_threshold_does_not_emit_signal():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 8, 14, 30, tzinfo=UTC))
    signals = await _capture_signals(bus)
    strategy = DeltaHedgeStrategy(
        strategy_id="delta-hedge",
        bus=bus,
        clock=clock,
        hedge_symbol="AAPL",
        greeks_provider=lambda: Greeks(delta=24.9),
        delta_threshold=25.0,
    )

    await strategy.on_market_event(_market())

    assert signals == []


@pytest.mark.asyncio
async def test_low_gamma_uses_normal_cooldown():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 8, 14, 30, tzinfo=UTC))
    signals = await _capture_signals(bus)
    strategy = DeltaHedgeStrategy(
        strategy_id="delta-hedge",
        bus=bus,
        clock=clock,
        hedge_symbol="AAPL",
        greeks_provider=lambda: Greeks(delta=100.0, gamma=0.05),
        delta_threshold=25.0,
        min_rebalance_seconds=300,
        high_gamma_threshold=0.10,
        high_gamma_min_rebalance_seconds=60,
    )

    await strategy.on_market_event(_market())
    clock.advance_to(clock.now() + timedelta(seconds=120))
    await strategy.on_market_event(_market())

    assert len(signals) == 1


@pytest.mark.asyncio
async def test_high_gamma_uses_shorter_cooldown():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 8, 14, 30, tzinfo=UTC))
    signals = await _capture_signals(bus)
    strategy = DeltaHedgeStrategy(
        strategy_id="delta-hedge",
        bus=bus,
        clock=clock,
        hedge_symbol="AAPL",
        greeks_provider=lambda: Greeks(delta=100.0, gamma=0.20),
        delta_threshold=25.0,
        min_rebalance_seconds=300,
        high_gamma_threshold=0.10,
        high_gamma_min_rebalance_seconds=60,
    )

    await strategy.on_market_event(_market())
    clock.advance_to(clock.now() + timedelta(seconds=120))
    await strategy.on_market_event(_market())

    assert len(signals) == 2


@pytest.mark.asyncio
async def test_ignores_market_events_for_other_symbols():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 8, 14, 30, tzinfo=UTC))
    signals = await _capture_signals(bus)
    strategy = DeltaHedgeStrategy(
        strategy_id="delta-hedge",
        bus=bus,
        clock=clock,
        hedge_symbol="AAPL",
        greeks_provider=lambda: Greeks(delta=100.0),
        delta_threshold=25.0,
    )

    await strategy.on_market_event(_market("MSFT"))

    assert signals == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"delta_threshold": -1.0},
        {"min_rebalance_seconds": -1},
        {"high_gamma_threshold": -0.01},
        {"min_rebalance_seconds": 60, "high_gamma_min_rebalance_seconds": 120},
    ],
)
def test_rejects_invalid_thresholds(kwargs):
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 8, 14, 30, tzinfo=UTC))

    with pytest.raises(ValueError):
        DeltaHedgeStrategy(
            strategy_id="delta-hedge",
            bus=bus,
            clock=clock,
            hedge_symbol="AAPL",
            greeks_provider=lambda: Greeks(),
            **kwargs,
        )


def test_delta_hedge_strategy_is_exported():
    assert ExportedDeltaHedgeStrategy is DeltaHedgeStrategy
