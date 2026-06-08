# Phase 4A: Backtest Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backtest engine — SimulatedExecutor (fills orders at simulated prices), BacktestRunner (replays Parquet data through EventBus), and PerformanceMetrics (computes returns, drawdown, win rate).

**Architecture:** Backtest package depends only on core. BacktestRunner receives all components via DI (EventBus, SimClock, DataHandler, SimulatedExecutor, contracts). The caller (apps/trader or test code) wires strategy, risk, and storage onto the bus. SimulatedExecutor fills pending orders at next-tick prices (STK: last, OPT: bid/ask midpoint) with all-or-nothing atomicity per order. Performance metrics use FIFO trade matching on realized fills.

**Tech Stack:** Pure Python (no external deps beyond core), pytest + pytest-asyncio

**Phase 4 splits into 4A backtest / 4B live+TWS / 4C assembly. This plan is 4A.**

**Spec Resolutions:**
- Backtest fills at next tick — NOT same tick. Order queued at event T fills at event T+1 prices. This prevents look-ahead bias. Discriminating test included (Task 2)
- Multi-leg orders use all-or-nothing fill: if any leg lacks market data in the snapshot, the entire order stays pending (no partial fills that create naked legs)
- `max_drawdown` in BacktestResult is realized-only (from fill PnL, not mark-to-market equity). Field is named `realized_max_drawdown` to prevent misinterpretation. Mark-to-market equity curve deferred to future enhancement
- Fill prices: STK → `event.last`, OPT → `(event.bid + event.ask) / 2` (midpoint is optimistic, ignores spread — per spec)
- Commission: STK $0.005/share × abs(qty), OPT $0.65/contract × abs(qty)
- Backtest tests use plain async functions on EventBus, NOT BaseStrategy subclasses, to keep `backtest → core` dependency boundary clean. End-to-end strategy+risk integration test belongs in Phase 4C (apps/trader)
- Events from multiple contracts are merged and sorted by timestamp (Python's sort is stable, so equal-timestamp ticks keep per-contract insertion order)
- Sharpe ratio deferred to Phase 4C (requires daily return tracking with equity curve)

---

## File Structure

```
packages/
  backtest/
    src/backtest/
      executor.py                  ← NEW (SimulatedExecutor)
      runner.py                    ← NEW (BacktestRunner)
      metrics.py                   ← NEW (Trade, BacktestResult, compute_metrics)
      __init__.py                  ← MODIFY (exports)
    tests/
      test_executor.py             ← NEW (4 tests)
      test_runner.py               ← NEW (3 tests)
      test_metrics.py              ← NEW (4 tests)
      test_integration.py          ← NEW (1 test)
```

---

### Task 1: SimulatedExecutor (`backtest/executor.py`)

**Files:**
- Create: `packages/backtest/src/backtest/executor.py`
- Test: `packages/backtest/tests/test_executor.py`

- [ ] **Step 1: Write failing tests**

Create `packages/backtest/tests/test_executor.py`:

```python
import pytest
from datetime import UTC, datetime

from core.bus import EventBus
from core.clock import SimClock
from core.events import FillEvent, MarketEvent, OrderEvent
from core.models import Contract, Leg, Order

from backtest.executor import SimulatedExecutor


def _stk_market(last=150.0):
    return MarketEvent(
        symbol="AAPL",
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        bid=149.90,
        ask=150.10,
        last=last,
        volume=1000,
    )


def _opt_market(bid=5.00, ask=5.40):
    return MarketEvent(
        symbol="AAPL260620C00150000",
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        bid=bid,
        ask=ask,
        last=5.20,
        volume=100,
    )


def _order_event(legs, strategy_id="test"):
    order = Order(legs=legs, strategy_id=strategy_id)
    return OrderEvent(
        order=order,
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        approved_by="PreTradeValidator",
    )


@pytest.mark.asyncio
async def test_fill_stk_at_last_price():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC))
    executor = SimulatedExecutor(bus, clock)
    legs = [Leg(contract=Contract(symbol="AAPL", sec_type="STK"), quantity=100)]
    await executor.on_order(_order_event(legs))
    snapshot = {"AAPL": _stk_market(last=150.0)}
    fills = await executor.fill_pending(snapshot)
    assert len(fills) == 1
    assert fills[0].legs_filled[0].entry_price == 150.0
    # Commission: $0.005/share * 100 = $0.50
    assert fills[0].commission == pytest.approx(0.50)


@pytest.mark.asyncio
async def test_fill_opt_at_midpoint():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC))
    executor = SimulatedExecutor(bus, clock)
    legs = [
        Leg(
            contract=Contract(
                symbol="AAPL260620C00150000",
                sec_type="OPT",
                expiry="20260620",
                strike=150.0,
                right="C",
            ),
            quantity=-1,
        )
    ]
    await executor.on_order(_order_event(legs))
    snapshot = {"AAPL260620C00150000": _opt_market(bid=5.00, ask=5.40)}
    fills = await executor.fill_pending(snapshot)
    assert len(fills) == 1
    assert fills[0].legs_filled[0].entry_price == pytest.approx(5.20)
    # Commission: $0.65/contract * 1 = $0.65
    assert fills[0].commission == pytest.approx(0.65)


@pytest.mark.asyncio
async def test_no_fill_when_empty():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC))
    executor = SimulatedExecutor(bus, clock)
    fills = await executor.fill_pending({"AAPL": _stk_market()})
    assert fills == []


@pytest.mark.asyncio
async def test_all_or_nothing_multi_leg():
    """If any leg lacks market data, the entire order stays pending."""
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC))
    executor = SimulatedExecutor(bus, clock)
    legs = [
        Leg(contract=Contract(symbol="AAPL", sec_type="STK"), quantity=100),
        Leg(
            contract=Contract(
                symbol="AAPL260620C00150000",
                sec_type="OPT",
                expiry="20260620",
                strike=150.0,
                right="C",
            ),
            quantity=-1,
        ),
    ]
    await executor.on_order(_order_event(legs))
    # Only STK in snapshot, OPT missing
    snapshot = {"AAPL": _stk_market()}
    fills = await executor.fill_pending(snapshot)
    assert fills == []
    # Order should still be pending — fill again with complete snapshot
    snapshot["AAPL260620C00150000"] = _opt_market()
    fills = await executor.fill_pending(snapshot)
    assert len(fills) == 1
    assert len(fills[0].legs_filled) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/backtest/tests/test_executor.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backtest.executor'`

- [ ] **Step 3: Implement SimulatedExecutor**

Create `packages/backtest/src/backtest/executor.py`:

```python
from core.bus import EventBus
from core.clock import Clock
from core.events import FillEvent, MarketEvent, OrderEvent
from core.models import Leg


class SimulatedExecutor:
    def __init__(self, bus: EventBus, clock: Clock) -> None:
        self._bus = bus
        self._clock = clock
        self._pending: list[OrderEvent] = []
        self._fill_counter = 0

    async def on_order(self, event: OrderEvent) -> None:
        self._pending.append(event)

    async def fill_pending(
        self, market_snapshot: dict[str, MarketEvent]
    ) -> list[FillEvent]:
        fills: list[FillEvent] = []
        still_pending: list[OrderEvent] = []
        for order_event in self._pending:
            if not _can_fill(order_event, market_snapshot):
                still_pending.append(order_event)
                continue
            legs_filled: list[Leg] = []
            total_commission = 0.0
            for leg in order_event.order.legs:
                market = market_snapshot[leg.contract.symbol]
                price = _fill_price(leg, market)
                legs_filled.append(
                    Leg(
                        contract=leg.contract,
                        quantity=leg.quantity,
                        entry_price=price,
                    )
                )
                total_commission += _commission(leg)
            self._fill_counter += 1
            fill = FillEvent(
                order_id=f"sim-{self._fill_counter}",
                legs_filled=legs_filled,
                timestamp=self._clock.now(),
                commission=total_commission,
            )
            fills.append(fill)
            await self._bus.publish(fill)
        self._pending = still_pending
        return fills


def _can_fill(order_event: OrderEvent, snapshot: dict[str, MarketEvent]) -> bool:
    return all(
        leg.contract.symbol in snapshot for leg in order_event.order.legs
    )


def _fill_price(leg: Leg, market: MarketEvent) -> float:
    if leg.contract.sec_type == "OPT":
        return (market.bid + market.ask) / 2
    return market.last


def _commission(leg: Leg) -> float:
    qty = abs(leg.quantity)
    if leg.contract.sec_type == "OPT":
        return 0.65 * qty
    return 0.005 * qty
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/backtest/tests/test_executor.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check packages/backtest/ && uv run ruff format --check packages/backtest/
git add packages/backtest/
git commit -m "feat(backtest): add SimulatedExecutor with next-tick fills and commission model"
```

---

### Task 2: BacktestRunner (`backtest/runner.py`)

**Files:**
- Create: `packages/backtest/src/backtest/runner.py`
- Test: `packages/backtest/tests/test_runner.py`

- [ ] **Step 1: Write failing tests**

Create `packages/backtest/tests/test_runner.py`:

```python
import pytest
from datetime import UTC, datetime

from core.bus import EventBus
from core.clock import SimClock
from core.events import FillEvent, MarketEvent, OrderEvent
from core.models import Contract, Leg, Order

from backtest.executor import SimulatedExecutor
from backtest.runner import BacktestRunner


class _FakeDataHandler:
    """Minimal DataHandler that yields pre-loaded events."""

    def __init__(self, events_by_contract: dict[str, list[MarketEvent]]) -> None:
        self._events = events_by_contract

    async def subscribe_quote(self, contract):
        for event in self._events.get(contract.symbol, []):
            yield event

    async def fetch_history(self, contract, duration, bar_size):
        return []


def _stk_event(ts, last=150.0):
    return MarketEvent(
        symbol="AAPL",
        timestamp=ts,
        bid=last - 0.10,
        ask=last + 0.10,
        last=last,
        volume=1000,
    )


@pytest.mark.asyncio
async def test_replays_in_timestamp_order():
    """Events from multiple contracts are merged by timestamp."""
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 0, 0, tzinfo=UTC))
    executor = SimulatedExecutor(bus, clock)
    t1 = datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC)
    t2 = datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC)
    t3 = datetime(2026, 6, 4, 14, 32, 0, tzinfo=UTC)
    data = _FakeDataHandler(
        {
            "AAPL": [_stk_event(t1, 100.0), _stk_event(t3, 102.0)],
            "MSFT": [
                MarketEvent(
                    symbol="MSFT",
                    timestamp=t2,
                    bid=299.0,
                    ask=301.0,
                    last=300.0,
                    volume=500,
                )
            ],
        }
    )
    received: list[MarketEvent] = []

    async def capture(event: MarketEvent) -> None:
        received.append(event)

    bus.subscribe(MarketEvent, capture)
    contracts = [
        Contract(symbol="AAPL", sec_type="STK"),
        Contract(symbol="MSFT", sec_type="STK"),
    ]
    runner = BacktestRunner(bus, clock, data, executor, contracts)
    await runner.run()
    assert len(received) == 3
    assert received[0].symbol == "AAPL" and received[0].last == 100.0
    assert received[1].symbol == "MSFT" and received[1].last == 300.0
    assert received[2].symbol == "AAPL" and received[2].last == 102.0


@pytest.mark.asyncio
async def test_look_ahead_guard():
    """Order placed at T=0 (price=100) must fill at T=1 (price=110), NOT T=0."""
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 0, 0, tzinfo=UTC))
    executor = SimulatedExecutor(bus, clock)
    t0 = datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC)
    t1 = datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC)
    data = _FakeDataHandler(
        {"AAPL": [_stk_event(t0, last=100.0), _stk_event(t1, last=110.0)]}
    )
    fills: list[FillEvent] = []

    async def on_market(event: MarketEvent) -> None:
        if event.last == 100.0:
            order = Order(
                legs=[Leg(contract=Contract(symbol="AAPL", sec_type="STK"), quantity=100)],
                strategy_id="test",
            )
            order_event = OrderEvent(
                order=order,
                timestamp=clock.now(),
                approved_by="test",
            )
            await executor.on_order(order_event)

    async def on_fill(event: FillEvent) -> None:
        fills.append(event)

    bus.subscribe(MarketEvent, on_market)
    bus.subscribe(FillEvent, on_fill)
    contracts = [Contract(symbol="AAPL", sec_type="STK")]
    runner = BacktestRunner(bus, clock, data, executor, contracts)
    await runner.run()
    assert len(fills) == 1
    assert fills[0].legs_filled[0].entry_price == 110.0


@pytest.mark.asyncio
async def test_advances_clock():
    """Clock advances to each event's timestamp."""
    bus = EventBus()
    t0 = datetime(2026, 6, 4, 14, 0, 0, tzinfo=UTC)
    clock = SimClock(t0)
    executor = SimulatedExecutor(bus, clock)
    t1 = datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC)
    t2 = datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC)
    data = _FakeDataHandler({"AAPL": [_stk_event(t1, 100.0), _stk_event(t2, 105.0)]})
    timestamps: list[datetime] = []

    async def capture_time(event: MarketEvent) -> None:
        timestamps.append(clock.now())

    bus.subscribe(MarketEvent, capture_time)
    contracts = [Contract(symbol="AAPL", sec_type="STK")]
    runner = BacktestRunner(bus, clock, data, executor, contracts)
    await runner.run()
    assert timestamps == [t1, t2]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/backtest/tests/test_runner.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backtest.runner'`

- [ ] **Step 3: Implement BacktestRunner**

Create `packages/backtest/src/backtest/runner.py`:

```python
from core.bus import EventBus
from core.clock import SimClock
from core.data_handler import DataHandler
from core.events import FillEvent, MarketEvent
from core.models import Contract

from backtest.executor import SimulatedExecutor


class BacktestRunner:
    def __init__(
        self,
        bus: EventBus,
        clock: SimClock,
        data_handler: DataHandler,
        executor: SimulatedExecutor,
        contracts: list[Contract],
    ) -> None:
        self._bus = bus
        self._clock = clock
        self._data_handler = data_handler
        self._executor = executor
        self._contracts = contracts

    async def run(self) -> list[FillEvent]:
        all_events: list[MarketEvent] = []
        for contract in self._contracts:
            async for event in self._data_handler.subscribe_quote(contract):
                all_events.append(event)
        all_events.sort(key=lambda e: e.timestamp)

        all_fills: list[FillEvent] = []
        market_snapshot: dict[str, MarketEvent] = {}
        for event in all_events:
            self._clock.advance_to(event.timestamp)
            market_snapshot[event.symbol] = event
            fills = await self._executor.fill_pending(market_snapshot)
            all_fills.extend(fills)
            await self._bus.publish(event)

        return all_fills
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/backtest/tests/test_runner.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check packages/backtest/ && uv run ruff format --check packages/backtest/
git add packages/backtest/
git commit -m "feat(backtest): add BacktestRunner with timestamp-sorted replay and next-tick fills"
```

---

### Task 3: PerformanceMetrics (`backtest/metrics.py`)

**Files:**
- Create: `packages/backtest/src/backtest/metrics.py`
- Test: `packages/backtest/tests/test_metrics.py`

- [ ] **Step 1: Write failing tests**

Create `packages/backtest/tests/test_metrics.py`:

```python
import pytest
from datetime import UTC, datetime

from core.events import FillEvent
from core.models import Contract, Leg

from backtest.metrics import BacktestResult, compute_metrics


def _stk_fill(symbol, qty, price, commission, order_id="sim-1", ts=None):
    return FillEvent(
        order_id=order_id,
        legs_filled=[
            Leg(
                contract=Contract(symbol=symbol, sec_type="STK"),
                quantity=qty,
                entry_price=price,
            )
        ],
        timestamp=ts or datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        commission=commission,
    )


def _opt_fill(symbol, qty, price, commission, order_id="sim-1", ts=None):
    return FillEvent(
        order_id=order_id,
        legs_filled=[
            Leg(
                contract=Contract(
                    symbol=symbol,
                    sec_type="OPT",
                    expiry="20260620",
                    strike=150.0,
                    right="C",
                ),
                quantity=qty,
                entry_price=price,
            )
        ],
        timestamp=ts or datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        commission=commission,
    )


def test_total_return_stk():
    fills = [
        _stk_fill("AAPL", 100, 100.0, 0.50, "sim-1", datetime(2026, 6, 4, 14, 30, tzinfo=UTC)),
        _stk_fill("AAPL", -100, 110.0, 0.50, "sim-2", datetime(2026, 6, 5, 14, 30, tzinfo=UTC)),
    ]
    result = compute_metrics(fills, initial_equity=100000.0)
    # PnL: (110 - 100) * 100 = $1000, commission: $1.00, net: $999
    assert result.net_pnl == pytest.approx(999.0)
    assert result.total_return == pytest.approx(999.0 / 100000.0)


def test_total_return_opt():
    fills = [
        _opt_fill("AAPL_C150", 1, 5.00, 0.65, "sim-1", datetime(2026, 6, 4, 14, 30, tzinfo=UTC)),
        _opt_fill("AAPL_C150", -1, 7.00, 0.65, "sim-2", datetime(2026, 6, 5, 14, 30, tzinfo=UTC)),
    ]
    result = compute_metrics(fills, initial_equity=100000.0)
    # PnL: (7.00 - 5.00) * 1 * 100 = $200, commission: $1.30, net: $198.70
    assert result.net_pnl == pytest.approx(198.70)


def test_win_rate_and_profit_factor():
    fills = [
        _stk_fill("AAPL", 100, 100.0, 0.0, "sim-1", datetime(2026, 6, 4, 14, 30, tzinfo=UTC)),
        _stk_fill("AAPL", -100, 110.0, 0.0, "sim-2", datetime(2026, 6, 4, 15, 0, tzinfo=UTC)),
        _stk_fill("MSFT", 50, 300.0, 0.0, "sim-3", datetime(2026, 6, 5, 14, 30, tzinfo=UTC)),
        _stk_fill("MSFT", -50, 310.0, 0.0, "sim-4", datetime(2026, 6, 5, 15, 0, tzinfo=UTC)),
        _stk_fill("GOOG", 30, 200.0, 0.0, "sim-5", datetime(2026, 6, 6, 14, 30, tzinfo=UTC)),
        _stk_fill("GOOG", -30, 190.0, 0.0, "sim-6", datetime(2026, 6, 6, 15, 0, tzinfo=UTC)),
    ]
    result = compute_metrics(fills, initial_equity=100000.0)
    # Trade 1: +$1000, Trade 2: +$500, Trade 3: -$300
    assert result.win_rate == pytest.approx(2.0 / 3.0)
    # Profit factor: (1000+500) / 300 = 5.0
    assert result.profit_factor == pytest.approx(5.0)


def test_empty_fills():
    result = compute_metrics([], initial_equity=100000.0)
    assert result.net_pnl == 0.0
    assert result.total_return == 0.0
    assert result.win_rate == 0.0
    assert result.profit_factor == 0.0
    assert result.realized_max_drawdown == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/backtest/tests/test_metrics.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backtest.metrics'`

- [ ] **Step 3: Implement PerformanceMetrics**

Create `packages/backtest/src/backtest/metrics.py`:

```python
from dataclasses import dataclass, field

from core.events import FillEvent


@dataclass
class Trade:
    symbol: str
    quantity: int
    entry_price: float
    exit_price: float
    multiplier: int
    pnl: float


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    total_pnl: float = 0.0
    total_commission: float = 0.0
    net_pnl: float = 0.0
    total_return: float = 0.0
    realized_max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0


def compute_metrics(
    fills: list[FillEvent],
    initial_equity: float,
) -> BacktestResult:
    if not fills:
        return BacktestResult()

    trades = _match_trades(fills)
    total_commission = sum(f.commission for f in fills)
    total_pnl = sum(t.pnl for t in trades)
    net_pnl = total_pnl - total_commission

    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl < 0]
    win_rate = len(winners) / len(trades) if trades else 0.0
    gross_profit = sum(t.pnl for t in winners)
    gross_loss = abs(sum(t.pnl for t in losers))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    realized_max_drawdown = _realized_drawdown(trades)

    return BacktestResult(
        trades=trades,
        total_pnl=total_pnl,
        total_commission=total_commission,
        net_pnl=net_pnl,
        total_return=net_pnl / initial_equity if initial_equity > 0 else 0.0,
        realized_max_drawdown=realized_max_drawdown,
        win_rate=win_rate,
        profit_factor=profit_factor,
    )


def _match_trades(fills: list[FillEvent]) -> list[Trade]:
    open_positions: dict[str, list[tuple[int, float, int]]] = {}
    trades: list[Trade] = []

    for fill in fills:
        for leg in fill.legs_filled:
            symbol = leg.contract.symbol
            qty = leg.quantity
            price = leg.entry_price
            mult = leg.contract.multiplier if leg.contract.sec_type == "OPT" else 1

            if symbol not in open_positions:
                open_positions[symbol] = []
            opens = open_positions[symbol]

            if opens and _is_closing(opens[0][0], qty):
                remaining = abs(qty)
                while remaining > 0 and opens:
                    open_qty, open_price, open_mult = opens[0]
                    match_qty = min(remaining, abs(open_qty))
                    direction = 1 if open_qty > 0 else -1
                    pnl = (price - open_price) * match_qty * direction * mult
                    trades.append(
                        Trade(
                            symbol=symbol,
                            quantity=match_qty,
                            entry_price=open_price,
                            exit_price=price,
                            multiplier=mult,
                            pnl=pnl,
                        )
                    )
                    remaining -= match_qty
                    if match_qty == abs(open_qty):
                        opens.pop(0)
                    else:
                        new_open_qty = open_qty + (match_qty if open_qty < 0 else -match_qty)
                        opens[0] = (new_open_qty, open_price, open_mult)
                if remaining > 0:
                    opens.append((qty // abs(qty) * remaining, price, mult))
            else:
                opens.append((qty, price, mult))

    return trades


def _is_closing(open_qty: int, new_qty: int) -> bool:
    return (open_qty > 0 and new_qty < 0) or (open_qty < 0 and new_qty > 0)


def _realized_drawdown(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for trade in trades:
        cumulative += trade.pnl
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    return max_dd / peak if peak > 0 else 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/backtest/tests/test_metrics.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check packages/backtest/ && uv run ruff format --check packages/backtest/
git add packages/backtest/
git commit -m "feat(backtest): add PerformanceMetrics with FIFO trade matching"
```

---

### Task 4: Integration Test + Backtest Exports

**Files:**
- Create: `packages/backtest/tests/test_integration.py`
- Modify: `packages/backtest/src/backtest/__init__.py`

- [ ] **Step 1: Write integration test**

Create `packages/backtest/tests/test_integration.py`:

```python
import pytest
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from core.bus import EventBus
from core.clock import SimClock
from core.events import FillEvent, MarketEvent, OrderEvent
from core.models import Contract, Leg, Order
from core.partitions import tick_partition_path

from backtest.executor import SimulatedExecutor
from backtest.metrics import compute_metrics
from backtest.runner import BacktestRunner

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


def _write_ticks(base_dir: Path, contract: Contract, date: str, rows: list[dict]):
    partition = tick_partition_path(base_dir, contract, date)
    partition.mkdir(parents=True, exist_ok=True)
    nulls = {
        "model_delta": None,
        "model_gamma": None,
        "model_vega": None,
        "model_theta": None,
        "model_iv": None,
        "model_underlying": None,
    }
    for row in rows:
        for k, v in nulls.items():
            row.setdefault(k, v)
    table = pa.table(
        {col: [r[col] for r in rows] for col in TICK_SCHEMA.names},
        schema=TICK_SCHEMA,
    )
    pq.write_table(table, partition / "000000.parquet", use_dictionary=False)


@pytest.mark.asyncio
async def test_end_to_end_backtest(tmp_path):
    """Full backtest: Parquet → replay → signal → fill → metrics."""
    from market_data.historical import HistoricalDataHandler

    contract = Contract(symbol="AAPL", sec_type="STK")
    t1 = datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC)
    t2 = datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC)
    t3 = datetime(2026, 6, 4, 14, 32, 0, tzinfo=UTC)
    _write_ticks(
        tmp_path,
        contract,
        "2026-06-04",
        [
            {"timestamp": t1, "symbol": "AAPL", "bid": 99.9, "ask": 100.1, "last": 100.0, "volume": 1000},
            {"timestamp": t2, "symbol": "AAPL", "bid": 104.9, "ask": 105.1, "last": 105.0, "volume": 1000},
            {"timestamp": t3, "symbol": "AAPL", "bid": 109.9, "ask": 110.1, "last": 110.0, "volume": 1000},
        ],
    )

    bus = EventBus()
    clock = SimClock(t1)
    data_handler = HistoricalDataHandler(tmp_path)
    executor = SimulatedExecutor(bus, clock)

    # Plain async handler: buy at first tick, sell at second tick
    trade_count = 0

    async def signal_on_market(event: MarketEvent) -> None:
        nonlocal trade_count
        if event.last == 100.0:
            order = Order(
                legs=[Leg(contract=contract, quantity=100)],
                strategy_id="test",
            )
            await executor.on_order(
                OrderEvent(order=order, timestamp=clock.now(), approved_by="test")
            )
            trade_count += 1
        elif event.last == 105.0:
            order = Order(
                legs=[Leg(contract=contract, quantity=-100)],
                strategy_id="test",
            )
            await executor.on_order(
                OrderEvent(order=order, timestamp=clock.now(), approved_by="test")
            )
            trade_count += 1

    bus.subscribe(MarketEvent, signal_on_market)
    runner = BacktestRunner(bus, clock, data_handler, executor, [contract])
    fills = await runner.run()

    assert len(fills) == 2
    # Buy order placed at t1 (price=100), fills at t2 (price=105)
    assert fills[0].legs_filled[0].entry_price == 105.0
    assert fills[0].legs_filled[0].quantity == 100
    # Sell order placed at t2 (price=105), fills at t3 (price=110)
    assert fills[1].legs_filled[0].entry_price == 110.0
    assert fills[1].legs_filled[0].quantity == -100

    result = compute_metrics(fills, initial_equity=100000.0)
    # PnL: (110 - 105) * 100 = $500
    assert result.total_pnl == pytest.approx(500.0)
    assert result.total_commission > 0
    assert result.win_rate == 1.0
```

- [ ] **Step 2: Run integration test**

```bash
uv run pytest packages/backtest/tests/test_integration.py -v
```

Expected: PASS.

- [ ] **Step 3: Update backtest package exports**

Replace `packages/backtest/src/backtest/__init__.py`:

```python
from backtest.executor import SimulatedExecutor
from backtest.metrics import BacktestResult, Trade, compute_metrics
from backtest.runner import BacktestRunner

__all__ = [
    "BacktestResult",
    "BacktestRunner",
    "SimulatedExecutor",
    "Trade",
    "compute_metrics",
]
```

- [ ] **Step 4: Run ALL backtest tests + lint**

```bash
uv run pytest packages/backtest/tests/ -v
```

Expected: all 12 tests PASS.

```bash
uv run ruff check packages/backtest/
uv run ruff format --check packages/backtest/
```

Expected: no errors.

- [ ] **Step 5: Run full repo tests for regressions**

```bash
uv run pytest -v
```

Expected: 86 (existing) + 12 (backtest) = 98 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/backtest/
git commit -m "feat(backtest): add integration test and package exports"
```

---

## Phase 4B–4C Roadmap

### Phase 4B: Live Trading Path (tws-client + market-data live + execution)

| Task | Package | Key Deliverable |
|------|---------|-----------------|
| 4B.1 | tws-client | IB connection manager + auto-reconnect (30s after 23:45 EST disconnect) |
| 4B.2 | tws-client | Quote subscription + pacing limiter (2s/req, 5/15s global) |
| 4B.3 | tws-client | Option chain flow with `qualifyContracts()` |
| 4B.4 | market-data | `LiveDataHandler` — wraps tws-client, implements DataHandler ABC |
| 4B.5 | execution | `LiveGateway` — single-leg + BAG multi-leg order submission |

### Phase 4C: App Assembly (wiring everything together)

| Task | Package | Key Deliverable |
|------|---------|-----------------|
| 4C.1 | apps/trader | Config loading from `config.toml` |
| 4C.2 | apps/trader | Risk pipeline handler (SignalEvent → PreTradeValidator → DecisionLogger → OrderEvent) |
| 4C.3 | apps/trader | Live assembly (`main.py` — Clock → EventBus → TWS → LiveDataHandler → risk → LiveGateway → storage → strategy) |
| 4C.4 | apps/trader | Backtest assembly (swaps to Historical + SimulatedExecutor + SimClock) |
| 4C.5 | apps/trader | End-to-end integration test (strategy → risk → execution → storage) |
