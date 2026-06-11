import asyncio
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from core.events import MarketEvent
from core.models import Contract
from core.partitions import tick_partition_path
from storage.tick_schema import TICK_SCHEMA


class TickWriter:
    def __init__(
        self,
        base_dir: str | Path,
        flush_interval: int = 1000,
        flush_interval_bytes: int = 10_000_000,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._flush_interval = flush_interval
        self._flush_interval_bytes = flush_interval_bytes
        self._buffers: dict[str, list[dict]] = {}
        self._buffer_bytes: dict[str, int] = {}
        self._flush_locks: dict[str, asyncio.Lock] = {}
        # Track auto-flush tasks so close()/flush() can await them for durability.
        self._pending_tasks: set[asyncio.Task] = set()
        self._closed = False

    def _row_bytes(self, row: dict) -> int:
        """Approximate memory size of a single row dict."""
        return sys.getsizeof(row) + sum(sys.getsizeof(v) for v in row.values())

    def write(self, event: MarketEvent, contract: Contract) -> None:
        if self._closed:
            raise RuntimeError("TickWriter is closed")
        date_str = event.timestamp.strftime("%Y-%m-%d")
        key = str(tick_partition_path(self._base_dir, contract, date_str))
        greeks = event.model_greeks
        row = {
            "timestamp": event.timestamp,
            "symbol": event.symbol,
            "bid": event.bid,
            "ask": event.ask,
            "last": event.last,
            "volume": event.volume,
            "model_delta": greeks.delta if greeks else None,
            "model_gamma": greeks.gamma if greeks else None,
            "model_vega": greeks.vega if greeks else None,
            "model_theta": greeks.theta if greeks else None,
            "model_iv": greeks.implied_vol if greeks else None,
            "model_underlying": greeks.underlying_price if greeks else None,
        }
        if key not in self._buffers:
            self._buffers[key] = []
            self._buffer_bytes[key] = 0
        self._buffers[key].append(row)
        self._buffer_bytes[key] += self._row_bytes(row)
        if (
            len(self._buffers[key]) >= self._flush_interval
            or self._buffer_bytes[key] >= self._flush_interval_bytes
        ):
            task = asyncio.get_running_loop().create_task(self._flush_partition(key))
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)

    async def flush(self) -> None:
        # Await any in-flight auto-flush tasks first so their I/O completes
        # and their buffer-clear side-effects are visible before we scan buffers.
        if self._pending_tasks:
            await asyncio.gather(*list(self._pending_tasks), return_exceptions=True)
        tasks = [
            self._flush_partition(key)
            for key in list(self._buffers)
            if self._buffers.get(key)
        ]
        if tasks:
            await asyncio.gather(*tasks)

    async def close(self) -> None:
        await self.flush()
        self._closed = True

    async def _flush_partition(self, key: str) -> None:
        rows = self._buffers.get(key)
        if not rows:
            return
        # Take the rows and clear buffer atomically before the async I/O
        # so new writes accumulate in a fresh buffer while I/O is in flight.
        rows_to_write = rows
        self._buffers[key] = []
        self._buffer_bytes[key] = 0

        if key not in self._flush_locks:
            self._flush_locks[key] = asyncio.Lock()
        lock = self._flush_locks[key]

        async with lock:
            partition_dir = Path(key)
            partition_dir.mkdir(parents=True, exist_ok=True)
            batch_num = len(list(partition_dir.glob("*.parquet")))
            filepath = partition_dir / f"{batch_num:06d}.parquet"
            table = pa.table(
                {col: [r[col] for r in rows_to_write] for col in TICK_SCHEMA.names},
                schema=TICK_SCHEMA,
            )
            await asyncio.to_thread(
                pq.write_table, table, filepath, use_dictionary=False
            )
        # Remove key if buffer is still empty after flush
        if key in self._buffers and not self._buffers[key]:
            del self._buffers[key]
            del self._buffer_bytes[key]
