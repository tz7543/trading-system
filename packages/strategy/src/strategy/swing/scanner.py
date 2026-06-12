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
from strategy.swing.indicators import (
    adx,
    atr,
    bollinger,
    in_squeeze,
    macd,
    resample_weekly,
    sma,
)

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
        failures.append("ADX<=20 趨勢強度不足")
    if sma200 is None or close <= sma200:
        failures.append("收盤未站上200SMA")
    if weekly_sma is None or weekly_close <= weekly_sma:
        failures.append("週線未站上10週SMA")
    return failures


def trigger_fired(
    *,
    close_prev: float,
    close_now: float,
    mid_prev: float | None,
    mid_now: float | None,
    width_prev: float | None,
    width_now: float | None,
) -> bool:
    if mid_prev is None or mid_now is None or width_prev is None or width_now is None:
        return False
    return close_prev <= mid_prev and close_now > mid_now and width_now > width_prev


def momentum_confirmed(
    *,
    dif: float | None,
    dea: float | None,
    hist: float | None,
    hist_prev: float | None,
) -> bool:
    if dif is None or dea is None or hist is None or hist_prev is None:
        return False
    return dif > dea and hist > hist_prev


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

    closes = [bar.close for bar in bars]
    volumes = [float(bar.volume) for bar in bars]
    t = len(bars) - 1

    adx_series = adx(bars, params.atr_period)
    sma_long = sma(closes, params.sma_long)
    weekly = resample_weekly(bars)
    weekly_closes = [bar.close for bar in weekly]
    weekly_sma_series = sma(weekly_closes, params.weekly_sma)
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
        weekly_sma=weekly_sma_series[-1],
    )
    if adx_t is not None and params.adx_min < adx_t <= params.adx_trend:
        reasons.append("warning: ADX 20-25 middle state")

    squeeze_recent = any(
        in_squeeze(width, i, params.bb_pct_window, params.squeeze_pct) is True
        for i in range(t - params.squeeze_lookback + 1, t + 1)
    )
    trigger = trigger_fired(
        close_prev=closes[-2],
        close_now=closes[-1],
        mid_prev=middle[-2],
        mid_now=middle[-1],
        width_prev=width[-2],
        width_now=width[-1],
    )
    volume_ok = vol_avg[-1] is not None and volumes[-1] > vol_avg[-1]
    momentum = momentum_confirmed(
        dif=dif[-1], dea=dea[-1], hist=hist[-1], hist_prev=hist[-2]
    )

    if failures:
        verdict = "REJECT"
        reasons = failures + reasons
    elif squeeze_recent and trigger and volume_ok and momentum:
        verdict = "CANDIDATE"
    elif squeeze_recent and not trigger:
        # spec verdict mapping: WATCH is defined by trigger ABSENCE -- that
        # day's volume/momentum flags are only meaningful on the trigger day
        verdict = "WATCH"
        reasons.append("蓄勢中：squeeze 未觸發突破")  # noqa: RUF001
    else:
        verdict = "REJECT"
        if not squeeze_recent:
            reasons.append("未經蓄勢（近10日無BB squeeze）")  # noqa: RUF001
        if trigger and not volume_ok:
            reasons.append("突破未獲量能確認（量<=20日均量）")  # noqa: RUF001
        if trigger and not momentum:
            reasons.append("突破未獲MACD動能確認")

    # Task 9 extends from here (stop/T1/RR/sizing/exit plan/snapshot).
    return ScanResult(symbol=symbol, verdict=verdict, reasons=reasons, entry=entry)
