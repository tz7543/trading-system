"""Tests for async flush (H5) and memory-based batch counter (M4) in TickWriter."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch

from core.events import MarketEvent
from core.models import Contract, Greeks
from storage.tick_writer import TickWriter


def _stk_event(ts=None):
    return MarketEvent(
        symbol="AAPL",
        timestamp=ts or datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        bid=150.10,
        ask=150.20,
        last=150.15,
        volume=100,
    )


def _opt_event(ts=None, delta=0.55):
    return MarketEvent(
        symbol="AAPL260620C00150000",
        timestamp=ts or datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        bid=5.10,
        ask=5.30,
        last=5.20,
        volume=50,
        model_greeks=Greeks(
            delta=delta,
            gamma=0.03,
            vega=0.18,
            theta=-0.05,
            implied_vol=0.25,
            underlying_price=150.15,
        ),
    )


# ── H5: async flush tests ──────────────────────────────────────────────────────


async def test_flush_is_coroutine(tmp_path):
    """flush() must return a coroutine (be async), not block synchronously."""
    writer = TickWriter(tmp_path, flush_interval=100)
    contract = Contract(symbol="AAPL", sec_type="STK")
    writer.write(_stk_event(), contract)
    result = writer.flush()
    # Must be awaitable (coroutine), not None
    assert asyncio.iscoroutine(result), "flush() must be async (return a coroutine)"
    await result


async def test_flush_uses_to_thread(tmp_path):
    """pq.write_table must be called via asyncio.to_thread, not synchronously."""
    writer = TickWriter(tmp_path, flush_interval=1)
    contract = Contract(symbol="AAPL", sec_type="STK")

    to_thread_calls = []

    original_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        to_thread_calls.append(func)
        return await original_to_thread(func, *args, **kwargs)

    with patch("asyncio.to_thread", side_effect=spy_to_thread):
        writer.write(_stk_event(), contract)
        # write() triggers auto-flush when interval=1; if write is now async, we await it
        # Otherwise flush manually
        await writer.flush()

    # write_table should have been offloaded via to_thread
    import pyarrow.parquet as pq

    assert any(
        getattr(fn, "__name__", "") == "write_table" or fn is pq.write_table
        for fn in to_thread_calls
    ), f"pq.write_table must be called via asyncio.to_thread. Calls: {to_thread_calls}"


async def test_close_is_async(tmp_path):
    """close() must be async so it can await the final flush."""
    writer = TickWriter(tmp_path, flush_interval=100)
    contract = Contract(symbol="AAPL", sec_type="STK")
    writer.write(_stk_event(), contract)
    result = writer.close()
    assert asyncio.iscoroutine(result), "close() must be async"
    await result
    files = list(tmp_path.rglob("*.parquet"))
    assert len(files) == 1


async def test_concurrent_flushes_same_partition_serialize(tmp_path):
    """Two truly concurrent flush calls on the same partition must serialize (no interleaving).

    The lock must prevent start→start→end→end ordering.
    The test calls _flush_partition concurrently via asyncio.gather so that both
    coroutines are live at the same time and the lock is the only thing serializing them.
    """
    write_order = []

    contract = Contract(symbol="AAPL", sec_type="STK")
    ts1 = datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC)
    ts2 = datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC)

    original_to_thread = asyncio.to_thread

    async def slow_to_thread(func, *args, **kwargs):
        write_order.append("start")
        # Yield multiple times so the other coroutine gets a chance to run
        for _ in range(5):
            await asyncio.sleep(0)
        result = await original_to_thread(func, *args, **kwargs)
        write_order.append("end")
        return result

    writer = TickWriter(tmp_path, flush_interval=100)

    from core.partitions import tick_partition_path

    date_str = ts1.strftime("%Y-%m-%d")
    key = str(tick_partition_path(tmp_path, contract, date_str))

    # Pre-populate two separate row-sets in the writer's internal state
    # by writing rows and then manually splitting them so both flushes have data.
    writer.write(_stk_event(ts=ts1), contract)
    rows_1 = list(writer._buffers[key])
    bytes_1 = writer._buffer_bytes[key]

    writer.write(_stk_event(ts=ts2), contract)
    rows_2 = list(writer._buffers[key])
    bytes_2 = writer._buffer_bytes[key]

    # Restore buffer to empty so _flush_partition won't silently no-op
    writer._buffers[key] = []
    writer._buffer_bytes[key] = 0

    # Inject two batches directly and run _flush_partition twice concurrently.
    # We do this by temporarily setting the buffer before each coroutine
    # reads it, which means we must drive them at the coroutine level.

    async def flush_with_rows(rows, byte_size):
        writer._buffers[key] = list(rows)
        writer._buffer_bytes[key] = byte_size
        await writer._flush_partition(key)

    with patch("asyncio.to_thread", side_effect=slow_to_thread):
        # Run both flush coroutines concurrently — gather starts both before
        # either completes, giving the lock the chance to serialize them.
        await asyncio.gather(
            flush_with_rows(rows_1, bytes_1),
            flush_with_rows(rows_2, bytes_2),
        )

    # Serialized: start→end→start→end (not start→start→end→end)
    assert write_order == ["start", "end", "start", "end"], (
        f"Flushes must serialize per partition. Got order: {write_order}"
    )


async def test_different_partitions_do_not_block_each_other(tmp_path):
    """Flushes to different partition keys must not block each other."""
    contract_a = Contract(symbol="AAPL", sec_type="STK")
    contract_b = Contract(symbol="MSFT", sec_type="STK")
    ts = datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC)

    completed = []
    original_to_thread = asyncio.to_thread

    async def tracked_to_thread(func, *args, **kwargs):
        await asyncio.sleep(0)
        result = await original_to_thread(func, *args, **kwargs)
        completed.append(1)
        return result

    writer = TickWriter(tmp_path, flush_interval=100)
    writer.write(
        MarketEvent(
            symbol="AAPL",
            timestamp=ts,
            bid=150.0,
            ask=150.1,
            last=150.05,
            volume=100,
        ),
        contract_a,
    )
    writer.write(
        MarketEvent(
            symbol="MSFT",
            timestamp=ts,
            bid=300.0,
            ask=300.1,
            last=300.05,
            volume=200,
        ),
        contract_b,
    )

    with patch("asyncio.to_thread", side_effect=tracked_to_thread):
        await writer.flush()

    # Both partitions flushed
    assert len(completed) == 2


# ── M4: memory-based batch counter tests ──────────────────────────────────────


async def test_memory_counter_tracked(tmp_path):
    """TickWriter must track approximate byte count per partition key."""
    writer = TickWriter(
        tmp_path, flush_interval=999_999, flush_interval_bytes=100_000_000
    )
    contract = Contract(symbol="AAPL", sec_type="STK")
    writer.write(_stk_event(), contract)

    # After one write, some bytes should be tracked
    assert hasattr(writer, "_buffer_bytes"), (
        "TickWriter must have _buffer_bytes attribute for M4 memory tracking"
    )
    total_bytes = sum(writer._buffer_bytes.values())
    assert total_bytes > 0, "Memory counter must be > 0 after writing a row"


async def test_memory_threshold_triggers_flush(tmp_path):
    """When bytes accumulated >= flush_interval_bytes, flush must trigger."""
    # Set a very small byte threshold so a few rows trigger it
    writer = TickWriter(tmp_path, flush_interval=999_999, flush_interval_bytes=1)
    contract = Contract(symbol="AAPL", sec_type="STK")

    # Write one event; bytes >= 1 should trigger auto-flush
    writer.write(_stk_event(), contract)
    # Auto-flush is triggered during write when threshold exceeded
    # Give the async flush a chance to run
    await asyncio.sleep(0)

    # After auto-flush, buffer should be cleared
    # At minimum, _buffer_bytes counter for the key should be reset
    from core.partitions import tick_partition_path

    date_str = _stk_event().timestamp.strftime("%Y-%m-%d")
    key = str(tick_partition_path(tmp_path, contract, date_str))
    assert writer._buffer_bytes.get(key, 0) == 0, (
        "Memory counter must be reset to 0 after flush"
    )


async def test_memory_counter_resets_after_flush(tmp_path):
    """_buffer_bytes counter must be 0 for a key after explicit flush."""
    writer = TickWriter(
        tmp_path, flush_interval=999_999, flush_interval_bytes=100_000_000
    )
    contract = Contract(symbol="AAPL", sec_type="STK")

    for _ in range(5):
        writer.write(_stk_event(), contract)

    from core.partitions import tick_partition_path

    date_str = _stk_event().timestamp.strftime("%Y-%m-%d")
    key = str(tick_partition_path(tmp_path, contract, date_str))

    assert writer._buffer_bytes[key] > 0, "Should have accumulated bytes"

    await writer.flush()

    assert writer._buffer_bytes.get(key, 0) == 0, "Memory counter must be 0 after flush"


async def test_memory_counter_accumulates_across_rows(tmp_path):
    """Each appended row must increase the memory counter."""
    writer = TickWriter(
        tmp_path, flush_interval=999_999, flush_interval_bytes=100_000_000
    )
    contract = Contract(symbol="AAPL", sec_type="STK")

    from core.partitions import tick_partition_path

    date_str = _stk_event().timestamp.strftime("%Y-%m-%d")
    key = str(tick_partition_path(tmp_path, contract, date_str))

    writer.write(_stk_event(), contract)
    bytes_after_1 = writer._buffer_bytes[key]

    writer.write(_stk_event(), contract)
    bytes_after_2 = writer._buffer_bytes[key]

    assert bytes_after_2 > bytes_after_1, (
        "Memory counter must increase with each row written"
    )


# ── Durability: close() must not lose in-flight auto-flush tasks ──────────────


async def test_close_awaits_inflight_autoflush_tasks(tmp_path):
    """close() must await any in-flight auto-flush tasks so no ticks are lost.

    write() fires create_task(_flush_partition) when threshold is hit.
    If close() returns before that task completes, the Parquet file may not
    exist yet — a durability regression.  This test proves the fix.
    """
    import asyncio as _asyncio

    original_to_thread = _asyncio.to_thread
    write_started = _asyncio.Event()
    allow_write = _asyncio.Event()

    async def blocking_to_thread(func, *args, **kwargs):
        write_started.set()
        await allow_write.wait()  # block until test releases it
        return await original_to_thread(func, *args, **kwargs)

    writer = TickWriter(
        tmp_path, flush_interval=1
    )  # threshold=1: first write triggers auto-flush
    contract = Contract(symbol="AAPL", sec_type="STK")

    with patch("asyncio.to_thread", side_effect=blocking_to_thread):
        writer.write(_stk_event(), contract)

        # Wait until the auto-flush task has started the I/O
        await write_started.wait()

        # At this point Parquet write is in-flight (blocked on allow_write).
        # close() must not return until the I/O finishes.
        close_task = _asyncio.create_task(writer.close())

        # Yield a few times — close() should NOT have returned yet
        for _ in range(5):
            await _asyncio.sleep(0)

        assert not close_task.done(), (
            "close() returned before in-flight auto-flush task completed — "
            "ticks would be lost on shutdown"
        )

        # Now unblock the write and let close() complete
        allow_write.set()
        await close_task

    files = list(tmp_path.rglob("*.parquet"))
    assert len(files) == 1, (
        f"Expected 1 Parquet file after close(), found {len(files)} — ticks lost"
    )


# ── Regression: existing behaviour must still hold ────────────────────────────


async def test_write_stk_creates_parquet_async(tmp_path):
    """Existing STK write → close → file exists, partition structure preserved."""
    writer = TickWriter(tmp_path, flush_interval=1)
    contract = Contract(symbol="AAPL", sec_type="STK")
    writer.write(_stk_event(), contract)
    await writer.close()
    files = list(tmp_path.rglob("*.parquet"))
    assert len(files) == 1
    assert "sec_type=STK" in str(files[0])
    assert "symbol=AAPL" in str(files[0])


async def test_multiple_flushes_batch_numbering_async(tmp_path):
    """Batch files must still be 000000.parquet, 000001.parquet etc."""
    writer = TickWriter(tmp_path, flush_interval=100)
    contract = Contract(symbol="AAPL", sec_type="STK")
    writer.write(_stk_event(), contract)
    await writer.flush()
    writer.write(_stk_event(ts=datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC)), contract)
    await writer.flush()
    partition_dir = next(iter(tmp_path.rglob("date=*")))
    files = sorted(partition_dir.glob("*.parquet"))
    assert len(files) == 2
    assert files[0].name == "000000.parquet"
    assert files[1].name == "000001.parquet"
