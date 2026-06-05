from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class LiveClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class SimClock:
    def __init__(self, start: datetime) -> None:
        self._current = start

    def now(self) -> datetime:
        return self._current

    def advance_to(self, ts: datetime) -> None:
        self._current = ts
