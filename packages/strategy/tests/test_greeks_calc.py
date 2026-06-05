from core.models import Contract, Greeks, Leg
from strategy.greeks_calc import GreeksCalculator


def test_composite_single_opt():
    leg = Leg(
        contract=Contract(
            symbol="AAPL260620C00150000",
            sec_type="OPT",
            expiry="20260620",
            strike=150.0,
            right="C",
        ),
        quantity=1,
    )
    greeks_map = {
        "AAPL260620C00150000": Greeks(
            delta=0.50,
            gamma=0.03,
            vega=0.18,
            theta=-0.05,
        ),
    }
    result = GreeksCalculator.composite([leg], greeks_map)
    assert result.delta == 50.0  # 0.50 * 1 * 100
    assert result.gamma == 3.0  # 0.03 * 1 * 100
    assert result.vega == 18.0  # 0.18 * 1 * 100
    assert result.theta == -5.0  # -0.05 * 1 * 100


def test_composite_covered_call():
    """Discriminating test: STK delta + OPT delta must end up on same unit basis."""
    stk_leg = Leg(
        contract=Contract(symbol="AAPL", sec_type="STK"),
        quantity=100,
    )
    call_leg = Leg(
        contract=Contract(
            symbol="AAPL260620C00150000",
            sec_type="OPT",
            expiry="20260620",
            strike=150.0,
            right="C",
        ),
        quantity=-1,
    )
    greeks_map = {
        "AAPL260620C00150000": Greeks(delta=0.50),
    }
    result = GreeksCalculator.composite([stk_leg, call_leg], greeks_map)
    assert result.delta == 50.0
    assert result.gamma == 0.0
    assert result.vega == 0.0


def test_composite_iron_condor():
    legs = [
        Leg(
            contract=Contract(
                symbol="IC_P_BUY",
                sec_type="OPT",
                expiry="20260620",
                strike=140.0,
                right="P",
            ),
            quantity=1,
        ),
        Leg(
            contract=Contract(
                symbol="IC_P_SELL",
                sec_type="OPT",
                expiry="20260620",
                strike=145.0,
                right="P",
            ),
            quantity=-1,
        ),
        Leg(
            contract=Contract(
                symbol="IC_C_SELL",
                sec_type="OPT",
                expiry="20260620",
                strike=155.0,
                right="C",
            ),
            quantity=-1,
        ),
        Leg(
            contract=Contract(
                symbol="IC_C_BUY",
                sec_type="OPT",
                expiry="20260620",
                strike=160.0,
                right="C",
            ),
            quantity=1,
        ),
    ]
    greeks_map = {
        "IC_P_BUY": Greeks(delta=-0.15, gamma=0.02, vega=0.10, theta=-0.03),
        "IC_P_SELL": Greeks(delta=-0.30, gamma=0.04, vega=0.15, theta=-0.05),
        "IC_C_SELL": Greeks(delta=0.30, gamma=0.04, vega=0.15, theta=-0.05),
        "IC_C_BUY": Greeks(delta=0.15, gamma=0.02, vega=0.10, theta=-0.03),
    }
    result = GreeksCalculator.composite(legs, greeks_map)
    assert abs(result.delta) < 0.01
    assert result.gamma == -4.0
    assert result.theta == 4.0


def test_composite_missing_greeks():
    legs = [
        Leg(
            contract=Contract(
                symbol="AAPL260620C00150000",
                sec_type="OPT",
                expiry="20260620",
                strike=150.0,
                right="C",
            ),
            quantity=1,
        ),
        Leg(
            contract=Contract(
                symbol="MISSING",
                sec_type="OPT",
                expiry="20260620",
                strike=160.0,
                right="C",
            ),
            quantity=1,
        ),
    ]
    greeks_map = {
        "AAPL260620C00150000": Greeks(delta=0.50, gamma=0.03),
    }
    result = GreeksCalculator.composite(legs, greeks_map)
    assert result.delta == 50.0
    assert result.gamma == 3.0
