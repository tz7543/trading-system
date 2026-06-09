from datetime import UTC, datetime

from core.events import MarketEvent
from core.models import Contract, Leg
from strategy.managed_exit import ManagedExit


def _opt(symbol: str) -> Contract:
    return Contract(
        symbol=symbol, sec_type="OPT", expiry="20260620", strike=150.0, right="C"
    )


def _market(symbol: str, bid: float, ask: float) -> MarketEvent:
    return MarketEvent(
        symbol=symbol,
        timestamp=datetime(2026, 6, 10, 14, 30, tzinfo=UTC),
        bid=bid,
        ask=ask,
        last=(bid + ask) / 2,
        volume=100,
    )


def test_credit_spread_entry_cost():
    legs = [
        Leg(contract=_opt("SHORT_PUT"), quantity=-1, entry_price=3.00),
        Leg(contract=_opt("LONG_PUT"), quantity=1, entry_price=1.50),
    ]
    me = ManagedExit(legs)
    assert me.entry_cost == -150.0  # received $150 credit


def test_credit_spread_50pct_profit():
    legs = [
        Leg(contract=_opt("SHORT_PUT"), quantity=-1, entry_price=3.00),
        Leg(contract=_opt("LONG_PUT"), quantity=1, entry_price=1.50),
    ]
    me = ManagedExit(legs, profit_target=0.50)

    market = {
        "SHORT_PUT": _market("SHORT_PUT", 0.70, 0.80),  # mid=0.75
        "LONG_PUT": _market("LONG_PUT", 0.00, 0.00),  # mid=0.00
    }
    # current_value = 0.75 * -1 * 100 + 0.00 * 1 * 100 = -75
    # pnl = -75 - (-150) = 75
    # profit_pct = 75 / 150 = 0.50
    assert me.should_exit(market) is True


def test_credit_spread_not_yet_at_target():
    legs = [
        Leg(contract=_opt("SHORT_PUT"), quantity=-1, entry_price=3.00),
        Leg(contract=_opt("LONG_PUT"), quantity=1, entry_price=1.50),
    ]
    me = ManagedExit(legs, profit_target=0.50)

    market = {
        "SHORT_PUT": _market("SHORT_PUT", 1.90, 2.10),  # mid=2.00
        "LONG_PUT": _market("LONG_PUT", 0.70, 0.80),  # mid=0.75
    }
    # current_value = 2.00 * -1 * 100 + 0.75 * 1 * 100 = -125
    # pnl = -125 - (-150) = 25
    # profit_pct = 25 / 150 = 0.167
    assert me.should_exit(market) is False
    pct = me.profit_pct(market)
    assert pct is not None
    assert abs(pct - 0.167) < 0.01


def test_missing_market_data_returns_none():
    legs = [
        Leg(contract=_opt("SHORT_PUT"), quantity=-1, entry_price=3.00),
        Leg(contract=_opt("LONG_PUT"), quantity=1, entry_price=1.50),
    ]
    me = ManagedExit(legs)
    assert me.profit_pct({}) is None
    assert me.should_exit({}) is False


def test_debit_spread_roi():
    """For debit spreads, profit_pct is ROI on cost, not pct of max profit."""
    legs = [
        Leg(contract=_opt("LONG_CALL"), quantity=1, entry_price=5.00),
        Leg(contract=_opt("SHORT_CALL"), quantity=-1, entry_price=2.00),
    ]
    me = ManagedExit(legs, profit_target=0.50)
    # entry_cost = 5.00 * 1 * 100 + 2.00 * -1 * 100 = 300 (paid $300 debit)

    market = {
        "LONG_CALL": _market("LONG_CALL", 7.40, 7.60),  # mid=7.50
        "SHORT_CALL": _market("SHORT_CALL", 2.90, 3.10),  # mid=3.00
    }
    # current_value = 450, pnl = 150, roi = 150/300 = 0.50
    assert me.should_exit(market) is True


def test_iron_condor_full_profit():
    legs = [
        Leg(contract=_opt("BUY_P"), quantity=1, entry_price=0.50),
        Leg(contract=_opt("SELL_P"), quantity=-1, entry_price=1.50),
        Leg(contract=_opt("SELL_C"), quantity=-1, entry_price=1.50),
        Leg(contract=_opt("BUY_C"), quantity=1, entry_price=0.50),
    ]
    me = ManagedExit(legs, profit_target=0.50)
    # entry_cost = (0.50*1 + 1.50*-1 + 1.50*-1 + 0.50*1) * 100 = -200

    market = {
        "BUY_P": _market("BUY_P", 0.00, 0.10),
        "SELL_P": _market("SELL_P", 0.40, 0.60),
        "SELL_C": _market("SELL_C", 0.40, 0.60),
        "BUY_C": _market("BUY_C", 0.00, 0.10),
    }
    # current = 0.05*1*100 + 0.50*-1*100 + 0.50*-1*100 + 0.05*1*100 = -90
    # pnl = -90 - (-200) = 110
    # profit_pct = 110 / 200 = 0.55
    assert me.should_exit(market) is True
