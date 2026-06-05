import asyncio
import importlib
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import ib_async as ibi

from backtest import BacktestRunner, SimulatedExecutor
from core import (
    AlertEvent,
    DataHandler,
    EventBus,
    FillEvent,
    Greeks,
    LiveClock,
    MarketEvent,
    OrderEvent,
    Position,
    SignalEvent,
    SimClock,
    ValidationResult,
)
from core.models import Contract
from execution import LiveGateway
from market_data.historical import HistoricalDataHandler
from risk import CircuitBreaker, PreTradeValidator, RealTimeMonitor
from storage import DecisionLogger, StorageSubscriber, TickWriter, TradeStore
from strategy.base import BaseStrategy
from trading_app.config import TraderConfig
from tws_client import ConnectionManager, LiveDataHandler

MarketLookup = Callable[[str], MarketEvent | None]
GreeksProvider = Callable[[], Greeks]
ProposedGreeksProvider = Callable[[SignalEvent], Greeks]
PositionsProvider = Callable[[], list[Position]]
EquityProvider = Callable[[], float]
FillRecorder = Callable[[FillEvent], None]


class AppRiskState:
    def __init__(self, initial_equity: float = 0.0) -> None:
        self._initial_equity = initial_equity
        self._positions: list[Position] = []

    def record_fill(self, event: FillEvent) -> None:
        if not event.legs_filled:
            return
        self._positions.append(
            Position(legs=event.legs_filled, strategy_id=event.order_id)
        )

    def positions(self) -> list[Position]:
        return list(self._positions)

    def portfolio_greeks(self) -> Greeks:
        total = Greeks()
        for position in self._positions:
            if not position.greeks:
                continue
            total.delta += position.greeks.delta
            total.gamma += position.greeks.gamma
            total.vega += position.greeks.vega
            total.theta += position.greeks.theta
            total.implied_vol += position.greeks.implied_vol
            total.underlying_price += position.greeks.underlying_price
        return total

    def proposed_greeks(self, signal: SignalEvent) -> Greeks:
        raw = signal.context.get("proposed_greeks")
        if isinstance(raw, Greeks):
            return raw
        if isinstance(raw, dict):
            return Greeks(
                delta=float(raw.get("delta", 0.0)),
                gamma=float(raw.get("gamma", 0.0)),
                vega=float(raw.get("vega", 0.0)),
                theta=float(raw.get("theta", 0.0)),
                implied_vol=float(raw.get("implied_vol", 0.0)),
                underlying_price=float(raw.get("underlying_price", 0.0)),
            )
        return Greeks()

    def equity(self) -> float:
        return self._initial_equity


class RiskPipeline:
    def __init__(
        self,
        bus: EventBus,
        validator: PreTradeValidator,
        clock: LiveClock | SimClock,
        decision_logger: DecisionLogger | None = None,
        market_lookup: MarketLookup | None = None,
        monitor: RealTimeMonitor | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        portfolio_greeks_provider: GreeksProvider | None = None,
        proposed_greeks_provider: ProposedGreeksProvider | None = None,
        positions_provider: PositionsProvider | None = None,
        equity_provider: EquityProvider | None = None,
        fill_recorder: FillRecorder | None = None,
        approved_by: str = "pre-trade-validator",
    ) -> None:
        self._bus = bus
        self._validator = validator
        self._clock = clock
        self._decision_logger = decision_logger
        self._market_lookup = market_lookup or (lambda _symbol: None)
        self._monitor = monitor
        self._circuit_breaker = circuit_breaker
        self._portfolio_greeks_provider = portfolio_greeks_provider or Greeks
        self._proposed_greeks_provider = proposed_greeks_provider or (
            lambda _signal: Greeks()
        )
        self._positions_provider = positions_provider or list
        self._equity_provider = equity_provider or (lambda: 0.0)
        self._fill_recorder = fill_recorder
        self._approved_by = approved_by

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        if self._circuit_breaker is None:
            raise RuntimeError("RiskPipeline has no circuit breaker")
        return self._circuit_breaker

    async def on_signal(self, signal: SignalEvent) -> None:
        if self._circuit_breaker and self._circuit_breaker.is_triggered:
            self._log_decision(
                signal,
                ValidationResult(
                    approved=False,
                    reason="Circuit breaker triggered",
                ),
            )
            return

        result = self._validator.validate(
            signal,
            portfolio_greeks=self._portfolio_greeks_provider(),
            proposed_greeks=self._proposed_greeks_provider(signal),
            positions=self._positions_provider(),
        )
        self._log_decision(signal, result)

        if not result.approved:
            return

        await self._bus.publish(
            OrderEvent(
                order=signal.proposed_order,
                timestamp=self._clock.now(),
                approved_by=self._approved_by,
            )
        )

    async def on_fill(self, event: FillEvent) -> None:
        if self._fill_recorder:
            self._fill_recorder(event)

        if not self._monitor:
            return

        portfolio_greeks = self._portfolio_greeks_provider()
        equity = self._equity_provider()
        for alert in self._monitor.check(portfolio_greeks, equity):
            await self._bus.publish(alert)

        if (
            self._circuit_breaker
            and not self._circuit_breaker.is_triggered
            and self._monitor.should_circuit_break(portfolio_greeks, equity)
        ):
            self._circuit_breaker.trigger()
            await self._bus.publish(
                AlertEvent(
                    message="Circuit breaker triggered",
                    value=equity,
                    timestamp=self._clock.now(),
                )
            )

    def _log_decision(self, signal: SignalEvent, result: ValidationResult) -> None:
        market = self._market_lookup(_signal_symbol(signal))
        if self._decision_logger and market:
            self._decision_logger.log(signal, market, result)


@dataclass
class BacktestApp:
    bus: EventBus
    clock: SimClock
    data_handler: HistoricalDataHandler
    executor: SimulatedExecutor
    runner: BacktestRunner
    risk_pipeline: RiskPipeline
    risk_state: AppRiskState
    storage_subscriber: StorageSubscriber
    trade_store: TradeStore
    decision_logger: DecisionLogger
    circuit_breaker: CircuitBreaker

    async def run(self) -> list[FillEvent]:
        return await self.runner.run()

    async def close(self) -> None:
        try:
            await self.storage_subscriber.stop()
        finally:
            self.decision_logger.close()


@dataclass
class LiveApp:
    bus: EventBus
    clock: LiveClock
    connection: ConnectionManager
    data_handler: LiveDataHandler
    gateway: LiveGateway
    risk_pipeline: RiskPipeline
    risk_state: AppRiskState
    storage_subscriber: StorageSubscriber
    trade_store: TradeStore
    decision_logger: DecisionLogger
    circuit_breaker: CircuitBreaker
    contracts: Sequence[Contract]

    async def connect(self) -> None:
        await self.connection.connect()

    async def run_market_data(self) -> None:
        await publish_market_data(self.bus, self.data_handler, self.contracts)

    async def close(self) -> None:
        self.connection.disconnect()
        try:
            await self.storage_subscriber.stop()
        finally:
            self.decision_logger.close()


async def build_backtest_app(
    config: TraderConfig,
    contracts: Sequence[Contract],
    start: datetime,
) -> BacktestApp:
    bus = EventBus()
    clock = SimClock(start)
    data_handler = HistoricalDataHandler(config.backtest.ticks_dir)
    executor = SimulatedExecutor(bus, clock)
    storage_subscriber, trade_store = await _start_storage(
        bus, config.storage, contracts
    )
    decision_logger = _build_decision_logger(config.storage.decision_db)
    risk_state = AppRiskState(initial_equity=config.risk.initial_equity)
    risk_pipeline = _wire_risk_pipeline(
        bus,
        clock,
        config,
        decision_logger,
        storage_subscriber.last_market,
        risk_state,
    )
    bus.subscribe(OrderEvent, executor.on_order)
    runner = BacktestRunner(bus, clock, data_handler, executor, list(contracts))
    return BacktestApp(
        bus=bus,
        clock=clock,
        data_handler=data_handler,
        executor=executor,
        runner=runner,
        risk_pipeline=risk_pipeline,
        risk_state=risk_state,
        storage_subscriber=storage_subscriber,
        trade_store=trade_store,
        decision_logger=decision_logger,
        circuit_breaker=risk_pipeline.circuit_breaker,
    )


async def build_live_app(
    config: TraderConfig,
    ib: ibi.IB | None = None,
    contracts: Sequence[Contract] = (),
) -> LiveApp:
    ib = ib or ibi.IB()
    bus = EventBus()
    clock = LiveClock()
    connection = ConnectionManager(
        ib,
        host=config.tws.host,
        port=config.tws.port,
        client_id=config.tws.client_id,
    )
    data_handler = LiveDataHandler(ib, max_subscriptions=config.tws.max_subscriptions)
    gateway = LiveGateway(bus, clock, ib)
    storage_subscriber, trade_store = await _start_storage(
        bus, config.storage, contracts
    )
    decision_logger = _build_decision_logger(config.storage.decision_db)
    risk_state = AppRiskState(initial_equity=config.risk.initial_equity)
    risk_pipeline = _wire_risk_pipeline(
        bus,
        clock,
        config,
        decision_logger,
        storage_subscriber.last_market,
        risk_state,
    )
    bus.subscribe(OrderEvent, gateway.on_order)
    return LiveApp(
        bus=bus,
        clock=clock,
        connection=connection,
        data_handler=data_handler,
        gateway=gateway,
        risk_pipeline=risk_pipeline,
        risk_state=risk_state,
        storage_subscriber=storage_subscriber,
        trade_store=trade_store,
        decision_logger=decision_logger,
        circuit_breaker=risk_pipeline.circuit_breaker,
        contracts=list(contracts),
    )


def subscribe_strategy(bus: EventBus, strategy: BaseStrategy) -> None:
    bus.subscribe(MarketEvent, strategy.on_market_event)
    bus.subscribe(FillEvent, strategy.on_fill)


def load_strategy(
    class_path: str,
    strategy_id: str,
    bus: EventBus,
    clock: LiveClock | SimClock,
    params: dict | None = None,
) -> BaseStrategy:
    module_name, class_name = _split_class_path(class_path)
    module = importlib.import_module(module_name)
    strategy_class = getattr(module, class_name)
    strategy = strategy_class(
        strategy_id=strategy_id, bus=bus, clock=clock, **(params or {})
    )
    if not isinstance(strategy, BaseStrategy):
        raise TypeError(f"{class_path} did not create a BaseStrategy")
    return strategy


async def publish_market_data(
    bus: EventBus,
    data_handler: DataHandler,
    contracts: Sequence[Contract],
) -> None:
    async def publish_contract(contract: Contract) -> None:
        stream: AsyncIterator[MarketEvent] = data_handler.subscribe_quote(contract)
        async for event in stream:
            await bus.publish(event)

    await asyncio.gather(*(publish_contract(contract) for contract in contracts))


def _wire_risk_pipeline(
    bus: EventBus,
    clock: LiveClock | SimClock,
    config: TraderConfig,
    decision_logger: DecisionLogger,
    market_lookup: MarketLookup,
    risk_state: AppRiskState,
) -> RiskPipeline:
    circuit_breaker = CircuitBreaker()
    pipeline = RiskPipeline(
        bus=bus,
        validator=PreTradeValidator(config.risk.to_risk_limits()),
        clock=clock,
        decision_logger=decision_logger,
        market_lookup=market_lookup,
        monitor=RealTimeMonitor(config.risk.to_risk_limits(), clock),
        circuit_breaker=circuit_breaker,
        portfolio_greeks_provider=risk_state.portfolio_greeks,
        proposed_greeks_provider=risk_state.proposed_greeks,
        positions_provider=risk_state.positions,
        equity_provider=risk_state.equity,
        fill_recorder=risk_state.record_fill,
    )
    bus.subscribe(SignalEvent, pipeline.on_signal)
    bus.subscribe(FillEvent, pipeline.on_fill)
    return pipeline


async def _start_storage(
    bus: EventBus,
    config,
    contracts: Sequence[Contract],
) -> tuple[StorageSubscriber, TradeStore]:
    config.ticks_dir.mkdir(parents=True, exist_ok=True)
    _ensure_parent(config.trade_db)
    trade_store = TradeStore(config.trade_db)
    await trade_store.init()
    subscriber = StorageSubscriber(
        bus=bus,
        tick_writer=TickWriter(config.ticks_dir),
        trade_store=trade_store,
    )
    for contract in contracts:
        subscriber.register_contract(contract.symbol, contract)
    await subscriber.start()
    return subscriber, trade_store


def _build_decision_logger(path: Path) -> DecisionLogger:
    _ensure_parent(path)
    return DecisionLogger(path)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _signal_symbol(signal: SignalEvent) -> str:
    if not signal.proposed_order.legs:
        return ""
    return signal.proposed_order.legs[0].contract.symbol


def _split_class_path(class_path: str) -> tuple[str, str]:
    if ":" in class_path:
        module_name, class_name = class_path.split(":", 1)
    else:
        module_name, _, class_name = class_path.rpartition(".")
    if not module_name or not class_name:
        raise ValueError("Strategy class_path must be 'module:Class' or 'module.Class'")
    return module_name, class_name
