import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import ib_async as ibi
import pytest

from core.bus import EventBus
from core.clock import LiveClock
from core.events import AssignmentEvent, FillEvent, OrderEvent, OrderStatusEvent
from core.models import Contract, Leg, Order
from execution.live_gateway import LiveGateway, _derive_status


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


def _make_trade(
    order_id: int = 1,
    status: str = "Submitted",
    filled: float = 0.0,
    remaining: float = 100.0,
):
    """Build a real ib_async Trade with real eventkit Events."""
    trade = ibi.Trade(
        contract=ibi.Stock("AAPL", "SMART", "USD"),
        order=ibi.Order(orderId=order_id, action="BUY", totalQuantity=100),
        orderStatus=ibi.OrderStatus(
            orderId=order_id,
            status=status,
            filled=filled,
            remaining=remaining,
            avgFillPrice=0.0,
        ),
    )
    return trade


def _make_fill(
    shares: float = 100.0,
    avg_price: float = 150.5,
    side: str = "BOT",
    commission: float = 1.0,
):
    return ibi.Fill(
        contract=ibi.Stock("AAPL", "SMART", "USD"),
        execution=ibi.Execution(shares=shares, avgPrice=avg_price, side=side),
        commissionReport=ibi.CommissionReport(commission=commission),
        time=datetime(2026, 6, 5, 14, 30, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_fill_publishes_fill_event():
    mock_ib = _make_mock_ib()
    trade = _make_trade(order_id=1, remaining=0.0)
    mock_ib.placeOrder.return_value = trade

    bus = EventBus()
    clock = LiveClock()
    received: list[FillEvent] = []

    async def capture(event: FillEvent) -> None:
        received.append(event)

    bus.subscribe(FillEvent, capture)

    gateway = LiveGateway(bus, clock, mock_ib)
    event = _stk_order_event()
    await gateway.on_order(event)

    # Emit fillEvent with (trade, fill) two-arg semantics
    fill = _make_fill()
    trade.fillEvent.emit(trade, fill)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0].order_id == event.order_id
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


# ---------------------------------------------------------------------------
# New Task 5 tests — status closure, incremental fills, error visibility
# ---------------------------------------------------------------------------


def _order_event_single_leg(strategy_id: str = "s1") -> OrderEvent:
    legs = [
        Leg(
            contract=Contract(symbol="AAPL", sec_type="STK", con_id=265598),
            quantity=100,
        )
    ]
    order = Order(
        legs=legs, strategy_id=strategy_id, order_type="LMT", limit_price=150.0
    )
    return OrderEvent(
        order=order,
        timestamp=datetime(2026, 6, 5, 14, 30, tzinfo=UTC),
        approved_by="risk",
    )


def _order_event_bag_unqualified() -> OrderEvent:
    """BAG order whose legs have con_id=0 — triggers ValueError in _build_bag."""
    legs = [
        Leg(
            contract=Contract(
                symbol="AAPL",
                sec_type="OPT",
                expiry="20260620",
                strike=150.0,
                right="C",
                con_id=0,
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
                con_id=0,
            ),
            quantity=1,
        ),
    ]
    order = Order(legs=legs, strategy_id="s1", order_type="LMT", limit_price=-0.50)
    return OrderEvent(
        order=order,
        timestamp=datetime(2026, 6, 5, 14, 30, tzinfo=UTC),
        approved_by="risk",
    )


def _gateway_env():
    mock_ib = _make_mock_ib()
    trade = ibi.Trade(
        contract=ibi.Stock("AAPL", "SMART", "USD"),
        order=ibi.Order(orderId=42, action="BUY", totalQuantity=100),
        orderStatus=ibi.OrderStatus(
            orderId=42, status="Submitted", filled=0, remaining=100, avgFillPrice=0.0
        ),
    )
    mock_ib.placeOrder.return_value = trade
    bus = EventBus()
    clock = LiveClock()
    received_status: list[OrderStatusEvent] = []

    async def cap_status(e: OrderStatusEvent) -> None:
        received_status.append(e)

    bus.subscribe(OrderStatusEvent, cap_status)
    gw = LiveGateway(bus, clock, mock_ib)
    return bus, gw, mock_ib, trade, received_status


@pytest.mark.asyncio
async def test_submitted_status_published_on_place():
    _bus, gateway, _ib, trade, received = _gateway_env()
    event = _order_event_single_leg()
    await gateway.on_order(event)
    assert len(received) >= 1
    assert received[0].status == "SUBMITTED"
    assert received[0].order_id == event.order_id
    assert received[0].broker_order_id == str(trade.orderStatus.orderId)


@pytest.mark.asyncio
async def test_terminal_inactive_with_error_maps_rejected():
    _bus, gateway, _ib, trade, received = _gateway_env()
    event = _order_event_single_leg()
    await gateway.on_order(event)

    trade.orderStatus.status = "Inactive"
    trade.orderStatus.filled = 0
    trade.orderStatus.remaining = 100
    trade.log.append(
        ibi.TradeLogEntry(
            time=datetime(2026, 6, 5, 14, 31, tzinfo=UTC),
            status="Inactive",
            message="margin insufficient",
            errorCode=201,
        )
    )
    trade.statusEvent.emit(trade)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    statuses = [e.status for e in received]
    assert "REJECTED" in statuses
    rejected = next(e for e in received if e.status == "REJECTED")
    assert "margin" in rejected.reason


@pytest.mark.asyncio
async def test_cancel_after_warning_is_cancelled_not_rejected():
    _bus, gateway, _ib, trade, received = _gateway_env()
    event = _order_event_single_leg()
    await gateway.on_order(event)

    # Warning log entry with nonzero errorCode, then a clean cancellation
    trade.log.append(
        ibi.TradeLogEntry(
            time=datetime(2026, 6, 5, 14, 31, tzinfo=UTC),
            status="Submitted",
            message="held for review",
            errorCode=399,
        )
    )
    trade.log.append(
        ibi.TradeLogEntry(
            time=datetime(2026, 6, 5, 14, 32, tzinfo=UTC),
            status="Cancelled",
            message="",
            errorCode=0,
        )
    )
    trade.orderStatus.status = "Cancelled"
    trade.orderStatus.filled = 0
    trade.orderStatus.remaining = 100
    trade.statusEvent.emit(trade)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    statuses = [e.status for e in received]
    assert "CANCELLED" in statuses
    assert "REJECTED" not in statuses


@pytest.mark.asyncio
async def test_incremental_fills_no_double_count():
    bus, gateway, _ib, trade, _statuses = _gateway_env()
    fills_received: list[FillEvent] = []

    async def cap_fill(e: FillEvent) -> None:
        fills_received.append(e)

    bus.subscribe(FillEvent, cap_fill)
    event = _order_event_single_leg()
    await gateway.on_order(event)

    # First partial fill: 50 shares, 50 remaining
    trade.orderStatus.filled = 50
    trade.orderStatus.remaining = 50
    fill1 = ibi.Fill(
        contract=ibi.Stock("AAPL", "SMART", "USD"),
        execution=ibi.Execution(shares=50.0, avgPrice=150.0, side="BOT"),
        commissionReport=ibi.CommissionReport(commission=0.5),
        time=datetime(2026, 6, 5, 14, 31, tzinfo=UTC),
    )
    trade.fillEvent.emit(trade, fill1)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # Second partial fill: 50 more, 0 remaining
    trade.orderStatus.filled = 100
    trade.orderStatus.remaining = 0
    fill2 = ibi.Fill(
        contract=ibi.Stock("AAPL", "SMART", "USD"),
        execution=ibi.Execution(shares=50.0, avgPrice=151.0, side="BOT"),
        commissionReport=ibi.CommissionReport(commission=0.5),
        time=datetime(2026, 6, 5, 14, 32, tzinfo=UTC),
    )
    trade.fillEvent.emit(trade, fill2)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(fills_received) == 2
    assert fills_received[0].legs_filled[0].quantity == 50
    assert fills_received[1].legs_filled[0].quantity == 50
    assert all(f.order_id == event.order_id for f in fills_received)
    assert all(f.strategy_id == "s1" for f in fills_received)


@pytest.mark.asyncio
async def test_partial_status_from_fill_remaining():
    _bus, gateway, _ib, trade, status_received = _gateway_env()
    event = _order_event_single_leg()
    await gateway.on_order(event)

    # After a fill with remaining > 0, _on_fill calls _on_status → PARTIAL
    trade.orderStatus.filled = 50
    trade.orderStatus.remaining = 50
    fill = ibi.Fill(
        contract=ibi.Stock("AAPL", "SMART", "USD"),
        execution=ibi.Execution(shares=50.0, avgPrice=150.0, side="BOT"),
        commissionReport=ibi.CommissionReport(commission=0.5),
        time=datetime(2026, 6, 5, 14, 31, tzinfo=UTC),
    )
    trade.fillEvent.emit(trade, fill)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    statuses = [e.status for e in status_received]
    assert "PARTIAL" in statuses


@pytest.mark.asyncio
async def test_submitted_not_regressed_after_partial():
    """After a PARTIAL status, a subsequent statusEvent with filled>0 emits PARTIAL, not SUBMITTED."""
    _bus, gateway, _ib, trade, status_received = _gateway_env()
    event = _order_event_single_leg()
    await gateway.on_order(event)

    # Trigger a fill → PARTIAL
    trade.orderStatus.filled = 50
    trade.orderStatus.remaining = 50
    fill = ibi.Fill(
        contract=ibi.Stock("AAPL", "SMART", "USD"),
        execution=ibi.Execution(shares=50.0, avgPrice=150.0, side="BOT"),
        commissionReport=ibi.CommissionReport(commission=0.5),
        time=datetime(2026, 6, 5, 14, 31, tzinfo=UTC),
    )
    trade.fillEvent.emit(trade, fill)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # IB echoes a "Submitted" status with filled=50 — should derive PARTIAL, not SUBMITTED
    trade.statusEvent.emit(trade)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    statuses = [e.status for e in status_received]
    partial_idx = statuses.index("PARTIAL")
    # No SUBMITTED may appear after the first PARTIAL
    assert "SUBMITTED" not in statuses[partial_idx + 1 :]
    # Exactly one PARTIAL (dedup memo prevents a second identical PARTIAL)
    assert statuses.count("PARTIAL") == 1


@pytest.mark.asyncio
async def test_bag_fills_attributed_per_leg():
    """BAG: two separate fillEvent emissions produce two FillEvents with distinct contract_keys."""
    mock_ib = _make_mock_ib()
    trade = ibi.Trade(
        contract=ibi.Contract(
            secType="BAG", symbol="AAPL", currency="USD", exchange="SMART"
        ),
        order=ibi.Order(orderId=99, action="BUY", totalQuantity=1),
        orderStatus=ibi.OrderStatus(
            orderId=99, status="Submitted", filled=0, remaining=1, avgFillPrice=0.0
        ),
    )
    mock_ib.placeOrder.return_value = trade
    bus = EventBus()
    clock = LiveClock()
    fills_received: list[FillEvent] = []

    async def cap(e: FillEvent) -> None:
        fills_received.append(e)

    bus.subscribe(FillEvent, cap)
    gw = LiveGateway(bus, clock, mock_ib)
    bag_event = _bag_order_event()
    await gw.on_order(bag_event)

    # Leg 1 fill: call 150
    trade.orderStatus.filled = 0
    trade.orderStatus.remaining = 1
    fill_call = ibi.Fill(
        contract=ibi.Option("AAPL", "20260620", 150.0, "C", "SMART"),
        execution=ibi.Execution(shares=1.0, avgPrice=2.0, side="SLD"),
        commissionReport=ibi.CommissionReport(commission=0.65),
        time=datetime(2026, 6, 5, 14, 31, tzinfo=UTC),
    )
    trade.fillEvent.emit(trade, fill_call)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # Leg 2 fill: call 155
    fill_put = ibi.Fill(
        contract=ibi.Option("AAPL", "20260620", 155.0, "C", "SMART"),
        execution=ibi.Execution(shares=1.0, avgPrice=1.5, side="BOT"),
        commissionReport=ibi.CommissionReport(commission=0.65),
        time=datetime(2026, 6, 5, 14, 31, tzinfo=UTC),
    )
    trade.fillEvent.emit(trade, fill_put)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(fills_received) == 2
    keys = {f.legs_filled[0].contract.strike for f in fills_received}
    assert keys == {150.0, 155.0}


@pytest.mark.asyncio
async def test_internal_error_publishes_rejected():
    """BAG legs with con_id=0 cause ValueError in _build_bag; on_order must not raise, must REJECT."""
    mock_ib = _make_mock_ib()
    bus = EventBus()
    clock = LiveClock()
    received_status: list[OrderStatusEvent] = []

    async def cap(e: OrderStatusEvent) -> None:
        received_status.append(e)

    bus.subscribe(OrderStatusEvent, cap)
    gw = LiveGateway(bus, clock, mock_ib)
    event = _order_event_bag_unqualified()
    await gw.on_order(event)  # must not raise

    mock_ib.placeOrder.assert_not_called()
    assert len(received_status) >= 1
    assert received_status[-1].status == "REJECTED"
    assert "con_id" in received_status[-1].reason


# ---------------------------------------------------------------------------
# Unit tests for _derive_status
# ---------------------------------------------------------------------------


def test_derive_status_filled():
    trade = ibi.Trade(
        contract=ibi.Stock("AAPL", "SMART", "USD"),
        order=ibi.Order(),
        orderStatus=ibi.OrderStatus(),
    )
    status, reason = _derive_status("Filled", 100, trade)
    assert status == "FILLED"
    assert reason == ""


def test_derive_status_inactive_error_code_rejected():
    trade = ibi.Trade(
        contract=ibi.Stock("AAPL", "SMART", "USD"),
        order=ibi.Order(),
        orderStatus=ibi.OrderStatus(),
    )
    trade.log.append(
        ibi.TradeLogEntry(
            time=datetime(2026, 6, 5, tzinfo=UTC),
            status="Inactive",
            message="margin",
            errorCode=201,
        )
    )
    status, reason = _derive_status("Inactive", 0, trade)
    assert status == "REJECTED"
    assert reason == "margin"


def test_derive_status_cancelled_no_error():
    trade = ibi.Trade(
        contract=ibi.Stock("AAPL", "SMART", "USD"),
        order=ibi.Order(),
        orderStatus=ibi.OrderStatus(),
    )
    trade.log.append(
        ibi.TradeLogEntry(
            time=datetime(2026, 6, 5, tzinfo=UTC),
            status="Cancelled",
            message="",
            errorCode=0,
        )
    )
    status, reason = _derive_status("Cancelled", 0, trade)
    assert status == "CANCELLED"
    assert reason == ""


def test_derive_status_submitted_no_fill():
    trade = ibi.Trade(
        contract=ibi.Stock("AAPL", "SMART", "USD"),
        order=ibi.Order(),
        orderStatus=ibi.OrderStatus(),
    )
    status, reason = _derive_status("Submitted", 0, trade)
    assert status == "SUBMITTED"
    assert reason == ""


def test_derive_status_submitted_with_fill_is_partial():
    trade = ibi.Trade(
        contract=ibi.Stock("AAPL", "SMART", "USD"),
        order=ibi.Order(),
        orderStatus=ibi.OrderStatus(),
    )
    status, reason = _derive_status("Submitted", 50, trade)
    assert status == "PARTIAL"
    assert reason == ""


def test_derive_status_unknown_returns_none():
    trade = ibi.Trade(
        contract=ibi.Stock("AAPL", "SMART", "USD"),
        order=ibi.Order(),
        orderStatus=ibi.OrderStatus(),
    )
    status, reason = _derive_status("SomeUnknownStatus", 0, trade)
    assert status is None
    assert reason == ""
