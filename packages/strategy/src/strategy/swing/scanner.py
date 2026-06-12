# packages/strategy/src/strategy/swing/scanner.py
"""Swing scanner rule engine. Pure: list[Bar] in, ScanResult out. No I/O.

Spec: docs/superpowers/specs/2026-06-12-swing-scanner-design.md -- the spec is
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
# them earlier -- the auto-format hook strips unused imports (F401).

MANUAL_CHECKLIST = [
    "距財報 ≥ 3 天（無財報日曆資料，自行確認）",  # noqa: RUF001
    "與既有持胁相關性 < 0.7（無組合資料，自行確認)",  # noqa: RUF001
    "重大事件日（FOMC/CPI）自行確認",  # noqa: RUF001
]
TIME_STOP_TEXT = "≤5日浮盈<0.5R減半；≤15日未達T1全出"  # noqa: RUF001


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
    confirmations: dict | None = None  # squeeze/trigger/volume/momentum -> bool
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
