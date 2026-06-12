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
