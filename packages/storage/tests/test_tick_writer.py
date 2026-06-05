from datetime import UTC, datetime

import pytest

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


def test_write_stk_creates_parquet(tmp_path):
    writer = TickWriter(tmp_path, flush_interval=1)
    contract = Contract(symbol="AAPL", sec_type="STK")
    writer.write(_stk_event(), contract)
    writer.close()
    files = list(tmp_path.rglob("*.parquet"))
    assert len(files) == 1
    assert "sec_type=STK" in str(files[0])
    assert "symbol=AAPL" in str(files[0])


def test_write_opt_with_greeks(tmp_path):
    writer = TickWriter(tmp_path, flush_interval=1)
    contract = Contract(
        symbol="AAPL260620C00150000",
        sec_type="OPT",
        expiry="20260620",
        strike=150.0,
        right="C",
    )
    writer.write(_opt_event(), contract)
    writer.close()
    files = list(tmp_path.rglob("*.parquet"))
    assert len(files) == 1
    assert "sec_type=OPT" in str(files[0])
    assert "strike=150.0" in str(files[0])


def test_flush_writes_batch_file(tmp_path):
    writer = TickWriter(tmp_path, flush_interval=100)
    contract = Contract(symbol="AAPL", sec_type="STK")
    writer.write(_stk_event(), contract)
    assert len(list(tmp_path.rglob("*.parquet"))) == 0
    writer.flush()
    assert len(list(tmp_path.rglob("*.parquet"))) == 1


def test_multiple_flushes_create_multiple_files(tmp_path):
    writer = TickWriter(tmp_path, flush_interval=100)
    contract = Contract(symbol="AAPL", sec_type="STK")
    writer.write(_stk_event(), contract)
    writer.flush()
    writer.write(_stk_event(ts=datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC)), contract)
    writer.flush()
    partition_dir = list(tmp_path.rglob("date=*"))[0]
    files = sorted(partition_dir.glob("*.parquet"))
    assert len(files) == 2
    assert files[0].name == "000000.parquet"
    assert files[1].name == "000001.parquet"


def test_write_after_close_raises(tmp_path):
    writer = TickWriter(tmp_path, flush_interval=1)
    writer.close()
    with pytest.raises(RuntimeError):
        writer.write(_stk_event(), Contract(symbol="AAPL", sec_type="STK"))
