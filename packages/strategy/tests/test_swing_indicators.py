from datetime import date

import pytest

from core.models import Bar
from strategy.swing.indicators import atr, ema, sma, true_range


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
