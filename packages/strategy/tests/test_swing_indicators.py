from datetime import date, datetime

import pytest

from core.models import Bar
from strategy.swing.indicators import (
    adx,
    atr,
    bollinger,
    ema,
    in_squeeze,
    macd,
    nearest_rank_percentile,
    pivot_highs,
    resample_weekly,
    sma,
    true_range,
)


def test_sma_pads_warmup_with_none():
    assert sma([1.0, 2.0, 3.0, 4.0, 5.0], 3) == [None, None, 2.0, 3.0, 4.0]


def test_sma_period_longer_than_series():
    assert sma([1.0, 2.0], 5) == [None, None]


def test_ema_seeds_with_sma_then_recurses():
    # period 3 → alpha = 0.5; seed at index 2 = mean(1,2,3) = 2
    # idx3 = 0.5*4 + 0.5*2 = 3; idx4 = 0.5*5 + 0.5*3 = 4
    assert ema([1.0, 2.0, 3.0, 4.0, 5.0], 3) == [None, None, 2.0, 3.0, 4.0]


def make_bar(i, o, h, lo, c, v=1000):
    return Bar(
        timestamp=date(2026, 1, 1 + i),
        symbol="T",
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=v,
    )


def test_true_range_uses_prev_close():
    bars = [
        make_bar(0, 10, 11, 9, 10),  # TR0 = high-low = 2
        make_bar(1, 10, 12, 10, 11),  # max(2, |12-10|, |10-10|) = 2
        make_bar(2, 11, 11, 8, 9),  # max(3, |11-11|, |8-11|) = 3
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


def test_adx_wilder_hand_computed_period_2():
    bars = [
        make_bar(0, 9.5, 10.0, 9.0, 9.5),
        make_bar(1, 10.0, 11.0, 10.0, 10.5),
        make_bar(2, 11.0, 12.0, 11.0, 11.5),
        make_bar(3, 11.0, 11.5, 10.0, 10.5),
        make_bar(4, 11.5, 12.5, 11.0, 12.0),
        make_bar(5, 12.5, 13.5, 12.0, 13.0),
    ]
    # TR=[1,1.5,1.5,1.5,2,1.5]; +DM=[0,1,1,0,1,1]; -DM=[0,0,0,1,0,0]
    # Wilder(2) +DM=[_,.5,.75,.375,.6875,.84375]; -DM=[_,0,0,.5,.25,.125]
    # DX=100|p-m|/(p+m) (TR cancels) = [_,100,100,100/7,140/3,2300/31]
    # ADX(2): idx2=mean(100,100)=100; idx3=(100+100/7)/2=400/7
    # idx4=(400/7+140/3)/2=1090/21; idx5=(1090/21+2300/31)/2
    result = adx(bars, period=2)
    assert result[:2] == [None, None]
    assert result[2] == pytest.approx(100.0)
    assert result[3] == pytest.approx(400 / 7)
    assert result[4] == pytest.approx(1090 / 21)
    assert result[5] == pytest.approx((1090 / 21 + 2300 / 31) / 2)


def test_bollinger_constant_series_zero_width():
    middle, upper, lower, width = bollinger([5.0] * 7, period=5, num_std=2.0)
    assert middle[4] == upper[4] == lower[4] == 5.0
    assert width[4] == 0.0
    assert middle[:4] == [None] * 4


def test_bollinger_known_window():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    middle, upper, lower, width = bollinger(closes, period=5, num_std=2.0)
    # mean 3, population var = (4+1+0+1+4)/5 = 2, std = sqrt(2)
    std = 2**0.5
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
    # window=5 ending idx5: values [5,4,3,2,1], p20 = 1.0; width[5]=1.0 <= 1.0 → True
    assert in_squeeze(width, 5, window=5, pct=20.0) is True
    # window not fully populated (includes the None) → None
    assert in_squeeze(width, 4, window=5, pct=20.0) is None


def test_macd_alignment_and_constant_series():
    closes = [10.0] * 40
    dif, dea, hist = macd(closes, fast=12, slow=26, signal=9)
    assert len(dif) == len(dea) == len(hist) == 40
    assert dif[24] is None  # before slow EMA exists
    assert dif[25] == pytest.approx(0.0)  # first DIF at index slow-1
    assert dea[32] is None  # signal EMA needs 9 DIF values
    assert dea[33] == pytest.approx(0.0)  # 25 + 9 - 1
    assert hist[33] == pytest.approx(0.0)
    assert hist[32] is None


def test_macd_rising_series_positive_dif():
    closes = [float(i) for i in range(1, 61)]
    dif, dea, _hist = macd(closes)
    assert dif[-1] > 0
    assert dea[-1] > 0


def test_resample_weekly_groups_iso_weeks_and_accepts_date_or_datetime():
    # 2026-01-05 is a Monday (ISO week 2); 2026-01-12 the next Monday (week 3)
    bars = [
        Bar(date(2026, 1, 5), "T", 10, 12, 9, 11, 100),
        Bar(datetime(2026, 1, 7), "T", 11, 15, 10, 14, 200),  # datetime mixed in
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
