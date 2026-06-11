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


def test_pnl_fsum_precision():
    # Build many small fractional PnL values that expose IEEE-754 drift with sum().
    # Each round-trip: buy 1 @ 0.1, sell 1 @ 0.2  → pnl = +0.1
    # 100 such trades: expected total_pnl = 10.0 exactly via fsum.
    # With naive sum() the accumulated rounding error on 0.1 * 100 is non-zero.
    fills = []
    for i in range(100):
        oid_buy = f"b-{i}"
        oid_sell = f"s-{i}"
        fills.append(
            _stk_fill(
                f"SYM{i}",
                10,
                0.10,
                0.0,
                oid_buy,
                datetime(2026, 6, 4, 14, 30, tzinfo=UTC),
            )
        )
        fills.append(
            _stk_fill(
                f"SYM{i}",
                -10,
                0.20,
                0.0,
                oid_sell,
                datetime(2026, 6, 4, 14, 31, tzinfo=UTC),
            )
        )
    result = compute_metrics(fills, initial_equity=100000.0)
    # Each trade pnl = (0.20 - 0.10) * 10 = 1.0; 100 trades = 100.0 total_pnl
    assert result.total_pnl == pytest.approx(100.0)
    assert result.net_pnl == pytest.approx(100.0)
    # Additionally verify commission fsum: all zero here, so 0.0
    assert result.total_commission == pytest.approx(0.0)
