import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import ib_async as ibi
import pytest
from eventkit import Event

from core.bus import EventBus
from core.clock import LiveClock
from core.events import AssignmentEvent, FillEvent, OrderEvent
from core.models import Contract, Leg, Order
from execution.live_gateway import LiveGateway


def _make_mock_ib():
    ib = MagicMock()
    ib.placeOrder = MagicMock()
    return ib


def _stk_order_event():
    legs = [
        Leg(
            contract=Contract(symbol="AAPL", sec_type="STK", con_id=265598),
            quantity=100,
        )
    ]
    order = Order(legs=legs, strategy_id="test", order_type="LMT", limit_price=150.0)
    return OrderEvent(
        order=order,
        timestamp=datetime(2026, 6, 5, 14, 30, tzinfo=UTC),
        approved_by="risk",
    )


def _bag_order_event():
    legs = [
        Leg(
            contract=Contract(
                symbol="AAPL",
                sec_type="OPT",
                expiry="20260620",
                strike=150.0,
                right="C",
                con_id=100001,
            ),
            quantity=-1,
        ),
        Leg(
            contract=Contract(
                symbol="AAPL",
                sec_type="OPT",
                expiry="20260620",
                strike=155.0,
                right="C",
                con_id=100002,
            ),
            quantity=1,
        ),
    ]
    order = Order(legs=legs, strategy_id="test", order_type="LMT", limit_price=-0.50)
    return OrderEvent(
        order=order,
        timestamp=datetime(2026, 6, 5, 14, 30, tzinfo=UTC),
        approved_by="risk",
    )


@pytest.mark.asyncio
async def test_single_leg_places_order():
    mock_ib = _make_mock_ib()
    mock_trade = MagicMock()
    mock_trade.orderStatus.orderId = 1
    mock_ib.placeOrder.return_value = mock_trade

    bus = EventBus()
    clock = LiveClock()
    gateway = LiveGateway(bus, clock, mock_ib)
    await gateway.on_order(_stk_order_event())

    mock_ib.placeOrder.assert_called_once()
    args = mock_ib.placeOrder.call_args
    ib_contract = args[0][0]
    ib_order = args[0][1]
    assert isinstance(ib_contract, ibi.Stock)
    assert ib_contract.symbol == "AAPL"
    assert ib_order.action == "BUY"
    assert ib_order.totalQuantity == 100
    assert ib_order.lmtPrice == 150.0


@pytest.mark.asyncio
async def test_multi_leg_places_bag_order():
    mock_ib = _make_mock_ib()
    mock_trade = MagicMock()
    mock_trade.orderStatus.orderId = 2
    mock_ib.placeOrder.return_value = mock_trade

    bus = EventBus()
    clock = LiveClock()
    gateway = LiveGateway(bus, clock, mock_ib)
    await gateway.on_order(_bag_order_event())

    mock_ib.placeOrder.assert_called_once()
    args = mock_ib.placeOrder.call_args
    ib_contract = args[0][0]
    ib_order = args[0][1]
    assert ib_contract.secType == "BAG"
    assert ib_contract.symbol == "AAPL"
    assert len(ib_contract.comboLegs) == 2
    # First leg: sell 1 AAPL call 150
    assert ib_contract.comboLegs[0].conId == 100001
    assert ib_contract.comboLegs[0].action == "SELL"
    assert ib_contract.comboLegs[0].ratio == 1
    # Second leg: buy 1 AAPL call 155
    assert ib_contract.comboLegs[1].conId == 100002
    assert ib_contract.comboLegs[1].action == "BUY"
    assert ib_contract.comboLegs[1].ratio == 1
    # Credit spread → negative lmtPrice
    assert ib_order.lmtPrice == -0.50


@pytest.mark.asyncio
async def test_fill_publishes_fill_event():
    mock_ib = _make_mock_ib()
    mock_trade = MagicMock()
    mock_trade.orderStatus.orderId = 1
    mock_trade.isDone.return_value = True
    mock_trade.fills = [
        MagicMock(
            execution=MagicMock(shares=100.0, avgPrice=150.5, side="BOT"),
            contract=ibi.Stock("AAPL", "SMART", "USD"),
            commissionReport=MagicMock(commission=1.00),
        )
    ]
    # Use a real eventkit.Event — MagicMock's __iadd__ doesn't work correctly
    # because += rebinds the attribute, losing the mock reference.
    mock_trade.filledEvent = Event("filledEvent")
    mock_ib.placeOrder.return_value = mock_trade

    bus = EventBus()
    clock = LiveClock()
    received: list[FillEvent] = []

    async def capture(event: FillEvent) -> None:
        received.append(event)

    bus.subscribe(FillEvent, capture)

    gateway = LiveGateway(bus, clock, mock_ib)
    await gateway.on_order(_stk_order_event())

    # Emit the filledEvent — the gateway's handler will call _on_filled → _publish_fill
    mock_trade.filledEvent.emit(mock_trade)
    await asyncio.sleep(0)  # let ensure_future run
    await asyncio.sleep(0)  # let _publish_fill complete

    assert len(received) == 1
    assert received[0].order_id == "1"
    assert received[0].legs_filled[0].entry_price == 150.5
    assert received[0].commission == 1.00


@pytest.mark.asyncio
async def test_on_assignment_publishes_assignment_event():
    mock_ib = _make_mock_ib()
    bus = EventBus()
    clock = LiveClock()
    received: list[AssignmentEvent] = []

    async def capture(event: AssignmentEvent) -> None:
        received.append(event)

    bus.subscribe(AssignmentEvent, capture)
    gateway = LiveGateway(bus, clock, mock_ib)
    assigned_contract = Contract(
        symbol="AAPL",
        sec_type="OPT",
        expiry="20260620",
        strike=145.0,
        right="P",
    )

    await gateway.on_assignment(
        strategy_id="short-put",
        assigned_contract=assigned_contract,
        contracts_assigned=1,
        account="DU123",
        underlying_price=144.50,
    )

    assert len(received) == 1
    assert received[0].strategy_id == "short-put"
    assert received[0].assigned_contract == assigned_contract
    assert received[0].contracts_assigned == 1
    assert received[0].stock_quantity == 100
    assert received[0].account == "DU123"
    assert received[0].underlying_price == 144.50


def _bag_legs():
    return [
        Leg(
            contract=Contract(
                symbol="AAPL",
                sec_type="OPT",
                expiry="20260620",
                strike=150.0,
                right="C",
                con_id=100001,
            ),
            quantity=-1,
        ),
        Leg(
            contract=Contract(
                symbol="AAPL",
                sec_type="OPT",
                expiry="20260620",
                strike=155.0,
                right="C",
                con_id=100002,
            ),
            quantity=1,
        ),
    ]


@pytest.mark.asyncio
async def test_bag_credit_spread_sign_correction():
    mock_ib = _make_mock_ib()
    mock_trade = MagicMock()
    mock_trade.orderStatus.orderId = 3
    mock_ib.placeOrder.return_value = mock_trade

    order = Order(
        legs=_bag_legs(),
        strategy_id="test",
        order_type="LMT",
        limit_price=2.00,
        is_credit=True,
    )
    event = OrderEvent(
        order=order,
        timestamp=datetime(2026, 6, 5, 14, 30, tzinfo=UTC),
        approved_by="risk",
    )

    bus = EventBus()
    clock = LiveClock()
    gateway = LiveGateway(bus, clock, mock_ib)
    await gateway.on_order(event)

    args = mock_ib.placeOrder.call_args
    ib_order = args[0][1]
    assert ib_order.lmtPrice == -2.00


@pytest.mark.asyncio
async def test_bag_debit_spread_sign_correction():
    mock_ib = _make_mock_ib()
    mock_trade = MagicMock()
    mock_trade.orderStatus.orderId = 4
    mock_ib.placeOrder.return_value = mock_trade

    order = Order(
        legs=_bag_legs(),
        strategy_id="test",
        order_type="LMT",
        limit_price=-1.50,
        is_credit=False,
    )
    event = OrderEvent(
        order=order,
        timestamp=datetime(2026, 6, 5, 14, 30, tzinfo=UTC),
        approved_by="risk",
    )

    bus = EventBus()
    clock = LiveClock()
    gateway = LiveGateway(bus, clock, mock_ib)
    await gateway.on_order(event)

    args = mock_ib.placeOrder.call_args
    ib_order = args[0][1]
    assert ib_order.lmtPrice == 1.50


@pytest.mark.asyncio
async def test_bag_credit_already_negative_no_double_negate():
    mock_ib = _make_mock_ib()
    mock_trade = MagicMock()
    mock_trade.orderStatus.orderId = 6
    mock_ib.placeOrder.return_value = mock_trade

    order = Order(
        legs=_bag_legs(),
        strategy_id="test",
        order_type="LMT",
        limit_price=-2.00,
        is_credit=True,
    )
    event = OrderEvent(
        order=order,
        timestamp=datetime(2026, 6, 5, 14, 30, tzinfo=UTC),
        approved_by="risk",
    )

    bus = EventBus()
    clock = LiveClock()
    gateway = LiveGateway(bus, clock, mock_ib)
    await gateway.on_order(event)

    args = mock_ib.placeOrder.call_args
    ib_order = args[0][1]
    assert ib_order.lmtPrice == -2.00


@pytest.mark.asyncio
async def test_bag_debit_positive_passthrough():
    mock_ib = _make_mock_ib()
    mock_trade = MagicMock()
    mock_trade.orderStatus.orderId = 7
    mock_ib.placeOrder.return_value = mock_trade

    order = Order(
        legs=_bag_legs(),
        strategy_id="test",
        order_type="LMT",
        limit_price=1.50,
        is_credit=False,
    )
    event = OrderEvent(
        order=order,
        timestamp=datetime(2026, 6, 5, 14, 30, tzinfo=UTC),
        approved_by="risk",
    )

    bus = EventBus()
    clock = LiveClock()
    gateway = LiveGateway(bus, clock, mock_ib)
    await gateway.on_order(event)

    args = mock_ib.placeOrder.call_args
    ib_order = args[0][1]
    assert ib_order.lmtPrice == 1.50


@pytest.mark.asyncio
async def test_bag_non_guaranteed_params():
    mock_ib = _make_mock_ib()
    mock_trade = MagicMock()
    mock_trade.orderStatus.orderId = 5
    mock_ib.placeOrder.return_value = mock_trade

    order = Order(
        legs=_bag_legs(),
        strategy_id="test",
        order_type="LMT",
        limit_price=-0.50,
    )
    event = OrderEvent(
        order=order,
        timestamp=datetime(2026, 6, 5, 14, 30, tzinfo=UTC),
        approved_by="risk",
    )

    bus = EventBus()
    clock = LiveClock()
    gateway = LiveGateway(bus, clock, mock_ib)
    await gateway.on_order(event)

    args = mock_ib.placeOrder.call_args
    ib_order = args[0][1]
    assert any(
        tv.tag == "NonGuaranteed" and tv.value == "1"
        for tv in ib_order.smartComboRoutingParams
    )
