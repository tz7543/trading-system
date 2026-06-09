from datetime import UTC, datetime

from core.events import SignalEvent
from core.models import Contract, Greeks, Leg, MarginInfo, Order, Position, RiskLimits
from risk.pre_trade import PreTradeValidator


def _limits():
    return RiskLimits(
        max_delta=200.0,
        max_vega=500.0,
        max_drawdown=0.10,
        max_position_size=5,
        max_margin_utilization=0.80,
    )


def _signal(legs=None, strategy_id="test"):
    if legs is None:
        c = Contract(symbol="AAPL", sec_type="STK")
        legs = [Leg(contract=c, quantity=100)]
    order = Order(legs=legs, strategy_id=strategy_id)
    return SignalEvent(
        strategy_id=strategy_id,
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        direction="ENTER",
        proposed_order=order,
        reason="Test",
    )


def test_approved_within_limits():
    validator = PreTradeValidator(_limits())
    result = validator.validate(
        signal=_signal(),
        portfolio_greeks=Greeks(delta=50.0, vega=100.0),
        proposed_greeks=Greeks(delta=100.0, vega=50.0),
        positions=[],
    )
    assert result.approved is True


def test_rejected_position_limit():
    validator = PreTradeValidator(_limits())
    existing = [
        Position(
            legs=[Leg(contract=Contract(symbol="AAPL", sec_type="STK"), quantity=100)],
            strategy_id=f"s{i}",
        )
        for i in range(5)
    ]
    result = validator.validate(
        signal=_signal(),
        portfolio_greeks=Greeks(),
        proposed_greeks=Greeks(),
        positions=existing,
    )
    assert result.approved is False
    assert "Position limit" in result.reason


def test_rejected_delta_exceeded():
    validator = PreTradeValidator(_limits())
    result = validator.validate(
        signal=_signal(),
        portfolio_greeks=Greeks(delta=150.0),
        proposed_greeks=Greeks(delta=100.0),
        positions=[],
    )
    assert result.approved is False
    assert "Delta" in result.reason


def test_rejected_vega_exceeded():
    validator = PreTradeValidator(_limits())
    result = validator.validate(
        signal=_signal(),
        portfolio_greeks=Greeks(vega=400.0),
        proposed_greeks=Greeks(vega=200.0),
        positions=[],
    )
    assert result.approved is False
    assert "Vega" in result.reason


def test_approved_margin_within_limits():
    validator = PreTradeValidator(_limits())
    result = validator.validate(
        signal=_signal(),
        portfolio_greeks=Greeks(),
        proposed_greeks=Greeks(),
        positions=[],
        margin_info=MarginInfo(
            init_margin=50000.0,
            maint_margin=40000.0,
            equity_with_loan=100000.0,
        ),
    )
    assert result.approved is True


def test_rejected_margin_exceeded():
    validator = PreTradeValidator(_limits())
    result = validator.validate(
        signal=_signal(),
        portfolio_greeks=Greeks(),
        proposed_greeks=Greeks(),
        positions=[],
        margin_info=MarginInfo(
            init_margin=90000.0,
            maint_margin=70000.0,
            equity_with_loan=100000.0,
        ),
    )
    assert result.approved is False
    assert "Margin" in result.reason


def test_approved_without_margin_info():
    validator = PreTradeValidator(_limits())
    result = validator.validate(
        signal=_signal(),
        portfolio_greeks=Greeks(),
        proposed_greeks=Greeks(),
        positions=[],
        margin_info=None,
    )
    assert result.approved is True
