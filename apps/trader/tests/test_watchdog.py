from datetime import UTC, datetime, timedelta

from core import MarketEvent, SimClock
from core.models import Contract
from trading_app.watchdog import MarketDataWatchdog


def _mkt(symbol: str, contract: Contract | None = None) -> MarketEvent:
    return MarketEvent(
        symbol=symbol,
        timestamp=datetime(2026, 6, 10, tzinfo=UTC),
        bid=1.0,
        ask=2.0,
        last=1.5,
        volume=10,
        contract=contract,
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


# ---------------------------------------------------------------------------
# Fix 3: per-contract watchdog key
# ---------------------------------------------------------------------------


async def test_per_contract_key_stk_still_flowing_opt_stale():
    """AAPL STK ticks keep flowing; AAPL OPT contract goes silent past
    stale_seconds.  check_now() must return exactly one alert and its
    message must contain the OPT contract key (not bare 'AAPL')."""
    clock = SimClock(datetime(2026, 6, 10, tzinfo=UTC))
    dog = MarketDataWatchdog(clock=clock, stale_seconds=60.0)

    opt_contract = Contract(
        symbol="AAPL",
        sec_type="OPT",
        expiry="20260620",
        strike=150.0,
        right="C",
    )
    stk_contract = Contract(symbol="AAPL", sec_type="STK")

    # Seed both at t=0
    await dog.on_market(_mkt("AAPL", contract=opt_contract))
    await dog.on_market(_mkt("AAPL", contract=stk_contract))

    # Advance time past stale threshold
    clock.advance_to(clock.now() + timedelta(seconds=61))

    # Refresh STK only
    await dog.on_market(_mkt("AAPL", contract=stk_contract))

    alerts = dog.check_now()

    # Exactly one alert: the OPT contract
    assert len(alerts) == 1
    # Message must contain the OPT contract key, not bare "AAPL"
    opt_key = "AAPL|20260620|150.0|C"
    assert opt_key in alerts[0].message
