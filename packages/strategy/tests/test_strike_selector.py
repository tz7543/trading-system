import pytest

from core.models import Greeks
from strategy.strike_selector import (
    filter_strikes,
    select_atm,
    select_by_delta,
    select_strike,
)

STRIKES = [140.0, 142.5, 145.0, 147.5, 150.0, 152.5, 155.0, 157.5, 160.0]


def test_filter_strikes_normal():
    result = filter_strikes(STRIKES, underlying_price=150.0, max_distance=2)
    assert result == [145.0, 147.5, 150.0, 152.5, 155.0]


def test_filter_strikes_empty():
    result = filter_strikes([], underlying_price=150.0, max_distance=5)
    assert result == []


def test_filter_strikes_all_within_range():
    result = filter_strikes(STRIKES, underlying_price=150.0, max_distance=20)
    assert result == STRIKES


def test_select_atm_exact():
    result = select_atm(STRIKES, underlying_price=150.0)
    assert result == 150.0


def test_select_atm_between_strikes():
    result = select_atm(STRIKES, underlying_price=151.0)
    assert result == 150.0


def test_select_atm_equidistant_picks_lower():
    result = select_atm([145.0, 150.0, 155.0], underlying_price=152.5)
    assert result == 150.0


def test_select_atm_positive_offset():
    result = select_atm(STRIKES, underlying_price=150.0, offset=2)
    assert result == 155.0


def test_select_atm_negative_offset():
    result = select_atm(STRIKES, underlying_price=150.0, offset=-2)
    assert result == 145.0


def test_select_atm_offset_out_of_range():
    with pytest.raises(ValueError, match=r"offset .* out of range"):
        select_atm(STRIKES, underlying_price=150.0, offset=20)


def test_select_atm_empty_strikes():
    with pytest.raises(ValueError, match="no strikes available"):
        select_atm([], underlying_price=150.0)


def test_select_by_delta_call():
    greeks_map = {
        145.0: Greeks(delta=0.70),
        150.0: Greeks(delta=0.50),
        155.0: Greeks(delta=0.30),
        160.0: Greeks(delta=0.15),
    }
    result = select_by_delta(
        strikes=[145.0, 150.0, 155.0, 160.0],
        greeks_map=greeks_map,
        target_delta=0.30,
        right="C",
    )
    assert result == 155.0


def test_select_by_delta_put():
    greeks_map = {
        140.0: Greeks(delta=-0.15),
        145.0: Greeks(delta=-0.30),
        150.0: Greeks(delta=-0.50),
        155.0: Greeks(delta=-0.70),
    }
    result = select_by_delta(
        strikes=[140.0, 145.0, 150.0, 155.0],
        greeks_map=greeks_map,
        target_delta=0.30,
        right="P",
    )
    assert result == 145.0


def test_select_by_delta_no_greeks():
    with pytest.raises(ValueError, match="no greeks available"):
        select_by_delta(
            strikes=[145.0, 150.0, 155.0],
            greeks_map={},
            target_delta=0.30,
            right="C",
        )


def test_select_by_delta_partial_greeks():
    greeks_map = {
        150.0: Greeks(delta=0.50),
        155.0: Greeks(delta=0.30),
    }
    result = select_by_delta(
        strikes=[145.0, 150.0, 155.0, 160.0],
        greeks_map=greeks_map,
        target_delta=0.50,
        right="C",
    )
    assert result == 150.0


def test_select_by_delta_tie_picks_lower():
    greeks_map = {
        145.0: Greeks(delta=0.40),
        155.0: Greeks(delta=0.20),
    }
    result = select_by_delta(
        strikes=[145.0, 155.0],
        greeks_map=greeks_map,
        target_delta=0.30,
        right="C",
    )
    assert result == 145.0


def test_select_strike_with_greeks():
    greeks_map = {
        145.0: Greeks(delta=0.70),
        150.0: Greeks(delta=0.50),
        155.0: Greeks(delta=0.30),
    }
    result = select_strike(
        strikes=[145.0, 150.0, 155.0],
        underlying_price=150.0,
        right="C",
        target_delta=0.30,
        greeks_map=greeks_map,
    )
    assert result == 155.0


def test_select_strike_fallback_no_greeks():
    result = select_strike(
        strikes=[145.0, 150.0, 155.0],
        underlying_price=150.0,
        right="C",
    )
    assert result == 150.0


def test_select_strike_fallback_delta_without_greeks():
    result = select_strike(
        strikes=[145.0, 150.0, 155.0],
        underlying_price=150.0,
        right="C",
        target_delta=0.30,
    )
    assert result == 150.0


def test_select_strike_fallback_with_offset():
    result = select_strike(
        strikes=[145.0, 150.0, 155.0],
        underlying_price=150.0,
        right="C",
        offset=1,
    )
    assert result == 155.0
