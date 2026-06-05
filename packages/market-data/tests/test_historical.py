from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from core.events import MarketEvent
from core.models import Contract, Greeks
from core.partitions import tick_partition_path
from market_data.historical import TICK_SCHEMA, HistoricalDataHandler


def _write_test_data(base_dir, contract, date_str, rows):
    partition = tick_partition_path(base_dir, contract, date_str)
    partition.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {col: [r[col] for r in rows] for col in TICK_SCHEMA.names},
        schema=TICK_SCHEMA,
    )
    pq.write_table(table, partition / "000000.parquet", use_dictionary=False)


def _stk_row(ts, last=150.15):
    return {
        "timestamp": ts,
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


def _opt_row(ts, delta=0.55):
    return {
        "timestamp": ts,
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


@pytest.mark.asyncio
async def test_subscribe_quote_yields_events(tmp_path):
    contract = Contract(symbol="AAPL", sec_type="STK")
    _write_test_data(
        tmp_path,
        contract,
        "2026-06-04",
        [
            _stk_row(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC)),
            _stk_row(datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC), last=150.35),
        ],
    )
    handler = HistoricalDataHandler(tmp_path)
    events = [e async for e in handler.subscribe_quote(contract)]
    assert len(events) == 2
    assert events[0].symbol == "AAPL"
    assert events[0].bid == 150.10


@pytest.mark.asyncio
async def test_subscribe_quote_option_with_greeks(tmp_path):
    contract = Contract(
        symbol="AAPL260620C00150000",
        sec_type="OPT",
        expiry="20260620",
        strike=150.0,
        right="C",
    )
    _write_test_data(
        tmp_path,
        contract,
        "2026-06-04",
        [_opt_row(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC))],
    )
    handler = HistoricalDataHandler(tmp_path)
    events = [e async for e in handler.subscribe_quote(contract)]
    assert len(events) == 1
    assert events[0].model_greeks is not None
    assert events[0].model_greeks.delta == 0.55


@pytest.mark.asyncio
async def test_fetch_history_returns_daily_bars(tmp_path):
    contract = Contract(symbol="AAPL", sec_type="STK")
    _write_test_data(
        tmp_path,
        contract,
        "2026-06-04",
        [
            _stk_row(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC), last=150.15),
            _stk_row(datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC), last=150.35),
        ],
    )
    handler = HistoricalDataHandler(tmp_path)
    bars = await handler.fetch_history(contract, "1 D", "1 day")
    assert len(bars) == 1
    assert bars[0].symbol == "AAPL"
    assert bars[0].open == 150.15
    assert bars[0].close == 150.35
    assert bars[0].high == 150.35
    assert bars[0].low == 150.15
    assert bars[0].volume == 200


@pytest.mark.asyncio
async def test_subscribe_quote_sorts_across_batches(tmp_path):
    contract = Contract(symbol="AAPL", sec_type="STK")
    partition = tick_partition_path(tmp_path, contract, "2026-06-04")
    partition.mkdir(parents=True, exist_ok=True)
    # Batch 0: later timestamp
    row_late = _stk_row(datetime(2026, 6, 4, 14, 35, 0, tzinfo=UTC), last=150.50)
    table0 = pa.table(
        {col: [row_late[col]] for col in TICK_SCHEMA.names},
        schema=TICK_SCHEMA,
    )
    pq.write_table(table0, partition / "000000.parquet", use_dictionary=False)
    # Batch 1: earlier timestamp
    row_early = _stk_row(datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC), last=150.10)
    table1 = pa.table(
        {col: [row_early[col]] for col in TICK_SCHEMA.names},
        schema=TICK_SCHEMA,
    )
    pq.write_table(table1, partition / "000001.parquet", use_dictionary=False)

    handler = HistoricalDataHandler(tmp_path)
    events = [e async for e in handler.subscribe_quote(contract)]
    assert len(events) == 2
    assert events[0].last == 150.10
    assert events[1].last == 150.50
    assert events[0].timestamp < events[1].timestamp


@pytest.mark.asyncio
async def test_integration_tick_writer_to_historical_handler(tmp_path):
    """Cross-package integration: TickWriter writes → HistoricalDataHandler reads."""
    from storage.tick_writer import TickWriter

    contract = Contract(symbol="AAPL", sec_type="STK")
    opt_contract = Contract(
        symbol="AAPL260620C00150000",
        sec_type="OPT",
        expiry="20260620",
        strike=150.0,
        right="C",
    )

    writer = TickWriter(tmp_path, flush_interval=1)
    stk_event = MarketEvent(
        symbol="AAPL",
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        bid=150.10,
        ask=150.20,
        last=150.15,
        volume=100,
    )
    opt_event = MarketEvent(
        symbol="AAPL260620C00150000",
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        bid=5.10,
        ask=5.30,
        last=5.20,
        volume=50,
        model_greeks=Greeks(
            delta=0.55,
            gamma=0.03,
            vega=0.18,
            theta=-0.05,
            implied_vol=0.25,
            underlying_price=150.15,
        ),
    )
    writer.write(stk_event, contract)
    writer.write(opt_event, opt_contract)
    writer.close()

    handler = HistoricalDataHandler(tmp_path)

    stk_events = [e async for e in handler.subscribe_quote(contract)]
    assert len(stk_events) == 1
    assert stk_events[0].symbol == "AAPL"
    assert stk_events[0].bid == 150.10

    opt_events = [e async for e in handler.subscribe_quote(opt_contract)]
    assert len(opt_events) == 1
    assert opt_events[0].model_greeks is not None
    assert opt_events[0].model_greeks.delta == 0.55


@pytest.mark.asyncio
async def test_fetch_history_empty(tmp_path):
    handler = HistoricalDataHandler(tmp_path)
    contract = Contract(symbol="MSFT", sec_type="STK")
    bars = await handler.fetch_history(contract, "1 D", "1 day")
    assert bars == []
