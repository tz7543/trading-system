from datetime import datetime

from core.models import (
    Bar,
    Contract,
    Greeks,
    Leg,
    OptionChain,
    Order,
    Position,
    RiskLimits,
    ValidationResult,
)


def test_bar():
    bar = Bar(
        timestamp=datetime(2026, 1, 2, 9, 30),
        symbol="AAPL",
        open=150.0,
        high=152.0,
        low=149.0,
        close=151.0,
        volume=1000,
    )
    assert bar.symbol == "AAPL"
    assert bar.close == 151.0


def test_greeks_defaults():
    g = Greeks()
    assert g.delta == 0.0
    assert g.gamma == 0.0
    assert g.implied_vol == 0.0
    assert g.underlying_price == 0.0


def test_contract_stock_defaults():
    c = Contract(symbol="AAPL", sec_type="STK")
    assert c.currency == "USD"
    assert c.exchange == "SMART"
    assert c.expiry == ""
    assert c.right == ""
    assert c.multiplier == 100
    assert c.con_id == 0


def test_contract_option():
    c = Contract(
        symbol="AAPL",
        sec_type="OPT",
        expiry="20260117",
        strike=150.0,
        right="C",
    )
    assert c.sec_type == "OPT"
    assert c.strike == 150.0
    assert c.right == "C"


def test_leg_defaults():
    c = Contract(symbol="AAPL", sec_type="OPT", expiry="20260117", strike=150.0, right="C")
    leg = Leg(contract=c, quantity=1)
    assert leg.entry_price == 0.0
    assert leg.quantity == 1


def test_option_chain():
    chain = OptionChain(
        exchange="SMART",
        trading_class="AAPL",
        multiplier=100,
        expirations=["20260117", "20260221"],
        strikes=[150.0, 152.5, 155.0],
    )
    assert len(chain.expirations) == 2
    assert len(chain.strikes) == 3


def test_risk_limits():
    limits = RiskLimits(
        max_delta=500.0,
        max_vega=1000.0,
        max_drawdown=0.05,
        max_position_size=10,
        max_margin_utilization=0.8,
    )
    assert limits.max_drawdown == 0.05
    assert limits.max_margin_utilization == 0.8


def test_validation_result_approved():
    v = ValidationResult(approved=True)
    assert v.approved is True
    assert v.reason is None


def test_validation_result_rejected():
    v = ValidationResult(approved=False, reason="Delta limit exceeded")
    assert v.approved is False
    assert v.reason == "Delta limit exceeded"


def test_position_defaults():
    c = Contract(symbol="AAPL", sec_type="STK")
    leg = Leg(contract=c, quantity=100)
    pos = Position(legs=[leg], strategy_id="test_strategy")
    assert pos.greeks is None
    assert pos.unrealized_pnl == 0.0
    assert len(pos.legs) == 1


def test_order_defaults():
    c = Contract(symbol="AAPL", sec_type="OPT", expiry="20260117", strike=150.0, right="C")
    leg = Leg(contract=c, quantity=1)
    order = Order(legs=[leg], strategy_id="iron_condor_1")
    assert order.order_type == "LMT"
    assert order.time_in_force == "DAY"
    assert order.limit_price is None


def test_order_with_all_fields():
    c = Contract(symbol="AAPL", sec_type="STK")
    leg = Leg(contract=c, quantity=100, entry_price=150.0)
    order = Order(
        legs=[leg],
        strategy_id="momentum_1",
        order_type="MKT",
        limit_price=None,
        time_in_force="GTC",
    )
    assert order.order_type == "MKT"
    assert order.time_in_force == "GTC"
