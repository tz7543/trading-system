# Swing Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `scan` CLI subcommand per `docs/superpowers/specs/2026-06-12-swing-scanner-design.md` — a deterministic swing-trade scanner producing verdict / entry / stop / T1 / RR / sizing / exit plan per symbol.

**Architecture:** Pure indicator functions + rule engine in a new `strategy.swing` subpackage (depends only on `core`); data injected via the existing `DataHandler.fetch_history`; app-layer wiring (`run_scan`) plus report rendering in `apps/trader`.

**Tech Stack:** Python 3.11, stdlib only (dataclasses, math, tomllib), pydantic (app config), pytest + pytest-asyncio (asyncio_mode=auto). No new dependencies.

**Conventions for every task:**
- Run tests from the repo root: `uv run pytest <path> -v`.
- `.py` files are auto-formatted by hooks on Write/Edit — do not hand-format.
- Commit with `rtk git add <files> && rtk git commit -m "<msg>"`.
- The spec is the authority for every constant and boundary; if code and spec disagree, the spec wins.

**File map (final state):**
- Create `packages/strategy/src/strategy/swing/__init__.py` — re-exports.
- Create `packages/strategy/src/strategy/swing/indicators.py` — pure indicator functions.
- Create `packages/strategy/src/strategy/swing/scanner.py` — `ScanParams`, `ScanResult`, helpers, `evaluate()`.
- Create `packages/strategy/tests/test_swing_indicators.py`.
- Create `packages/strategy/tests/test_swing_scanner.py`.
- Modify `apps/trader/src/trading_app/config.py` — `ScannerConfig`, `TraderConfig.scanner`.
- Create `apps/trader/src/trading_app/scan_report.py` — table + JSON rendering.
- Modify `apps/trader/src/trading_app/assembly.py` — `run_scan()`.
- Modify `apps/trader/src/trading_app/cli.py` — `scan` subcommand.
- Modify `apps/trader/config.toml` — commented `[scanner]` example.
- Create `apps/trader/tests/test_scan.py`.

---

### Task 1: swing package scaffold + `sma` / `ema`

**Files:**
- Create: `packages/strategy/src/strategy/swing/__init__.py`
- Create: `packages/strategy/src/strategy/swing/indicators.py`
- Test: `packages/strategy/tests/test_swing_indicators.py`

- [ ] **Step 1: Write the failing tests**

```python
# packages/strategy/tests/test_swing_indicators.py
from strategy.swing.indicators import ema, sma


def test_sma_pads_warmup_with_none():
    assert sma([1.0, 2.0, 3.0, 4.0, 5.0], 3) == [None, None, 2.0, 3.0, 4.0]


def test_sma_period_longer_than_series():
    assert sma([1.0, 2.0], 5) == [None, None]


def test_ema_seeds_with_sma_then_recurses():
    # period 3 → alpha = 0.5; seed at index 2 = mean(1,2,3) = 2
    # idx3 = 0.5*4 + 0.5*2 = 3; idx4 = 0.5*5 + 0.5*3 = 4
    assert ema([1.0, 2.0, 3.0, 4.0, 5.0], 3) == [None, None, 2.0, 3.0, 4.0]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/strategy/tests/test_swing_indicators.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'strategy.swing'`

- [ ] **Step 3: Implement**

```python
# packages/strategy/src/strategy/swing/__init__.py
"""Swing-trading scanner: pure indicators and rule engine."""
```

```python
# packages/strategy/src/strategy/swing/indicators.py
"""Pure indicator functions for the swing scanner.

Every series function returns a list aligned to its input, with None during
warmup, so callers can inspect t and t-1 by index. No third-party deps.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import ceil

from core.models import Bar


def sma(values: Sequence[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[float | None] = [None] * len(values)
    total = 0.0
    for i, value in enumerate(values):
        total += value
        if i >= period:
            total -= values[i - period]
        if i >= period - 1:
            out[i] = total / period
    return out


def ema(values: Sequence[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    alpha = 2.0 / (period + 1)
    for i in range(period, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out
```

(`Bar` and `ceil` are imported now because later tasks in this same file use
them; the hook's `ruff check --fix` would drop unused imports, so if it does,
re-add them in the task that needs them.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest packages/strategy/tests/test_swing_indicators.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
rtk git add packages/strategy/src/strategy/swing packages/strategy/tests/test_swing_indicators.py
rtk git commit -m "feat(strategy): scaffold swing package with sma/ema"
```

---

### Task 2: `true_range` / Wilder smoothing / `atr`

**Files:**
- Modify: `packages/strategy/src/strategy/swing/indicators.py`
- Test: `packages/strategy/tests/test_swing_indicators.py`

- [ ] **Step 1: Write the failing tests** (append to the test file)

```python
from datetime import date

import pytest

from core.models import Bar
from strategy.swing.indicators import atr, true_range


def make_bar(i, o, h, lo, c, v=1000):
    return Bar(
        timestamp=date(2026, 1, 1 + i), symbol="T",
        open=o, high=h, low=lo, close=c, volume=v,
    )


def test_true_range_uses_prev_close():
    bars = [
        make_bar(0, 10, 11, 9, 10),     # TR0 = high-low = 2
        make_bar(1, 10, 12, 10, 11),    # max(2, |12-10|, |10-10|) = 2
        make_bar(2, 11, 11, 8, 9),      # max(3, |11-11|, |8-11|) = 3
    ]
    assert true_range(bars) == [2.0, 2.0, 3.0]


def test_atr_wilder_recurrence():
    # TRs = [2, 2, 3, 1, 5] (5th bar: high 14 low 9 prev_close 9 → max(5,5,0)=5)
    bars = [
        make_bar(0, 10, 11, 9, 10),
        make_bar(1, 10, 12, 10, 11),
        make_bar(2, 11, 11, 8, 9),
        make_bar(3, 9, 10, 9, 9),
        make_bar(4, 9, 14, 9, 13),
    ]
    result = atr(bars, 3)
    # seed at idx2 = mean(2,2,3) = 7/3
    # idx3 = (7/3 * 2 + 1) / 3 = 17/9
    # idx4 = (17/9 * 2 + 5) / 3 = 79/27
    assert result[:2] == [None, None]
    assert result[2] == pytest.approx(7 / 3)
    assert result[3] == pytest.approx(17 / 9)
    assert result[4] == pytest.approx(79 / 27)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/strategy/tests/test_swing_indicators.py -v`
Expected: FAIL — `ImportError: cannot import name 'atr'`

- [ ] **Step 3: Implement** (append to indicators.py)

```python
def true_range(bars: Sequence[Bar]) -> list[float]:
    out: list[float] = []
    for i, bar in enumerate(bars):
        if i == 0:
            out.append(bar.high - bar.low)
            continue
        prev_close = bars[i - 1].close
        out.append(
            max(
                bar.high - bar.low,
                abs(bar.high - prev_close),
                abs(bar.low - prev_close),
            )
        )
    return out


def wilder_smooth(values: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = (prev * (period - 1) + values[i]) / period
        out[i] = prev
    return out


def atr(bars: Sequence[Bar], period: int) -> list[float | None]:
    return wilder_smooth(true_range(bars), period)
```

- [ ] **Step 4: Run to verify pass** — same command, expected: all passed.

- [ ] **Step 5: Commit**

```bash
rtk git add packages/strategy/src/strategy/swing/indicators.py packages/strategy/tests/test_swing_indicators.py
rtk git commit -m "feat(strategy): add true_range, wilder_smooth, atr"
```

---

### Task 3: `adx` (Wilder)

**Files:** same as Task 2.

- [ ] **Step 1: Write the failing tests** (append)

```python
from strategy.swing.indicators import adx


def _trend_bars(n, step):
    # Strict monotonic trend with constant 1-point bar range:
    # uptrend (+step): +DM = step, -DM = 0 every bar → DX = 100 → ADX = 100.
    bars = []
    base = 100.0
    for i in range(n):
        lo = base + i * step
        bars.append(make_bar(i % 27, lo, lo + 1, lo, lo + 0.5))
    return bars


def test_adx_is_100_in_pure_uptrend():
    result = adx(_trend_bars(12, 1.0), period=3)
    # first ADX at index 2*period-2 = 4
    assert result[:4] == [None] * 4
    for value in result[4:]:
        assert value == pytest.approx(100.0)


def test_adx_is_100_in_pure_downtrend():
    result = adx(_trend_bars(12, -1.0), period=3)
    for value in result[4:]:
        assert value == pytest.approx(100.0)


def test_adx_too_short_series_all_none():
    assert adx(_trend_bars(4, 1.0), period=3) == [None] * 4
```

- [ ] **Step 2: Run to verify failure** — `ImportError: cannot import name 'adx'`.

- [ ] **Step 3: Implement** (append to indicators.py)

```python
def adx(bars: Sequence[Bar], period: int = 14) -> list[float | None]:
    n = len(bars)
    out: list[float | None] = [None] * n
    if n < 2 * period:
        return out
    plus_dm = [0.0]
    minus_dm = [0.0]
    for i in range(1, n):
        up = bars[i].high - bars[i - 1].high
        down = bars[i - 1].low - bars[i].low
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    sm_tr = wilder_smooth(true_range(bars), period)
    sm_plus = wilder_smooth(plus_dm, period)
    sm_minus = wilder_smooth(minus_dm, period)
    dx: list[float | None] = [None] * n
    for i in range(period - 1, n):
        tr_i, plus_i, minus_i = sm_tr[i], sm_plus[i], sm_minus[i]
        if tr_i is None or plus_i is None or minus_i is None or tr_i == 0:
            continue
        plus_di = 100.0 * plus_i / tr_i
        minus_di = 100.0 * minus_i / tr_i
        denom = plus_di + minus_di
        dx[i] = 0.0 if denom == 0 else 100.0 * abs(plus_di - minus_di) / denom
    first = 2 * period - 2  # first index with `period` DX values
    window = dx[period - 1 : first + 1]
    if any(value is None for value in window):
        return out
    prev = sum(window) / period
    out[first] = prev
    for i in range(first + 1, n):
        value = dx[i]
        if value is None:
            # flat segment (TR=0); hold — the scanner SKIPs such series anyway
            out[i] = prev
            continue
        prev = (prev * (period - 1) + value) / period
        out[i] = prev
    return out
```

- [ ] **Step 4: Run to verify pass.**

- [ ] **Step 5: Commit** — `rtk git commit -m "feat(strategy): add Wilder ADX"` (after `rtk git add` of both files).

---

### Task 4: `bollinger` + `nearest_rank_percentile` + `in_squeeze`

**Files:** same as Task 2.

- [ ] **Step 1: Write the failing tests** (append)

```python
from strategy.swing.indicators import bollinger, in_squeeze, nearest_rank_percentile


def test_bollinger_constant_series_zero_width():
    middle, upper, lower, width = bollinger([5.0] * 7, period=5, num_std=2.0)
    assert middle[4] == upper[4] == lower[4] == 5.0
    assert width[4] == 0.0
    assert middle[:4] == [None] * 4


def test_bollinger_known_window():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    middle, upper, lower, width = bollinger(closes, period=5, num_std=2.0)
    # mean 3, population var = (4+1+0+1+4)/5 = 2, std = sqrt(2)
    std = 2 ** 0.5
    assert middle[4] == pytest.approx(3.0)
    assert upper[4] == pytest.approx(3 + 2 * std)
    assert lower[4] == pytest.approx(3 - 2 * std)
    assert width[4] == pytest.approx(4 * std / 3)  # (upper-lower)/middle


def test_nearest_rank_percentile():
    window = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]
    # N=10, rank = ceil(0.2*10) = 2 → 2nd smallest = 2.0
    assert nearest_rank_percentile(window, 20.0) == 2.0


def test_in_squeeze_inclusive_tie_and_window():
    width = [None, 5.0, 4.0, 3.0, 2.0, 1.0]
    # window=5 ending idx5: values [5,4,3,2,1], p20 = 1.0; width[5]=1.0 ≤ 1.0 → True
    assert in_squeeze(width, 5, window=5, pct=20.0) is True
    # window not fully populated (includes the None) → None
    assert in_squeeze(width, 4, window=5, pct=20.0) is None
```

- [ ] **Step 2: Run to verify failure** — ImportError.

- [ ] **Step 3: Implement** (append to indicators.py)

```python
def bollinger(
    closes: Sequence[float], period: int = 20, num_std: float = 2.0
) -> tuple[
    list[float | None], list[float | None], list[float | None], list[float | None]
]:
    middle = sma(closes, period)
    n = len(closes)
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    width: list[float | None] = [None] * n
    for i in range(period - 1, n):
        mid = middle[i]
        window = closes[i - period + 1 : i + 1]
        variance = sum((c - mid) ** 2 for c in window) / period  # population σ
        std = variance**0.5
        upper[i] = mid + num_std * std
        lower[i] = mid - num_std * std
        if mid > 0:
            width[i] = (upper[i] - lower[i]) / mid
    return middle, upper, lower, width


def nearest_rank_percentile(window: Sequence[float], pct: float) -> float:
    ordered = sorted(window)
    rank = max(1, ceil(pct / 100.0 * len(ordered)))
    return ordered[rank - 1]


def in_squeeze(
    width: Sequence[float | None], idx: int, window: int, pct: float
) -> bool | None:
    """width(idx) ≤ pct-percentile of the `window` widths ending at idx.

    Returns None when the window is not fully populated.
    """
    if idx + 1 < window:
        return None
    values = width[idx - window + 1 : idx + 1]
    if any(value is None for value in values):
        return None
    return values[-1] <= nearest_rank_percentile(values, pct)
```

- [ ] **Step 4: Run to verify pass.**

- [ ] **Step 5: Commit** — `"feat(strategy): add bollinger width, percentile, squeeze"`.

---

### Task 5: `macd`

**Files:** same as Task 2.

- [ ] **Step 1: Write the failing tests** (append)

```python
from strategy.swing.indicators import macd


def test_macd_alignment_and_constant_series():
    closes = [10.0] * 40
    dif, dea, hist = macd(closes, fast=12, slow=26, signal=9)
    assert len(dif) == len(dea) == len(hist) == 40
    assert dif[24] is None                 # before slow EMA exists
    assert dif[25] == pytest.approx(0.0)   # first DIF at index slow-1
    assert dea[32] is None                 # signal EMA needs 9 DIF values
    assert dea[33] == pytest.approx(0.0)   # 25 + 9 - 1
    assert hist[33] == pytest.approx(0.0)
    assert hist[32] is None


def test_macd_rising_series_positive_dif():
    closes = [float(i) for i in range(1, 61)]
    dif, dea, hist = macd(closes)
    assert dif[-1] > 0
    assert dea[-1] > 0
```

- [ ] **Step 2: Run to verify failure** — ImportError.

- [ ] **Step 3: Implement** (append to indicators.py)

```python
def macd(
    closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    n = len(closes)
    dif: list[float | None] = [None] * n
    for i in range(n):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            dif[i] = ema_fast[i] - ema_slow[i]
    first_dif = slow - 1
    dea: list[float | None] = [None] * n
    if n > first_dif:
        dea_tail = ema([v for v in dif[first_dif:] if v is not None], signal)
        for offset, value in enumerate(dea_tail):
            dea[first_dif + offset] = value
    hist: list[float | None] = [
        None if dif[i] is None or dea[i] is None else dif[i] - dea[i]
        for i in range(n)
    ]
    return dif, dea, hist
```

- [ ] **Step 4: Run to verify pass.**

- [ ] **Step 5: Commit** — `"feat(strategy): add MACD series"`.

---

### Task 6: `resample_weekly` + `pivot_highs`

**Files:** same as Task 2.

- [ ] **Step 1: Write the failing tests** (append)

```python
from datetime import datetime

from strategy.swing.indicators import pivot_highs, resample_weekly


def test_resample_weekly_groups_iso_weeks_and_accepts_date_or_datetime():
    # 2026-01-05 is a Monday (ISO week 2); 2026-01-12 the next Monday (week 3)
    bars = [
        Bar(date(2026, 1, 5), "T", 10, 12, 9, 11, 100),
        Bar(datetime(2026, 1, 7), "T", 11, 15, 10, 14, 200),   # datetime mixed in
        Bar(date(2026, 1, 9), "T", 14, 14, 8, 9, 300),
        Bar(date(2026, 1, 12), "T", 9, 10, 9, 10, 400),
    ]
    weekly = resample_weekly(bars)
    assert len(weekly) == 2
    first = weekly[0]
    assert (first.open, first.high, first.low, first.close) == (10, 15, 8, 9)
    assert first.volume == 600
    assert first.timestamp == date(2026, 1, 5)
    assert weekly[1].close == 10


def test_pivot_highs_strict_flanks():
    #            0  1  2  3  4  5  6
    highs = [1.0, 2.0, 5.0, 2.0, 1.0, 5.0, 5.0]
    # idx2: 5 > 1,2 (left) and > 2,1 (right) → pivot
    # idx5 would need > idx6 (5 > 5 is false) → not a pivot (strict)
    assert pivot_highs(highs, flank=2) == [2]


def test_pivot_highs_flat_top_disqualified():
    assert pivot_highs([1.0, 5.0, 5.0, 5.0, 1.0], flank=2) == []
```

- [ ] **Step 2: Run to verify failure** — ImportError.

- [ ] **Step 3: Implement** (append to indicators.py)

```python
def resample_weekly(bars: Sequence[Bar]) -> list[Bar]:
    """Group daily bars by ISO week. Accepts date or datetime timestamps.

    The in-progress week is included as the latest weekly bar (spec rule).
    """
    weekly: list[Bar] = []
    current_key: tuple[int, int] | None = None
    for bar in bars:
        iso = bar.timestamp.isocalendar()  # valid on date AND datetime
        key = (iso[0], iso[1])
        if key != current_key:
            weekly.append(
                Bar(
                    timestamp=bar.timestamp,
                    symbol=bar.symbol,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                )
            )
            current_key = key
            continue
        last = weekly[-1]
        weekly[-1] = Bar(
            timestamp=last.timestamp,
            symbol=last.symbol,
            open=last.open,
            high=max(last.high, bar.high),
            low=min(last.low, bar.low),
            close=bar.close,
            volume=last.volume + bar.volume,
        )
    return weekly


def pivot_highs(highs: Sequence[float], flank: int = 2) -> list[int]:
    """Indices whose high is strictly greater than `flank` bars on each side."""
    out: list[int] = []
    for i in range(flank, len(highs) - flank):
        center = highs[i]
        left_ok = all(center > highs[i - j] for j in range(1, flank + 1))
        right_ok = all(center > highs[i + j] for j in range(1, flank + 1))
        if left_ok and right_ok:
            out.append(i)
    return out
```

- [ ] **Step 4: Run to verify pass.**

- [ ] **Step 5: Commit** — `"feat(strategy): add weekly resample and pivot highs"`.

---

### Task 7: scanner dataclasses + SKIP paths

**Files:**
- Create: `packages/strategy/src/strategy/swing/scanner.py`
- Test: `packages/strategy/tests/test_swing_scanner.py`

- [ ] **Step 1: Write the failing tests**

```python
# packages/strategy/tests/test_swing_scanner.py
import math
from datetime import date, timedelta

from core.models import Bar
from strategy.swing.scanner import ScanParams, evaluate

START = date(2026, 1, 2)


def flat_bars(n, price=100.0, volume=1000):
    return [
        Bar(START + timedelta(days=i), "T", price, price, price, price, volume)
        for i in range(n)
    ]


def test_insufficient_bars_skip():
    result = evaluate("T", flat_bars(10), equity=100_000, risk_pct=0.015)
    assert result.verdict == "SKIP"
    assert any("資料不足" in r for r in result.reasons)
    assert result.entry is None and result.shares is None


def test_invalid_bar_data_skip():
    bars = flat_bars(400)
    bars[5] = Bar(START + timedelta(days=5), "T", 100, 99, 100, 100, 1000)  # high < low
    result = evaluate("T", bars, equity=100_000, risk_pct=0.015)
    assert result.verdict == "SKIP"
    assert "invalid bar data" in result.reasons


def test_zero_volume_bar_is_skip_not_gate_false():
    bars = flat_bars(400)
    bars[100] = Bar(START + timedelta(days=100), "T", 100, 100, 100, 100, 0)
    result = evaluate("T", bars, equity=100_000, risk_pct=0.015)
    assert result.verdict == "SKIP"
    assert "invalid bar data" in result.reasons


def test_nonfinite_close_skip():
    bars = flat_bars(400)
    bars[7] = Bar(START + timedelta(days=7), "T", 100, 101, 99, math.nan, 1000)
    result = evaluate("T", bars, equity=100_000, risk_pct=0.015)
    assert result.verdict == "SKIP"


def test_degenerate_flat_series_skip():
    # every bar identical → ATR(5/14/20) = 0 → degenerate
    result = evaluate("T", flat_bars(400), equity=100_000, risk_pct=0.015)
    assert result.verdict == "SKIP"
    assert "degenerate price series" in result.reasons


def test_params_defaults_match_spec():
    p = ScanParams()
    assert (p.adx_min, p.sma_long, p.weekly_sma) == (20.0, 200, 10)
    assert (p.bb_pct_window, p.squeeze_pct, p.squeeze_lookback) == (120, 20.0, 10)
    assert (p.min_rr, p.min_bars, p.atr_ratio_max) == (2.5, 340, 1.5)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest packages/strategy/tests/test_swing_scanner.py -v`
Expected: FAIL — no module `strategy.swing.scanner`

- [ ] **Step 3: Implement**

```python
# packages/strategy/src/strategy/swing/scanner.py
"""Swing scanner rule engine. Pure: list[Bar] in, ScanResult out. No I/O.

Spec: docs/superpowers/specs/2026-06-12-swing-scanner-design.md — the spec is
authoritative for every constant and boundary in this module.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from core.models import Bar

from strategy.swing.indicators import atr

# NOTE: Tasks 8-9 extend this import to add adx, bollinger, in_squeeze, macd,
# nearest_rank_percentile, pivot_highs, resample_weekly, sma. Do NOT import
# them earlier — the auto-format hook strips unused imports (F401).

MANUAL_CHECKLIST = [
    "距財報 ≥ 3 天（無財報日曆資料，自行確認）",
    "與既有持倉相關性 < 0.7（無組合資料，自行確認)",
    "重大事件日（FOMC/CPI）自行確認",
]
TIME_STOP_TEXT = "≤5日浮盈<0.5R減半；≤15日未達T1全出"


@dataclass(frozen=True)
class ScanParams:
    adx_min: float = 20.0
    adx_trend: float = 25.0
    sma_long: int = 200
    weekly_sma: int = 10
    bb_period: int = 20
    bb_std: float = 2.0
    bb_pct_window: int = 120
    squeeze_pct: float = 20.0
    squeeze_lookback: int = 10
    vol_sma: int = 20
    atr_fast: int = 5
    atr_period: int = 14
    atr_slow: int = 20
    atr_ratio_max: float = 1.5
    struct_window: int = 20
    struct_buffer_atr: float = 0.1
    pivot_window: int = 120
    pivot_flank: int = 2
    min_rr: float = 2.5
    min_bars: int = 340


@dataclass
class ScanResult:
    symbol: str
    verdict: str  # "CANDIDATE" | "WATCH" | "REJECT" | "SKIP"
    reasons: list[str] = field(default_factory=list)
    entry: float | None = None
    stop: float | None = None
    stop_basis: str | None = None  # "atr" | "structure" | "ma" | "floor"
    t1: float | None = None
    t1_fallback: bool = False
    rr: float | None = None
    shares: int | None = None
    multipliers: dict | None = None
    exit_plan: dict | None = None
    manual_checklist: list[str] = field(default_factory=list)
    indicator_snapshot: dict | None = None


def _invalid_bar(bar: Bar) -> bool:
    prices = (bar.open, bar.high, bar.low, bar.close)
    if any(not math.isfinite(p) or p <= 0 for p in prices):
        return True
    if bar.high < bar.low:
        return True
    return not math.isfinite(bar.volume) or bar.volume <= 0


def evaluate(
    symbol: str,
    bars: Sequence[Bar],
    params: ScanParams | None = None,
    *,
    equity: float,
    risk_pct: float,
    vix: float | None = None,
) -> ScanResult:
    # default kept out of the signature: ruff bugbear B008 flags call defaults
    if params is None:
        params = ScanParams()
    if len(bars) < params.min_bars:
        return ScanResult(
            symbol=symbol,
            verdict="SKIP",
            reasons=[f"資料不足: {len(bars)} < {params.min_bars}"],
        )
    if any(_invalid_bar(bar) for bar in bars):
        return ScanResult(symbol=symbol, verdict="SKIP", reasons=["invalid bar data"])

    atr_fast = atr(bars, params.atr_fast)
    atr_mid = atr(bars, params.atr_period)
    atr_slow = atr(bars, params.atr_slow)
    if not atr_fast[-1] or not atr_mid[-1] or not atr_slow[-1]:
        return ScanResult(
            symbol=symbol, verdict="SKIP", reasons=["degenerate price series"]
        )

    # Tasks 8-9 extend from here.
    return ScanResult(symbol=symbol, verdict="REJECT", reasons=["not implemented"])
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest packages/strategy/tests/test_swing_scanner.py -v`
Expected: all pass (the `not implemented` branch is unreachable by these tests).

- [ ] **Step 5: Commit** — `"feat(strategy): scanner dataclasses and SKIP guards"`.

---

### Task 8: regime gates + four confirmations

**Files:** same as Task 7.

Test fixtures need a builder producing bars that pass everything, with knobs
to break individual conditions.

- [ ] **Step 1: Add the fixture builder and failing tests** (append to test file)

```python
def build_bars(
    n=360,
    ramp_days=349,
    ramp_step=0.25,
    quiet_step=0.05,
    quiet_range=0.2,
    breakout_pct=0.05,
    breakout_volume_mult=3.0,
    base=100.0,
    volume=1_000_000,
):
    """Uptrend ramp → short quiet drift (squeeze) → breakout on the last bar.

    Designed to satisfy: ADX>20 (monotonic +DM), close>SMA200, weekly up,
    squeeze in last 10 sessions, middle-band breakout with width expansion,
    volume > 20d avg, MACD hist expanding.
    """
    bars = []
    price = base
    for i in range(n):
        if i < ramp_days:
            price += ramp_step
            high, low = price + 0.5, price - 0.5
            vol = volume
        elif i < n - 1:
            price += quiet_step
            high, low = price + quiet_range / 2, price - quiet_range / 2
            vol = int(volume * 0.6)
        else:
            price *= 1 + breakout_pct
            high, low = price + 1.0, price - 1.0
            vol = int(volume * breakout_volume_mult)
        bars.append(
            Bar(START + timedelta(days=i), "T", price - 0.1, high, low, price, vol)
        )
    return bars


def test_full_setup_is_candidate():
    result = evaluate("T", build_bars(), equity=100_000, risk_pct=0.015)
    assert result.verdict == "CANDIDATE", result.reasons


def test_below_sma200_rejects():
    # invert the ramp so price ends far below its long average
    bars = build_bars(ramp_step=-0.25, base=300.0)
    result = evaluate("T", bars, equity=100_000, risk_pct=0.015)
    assert result.verdict == "REJECT"
    assert any("200SMA" in r for r in result.reasons)


def test_no_breakout_with_squeeze_is_watch():
    # last bar stays inside the quiet drift → squeeze present, no trigger
    bars = build_bars(breakout_pct=0.0, breakout_volume_mult=0.6)
    result = evaluate("T", bars, equity=100_000, risk_pct=0.015)
    assert result.verdict == "WATCH"
    assert any("蓄勢" in r for r in result.reasons)


def test_breakout_without_volume_rejects():
    bars = build_bars(breakout_volume_mult=0.5)
    result = evaluate("T", bars, equity=100_000, risk_pct=0.015)
    assert result.verdict == "REJECT"
    assert any("量" in r for r in result.reasons)


def test_adx_boundary_exactly_20_fails_gate():
    # direct boundary check is at unit level: gate uses strict >
    from strategy.swing.scanner import _gate_failures
    assert _gate_failures(adx_value=20.0, close=100.0, sma200=90.0,
                          weekly_close=100.0, weekly_sma=90.0)
    assert not _gate_failures(adx_value=20.01, close=100.0, sma200=90.0,
                              weekly_close=100.0, weekly_sma=90.0)
```

- [ ] **Step 2: Run to verify failure** — CANDIDATE test fails on `not implemented`.

- [ ] **Step 3: Implement** — first extend the indicators import in scanner.py to:

```python
from strategy.swing.indicators import (
    adx,
    atr,
    bollinger,
    in_squeeze,
    macd,
    resample_weekly,
    sma,
)
```

Then replace the `# Tasks 8-9 extend from here.` block in `evaluate()` and
add the helper:

```python
def _gate_failures(
    *,
    adx_value: float | None,
    close: float,
    sma200: float | None,
    weekly_close: float,
    weekly_sma: float | None,
) -> list[str]:
    failures = []
    if adx_value is None or adx_value <= 20.0:
        failures.append("ADX≤20 趨勢強度不足")
    if sma200 is None or close <= sma200:
        failures.append("收盤未站上200SMA")
    if weekly_sma is None or weekly_close <= weekly_sma:
        failures.append("週線未站上10週SMA")
    return failures
```

Inside `evaluate()` after the degenerate guard:

```python
    closes = [bar.close for bar in bars]
    volumes = [float(bar.volume) for bar in bars]
    t = len(bars) - 1

    adx_series = adx(bars, params.atr_period)
    sma_long = sma(closes, params.sma_long)
    weekly = resample_weekly(bars)
    weekly_closes = [bar.close for bar in weekly]
    weekly_sma = sma(weekly_closes, params.weekly_sma)
    middle, _upper, _lower, width = bollinger(closes, params.bb_period, params.bb_std)
    vol_avg = sma(volumes, params.vol_sma)
    dif, dea, hist = macd(closes)

    entry = closes[-1]
    reasons: list[str] = []
    adx_t = adx_series[-1]

    failures = _gate_failures(
        adx_value=adx_t,
        close=entry,
        sma200=sma_long[-1],
        weekly_close=weekly_closes[-1],
        weekly_sma=weekly_sma[-1],
    )
    if adx_t is not None and params.adx_min < adx_t <= params.adx_trend:
        reasons.append("warning: ADX 20–25 中間態")

    squeeze_recent = any(
        in_squeeze(width, i, params.bb_pct_window, params.squeeze_pct) is True
        for i in range(t - params.squeeze_lookback + 1, t + 1)
    )
    trigger = (
        middle[-2] is not None
        and middle[-1] is not None
        and width[-1] is not None
        and width[-2] is not None
        and closes[-2] <= middle[-2]
        and closes[-1] > middle[-1]
        and width[-1] > width[-2]
    )
    volume_ok = vol_avg[-1] is not None and volumes[-1] > vol_avg[-1]
    momentum = (
        dif[-1] is not None
        and dea[-1] is not None
        and hist[-1] is not None
        and hist[-2] is not None
        and dif[-1] > dea[-1]
        and hist[-1] > hist[-2]
    )

    if failures:
        verdict = "REJECT"
        reasons = failures + reasons
    elif squeeze_recent and trigger and volume_ok and momentum:
        verdict = "CANDIDATE"
    elif squeeze_recent and not trigger:
        # spec: squeeze present, no trigger yet → 蓄勢中
        verdict = "WATCH"
        reasons.append("蓄勢中：squeeze 未觸發突破")
    else:
        verdict = "REJECT"
        if not squeeze_recent:
            reasons.append("未經蓄勢（近10日無BB squeeze）")
        if trigger and not volume_ok:
            reasons.append("突破未獲量能確認（量≤20日均量）")
        if trigger and not momentum:
            reasons.append("突破未獲MACD動能確認")

    # Task 9 extends from here (stop/T1/RR/sizing/exit plan/snapshot).
    return ScanResult(symbol=symbol, verdict=verdict, reasons=reasons, entry=entry)
```

- [ ] **Step 4: Run to verify pass.** If `test_full_setup_is_candidate` fails,
debug by printing which of the four flags is False — adjust the FIXTURE knobs
(quiet length, breakout size), never the rule constants.

- [ ] **Step 5: Commit** — `"feat(strategy): swing gates and four-confirmation verdicts"`.

---

### Task 9: stop / T1 / RR / sizing / exit plan / snapshot

**Files:** same as Task 7.

- [ ] **Step 1: Write the failing tests** (append)

```python
from strategy.swing.scanner import stop_distance, t1_target, vix_multiplier


def test_stop_distance_picks_min_viable_term_and_basis():
    # atr term = 2*2=4; structure = 100-(95-0.2)=5.2; ma = 100-97=3 → min = ma
    dist, basis = stop_distance(entry=100.0, atr14=2.0, struct_low=95.0, sma20=97.0)
    assert (dist, basis) == (3.0, "ma")


def test_stop_distance_floor_binds():
    # min term 0.4 < 0.5*atr=1.0 → floor
    dist, basis = stop_distance(entry=100.0, atr14=2.0, struct_low=99.8, sma20=99.6)
    assert (dist, basis) == (1.0, "floor")


def test_stop_distance_cap_binds():
    # all terms above 2*atr → cap to atr basis
    dist, basis = stop_distance(entry=100.0, atr14=2.0, struct_low=80.0, sma20=85.0)
    assert (dist, basis) == (4.0, "atr")


def test_stop_distance_nonviable_terms_excluded():
    # entry below sma20 → ma term ≤ 0 excluded; structure viable
    dist, basis = stop_distance(entry=100.0, atr14=2.0, struct_low=98.0, sma20=101.0)
    assert basis == "structure"
    assert dist == pytest.approx(100.0 - (98.0 - 0.2))


def test_t1_picks_most_recent_pivot_above_entry():
    highs = [10.0] * 130
    highs[100] = 50.0   # pivot, above entry
    highs[110] = 40.0   # pivot, above entry, more recent
    t1, fallback = t1_target(highs, entry=20.0, dist=2.0, min_rr=2.5,
                             window=120, flank=2)
    assert (t1, fallback) == (40.0, False)


def test_t1_excludes_last_two_sessions_and_falls_back():
    highs = [10.0] * 130
    highs[-2] = 50.0  # would be a pivot but unconfirmable
    t1, fallback = t1_target(highs, entry=20.0, dist=2.0, min_rr=2.5,
                             window=120, flank=2)
    assert fallback is True
    assert t1 == pytest.approx(20.0 + 2.5 * 2.0)


def test_vix_multiplier_bands():
    assert vix_multiplier(None) == 1.0
    assert vix_multiplier(14.99) == 1.25
    assert vix_multiplier(15.0) == 1.0
    assert vix_multiplier(25.0) == 0.75
    assert vix_multiplier(35.0) == 0.5


def test_candidate_full_fields_and_sizing():
    result = evaluate("T", build_bars(), equity=100_000, risk_pct=0.015)
    assert result.verdict == "CANDIDATE"
    assert result.stop is not None and result.stop < result.entry
    assert result.rr is not None and result.rr >= 2.5
    assert result.t1_fallback is True  # breakout to new high → no pivot above
    assert result.shares is not None and result.shares >= 0
    assert set(result.indicator_snapshot) == {
        "adx", "atr14", "atr_ratio", "bb_width", "bb_width_p20",
        "macd_dif", "macd_dea", "macd_hist",
    }
    assert set(result.exit_plan) == {"ma5", "ma10", "ma20", "time_stop"}
    assert result.manual_checklist  # non-empty for CANDIDATE


def test_shares_floor_to_zero_keeps_verdict():
    result = evaluate("T", build_bars(), equity=10.0, risk_pct=0.015)
    assert result.verdict in ("CANDIDATE", "WATCH")
    assert result.shares == 0
    assert any("部位不足一股" in r for r in result.reasons)
```

- [ ] **Step 2: Run to verify failure** — ImportError on the three helpers.

- [ ] **Step 3: Implement** — extend the indicators import once more
(add `nearest_rank_percentile` and `pivot_highs` to the Task-8 import list),
then add helpers to scanner.py:

```python
def stop_distance(
    *, entry: float, atr14: float, struct_low: float, sma20: float,
    buffer_atr: float = 0.1,
) -> tuple[float, str]:
    terms = {"atr": 2.0 * atr14}
    struct_term = entry - (struct_low - buffer_atr * atr14)
    if struct_term > 0:
        terms["structure"] = struct_term
    ma_term = entry - sma20
    if ma_term > 0:
        terms["ma"] = ma_term
    basis, dist = min(terms.items(), key=lambda item: item[1])
    floor = 0.5 * atr14
    if dist < floor:
        dist, basis = floor, "floor"
    cap = 2.0 * atr14
    if dist > cap:
        dist, basis = cap, "atr"
    return dist, basis


def t1_target(
    highs: Sequence[float], *, entry: float, dist: float, min_rr: float,
    window: int, flank: int,
) -> tuple[float, bool]:
    t = len(highs) - 1
    lo = max(0, t - window + 1)
    candidates = [
        i
        for i in pivot_highs(highs, flank)
        if lo <= i <= t - 2 and highs[i] > entry
    ]
    if candidates:
        return highs[max(candidates)], False
    return entry + min_rr * dist, True


def vix_multiplier(vix: float | None) -> float:
    if vix is None:
        return 1.0
    if vix < 15.0:
        return 1.25
    if vix < 25.0:
        return 1.0
    if vix < 35.0:
        return 0.75
    return 0.5
```

Replace the Task-8 ending of `evaluate()` (everything from
`# Task 9 extends from here` to the final `return`) with:

```python
    atr14_t = atr_mid[-1]
    dist, basis = stop_distance(
        entry=entry,
        atr14=atr14_t,
        struct_low=min(bar.low for bar in bars[-params.struct_window :]),
        sma20=middle[-1],
        buffer_atr=params.struct_buffer_atr,
    )
    if dist <= 0:
        return ScanResult(
            symbol=symbol, verdict="SKIP", reasons=["degenerate price series"]
        )
    highs = [bar.high for bar in bars]
    t1, fallback = t1_target(
        highs, entry=entry, dist=dist, min_rr=params.min_rr,
        window=params.pivot_window, flank=params.pivot_flank,
    )
    rr = (t1 - entry) / dist
    if verdict == "CANDIDATE" and rr < params.min_rr:
        verdict = "WATCH"
        reasons.append("盈虧比不足")

    atr_ratio = atr_fast[-1] / atr_slow[-1]
    atr_mult = 0.5 if atr_ratio > params.atr_ratio_max else 1.0
    vix_mult = vix_multiplier(vix)
    shares = math.floor(math.floor(equity * risk_pct / dist) * atr_mult * vix_mult)
    if shares == 0:
        reasons.append("部位不足一股（權益過小或停損過寬）")

    sma5 = sma(closes, 5)
    sma10 = sma(closes, 10)
    p20 = nearest_rank_percentile(
        [w for w in width[-params.bb_pct_window :] if w is not None],
        params.squeeze_pct,
    )
    return ScanResult(
        symbol=symbol,
        verdict=verdict,
        reasons=reasons,
        entry=entry,
        stop=entry - dist,
        stop_basis=basis,
        t1=t1,
        t1_fallback=fallback,
        rr=rr,
        shares=shares,
        multipliers={"atr": atr_mult, "vix": vix_mult if vix is not None else None},
        exit_plan={
            "ma5": sma5[-1],
            "ma10": sma10[-1],
            "ma20": middle[-1],
            "time_stop": TIME_STOP_TEXT,
        },
        manual_checklist=list(MANUAL_CHECKLIST),
        indicator_snapshot={
            "adx": adx_t,
            "atr14": atr14_t,
            "atr_ratio": atr_ratio,
            "bb_width": width[-1],
            "bb_width_p20": p20,
            "macd_dif": dif[-1],
            "macd_dea": dea[-1],
            "macd_hist": hist[-1],
        },
    )
```

Also export the public API:

```python
# packages/strategy/src/strategy/swing/__init__.py
"""Swing-trading scanner: pure indicators and rule engine."""

from strategy.swing.scanner import ScanParams, ScanResult, evaluate

__all__ = ["ScanParams", "ScanResult", "evaluate"]
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest packages/strategy/tests -v`
Expected: all swing tests pass; existing strategy tests untouched.

- [ ] **Step 5: Commit** — `"feat(strategy): swing stop/T1/RR/sizing and full ScanResult"`.

---

### Task 10: `ScannerConfig`

**Files:**
- Modify: `apps/trader/src/trading_app/config.py`
- Test: `apps/trader/tests/test_scan.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# apps/trader/tests/test_scan.py
import pytest
from pydantic import ValidationError

from trading_app.config import ScannerConfig, TraderConfig


def test_scanner_config_defaults():
    cfg = ScannerConfig(symbols=["AAPL"], equity=50_000)
    assert cfg.risk_pct == 0.015
    assert cfg.vix is None


def test_scanner_config_rejects_bad_values():
    with pytest.raises(ValidationError):
        ScannerConfig(symbols=[], equity=50_000)
    with pytest.raises(ValidationError):
        ScannerConfig(symbols=["AAPL"], equity=0)
    with pytest.raises(ValidationError):
        ScannerConfig(symbols=["AAPL"], equity=1, risk_pct=0.06)
    with pytest.raises(ValidationError):
        ScannerConfig(symbols=["AAPL"], equity=1, vix=-1)
    with pytest.raises(ValidationError):
        ScannerConfig(symbols=["AAPL"], equity=1, extra_field=1)


def test_trader_config_scanner_section_optional():
    assert TraderConfig().scanner is None
    cfg = TraderConfig.model_validate(
        {"scanner": {"symbols": ["AAPL", "MSFT"], "equity": 100000}}
    )
    assert cfg.scanner.symbols == ["AAPL", "MSFT"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest apps/trader/tests/test_scan.py -v`
Expected: FAIL — `ImportError: cannot import name 'ScannerConfig'`

- [ ] **Step 3: Implement** — in `apps/trader/src/trading_app/config.py`, insert
after `class StrategyConfig` (line 84-89) and register on `TraderConfig`:

```python
class ScannerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbols: list[str] = Field(min_length=1)
    equity: float = Field(gt=0)
    risk_pct: float = Field(default=0.015, gt=0, le=0.05)
    vix: float | None = Field(default=None, ge=0)
```

In `TraderConfig`, add after `strategy: StrategyConfig | None = None`:

```python
    scanner: ScannerConfig | None = None
```

- [ ] **Step 4: Run to verify pass.**

- [ ] **Step 5: Commit** — `"feat(trader): add [scanner] config section"`.

---

### Task 11: `scan_report` rendering + JSON payload

**Files:**
- Create: `apps/trader/src/trading_app/scan_report.py`
- Test: `apps/trader/tests/test_scan.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
from strategy.swing.scanner import ScanResult
from trading_app.scan_report import json_payload, render_report


def _results():
    return [
        ScanResult(symbol="SKP", verdict="SKIP", reasons=["fetch failed: x"]),
        ScanResult(
            symbol="CND", verdict="CANDIDATE", reasons=[],
            entry=101.23456, stop=98.7, stop_basis="ma", t1=110.0,
            t1_fallback=False, rr=3.27654, shares=59,
            multipliers={"atr": 1.0, "vix": None},
            exit_plan={"ma5": 100.9, "ma10": 100.5, "ma20": 99.8, "time_stop": "t"},
            manual_checklist=["check1"],
            indicator_snapshot={
                "adx": 31.2, "atr14": 1.9, "atr_ratio": 1.1, "bb_width": 0.04,
                "bb_width_p20": 0.03, "macd_dif": 0.5, "macd_dea": 0.4,
                "macd_hist": 0.1,
            },
        ),
    ]


def test_render_report_sorts_candidates_first():
    text = render_report(_results())
    assert text.index("CND") < text.index("SKP")
    assert "check1" in text  # manual checklist appears in detail block


def test_json_payload_schema_and_rounding():
    payload = json_payload(_results(), generated_at="2026-06-12T22:00:00+00:00")
    assert payload["generated_at"] == "2026-06-12T22:00:00+00:00"
    by_symbol = {r["symbol"]: r for r in payload["results"]}
    assert by_symbol["CND"]["entry"] == 101.2346  # 4-dp rounding
    assert by_symbol["CND"]["rr"] == 3.2765
    assert by_symbol["CND"]["stop_basis"] == "ma"
    assert by_symbol["SKP"]["indicator_snapshot"] is None
    assert by_symbol["SKP"]["entry"] is None
```

- [ ] **Step 2: Run to verify failure** — ImportError.

- [ ] **Step 3: Implement**

```python
# apps/trader/src/trading_app/scan_report.py
"""Console table and JSON serialization for swing scan results."""

from __future__ import annotations

import dataclasses
from typing import Any

from strategy.swing.scanner import ScanResult

_VERDICT_ORDER = {"CANDIDATE": 0, "WATCH": 1, "REJECT": 2, "SKIP": 3}


def _round4(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {k: _round4(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round4(v) for v in value]
    return value


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def render_report(results: list[ScanResult]) -> str:
    ordered = sorted(results, key=lambda r: (_VERDICT_ORDER[r.verdict], r.symbol))
    lines = [
        f"{'SYMBOL':<8}{'VERDICT':<11}{'ENTRY':>9}{'STOP':>9}"
        f"{'T1':>9}{'RR':>7}{'SHARES':>8}  REASON"
    ]
    for r in ordered:
        reason = r.reasons[0] if r.reasons else ""
        shares = "-" if r.shares is None else str(r.shares)
        rr = "-" if r.rr is None else f"{r.rr:.2f}"
        lines.append(
            f"{r.symbol:<8}{r.verdict:<11}{_fmt(r.entry):>9}{_fmt(r.stop):>9}"
            f"{_fmt(r.t1):>9}{rr:>7}{shares:>8}  {reason}"
        )
    for r in ordered:
        if r.verdict not in ("CANDIDATE", "WATCH"):
            continue
        lines.append("")
        lines.append(f"== {r.symbol} ({r.verdict}) ==")
        lines.append(
            f"entry={_fmt(r.entry)} stop={_fmt(r.stop)} ({r.stop_basis}) "
            f"t1={_fmt(r.t1)}{' (fallback)' if r.t1_fallback else ''} "
            f"rr={'-' if r.rr is None else f'{r.rr:.2f}'} shares={r.shares}"
        )
        if r.exit_plan:
            lines.append(
                f"exit: 5MA={_fmt(r.exit_plan['ma5'])} "
                f"10MA={_fmt(r.exit_plan['ma10'])} 20MA={_fmt(r.exit_plan['ma20'])} "
                f"| {r.exit_plan['time_stop']}"
            )
        for reason in r.reasons:
            lines.append(f"note: {reason}")
        for item in r.manual_checklist:
            lines.append(f"manual: {item}")
    return "\n".join(lines)


def json_payload(results: list[ScanResult], *, generated_at: str) -> dict:
    return {
        "generated_at": generated_at,
        "results": [_round4(dataclasses.asdict(r)) for r in results],
    }
```

Note: `ScanResult` contains no date fields (timestamps stay in `Bar`), so the
spec's "dates as YYYY-MM-DD" clause is satisfied vacuously; `generated_at` is
the only timestamp and is passed as an ISO string by the caller.

- [ ] **Step 4: Run to verify pass.**

- [ ] **Step 5: Commit** — `"feat(trader): scan report rendering and JSON payload"`.

---

### Task 12: `run_scan` in assembly

**Files:**
- Modify: `apps/trader/src/trading_app/assembly.py`
- Test: `apps/trader/tests/test_scan.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
import json
from datetime import date, timedelta

from core.models import Bar, Contract
from trading_app.assembly import run_scan


class FakeDataHandler:
    """Implements only what run_scan uses: fetch_history."""

    def __init__(self, history: dict[str, list[Bar]]):
        self.history = history
        self.requests: list[tuple[Contract, str, str]] = []

    async def fetch_history(self, contract, duration, bar_size):
        self.requests.append((contract, duration, bar_size))
        if contract.symbol == "BOOM":
            raise RuntimeError("no contract")
        return self.history.get(contract.symbol, [])


def _flat_history(n=400, price=100.0):
    start = date(2026, 1, 2)
    return [
        Bar(start + timedelta(days=i), "X", price, price, price, price, 1000)
        for i in range(n)
    ]


def _scan_config(symbols):
    return TraderConfig.model_validate(
        {"scanner": {"symbols": symbols, "equity": 100000}}
    )


async def test_run_scan_skips_failures_and_continues(capsys, tmp_path):
    handler = FakeDataHandler({"FLAT": _flat_history()})
    json_file = tmp_path / "out.json"
    code = await run_scan(
        _scan_config(["BOOM", "FLAT", "EMPTY"]),
        data_handler=handler,
        json_path=json_file,
    )
    assert code == 0
    # all three symbols requested with spec duration/bar size, STK contracts
    assert [(c.symbol, c.sec_type, d, b) for c, d, b in handler.requests] == [
        ("BOOM", "STK", "2 Y", "1 day"),
        ("FLAT", "STK", "2 Y", "1 day"),
        ("EMPTY", "STK", "2 Y", "1 day"),
    ]
    payload = json.loads(json_file.read_text())
    verdicts = {r["symbol"]: r["verdict"] for r in payload["results"]}
    assert verdicts == {"BOOM": "SKIP", "FLAT": "SKIP", "EMPTY": "SKIP"}
    assert "generated_at" in payload
    out = capsys.readouterr().out
    assert "BOOM" in out and "FLAT" in out


async def test_run_scan_requires_scanner_section():
    with pytest.raises(ValueError, match=r"\[scanner\]"):
        await run_scan(TraderConfig(), data_handler=FakeDataHandler({}))
```

- [ ] **Step 2: Run to verify failure** — `ImportError: cannot import name 'run_scan'`.

- [ ] **Step 3: Implement** — append to `apps/trader/src/trading_app/assembly.py`
(after `load_strategy`); add the two imports to the existing import block
(`from strategy.swing.scanner import ScanResult, evaluate` next to the
existing `from strategy.base import BaseStrategy`, and
`from trading_app.scan_report import json_payload, render_report` next to the
`trading_app.config` import):

```python
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
        payload = json_payload(
            results, generated_at=datetime.now(UTC).isoformat()
        )
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
```

`json` must be added to assembly's stdlib imports (`import json` next to
`import asyncio`). `datetime`/`UTC` and `Path` are already imported.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest apps/trader/tests/test_scan.py -v`
Expected: all pass.

- [ ] **Step 5: Commit** — `"feat(trader): run_scan wiring with injectable DataHandler"`.

---

### Task 13: `scan` CLI subcommand + config example

**Files:**
- Modify: `apps/trader/src/trading_app/cli.py`
- Modify: `apps/trader/config.toml`
- Test: `apps/trader/tests/test_scan.py` (append)

- [ ] **Step 1: Write the failing test** (append)

```python
from trading_app.cli import _build_parser


def test_cli_scan_subcommand_parses():
    args = _build_parser().parse_args(["scan", "--json", "out.json"])
    assert args.command == "scan"
    assert str(args.json) == "out.json"
    args = _build_parser().parse_args(["scan"])
    assert args.json is None
```

- [ ] **Step 2: Run to verify failure** — argparse error: `invalid choice: 'scan'`.

- [ ] **Step 3: Implement** — in `cli.py`:

In `_build_parser()` after the `live` subparser line:

```python
    scan_parser = subparsers.add_parser("scan", parents=[config_parser])
    scan_parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write full scan results JSON to this path",
    )
```

In `main()` after the `live` dispatch:

```python
    if args.command == "scan":
        return asyncio.run(run_scan(config, json_path=args.json))
```

Add `run_scan` to the existing `from trading_app.assembly import (...)` block.

In `apps/trader/config.toml`, append:

```toml
# [scanner]
# symbols = ["AAPL", "MSFT", "NVDA"]
# equity = 100000.0
# risk_pct = 0.015   # 波段單筆風險 1.5%（knowledge base）
# vix = 18.5         # optional; omit to skip the VIX multiplier
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest apps/trader/tests -v`
Expected: all pass, including the pre-existing cli/config/assembly tests.

- [ ] **Step 5: Commit** — `"feat(trader): scan CLI subcommand"`.

---

### Task 14: full verification

- [ ] **Step 1: Full test suite**

Run: `uv run pytest`
Expected: all packages pass, zero failures.

- [ ] **Step 2: Lint**

Run: `uv run ruff check .`
Expected: clean (hooks have been formatting along the way).

- [ ] **Step 3: Spec conformance sweep** — re-read the spec's Rule Set section
and confirm each table row / formula maps to an implemented test. Pay
attention to: equality edges (ADX 20, VIX 15/25/35, ratio 1.5, percentile
tie), 340-bar floor, zero-volume SKIP, partial-week inclusion.

- [ ] **Step 4: Commit anything outstanding; do NOT merge** — Stage 6+ of the
pipeline (PR, dual review, merge) takes over from here.

---

## Rollback Strategy

Purely additive feature. To roll back after merge:
`rtk git revert <squash-merge-sha>` — removes the `strategy.swing` package,
the `scan` subcommand, `ScannerConfig`, and `scan_report.py` in one commit.
No DB migrations, no feature flags, no config invalidations (the `[scanner]`
TOML example is commented out; existing configs stay valid).
