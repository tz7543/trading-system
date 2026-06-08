from typing import Literal

from core.models import Contract, Leg, Order


def iron_condor(
    underlying: str,
    expiry: str,
    put_buy_strike: float,
    put_sell_strike: float,
    call_sell_strike: float,
    call_buy_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if not (put_buy_strike < put_sell_strike < call_sell_strike < call_buy_strike):
        raise ValueError(
            f"Strikes must satisfy put_buy < put_sell < call_sell < call_buy, "
            f"got {put_buy_strike} < {put_sell_strike} < {call_sell_strike} < {call_buy_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=put_buy_strike,
                right="P",
            ),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=put_sell_strike,
                right="P",
            ),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=call_sell_strike,
                right="C",
            ),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=call_buy_strike,
                right="C",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def bull_call_spread(
    underlying: str,
    expiry: str,
    buy_strike: float,
    sell_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if buy_strike >= sell_strike:
        raise ValueError(
            f"buy_strike must be less than sell_strike, got {buy_strike} >= {sell_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=buy_strike,
                right="C",
            ),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=sell_strike,
                right="C",
            ),
            quantity=-quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def covered_call(
    underlying: str,
    expiry: str,
    call_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    legs = [
        Leg(
            contract=Contract(symbol=underlying, sec_type="STK"),
            quantity=100 * quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=call_strike,
                right="C",
            ),
            quantity=-quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def straddle(
    underlying: str,
    expiry: str,
    strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=strike,
                right="C",
            ),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=strike,
                right="P",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def bear_put_spread(
    underlying: str,
    expiry: str,
    buy_strike: float,
    sell_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if buy_strike <= sell_strike:
        raise ValueError(
            f"buy_strike must be greater than sell_strike, got {buy_strike} <= {sell_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=buy_strike,
                right="P",
            ),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=sell_strike,
                right="P",
            ),
            quantity=-quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def bull_put_spread(
    underlying: str,
    expiry: str,
    sell_strike: float,
    buy_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if sell_strike <= buy_strike:
        raise ValueError(
            f"sell_strike must be greater than buy_strike, got {sell_strike} <= {buy_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=sell_strike,
                right="P",
            ),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=buy_strike,
                right="P",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def bear_call_spread(
    underlying: str,
    expiry: str,
    sell_strike: float,
    buy_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if sell_strike >= buy_strike:
        raise ValueError(
            f"sell_strike must be less than buy_strike, got {sell_strike} >= {buy_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=sell_strike,
                right="C",
            ),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=buy_strike,
                right="C",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def strangle(
    underlying: str,
    expiry: str,
    put_strike: float,
    call_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if put_strike >= call_strike:
        raise ValueError(
            f"put_strike must be less than call_strike, got {put_strike} >= {call_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=put_strike,
                right="P",
            ),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=call_strike,
                right="C",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def call_butterfly(
    underlying: str,
    expiry: str,
    lower_strike: float,
    middle_strike: float,
    upper_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if not (lower_strike < middle_strike < upper_strike):
        raise ValueError(
            f"Strikes must satisfy lower < middle < upper, "
            f"got {lower_strike}, {middle_strike}, {upper_strike}"
        )
    if abs((middle_strike - lower_strike) - (upper_strike - middle_strike)) > 1e-9:
        raise ValueError(
            f"wings must be equidistant from middle, "
            f"got {middle_strike - lower_strike} vs {upper_strike - middle_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=lower_strike,
                right="C",
            ),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=middle_strike,
                right="C",
            ),
            quantity=-2 * quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=upper_strike,
                right="C",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def put_butterfly(
    underlying: str,
    expiry: str,
    lower_strike: float,
    middle_strike: float,
    upper_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if not (lower_strike < middle_strike < upper_strike):
        raise ValueError(
            f"Strikes must satisfy lower < middle < upper, "
            f"got {lower_strike}, {middle_strike}, {upper_strike}"
        )
    if abs((middle_strike - lower_strike) - (upper_strike - middle_strike)) > 1e-9:
        raise ValueError(
            f"wings must be equidistant from middle, "
            f"got {middle_strike - lower_strike} vs {upper_strike - middle_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=lower_strike,
                right="P",
            ),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=middle_strike,
                right="P",
            ),
            quantity=-2 * quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=upper_strike,
                right="P",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def iron_butterfly(
    underlying: str,
    expiry: str,
    put_buy_strike: float,
    middle_strike: float,
    call_buy_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if not (put_buy_strike < middle_strike < call_buy_strike):
        raise ValueError(
            f"Strikes must satisfy put_buy < middle < call_buy, "
            f"got {put_buy_strike}, {middle_strike}, {call_buy_strike}"
        )
    if abs((middle_strike - put_buy_strike) - (call_buy_strike - middle_strike)) > 1e-9:
        raise ValueError(
            f"wings must be equidistant from middle, "
            f"got {middle_strike - put_buy_strike} vs {call_buy_strike - middle_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=put_buy_strike,
                right="P",
            ),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=middle_strike,
                right="P",
            ),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=middle_strike,
                right="C",
            ),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=call_buy_strike,
                right="C",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def collar(
    underlying: str,
    expiry: str,
    put_strike: float,
    call_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if put_strike >= call_strike:
        raise ValueError(
            f"put_strike must be less than call_strike, got {put_strike} >= {call_strike}"
        )
    legs = [
        Leg(
            contract=Contract(symbol=underlying, sec_type="STK"),
            quantity=100 * quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=put_strike,
                right="P",
            ),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=call_strike,
                right="C",
            ),
            quantity=-quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def protective_put(
    underlying: str,
    expiry: str,
    put_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    legs = [
        Leg(
            contract=Contract(symbol=underlying, sec_type="STK"),
            quantity=100 * quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=put_strike,
                right="P",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def cash_secured_put(
    underlying: str,
    expiry: str,
    strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=strike,
                right="P",
            ),
            quantity=-quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def calendar_spread(
    underlying: str,
    strike: float,
    near_expiry: str,
    far_expiry: str,
    right: Literal["C", "P"] = "C",
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if near_expiry == far_expiry:
        raise ValueError(
            f"near_expiry must differ from far_expiry, both are {near_expiry}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=near_expiry,
                strike=strike,
                right=right,
            ),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=far_expiry,
                strike=strike,
                right=right,
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def diagonal_spread(
    underlying: str,
    near_expiry: str,
    near_strike: float,
    far_expiry: str,
    far_strike: float,
    right: Literal["C", "P"] = "C",
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if near_expiry == far_expiry:
        raise ValueError(
            f"near_expiry must differ from far_expiry, both are {near_expiry}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=near_expiry,
                strike=near_strike,
                right=right,
            ),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=far_expiry,
                strike=far_strike,
                right=right,
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)
