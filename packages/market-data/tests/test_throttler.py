import asyncio

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
