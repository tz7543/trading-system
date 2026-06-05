# Phase 3: Trading Logic (strategy + risk) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the strategy and risk packages — strategy base class, multi-leg option order factories, Greeks aggregation, and three-tier risk (pre-trade validation, real-time monitoring, circuit breaker).

**Architecture:** Strategy and risk are independent packages, both depending only on `core`. `GreeksCalculator` lives in strategy; `PreTradeValidator` accepts pre-computed Greeks so risk never imports strategy. Phase 4 wiring connects them: strategy emits SignalEvent → risk validates → DecisionLogger records. Strategy only receives `MarketEvent` and its own `FillEvent` — never portfolio state (prevents look-ahead bias).

**Tech Stack:** Pure Python (no external deps beyond core), pytest + pytest-asyncio

**Spec Resolutions:**
- GreeksCalculator returns position-level Greeks (OPT: per-share × quantity × multiplier; STK: delta = quantity, gamma/vega/theta = 0). This is the unit that `RiskLimits.max_delta` / `max_vega` compare against
- `RiskLimits.max_position_size` counts distinct Position objects (not total legs). One iron condor = 1 position
- `covered_call()` API matches siblings: takes `(underlying, expiry, call_strike, quantity)` — builds Contracts internally, scales shares with quantity (N contracts → 100×N shares + N short calls)
- RealTimeMonitor is implemented as sync `check()` / `should_circuit_break()` — the async event loop that calls them is Phase 4 (app assembly). Spec §9.1 says "非同步，持續運行" — that describes the runtime, not the monitor itself
- DecisionLogger logging happens in Phase 4 wiring (apps/trader); risk only returns `ValidationResult`. This respects `risk → core` only (no `risk → storage`)
- CircuitBreaker triggers on same thresholds as alerts for MVP (max_drawdown exceeded, delta breach per §9.1)
- `py_vollib` Greeks calculation (backtest/supplement) is deferred to Phase 4; Phase 3 only computes composite from existing Greeks
- `BaseStrategy.signal()` types `direction` as `Literal["ENTER", "EXIT", "ADJUST"]` to match `SignalEvent`

---

## File Structure

```
packages/
  strategy/
    src/strategy/
      greeks_calc.py               ← NEW (GreeksCalculator.composite)
      base.py                      ← NEW (BaseStrategy ABC)
      multi_leg.py                 ← NEW (iron_condor, bull_call_spread, covered_call, straddle)
      __init__.py                  ← MODIFY (exports)
    tests/
      test_greeks_calc.py          ← NEW (4 tests)
      test_base_strategy.py        ← NEW (4 tests)
      test_multi_leg.py            ← NEW (4 tests)
  risk/
    src/risk/
      pre_trade.py                 ← NEW (PreTradeValidator)
      monitor.py                   ← NEW (RealTimeMonitor)
      circuit_breaker.py           ← NEW (CircuitBreaker)
      __init__.py                  ← MODIFY (exports)
    tests/
      test_pre_trade.py            ← NEW (4 tests)
      test_monitor.py              ← NEW (4 tests)
      test_circuit_breaker.py      ← NEW (4 tests)
```

---

### Task 1: GreeksCalculator (`strategy/greeks_calc.py`)

**Files:**
- Create: `packages/strategy/src/strategy/greeks_calc.py`
- Test: `packages/strategy/tests/test_greeks_calc.py`

- [ ] **Step 1: Write failing tests**

Create `packages/strategy/tests/test_greeks_calc.py`:

```python
from core.models import Contract, Greeks, Leg

from strategy.greeks_calc import GreeksCalculator


def test_composite_single_opt():
    leg = Leg(
        contract=Contract(
            symbol="AAPL260620C00150000", sec_type="OPT",
            expiry="20260620", strike=150.0, right="C",
        ),
        quantity=1,
    )
    greeks_map = {
        "AAPL260620C00150000": Greeks(
            delta=0.50, gamma=0.03, vega=0.18, theta=-0.05,
        ),
    }
    result = GreeksCalculator.composite([leg], greeks_map)
    assert result.delta == 50.0   # 0.50 * 1 * 100
    assert result.gamma == 3.0    # 0.03 * 1 * 100
    assert result.vega == 18.0    # 0.18 * 1 * 100
    assert result.theta == -5.0   # -0.05 * 1 * 100


def test_composite_covered_call():
    """Discriminating test: STK delta + OPT delta must end up on same unit basis."""
    stk_leg = Leg(
        contract=Contract(symbol="AAPL", sec_type="STK"),
        quantity=100,
    )
    call_leg = Leg(
        contract=Contract(
            symbol="AAPL260620C00150000", sec_type="OPT",
            expiry="20260620", strike=150.0, right="C",
        ),
        quantity=-1,
    )
    greeks_map = {
        "AAPL260620C00150000": Greeks(delta=0.50),
    }
    result = GreeksCalculator.composite([stk_leg, call_leg], greeks_map)
    # STK: +100 shares → delta = +100
    # OPT: -1 call × 0.50 × 100 multiplier → delta = -50
    # Net: +50
    assert result.delta == 50.0
    assert result.gamma == 0.0  # STK has no gamma, OPT gamma=0
    assert result.vega == 0.0


def test_composite_iron_condor():
    legs = [
        Leg(contract=Contract(symbol="IC_P_BUY", sec_type="OPT", expiry="20260620", strike=140.0, right="P"), quantity=1),
        Leg(contract=Contract(symbol="IC_P_SELL", sec_type="OPT", expiry="20260620", strike=145.0, right="P"), quantity=-1),
        Leg(contract=Contract(symbol="IC_C_SELL", sec_type="OPT", expiry="20260620", strike=155.0, right="C"), quantity=-1),
        Leg(contract=Contract(symbol="IC_C_BUY", sec_type="OPT", expiry="20260620", strike=160.0, right="C"), quantity=1),
    ]
    greeks_map = {
        "IC_P_BUY": Greeks(delta=-0.15, gamma=0.02, vega=0.10, theta=-0.03),
        "IC_P_SELL": Greeks(delta=-0.30, gamma=0.04, vega=0.15, theta=-0.05),
        "IC_C_SELL": Greeks(delta=0.30, gamma=0.04, vega=0.15, theta=-0.05),
        "IC_C_BUY": Greeks(delta=0.15, gamma=0.02, vega=0.10, theta=-0.03),
    }
    result = GreeksCalculator.composite(legs, greeks_map)
    # delta: (-0.15*1 + -0.30*-1 + 0.30*-1 + 0.15*1) * 100 = 0
    assert abs(result.delta) < 0.01
    # gamma: (0.02*1 + 0.04*-1 + 0.04*-1 + 0.02*1) * 100 = -4.0
    assert result.gamma == -4.0
    # theta: (-0.03*1 + -0.05*-1 + -0.05*-1 + -0.03*1) * 100 = 4.0
    assert result.theta == 4.0


def test_composite_missing_greeks():
    legs = [
        Leg(contract=Contract(symbol="AAPL260620C00150000", sec_type="OPT", expiry="20260620", strike=150.0, right="C"), quantity=1),
        Leg(contract=Contract(symbol="MISSING", sec_type="OPT", expiry="20260620", strike=160.0, right="C"), quantity=1),
    ]
    greeks_map = {
        "AAPL260620C00150000": Greeks(delta=0.50, gamma=0.03),
    }
    result = GreeksCalculator.composite(legs, greeks_map)
    assert result.delta == 50.0  # only the first leg contributes
    assert result.gamma == 3.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/strategy/tests/test_greeks_calc.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'strategy.greeks_calc'`

- [ ] **Step 3: Implement GreeksCalculator**

Create `packages/strategy/src/strategy/greeks_calc.py`:

```python
from core.models import Greeks, Leg


class GreeksCalculator:
    @staticmethod
    def composite(legs: list[Leg], greeks_map: dict[str, Greeks]) -> Greeks:
        delta = 0.0
        gamma = 0.0
        vega = 0.0
        theta = 0.0
        for leg in legs:
            if leg.contract.sec_type == "STK":
                delta += leg.quantity
                continue
            g = greeks_map.get(leg.contract.symbol)
            if g is None:
                continue
            mult = leg.contract.multiplier
            delta += g.delta * leg.quantity * mult
            gamma += g.gamma * leg.quantity * mult
            vega += g.vega * leg.quantity * mult
            theta += g.theta * leg.quantity * mult
        return Greeks(delta=delta, gamma=gamma, vega=vega, theta=theta)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/strategy/tests/test_greeks_calc.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/
git commit -m "feat(strategy): add GreeksCalculator with position-level composite Greeks"
```

---

### Task 2: BaseStrategy (`strategy/base.py`)

**Files:**
- Create: `packages/strategy/src/strategy/base.py`
- Test: `packages/strategy/tests/test_base_strategy.py`

- [ ] **Step 1: Write failing tests**

Create `packages/strategy/tests/test_base_strategy.py`:

```python
import pytest
from datetime import UTC, datetime
from typing import Literal

from core.bus import EventBus
from core.clock import SimClock
from core.events import FillEvent, MarketEvent, SignalEvent
from core.models import Contract, Leg, Order

from strategy.base import BaseStrategy


class DummyStrategy(BaseStrategy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.received_events: list[MarketEvent] = []
        self.received_fills: list[FillEvent] = []

    async def on_market_event(self, event: MarketEvent) -> None:
        self.received_events.append(event)

    async def on_fill(self, event: FillEvent) -> None:
        self.received_fills.append(event)


def _make_order():
    c = Contract(symbol="AAPL", sec_type="STK")
    return Order(legs=[Leg(contract=c, quantity=100)], strategy_id="test_strat")


@pytest.mark.asyncio
async def test_signal_publishes_to_bus():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    strat = DummyStrategy("test_strat", bus, clock)
    received: list[SignalEvent] = []
    bus.subscribe(SignalEvent, lambda e: received.append(e))
    await strat.signal("ENTER", _make_order(), "Test reason")
    assert len(received) == 1
    assert received[0].direction == "ENTER"
    assert received[0].reason == "Test reason"
    assert received[0].proposed_order.strategy_id == "test_strat"


@pytest.mark.asyncio
async def test_signal_uses_clock_timestamp():
    bus = EventBus()
    ts = datetime(2026, 6, 4, 15, 0, 0, tzinfo=UTC)
    clock = SimClock(ts)
    strat = DummyStrategy("test_strat", bus, clock)
    received: list[SignalEvent] = []
    bus.subscribe(SignalEvent, lambda e: received.append(e))
    await strat.signal("EXIT", _make_order(), "Close position")
    assert received[0].timestamp == ts


@pytest.mark.asyncio
async def test_signal_includes_strategy_id():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    strat = DummyStrategy("my_ic_strategy", bus, clock)
    received: list[SignalEvent] = []
    bus.subscribe(SignalEvent, lambda e: received.append(e))
    await strat.signal("ENTER", _make_order(), "IV spike")
    assert received[0].strategy_id == "my_ic_strategy"


def test_cannot_instantiate_base_strategy():
    bus = EventBus()
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    with pytest.raises(TypeError):
        BaseStrategy("test", bus, clock)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/strategy/tests/test_base_strategy.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'strategy.base'`

- [ ] **Step 3: Implement BaseStrategy**

Create `packages/strategy/src/strategy/base.py`:

```python
from abc import ABC, abstractmethod
from typing import Literal

from core.bus import EventBus
from core.clock import Clock
from core.events import FillEvent, MarketEvent, SignalEvent
from core.models import Order


class BaseStrategy(ABC):
    def __init__(self, strategy_id: str, bus: EventBus, clock: Clock) -> None:
        self.strategy_id = strategy_id
        self._bus = bus
        self._clock = clock

    @abstractmethod
    async def on_market_event(self, event: MarketEvent) -> None: ...

    @abstractmethod
    async def on_fill(self, event: FillEvent) -> None: ...

    async def signal(
        self,
        direction: Literal["ENTER", "EXIT", "ADJUST"],
        order: Order,
        reason: str,
        context: dict | None = None,
    ) -> None:
        event = SignalEvent(
            strategy_id=self.strategy_id,
            timestamp=self._clock.now(),
            direction=direction,
            proposed_order=order,
            reason=reason,
            context=context or {},
        )
        await self._bus.publish(event)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/strategy/tests/test_base_strategy.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/
git commit -m "feat(strategy): add BaseStrategy ABC with signal emission via EventBus"
```

---

### Task 3: MultiLegOrder + Strategy Exports

**Files:**
- Create: `packages/strategy/src/strategy/multi_leg.py`
- Modify: `packages/strategy/src/strategy/__init__.py`
- Test: `packages/strategy/tests/test_multi_leg.py`

- [ ] **Step 1: Write failing tests**

Create `packages/strategy/tests/test_multi_leg.py`:

```python
from core.models import Contract

from strategy.multi_leg import bull_call_spread, covered_call, iron_condor, straddle


def test_iron_condor():
    order = iron_condor(
        underlying="AAPL",
        expiry="20260620",
        put_buy_strike=140.0,
        put_sell_strike=145.0,
        call_sell_strike=155.0,
        call_buy_strike=160.0,
        quantity=2,
        strategy_id="ic_1",
    )
    assert len(order.legs) == 4
    assert order.strategy_id == "ic_1"
    # Buy put (lower)
    assert order.legs[0].contract.strike == 140.0
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == 2
    # Sell put
    assert order.legs[1].contract.strike == 145.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == -2
    # Sell call
    assert order.legs[2].contract.strike == 155.0
    assert order.legs[2].contract.right == "C"
    assert order.legs[2].quantity == -2
    # Buy call (higher)
    assert order.legs[3].contract.strike == 160.0
    assert order.legs[3].contract.right == "C"
    assert order.legs[3].quantity == 2


def test_bull_call_spread():
    order = bull_call_spread(
        underlying="AAPL",
        expiry="20260620",
        buy_strike=150.0,
        sell_strike=160.0,
        strategy_id="bcs_1",
    )
    assert len(order.legs) == 2
    assert order.legs[0].contract.strike == 150.0
    assert order.legs[0].contract.right == "C"
    assert order.legs[0].quantity == 1
    assert order.legs[1].contract.strike == 160.0
    assert order.legs[1].contract.right == "C"
    assert order.legs[1].quantity == -1


def test_covered_call():
    order = covered_call(
        underlying="AAPL",
        expiry="20260620",
        call_strike=155.0,
        quantity=2,
        strategy_id="cc_1",
    )
    assert len(order.legs) == 2
    # Stock leg: 100 shares per contract × quantity
    assert order.legs[0].contract.sec_type == "STK"
    assert order.legs[0].contract.symbol == "AAPL"
    assert order.legs[0].quantity == 200  # 100 * 2
    # Call leg: short
    assert order.legs[1].contract.sec_type == "OPT"
    assert order.legs[1].contract.strike == 155.0
    assert order.legs[1].contract.right == "C"
    assert order.legs[1].quantity == -2


def test_straddle():
    order = straddle(
        underlying="AAPL",
        expiry="20260620",
        strike=150.0,
        quantity=3,
        strategy_id="strad_1",
    )
    assert len(order.legs) == 2
    assert order.legs[0].contract.strike == 150.0
    assert order.legs[0].contract.right == "C"
    assert order.legs[0].quantity == 3
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/strategy/tests/test_multi_leg.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'strategy.multi_leg'`

- [ ] **Step 3: Implement MultiLegOrder factories**

Create `packages/strategy/src/strategy/multi_leg.py`:

```python
from core.models import Contract, Leg, Order


def iron_condor(
    underlying: str,
    expiry: str,
    put_buy_strike: float,
    put_sell_strike: float,
    call_sell_strike: float,
    call_buy_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    legs = [
        Leg(
            contract=Contract(symbol=underlying, sec_type="OPT", expiry=expiry, strike=put_buy_strike, right="P"),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(symbol=underlying, sec_type="OPT", expiry=expiry, strike=put_sell_strike, right="P"),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(symbol=underlying, sec_type="OPT", expiry=expiry, strike=call_sell_strike, right="C"),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(symbol=underlying, sec_type="OPT", expiry=expiry, strike=call_buy_strike, right="C"),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def bull_call_spread(
    underlying: str,
    expiry: str,
    buy_strike: float,
    sell_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    legs = [
        Leg(
            contract=Contract(symbol=underlying, sec_type="OPT", expiry=expiry, strike=buy_strike, right="C"),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(symbol=underlying, sec_type="OPT", expiry=expiry, strike=sell_strike, right="C"),
            quantity=-quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def covered_call(
    underlying: str,
    expiry: str,
    call_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    legs = [
        Leg(
            contract=Contract(symbol=underlying, sec_type="STK"),
            quantity=100 * quantity,
        ),
        Leg(
            contract=Contract(symbol=underlying, sec_type="OPT", expiry=expiry, strike=call_strike, right="C"),
            quantity=-quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)


def straddle(
    underlying: str,
    expiry: str,
    strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    legs = [
        Leg(
            contract=Contract(symbol=underlying, sec_type="OPT", expiry=expiry, strike=strike, right="C"),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(symbol=underlying, sec_type="OPT", expiry=expiry, strike=strike, right="P"),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/strategy/tests/test_multi_leg.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Update strategy package exports**

Replace `packages/strategy/src/strategy/__init__.py`:

```python
from strategy.base import BaseStrategy
from strategy.greeks_calc import GreeksCalculator
from strategy.multi_leg import bull_call_spread, covered_call, iron_condor, straddle

__all__ = [
    "BaseStrategy",
    "GreeksCalculator",
    "bull_call_spread",
    "covered_call",
    "iron_condor",
    "straddle",
]
```

- [ ] **Step 6: Run all strategy tests + linter**

```bash
uv run pytest packages/strategy/tests/ -v
```

Expected: all 12 tests PASS (4 greeks + 4 base + 4 multi_leg).

```bash
uv run ruff check packages/strategy/
uv run ruff format --check packages/strategy/
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add packages/strategy/
git commit -m "feat(strategy): add multi-leg option factories and package exports"
```

---

### Task 4: PreTradeValidator (`risk/pre_trade.py`)

**Files:**
- Create: `packages/risk/src/risk/pre_trade.py`
- Test: `packages/risk/tests/test_pre_trade.py`

- [ ] **Step 1: Write failing tests**

Create `packages/risk/tests/test_pre_trade.py`:

```python
from datetime import UTC, datetime

from core.events import SignalEvent
from core.models import Contract, Greeks, Leg, Order, Position, RiskLimits

from risk.pre_trade import PreTradeValidator


def _limits():
    return RiskLimits(
        max_delta=200.0,
        max_vega=500.0,
        max_drawdown=0.10,
        max_position_size=5,
        max_margin_utilization=0.80,
    )


def _signal(legs=None, strategy_id="test"):
    if legs is None:
        c = Contract(symbol="AAPL", sec_type="STK")
        legs = [Leg(contract=c, quantity=100)]
    order = Order(legs=legs, strategy_id=strategy_id)
    return SignalEvent(
        strategy_id=strategy_id,
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        direction="ENTER",
        proposed_order=order,
        reason="Test",
    )


def test_approved_within_limits():
    validator = PreTradeValidator(_limits())
    result = validator.validate(
        signal=_signal(),
        portfolio_greeks=Greeks(delta=50.0, vega=100.0),
        proposed_greeks=Greeks(delta=100.0, vega=50.0),
        positions=[],
    )
    assert result.approved is True


def test_rejected_position_limit():
    validator = PreTradeValidator(_limits())
    existing = [
        Position(legs=[Leg(contract=Contract(symbol="AAPL", sec_type="STK"), quantity=100)], strategy_id=f"s{i}")
        for i in range(5)
    ]
    result = validator.validate(
        signal=_signal(),
        portfolio_greeks=Greeks(),
        proposed_greeks=Greeks(),
        positions=existing,
    )
    assert result.approved is False
    assert "Position limit" in result.reason


def test_rejected_delta_exceeded():
    validator = PreTradeValidator(_limits())
    result = validator.validate(
        signal=_signal(),
        portfolio_greeks=Greeks(delta=150.0),
        proposed_greeks=Greeks(delta=100.0),
        positions=[],
    )
    assert result.approved is False
    assert "Delta" in result.reason


def test_rejected_vega_exceeded():
    validator = PreTradeValidator(_limits())
    result = validator.validate(
        signal=_signal(),
        portfolio_greeks=Greeks(vega=400.0),
        proposed_greeks=Greeks(vega=200.0),
        positions=[],
    )
    assert result.approved is False
    assert "Vega" in result.reason
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/risk/tests/test_pre_trade.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'risk.pre_trade'`

- [ ] **Step 3: Implement PreTradeValidator**

Create `packages/risk/src/risk/pre_trade.py`:

```python
from core.events import SignalEvent
from core.models import Greeks, Position, RiskLimits, ValidationResult


class PreTradeValidator:
    def __init__(self, risk_limits: RiskLimits) -> None:
        self._limits = risk_limits

    def validate(
        self,
        signal: SignalEvent,
        portfolio_greeks: Greeks,
        proposed_greeks: Greeks,
        positions: list[Position],
    ) -> ValidationResult:
        new_count = len(positions) + 1
        if new_count > self._limits.max_position_size:
            return ValidationResult(
                approved=False,
                reason=f"Position limit exceeded: {new_count} > {self._limits.max_position_size}",
            )

        new_delta = portfolio_greeks.delta + proposed_greeks.delta
        if abs(new_delta) > self._limits.max_delta:
            return ValidationResult(
                approved=False,
                reason=f"Delta limit exceeded: {new_delta:.2f} > +/-{self._limits.max_delta}",
            )

        new_vega = portfolio_greeks.vega + proposed_greeks.vega
        if abs(new_vega) > self._limits.max_vega:
            return ValidationResult(
                approved=False,
                reason=f"Vega limit exceeded: {new_vega:.2f} > +/-{self._limits.max_vega}",
            )

        return ValidationResult(approved=True)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/risk/tests/test_pre_trade.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/risk/
git commit -m "feat(risk): add PreTradeValidator with delta/vega/position-count checks"
```

---

### Task 5: RealTimeMonitor (`risk/monitor.py`)

**Files:**
- Create: `packages/risk/src/risk/monitor.py`
- Test: `packages/risk/tests/test_monitor.py`

- [ ] **Step 1: Write failing tests**

Create `packages/risk/tests/test_monitor.py`:

```python
from datetime import UTC, datetime

from core.clock import SimClock
from core.events import AlertEvent
from core.models import Greeks, RiskLimits

from risk.monitor import RealTimeMonitor


def _limits():
    return RiskLimits(
        max_delta=200.0,
        max_vega=500.0,
        max_drawdown=0.10,
        max_position_size=5,
        max_margin_utilization=0.80,
    )


def test_no_alerts_within_limits():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    alerts = monitor.check(
        portfolio_greeks=Greeks(delta=100.0, vega=200.0),
        equity=100000.0,
    )
    assert alerts == []


def test_alert_on_drawdown():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    monitor.check(portfolio_greeks=Greeks(), equity=100000.0)
    alerts = monitor.check(
        portfolio_greeks=Greeks(),
        equity=85000.0,
    )
    assert len(alerts) == 1
    assert "drawdown" in alerts[0].message.lower()


def test_alert_on_delta_drift():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    alerts = monitor.check(
        portfolio_greeks=Greeks(delta=250.0),
        equity=100000.0,
    )
    assert any("delta" in a.message.lower() for a in alerts)


def test_should_circuit_break_on_drawdown():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    monitor.check(portfolio_greeks=Greeks(), equity=100000.0)
    assert not monitor.should_circuit_break(Greeks(), 95000.0)
    assert monitor.should_circuit_break(Greeks(), 85000.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/risk/tests/test_monitor.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'risk.monitor'`

- [ ] **Step 3: Implement RealTimeMonitor**

Create `packages/risk/src/risk/monitor.py`:

```python
from core.clock import Clock
from core.events import AlertEvent
from core.models import Greeks, RiskLimits


class RealTimeMonitor:
    def __init__(self, risk_limits: RiskLimits, clock: Clock) -> None:
        self._limits = risk_limits
        self._clock = clock
        self._peak_equity: float = 0.0

    def update_equity(self, equity: float) -> None:
        if equity > self._peak_equity:
            self._peak_equity = equity

    def check(
        self,
        portfolio_greeks: Greeks,
        equity: float,
    ) -> list[AlertEvent]:
        self.update_equity(equity)
        alerts: list[AlertEvent] = []
        now = self._clock.now()

        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity
            if drawdown > self._limits.max_drawdown:
                alerts.append(
                    AlertEvent(
                        message=f"Max drawdown exceeded: {drawdown:.2%}",
                        value=drawdown,
                        timestamp=now,
                    )
                )

        if abs(portfolio_greeks.delta) > self._limits.max_delta:
            alerts.append(
                AlertEvent(
                    message=f"Delta drift: {portfolio_greeks.delta:.2f} exceeds +/-{self._limits.max_delta}",
                    value=portfolio_greeks.delta,
                    timestamp=now,
                )
            )

        if abs(portfolio_greeks.vega) > self._limits.max_vega:
            alerts.append(
                AlertEvent(
                    message=f"Vega drift: {portfolio_greeks.vega:.2f} exceeds +/-{self._limits.max_vega}",
                    value=portfolio_greeks.vega,
                    timestamp=now,
                )
            )

        return alerts

    def should_circuit_break(
        self,
        portfolio_greeks: Greeks,
        equity: float,
    ) -> bool:
        self.update_equity(equity)
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity
            if drawdown > self._limits.max_drawdown:
                return True
        if abs(portfolio_greeks.delta) > self._limits.max_delta:
            return True
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/risk/tests/test_monitor.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/risk/
git commit -m "feat(risk): add RealTimeMonitor with drawdown and Greeks drift checks"
```

---

### Task 6: CircuitBreaker + Risk Exports

**Files:**
- Create: `packages/risk/src/risk/circuit_breaker.py`
- Modify: `packages/risk/src/risk/__init__.py`
- Test: `packages/risk/tests/test_circuit_breaker.py`

- [ ] **Step 1: Write failing tests**

Create `packages/risk/tests/test_circuit_breaker.py`:

```python
from core.models import Contract, Leg, Position

from risk.circuit_breaker import CircuitBreaker


def test_initially_not_triggered():
    cb = CircuitBreaker()
    assert cb.is_triggered is False


def test_trigger_sets_state():
    cb = CircuitBreaker()
    cb.trigger()
    assert cb.is_triggered is True


def test_flatten_orders_reverses_positions():
    cb = CircuitBreaker()
    positions = [
        Position(
            legs=[
                Leg(contract=Contract(symbol="AAPL", sec_type="STK"), quantity=100),
            ],
            strategy_id="momentum_1",
        ),
        Position(
            legs=[
                Leg(contract=Contract(symbol="AAPL260620C00150000", sec_type="OPT", expiry="20260620", strike=150.0, right="C"), quantity=-2),
                Leg(contract=Contract(symbol="AAPL260620P00140000", sec_type="OPT", expiry="20260620", strike=140.0, right="P"), quantity=2),
            ],
            strategy_id="ic_1",
        ),
    ]
    orders = cb.flatten_orders(positions)
    assert len(orders) == 2
    # First position: STK +100 → flatten with -100
    assert orders[0].legs[0].quantity == -100
    assert orders[0].order_type == "MKT"
    assert orders[0].strategy_id == "momentum_1"
    # Second position: OPT -2,+2 → flatten with +2,-2
    assert orders[1].legs[0].quantity == 2
    assert orders[1].legs[1].quantity == -2
    assert orders[1].order_type == "MKT"


def test_reset_clears_triggered():
    cb = CircuitBreaker()
    cb.trigger()
    assert cb.is_triggered is True
    cb.reset()
    assert cb.is_triggered is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/risk/tests/test_circuit_breaker.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'risk.circuit_breaker'`

- [ ] **Step 3: Implement CircuitBreaker**

Create `packages/risk/src/risk/circuit_breaker.py`:

```python
from core.models import Leg, Order, Position


class CircuitBreaker:
    def __init__(self) -> None:
        self._triggered = False

    @property
    def is_triggered(self) -> bool:
        return self._triggered

    def trigger(self) -> None:
        self._triggered = True

    def reset(self) -> None:
        self._triggered = False

    def flatten_orders(self, positions: list[Position]) -> list[Order]:
        orders: list[Order] = []
        for pos in positions:
            flatten_legs = [
                Leg(contract=leg.contract, quantity=-leg.quantity)
                for leg in pos.legs
            ]
            orders.append(
                Order(
                    legs=flatten_legs,
                    strategy_id=pos.strategy_id,
                    order_type="MKT",
                )
            )
        return orders
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/risk/tests/test_circuit_breaker.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Update risk package exports**

Replace `packages/risk/src/risk/__init__.py`:

```python
from risk.circuit_breaker import CircuitBreaker
from risk.monitor import RealTimeMonitor
from risk.pre_trade import PreTradeValidator

__all__ = [
    "CircuitBreaker",
    "PreTradeValidator",
    "RealTimeMonitor",
]
```

- [ ] **Step 6: Run all risk tests + full Phase 3 suite + linter**

```bash
uv run pytest packages/strategy/tests/ packages/risk/tests/ -v
```

Expected: all 24 tests PASS (12 strategy + 12 risk).

```bash
uv run ruff check packages/strategy/ packages/risk/
uv run ruff format --check packages/strategy/ packages/risk/
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add packages/risk/
git commit -m "feat(risk): add CircuitBreaker and set up risk package exports"
```

---

## Phase 4 Roadmap

### Phase 4: Integration (backtest + live path + assembly)

**Depends on:** Phase 2 + Phase 3 complete.

| Task | Package | Key Deliverable |
|------|---------|-----------------|
| 4.1 | backtest | `SimulatedExecutor` — fill-at-next-bar-open, commission model |
| 4.2 | backtest | `BacktestRunner` — replays Parquet → MarketEvent → EventBus |
| 4.3 | backtest | Performance metrics (Sharpe, max drawdown, win rate) |
| 4.4 | tws-client | IB connection manager + auto-reconnect |
| 4.5 | tws-client | Quote subscription + option chain flow |
| 4.6 | market-data | `LiveDataHandler` — wraps tws-client, implements DataHandler ABC |
| 4.7 | execution | `LiveGateway` — single-leg + BAG multi-leg order submission |
| 4.8 | apps/trader | Live + backtest assembly (`main.py` + config loading) + wire DecisionLogger into risk pipeline |
