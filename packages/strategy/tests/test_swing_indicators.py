from strategy.swing.indicators import ema, sma


def test_sma_pads_warmup_with_none():
    assert sma([1.0, 2.0, 3.0, 4.0, 5.0], 3) == [None, None, 2.0, 3.0, 4.0]


def test_sma_period_longer_than_series():
    assert sma([1.0, 2.0], 5) == [None, None]


def test_ema_seeds_with_sma_then_recurses():
    # period 3 → alpha = 0.5; seed at index 2 = mean(1,2,3) = 2
    # idx3 = 0.5*4 + 0.5*2 = 3; idx4 = 0.5*5 + 0.5*3 = 4
    assert ema([1.0, 2.0, 3.0, 4.0, 5.0], 3) == [None, None, 2.0, 3.0, 4.0]
