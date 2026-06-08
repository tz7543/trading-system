# Dynamic Strike Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 4 pure functions to `strategy/strike_selector.py` that select option strikes from a chain using delta-based or ATM-relative logic.

**Architecture:** Pure functions in a new `strike_selector.py` file, depending only on `core.models.Greeks` and `typing.Literal`. No new dependencies. The module sits alongside `multi_leg.py` and `greeks_calc.py` in the strategy package.

**Tech Stack:** Python 3.11, `core.models.Greeks`, pytest

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `packages/strategy/src/strategy/strike_selector.py` | 4 pure strike selection functions |
| Create | `packages/strategy/tests/test_strike_selector.py` | ~17 tests covering all functions + integration |
| Modify | `packages/strategy/src/strategy/__init__.py` | Export the 4 new functions |

---

### Task 1: `filter_strikes`

**Files:**
- Create: `packages/strategy/tests/test_strike_selector.py`
- Create: `packages/strategy/src/strategy/strike_selector.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/strategy/tests/test_strike_selector.py`:

```python
import pytest

from strategy.strike_selector import filter_strikes


STRIKES = [140.0, 142.5, 145.0, 147.5, 150.0, 152.5, 155.0, 157.5, 160.0]


def test_filter_strikes_normal():
    result = filter_strikes(STRIKES, underlying_price=150.0, max_distance=2)
    assert result == [145.0, 147.5, 150.0, 152.5, 155.0]


def test_filter_strikes_empty():
    result = filter_strikes([], underlying_price=150.0, max_distance=5)
    assert result == []


def test_filter_strikes_all_within_range():
    result = filter_strikes(STRIKES, underlying_price=150.0, max_distance=20)
    assert result == STRIKES
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/strategy/tests/test_strike_selector.py -v`
Expected: FAIL with `ImportError` (module not found)

- [ ] **Step 3: Write minimal implementation**

Create `packages/strategy/src/strategy/strike_selector.py`:

```python
from typing import Literal

from core.models import Greeks


def filter_strikes(
    strikes: list[float],
    underlying_price: float,
    max_distance: int = 10,
) -> list[float]:
    if not strikes:
        return []
    sorted_strikes = sorted(strikes)
    atm_idx = min(
        range(len(sorted_strikes)),
        key=lambda i: (abs(sorted_strikes[i] - underlying_price), sorted_strikes[i]),
    )
    lo = max(0, atm_idx - max_distance)
    hi = min(len(sorted_strikes), atm_idx + max_distance + 1)
    return sorted_strikes[lo:hi]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_strike_selector.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/strike_selector.py packages/strategy/tests/test_strike_selector.py
git commit -m "feat(strategy): add filter_strikes function"
```

---

### Task 2: `select_atm`

**Files:**
- Modify: `packages/strategy/tests/test_strike_selector.py`
- Modify: `packages/strategy/src/strategy/strike_selector.py`

- [ ] **Step 1: Write the failing tests**

Add to `packages/strategy/tests/test_strike_selector.py`:

```python
from strategy.strike_selector import filter_strikes, select_atm


STRIKES = [140.0, 142.5, 145.0, 147.5, 150.0, 152.5, 155.0, 157.5, 160.0]


def test_select_atm_exact():
    result = select_atm(STRIKES, underlying_price=150.0)
    assert result == 150.0


def test_select_atm_between_strikes():
    result = select_atm(STRIKES, underlying_price=151.0)
    assert result == 150.0


def test_select_atm_equidistant_picks_lower():
    result = select_atm([145.0, 150.0, 155.0], underlying_price=152.5)
    assert result == 150.0


def test_select_atm_positive_offset():
    result = select_atm(STRIKES, underlying_price=150.0, offset=2)
    assert result == 155.0


def test_select_atm_negative_offset():
    result = select_atm(STRIKES, underlying_price=150.0, offset=-2)
    assert result == 145.0


def test_select_atm_offset_out_of_range():
    with pytest.raises(ValueError, match="offset .* out of range"):
        select_atm(STRIKES, underlying_price=150.0, offset=20)


def test_select_atm_empty_strikes():
    with pytest.raises(ValueError, match="no strikes available"):
        select_atm([], underlying_price=150.0)
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `uv run pytest packages/strategy/tests/test_strike_selector.py::test_select_atm_exact -v`
Expected: FAIL with `ImportError` (function not defined)

- [ ] **Step 3: Write minimal implementation**

Add to `packages/strategy/src/strategy/strike_selector.py`:

```python
def select_atm(
    strikes: list[float],
    underlying_price: float,
    offset: int = 0,
) -> float:
    if not strikes:
        raise ValueError("no strikes available")
    sorted_strikes = sorted(strikes)
    atm_idx = min(
        range(len(sorted_strikes)),
        key=lambda i: (abs(sorted_strikes[i] - underlying_price), sorted_strikes[i]),
    )
    target_idx = atm_idx + offset
    if target_idx < 0 or target_idx >= len(sorted_strikes):
        raise ValueError(
            f"offset {offset} out of range, only {len(sorted_strikes)} strikes available"
        )
    return sorted_strikes[target_idx]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_strike_selector.py -v`
Expected: 10 PASSED (3 filter + 7 select_atm)

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/strike_selector.py packages/strategy/tests/test_strike_selector.py
git commit -m "feat(strategy): add select_atm function"
```

---

### Task 3: `select_by_delta`

**Files:**
- Modify: `packages/strategy/tests/test_strike_selector.py`
- Modify: `packages/strategy/src/strategy/strike_selector.py`

- [ ] **Step 1: Write the failing tests**

Add to `packages/strategy/tests/test_strike_selector.py`:

```python
from core.models import Greeks

from strategy.strike_selector import filter_strikes, select_atm, select_by_delta


def test_select_by_delta_call():
    greeks_map = {
        145.0: Greeks(delta=0.70),
        150.0: Greeks(delta=0.50),
        155.0: Greeks(delta=0.30),
        160.0: Greeks(delta=0.15),
    }
    result = select_by_delta(
        strikes=[145.0, 150.0, 155.0, 160.0],
        greeks_map=greeks_map,
        target_delta=0.30,
        right="C",
    )
    assert result == 155.0


def test_select_by_delta_put():
    greeks_map = {
        140.0: Greeks(delta=-0.15),
        145.0: Greeks(delta=-0.30),
        150.0: Greeks(delta=-0.50),
        155.0: Greeks(delta=-0.70),
    }
    result = select_by_delta(
        strikes=[140.0, 145.0, 150.0, 155.0],
        greeks_map=greeks_map,
        target_delta=0.30,
        right="P",
    )
    assert result == 145.0


def test_select_by_delta_no_greeks():
    with pytest.raises(ValueError, match="no greeks available"):
        select_by_delta(
            strikes=[145.0, 150.0, 155.0],
            greeks_map={},
            target_delta=0.30,
            right="C",
        )


def test_select_by_delta_partial_greeks():
    greeks_map = {
        150.0: Greeks(delta=0.50),
        155.0: Greeks(delta=0.30),
    }
    result = select_by_delta(
        strikes=[145.0, 150.0, 155.0, 160.0],
        greeks_map=greeks_map,
        target_delta=0.50,
        right="C",
    )
    assert result == 150.0


def test_select_by_delta_tie_picks_lower():
    greeks_map = {
        145.0: Greeks(delta=0.40),
        155.0: Greeks(delta=0.20),
    }
    result = select_by_delta(
        strikes=[145.0, 155.0],
        greeks_map=greeks_map,
        target_delta=0.30,
        right="C",
    )
    assert result == 145.0
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `uv run pytest packages/strategy/tests/test_strike_selector.py::test_select_by_delta_call -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Add to `packages/strategy/src/strategy/strike_selector.py`:

```python
def select_by_delta(
    strikes: list[float],
    greeks_map: dict[float, Greeks],
    target_delta: float,
    right: Literal["C", "P"],
) -> float:
    candidates: list[tuple[float, float]] = []
    for strike in strikes:
        g = greeks_map.get(strike)
        if g is None:
            continue
        delta_val = abs(g.delta) if right == "P" else g.delta
        distance = abs(delta_val - target_delta)
        candidates.append((strike, distance))
    if not candidates:
        raise ValueError("no greeks available for any strike")
    candidates.sort(key=lambda c: (c[1], c[0]))
    return candidates[0][0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_strike_selector.py -v`
Expected: 15 PASSED (3 filter + 7 select_atm + 5 select_by_delta)

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/strike_selector.py packages/strategy/tests/test_strike_selector.py
git commit -m "feat(strategy): add select_by_delta function"
```

---

### Task 4: `select_strike`

**Files:**
- Modify: `packages/strategy/tests/test_strike_selector.py`
- Modify: `packages/strategy/src/strategy/strike_selector.py`

- [ ] **Step 1: Write the failing tests**

Add to `packages/strategy/tests/test_strike_selector.py`:

```python
from strategy.strike_selector import (
    filter_strikes,
    select_atm,
    select_by_delta,
    select_strike,
)


def test_select_strike_with_greeks():
    greeks_map = {
        145.0: Greeks(delta=0.70),
        150.0: Greeks(delta=0.50),
        155.0: Greeks(delta=0.30),
    }
    result = select_strike(
        strikes=[145.0, 150.0, 155.0],
        underlying_price=150.0,
        right="C",
        target_delta=0.30,
        greeks_map=greeks_map,
    )
    assert result == 155.0


def test_select_strike_fallback_no_greeks():
    result = select_strike(
        strikes=[145.0, 150.0, 155.0],
        underlying_price=150.0,
        right="C",
    )
    assert result == 150.0


def test_select_strike_fallback_delta_without_greeks():
    result = select_strike(
        strikes=[145.0, 150.0, 155.0],
        underlying_price=150.0,
        right="C",
        target_delta=0.30,
    )
    assert result == 150.0


def test_select_strike_fallback_with_offset():
    result = select_strike(
        strikes=[145.0, 150.0, 155.0],
        underlying_price=150.0,
        right="C",
        offset=1,
    )
    assert result == 155.0
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `uv run pytest packages/strategy/tests/test_strike_selector.py::test_select_strike_with_greeks -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Add to `packages/strategy/src/strategy/strike_selector.py`:

```python
def select_strike(
    strikes: list[float],
    underlying_price: float,
    right: Literal["C", "P"],
    target_delta: float | None = None,
    greeks_map: dict[float, Greeks] | None = None,
    offset: int = 0,
) -> float:
    if target_delta is not None and greeks_map is not None:
        return select_by_delta(strikes, greeks_map, target_delta, right)
    return select_atm(strikes, underlying_price, offset)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_strike_selector.py -v`
Expected: 19 PASSED (3 + 7 + 5 + 4)

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/strike_selector.py packages/strategy/tests/test_strike_selector.py
git commit -m "feat(strategy): add select_strike unified entry point"
```

---

### Task 5: Integration Test — Iron Condor Strike Selection

**Files:**
- Modify: `packages/strategy/tests/test_strike_selector.py`

- [ ] **Step 1: Write the integration test**

Add to `packages/strategy/tests/test_strike_selector.py`:

```python
def test_iron_condor_strike_selection():
    """Simulate selecting 4 strikes for an Iron Condor using delta targets."""
    strikes = [
        130.0, 135.0, 140.0, 145.0, 147.5, 150.0,
        152.5, 155.0, 160.0, 165.0, 170.0,
    ]
    underlying_price = 150.0
    call_greeks = {
        130.0: Greeks(delta=0.95),
        135.0: Greeks(delta=0.90),
        140.0: Greeks(delta=0.80),
        145.0: Greeks(delta=0.65),
        147.5: Greeks(delta=0.55),
        150.0: Greeks(delta=0.50),
        152.5: Greeks(delta=0.40),
        155.0: Greeks(delta=0.30),
        160.0: Greeks(delta=0.16),
        165.0: Greeks(delta=0.08),
        170.0: Greeks(delta=0.03),
    }
    put_greeks = {
        130.0: Greeks(delta=-0.05),
        135.0: Greeks(delta=-0.10),
        140.0: Greeks(delta=-0.20),
        145.0: Greeks(delta=-0.35),
        147.5: Greeks(delta=-0.45),
        150.0: Greeks(delta=-0.50),
        152.5: Greeks(delta=-0.60),
        155.0: Greeks(delta=-0.70),
        160.0: Greeks(delta=-0.84),
        165.0: Greeks(delta=-0.92),
        170.0: Greeks(delta=-0.97),
    }

    call_sell = select_strike(
        strikes, underlying_price, right="C",
        target_delta=0.16, greeks_map=call_greeks,
    )
    call_buy = select_strike(
        strikes, underlying_price, right="C",
        target_delta=0.05, greeks_map=call_greeks,
    )
    put_sell = select_strike(
        strikes, underlying_price, right="P",
        target_delta=0.16, greeks_map=put_greeks,
    )
    put_buy = select_strike(
        strikes, underlying_price, right="P",
        target_delta=0.05, greeks_map=put_greeks,
    )

    assert call_sell == 160.0   # 0.16 delta call
    assert call_buy == 170.0    # 0.03 closest to 0.05
    assert put_sell == 140.0    # abs(-0.20) closest to 0.16
    assert put_buy == 130.0     # abs(-0.05) = 0.05

    assert put_buy < put_sell < call_sell < call_buy
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest packages/strategy/tests/test_strike_selector.py::test_iron_condor_strike_selection -v`
Expected: PASSED (no new implementation needed — this exercises existing functions)

- [ ] **Step 3: Commit**

```bash
git add packages/strategy/tests/test_strike_selector.py
git commit -m "test(strategy): add iron condor strike selection integration test"
```

---

### Task 6: Update `__init__.py` Exports

**Files:**
- Modify: `packages/strategy/src/strategy/__init__.py`

- [ ] **Step 1: Update exports**

Replace the contents of `packages/strategy/src/strategy/__init__.py` with:

```python
from strategy.base import BaseStrategy
from strategy.greeks_calc import GreeksCalculator
from strategy.multi_leg import (
    bear_call_spread,
    bear_put_spread,
    bull_call_spread,
    bull_put_spread,
    calendar_spread,
    call_butterfly,
    cash_secured_put,
    collar,
    covered_call,
    diagonal_spread,
    iron_butterfly,
    iron_condor,
    protective_put,
    put_butterfly,
    straddle,
    strangle,
)
from strategy.strike_selector import (
    filter_strikes,
    select_atm,
    select_by_delta,
    select_strike,
)

__all__ = [
    "BaseStrategy",
    "GreeksCalculator",
    "bear_call_spread",
    "bear_put_spread",
    "bull_call_spread",
    "bull_put_spread",
    "calendar_spread",
    "call_butterfly",
    "cash_secured_put",
    "collar",
    "covered_call",
    "diagonal_spread",
    "filter_strikes",
    "iron_butterfly",
    "iron_condor",
    "protective_put",
    "put_butterfly",
    "select_atm",
    "select_by_delta",
    "select_strike",
    "straddle",
    "strangle",
]
```

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest packages/strategy/tests/ -v`
Expected: All tests PASS (39 multi_leg + 8 others + 20 strike_selector)

- [ ] **Step 3: Run linter**

Run: `uv run ruff check packages/strategy/ && uv run ruff format --check packages/strategy/`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add packages/strategy/src/strategy/__init__.py
git commit -m "feat(strategy): export strike selector functions"
```
