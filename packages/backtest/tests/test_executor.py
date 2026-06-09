from datetime import UTC, datetime

import pytest

from backtest.executor import SimulatedExecutor
from core.bus import EventBus
from core.clock import SimClock
from core.events import FillEvent, MarketEvent, OrderEvent
from core.models import Contract, Leg, Order


def _stk_market(last=150.0):
    return MarketEvent(
        symbol="AAPL",
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        bid=149.90,
        ask=150.10,
        last=last,
        volume=1000,
    )


def _opt_market(bid=5.00, ask=5.40):
    return MarketEvent(
        symbol="AAPL260620C00150000",
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        bid=bid,
        ask=ask,
        last=5.20,
        volume=100,
    )


def _order_event(legs, strategy_id="test"):
    order = Order(legs=legs, strategy_id=strategy_id)
    return OrderEvent(
        order=order,
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        approved_by="PreTradeValidator",
    )


@pytest.mark.asyncio
async def test_fill_stk_at_last_price():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC))
    executor = SimulatedExecutor(bus, clock)
    received: list[FillEvent] = []

    async def capture_fill(event: FillEvent) -> None:
        received.append(event)

    bus.subscribe(FillEvent, capture_fill)
    legs = [Leg(contract=Contract(symbol="AAPL", sec_type="STK"), quantity=100)]
    await executor.on_order(_order_event(legs))
    snapshot = {"AAPL": _stk_market(last=150.0)}
    fills = await executor.fill_pending(snapshot)
    assert len(fills) == 1
    assert fills[0].legs_filled[0].entry_price == 150.0
    # Commission: max($0.005/share * 100, $1.00) = $1.00
    assert fills[0].commission == pytest.approx(1.00)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_fill_opt_with_orats_slippage():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC))
    executor = SimulatedExecutor(bus, clock)
    legs = [
        Leg(
            contract=Contract(
                symbol="AAPL260620C00150000",
                sec_type="OPT",
                expiry="20260620",
                strike=150.0,
                right="C",
            ),
            quantity=-1,
        )
    ]
    await executor.on_order(_order_event(legs))
    snapshot = {"AAPL260620C00150000": _opt_market(bid=5.00, ask=5.40)}
    fills = await executor.fill_pending(snapshot)
    assert len(fills) == 1
    # 1-leg sell: ask - spread * fill_quality = 5.40 - 0.40 * 0.75 = 5.10
    assert fills[0].legs_filled[0].entry_price == pytest.approx(5.10)
    # Commission: max($0.65/contract * 1, $1.00) = $1.00
    assert fills[0].commission == pytest.approx(1.00)


@pytest.mark.asyncio
async def test_no_fill_when_empty():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC))
    executor = SimulatedExecutor(bus, clock)
    fills = await executor.fill_pending({"AAPL": _stk_market()})
    assert fills == []


@pytest.mark.asyncio
async def test_all_or_nothing_multi_leg():
    """If any leg lacks market data, the entire order stays pending."""
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC))
    executor = SimulatedExecutor(bus, clock)
    legs = [
        Leg(contract=Contract(symbol="AAPL", sec_type="STK"), quantity=100),
        Leg(
            contract=Contract(
                symbol="AAPL260620C00150000",
                sec_type="OPT",
                expiry="20260620",
                strike=150.0,
                right="C",
            ),
            quantity=-1,
        ),
    ]
    await executor.on_order(_order_event(legs))
    # Only STK in snapshot, OPT missing
    snapshot = {"AAPL": _stk_market()}
    fills = await executor.fill_pending(snapshot)
    assert fills == []
    # Order should still be pending — fill again with complete snapshot
    snapshot["AAPL260620C00150000"] = _opt_market()
    fills = await executor.fill_pending(snapshot)
    assert len(fills) == 1
    assert len(fills[0].legs_filled) == 2
    # STK $0.50 + OPT $0.65 = $1.15 > $1.00 floor
    assert fills[0].commission == pytest.approx(1.15)


def test_fill_quality_by_leg_count():
    from backtest.executor import _fill_quality

    assert _fill_quality(1) == 0.75
    assert _fill_quality(2) == 0.66
    assert _fill_quality(3) == 0.56
    assert _fill_quality(4) == 0.53
    assert _fill_quality(6) == 0.53


def test_fill_price_orats_single_leg():
    from backtest.executor import _fill_price

    market = _opt_market(bid=1.00, ask=2.00)
    buy_leg = Leg(
        contract=Contract(
            symbol="AAPL260620C00150000",
            sec_type="OPT",
            expiry="20260620",
            strike=150.0,
            right="C",
        ),
        quantity=1,
    )
    sell_leg = Leg(
        contract=Contract(
            symbol="AAPL260620C00150000",
            sec_type="OPT",
            expiry="20260620",
            strike=150.0,
            right="C",
        ),
        quantity=-1,
    )
    # 1-leg buy: bid + spread * 0.75 = 1.00 + 1.00 * 0.75 = 1.75
    assert _fill_price(buy_leg, market, num_legs=1) == pytest.approx(1.75)
    # 1-leg sell: ask - spread * 0.75 = 2.00 - 1.00 * 0.75 = 1.25
    assert _fill_price(sell_leg, market, num_legs=1) == pytest.approx(1.25)
