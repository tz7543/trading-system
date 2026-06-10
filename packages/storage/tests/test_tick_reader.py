from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq

from core.models import Contract
from core.partitions import tick_partition_path
from storage.tick_reader import TickReader
from storage.tick_schema import TICK_SCHEMA


def _write_parquet(partition_dir, rows):
    """Helper to create test Parquet files directly."""
    partition_dir.mkdir(parents=True, exist_ok=True)
    batch_num = len(list(partition_dir.glob("*.parquet")))
    table = pa.table(
        {col: [r[col] for r in rows] for col in TICK_SCHEMA.names},
        schema=TICK_SCHEMA,
    )
    pq.write_table(
        table, partition_dir / f"{batch_num:06d}.parquet", use_dictionary=False
    )


def _stk_row(ts=None, last=150.15):
    return {
        "timestamp": ts or datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        "symbol": "AAPL",
        "bid": 150.10,
        "ask": 150.20,
        "last": last,
        "volume": 100,
        "model_delta": None,
        "model_gamma": None,
        "model_vega": None,
        "model_theta": None,
        "model_iv": None,
        "model_underlying": None,
    }


def _opt_row(ts=None, delta=0.55):
    return {
        "timestamp": ts or datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        "symbol": "AAPL260620C00150000",
        "bid": 5.10,
        "ask": 5.30,
        "last": 5.20,
        "volume": 50,
        "model_delta": delta,
        "model_gamma": 0.03,
        "model_vega": 0.18,
        "model_theta": -0.05,
        "model_iv": 0.25,
        "model_underlying": 150.15,
    }


def test_read_stk_events(tmp_path):
    contract = Contract(symbol="AAPL", sec_type="STK")
    _write_parquet(tick_partition_path(tmp_path, contract, "2026-06-04"), [_stk_row()])
    reader = TickReader(tmp_path)
    events = reader.read(contract)
    assert len(events) == 1
    assert events[0].symbol == "AAPL"
    assert events[0].bid == 150.10
    assert events[0].model_greeks is None


def test_read_opt_with_greeks(tmp_path):
    contract = Contract(
        symbol="AAPL260620C00150000",
        sec_type="OPT",
        expiry="20260620",
        strike=150.0,
        right="C",
    )
    _write_parquet(tick_partition_path(tmp_path, contract, "2026-06-04"), [_opt_row()])
    reader = TickReader(tmp_path)
    events = reader.read(contract)
    assert len(events) == 1
    assert events[0].model_greeks is not None
    assert events[0].model_greeks.delta == 0.55
    assert events[0].model_greeks.implied_vol == 0.25


def test_read_multiple_batches(tmp_path):
    contract = Contract(symbol="AAPL", sec_type="STK")
    partition = tick_partition_path(tmp_path, contract, "2026-06-04")
    _write_parquet(partition, [_stk_row()])
    _write_parquet(
        partition,
        [_stk_row(ts=datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC))],
    )
    reader = TickReader(tmp_path)
    events = reader.read(contract)
    assert len(events) == 2


def test_read_sorts_by_timestamp_across_batches(tmp_path):
    contract = Contract(symbol="AAPL", sec_type="STK")
    partition = tick_partition_path(tmp_path, contract, "2026-06-04")
    _write_parquet(
        partition,
        [_stk_row(ts=datetime(2026, 6, 4, 14, 35, 0, tzinfo=UTC), last=150.50)],
    )
    _write_parquet(
        partition,
        [_stk_row(ts=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC), last=150.10)],
    )
    _write_parquet(
        partition,
        [_stk_row(ts=datetime(2026, 6, 4, 14, 32, 0, tzinfo=UTC), last=150.30)],
    )
    reader = TickReader(tmp_path)
    events = reader.read(contract)
    assert len(events) == 3
    assert events[0].last == 150.10
    assert events[1].last == 150.30
    assert events[2].last == 150.50
    assert events[0].timestamp < events[1].timestamp < events[2].timestamp


def test_read_events_carry_contract(tmp_path):
    contract = Contract(
        symbol="AAPL260620C00150000",
        sec_type="OPT",
        expiry="20260620",
        strike=150.0,
        right="C",
    )
    _write_parquet(tick_partition_path(tmp_path, contract, "2026-06-04"), [_opt_row()])
    reader = TickReader(tmp_path)
    events = reader.read(contract)
    assert len(events) == 1
    assert events[0].contract is contract


def test_read_empty_returns_empty(tmp_path):
    reader = TickReader(tmp_path)
    events = reader.read(Contract(symbol="MSFT", sec_type="STK"))
    assert events == []


def test_read_date_filter(tmp_path):
    contract = Contract(symbol="AAPL", sec_type="STK")
    _write_parquet(tick_partition_path(tmp_path, contract, "2026-06-04"), [_stk_row()])
    _write_parquet(
        tick_partition_path(tmp_path, contract, "2026-06-05"),
        [_stk_row(ts=datetime(2026, 6, 5, 14, 30, 0, tzinfo=UTC))],
    )
    reader = TickReader(tmp_path)
    events = reader.read(contract, start_date="2026-06-04", end_date="2026-06-04")
    assert len(events) == 1
    assert events[0].timestamp.day == 4
