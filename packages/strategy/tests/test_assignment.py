from datetime import UTC, datetime

import pytest

from core.events import AssignmentEvent
from core.models import Contract, Leg, Position, assignment_stock_quantity
from strategy.assignment import (
    apply_assignment,
    build_roll_order,
    is_partial_assignment,
)


def _option(right: str = "P", strike: float = 145.0) -> Contract:
    return Contract(
        symbol="AAPL",
        sec_type="OPT",
        expiry="20260620",
        strike=strike,
        right=right,
    )


def _assignment(
    contract: Contract,
    contracts_assigned: int = 1,
) -> AssignmentEvent:
    return AssignmentEvent(
        strategy_id="short-option",
        timestamp=datetime(2026, 6, 20, 21, 0, tzinfo=UTC),
        assigned_contract=contract,
        contracts_assigned=contracts_assigned,
        stock_quantity=assignment_stock_quantity(contract, contracts_assigned),
    )


def test_short_put_assignment_reduces_option_and_adds_long_stock():
    contract = _option("P")
    position = Position(
        strategy_id="short-option",
        legs=[Leg(contract=contract, quantity=-2)],
    )

    result = apply_assignment(position, _assignment(contract, contracts_assigned=1))

    assert result.strategy_id == "short-option"
    assert result.legs[0].contract == contract
    assert result.legs[0].quantity == -1
    assert result.legs[1].contract == Contract(symbol="AAPL", sec_type="STK")
    assert result.legs[1].quantity == 100


def test_short_call_assignment_reduces_option_and_adds_short_stock():
    contract = _option("C", strike=155.0)
    position = Position(
        strategy_id="short-option",
        legs=[Leg(contract=contract, quantity=-1)],
    )

    result = apply_assignment(position, _assignment(contract, contracts_assigned=1))

    assert len(result.legs) == 1
    assert result.legs[0].contract == Contract(symbol="AAPL", sec_type="STK")
    assert result.legs[0].quantity == -100


def test_assignment_merges_existing_stock_leg():
    contract = _option("P")
    position = Position(
        strategy_id="short-option",
        legs=[
            Leg(contract=contract, quantity=-1),
            Leg(contract=Contract(symbol="AAPL", sec_type="STK"), quantity=50),
        ],
    )

    result = apply_assignment(position, _assignment(contract, contracts_assigned=1))

    assert len(result.legs) == 1
    assert result.legs[0].contract.sec_type == "STK"
    assert result.legs[0].quantity == 150


def test_partial_assignment_detection():
    contract = _option("P")
    position = Position(
        strategy_id="short-option",
        legs=[Leg(contract=contract, quantity=-3)],
    )

    assert is_partial_assignment(position, _assignment(contract, 1)) is True
    assert is_partial_assignment(position, _assignment(contract, 3)) is False


def test_over_assignment_raises_value_error():
    contract = _option("P")
    position = Position(
        strategy_id="short-option",
        legs=[Leg(contract=contract, quantity=-1)],
    )

    with pytest.raises(ValueError, match="contracts_assigned exceeds open quantity"):
        apply_assignment(position, _assignment(contract, contracts_assigned=2))


def test_assignment_without_matching_short_option_raises_value_error():
    contract = _option("P")
    position = Position(
        strategy_id="short-option",
        legs=[Leg(contract=contract, quantity=1)],
    )

    with pytest.raises(ValueError, match="no matching short option leg"):
        apply_assignment(position, _assignment(contract, contracts_assigned=1))


def test_build_roll_order_closes_existing_leg_and_opens_replacement():
    leg = Leg(contract=_option("P"), quantity=-1)

    order = build_roll_order(
        leg,
        new_expiry="20260718",
        new_strike=140.0,
        strategy_id="roll-short-put",
    )

    assert order.strategy_id == "roll-short-put"
    assert order.legs[0].contract.expiry == "20260620"
    assert order.legs[0].quantity == 1
    assert order.legs[1].contract.expiry == "20260718"
    assert order.legs[1].contract.strike == 140.0
    assert order.legs[1].quantity == -1


def test_build_roll_order_rejects_stock_leg():
    with pytest.raises(ValueError, match="roll leg must be an option"):
        build_roll_order(
            Leg(contract=Contract(symbol="AAPL", sec_type="STK"), quantity=100),
            new_expiry="20260718",
        )


def test_build_roll_order_rejects_same_expiry():
    with pytest.raises(ValueError, match="new_expiry must differ"):
        build_roll_order(Leg(contract=_option("P"), quantity=-1), "20260620")
