import asyncio
import time


class RequestThrottler:
    def __init__(
        self,
        max_concurrent: int = 50,
        max_per_window: int = 60,
        window_seconds: float = 600.0,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_per_window = max_per_window
        self._window_seconds = window_seconds
        self._request_times: list[float] = []

    async def acquire(self) -> None:
        await self._semaphore.acquire()
        while True:
            now = time.monotonic()
            self._request_times = [
                t for t in self._request_times if now - t < self._window_seconds
            ]
            if len(self._request_times) < self._max_per_window:
                self._request_times.append(now)
                return
            oldest = self._request_times[0]
            wait = self._window_seconds - (now - oldest) + 0.1
            await asyncio.sleep(wait)

    def release(self) -> None:
        self._semaphore.release()

    async def __aenter__(self) -> "RequestThrottler":
        await self.acquire()
        return self

    async def __aexit__(self, *args: object) -> None:
        self.release()

    @property
    def active_requests(self) -> int:
        return self._semaphore._value
