from datetime import UTC, datetime

import pytest

from core.bus import EventBus
from core.clock import SimClock
from core.events import MarketEvent, SignalEvent
from core.models import Contract, Greeks, Leg, Order
from strategy.iv_entry import IVRankEntryStrategy
from strategy.iv_metrics import IVMetrics


def _market(symbol: str = "AAPL260620P00145000") -> MarketEvent:
    return MarketEvent(
        symbol=symbol,
        timestamp=datetime(2026, 6, 8, 14, 30, tzinfo=UTC),
        bid=4.90,
        ask=5.10,
        last=5.00,
        volume=100,
        model_greeks=Greeks(implied_vol=0.42),
    )


def _order_factory(event: MarketEvent, metrics: IVMetrics) -> Order:
    return Order(
        legs=[
            Leg(
                contract=Contract(
                    symbol=event.symbol,
                    sec_type="OPT",
                    expiry="20260620",
                    strike=145.0,
                    right="P",
                ),
                quantity=-1,
            )
        ],
        strategy_id="iv-entry",
        order_type="LMT",
        limit_price=-1.25,
    )


async def _capture_signals(bus: EventBus) -> list[SignalEvent]:
    signals: list[SignalEvent] = []

    async def capture(event: SignalEvent) -> None:
        signals.append(event)

    bus.subscribe(SignalEvent, capture)
    return signals


@pytest.mark.asyncio
async def test_high_iv_rank_emits_enter_signal_with_metrics_context():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 8, 14, 30, tzinfo=UTC))
    signals = await _capture_signals(bus)
    strategy = IVRankEntryStrategy(
        strategy_id="iv-entry",
        bus=bus,
        clock=clock,
        symbol="AAPL260620P00145000",
        metrics_provider=lambda _event: IVMetrics(
            current_iv=0.42,
            iv_rank=72.5,
            iv_percentile=80.0,
            history_count=252,
        ),
        order_factory=_order_factory,
        entry_rank_threshold=70.0,
    )

    await strategy.on_market_event(_market())

    assert len(signals) == 1
    signal = signals[0]
    assert signal.direction == "ENTER"
    assert signal.reason == "IV rank entry"
    assert signal.proposed_order.strategy_id == "iv-entry"
    assert signal.proposed_order.legs[0].quantity == -1
    assert signal.context == {
        "current_iv": 0.42,
        "iv_rank": 72.5,
        "iv_percentile": 80.0,
        "history_count": 252,
    }


@pytest.mark.asyncio
async def test_low_iv_rank_does_not_emit_signal():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 8, 14, 30, tzinfo=UTC))
    signals = await _capture_signals(bus)
    strategy = IVRankEntryStrategy(
        strategy_id="iv-entry",
        bus=bus,
        clock=clock,
        symbol="AAPL260620P00145000",
        metrics_provider=lambda _event: IVMetrics(
            current_iv=0.30,
            iv_rank=69.9,
            iv_percentile=65.0,
            history_count=252,
        ),
        order_factory=_order_factory,
        entry_rank_threshold=70.0,
    )

    await strategy.on_market_event(_market())

    assert signals == []


@pytest.mark.asyncio
async def test_duplicate_high_iv_events_emit_only_one_entry_signal():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 8, 14, 30, tzinfo=UTC))
    signals = await _capture_signals(bus)
    strategy = IVRankEntryStrategy(
        strategy_id="iv-entry",
        bus=bus,
        clock=clock,
        symbol="AAPL260620P00145000",
        metrics_provider=lambda _event: IVMetrics(
            current_iv=0.42,
            iv_rank=72.5,
            iv_percentile=80.0,
            history_count=252,
        ),
        order_factory=_order_factory,
        entry_rank_threshold=70.0,
    )

    await strategy.on_market_event(_market())
    await strategy.on_market_event(_market())

    assert len(signals) == 1


@pytest.mark.asyncio
async def test_ignores_market_events_for_other_symbols():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 8, 14, 30, tzinfo=UTC))
    signals = await _capture_signals(bus)
    strategy = IVRankEntryStrategy(
        strategy_id="iv-entry",
        bus=bus,
        clock=clock,
        symbol="AAPL260620P00145000",
        metrics_provider=lambda _event: IVMetrics(
            current_iv=0.42,
            iv_rank=72.5,
            iv_percentile=80.0,
            history_count=252,
        ),
        order_factory=_order_factory,
        entry_rank_threshold=70.0,
    )

    await strategy.on_market_event(_market("MSFT260620P00145000"))

    assert signals == []


def test_rejects_invalid_entry_rank_threshold():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 8, 14, 30, tzinfo=UTC))

    with pytest.raises(ValueError):
        IVRankEntryStrategy(
            strategy_id="iv-entry",
            bus=bus,
            clock=clock,
            symbol="AAPL260620P00145000",
            metrics_provider=lambda _event: None,
            order_factory=_order_factory,
            entry_rank_threshold=101.0,
        )
