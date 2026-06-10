from datetime import UTC, datetime, timedelta

from core import MarketEvent, SimClock
from trading_app.watchdog import MarketDataWatchdog


def _mkt(symbol: str) -> MarketEvent:
    return MarketEvent(
        symbol=symbol,
        timestamp=datetime(2026, 6, 10, tzinfo=UTC),
        bid=1.0,
        ask=2.0,
        last=1.5,
        volume=10,
    )


async def test_stale_symbol_alerts_once_until_recovery():
    clock = SimClock(datetime(2026, 6, 10, tzinfo=UTC))
    dog = MarketDataWatchdog(clock=clock, stale_seconds=60.0)
    await dog.on_market(_mkt("AAPL"))
    clock.advance_to(clock.now() + timedelta(seconds=61))
    assert len(dog.check_now()) == 1
    clock.advance_to(clock.now() + timedelta(seconds=61))
    assert dog.check_now() == []  # cooldown: no repeat alert
    await dog.on_market(_mkt("AAPL"))  # fresh tick resets
    clock.advance_to(clock.now() + timedelta(seconds=61))
    assert len(dog.check_now()) == 1  # alerts again after reset


async def test_fresh_data_no_alert():
    clock = SimClock(datetime(2026, 6, 10, tzinfo=UTC))
    dog = MarketDataWatchdog(clock=clock, stale_seconds=60.0)
    await dog.on_market(_mkt("AAPL"))
    clock.advance_to(clock.now() + timedelta(seconds=30))
    assert dog.check_now() == []
