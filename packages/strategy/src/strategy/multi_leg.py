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
