from datetime import UTC, datetime

from core.events import AlertEvent, FillEvent, MarketEvent, OrderEvent, SignalEvent
from core.models import Contract, Greeks, Leg, Order


def test_market_event_stock():
    event = MarketEvent(
        symbol="AAPL",
        timestamp=datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        bid=150.0,
        ask=150.05,
        last=150.02,
        volume=100,
    )
    assert event.symbol == "AAPL"
    assert event.model_greeks is None
    assert event.bar is None
    assert event.bid_greeks is None


def test_market_event_option_with_greeks():
    g = Greeks(
        delta=0.45,
        gamma=0.03,
        vega=0.12,
        theta=-0.05,
        implied_vol=0.25,
        underlying_price=150.0,
    )
    event = MarketEvent(
        symbol="AAPL260117C00150000",
        timestamp=datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        bid=3.50,
        ask=3.60,
        last=3.55,
        volume=50,
        model_greeks=g,
    )
    assert event.model_greeks is not None
    assert event.model_greeks.delta == 0.45


def test_signal_event():
    c = Contract(
        symbol="AAPL", sec_type="OPT", expiry="20260117", strike=150.0, right="C"
    )
    order = Order(legs=[Leg(contract=c, quantity=1)], strategy_id="ic_1")
    event = SignalEvent(
        strategy_id="ic_1",
        timestamp=datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        direction="ENTER",
        proposed_order=order,
        reason="IV spike above threshold",
        context={"iv_rank": 0.85},
    )
    assert event.direction == "ENTER"
    assert event.context["iv_rank"] == 0.85


def test_order_event():
    c = Contract(symbol="AAPL", sec_type="STK")
    order = Order(legs=[Leg(contract=c, quantity=100)], strategy_id="test")
    event = OrderEvent(
        order=order,
        timestamp=datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        approved_by="PreTradeValidator",
    )
    assert event.approved_by == "PreTradeValidator"


def test_fill_event():
    c = Contract(symbol="AAPL", sec_type="STK")
    leg = Leg(contract=c, quantity=100, entry_price=150.0)
    event = FillEvent(
        order_id="ORD-001",
        legs_filled=[leg],
        timestamp=datetime(2026, 1, 2, 9, 30, 1, tzinfo=UTC),
        commission=1.0,
    )
    assert event.order_id == "ORD-001"
    assert event.commission == 1.0
    assert event.legs_filled[0].entry_price == 150.0


def test_alert_event():
    event = AlertEvent(
        message="Delta breach",
        value=550.0,
        timestamp=datetime(2026, 1, 2, 10, 0, tzinfo=UTC),
    )
    assert event.message == "Delta breach"
    assert event.value == 550.0
