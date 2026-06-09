from core.models import Greeks, Leg


class GreeksCalculator:
    @staticmethod
    def composite(legs: list[Leg], greeks_map: dict[str, Greeks]) -> Greeks:
        result = Greeks()
        for leg in legs:
            if leg.contract.sec_type == "STK":
                result = result + Greeks(delta=leg.quantity)
                continue
            g = greeks_map.get(leg.contract.symbol)
            if g is None:
                continue
            result = result + g * (leg.quantity * leg.contract.multiplier)
        return result
