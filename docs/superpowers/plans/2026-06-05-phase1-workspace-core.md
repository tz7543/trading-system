# Phase 1: Workspace + Core Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the uv workspace monorepo scaffold and implement the `core` package — all shared data models, events, event bus, clock abstractions, and DataHandler ABC.

**Architecture:** Monorepo with `uv workspaces`. The `core` package has zero external dependencies and defines all shared types that every other package depends on. Dependency flows one way: all packages → core, never reverse. DataHandler ABC lives in core (not market-data) so strategy only depends on core.

**Tech Stack:** Python 3.11+, uv workspaces, hatchling (build backend), pytest + pytest-asyncio

**Spec Resolutions:**
- DataHandler ABC defined in `core`, implementations in `market-data`
- Storage: `analytics.duckdb` + single `trades.db` (per §7.1, not §2.1's three-file layout)

---

## File Structure

```
trading-system/
├── pyproject.toml                              ← workspace root (NEW)
├── ruff.toml                                   ← existing, no changes needed
├── packages/
│   ├── core/
│   │   ├── pyproject.toml                      ← NEW
│   │   ├── src/core/
│   │   │   ├── __init__.py                     ← NEW (public exports)
│   │   │   ├── models.py                       ← NEW (Bar, Contract, Greeks, etc.)
│   │   │   ├── events.py                       ← NEW (MarketEvent, SignalEvent, etc.)
│   │   │   ├── bus.py                          ← NEW (EventBus pub/sub)
│   │   │   ├── clock.py                        ← NEW (Clock protocol, LiveClock, SimClock)
│   │   │   └── data_handler.py                 ← NEW (DataHandler ABC)
│   │   └── tests/
│   │       ├── test_models.py                  ← NEW
│   │       ├── test_events.py                  ← NEW
│   │       ├── test_bus.py                     ← NEW
│   │       └── test_clock.py                   ← NEW
│   ├── tws-client/                             ← STUB
│   │   ├── pyproject.toml
│   │   └── src/tws_client/__init__.py
│   ├── market-data/                            ← STUB
│   │   ├── pyproject.toml
│   │   └── src/market_data/__init__.py
│   ├── storage/                                ← STUB
│   │   ├── pyproject.toml
│   │   └── src/storage/__init__.py
│   ├── risk/                                   ← STUB
│   │   ├── pyproject.toml
│   │   └── src/risk/__init__.py
│   ├── strategy/                               ← STUB
│   │   ├── pyproject.toml
│   │   └── src/strategy/__init__.py
│   ├── backtest/                               ← STUB
│   │   ├── pyproject.toml
│   │   └── src/backtest/__init__.py
│   └── execution/                              ← STUB
│       ├── pyproject.toml
│       └── src/execution/__init__.py
├── apps/
│   └── trader/
│       ├── pyproject.toml                      ← NEW
│       └── config.toml                         ← NEW (placeholder)
└── data/
    └── .gitkeep                                ← existing
```

**Cleanup:** Remove old scaffold directories (`analysis/`, `risk/`, `strategies/`, `tests/`) — they conflict with the new `packages/` structure.

---

### Task 1: Monorepo Workspace Scaffold

**Files:**
- Create: `pyproject.toml` (root)
- Create: `packages/core/pyproject.toml`
- Create: `packages/core/src/core/__init__.py`
- Create: `packages/{tws-client,market-data,storage,risk,strategy,backtest,execution}/pyproject.toml`
- Create: `packages/{tws-client,market-data,storage,risk,strategy,backtest,execution}/src/{pkg}/__init__.py`
- Create: `apps/trader/pyproject.toml`
- Create: `apps/trader/config.toml`
- Remove: `analysis/`, `risk/`, `strategies/`, `tests/` (old empty scaffolds)

- [ ] **Step 1: Remove old scaffold directories**

```bash
rm -rf analysis/ risk/ strategies/ tests/
```

These were placeholder directories from the initial scaffold and conflict with the new monorepo layout.

- [ ] **Step 2: Create root workspace pyproject.toml**

Create `pyproject.toml` at the repo root. **No `[project]` table** — this is a virtual workspace root, not a buildable package:

```toml
[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.9",
]

[tool.uv.workspace]
members = ["packages/*", "apps/trader"]

[tool.pytest.ini_options]
testpaths = ["packages"]
asyncio_mode = "auto"
```

- [ ] **Step 3: Create core package pyproject.toml**

Create `packages/core/pyproject.toml`:

```toml
[project]
name = "trading-core"
version = "0.1.0"
requires-python = ">=3.11"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/core"]
```

Create `packages/core/src/core/__init__.py` (empty file for now).

- [ ] **Step 4: Create stub packages**

Each stub needs a `pyproject.toml` and an empty `__init__.py`. Use the table below for exact values:

| Directory | Package Name | Import Name | Depends On |
|-----------|-------------|-------------|------------|
| `packages/tws-client/` | `trading-tws-client` | `tws_client` | `trading-core` |
| `packages/market-data/` | `trading-market-data` | `market_data` | `trading-core` |
| `packages/storage/` | `trading-storage` | `storage` | `trading-core` |
| `packages/risk/` | `trading-risk` | `risk` | `trading-core` |
| `packages/strategy/` | `trading-strategy` | `strategy` | `trading-core` |
| `packages/backtest/` | `trading-backtest` | `backtest` | `trading-core` |
| `packages/execution/` | `trading-execution` | `execution` | `trading-core` |

Template for each stub (replace `{pkg_name}`, `{import_name}`). **Critical:** `[tool.uv.sources]` is required — without it, uv won't resolve workspace deps:

```toml
[project]
name = "{pkg_name}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "trading-core",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{import_name}"]

[tool.uv.sources]
trading-core = { workspace = true }
```

Create `packages/{dir}/src/{import_name}/__init__.py` (empty file) for each.

- [ ] **Step 5: Create apps/trader package**

Create `apps/trader/pyproject.toml`. No `[build-system]` — this is a script app, not a buildable package (Phase 4 adds `main.py`):

```toml
[project]
name = "trading-app"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "trading-core",
]

[tool.uv.sources]
trading-core = { workspace = true }
```

Create `apps/trader/config.toml` (placeholder):

```toml
[tws]
host = "127.0.0.1"
port = 7497
client_id = 1

[risk]
max_delta = 500.0
max_vega = 1000.0
max_drawdown = 0.05
max_position_size = 10
max_margin_utilization = 0.8
```

- [ ] **Step 6: Install and verify**

```bash
uv sync
```

Expected: resolves all workspace members, creates `uv.lock`.

```bash
uv run python -c "import core; print('core OK')"
```

Expected: `core OK`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock packages/ apps/
git commit -m "chore: scaffold uv workspace monorepo with core + stub packages"
```

---

### Task 2: Core Data Models

**Files:**
- Create: `packages/core/src/core/models.py`
- Test: `packages/core/tests/test_models.py`

- [ ] **Step 1: Write failing tests**

Create `packages/core/tests/test_models.py`:

```python
from datetime import datetime

from core.models import (
    Bar,
    Contract,
    Greeks,
    Leg,
    OptionChain,
    Order,
    Position,
    RiskLimits,
    ValidationResult,
)


def test_bar():
    bar = Bar(
        timestamp=datetime(2026, 1, 2, 9, 30),
        symbol="AAPL",
        open=150.0,
        high=152.0,
        low=149.0,
        close=151.0,
        volume=1000,
    )
    assert bar.symbol == "AAPL"
    assert bar.close == 151.0


def test_greeks_defaults():
    g = Greeks()
    assert g.delta == 0.0
    assert g.gamma == 0.0
    assert g.implied_vol == 0.0
    assert g.underlying_price == 0.0


def test_contract_stock_defaults():
    c = Contract(symbol="AAPL", sec_type="STK")
    assert c.currency == "USD"
    assert c.exchange == "SMART"
    assert c.expiry == ""
    assert c.right == ""
    assert c.multiplier == 100
    assert c.con_id == 0


def test_contract_option():
    c = Contract(
        symbol="AAPL",
        sec_type="OPT",
        expiry="20260117",
        strike=150.0,
        right="C",
    )
    assert c.sec_type == "OPT"
    assert c.strike == 150.0
    assert c.right == "C"


def test_leg_defaults():
    c = Contract(symbol="AAPL", sec_type="OPT", expiry="20260117", strike=150.0, right="C")
    leg = Leg(contract=c, quantity=1)
    assert leg.entry_price == 0.0
    assert leg.quantity == 1


def test_option_chain():
    chain = OptionChain(
        exchange="SMART",
        trading_class="AAPL",
        multiplier=100,
        expirations=["20260117", "20260221"],
        strikes=[150.0, 152.5, 155.0],
    )
    assert len(chain.expirations) == 2
    assert len(chain.strikes) == 3


def test_risk_limits():
    limits = RiskLimits(
        max_delta=500.0,
        max_vega=1000.0,
        max_drawdown=0.05,
        max_position_size=10,
        max_margin_utilization=0.8,
    )
    assert limits.max_drawdown == 0.05
    assert limits.max_margin_utilization == 0.8


def test_validation_result_approved():
    v = ValidationResult(approved=True)
    assert v.approved is True
    assert v.reason is None


def test_validation_result_rejected():
    v = ValidationResult(approved=False, reason="Delta limit exceeded")
    assert v.approved is False
    assert v.reason == "Delta limit exceeded"


def test_position_defaults():
    c = Contract(symbol="AAPL", sec_type="STK")
    leg = Leg(contract=c, quantity=100)
    pos = Position(legs=[leg], strategy_id="test_strategy")
    assert pos.greeks is None
    assert pos.unrealized_pnl == 0.0
    assert len(pos.legs) == 1


def test_order_defaults():
    c = Contract(symbol="AAPL", sec_type="OPT", expiry="20260117", strike=150.0, right="C")
    leg = Leg(contract=c, quantity=1)
    order = Order(legs=[leg], strategy_id="iron_condor_1")
    assert order.order_type == "LMT"
    assert order.time_in_force == "DAY"
    assert order.limit_price is None


def test_order_with_all_fields():
    c = Contract(symbol="AAPL", sec_type="STK")
    leg = Leg(contract=c, quantity=100, entry_price=150.0)
    order = Order(
        legs=[leg],
        strategy_id="momentum_1",
        order_type="MKT",
        limit_price=None,
        time_in_force="GTC",
    )
    assert order.order_type == "MKT"
    assert order.time_in_force == "GTC"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/core/tests/test_models.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.models'` or `ImportError`.

- [ ] **Step 3: Implement models**

Create `packages/core/src/core/models.py`:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass
class Bar:
    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class Greeks:
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0
    implied_vol: float = 0.0
    underlying_price: float = 0.0


@dataclass
class Contract:
    symbol: str
    sec_type: Literal["STK", "OPT"]
    currency: str = "USD"
    exchange: str = "SMART"
    expiry: str = ""
    strike: float = 0.0
    right: Literal["C", "P", ""] = ""
    multiplier: int = 100
    con_id: int = 0


@dataclass
class Leg:
    contract: Contract
    quantity: int
    entry_price: float = 0.0


@dataclass
class OptionChain:
    exchange: str
    trading_class: str
    multiplier: int
    expirations: list[str]
    strikes: list[float]


@dataclass
class RiskLimits:
    max_delta: float
    max_vega: float
    max_drawdown: float
    max_position_size: int
    max_margin_utilization: float


@dataclass
class ValidationResult:
    approved: bool
    reason: str | None = None


@dataclass
class Position:
    legs: list[Leg]
    strategy_id: str
    greeks: Greeks | None = None
    unrealized_pnl: float = 0.0


@dataclass
class Order:
    legs: list[Leg]
    strategy_id: str
    order_type: Literal["MKT", "LMT", "STP"] = "LMT"
    limit_price: float | None = None
    time_in_force: Literal["DAY", "GTC"] = "DAY"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/core/tests/test_models.py -v
```

Expected: all 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/core/models.py packages/core/tests/test_models.py
git commit -m "feat(core): add data models — Bar, Contract, Greeks, Leg, Order, Position, etc."
```

---

### Task 3: Core Events

**Files:**
- Create: `packages/core/src/core/events.py`
- Test: `packages/core/tests/test_events.py`

- [ ] **Step 1: Write failing tests**

Create `packages/core/tests/test_events.py`:

```python
from datetime import UTC, datetime

from core.events import AlertEvent, FillEvent, MarketEvent, OrderEvent, SignalEvent
from core.models import Contract, Greeks, Leg, Order


def test_market_event_stock():
    event = MarketEvent(
        symbol="AAPL",
        timestamp=datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        bid=150.0,
        ask=150.05,
        last=150.02,
        volume=100,
    )
    assert event.symbol == "AAPL"
    assert event.model_greeks is None
    assert event.bar is None
    assert event.bid_greeks is None


def test_market_event_option_with_greeks():
    g = Greeks(delta=0.45, gamma=0.03, vega=0.12, theta=-0.05, implied_vol=0.25, underlying_price=150.0)
    event = MarketEvent(
        symbol="AAPL260117C00150000",
        timestamp=datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        bid=3.50,
        ask=3.60,
        last=3.55,
        volume=50,
        model_greeks=g,
    )
    assert event.model_greeks is not None
    assert event.model_greeks.delta == 0.45


def test_signal_event():
    c = Contract(symbol="AAPL", sec_type="OPT", expiry="20260117", strike=150.0, right="C")
    order = Order(legs=[Leg(contract=c, quantity=1)], strategy_id="ic_1")
    event = SignalEvent(
        strategy_id="ic_1",
        timestamp=datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        direction="ENTER",
        proposed_order=order,
        reason="IV spike above threshold",
        context={"iv_rank": 0.85},
    )
    assert event.direction == "ENTER"
    assert event.context["iv_rank"] == 0.85


def test_order_event():
    c = Contract(symbol="AAPL", sec_type="STK")
    order = Order(legs=[Leg(contract=c, quantity=100)], strategy_id="test")
    event = OrderEvent(
        order=order,
        timestamp=datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        approved_by="PreTradeValidator",
    )
    assert event.approved_by == "PreTradeValidator"


def test_fill_event():
    c = Contract(symbol="AAPL", sec_type="STK")
    leg = Leg(contract=c, quantity=100, entry_price=150.0)
    event = FillEvent(
        order_id="ORD-001",
        legs_filled=[leg],
        timestamp=datetime(2026, 1, 2, 9, 30, 1, tzinfo=UTC),
        commission=1.0,
    )
    assert event.order_id == "ORD-001"
    assert event.commission == 1.0
    assert event.legs_filled[0].entry_price == 150.0


def test_alert_event():
    event = AlertEvent(
        message="Delta breach",
        value=550.0,
        timestamp=datetime(2026, 1, 2, 10, 0, tzinfo=UTC),
    )
    assert event.message == "Delta breach"
    assert event.value == 550.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/core/tests/test_events.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement events**

Create `packages/core/src/core/events.py`:

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from core.models import Bar, Greeks, Leg, Order


@dataclass
class MarketEvent:
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    last: float
    volume: int
    bid_greeks: Greeks | None = None
    ask_greeks: Greeks | None = None
    last_greeks: Greeks | None = None
    model_greeks: Greeks | None = None
    bar: Bar | None = None


@dataclass
class SignalEvent:
    strategy_id: str
    timestamp: datetime
    direction: Literal["ENTER", "EXIT", "ADJUST"]
    proposed_order: Order
    reason: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderEvent:
    order: Order
    timestamp: datetime
    approved_by: str


@dataclass
class FillEvent:
    order_id: str
    legs_filled: list[Leg]
    timestamp: datetime
    commission: float


@dataclass
class AlertEvent:
    message: str
    value: float
    timestamp: datetime
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/core/tests/test_events.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/core/events.py packages/core/tests/test_events.py
git commit -m "feat(core): add event types — MarketEvent, SignalEvent, OrderEvent, FillEvent, AlertEvent"
```

---

### Task 4: EventBus

**Files:**
- Create: `packages/core/src/core/bus.py`
- Test: `packages/core/tests/test_bus.py`

- [ ] **Step 1: Write failing tests**

Create `packages/core/tests/test_bus.py`:

```python
import pytest

from core.bus import EventBus
from core.events import FillEvent, MarketEvent
from datetime import UTC, datetime


def _make_market_event(symbol: str = "AAPL") -> MarketEvent:
    return MarketEvent(
        symbol=symbol,
        timestamp=datetime(2026, 1, 2, 9, 30, tzinfo=UTC),
        bid=150.0,
        ask=150.05,
        last=150.02,
        volume=100,
    )


@pytest.mark.asyncio
async def test_publish_calls_subscriber():
    bus = EventBus()
    received: list[MarketEvent] = []

    async def handler(event: MarketEvent) -> None:
        received.append(event)

    bus.subscribe(MarketEvent, handler)
    await bus.publish(_make_market_event())

    assert len(received) == 1
    assert received[0].symbol == "AAPL"


@pytest.mark.asyncio
async def test_type_routing_only_matching_type():
    bus = EventBus()
    market_received: list = []
    fill_received: list = []

    async def market_handler(event: MarketEvent) -> None:
        market_received.append(event)

    async def fill_handler(event: FillEvent) -> None:
        fill_received.append(event)

    bus.subscribe(MarketEvent, market_handler)
    bus.subscribe(FillEvent, fill_handler)

    await bus.publish(_make_market_event())

    assert len(market_received) == 1
    assert len(fill_received) == 0


@pytest.mark.asyncio
async def test_multiple_subscribers_same_type():
    bus = EventBus()
    received_a: list = []
    received_b: list = []

    async def handler_a(event: MarketEvent) -> None:
        received_a.append(event)

    async def handler_b(event: MarketEvent) -> None:
        received_b.append(event)

    bus.subscribe(MarketEvent, handler_a)
    bus.subscribe(MarketEvent, handler_b)

    await bus.publish(_make_market_event())

    assert len(received_a) == 1
    assert len(received_b) == 1


@pytest.mark.asyncio
async def test_no_subscribers_does_not_raise():
    bus = EventBus()
    await bus.publish(_make_market_event())


@pytest.mark.asyncio
async def test_unsubscribe():
    bus = EventBus()
    received: list = []

    async def handler(event: MarketEvent) -> None:
        received.append(event)

    bus.subscribe(MarketEvent, handler)
    bus.unsubscribe(MarketEvent, handler)

    await bus.publish(_make_market_event())

    assert len(received) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/core/tests/test_bus.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement EventBus**

Create `packages/core/src/core/bus.py`:

```python
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable[..., Coroutine[Any, Any, None]]]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Callable[..., Coroutine[Any, Any, None]]) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: type, handler: Callable[..., Coroutine[Any, Any, None]]) -> None:
        handlers = self._handlers[event_type]
        handlers.remove(handler)

    async def publish(self, event: Any) -> None:
        for handler in self._handlers[type(event)]:
            await handler(event)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/core/tests/test_bus.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/core/bus.py packages/core/tests/test_bus.py
git commit -m "feat(core): add EventBus with type-routed async pub/sub"
```

---

### Task 5: Clock Abstractions

**Files:**
- Create: `packages/core/src/core/clock.py`
- Test: `packages/core/tests/test_clock.py`

- [ ] **Step 1: Write failing tests**

Create `packages/core/tests/test_clock.py`:

```python
from datetime import UTC, datetime

from core.clock import LiveClock, SimClock


def test_live_clock_returns_utc():
    clock = LiveClock()
    now = clock.now()
    assert now.tzinfo is not None


def test_live_clock_is_recent():
    clock = LiveClock()
    now = clock.now()
    assert now.year >= 2026


def test_sim_clock_returns_initial_time():
    start = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)
    clock = SimClock(start)
    assert clock.now() == start


def test_sim_clock_advance_to():
    start = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)
    clock = SimClock(start)
    new_time = datetime(2026, 1, 2, 10, 0, tzinfo=UTC)
    clock.advance_to(new_time)
    assert clock.now() == new_time


def test_sim_clock_multiple_advances():
    t1 = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 10, 0, tzinfo=UTC)
    t3 = datetime(2026, 1, 2, 15, 59, tzinfo=UTC)
    clock = SimClock(t1)
    clock.advance_to(t2)
    clock.advance_to(t3)
    assert clock.now() == t3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/core/tests/test_clock.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement Clock**

Create `packages/core/src/core/clock.py`:

```python
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class LiveClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class SimClock:
    def __init__(self, start: datetime) -> None:
        self._current = start

    def now(self) -> datetime:
        return self._current

    def advance_to(self, ts: datetime) -> None:
        self._current = ts
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/core/tests/test_clock.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/core/clock.py packages/core/tests/test_clock.py
git commit -m "feat(core): add Clock protocol with LiveClock and SimClock"
```

---

### Task 6: DataHandler ABC + Package Exports

**Files:**
- Create: `packages/core/src/core/data_handler.py`
- Modify: `packages/core/src/core/__init__.py`
- Test: `packages/core/tests/test_data_handler.py`

- [ ] **Step 1: Write failing test**

Create `packages/core/tests/test_data_handler.py`:

```python
import pytest

from core.data_handler import DataHandler


def test_data_handler_cannot_be_instantiated():
    with pytest.raises(TypeError):
        DataHandler()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest packages/core/tests/test_data_handler.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement DataHandler ABC**

Create `packages/core/src/core/data_handler.py`:

```python
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from core.events import MarketEvent
from core.models import Bar, Contract


class DataHandler(ABC):
    @abstractmethod
    async def subscribe_quote(self, contract: Contract) -> AsyncIterator[MarketEvent]: ...

    @abstractmethod
    async def fetch_history(self, contract: Contract, duration: str, bar_size: str) -> list[Bar]: ...
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest packages/core/tests/test_data_handler.py -v
```

Expected: 1 test PASS.

- [ ] **Step 5: Set up package exports**

Update `packages/core/src/core/__init__.py`:

```python
from core.bus import EventBus
from core.clock import Clock, LiveClock, SimClock
from core.data_handler import DataHandler
from core.events import AlertEvent, FillEvent, MarketEvent, OrderEvent, SignalEvent
from core.models import (
    Bar,
    Contract,
    Greeks,
    Leg,
    OptionChain,
    Order,
    Position,
    RiskLimits,
    ValidationResult,
)

__all__ = [
    "AlertEvent",
    "Bar",
    "Clock",
    "Contract",
    "DataHandler",
    "EventBus",
    "FillEvent",
    "Greeks",
    "Leg",
    "LiveClock",
    "MarketEvent",
    "OptionChain",
    "Order",
    "OrderEvent",
    "Position",
    "RiskLimits",
    "SignalEvent",
    "SimClock",
    "ValidationResult",
]
```

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest packages/core/tests/ -v
```

Expected: all 29 tests PASS (12 models + 6 events + 5 bus + 5 clock + 1 data_handler).

- [ ] **Step 7: Run linter**

```bash
uv run ruff check packages/core/
uv run ruff format --check packages/core/
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add packages/core/
git commit -m "feat(core): add DataHandler ABC and set up package exports"
```

---

## Phase 2–4 Roadmap

Sequencing follows **backtest-first** — the entire local-verifiable path is built before anything touching a live IB connection.

### Phase 2: Data Layer (storage → market-data)

**Depends on:** Phase 1 (core) complete

| Task | Package | Key Deliverable |
|------|---------|-----------------|
| 2.1 | storage | `TickWriter` — Parquet Hive-partitioned writes for STK + OPT ticks |
| 2.2 | storage | `TickReader` — Parquet reads with date/symbol pushdown filters |
| 2.3 | storage | `DecisionLogger` — DuckDB writer for SignalEvent snapshots |
| 2.4 | storage | `TradeStore` — SQLite WAL for orders + fills lifecycle |
| 2.5 | storage | `StorageSubscriber` — EventBus subscriber that auto-routes events to the right store |
| 2.6 | market-data | `HistoricalDataHandler` — reads from Parquet, implements DataHandler ABC |

**Test strategy:** All tests use temp directories + in-memory DBs. No external dependencies.

### Phase 3: Trading Logic (strategy → risk)

**Depends on:** Phase 1 complete (Phase 2 not required)

| Task | Package | Key Deliverable |
|------|---------|-----------------|
| 3.1 | strategy | `BaseStrategy` — `on_market_event()`, `signal()`, `on_fill()` |
| 3.2 | strategy | `MultiLegOrder` — factory methods: `iron_condor()`, `bull_call_spread()`, `covered_call()`, `straddle()` |
| 3.3 | strategy | `GreeksCalculator.composite(legs)` — multi-leg Greeks aggregation |
| 3.4 | risk | `PreTradeValidator` — sync validation (position limits, Delta/Vega, spread check) |
| 3.5 | risk | `RealTimeMonitor` — async Greeks drift + drawdown monitoring |
| 3.6 | risk | `CircuitBreaker` — emergency stop + flatten all positions |

**Test strategy:** Pure unit tests with hand-crafted events. No live data needed.

### Phase 4: Integration (backtest → live path → assembly)

**Depends on:** Phase 2 + Phase 3 complete

| Task | Package | Key Deliverable |
|------|---------|-----------------|
| 4.1 | backtest | `SimulatedExecutor` — fill-at-next-bar-open, commission model |
| 4.2 | backtest | `BacktestRunner` — replays Parquet → MarketEvent → EventBus |
| 4.3 | backtest | Performance metrics (Sharpe, max drawdown, win rate, etc.) |
| 4.4 | tws-client | IB connection manager + auto-reconnect |
| 4.5 | tws-client | Quote subscription + option chain flow |
| 4.6 | market-data | `LiveDataHandler` — wraps tws-client, implements DataHandler ABC |
| 4.7 | execution | `LiveGateway` — single-leg + BAG multi-leg order submission |
| 4.8 | apps/trader | Live + backtest assembly (`main.py` + config loading) |

**Test strategy:** Tasks 4.1–4.3 are fully local. Tasks 4.4–4.8 need IB TWS paper trading connection for integration tests.
