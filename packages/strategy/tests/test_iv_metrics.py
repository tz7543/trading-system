import math

import pytest

from strategy.iv_metrics import (
    IVMetrics,
    calculate_iv_metrics,
    calculate_iv_percentile,
    calculate_iv_rank,
    valid_iv_values,
)


def test_calculate_iv_rank_uses_zero_to_one_hundred_scale():
    result = calculate_iv_rank([0.20, 0.30, 0.50], 0.425)

    assert result == 75.0


def test_calculate_iv_percentile_uses_less_than_or_equal_count():
    result = calculate_iv_percentile([0.20, 0.30, 0.50], 0.30)

    assert result == pytest.approx(66.6666666667)


def test_valid_iv_values_ignores_none_nan_and_negative_values():
    result = valid_iv_values([None, 0.20, math.nan, -0.10, 0.35])

    assert result == [0.20, 0.35]


def test_empty_iv_history_raises_value_error():
    with pytest.raises(ValueError, match="iv history is empty"):
        calculate_iv_rank([None, math.nan, -0.01], 0.20)


def test_flat_iv_history_rank_is_binary():
    assert calculate_iv_rank([0.30, 0.30], 0.30) == 100.0
    assert calculate_iv_rank([0.30, 0.30], 0.20) == 0.0


def test_calculate_iv_metrics_returns_composite_dataclass():
    result = calculate_iv_metrics([0.20, 0.30, 0.50], 0.425)

    assert isinstance(result, IVMetrics)
    assert result.current_iv == 0.425
    assert result.iv_rank == 75.0
    assert result.iv_percentile == pytest.approx(66.6666666667)
    assert result.history_count == 3
