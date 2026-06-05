from pathlib import Path

from core.models import Contract
from core.partitions import tick_contract_dir, tick_partition_path


def test_stk_partition_path():
    contract = Contract(symbol="AAPL", sec_type="STK")
    path = tick_partition_path("/data", contract, "2026-06-04")
    assert path == Path("/data/ticks/sec_type=STK/symbol=AAPL/date=2026-06-04")


def test_opt_partition_path():
    contract = Contract(
        symbol="AAPL", sec_type="OPT", expiry="20260620", strike=150.0, right="C"
    )
    path = tick_partition_path("/data", contract, "2026-06-04")
    assert path == Path(
        "/data/ticks/sec_type=OPT/symbol=AAPL/expiry=20260620/strike=150.0/right=C/date=2026-06-04"
    )


def test_different_strikes_different_paths():
    c1 = Contract(symbol="AAPL", sec_type="OPT", expiry="20260620", strike=150.0, right="C")
    c2 = Contract(symbol="AAPL", sec_type="OPT", expiry="20260620", strike=155.0, right="C")
    p1 = tick_partition_path("/data", c1, "2026-06-04")
    p2 = tick_partition_path("/data", c2, "2026-06-04")
    assert p1 != p2
    assert "strike=150.0" in str(p1)
    assert "strike=155.0" in str(p2)


def test_contract_dir_excludes_date():
    contract = Contract(symbol="AAPL", sec_type="STK")
    dir_path = tick_contract_dir("/data", contract)
    assert dir_path == Path("/data/ticks/sec_type=STK/symbol=AAPL")
    assert "date=" not in str(dir_path)
