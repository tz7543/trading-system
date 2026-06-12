import asyncio
import importlib
import json
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import ib_async as ibi

from backtest import BacktestRunner, SimulatedExecutor
from core import (
    AlertEvent,
    DataHandler,
    EventBus,
    FillEvent,
    Greeks,
    Leg,
    LiveClock,
    MarketEvent,
    OrderEvent,
    OrderStatusEvent,
    Position,
    SignalEvent,
    SimClock,
    ValidationResult,
)
from core.models import Contract, MarginInfo, contract_key
from execution import LiveGateway
from market_data.historical import HistoricalDataHandler
from risk import CircuitBreaker, PreTradeValidator, RealTimeMonitor
from storage import DecisionLogger, StorageSubscriber, TickWriter, TradeStore
from strategy.base import BaseStrategy
from strategy.swing.scanner import ScanResult, evaluate
from trading_app.config import TraderConfig
from trading_app.scan_report import json_payload, render_report
from trading_app.watchdog import MarketDataWatchdog
from tws_client import AccountState, ConnectionManager, LiveDataHandler

logger = logging.getLogger(__name__)

MarketLookup = Callable[[str], MarketEvent | None]
GreeksProvider = Callable[[], Greeks]
ProposedGreeksProvider = Callable[[SignalEvent], Greeks]
PositionsProvider = Callable[[], list[Position]]
EquityProvider = Callable[[], float | None]
MarginCushionProvider = Callable[[], float | None]
MarginInfoProvider = Callable[[], "MarginInfo | None"]
MinDteProvider = Callable[[], int | None]
FillRecorder = Callable[[FillEvent], None]
GreeksLookup = Callable[[str], MarketEvent | None]


class AppRiskState:
    def __init__(
        self,
        initial_equity: float = 0.0,
        clock: LiveClock | SimClock | None = None,
        greeks_lookup: GreeksLookup | None = None,
    ) -> None:
        self._initial_equity = initial_equity
        self._clock = clock or LiveClock()
        self._greeks_lookup = greeks_lookup or (lambda _key: None)
        self._net: dict[str, Leg] = {}
        self._strategy_by_key: dict[str, str] = {}
        self._realized_pnl: float = 0.0

    def record_fill(self, event: FillEvent) -> None:
        for leg in event.legs_filled:
            mult = leg.contract.multiplier if leg.contract.sec_type == "OPT" else 1
            if leg.entry_price:
                self._realized_pnl -= leg.quantity * leg.entry_price * mult
            key = contract_key(leg.contract)
            existing = self._net.get(key)
            new_qty = (existing.quantity if existing else 0) + leg.quantity
            if new_qty == 0:
                self._net.pop(key, None)
                self._strategy_by_key.pop(key, None)
            else:
                # entry_price on the netted Leg is last-fill price, not cost basis
                self._net[key] = Leg(
                    contract=leg.contract,
                    quantity=new_qty,
                    entry_price=leg.entry_price,
                )
                self._strategy_by_key[key] = event.strategy_id
        self._realized_pnl -= event.commission

    def positions(self) -> list[Position]:
        # Semantic change (intentional fix): max_position_size now counts net open
        # contract positions (one per contract_key), not historical fill count —
        # the old behavior accumulated even closing fills, which was an audited bug.
        return [
            Position(legs=[leg], strategy_id=self._strategy_by_key.get(key, ""))
            for key, leg in self._net.items()
        ]

    def portfolio_greeks(self) -> Greeks:
        total = Greeks()
        for key, leg in self._net.items():
            if leg.contract.sec_type == "STK":
                total = total + Greeks(delta=leg.quantity)
                continue
            market = self._greeks_lookup(key)
            greeks = market.model_greeks if market else None
            if greeks is None:
                logger.debug("No greeks for %s; skipping", key)
                continue
            total = total + greeks * (leg.quantity * leg.contract.multiplier)
        return total

    def min_dte(self) -> int | None:
        dtes = []
        for leg in self._net.values():
            if leg.contract.sec_type != "OPT" or not leg.contract.expiry:
                continue
            try:
                expiry_date = (
                    datetime.strptime(leg.contract.expiry, "%Y%m%d")
                    .replace(tzinfo=UTC)
                    .date()
                )
            except ValueError:
                logger.warning(
                    "Malformed expiry %r on %s; skipping leg in min_dte",
                    leg.contract.expiry,
                    leg.contract.symbol,
                )
                continue
            dtes.append((expiry_date - self._clock.now().date()).days)
        return min(dtes) if dtes else None

    def equity(self) -> float:
        # backtest cash-flow approximation (known limitation); live path should use AccountState
        return self._initial_equity + self._realized_pnl

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
        margin_cushion_provider: MarginCushionProvider | None = None,
        margin_info_provider: MarginInfoProvider | None = None,
        min_dte_provider: MinDteProvider | None = None,
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
        self._equity_provider = equity_provider or (lambda: None)
        self._margin_cushion_provider = margin_cushion_provider or (lambda: None)
        self._margin_info_provider: MarginInfoProvider = margin_info_provider or (
            lambda: None
        )
        self._min_dte_provider = min_dte_provider or (lambda: None)
        self._fill_recorder = fill_recorder
        self._approved_by = approved_by

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        if self._circuit_breaker is None:
            raise RuntimeError("RiskPipeline has no circuit breaker")
        return self._circuit_breaker

    async def on_signal(self, signal: SignalEvent) -> None:
        if self._circuit_breaker and self._circuit_breaker.is_triggered:
            await self._log_decision(
                signal,
                ValidationResult(
                    approved=False,
                    reason="Circuit breaker triggered",
                ),
            )
            return

        if self._equity_provider() is None:
            await self._log_decision(
                signal,
                ValidationResult(approved=False, reason="account data unavailable"),
            )
            return

        result = self._validator.validate(
            signal,
            portfolio_greeks=self._portfolio_greeks_provider(),
            proposed_greeks=self._proposed_greeks_provider(signal),
            positions=self._positions_provider(),
            margin_info=self._margin_info_provider(),
        )
        await self._log_decision(signal, result)

        if not result.approved:
            return

        await self._bus.publish(
            OrderEvent(
                order=signal.proposed_order,
                timestamp=self._clock.now(),
                approved_by=self._approved_by,
            )
        )

    async def on_order_status(self, event: OrderStatusEvent) -> None:
        if event.status in ("REJECTED", "CANCELLED"):
            await self._bus.publish(
                AlertEvent(
                    message=f"Order {event.order_id} {event.status}: {event.reason}",
                    value=0.0,
                    timestamp=self._clock.now(),
                )
            )

    async def check_now(self) -> None:
        # NOTE: RealTimeMonitor is stateless — alerts repeat on each call while a
        # condition persists (per-fill + periodic); future alert sinks need their
        # own dedup.
        if not self._monitor:
            return
        equity = self._equity_provider()
        if equity is None:
            logger.debug("Equity unavailable; skipping risk check")
            return
        greeks = self._portfolio_greeks_provider()
        min_dte = self._min_dte_provider()
        cushion = self._margin_cushion_provider()
        for alert in self._monitor.check(
            greeks, equity, min_dte=min_dte, margin_cushion=cushion
        ):
            await self._bus.publish(alert)
        if (
            self._circuit_breaker
            and not self._circuit_breaker.is_triggered
            and self._monitor.should_circuit_break(
                greeks, equity, min_dte=min_dte, margin_cushion=cushion
            )
        ):
            self._circuit_breaker.trigger()
            await self._bus.publish(
                AlertEvent(
                    message="Circuit breaker triggered",
                    value=equity,
                    timestamp=self._clock.now(),
                )
            )

    async def on_fill(self, event: FillEvent) -> None:
        if self._fill_recorder:
            self._fill_recorder(event)
        await self.check_now()

    async def _log_decision(
        self, signal: SignalEvent, result: ValidationResult
    ) -> None:
        market = self._market_lookup(_signal_symbol(signal))
        if self._decision_logger:
            await self._decision_logger.log(signal, market, result)


def log_alerts(bus: EventBus) -> None:
    async def _on_alert(event: AlertEvent) -> None:
        logger.warning("ALERT: %s (value=%s)", event.message, event.value)

    bus.subscribe(AlertEvent, _on_alert)


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
    account_state: AccountState
    watchdog: MarketDataWatchdog
    _reconnected: asyncio.Event = field(default_factory=asyncio.Event)
    _shutdown: bool = False

    def __post_init__(self) -> None:
        self.connection.on_reconnected.append(self._reconnected.set)
        self.bus.subscribe(MarketEvent, self.watchdog.on_market)

    async def connect(self) -> None:
        await self.connection.connect()
        await self.account_state.start()

    async def run_market_data(self) -> None:
        # Live streams are infinite generators that hang on disconnect, so race
        # the publish task against the reconnect signal: reconnect wins → cancel
        # the dead streams and resubscribe; streams ending naturally (e.g.
        # finite handlers) → wait for the sticky reconnect signal.
        while not self._shutdown:
            publish_task = asyncio.create_task(
                publish_market_data(self.bus, self.data_handler, self.contracts)
            )
            reconnect_wait = asyncio.create_task(self._reconnected.wait())
            try:
                await asyncio.wait(
                    {publish_task, reconnect_wait},
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                for task in (publish_task, reconnect_wait):
                    task.cancel()
                await asyncio.gather(
                    publish_task, reconnect_wait, return_exceptions=True
                )
            if self._shutdown:
                return
            await self._reconnected.wait()  # sticky: may already be set
            if self._shutdown:
                return
            self._reconnected.clear()
            await self.bus.publish(
                AlertEvent(
                    message="market data restarting after reconnect",
                    value=0.0,
                    timestamp=self.clock.now(),
                )
            )

    async def risk_check_loop(self, interval: float) -> None:
        # Deliberately sleep before the first check so account/market data can
        # populate; per-fill check_now() still covers the active period.
        while True:
            await asyncio.sleep(interval)
            try:
                await self.risk_pipeline.check_now()
            except Exception:
                logger.exception("Periodic risk check failed; loop continues")

    async def watchdog_loop(self, interval: float = 10.0) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                for alert in self.watchdog.check_now():
                    await self.bus.publish(alert)
            except Exception:
                logger.exception("Watchdog check failed; loop continues")

    async def close(self) -> None:
        self._shutdown = True
        self._reconnected.set()  # wake run_market_data so it can exit
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
    risk_state = AppRiskState(
        initial_equity=config.risk.initial_equity,
        clock=clock,
        greeks_lookup=storage_subscriber.last_market_by_contract,
    )
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
    account_state = AccountState(ib)
    risk_state = AppRiskState(
        initial_equity=config.risk.initial_equity,
        clock=clock,
        greeks_lookup=storage_subscriber.last_market_by_contract,
    )
    watchdog = MarketDataWatchdog(
        clock=clock, stale_seconds=config.tws.stale_data_seconds
    )
    risk_pipeline = _wire_risk_pipeline(
        bus,
        clock,
        config,
        decision_logger,
        storage_subscriber.last_market,
        risk_state,
        equity_provider=account_state.equity,
        margin_cushion_provider=account_state.margin_cushion,
        margin_info_provider=account_state.margin_info,
        min_dte_provider=risk_state.min_dte,
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
        account_state=account_state,
        watchdog=watchdog,
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

    results = await asyncio.gather(
        *(publish_contract(contract) for contract in contracts),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, Exception):
            logger.error("Market data stream failed: %s", result)


async def run_scan(
    config: TraderConfig,
    data_handler: DataHandler | None = None,
    json_path: Path | None = None,
) -> int:
    scanner_config = config.scanner
    if scanner_config is None:
        raise ValueError("[scanner] config is required for the scan command")

    connection: ConnectionManager | None = None
    if data_handler is None:
        symbol_count = len(scanner_config.symbols)
        logger.info(
            "scanning %d symbols via TWS; pacing ≈ 15s each (~%d min total)",
            symbol_count,
            symbol_count * 15 // 60,
        )
        if symbol_count > 40:
            logger.warning("more than 40 symbols — expect a long scan")
        ib = ibi.IB()
        connection = ConnectionManager(
            ib,
            host=config.tws.host,
            port=config.tws.port,
            client_id=config.tws.client_id,
        )
        await connection.connect()
        data_handler = LiveDataHandler(
            ib, max_subscriptions=config.tws.max_subscriptions
        )
    try:
        results: list[ScanResult] = []
        for symbol in scanner_config.symbols:
            contract = Contract(symbol=symbol, sec_type="STK")
            try:
                bars = await data_handler.fetch_history(contract, "2 Y", "1 day")
            except Exception as exc:  # spec: per-symbol failure → SKIP, continue
                results.append(
                    ScanResult(
                        symbol=symbol,
                        verdict="SKIP",
                        reasons=[f"fetch failed: {exc}"],
                    )
                )
                continue
            results.append(
                evaluate(
                    symbol,
                    bars,
                    equity=scanner_config.equity,
                    risk_pct=scanner_config.risk_pct,
                    vix=scanner_config.vix,
                )
            )
    finally:
        if connection is not None:
            connection.disconnect()

    print(render_report(results))
    if json_path is not None:
        payload = json_payload(results, generated_at=datetime.now(UTC).isoformat())
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _wire_risk_pipeline(
    bus: EventBus,
    clock: LiveClock | SimClock,
    config: TraderConfig,
    decision_logger: DecisionLogger,
    market_lookup: MarketLookup,
    risk_state: AppRiskState,
    equity_provider: EquityProvider | None = None,
    margin_cushion_provider: MarginCushionProvider | None = None,
    margin_info_provider: MarginInfoProvider | None = None,
    min_dte_provider: MinDteProvider | None = None,
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
        equity_provider=equity_provider
        if equity_provider is not None
        else risk_state.equity,
        margin_cushion_provider=margin_cushion_provider or (lambda: None),
        margin_info_provider=margin_info_provider,
        min_dte_provider=min_dte_provider
        if min_dte_provider is not None
        else risk_state.min_dte,
        fill_recorder=risk_state.record_fill,
    )
    bus.subscribe(SignalEvent, pipeline.on_signal)
    bus.subscribe(FillEvent, pipeline.on_fill)
    bus.subscribe(OrderStatusEvent, pipeline.on_order_status)
    log_alerts(bus)
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
