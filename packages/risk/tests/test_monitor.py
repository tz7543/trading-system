from datetime import UTC, datetime

from core.clock import SimClock
from core.models import Greeks, RiskLimits
from risk.monitor import RealTimeMonitor


def _limits():
    return RiskLimits(
        max_delta=200.0,
        max_vega=500.0,
        max_drawdown=0.10,
        max_position_size=5,
        max_margin_utilization=0.80,
    )


def test_no_alerts_within_limits():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    alerts = monitor.check(
        portfolio_greeks=Greeks(delta=100.0, vega=200.0),
        equity=100000.0,
    )
    assert alerts == []


def test_alert_on_drawdown():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    monitor.check(portfolio_greeks=Greeks(), equity=100000.0)
    alerts = monitor.check(
        portfolio_greeks=Greeks(),
        equity=85000.0,
    )
    assert len(alerts) == 1
    assert "drawdown" in alerts[0].message.lower()


def test_alert_on_delta_drift():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    alerts = monitor.check(
        portfolio_greeks=Greeks(delta=250.0),
        equity=100000.0,
    )
    assert any("delta" in a.message.lower() for a in alerts)


def test_should_circuit_break_on_drawdown():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    monitor.check(portfolio_greeks=Greeks(), equity=100000.0)
    assert not monitor.should_circuit_break(Greeks(), 95000.0)
    assert monitor.should_circuit_break(Greeks(), 85000.0)


def test_alert_on_low_dte():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    alerts = monitor.check(portfolio_greeks=Greeks(), equity=100000.0, min_dte=5)
    assert any("gamma" in a.message.lower() for a in alerts)


def test_alert_critical_dte():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    alerts = monitor.check(portfolio_greeks=Greeks(), equity=100000.0, min_dte=2)
    assert any("critical" in a.message.lower() for a in alerts)


def test_no_dte_alert_above_threshold():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    alerts = monitor.check(portfolio_greeks=Greeks(), equity=100000.0, min_dte=30)
    assert not any(
        "gamma" in a.message.lower() or "dte" in a.message.lower() for a in alerts
    )


def test_margin_cushion_yellow():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    alerts = monitor.check(
        portfolio_greeks=Greeks(), equity=100000.0, margin_cushion=0.08
    )
    assert any("yellow" in a.message.lower() for a in alerts)


def test_margin_cushion_red():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    alerts = monitor.check(
        portfolio_greeks=Greeks(), equity=100000.0, margin_cushion=0.01
    )
    assert any("red" in a.message.lower() for a in alerts)


def test_circuit_break_on_zero_dte():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    assert monitor.should_circuit_break(Greeks(), 100000.0, min_dte=0)


def test_circuit_break_on_margin_emergency():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    assert monitor.should_circuit_break(Greeks(), 100000.0, margin_cushion=0.01)


def test_no_circuit_break_safe_dte_and_margin():
    clock = SimClock(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))
    monitor = RealTimeMonitor(_limits(), clock)
    assert not monitor.should_circuit_break(
        Greeks(), 100000.0, min_dte=30, margin_cushion=0.15
    )
