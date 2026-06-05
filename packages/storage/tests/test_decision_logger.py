from datetime import UTC, datetime

from core.events import MarketEvent, SignalEvent
from core.models import Contract, Greeks, Leg, Order, ValidationResult

from storage.decision_logger import DecisionLogger


def _make_signal():
    c = Contract(symbol="AAPL", sec_type="OPT", expiry="20260620", strike=150.0, right="C")
    order = Order(legs=[Leg(contract=c, quantity=1)], strategy_id="ic_1")
    return SignalEvent(
        strategy_id="ic_1",
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        direction="ENTER",
        proposed_order=order,
        reason="IV spike",
        context={"iv_rank": 0.85},
    )


def _make_market():
    return MarketEvent(
        symbol="AAPL260620C00150000",
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        bid=5.10,
        ask=5.30,
        last=5.20,
        volume=50,
        model_greeks=Greeks(
            delta=0.55, gamma=0.03, vega=0.18,
            theta=-0.05, implied_vol=0.25, underlying_price=150.15,
        ),
    )


def test_log_approved_decision(tmp_path):
    logger = DecisionLogger(tmp_path / "analytics.duckdb")
    logger.log(_make_signal(), _make_market(), ValidationResult(approved=True))
    rows = logger.query("SELECT * FROM decisions")
    assert len(rows) == 1
    assert rows[0]["strategy_id"] == "ic_1"
    assert rows[0]["risk_approved"] == True  # noqa: E712 — DuckDB BOOLEAN may be numpy.bool_
    assert rows[0]["delta"] == 0.55
    logger.close()


def test_log_rejected_decision(tmp_path):
    logger = DecisionLogger(tmp_path / "analytics.duckdb")
    logger.log(
        _make_signal(),
        _make_market(),
        ValidationResult(approved=False, reason="Delta limit exceeded"),
    )
    rows = logger.query("SELECT * FROM decisions WHERE risk_approved = false")
    assert len(rows) == 1
    assert rows[0]["risk_reason"] == "Delta limit exceeded"
    logger.close()


def test_query_empty(tmp_path):
    logger = DecisionLogger(tmp_path / "analytics.duckdb")
    rows = logger.query("SELECT * FROM decisions")
    assert rows == []
    logger.close()
