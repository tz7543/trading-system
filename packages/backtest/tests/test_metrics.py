from datetime import UTC, datetime

import pytest

from backtest.metrics import compute_metrics
from core.events import FillEvent
from core.models import Contract, Leg


def _stk_fill(symbol, qty, price, commission, order_id="sim-1", ts=None):
    return FillEvent(
        order_id=order_id,
        legs_filled=[
            Leg(
                contract=Contract(symbol=symbol, sec_type="STK"),
                quantity=qty,
                entry_price=price,
            )
        ],
        timestamp=ts or datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        commission=commission,
    )


def _opt_fill(symbol, qty, price, commission, order_id="sim-1", ts=None):
    return FillEvent(
        order_id=order_id,
        legs_filled=[
            Leg(
                contract=Contract(
                    symbol=symbol,
                    sec_type="OPT",
                    expiry="20260620",
                    strike=150.0,
                    right="C",
                ),
                quantity=qty,
                entry_price=price,
            )
        ],
        timestamp=ts or datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        commission=commission,
    )


def test_total_return_stk():
    fills = [
        _stk_fill(
            "AAPL", 100, 100.0, 0.50, "sim-1", datetime(2026, 6, 4, 14, 30, tzinfo=UTC)
        ),
        _stk_fill(
            "AAPL", -100, 110.0, 0.50, "sim-2", datetime(2026, 6, 5, 14, 30, tzinfo=UTC)
        ),
    ]
    result = compute_metrics(fills, initial_equity=100000.0)
    # PnL: (110 - 100) * 100 = $1000, commission: $1.00, net: $999
    assert result.net_pnl == pytest.approx(999.0)
    assert result.total_return == pytest.approx(999.0 / 100000.0)


def test_total_return_opt():
    fills = [
        _opt_fill(
            "AAPL_C150",
            1,
            5.00,
            0.65,
            "sim-1",
            datetime(2026, 6, 4, 14, 30, tzinfo=UTC),
        ),
        _opt_fill(
            "AAPL_C150",
            -1,
            7.00,
            0.65,
            "sim-2",
            datetime(2026, 6, 5, 14, 30, tzinfo=UTC),
        ),
    ]
    result = compute_metrics(fills, initial_equity=100000.0)
    # PnL: (7.00 - 5.00) * 1 * 100 = $200, commission: $1.30, net: $198.70
    assert result.net_pnl == pytest.approx(198.70)


def test_win_rate_and_profit_factor():
    fills = [
        _stk_fill(
            "AAPL", 100, 100.0, 0.0, "sim-1", datetime(2026, 6, 4, 14, 30, tzinfo=UTC)
        ),
        _stk_fill(
            "AAPL", -100, 110.0, 0.0, "sim-2", datetime(2026, 6, 4, 15, 0, tzinfo=UTC)
        ),
        _stk_fill(
            "MSFT", 50, 300.0, 0.0, "sim-3", datetime(2026, 6, 5, 14, 30, tzinfo=UTC)
        ),
        _stk_fill(
            "MSFT", -50, 310.0, 0.0, "sim-4", datetime(2026, 6, 5, 15, 0, tzinfo=UTC)
        ),
        _stk_fill(
            "GOOG", 30, 200.0, 0.0, "sim-5", datetime(2026, 6, 6, 14, 30, tzinfo=UTC)
        ),
        _stk_fill(
            "GOOG", -30, 190.0, 0.0, "sim-6", datetime(2026, 6, 6, 15, 0, tzinfo=UTC)
        ),
    ]
    result = compute_metrics(fills, initial_equity=100000.0)
    # Trade 1: +$1000, Trade 2: +$500, Trade 3: -$300
    assert result.win_rate == pytest.approx(2.0 / 3.0)
    # Profit factor: (1000+500) / 300 = 5.0
    assert result.profit_factor == pytest.approx(5.0)


def test_empty_fills():
    result = compute_metrics([], initial_equity=100000.0)
    assert result.net_pnl == 0.0
    assert result.total_return == 0.0
    assert result.win_rate == 0.0
    assert result.profit_factor == 0.0
    assert result.realized_max_drawdown == 0.0
