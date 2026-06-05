from core.models import Leg, Order, Position


class CircuitBreaker:
    def __init__(self) -> None:
        self._triggered = False

    @property
    def is_triggered(self) -> bool:
        return self._triggered

    def trigger(self) -> None:
        self._triggered = True

    def reset(self) -> None:
        self._triggered = False

    def flatten_orders(self, positions: list[Position]) -> list[Order]:
        orders: list[Order] = []
        for pos in positions:
            flatten_legs = [
                Leg(contract=leg.contract, quantity=-leg.quantity) for leg in pos.legs
            ]
            orders.append(
                Order(
                    legs=flatten_legs,
                    strategy_id=pos.strategy_id,
                    order_type="MKT",
                )
            )
        return orders
