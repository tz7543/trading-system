import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import eventkit as ev
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from core.bus import EventBus
from core.clock import SimClock
from core.events import (
    AlertEvent,
    FillEvent,
    MarketEvent,
    OrderEvent,
    OrderStatusEvent,
    SignalEvent,
)
from core.models import Contract, Greeks, Leg, Order, RiskLimits, contract_key
from core.partitions import tick_partition_path
from risk import CircuitBreaker, PreTradeValidator, RealTimeMonitor
from strategy import DeltaHedgeStrategy, GreeksCalculator
from strategy.base import BaseStrategy
from trading_app.assembly import (
    AppRiskState,
    RiskPipeline,
    build_backtest_app,
    build_live_app,
    load_strategy,
    log_alerts,
    publish_market_data,
    subscribe_strategy,
)
from trading_app.config import BacktestConfig, StorageConfig, TraderConfig

TICK_SCHEMA = pa.schema(
    [
        ("timestamp", pa.timestamp("us", tz="UTC")),
        ("symbol", pa.string()),
        ("bid", pa.float64()),
        ("ask", pa.float64()),
        ("last", pa.float64()),
        ("volume", pa.int64()),
        ("model_delta", pa.float64()),
        ("model_gamma", pa.float64()),
        ("model_vega", pa.float64()),
        ("model_theta", pa.float64()),
        ("model_iv", pa.float64()),
        ("model_underlying", pa.float64()),
    ]
)


class BuyThenSellStrategy(BaseStrategy):
    def __init__(
        self,
        strategy_id: str,
        bus: EventBus,
        clock: SimClock,
        contract: Contract,
    ) -> None:
        super().__init__(strategy_id, bus, clock)
        self._contract = contract
        self._signals_sent = 0
        self.fills: list[FillEvent] = []

    async def on_market_event(self, event: MarketEvent) -> None:
        if self._signals_sent == 0:
            quantity = 100
        elif self._signals_sent == 1:
            quantity = -100
        else:
            return

        self._signals_sent += 1
        await self.signal(
            "ENTER" if quantity > 0 else "EXIT",
            Order(
                legs=[Leg(contract=self._contract, quantity=quantity)],
                strategy_id=self.strategy_id,
            ),
            reason="test signal",
            context={"last": event.last},
        )

    async def on_fill(self, event: FillEvent) -> None:
        self.fills.append(event)


@pytest.mark.asyncio
async def test_backtest_app_wires_strategy_risk_execution_and_storage(tmp_path):
    contract = Contract(symbol="AAPL", sec_type="STK")
    ticks_dir = tmp_path / "input_ticks"
    _write_ticks(
        ticks_dir,
        contract,
        "2026-06-04",
        [
            _tick(datetime(2026, 6, 4, 14, 30, tzinfo=UTC), 100.0),
            _tick(datetime(2026, 6, 4, 14, 31, tzinfo=UTC), 105.0),
            _tick(datetime(2026, 6, 4, 14, 32, tzinfo=UTC), 110.0),
        ],
    )
    config = TraderConfig(
        backtest=BacktestConfig(ticks_dir=ticks_dir),
        storage=StorageConfig(
            ticks_dir=tmp_path / "logged_ticks",
            decision_db=tmp_path / "decisions.duckdb",
            trade_db=tmp_path / "orders.db",
        ),
    )

    app = await build_backtest_app(
        config,
        contracts=[contract],
        start=datetime(2026, 6, 4, 14, 30, tzinfo=UTC),
    )
    try:
        strategy = BuyThenSellStrategy("test", app.bus, app.clock, contract)
        subscribe_strategy(app.bus, strategy)

        fills = await app.run()
        orders = await app.trade_store.query_orders("test")
        stored_fills = await app.trade_store.query_fills()
        decisions = await app.decision_logger.query(
            "SELECT strategy_id, risk_approved FROM decisions ORDER BY timestamp"
        )

        assert [fill.legs_filled[0].quantity for fill in fills] == [100, -100]
        assert [fill.legs_filled[0].entry_price for fill in fills] == [105.0, 110.0]
        assert len(strategy.fills) == 2
        assert len(orders) == 2
        assert len(stored_fills) == 2
        assert decisions == [
            {"strategy_id": "test", "risk_approved": True},
            {"strategy_id": "test", "risk_approved": True},
        ]
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_live_app_wires_order_events_to_gateway(tmp_path):
    ib = MagicMock()
    ib.disconnect = MagicMock()
    ib.isConnected = MagicMock(return_value=False)
    ib.disconnectedEvent = ev.Event("disconnectedEvent")
    trade = MagicMock()
    trade.orderStatus.orderId = 7
    trade.filledEvent = ev.Event("filledEvent")
    ib.placeOrder.return_value = trade
    config = TraderConfig(
        storage=StorageConfig(
            ticks_dir=tmp_path / "ticks",
            decision_db=tmp_path / "decisions.duckdb",
            trade_db=tmp_path / "orders.db",
        )
    )
    contract = Contract(symbol="AAPL", sec_type="STK")

    app = await build_live_app(config, ib=ib, contracts=[contract])
    try:
        await app.bus.publish(
            OrderEvent(
                order=Order(
                    legs=[Leg(contract=contract, quantity=1)],
                    strategy_id="live-test",
                    limit_price=100.0,
                ),
                timestamp=app.clock.now(),
                approved_by="test",
            )
        )

        ib.placeOrder.assert_called_once()
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_live_app_wires_delta_hedge_adjust_signal_to_gateway(tmp_path):
    ib = MagicMock()
    ib.disconnect = MagicMock()
    ib.isConnected = MagicMock(return_value=False)
    ib.disconnectedEvent = ev.Event("disconnectedEvent")
    ib.accountSummaryEvent = ev.Event("accountSummaryEvent")

    async def _account_summary(account=""):
        return [MagicMock(tag="NetLiquidation", value="1000000")]

    ib.accountSummaryAsync = _account_summary
    trade = MagicMock()
    trade.orderStatus.orderId = 8
    trade.filledEvent = ev.Event("filledEvent")
    ib.placeOrder.return_value = trade
    config = TraderConfig(
        storage=StorageConfig(
            ticks_dir=tmp_path / "ticks",
            decision_db=tmp_path / "decisions.duckdb",
            trade_db=tmp_path / "orders.db",
        )
    )
    contract = Contract(symbol="AAPL", sec_type="STK")

    app = await build_live_app(config, ib=ib, contracts=[contract])
    try:
        # live risk truth comes from AccountState; seed it so the signal passes
        await app.account_state.start()
        strategy = DeltaHedgeStrategy(
            strategy_id="delta-hedge",
            bus=app.bus,
            clock=app.clock,
            hedge_symbol="AAPL",
            greeks_provider=lambda: Greeks(delta=125.0),
            delta_threshold=25.0,
        )
        subscribe_strategy(app.bus, strategy)

        await app.bus.publish(
            MarketEvent(
                symbol="AAPL",
                timestamp=app.clock.now(),
                bid=149.95,
                ask=150.05,
                last=150.0,
                volume=1000,
            )
        )

        ib.placeOrder.assert_called_once()
        ib_order = ib.placeOrder.call_args[0][1]
        assert ib_order.action == "SELL"
        assert ib_order.totalQuantity == 125
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_risk_pipeline_blocks_orders_when_circuit_breaker_is_triggered():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 30, tzinfo=UTC))
    circuit_breaker = CircuitBreaker()
    circuit_breaker.trigger()
    published: list[OrderEvent] = []

    async def capture(event: OrderEvent) -> None:
        published.append(event)

    bus.subscribe(OrderEvent, capture)
    pipeline = RiskPipeline(
        bus=bus,
        validator=PreTradeValidator(_risk_limits()),
        clock=clock,
        circuit_breaker=circuit_breaker,
    )
    await pipeline.on_signal(_signal(clock, Contract(symbol="AAPL", sec_type="STK")))

    assert published == []


@pytest.mark.asyncio
async def test_risk_pipeline_publishes_monitor_alerts_and_triggers_circuit_breaker():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 30, tzinfo=UTC))
    circuit_breaker = CircuitBreaker()
    alerts: list[AlertEvent] = []

    async def capture(event: AlertEvent) -> None:
        alerts.append(event)

    bus.subscribe(AlertEvent, capture)
    pipeline = RiskPipeline(
        bus=bus,
        validator=PreTradeValidator(_risk_limits()),
        clock=clock,
        monitor=RealTimeMonitor(_risk_limits(), clock),
        circuit_breaker=circuit_breaker,
        portfolio_greeks_provider=lambda: Greeks(delta=250.0),
        equity_provider=lambda: 100000.0,
    )

    await pipeline.on_fill(
        FillEvent(order_id="sim-1", legs_filled=[], timestamp=clock.now(), commission=0)
    )

    assert circuit_breaker.is_triggered is True
    assert any("delta" in alert.message.lower() for alert in alerts)


@pytest.mark.asyncio
async def test_publish_market_data_sends_live_quotes_to_bus():
    bus = EventBus()
    contract = Contract(symbol="AAPL", sec_type="STK")
    event = MarketEvent(
        symbol="AAPL",
        timestamp=datetime(2026, 6, 4, 14, 30, tzinfo=UTC),
        bid=99.9,
        ask=100.1,
        last=100.0,
        volume=1000,
    )
    received: list[MarketEvent] = []

    async def capture(event: MarketEvent) -> None:
        received.append(event)

    bus.subscribe(MarketEvent, capture)
    await publish_market_data(bus, _FakeDataHandler([event]), [contract])

    assert received == [event]


def test_load_strategy_imports_configured_strategy(tmp_path, monkeypatch):
    module_path = tmp_path / "sample_strategy.py"
    module_path.write_text(
        """
from strategy.base import BaseStrategy


class SampleStrategy(BaseStrategy):
    def __init__(self, strategy_id, bus, clock, threshold):
        super().__init__(strategy_id, bus, clock)
        self.threshold = threshold

    async def on_market_event(self, event):
        pass

    async def on_fill(self, event):
        pass
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 30, tzinfo=UTC))

    strategy = load_strategy(
        "sample_strategy:SampleStrategy",
        strategy_id="sample",
        bus=bus,
        clock=clock,
        params={"threshold": 150.0},
    )

    assert strategy.strategy_id == "sample"
    assert strategy.threshold == 150.0


def test_app_risk_state_tracks_filled_positions_and_signal_greeks():
    state = AppRiskState(initial_equity=100000.0)
    contract = Contract(symbol="AAPL", sec_type="STK")
    fill = FillEvent(
        order_id="sim-1",
        legs_filled=[Leg(contract=contract, quantity=100, entry_price=105.0)],
        timestamp=datetime(2026, 6, 4, 14, 31, tzinfo=UTC),
        commission=1.0,
    )
    state.record_fill(fill)

    signal = SignalEvent(
        strategy_id="test",
        timestamp=fill.timestamp,
        direction="ENTER",
        proposed_order=Order(
            legs=[Leg(contract=contract, quantity=1)],
            strategy_id="test",
        ),
        reason="test",
        context={"proposed_greeks": {"delta": 25.0, "vega": 3.0}},
    )

    # strategy_id is now taken from FillEvent.strategy_id (was order_id in old code)
    assert state.positions()[0].strategy_id == ""
    assert state.equity() == 100000.0 - 100 * 105.0 - 1.0
    assert state.proposed_greeks(signal).delta == 25.0
    assert state.proposed_greeks(signal).vega == 3.0


# ---------------------------------------------------------------------------
# Task 6 helpers
# ---------------------------------------------------------------------------


def _opt(strike, right) -> Contract:
    return Contract(
        symbol="AAPL", sec_type="OPT", expiry="20991231", strike=strike, right=right
    )


def _clock() -> SimClock:
    return SimClock(datetime(2026, 6, 10, tzinfo=UTC))


def _now() -> datetime:
    return datetime(2026, 6, 10, tzinfo=UTC)


def _mkt(
    symbol: str, *, contract: Contract | None = None, model_greeks: Greeks | None = None
) -> MarketEvent:
    return MarketEvent(
        symbol=symbol,
        timestamp=_now(),
        bid=1.0,
        ask=2.0,
        last=1.5,
        volume=10,
        contract=contract,
        model_greeks=model_greeks,
    )


# ---------------------------------------------------------------------------
# Task 6 tests
# ---------------------------------------------------------------------------


def test_netting_open_close_removes_position():
    state = AppRiskState(clock=SimClock(datetime(2026, 6, 10, tzinfo=UTC)))
    leg = Leg(contract=_opt(150.0, "C"), quantity=-1, entry_price=2.0)
    state.record_fill(FillEvent("o1", [leg], datetime.now(UTC), 1.0, "s1"))
    closing = Leg(contract=_opt(150.0, "C"), quantity=1, entry_price=1.0)
    state.record_fill(FillEvent("o2", [closing], datetime.now(UTC), 1.0, "s1"))
    assert state.positions() == []
    assert state.min_dte() is None


def test_portfolio_greeks_per_contract_lookup():
    call, put = _opt(150.0, "C"), _opt(140.0, "P")
    events = {
        contract_key(call): _mkt("AAPL", contract=call, model_greeks=Greeks(delta=0.5)),
        contract_key(put): _mkt("AAPL", contract=put, model_greeks=Greeks(delta=-0.3)),
    }
    state = AppRiskState(clock=_clock(), greeks_lookup=events.get)
    state.record_fill(FillEvent("o1", [Leg(call, 1)], _now(), 0.0, "s1"))
    state.record_fill(FillEvent("o2", [Leg(put, 2)], _now(), 0.0, "s1"))
    assert all(p.strategy_id == "s1" for p in state.positions())
    g = state.portfolio_greeks()
    assert g.delta == pytest.approx(0.5 * 100 + (-0.3) * 2 * 100)


def test_stock_delta_no_multiplier():
    stk = Contract(symbol="AAPL", sec_type="STK")
    state = AppRiskState(clock=_clock(), greeks_lookup=lambda k: None)
    state.record_fill(FillEvent("o1", [Leg(stk, 100)], _now(), 0.0, "s1"))
    assert state.portfolio_greeks().delta == pytest.approx(100)


def test_greeks_parity_with_composite_single_symbol():
    # Single symbol scenario: AppRiskState aggregation == GreeksCalculator.composite
    opt = _opt(150.0, "C")
    greeks = Greeks(delta=0.5, gamma=0.02, vega=0.1, theta=-0.05)
    legs = [Leg(contract=opt, quantity=2)]
    expected = GreeksCalculator.composite(legs, {"AAPL": greeks})
    state = AppRiskState(
        clock=_clock(),
        greeks_lookup={
            contract_key(opt): _mkt("AAPL", contract=opt, model_greeks=greeks)
        }.get,
    )
    state.record_fill(FillEvent("o1", legs, _now(), 0.0, "s1"))
    actual = state.portfolio_greeks()
    assert actual.delta == pytest.approx(expected.delta)
    assert actual.vega == pytest.approx(expected.vega)
    assert actual.theta == pytest.approx(expected.theta)


def test_cashflow_uses_multiplier():
    state = AppRiskState(initial_equity=10_000.0, clock=_clock())
    leg = Leg(contract=_opt(150.0, "C"), quantity=-1, entry_price=2.0)
    state.record_fill(FillEvent("o1", [leg], _now(), 1.0, "s1"))
    assert state.equity() == pytest.approx(10_000.0 + 2.0 * 100 - 1.0)


def test_min_dte():
    state = AppRiskState(clock=SimClock(datetime(2026, 6, 10, tzinfo=UTC)))
    near = Contract(
        symbol="AAPL", sec_type="OPT", expiry="20260620", strike=150.0, right="C"
    )
    state.record_fill(FillEvent("o1", [Leg(near, -1)], _now(), 0.0, "s1"))
    assert state.min_dte() == 10


class _FakeDataHandler:
    def __init__(self, events: list[MarketEvent]) -> None:
        self._events = events

    async def subscribe_quote(self, contract: Contract):
        for event in self._events:
            yield event


def _risk_limits() -> RiskLimits:
    return RiskLimits(
        max_delta=200.0,
        max_vega=500.0,
        max_drawdown=0.10,
        max_position_size=5,
        max_margin_utilization=0.80,
    )


def _signal(clock: SimClock, contract: Contract) -> SignalEvent:
    return SignalEvent(
        strategy_id="test",
        timestamp=clock.now(),
        direction="ENTER",
        proposed_order=Order(
            legs=[Leg(contract=contract, quantity=1)],
            strategy_id="test",
        ),
        reason="test",
    )


def _write_ticks(base_dir: Path, contract: Contract, date: str, rows: list[dict]):
    partition = tick_partition_path(base_dir, contract, date)
    partition.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {column: [row[column] for row in rows] for column in TICK_SCHEMA.names},
        schema=TICK_SCHEMA,
    )
    pq.write_table(table, partition / "000000.parquet", use_dictionary=False)


def _tick(timestamp: datetime, last: float) -> dict:
    return {
        "timestamp": timestamp,
        "symbol": "AAPL",
        "bid": last - 0.1,
        "ask": last + 0.1,
        "last": last,
        "volume": 1000,
        "model_delta": None,
        "model_gamma": None,
        "model_vega": None,
        "model_theta": None,
        "model_iv": None,
        "model_underlying": None,
    }


# ---------------------------------------------------------------------------
# Task 9 helpers
# ---------------------------------------------------------------------------


class _RecordingDecisionLogger:
    def __init__(self) -> None:
        self.decisions = []

    async def log(self, signal, market, result) -> None:
        self.decisions.append(result)


def _make_pipeline(
    bus: EventBus,
    clock: SimClock,
    equity_provider=None,
    margin_cushion_provider=None,
    decision_logger=None,
) -> tuple[RiskPipeline, list[AlertEvent]]:
    alerts: list[AlertEvent] = []

    async def capture_alert(event: AlertEvent) -> None:
        alerts.append(event)

    bus.subscribe(AlertEvent, capture_alert)
    circuit_breaker = CircuitBreaker()
    pipeline = RiskPipeline(
        bus=bus,
        validator=PreTradeValidator(_risk_limits()),
        clock=clock,
        decision_logger=decision_logger,
        market_lookup=lambda _symbol: _mkt("AAPL"),
        monitor=RealTimeMonitor(_risk_limits(), clock),
        circuit_breaker=circuit_breaker,
        portfolio_greeks_provider=lambda: Greeks(delta=10.0),
        equity_provider=equity_provider
        if equity_provider is not None
        else (lambda: 100_000.0),
        margin_cushion_provider=margin_cushion_provider or (lambda: None),
    )
    log_alerts(bus)
    return pipeline, alerts


# ---------------------------------------------------------------------------
# Task 9 tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_status_emits_alert():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 10, tzinfo=UTC))
    pipeline, alerts = _make_pipeline(bus, clock)
    bus.subscribe(OrderStatusEvent, pipeline.on_order_status)
    await bus.publish(
        OrderStatusEvent(
            order_id="o1",
            status="REJECTED",
            timestamp=clock.now(),
            reason="margin",
        )
    )
    assert any("REJECTED" in a.message and "margin" in a.message for a in alerts)


@pytest.mark.asyncio
async def test_check_now_triggers_circuit_break_on_margin():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 10, tzinfo=UTC))
    # margin_cushion_provider returns 0.01 → below 0.02 threshold → circuit break
    pipeline, alerts = _make_pipeline(bus, clock, margin_cushion_provider=lambda: 0.01)
    await pipeline.check_now()
    assert pipeline.circuit_breaker.is_triggered
    assert any("Circuit breaker" in a.message for a in alerts)


@pytest.mark.asyncio
async def test_equity_none_skips_checks_and_rejects_signals():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 10, tzinfo=UTC))
    decision_logger = _RecordingDecisionLogger()
    pipeline, alerts = _make_pipeline(
        bus, clock, equity_provider=lambda: None, decision_logger=decision_logger
    )
    orders_published: list[OrderEvent] = []

    async def capture_order(event: OrderEvent) -> None:
        orders_published.append(event)

    bus.subscribe(OrderEvent, capture_order)

    # check_now with None equity → no circuit break, no alerts
    await pipeline.check_now()
    assert not pipeline.circuit_breaker.is_triggered
    assert alerts == []

    # on_signal with None equity → order rejected, not published
    contract = Contract(symbol="AAPL", sec_type="STK")
    await pipeline.on_signal(_signal(clock, contract))
    assert orders_published == []
    assert decision_logger.decisions[-1].approved is False
    assert "account data unavailable" in decision_logger.decisions[-1].reason


@pytest.mark.asyncio
async def test_alert_logger_subscriber(caplog):
    import logging

    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 10, tzinfo=UTC))

    log_alerts(bus)
    with caplog.at_level(logging.WARNING, logger="trading_app.assembly"):
        await bus.publish(
            AlertEvent(
                message="test-alert-msg",
                value=42.0,
                timestamp=clock.now(),
            )
        )
    assert any("test-alert-msg" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Task 10: live reconnect loop
# ---------------------------------------------------------------------------


class CountingDataHandler:
    """Each subscribe_quote ends the stream immediately (simulates a dead
    stream after disconnect)."""

    def __init__(self) -> None:
        self.subscribe_count = 0

    async def subscribe_quote(self, contract):
        self.subscribe_count += 1
        return
        yield  # pragma: no cover — makes this an async generator


@pytest.fixture
async def live_app_env(tmp_path):
    ib = MagicMock()
    ib.disconnect = MagicMock()
    ib.isConnected = MagicMock(return_value=False)
    ib.disconnectedEvent = ev.Event("disconnectedEvent")
    config = TraderConfig(
        storage=StorageConfig(
            ticks_dir=tmp_path / "ticks",
            decision_db=tmp_path / "decisions.duckdb",
            trade_db=tmp_path / "orders.db",
        )
    )
    contract = Contract(symbol="AAPL", sec_type="STK")
    app = await build_live_app(config, ib=ib, contracts=[contract])
    handler = CountingDataHandler()
    app.data_handler = handler
    yield app, handler
    await app.close()


@pytest.mark.asyncio
async def test_run_market_data_resubscribes_after_reconnect(live_app_env):
    app, handler = live_app_env
    app._reconnected.set()  # sticky scenario: callback fired before wait
    task = asyncio.create_task(app.run_market_data())
    for _ in range(50):
        await asyncio.sleep(0)
        if handler.subscribe_count >= 2:
            break
    app._shutdown = True
    app._reconnected.set()
    await asyncio.wait_for(task, timeout=1)
    assert handler.subscribe_count >= 2


@pytest.mark.asyncio
async def test_run_market_data_exits_on_shutdown(live_app_env):
    app, _handler = live_app_env
    task = asyncio.create_task(app.run_market_data())
    await asyncio.sleep(0)
    app._shutdown = True
    app._reconnected.set()
    await asyncio.wait_for(task, timeout=1)  # passes if it does not hang
