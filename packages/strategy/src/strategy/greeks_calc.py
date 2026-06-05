from core.models import Greeks, Leg


class GreeksCalculator:
    @staticmethod
    def composite(legs: list[Leg], greeks_map: dict[str, Greeks]) -> Greeks:
        delta = 0.0
        gamma = 0.0
        vega = 0.0
        theta = 0.0
        for leg in legs:
            if leg.contract.sec_type == "STK":
                delta += leg.quantity
                continue
            g = greeks_map.get(leg.contract.symbol)
            if g is None:
                continue
            mult = leg.contract.multiplier
            delta += g.delta * leg.quantity * mult
            gamma += g.gamma * leg.quantity * mult
            vega += g.vega * leg.quantity * mult
            theta += g.theta * leg.quantity * mult
        return Greeks(delta=delta, gamma=gamma, vega=vega, theta=theta)
