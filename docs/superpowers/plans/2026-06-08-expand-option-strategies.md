# Expand Option Strategies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the multi-leg options strategy factory library from 4 strategies to 15, covering all four vertical spreads, volatility strategies, protection strategies, and time-structure (calendar/diagonal) strategies.

**Architecture:** Pure factory functions in `multi_leg.py` that return `Order(legs=[...])`, following the existing pattern. Each function validates strike ordering, accepts `quantity` and `strategy_id`, and builds `Leg` objects with `Contract` instances. No new dependencies, no runtime logic, no IB calls. Calendar/diagonal spreads work because each `Leg` carries its own `Contract` with an independent `expiry` field.

**Tech Stack:** Python 3.11, dataclasses from `core.models` (Contract, Leg, Order), pytest

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `packages/strategy/src/strategy/multi_leg.py` | Add 11 new factory functions |
| Modify | `packages/strategy/src/strategy/__init__.py` | Export new functions in `__all__` |
| Modify | `packages/strategy/tests/test_multi_leg.py` | Add tests for all 11 new strategies |

---

### Task 1: Bear Put Spread

**Files:**
- Modify: `packages/strategy/tests/test_multi_leg.py`
- Modify: `packages/strategy/src/strategy/multi_leg.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/strategy/tests/test_multi_leg.py`:

```python
from strategy.multi_leg import bear_put_spread


def test_bear_put_spread():
    order = bear_put_spread(
        underlying="AAPL",
        expiry="20260620",
        buy_strike=160.0,
        sell_strike=150.0,
        quantity=1,
        strategy_id="bps_1",
    )
    assert len(order.legs) == 2
    assert order.strategy_id == "bps_1"
    # Buy higher-strike put
    assert order.legs[0].contract.strike == 160.0
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == 1
    # Sell lower-strike put
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == -1


def test_bear_put_spread_invalid_strikes():
    with pytest.raises(ValueError, match="buy_strike must be greater than sell_strike"):
        bear_put_spread(
            underlying="AAPL",
            expiry="20260620",
            buy_strike=150.0,
            sell_strike=160.0,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_bear_put_spread -v`
Expected: FAIL with `ImportError` (function not defined)

- [ ] **Step 3: Write minimal implementation**

Add to `packages/strategy/src/strategy/multi_leg.py`:

```python
def bear_put_spread(
    underlying: str,
    expiry: str,
    buy_strike: float,
    sell_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if buy_strike <= sell_strike:
        raise ValueError(
            f"buy_strike must be greater than sell_strike, got {buy_strike} <= {sell_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=buy_strike,
                right="P",
            ),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=sell_strike,
                right="P",
            ),
            quantity=-quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_bear_put_spread packages/strategy/tests/test_multi_leg.py::test_bear_put_spread_invalid_strikes -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/multi_leg.py packages/strategy/tests/test_multi_leg.py
git commit -m "feat(strategy): add bear_put_spread factory"
```

---

### Task 2: Bull Put Spread (Credit Spread)

**Files:**
- Modify: `packages/strategy/tests/test_multi_leg.py`
- Modify: `packages/strategy/src/strategy/multi_leg.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/strategy/tests/test_multi_leg.py`:

```python
from strategy.multi_leg import bull_put_spread


def test_bull_put_spread():
    order = bull_put_spread(
        underlying="AAPL",
        expiry="20260620",
        sell_strike=155.0,
        buy_strike=150.0,
        quantity=2,
        strategy_id="bps_credit_1",
    )
    assert len(order.legs) == 2
    assert order.strategy_id == "bps_credit_1"
    # Sell higher-strike put (collect premium)
    assert order.legs[0].contract.strike == 155.0
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == -2
    # Buy lower-strike put (protection)
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == 2


def test_bull_put_spread_invalid_strikes():
    with pytest.raises(ValueError, match="sell_strike must be greater than buy_strike"):
        bull_put_spread(
            underlying="AAPL",
            expiry="20260620",
            sell_strike=150.0,
            buy_strike=155.0,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_bull_put_spread -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Add to `packages/strategy/src/strategy/multi_leg.py`:

```python
def bull_put_spread(
    underlying: str,
    expiry: str,
    sell_strike: float,
    buy_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if sell_strike <= buy_strike:
        raise ValueError(
            f"sell_strike must be greater than buy_strike, got {sell_strike} <= {buy_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=sell_strike,
                right="P",
            ),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=buy_strike,
                right="P",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_bull_put_spread packages/strategy/tests/test_multi_leg.py::test_bull_put_spread_invalid_strikes -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/multi_leg.py packages/strategy/tests/test_multi_leg.py
git commit -m "feat(strategy): add bull_put_spread factory"
```

---

### Task 3: Bear Call Spread (Credit Spread)

**Files:**
- Modify: `packages/strategy/tests/test_multi_leg.py`
- Modify: `packages/strategy/src/strategy/multi_leg.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/strategy/tests/test_multi_leg.py`:

```python
from strategy.multi_leg import bear_call_spread


def test_bear_call_spread():
    order = bear_call_spread(
        underlying="AAPL",
        expiry="20260620",
        sell_strike=155.0,
        buy_strike=160.0,
        quantity=1,
        strategy_id="bcs_credit_1",
    )
    assert len(order.legs) == 2
    assert order.strategy_id == "bcs_credit_1"
    # Sell lower-strike call (collect premium)
    assert order.legs[0].contract.strike == 155.0
    assert order.legs[0].contract.right == "C"
    assert order.legs[0].quantity == -1
    # Buy higher-strike call (protection)
    assert order.legs[1].contract.strike == 160.0
    assert order.legs[1].contract.right == "C"
    assert order.legs[1].quantity == 1


def test_bear_call_spread_invalid_strikes():
    with pytest.raises(ValueError, match="sell_strike must be less than buy_strike"):
        bear_call_spread(
            underlying="AAPL",
            expiry="20260620",
            sell_strike=160.0,
            buy_strike=155.0,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_bear_call_spread -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Add to `packages/strategy/src/strategy/multi_leg.py`:

```python
def bear_call_spread(
    underlying: str,
    expiry: str,
    sell_strike: float,
    buy_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if sell_strike >= buy_strike:
        raise ValueError(
            f"sell_strike must be less than buy_strike, got {sell_strike} >= {buy_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=sell_strike,
                right="C",
            ),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=buy_strike,
                right="C",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_bear_call_spread packages/strategy/tests/test_multi_leg.py::test_bear_call_spread_invalid_strikes -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/multi_leg.py packages/strategy/tests/test_multi_leg.py
git commit -m "feat(strategy): add bear_call_spread factory"
```

---

### Task 4: Strangle

**Files:**
- Modify: `packages/strategy/tests/test_multi_leg.py`
- Modify: `packages/strategy/src/strategy/multi_leg.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/strategy/tests/test_multi_leg.py`:

```python
from strategy.multi_leg import strangle


def test_strangle():
    order = strangle(
        underlying="AAPL",
        expiry="20260620",
        put_strike=145.0,
        call_strike=155.0,
        quantity=2,
        strategy_id="strng_1",
    )
    assert len(order.legs) == 2
    assert order.strategy_id == "strng_1"
    # Put leg
    assert order.legs[0].contract.strike == 145.0
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == 2
    # Call leg
    assert order.legs[1].contract.strike == 155.0
    assert order.legs[1].contract.right == "C"
    assert order.legs[1].quantity == 2


def test_strangle_invalid_strikes():
    with pytest.raises(ValueError, match="put_strike must be less than call_strike"):
        strangle(
            underlying="AAPL",
            expiry="20260620",
            put_strike=155.0,
            call_strike=145.0,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_strangle -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Add to `packages/strategy/src/strategy/multi_leg.py`:

```python
def strangle(
    underlying: str,
    expiry: str,
    put_strike: float,
    call_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if put_strike >= call_strike:
        raise ValueError(
            f"put_strike must be less than call_strike, got {put_strike} >= {call_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=put_strike,
                right="P",
            ),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=call_strike,
                right="C",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_strangle packages/strategy/tests/test_multi_leg.py::test_strangle_invalid_strikes -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/multi_leg.py packages/strategy/tests/test_multi_leg.py
git commit -m "feat(strategy): add strangle factory"
```

---

### Task 5: Call Butterfly

**Files:**
- Modify: `packages/strategy/tests/test_multi_leg.py`
- Modify: `packages/strategy/src/strategy/multi_leg.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/strategy/tests/test_multi_leg.py`:

```python
from strategy.multi_leg import call_butterfly


def test_call_butterfly():
    order = call_butterfly(
        underlying="AAPL",
        expiry="20260620",
        lower_strike=145.0,
        middle_strike=150.0,
        upper_strike=155.0,
        quantity=1,
        strategy_id="cfly_1",
    )
    assert len(order.legs) == 3
    assert order.strategy_id == "cfly_1"
    # Buy 1 lower-strike call
    assert order.legs[0].contract.strike == 145.0
    assert order.legs[0].contract.right == "C"
    assert order.legs[0].quantity == 1
    # Sell 2 middle-strike calls
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "C"
    assert order.legs[1].quantity == -2
    # Buy 1 upper-strike call
    assert order.legs[2].contract.strike == 155.0
    assert order.legs[2].contract.right == "C"
    assert order.legs[2].quantity == 1


def test_call_butterfly_non_equidistant():
    with pytest.raises(ValueError, match="wings must be equidistant"):
        call_butterfly(
            underlying="AAPL",
            expiry="20260620",
            lower_strike=145.0,
            middle_strike=150.0,
            upper_strike=160.0,
        )


def test_call_butterfly_invalid_order():
    with pytest.raises(ValueError, match="lower < middle < upper"):
        call_butterfly(
            underlying="AAPL",
            expiry="20260620",
            lower_strike=155.0,
            middle_strike=150.0,
            upper_strike=145.0,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_call_butterfly -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Add to `packages/strategy/src/strategy/multi_leg.py`:

```python
def call_butterfly(
    underlying: str,
    expiry: str,
    lower_strike: float,
    middle_strike: float,
    upper_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if not (lower_strike < middle_strike < upper_strike):
        raise ValueError(
            f"Strikes must satisfy lower < middle < upper, "
            f"got {lower_strike}, {middle_strike}, {upper_strike}"
        )
    if abs((middle_strike - lower_strike) - (upper_strike - middle_strike)) > 1e-9:
        raise ValueError(
            f"wings must be equidistant from middle, "
            f"got {middle_strike - lower_strike} vs {upper_strike - middle_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=lower_strike,
                right="C",
            ),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=middle_strike,
                right="C",
            ),
            quantity=-2 * quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=upper_strike,
                right="C",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_call_butterfly packages/strategy/tests/test_multi_leg.py::test_call_butterfly_non_equidistant packages/strategy/tests/test_multi_leg.py::test_call_butterfly_invalid_order -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/multi_leg.py packages/strategy/tests/test_multi_leg.py
git commit -m "feat(strategy): add call_butterfly factory"
```

---

### Task 6: Put Butterfly

**Files:**
- Modify: `packages/strategy/tests/test_multi_leg.py`
- Modify: `packages/strategy/src/strategy/multi_leg.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/strategy/tests/test_multi_leg.py`:

```python
from strategy.multi_leg import put_butterfly


def test_put_butterfly():
    order = put_butterfly(
        underlying="AAPL",
        expiry="20260620",
        lower_strike=145.0,
        middle_strike=150.0,
        upper_strike=155.0,
        quantity=1,
        strategy_id="pfly_1",
    )
    assert len(order.legs) == 3
    assert order.strategy_id == "pfly_1"
    # Buy 1 lower-strike put
    assert order.legs[0].contract.strike == 145.0
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == 1
    # Sell 2 middle-strike puts
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == -2
    # Buy 1 upper-strike put
    assert order.legs[2].contract.strike == 155.0
    assert order.legs[2].contract.right == "P"
    assert order.legs[2].quantity == 1


def test_put_butterfly_non_equidistant():
    with pytest.raises(ValueError, match="wings must be equidistant"):
        put_butterfly(
            underlying="AAPL",
            expiry="20260620",
            lower_strike=140.0,
            middle_strike=150.0,
            upper_strike=155.0,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_put_butterfly -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Add to `packages/strategy/src/strategy/multi_leg.py`:

```python
def put_butterfly(
    underlying: str,
    expiry: str,
    lower_strike: float,
    middle_strike: float,
    upper_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if not (lower_strike < middle_strike < upper_strike):
        raise ValueError(
            f"Strikes must satisfy lower < middle < upper, "
            f"got {lower_strike}, {middle_strike}, {upper_strike}"
        )
    if abs((middle_strike - lower_strike) - (upper_strike - middle_strike)) > 1e-9:
        raise ValueError(
            f"wings must be equidistant from middle, "
            f"got {middle_strike - lower_strike} vs {upper_strike - middle_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=lower_strike,
                right="P",
            ),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=middle_strike,
                right="P",
            ),
            quantity=-2 * quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=upper_strike,
                right="P",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_put_butterfly packages/strategy/tests/test_multi_leg.py::test_put_butterfly_non_equidistant -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/multi_leg.py packages/strategy/tests/test_multi_leg.py
git commit -m "feat(strategy): add put_butterfly factory"
```

---

### Task 7: Iron Butterfly

**Files:**
- Modify: `packages/strategy/tests/test_multi_leg.py`
- Modify: `packages/strategy/src/strategy/multi_leg.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/strategy/tests/test_multi_leg.py`:

```python
from strategy.multi_leg import iron_butterfly


def test_iron_butterfly():
    order = iron_butterfly(
        underlying="AAPL",
        expiry="20260620",
        put_buy_strike=140.0,
        middle_strike=150.0,
        call_buy_strike=160.0,
        quantity=1,
        strategy_id="ifly_1",
    )
    assert len(order.legs) == 4
    assert order.strategy_id == "ifly_1"
    # Buy OTM put (protection)
    assert order.legs[0].contract.strike == 140.0
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == 1
    # Sell ATM put
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == -1
    # Sell ATM call
    assert order.legs[2].contract.strike == 150.0
    assert order.legs[2].contract.right == "C"
    assert order.legs[2].quantity == -1
    # Buy OTM call (protection)
    assert order.legs[3].contract.strike == 160.0
    assert order.legs[3].contract.right == "C"
    assert order.legs[3].quantity == 1


def test_iron_butterfly_invalid_strikes():
    with pytest.raises(ValueError, match="put_buy < middle < call_buy"):
        iron_butterfly(
            underlying="AAPL",
            expiry="20260620",
            put_buy_strike=160.0,
            middle_strike=150.0,
            call_buy_strike=140.0,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_iron_butterfly -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Add to `packages/strategy/src/strategy/multi_leg.py`:

```python
def iron_butterfly(
    underlying: str,
    expiry: str,
    put_buy_strike: float,
    middle_strike: float,
    call_buy_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if not (put_buy_strike < middle_strike < call_buy_strike):
        raise ValueError(
            f"Strikes must satisfy put_buy < middle < call_buy, "
            f"got {put_buy_strike}, {middle_strike}, {call_buy_strike}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=put_buy_strike,
                right="P",
            ),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=middle_strike,
                right="P",
            ),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=middle_strike,
                right="C",
            ),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=call_buy_strike,
                right="C",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_iron_butterfly packages/strategy/tests/test_multi_leg.py::test_iron_butterfly_invalid_strikes -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/multi_leg.py packages/strategy/tests/test_multi_leg.py
git commit -m "feat(strategy): add iron_butterfly factory"
```

---

### Task 8: Collar

**Files:**
- Modify: `packages/strategy/tests/test_multi_leg.py`
- Modify: `packages/strategy/src/strategy/multi_leg.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/strategy/tests/test_multi_leg.py`:

```python
from strategy.multi_leg import collar


def test_collar():
    order = collar(
        underlying="AAPL",
        expiry="20260620",
        put_strike=145.0,
        call_strike=155.0,
        quantity=1,
        strategy_id="collar_1",
    )
    assert len(order.legs) == 3
    assert order.strategy_id == "collar_1"
    # Long 100 shares
    assert order.legs[0].contract.sec_type == "STK"
    assert order.legs[0].quantity == 100
    # Buy protective put
    assert order.legs[1].contract.strike == 145.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == 1
    # Sell covered call
    assert order.legs[2].contract.strike == 155.0
    assert order.legs[2].contract.right == "C"
    assert order.legs[2].quantity == -1


def test_collar_invalid_strikes():
    with pytest.raises(ValueError, match="put_strike must be less than call_strike"):
        collar(
            underlying="AAPL",
            expiry="20260620",
            put_strike=160.0,
            call_strike=150.0,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_collar -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Add to `packages/strategy/src/strategy/multi_leg.py`:

```python
def collar(
    underlying: str,
    expiry: str,
    put_strike: float,
    call_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if put_strike >= call_strike:
        raise ValueError(
            f"put_strike must be less than call_strike, got {put_strike} >= {call_strike}"
        )
    legs = [
        Leg(
            contract=Contract(symbol=underlying, sec_type="STK"),
            quantity=100 * quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=put_strike,
                right="P",
            ),
            quantity=quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=call_strike,
                right="C",
            ),
            quantity=-quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_collar packages/strategy/tests/test_multi_leg.py::test_collar_invalid_strikes -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/multi_leg.py packages/strategy/tests/test_multi_leg.py
git commit -m "feat(strategy): add collar factory"
```

---

### Task 9: Protective Put

**Files:**
- Modify: `packages/strategy/tests/test_multi_leg.py`
- Modify: `packages/strategy/src/strategy/multi_leg.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/strategy/tests/test_multi_leg.py`:

```python
from strategy.multi_leg import protective_put


def test_protective_put():
    order = protective_put(
        underlying="AAPL",
        expiry="20260620",
        put_strike=145.0,
        quantity=2,
        strategy_id="pp_1",
    )
    assert len(order.legs) == 2
    assert order.strategy_id == "pp_1"
    # Long shares
    assert order.legs[0].contract.sec_type == "STK"
    assert order.legs[0].quantity == 200  # 100 * 2
    # Long put
    assert order.legs[1].contract.strike == 145.0
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_protective_put -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Add to `packages/strategy/src/strategy/multi_leg.py`:

```python
def protective_put(
    underlying: str,
    expiry: str,
    put_strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    legs = [
        Leg(
            contract=Contract(symbol=underlying, sec_type="STK"),
            quantity=100 * quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=put_strike,
                right="P",
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_protective_put -v`
Expected: PASSED

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/multi_leg.py packages/strategy/tests/test_multi_leg.py
git commit -m "feat(strategy): add protective_put factory"
```

---

### Task 10: Cash-Secured Put

**Files:**
- Modify: `packages/strategy/tests/test_multi_leg.py`
- Modify: `packages/strategy/src/strategy/multi_leg.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/strategy/tests/test_multi_leg.py`:

```python
from strategy.multi_leg import cash_secured_put


def test_cash_secured_put():
    order = cash_secured_put(
        underlying="AAPL",
        expiry="20260620",
        strike=145.0,
        quantity=3,
        strategy_id="csp_1",
    )
    assert len(order.legs) == 1
    assert order.strategy_id == "csp_1"
    # Short put
    assert order.legs[0].contract.strike == 145.0
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == -3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_cash_secured_put -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Add to `packages/strategy/src/strategy/multi_leg.py`:

```python
def cash_secured_put(
    underlying: str,
    expiry: str,
    strike: float,
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=expiry,
                strike=strike,
                right="P",
            ),
            quantity=-quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_cash_secured_put -v`
Expected: PASSED

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/multi_leg.py packages/strategy/tests/test_multi_leg.py
git commit -m "feat(strategy): add cash_secured_put factory"
```

---

### Task 11: Calendar Spread

Each `Leg` carries its own `Contract` with an independent `expiry` field, so multi-expiration strategies work without model changes.

**Files:**
- Modify: `packages/strategy/tests/test_multi_leg.py`
- Modify: `packages/strategy/src/strategy/multi_leg.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/strategy/tests/test_multi_leg.py`:

```python
from strategy.multi_leg import calendar_spread


def test_calendar_spread_calls():
    order = calendar_spread(
        underlying="AAPL",
        strike=150.0,
        near_expiry="20260620",
        far_expiry="20260718",
        right="C",
        quantity=1,
        strategy_id="cal_1",
    )
    assert len(order.legs) == 2
    assert order.strategy_id == "cal_1"
    # Sell near-term option
    assert order.legs[0].contract.expiry == "20260620"
    assert order.legs[0].contract.strike == 150.0
    assert order.legs[0].contract.right == "C"
    assert order.legs[0].quantity == -1
    # Buy far-term option
    assert order.legs[1].contract.expiry == "20260718"
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "C"
    assert order.legs[1].quantity == 1


def test_calendar_spread_puts():
    order = calendar_spread(
        underlying="AAPL",
        strike=150.0,
        near_expiry="20260620",
        far_expiry="20260718",
        right="P",
        quantity=2,
        strategy_id="cal_2",
    )
    assert len(order.legs) == 2
    assert order.legs[0].contract.right == "P"
    assert order.legs[0].quantity == -2
    assert order.legs[1].contract.right == "P"
    assert order.legs[1].quantity == 2


def test_calendar_spread_same_expiry():
    with pytest.raises(ValueError, match="near_expiry must differ from far_expiry"):
        calendar_spread(
            underlying="AAPL",
            strike=150.0,
            near_expiry="20260620",
            far_expiry="20260620",
            right="C",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_calendar_spread_calls -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Add to `packages/strategy/src/strategy/multi_leg.py`:

```python
def calendar_spread(
    underlying: str,
    strike: float,
    near_expiry: str,
    far_expiry: str,
    right: Literal["C", "P"] = "C",
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if near_expiry == far_expiry:
        raise ValueError(
            f"near_expiry must differ from far_expiry, both are {near_expiry}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=near_expiry,
                strike=strike,
                right=right,
            ),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=far_expiry,
                strike=strike,
                right=right,
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)
```

Note: Add `from typing import Literal` to the imports at the top of `multi_leg.py` (it is not currently imported there; only `Contract`, `Leg`, `Order` are imported from `core.models`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_calendar_spread_calls packages/strategy/tests/test_multi_leg.py::test_calendar_spread_puts packages/strategy/tests/test_multi_leg.py::test_calendar_spread_same_expiry -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/multi_leg.py packages/strategy/tests/test_multi_leg.py
git commit -m "feat(strategy): add calendar_spread factory"
```

---

### Task 12: Diagonal Spread

**Files:**
- Modify: `packages/strategy/tests/test_multi_leg.py`
- Modify: `packages/strategy/src/strategy/multi_leg.py`

- [ ] **Step 1: Write the failing test**

Add to `packages/strategy/tests/test_multi_leg.py`:

```python
from strategy.multi_leg import diagonal_spread


def test_diagonal_spread():
    order = diagonal_spread(
        underlying="AAPL",
        near_expiry="20260620",
        near_strike=155.0,
        far_expiry="20260718",
        far_strike=150.0,
        right="C",
        quantity=1,
        strategy_id="diag_1",
    )
    assert len(order.legs) == 2
    assert order.strategy_id == "diag_1"
    # Sell near-term, near-strike
    assert order.legs[0].contract.expiry == "20260620"
    assert order.legs[0].contract.strike == 155.0
    assert order.legs[0].contract.right == "C"
    assert order.legs[0].quantity == -1
    # Buy far-term, far-strike
    assert order.legs[1].contract.expiry == "20260718"
    assert order.legs[1].contract.strike == 150.0
    assert order.legs[1].contract.right == "C"
    assert order.legs[1].quantity == 1


def test_diagonal_spread_same_expiry():
    with pytest.raises(ValueError, match="near_expiry must differ from far_expiry"):
        diagonal_spread(
            underlying="AAPL",
            near_expiry="20260620",
            near_strike=155.0,
            far_expiry="20260620",
            far_strike=150.0,
            right="C",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_diagonal_spread -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Add to `packages/strategy/src/strategy/multi_leg.py`:

```python
def diagonal_spread(
    underlying: str,
    near_expiry: str,
    near_strike: float,
    far_expiry: str,
    far_strike: float,
    right: Literal["C", "P"] = "C",
    quantity: int = 1,
    strategy_id: str = "",
) -> Order:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if near_expiry == far_expiry:
        raise ValueError(
            f"near_expiry must differ from far_expiry, both are {near_expiry}"
        )
    legs = [
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=near_expiry,
                strike=near_strike,
                right=right,
            ),
            quantity=-quantity,
        ),
        Leg(
            contract=Contract(
                symbol=underlying,
                sec_type="OPT",
                expiry=far_expiry,
                strike=far_strike,
                right=right,
            ),
            quantity=quantity,
        ),
    ]
    return Order(legs=legs, strategy_id=strategy_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/strategy/tests/test_multi_leg.py::test_diagonal_spread packages/strategy/tests/test_multi_leg.py::test_diagonal_spread_same_expiry -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add packages/strategy/src/strategy/multi_leg.py packages/strategy/tests/test_multi_leg.py
git commit -m "feat(strategy): add diagonal_spread factory"
```

---

### Task 13: Update `__init__.py` Exports

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
    call_butterfly,
    calendar_spread,
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

__all__ = [
    "BaseStrategy",
    "GreeksCalculator",
    "bear_call_spread",
    "bear_put_spread",
    "bull_call_spread",
    "bull_put_spread",
    "call_butterfly",
    "calendar_spread",
    "cash_secured_put",
    "collar",
    "covered_call",
    "diagonal_spread",
    "iron_butterfly",
    "iron_condor",
    "protective_put",
    "put_butterfly",
    "straddle",
    "strangle",
]
```

- [ ] **Step 2: Run full test suite to verify nothing is broken**

Run: `uv run pytest packages/strategy/tests/ -v`
Expected: All tests PASS (existing 4 strategy tests + all 11 new strategy tests)

- [ ] **Step 3: Run linter**

Run: `uv run ruff check packages/strategy/ && uv run ruff format --check packages/strategy/`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add packages/strategy/src/strategy/__init__.py
git commit -m "feat(strategy): export all 15 multi-leg strategy factories"
```

---

## Deferred — Needs Design / Brainstorming First

The following enhancements from the deep research are high-value but require new subsystems or runtime logic that can't be expressed as pure factory functions. Each should get its own brainstorming + plan cycle:

1. **IV Rank / IV Percentile entry logic** — Requires a 52-week IV history data source (storage/market-data pipeline work). Drives strategy selection (when to sell premium vs buy premium).

2. **Greeks-based position management** — Runtime `BaseStrategy` logic for delta-neutral hedging with gamma-aware rebalancing. Needs live Greeks wiring and rebalance trigger design.

3. **Dynamic strike selection via `reqSecDefOptParams`** — tws-client/market-data integration to discover option chains at runtime and select strikes algorithmically (e.g., delta-based strike selection for iron condors).

4. **Rolling / adjustment / early-assignment handling** — Runtime execution logic: when to roll a tested wing, how to detect and handle partial assignment creating naked exposure.
