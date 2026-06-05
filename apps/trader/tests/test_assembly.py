from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import eventkit as ev
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from core.bus import EventBus
from core.clock import SimClock
from core.events import AlertEvent, FillEvent, MarketEvent, OrderEvent, SignalEvent
from core.models import Contract, Greeks, Leg, Order, RiskLimits
from core.partitions import tick_partition_path
from risk import CircuitBreaker, PreTradeValidator, RealTimeMonitor
from strategy.base import BaseStrategy
from trading_app.assembly import (
    AppRiskState,
    RiskPipeline,
    build_backtest_app,
    build_live_app,
    load_strategy,
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
        decisions = app.decision_logger.query(
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

    assert state.positions()[0].strategy_id == "sim-1"
    assert state.equity() == 100000.0
    assert state.proposed_greeks(signal).delta == 25.0
    assert state.proposed_greeks(signal).vega == 3.0


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
