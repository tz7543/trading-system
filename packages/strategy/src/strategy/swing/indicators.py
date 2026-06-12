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


def nearest_rank_percentile(window: Sequence[float], pct: float) -> float:
    ordered = sorted(window)
    rank = max(1, ceil(pct / 100.0 * len(ordered)))
    return ordered[rank - 1]


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
        variance = sum((c - mid) ** 2 for c in window) / period  # population std
        std = variance**0.5
        upper[i] = mid + num_std * std
        lower[i] = mid - num_std * std
        if mid > 0:
            width[i] = (upper[i] - lower[i]) / mid
    return middle, upper, lower, width


def in_squeeze(
    width: Sequence[float | None], idx: int, window: int, pct: float
) -> bool | None:
    """width(idx) <= pct-percentile of the `window` widths ending at idx.

    Returns None when the window is not fully populated.
    """
    if idx + 1 < window:
        return None
    values = width[idx - window + 1 : idx + 1]
    if any(value is None for value in values):
        return None
    return values[-1] <= nearest_rank_percentile(values, pct)


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
        None if dif[i] is None or dea[i] is None else dif[i] - dea[i] for i in range(n)
    ]
    return dif, dea, hist


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
