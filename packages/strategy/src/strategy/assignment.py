from core.events import AssignmentEvent
from core.models import Contract, Leg, Order, Position


def is_partial_assignment(
    position: Position,
    assignment: AssignmentEvent,
) -> bool:
    leg = matching_short_option_leg(position, assignment)
    return assignment.contracts_assigned < abs(leg.quantity)


def apply_assignment(
    position: Position,
    assignment: AssignmentEvent,
) -> Position:
    assigned_leg = matching_short_option_leg(position, assignment)
    open_contracts = abs(assigned_leg.quantity)
    if assignment.contracts_assigned > open_contracts:
        raise ValueError("contracts_assigned exceeds open quantity")

    adjusted_legs: list[Leg] = []
    stock_added = False
    for leg in position.legs:
        if leg is assigned_leg:
            remaining_quantity = leg.quantity + assignment.contracts_assigned
            if remaining_quantity:
                adjusted_legs.append(
                    Leg(
                        contract=leg.contract,
                        quantity=remaining_quantity,
                        entry_price=leg.entry_price,
                    )
                )
            continue

        if _is_matching_stock_leg(leg, assignment.assigned_contract):
            merged_quantity = leg.quantity + assignment.stock_quantity
            if merged_quantity:
                adjusted_legs.append(
                    Leg(
                        contract=leg.contract,
                        quantity=merged_quantity,
                        entry_price=leg.entry_price,
                    )
                )
            stock_added = True
            continue

        adjusted_legs.append(leg)

    if not stock_added and assignment.stock_quantity:
        adjusted_legs.append(
            Leg(
                contract=Contract(
                    symbol=assignment.assigned_contract.symbol,
                    sec_type="STK",
                    currency=assignment.assigned_contract.currency,
                    exchange=assignment.assigned_contract.exchange,
                ),
                quantity=assignment.stock_quantity,
                entry_price=assignment.underlying_price,
            )
        )

    return Position(
        legs=adjusted_legs,
        strategy_id=position.strategy_id,
        greeks=position.greeks,
        unrealized_pnl=position.unrealized_pnl,
    )


def matching_short_option_leg(
    position: Position,
    assignment: AssignmentEvent,
) -> Leg:
    for leg in position.legs:
        if leg.quantity < 0 and _same_option_contract(
            leg.contract,
            assignment.assigned_contract,
        ):
            return leg
    raise ValueError("no matching short option leg")


def build_roll_order(
    leg: Leg,
    new_expiry: str,
    new_strike: float | None = None,
    strategy_id: str = "",
) -> Order:
    if leg.contract.sec_type != "OPT":
        raise ValueError("roll leg must be an option")
    if leg.quantity == 0:
        raise ValueError("roll leg quantity must be non-zero")
    if new_expiry == leg.contract.expiry:
        raise ValueError("new_expiry must differ from current expiry")

    replacement_contract = Contract(
        symbol=leg.contract.symbol,
        sec_type="OPT",
        currency=leg.contract.currency,
        exchange=leg.contract.exchange,
        expiry=new_expiry,
        strike=leg.contract.strike if new_strike is None else new_strike,
        right=leg.contract.right,
        multiplier=leg.contract.multiplier,
    )
    return Order(
        legs=[
            Leg(contract=leg.contract, quantity=-leg.quantity),
            Leg(contract=replacement_contract, quantity=leg.quantity),
        ],
        strategy_id=strategy_id,
    )


def _same_option_contract(left: Contract, right: Contract) -> bool:
    return (
        left.sec_type == "OPT"
        and right.sec_type == "OPT"
        and left.symbol == right.symbol
        and left.expiry == right.expiry
        and left.strike == right.strike
        and left.right == right.right
    )


def _is_matching_stock_leg(leg: Leg, assigned_contract: Contract) -> bool:
    return (
        leg.contract.sec_type == "STK"
        and leg.contract.symbol == assigned_contract.symbol
    )
