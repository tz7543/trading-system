import pytest

from strategy.multi_leg import (
    bear_call_spread,
    bear_put_spread,
    bull_call_spread,
    bull_put_spread,
    calendar_spread,
    call_butterfly,
    cash_secured_put,
    collar,
    covered_call,
    diagonal_spread,
    iron_butterfly,
    iron_condor,
    protective_put,
    put_butterfly,
    straddle,
    strangle,
)


def test_iron_condor():
    order = iron_condor(
        underlying="AAPL",
        expiry="20260620",
        put_buy_strike=140.0,
        put_sell_strike=145.0,
        call_sell_strike=155.0,
        call_buy_strike=160.0,
        quantity=2,
        strategy_id="ic_1",
    )
    assert len(order.legs) == 4
    assert order.strategy_id == "ic_1"
    # Buy put (lower)
    assert order.legs[0].contract.strike == 140.0
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == 2
    # Sell put
    assert order.legs[1].contract.strike == 145.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == -2
    # Sell call
    assert order.legs[2].contract.strike == 155.0
    assert order.legs[2].contract.right == "C"
    assert order.legs[2].quantity == -2
    # Buy call (higher)
    assert order.legs[3].contract.strike == 160.0
    assert order.legs[3].contract.right == "C"
    assert order.legs[3].quantity == 2


def test_bull_call_spread():
    order = bull_call_spread(
        underlying="AAPL",
        expiry="20260620",
        buy_strike=150.0,
        sell_strike=160.0,
        strategy_id="bcs_1",
    )
    assert len(order.legs) == 2
    assert order.legs[0].contract.strike == 150.0
    assert order.legs[0].contract.right == "C"
    assert order.legs[0].quantity == 1
    assert order.legs[1].contract.strike == 160.0
    assert order.legs[1].contract.right == "C"
    assert order.legs[1].quantity == -1


def test_covered_call():
    order = covered_call(
        underlying="AAPL",
        expiry="20260620",
        call_strike=155.0,
        quantity=2,
        strategy_id="cc_1",
    )
    assert len(order.legs) == 2
    # Stock leg: 100 shares per contract x quantity
    assert order.legs[0].contract.sec_type == "STK"
    assert order.legs[0].contract.symbol == "AAPL"
    assert order.legs[0].quantity == 200  # 100 * 2
    # Call leg: short
    assert order.legs[1].contract.sec_type == "OPT"
    assert order.legs[1].contract.strike == 155.0
    assert order.legs[1].contract.right == "C"
    assert order.legs[1].quantity == -2


def test_straddle():
    order = straddle(
        underlying="AAPL",
        expiry="20260620",
        strike=150.0,
        quantity=3,
        strategy_id="strad_1",
    )
    assert len(order.legs) == 2
    assert order.legs[0].contract.strike == 150.0
    assert order.legs[0].contract.right == "C"
    assert order.legs[0].quantity == 3
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == 3


def test_bear_put_spread():
    order = bear_put_spread(
        underlying="AAPL",
        expiry="20260620",
        buy_strike=160.0,
        sell_strike=150.0,
        quantity=1,
        strategy_id="bps_1",
    )
    assert len(order.legs) == 2
    assert order.strategy_id == "bps_1"
    assert order.legs[0].contract.strike == 160.0
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == 1
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == -1


def test_bear_put_spread_invalid_strikes():
    with pytest.raises(ValueError, match="buy_strike must be greater than sell_strike"):
        bear_put_spread(
            underlying="AAPL",
            expiry="20260620",
            buy_strike=150.0,
            sell_strike=160.0,
        )


def test_bull_put_spread():
    order = bull_put_spread(
        underlying="AAPL",
        expiry="20260620",
        sell_strike=155.0,
        buy_strike=150.0,
        quantity=2,
        strategy_id="bps_credit_1",
    )
    assert len(order.legs) == 2
    assert order.strategy_id == "bps_credit_1"
    assert order.legs[0].contract.strike == 155.0
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == -2
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == 2


def test_bull_put_spread_invalid_strikes():
    with pytest.raises(ValueError, match="sell_strike must be greater than buy_strike"):
        bull_put_spread(
            underlying="AAPL",
            expiry="20260620",
            sell_strike=150.0,
            buy_strike=155.0,
        )


def test_bear_call_spread():
    order = bear_call_spread(
        underlying="AAPL",
        expiry="20260620",
        sell_strike=155.0,
        buy_strike=160.0,
        quantity=1,
        strategy_id="bcs_credit_1",
    )
    assert len(order.legs) == 2
    assert order.strategy_id == "bcs_credit_1"
    assert order.legs[0].contract.strike == 155.0
    assert order.legs[0].contract.right == "C"
    assert order.legs[0].quantity == -1
    assert order.legs[1].contract.strike == 160.0
    assert order.legs[1].contract.right == "C"
    assert order.legs[1].quantity == 1


def test_bear_call_spread_invalid_strikes():
    with pytest.raises(ValueError, match="sell_strike must be less than buy_strike"):
        bear_call_spread(
            underlying="AAPL",
            expiry="20260620",
            sell_strike=160.0,
            buy_strike=155.0,
        )


def test_strangle():
    order = strangle(
        underlying="AAPL",
        expiry="20260620",
        put_strike=145.0,
        call_strike=155.0,
        quantity=2,
        strategy_id="strng_1",
    )
    assert len(order.legs) == 2
    assert order.strategy_id == "strng_1"
    assert order.legs[0].contract.strike == 145.0
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == 2
    assert order.legs[1].contract.strike == 155.0
    assert order.legs[1].contract.right == "C"
    assert order.legs[1].quantity == 2


def test_strangle_invalid_strikes():
    with pytest.raises(ValueError, match="put_strike must be less than call_strike"):
        strangle(
            underlying="AAPL",
            expiry="20260620",
            put_strike=155.0,
            call_strike=145.0,
        )


def test_call_butterfly():
    order = call_butterfly(
        underlying="AAPL",
        expiry="20260620",
        lower_strike=145.0,
        middle_strike=150.0,
        upper_strike=155.0,
        quantity=1,
        strategy_id="cfly_1",
    )
    assert len(order.legs) == 3
    assert order.strategy_id == "cfly_1"
    assert order.legs[0].contract.strike == 145.0
    assert order.legs[0].contract.right == "C"
    assert order.legs[0].quantity == 1
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "C"
    assert order.legs[1].quantity == -2
    assert order.legs[2].contract.strike == 155.0
    assert order.legs[2].contract.right == "C"
    assert order.legs[2].quantity == 1


def test_call_butterfly_non_equidistant():
    with pytest.raises(ValueError, match="wings must be equidistant"):
        call_butterfly(
            underlying="AAPL",
            expiry="20260620",
            lower_strike=145.0,
            middle_strike=150.0,
            upper_strike=160.0,
        )


def test_call_butterfly_invalid_order():
    with pytest.raises(ValueError, match="lower < middle < upper"):
        call_butterfly(
            underlying="AAPL",
            expiry="20260620",
            lower_strike=155.0,
            middle_strike=150.0,
            upper_strike=145.0,
        )


def test_put_butterfly():
    order = put_butterfly(
        underlying="AAPL",
        expiry="20260620",
        lower_strike=145.0,
        middle_strike=150.0,
        upper_strike=155.0,
        quantity=1,
        strategy_id="pfly_1",
    )
    assert len(order.legs) == 3
    assert order.strategy_id == "pfly_1"
    assert order.legs[0].contract.strike == 145.0
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == 1
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == -2
    assert order.legs[2].contract.strike == 155.0
    assert order.legs[2].contract.right == "P"
    assert order.legs[2].quantity == 1


def test_put_butterfly_non_equidistant():
    with pytest.raises(ValueError, match="wings must be equidistant"):
        put_butterfly(
            underlying="AAPL",
            expiry="20260620",
            lower_strike=140.0,
            middle_strike=150.0,
            upper_strike=155.0,
        )


def test_iron_butterfly():
    order = iron_butterfly(
        underlying="AAPL",
        expiry="20260620",
        put_buy_strike=140.0,
        middle_strike=150.0,
        call_buy_strike=160.0,
        quantity=1,
        strategy_id="ifly_1",
    )
    assert len(order.legs) == 4
    assert order.strategy_id == "ifly_1"
    assert order.legs[0].contract.strike == 140.0
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == 1
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == -1
    assert order.legs[2].contract.strike == 150.0
    assert order.legs[2].contract.right == "C"
    assert order.legs[2].quantity == -1
    assert order.legs[3].contract.strike == 160.0
    assert order.legs[3].contract.right == "C"
    assert order.legs[3].quantity == 1


def test_iron_butterfly_invalid_strikes():
    with pytest.raises(ValueError, match="put_buy < middle < call_buy"):
        iron_butterfly(
            underlying="AAPL",
            expiry="20260620",
            put_buy_strike=160.0,
            middle_strike=150.0,
            call_buy_strike=140.0,
        )


def test_collar():
    order = collar(
        underlying="AAPL",
        expiry="20260620",
        put_strike=145.0,
        call_strike=155.0,
        quantity=1,
        strategy_id="collar_1",
    )
    assert len(order.legs) == 3
    assert order.strategy_id == "collar_1"
    assert order.legs[0].contract.sec_type == "STK"
    assert order.legs[0].quantity == 100
    assert order.legs[1].contract.strike == 145.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == 1
    assert order.legs[2].contract.strike == 155.0
    assert order.legs[2].contract.right == "C"
    assert order.legs[2].quantity == -1


def test_collar_invalid_strikes():
    with pytest.raises(ValueError, match="put_strike must be less than call_strike"):
        collar(
            underlying="AAPL",
            expiry="20260620",
            put_strike=160.0,
            call_strike=150.0,
        )


def test_protective_put():
    order = protective_put(
        underlying="AAPL",
        expiry="20260620",
        put_strike=145.0,
        quantity=2,
        strategy_id="pp_1",
    )
    assert len(order.legs) == 2
    assert order.strategy_id == "pp_1"
    assert order.legs[0].contract.sec_type == "STK"
    assert order.legs[0].quantity == 200
    assert order.legs[1].contract.strike == 145.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == 2


def test_cash_secured_put():
    order = cash_secured_put(
        underlying="AAPL",
        expiry="20260620",
        strike=145.0,
        quantity=3,
        strategy_id="csp_1",
    )
    assert len(order.legs) == 1
    assert order.strategy_id == "csp_1"
    assert order.legs[0].contract.strike == 145.0
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == -3


def test_calendar_spread_calls():
    order = calendar_spread(
        underlying="AAPL",
        strike=150.0,
        near_expiry="20260620",
        far_expiry="20260718",
        right="C",
        quantity=1,
        strategy_id="cal_1",
    )
    assert len(order.legs) == 2
    assert order.strategy_id == "cal_1"
    assert order.legs[0].contract.expiry == "20260620"
    assert order.legs[0].contract.strike == 150.0
    assert order.legs[0].contract.right == "C"
    assert order.legs[0].quantity == -1
    assert order.legs[1].contract.expiry == "20260718"
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "C"
    assert order.legs[1].quantity == 1


def test_calendar_spread_puts():
    order = calendar_spread(
        underlying="AAPL",
        strike=150.0,
        near_expiry="20260620",
        far_expiry="20260718",
        right="P",
        quantity=2,
        strategy_id="cal_2",
    )
    assert len(order.legs) == 2
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == -2
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == 2


def test_calendar_spread_same_expiry():
    with pytest.raises(ValueError, match="near_expiry must differ from far_expiry"):
        calendar_spread(
            underlying="AAPL",
            strike=150.0,
            near_expiry="20260620",
            far_expiry="20260620",
            right="C",
        )


def test_diagonal_spread():
    order = diagonal_spread(
        underlying="AAPL",
        near_expiry="20260620",
        near_strike=155.0,
        far_expiry="20260718",
        far_strike=150.0,
        right="C",
        quantity=1,
        strategy_id="diag_1",
    )
    assert len(order.legs) == 2
    assert order.strategy_id == "diag_1"
    assert order.legs[0].contract.expiry == "20260620"
    assert order.legs[0].contract.strike == 155.0
    assert order.legs[0].contract.right == "C"
    assert order.legs[0].quantity == -1
    assert order.legs[1].contract.expiry == "20260718"
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "C"
    assert order.legs[1].quantity == 1


def test_diagonal_spread_same_expiry():
    with pytest.raises(ValueError, match="near_expiry must differ from far_expiry"):
        diagonal_spread(
            underlying="AAPL",
            near_expiry="20260620",
            near_strike=155.0,
            far_expiry="20260620",
            far_strike=150.0,
            right="C",
        )
