import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from market_data.throttler import RequestThrottler


@pytest.mark.asyncio
async def test_acquire_release():
    throttler = RequestThrottler(max_concurrent=2, max_per_window=10)
    await throttler.acquire()
    throttler.release()


@pytest.mark.asyncio
async def test_context_manager():
    throttler = RequestThrottler(max_concurrent=2, max_per_window=10)
    async with throttler:
        pass


@pytest.mark.asyncio
async def test_concurrent_limit():
    throttler = RequestThrottler(max_concurrent=2, max_per_window=100)
    acquired = 0

    async def try_acquire():
        nonlocal acquired
        await throttler.acquire()
        acquired += 1
        await asyncio.sleep(0.1)
        throttler.release()

    tasks = [asyncio.create_task(try_acquire()) for _ in range(5)]
    await asyncio.sleep(0.01)
    assert acquired <= 2
    await asyncio.gather(*tasks)
    assert acquired == 5


@pytest.mark.asyncio
async def test_rate_window_limit():
    throttler = RequestThrottler(
        max_concurrent=50, max_per_window=3, window_seconds=0.5
    )
    for _ in range(3):
        await throttler.acquire()
        throttler.release()
    acquired = asyncio.Event()

    async def slow_acquire():
        await throttler.acquire()
        acquired.set()
        throttler.release()

    task = asyncio.create_task(slow_acquire())
    await asyncio.sleep(0.05)
    assert not acquired.is_set()
    task.cancel()
    try:  # noqa: SIM105
        await task
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# New tests: pacing interval and sleep duration verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sleep_called_when_window_full():
    """When window is exhausted, acquire() calls asyncio.sleep.

    Strategy: seed _request_times directly so no real time passes, then
    mock both time.monotonic and asyncio.sleep.  monotonic returns a fixed
    value so the window check fires; after the first sleep call, monotonic
    jumps by window_seconds so the old timestamps are purged on the next
    loop iteration, allowing acquire() to complete.
    """
    window = 1.0
    throttler = RequestThrottler(
        max_concurrent=50, max_per_window=2, window_seconds=window
    )
    # Seed two timestamps that are fully inside the window.
    base_ts = 1000.0
    throttler._request_times = [base_ts, base_ts + 0.01]

    sleep_call_count = 0

    async def fake_sleep(duration):
        nonlocal sleep_call_count
        sleep_call_count += 1

    # acquire() calls time.monotonic() once per loop iteration.
    # First call: now = base+0.05  → window still full  → sleep fires (count=1)
    # Second call: now = base+2.0  → timestamps older than window → purged → return
    mono_values = iter([base_ts + 0.05, base_ts + window + 1.0] * 5)

    with (
        patch("market_data.throttler.asyncio.sleep", side_effect=fake_sleep),
        patch("market_data.throttler.time.monotonic", side_effect=mono_values),
    ):
        await throttler.acquire()
        throttler.release()

    assert sleep_call_count == 1


@pytest.mark.asyncio
async def test_sleep_duration_matches_formula():
    """Sleep duration == window_seconds - (now - oldest) + 0.1.

    We seed _request_times with known timestamps and a fixed monotonic value
    so the formula is deterministic.
    """
    window = 1.0
    throttler = RequestThrottler(
        max_concurrent=50, max_per_window=2, window_seconds=window
    )
    base_ts = 1000.0
    oldest = base_ts
    throttler._request_times = [oldest, base_ts + 0.01]

    # now = base_ts + 0.05 when the window check runs the first time.
    now_before_sleep = base_ts + 0.05
    expected_wait = window - (now_before_sleep - oldest) + 0.1  # = 1.05

    recorded_wait = None

    async def fake_sleep(duration):
        nonlocal recorded_wait
        recorded_wait = duration

    # acquire() calls time.monotonic() once per loop iteration.
    # Iter 1: now = now_before_sleep → window full → sleep with computed wait.
    # Iter 2: now = base + window + 1.0 → timestamps expire → return.
    mono_values = iter([now_before_sleep, base_ts + window + 1.0] * 5)

    with (
        patch("market_data.throttler.asyncio.sleep", side_effect=fake_sleep),
        patch("market_data.throttler.time.monotonic", side_effect=mono_values),
    ):
        await throttler.acquire()
        throttler.release()

    assert recorded_wait is not None, "asyncio.sleep was never called"
    assert abs(recorded_wait - expected_wait) < 1e-9, (
        f"expected wait {expected_wait}, got {recorded_wait}"
    )


@pytest.mark.asyncio
async def test_no_sleep_after_window_expires():
    """After the window expires, old timestamps are purged and sleep is NOT called."""
    throttler = RequestThrottler(
        max_concurrent=50, max_per_window=2, window_seconds=0.1
    )
    await throttler.acquire()
    throttler.release()
    await throttler.acquire()
    throttler.release()

    # Wait longer than the window so all timestamps drop out.
    await asyncio.sleep(0.15)

    with patch(
        "market_data.throttler.asyncio.sleep", new_callable=AsyncMock
    ) as mock_sleep:
        await throttler.acquire()
        throttler.release()

    mock_sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_consecutive_requests_each_counted():
    """Five rapid acquires within a window of 5 should each succeed without sleeping."""
    throttler = RequestThrottler(
        max_concurrent=50, max_per_window=5, window_seconds=1.0
    )
    with patch(
        "market_data.throttler.asyncio.sleep", new_callable=AsyncMock
    ) as mock_sleep:
        for _ in range(5):
            await throttler.acquire()
            throttler.release()

    mock_sleep.assert_not_awaited()
    assert len(throttler._request_times) == 5


@pytest.mark.asyncio
async def test_sixth_request_sleeps_once():
    """The 6th request in a window of 5 must trigger exactly one sleep call.

    Seed _request_times with 5 recent timestamps, then mock time.monotonic so
    the window is still full on the first loop iteration.  After sleep, time
    jumps past the window so timestamps expire and acquire completes.
    """
    window = 1.0
    throttler = RequestThrottler(
        max_concurrent=50, max_per_window=5, window_seconds=window
    )
    base_ts = 2000.0
    throttler._request_times = [base_ts + i * 0.01 for i in range(5)]

    sleep_call_count = 0

    async def fake_sleep(_duration):
        nonlocal sleep_call_count
        sleep_call_count += 1

    # acquire() calls time.monotonic() once per loop iteration.
    # Iter 1: now = base+0.05  → window full (5 entries within 1s) → sleep.
    # Iter 2: now = base+2.0   → all timestamps expire → acquire returns.
    mono_values = iter([base_ts + 0.05, base_ts + window + 1.0] * 5)

    with (
        patch("market_data.throttler.asyncio.sleep", side_effect=fake_sleep),
        patch("market_data.throttler.time.monotonic", side_effect=mono_values),
    ):
        await throttler.acquire()
        throttler.release()

    assert sleep_call_count == 1


@pytest.mark.asyncio
async def test_active_requests_property_returns_semaphore_available_permits():
    """active_requests currently returns _semaphore._value (available permits).

    This is documented as a known semantic issue: the property name implies
    "in-use count" but the implementation returns the remaining capacity.
    This test pins the current behavior so a future refactor is intentional.
    """
    throttler = RequestThrottler(max_concurrent=3, max_per_window=100)

    # Before any acquire: _value == max_concurrent (all permits available).
    assert throttler.active_requests == 3

    await throttler.acquire()
    # After one acquire: _value == max_concurrent - 1 (one permit consumed).
    assert throttler.active_requests == 2

    throttler.release()
    assert throttler.active_requests == 3
