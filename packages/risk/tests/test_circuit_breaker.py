from core.models import Contract, Leg, Position
from risk.circuit_breaker import CircuitBreaker


def test_initially_not_triggered():
    cb = CircuitBreaker()
    assert cb.is_triggered is False


def test_trigger_sets_state():
    cb = CircuitBreaker()
    cb.trigger()
    assert cb.is_triggered is True


def test_flatten_orders_reverses_positions():
    cb = CircuitBreaker()
    positions = [
        Position(
            legs=[
                Leg(contract=Contract(symbol="AAPL", sec_type="STK"), quantity=100),
            ],
            strategy_id="momentum_1",
        ),
        Position(
            legs=[
                Leg(
                    contract=Contract(
                        symbol="AAPL260620C00150000",
                        sec_type="OPT",
                        expiry="20260620",
                        strike=150.0,
                        right="C",
                    ),
                    quantity=-2,
                ),
                Leg(
                    contract=Contract(
                        symbol="AAPL260620P00140000",
                        sec_type="OPT",
                        expiry="20260620",
                        strike=140.0,
                        right="P",
                    ),
                    quantity=2,
                ),
            ],
            strategy_id="ic_1",
        ),
    ]
    orders = cb.flatten_orders(positions)
    assert len(orders) == 2
    # First position: STK +100 → flatten with -100
    assert orders[0].legs[0].quantity == -100
    assert orders[0].order_type == "MKT"
    assert orders[0].strategy_id == "momentum_1"
    # Second position: OPT -2,+2 → flatten with +2,-2
    assert orders[1].legs[0].quantity == 2
    assert orders[1].legs[1].quantity == -2
    assert orders[1].order_type == "MKT"


def test_reset_clears_triggered():
    cb = CircuitBreaker()
    cb.trigger()
    assert cb.is_triggered is True
    cb.reset()
    assert cb.is_triggered is False
