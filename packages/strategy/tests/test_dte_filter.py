from datetime import UTC, datetime

from strategy.dte_filter import days_to_expiry, in_dte_window


def test_days_to_expiry_basic():
    now = datetime(2026, 5, 20, 14, 30, tzinfo=UTC)
    assert days_to_expiry("20260620", now) == 31


def test_days_to_expiry_same_day():
    now = datetime(2026, 6, 20, 9, 0, tzinfo=UTC)
    assert days_to_expiry("20260620", now) == 0


def test_days_to_expiry_past():
    now = datetime(2026, 6, 25, 9, 0, tzinfo=UTC)
    assert days_to_expiry("20260620", now) == -5


def test_in_dte_window_inside():
    now = datetime(2026, 5, 20, 14, 30, tzinfo=UTC)
    assert in_dte_window("20260620", now, min_dte=30, max_dte=45) is True


def test_in_dte_window_at_boundaries():
    now_min = datetime(2026, 5, 21, 14, 30, tzinfo=UTC)  # 30 DTE
    assert in_dte_window("20260620", now_min, min_dte=30, max_dte=45) is True

    now_max = datetime(2026, 5, 6, 14, 30, tzinfo=UTC)  # 45 DTE
    assert in_dte_window("20260620", now_max, min_dte=30, max_dte=45) is True


def test_in_dte_window_outside():
    now_too_close = datetime(2026, 6, 10, 14, 30, tzinfo=UTC)  # 10 DTE
    assert in_dte_window("20260620", now_too_close, min_dte=30, max_dte=45) is False

    now_too_far = datetime(2026, 4, 20, 14, 30, tzinfo=UTC)  # 61 DTE
    assert in_dte_window("20260620", now_too_far, min_dte=30, max_dte=45) is False


def test_in_dte_window_custom_range():
    now = datetime(2026, 6, 10, 14, 30, tzinfo=UTC)  # 10 DTE
    assert in_dte_window("20260620", now, min_dte=7, max_dte=14) is True
