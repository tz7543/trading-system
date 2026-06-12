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


def build_bars(
    n=360,
    ramp_days=349,
    ramp_step=0.25,
    quiet_step=-0.15,
    quiet_range=0.2,
    breakout_pct=0.05,
    breakout_volume_mult=3.0,
    base=100.0,
    volume=1_000_000,
):
    """Uptrend ramp -> shallow PULLBACK toward the rising middle band
    (squeeze) -> breakout cross-up on the last bar.

    The pullback (negative quiet_step) is load-bearing: it drags the close
    BELOW the lagging SMA20 so the final bar satisfies the trigger's
    closes[-2] <= middle[-2] cross-up condition. A monotonic rise can never
    trigger (close always above its own SMA20). Also satisfies: ADX>20
    (pullback is short so Wilder decay stays mild), close>SMA200, weekly up,
    squeeze in last 10 sessions, width expansion, volume > 20d avg, MACD
    hist expanding on the breakout bar.
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
    # invert the ramp so price ends far below its long average; a falling
    # series also fails the weekly gate, pinning both reasons end-to-end
    bars = build_bars(ramp_step=-0.25, quiet_step=-0.5, base=300.0)
    result = evaluate("T", bars, equity=100_000, risk_pct=0.015)
    assert result.verdict == "REJECT"
    assert any("200SMA" in r for r in result.reasons)
    assert any("週線" in r for r in result.reasons)


def test_no_breakout_with_squeeze_is_watch():
    # last bar stays inside the quiet drift -> squeeze present, no trigger
    bars = build_bars(breakout_pct=0.0, breakout_volume_mult=0.6)
    result = evaluate("T", bars, equity=100_000, risk_pct=0.015)
    assert result.verdict == "WATCH"
    assert any("蓄勢" in r for r in result.reasons)


def test_breakout_without_volume_rejects():
    bars = build_bars(breakout_volume_mult=0.5)
    result = evaluate("T", bars, equity=100_000, risk_pct=0.015)
    assert result.verdict == "REJECT"
    assert any("量" in r for r in result.reasons)


def test_gate_equality_boundaries():
    # direct boundary checks at unit level: every gate uses strict >
    from strategy.swing.scanner import _gate_failures

    assert _gate_failures(
        adx_value=20.0, close=100.0, sma200=90.0, weekly_close=100.0, weekly_sma=90.0
    )
    assert not _gate_failures(
        adx_value=20.01,
        close=100.0,
        sma200=90.0,
        weekly_close=100.0,
        weekly_sma=90.0,
    )
    # close exactly at SMA200 fails; weekly close exactly at weekly SMA fails
    assert _gate_failures(
        adx_value=30.0, close=100.0, sma200=100.0, weekly_close=101.0, weekly_sma=90.0
    )
    assert _gate_failures(
        adx_value=30.0, close=100.0, sma200=90.0, weekly_close=100.0, weekly_sma=100.0
    )


def test_trigger_and_momentum_boundaries():
    from strategy.swing.scanner import momentum_confirmed, trigger_fired

    # yesterday close exactly AT the middle still arms the cross (<=);
    # width expansion is strict
    assert trigger_fired(
        close_prev=10.0,
        close_now=10.5,
        mid_prev=10.0,
        mid_now=10.2,
        width_prev=0.03,
        width_now=0.031,
    )
    assert not trigger_fired(
        close_prev=10.0,
        close_now=10.5,
        mid_prev=10.0,
        mid_now=10.2,
        width_prev=0.03,
        width_now=0.03,
    )
    assert not trigger_fired(
        close_prev=10.3,
        close_now=10.5,
        mid_prev=10.0,
        mid_now=10.2,
        width_prev=0.03,
        width_now=0.04,
    )
    assert not trigger_fired(
        close_prev=10.0,
        close_now=10.5,
        mid_prev=None,
        mid_now=10.2,
        width_prev=0.03,
        width_now=0.04,
    )
    # equal histogram is NOT expansion; DIF must exceed DEA strictly
    assert momentum_confirmed(dif=1.0, dea=0.9, hist=0.1, hist_prev=0.05)
    assert not momentum_confirmed(dif=1.0, dea=0.9, hist=0.1, hist_prev=0.1)
    assert not momentum_confirmed(dif=0.9, dea=0.9, hist=0.1, hist_prev=0.05)
    assert not momentum_confirmed(dif=None, dea=0.9, hist=0.1, hist_prev=0.05)


import pytest  # noqa: E402

from strategy.swing.scanner import (  # noqa: E402
    stop_distance,
    t1_target,
    vix_multiplier,
)


def test_stop_distance_picks_min_viable_term_and_basis():
    # atr term = 2*2=4; structure = 100-(95-0.2)=5.2; ma = 100-97=3 -> min = ma
    dist, basis = stop_distance(entry=100.0, atr14=2.0, struct_low=95.0, sma20=97.0)
    assert (dist, basis) == (3.0, "ma")


def test_stop_distance_floor_binds():
    # min term 0.4 < 0.5*atr=1.0 -> floor
    dist, basis = stop_distance(entry=100.0, atr14=2.0, struct_low=99.8, sma20=99.6)
    assert (dist, basis) == (1.0, "floor")


def test_stop_distance_atr_term_wins_when_others_wide():
    # structure/ma terms exceed 2xATR -> the always-present atr term is the
    # min. (The spec's 2xATR cap is redundant-by-construction because the
    # atr term is always a candidate, but the code keeps it per spec.)
    dist, basis = stop_distance(entry=100.0, atr14=2.0, struct_low=80.0, sma20=85.0)
    assert (dist, basis) == (4.0, "atr")


def test_stop_distance_nonviable_terms_excluded():
    # entry below sma20 -> ma term <= 0 excluded; structure viable
    dist, basis = stop_distance(entry=100.0, atr14=2.0, struct_low=98.0, sma20=101.0)
    assert basis == "structure"
    assert dist == pytest.approx(100.0 - (98.0 - 0.2))


def test_t1_picks_most_recent_pivot_above_entry():
    highs = [10.0] * 130
    highs[100] = 50.0  # pivot, above entry
    highs[110] = 40.0  # pivot, above entry, more recent
    t1, fallback = t1_target(
        highs, entry=20.0, dist=2.0, min_rr=2.5, window=120, flank=2
    )
    assert (t1, fallback) == (40.0, False)


def test_t1_excludes_last_two_sessions_and_falls_back():
    highs = [10.0] * 130
    highs[-2] = 50.0  # would be a pivot but unconfirmable
    t1, fallback = t1_target(
        highs, entry=20.0, dist=2.0, min_rr=2.5, window=120, flank=2
    )
    assert fallback is True
    assert t1 == pytest.approx(20.0 + 2.5 * 2.0)


def test_vix_multiplier_bands():
    assert vix_multiplier(None) == 1.0
    assert vix_multiplier(14.99) == 1.25
    assert vix_multiplier(15.0) == 1.0
    assert vix_multiplier(25.0) == 0.75
    assert vix_multiplier(35.0) == 0.5


def test_atr_haircut_boundary():
    from strategy.swing.scanner import atr_haircut

    assert atr_haircut(1.5) == 1.0  # exactly 1.5 keeps full size (strict >)
    assert atr_haircut(1.5001) == 0.5


def test_t1_flat_top_and_below_entry_pivots_fall_back():
    flat = [10.0] * 130
    flat[100] = flat[101] = 50.0  # flat top -- strict flanks disqualify
    t1, fallback = t1_target(
        flat, entry=20.0, dist=2.0, min_rr=2.5, window=120, flank=2
    )
    assert fallback is True and t1 == pytest.approx(25.0)
    below = [10.0] * 130
    below[100] = 15.0  # genuine pivot but at/below entry
    t1, fallback = t1_target(
        below, entry=20.0, dist=2.0, min_rr=2.5, window=120, flank=2
    )
    assert fallback is True and t1 == pytest.approx(25.0)


def test_candidate_full_fields_and_sizing():
    result = evaluate("T", build_bars(), equity=100_000, risk_pct=0.015)
    assert result.verdict == "CANDIDATE"
    assert result.stop is not None and result.stop < result.entry
    assert result.rr is not None and result.rr >= 2.5
    assert result.t1_fallback is True  # breakout to new high -> no pivot above
    assert result.shares is not None and result.shares >= 0
    assert set(result.indicator_snapshot) == {
        "adx",
        "atr14",
        "atr_ratio",
        "bb_width",
        "bb_width_p20",
        "macd_dif",
        "macd_dea",
        "macd_hist",
    }
    assert set(result.exit_plan) == {"ma5", "ma10", "ma20", "time_stop"}
    assert result.manual_checklist  # non-empty for CANDIDATE
    assert result.confirmations == {
        "squeeze": True,
        "trigger": True,
        "volume": True,
        "momentum": True,
    }


def test_shares_floor_to_zero_keeps_verdict():
    result = evaluate("T", build_bars(), equity=10.0, risk_pct=0.015)
    assert result.verdict in ("CANDIDATE", "WATCH")
    assert result.shares == 0
    assert any("部位不足一股" in r for r in result.reasons)
