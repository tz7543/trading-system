from datetime import UTC, datetime

from core.clock import LiveClock, SimClock


def test_live_clock_returns_utc():
    clock = LiveClock()
    now = clock.now()
    assert now.tzinfo is not None


def test_live_clock_is_recent():
    clock = LiveClock()
    now = clock.now()
    assert now.year >= 2026


def test_sim_clock_returns_initial_time():
    start = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)
    clock = SimClock(start)
    assert clock.now() == start


def test_sim_clock_advance_to():
    start = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)
    clock = SimClock(start)
    new_time = datetime(2026, 1, 2, 10, 0, tzinfo=UTC)
    clock.advance_to(new_time)
    assert clock.now() == new_time


def test_sim_clock_multiple_advances():
    t1 = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 10, 0, tzinfo=UTC)
    t3 = datetime(2026, 1, 2, 15, 59, tzinfo=UTC)
    clock = SimClock(t1)
    clock.advance_to(t2)
    clock.advance_to(t3)
    assert clock.now() == t3
