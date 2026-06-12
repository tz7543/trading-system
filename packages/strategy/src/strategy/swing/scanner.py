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
    nearest_rank_percentile,
    pivot_highs,
    resample_weekly,
    sma,
)

MANUAL_CHECKLIST = [
    "距財報 ≥ 3 天（無財報日曆資料，自行確認）",  # noqa: RUF001
    "與既有持倉相關性 < 0.7（無組合資料，自行確認)",  # noqa: RUF001
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


def stop_distance(
    *,
    entry: float,
    atr14: float,
    struct_low: float,
    sma20: float,
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
    highs: Sequence[float],
    *,
    entry: float,
    dist: float,
    min_rr: float,
    window: int,
    flank: int,
) -> tuple[float, bool]:
    t = len(highs) - 1
    lo = max(0, t - window + 1)
    candidates = [
        i for i in pivot_highs(highs, flank) if lo <= i <= t - 2 and highs[i] > entry
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


def atr_haircut(ratio: float, threshold: float = 1.5) -> float:
    return 0.5 if ratio > threshold else 1.0


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
        reasons.append("warning: ADX 20-25 中間態")

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
        highs,
        entry=entry,
        dist=dist,
        min_rr=params.min_rr,
        window=params.pivot_window,
        flank=params.pivot_flank,
    )
    # When fallback, t1 = entry + min_rr * dist so rr is exactly min_rr by
    # construction; use that directly to avoid float precision drift.
    rr = params.min_rr if fallback else (t1 - entry) / dist
    if verdict == "CANDIDATE" and rr < params.min_rr:
        verdict = "WATCH"
        reasons.append("盈虧比不足")

    atr_ratio = atr_fast[-1] / atr_slow[-1]
    atr_mult = atr_haircut(atr_ratio, params.atr_ratio_max)
    vix_mult = vix_multiplier(vix)
    shares = math.floor(math.floor(equity * risk_pct / dist) * atr_mult * vix_mult)
    if shares == 0:
        reasons.append("部位不足一股（權益過小或停損過寬）")  # noqa: RUF001

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
        confirmations={
            "squeeze": squeeze_recent,
            "trigger": trigger,
            "volume": volume_ok,
            "momentum": momentum,
        },
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
