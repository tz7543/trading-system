# Phase 2: Data Layer (storage + market-data) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the storage and market-data packages — Parquet tick read/write, DuckDB decision log, SQLite trade store, EventBus subscriber, and historical DataHandler implementation.

**Architecture:** Partition path logic lives in `core/partitions.py` (zero external deps) so both `storage` and `market-data` import from `core` only — respecting the spec's dependency diagram (`market-data → core`, `storage → core`). Both packages do their own pyarrow I/O independently. `StorageSubscriber` auto-routes EventBus events to the appropriate stores.

**Tech Stack:** pyarrow (Parquet), duckdb, aiosqlite (SQLite WAL), pytest + pytest-asyncio + tmp_path

**Spec Resolutions:**
- Partition path logic in `core/partitions.py` — avoids `market-data → storage` dependency (spec §2.2)
- Batch files per partition (`000000.parquet`, ...) instead of single `data.parquet` — Parquet doesn't support appending
- Only `model_greeks` stored in Parquet (not all 4 Greeks types) — MVP; spec §8.3 says model_greeks is primary
- `fetch_history` MVP returns daily bars aggregated from ticks — full `duration`/`bar_size` support deferred to Phase 4
- DuckDB needs `pytz` as transitive dependency for TIMESTAMPTZ round-trips
- Parquet writes use `use_dictionary=False` — avoids schema mismatch on pyarrow dataset reads
- DecisionLogger is called directly by risk layer (Phase 3), not routed via StorageSubscriber — because the risk result isn't available from the EventBus
- TickReader and HistoricalDataHandler sort events by timestamp after reading — pyarrow doesn't guarantee order across batch files within a partition
- System/error logging (§7.1 "結構化 JSON，stdout + rotating file" via loguru) is deferred to Phase 4 (app assembly)

**Invariant:** Option `MarketEvent.symbol` must be a unique contract identifier (e.g., OCC symbol "AAPL260620C00150000"), NOT the underlying symbol "AAPL". This ensures two strikes on the same underlying land in different partitions and that `StorageSubscriber._contract_map[event.symbol]` doesn't collide. Task 6 tests this with two distinct OPT contracts.

---

## File Structure

```
packages/
  core/
    src/core/
      partitions.py                    ← NEW (tick_contract_dir, tick_partition_path)
      __init__.py                      ← MODIFY (add partition exports)
    tests/
      test_partitions.py               ← NEW (4 tests)
  storage/
    pyproject.toml                     ← MODIFY (add pyarrow, duckdb, aiosqlite, pytz deps)
    src/storage/
      __init__.py                      ← MODIFY (exports)
      tick_schema.py                   ← NEW (shared Parquet schema)
      tick_writer.py                   ← NEW
      tick_reader.py                   ← NEW
      decision_logger.py               ← NEW
      trade_store.py                   ← NEW
      subscriber.py                    ← NEW
    tests/
      test_tick_writer.py              ← NEW (5 tests)
      test_tick_reader.py              ← NEW (6 tests)
      test_decision_logger.py          ← NEW (3 tests)
      test_trade_store.py              ← NEW (4 tests)
      test_subscriber.py              ← NEW (5 tests)
  market-data/
    pyproject.toml                     ← MODIFY (add pyarrow dep)
    src/market_data/
      __init__.py                      ← MODIFY (exports)
      historical.py                    ← NEW
    tests/
      test_historical.py               ← NEW (6 tests)
```

---

### Task 1: Partition Path Utility (`core/partitions.py`)

**Files:**
- Create: `packages/core/src/core/partitions.py`
- Modify: `packages/core/src/core/__init__.py`
- Test: `packages/core/tests/test_partitions.py`

- [ ] **Step 1: Write failing tests**

Create `packages/core/tests/test_partitions.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/core/tests/test_partitions.py -v
```

Expected: FAIL with `ImportError: cannot import name 'tick_contract_dir'`

- [ ] **Step 3: Implement partitions module**

Create `packages/core/src/core/partitions.py`:

```python
from pathlib import Path

from core.models import Contract


def tick_contract_dir(base_dir: str | Path, contract: Contract) -> Path:
    path = (
        Path(base_dir)
        / "ticks"
        / f"sec_type={contract.sec_type}"
        / f"symbol={contract.symbol}"
    )
    if contract.sec_type == "OPT":
        path = (
            path
            / f"expiry={contract.expiry}"
            / f"strike={contract.strike}"
            / f"right={contract.right}"
        )
    return path


def tick_partition_path(
    base_dir: str | Path, contract: Contract, date: str
) -> Path:
    return tick_contract_dir(base_dir, contract) / f"date={date}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/core/tests/test_partitions.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Update core exports**

Add to `packages/core/src/core/__init__.py`:

```python
from core.partitions import tick_contract_dir, tick_partition_path
```

Add `"tick_contract_dir"` and `"tick_partition_path"` to `__all__`.

- [ ] **Step 6: Run full core test suite**

```bash
uv run pytest packages/core/tests/ -v
```

Expected: all 33 tests PASS (29 existing + 4 new).

- [ ] **Step 7: Commit**

```bash
git add packages/core/
git commit -m "feat(core): add tick partition path utilities for Hive-partitioned storage"
```

---

### Task 2: Storage Package Setup + TickWriter

**Files:**
- Modify: `packages/storage/pyproject.toml`
- Create: `packages/storage/src/storage/tick_schema.py`
- Create: `packages/storage/src/storage/tick_writer.py`
- Test: `packages/storage/tests/test_tick_writer.py`

- [ ] **Step 1: Update storage dependencies**

Replace `packages/storage/pyproject.toml`:

```toml
[project]
name = "storage"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "trading-core",
    "pyarrow>=18.0",
    "duckdb>=1.0",
    "aiosqlite>=0.20",
    "pytz>=2024.1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/storage"]

[tool.uv.sources]
trading-core = { workspace = true }
```

Run `uv sync` and verify it succeeds.

- [ ] **Step 2: Create shared Parquet schema**

Create `packages/storage/src/storage/tick_schema.py`:

```python
import pyarrow as pa

TICK_SCHEMA = pa.schema([
    ("timestamp", pa.timestamp("us", tz="UTC")),
    ("symbol", pa.string()),
    ("bid", pa.float64()),
    ("ask", pa.float64()),
    ("last", pa.float64()),
    ("volume", pa.int64()),
    ("model_delta", pa.float64()),
    ("model_gamma", pa.float64()),
    ("model_vega", pa.float64()),
    ("model_theta", pa.float64()),
    ("model_iv", pa.float64()),
    ("model_underlying", pa.float64()),
])
```

- [ ] **Step 3: Write failing tests**

Create `packages/storage/tests/test_tick_writer.py`:

```python
import pytest
from datetime import UTC, datetime

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
    writer.write(
        _stk_event(ts=datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC)), contract
    )
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
        writer.write(
            _stk_event(), Contract(symbol="AAPL", sec_type="STK")
        )
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
uv run pytest packages/storage/tests/test_tick_writer.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'storage.tick_writer'`

- [ ] **Step 5: Implement TickWriter**

Create `packages/storage/src/storage/tick_writer.py`:

```python
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from core.events import MarketEvent
from core.models import Contract
from core.partitions import tick_partition_path

from storage.tick_schema import TICK_SCHEMA


class TickWriter:
    def __init__(self, base_dir: str | Path, flush_interval: int = 1000) -> None:
        self._base_dir = Path(base_dir)
        self._flush_interval = flush_interval
        self._buffers: dict[str, list[dict]] = {}
        self._closed = False

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
        self._buffers[key].append(row)
        if len(self._buffers[key]) >= self._flush_interval:
            self._flush_partition(key)

    def flush(self) -> None:
        for key in list(self._buffers):
            if self._buffers[key]:
                self._flush_partition(key)

    def close(self) -> None:
        self.flush()
        self._closed = True

    def _flush_partition(self, key: str) -> None:
        rows = self._buffers.pop(key, [])
        if not rows:
            return
        partition_dir = Path(key)
        partition_dir.mkdir(parents=True, exist_ok=True)
        batch_num = len(list(partition_dir.glob("*.parquet")))
        filepath = partition_dir / f"{batch_num:06d}.parquet"
        table = pa.table(
            {col: [r[col] for r in rows] for col in TICK_SCHEMA.names},
            schema=TICK_SCHEMA,
        )
        pq.write_table(table, filepath, use_dictionary=False)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run pytest packages/storage/tests/test_tick_writer.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/storage/
git commit -m "feat(storage): add TickWriter with Hive-partitioned Parquet batch writes"
```

---

### Task 3: TickReader

**Files:**
- Create: `packages/storage/src/storage/tick_reader.py`
- Test: `packages/storage/tests/test_tick_reader.py`

- [ ] **Step 1: Write failing tests**

Create `packages/storage/tests/test_tick_reader.py`:

```python
from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq

from core.events import MarketEvent
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
    _write_parquet(
        tick_partition_path(tmp_path, contract, "2026-06-04"), [_stk_row()]
    )
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
    _write_parquet(
        tick_partition_path(tmp_path, contract, "2026-06-04"), [_opt_row()]
    )
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


def test_read_empty_returns_empty(tmp_path):
    reader = TickReader(tmp_path)
    events = reader.read(Contract(symbol="MSFT", sec_type="STK"))
    assert events == []


def test_read_date_filter(tmp_path):
    contract = Contract(symbol="AAPL", sec_type="STK")
    _write_parquet(
        tick_partition_path(tmp_path, contract, "2026-06-04"), [_stk_row()]
    )
    _write_parquet(
        tick_partition_path(tmp_path, contract, "2026-06-05"),
        [_stk_row(ts=datetime(2026, 6, 5, 14, 30, 0, tzinfo=UTC))],
    )
    reader = TickReader(tmp_path)
    events = reader.read(contract, start_date="2026-06-04", end_date="2026-06-04")
    assert len(events) == 1
    assert events[0].timestamp.day == 4
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/storage/tests/test_tick_reader.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'storage.tick_reader'`

- [ ] **Step 3: Implement TickReader**

Create `packages/storage/src/storage/tick_reader.py`:

```python
from datetime import datetime, timedelta
from pathlib import Path

import pyarrow.dataset as ds

from core.events import MarketEvent
from core.models import Contract, Greeks
from core.partitions import tick_contract_dir, tick_partition_path

from storage.tick_schema import TICK_SCHEMA


class TickReader:
    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)

    def read(
        self,
        contract: Contract,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[MarketEvent]:
        if start_date and end_date:
            dates = self._date_range(start_date, end_date)
        elif start_date:
            dates = [start_date]
        else:
            dates = self._discover_dates(contract)
        events: list[MarketEvent] = []
        for date_str in sorted(dates):
            partition_dir = tick_partition_path(self._base_dir, contract, date_str)
            if not partition_dir.exists():
                continue
            dataset = ds.dataset(
                str(partition_dir), format="parquet", schema=TICK_SCHEMA
            )
            table = dataset.to_table()
            events.extend(_table_to_events(table))
        events.sort(key=lambda e: e.timestamp)
        return events

    def _discover_dates(self, contract: Contract) -> list[str]:
        base = tick_contract_dir(self._base_dir, contract)
        if not base.exists():
            return []
        return [
            d.name.removeprefix("date=")
            for d in base.iterdir()
            if d.is_dir() and d.name.startswith("date=")
        ]

    @staticmethod
    def _date_range(start: str, end: str) -> list[str]:
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        dates = []
        current = start_dt
        while current <= end_dt:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
        return dates


def _table_to_events(table) -> list[MarketEvent]:
    rows = table.to_pydict()
    events = []
    for i in range(len(rows["timestamp"])):
        greeks = None
        if rows["model_delta"][i] is not None:
            greeks = Greeks(
                delta=rows["model_delta"][i],
                gamma=rows["model_gamma"][i],
                vega=rows["model_vega"][i],
                theta=rows["model_theta"][i],
                implied_vol=rows["model_iv"][i],
                underlying_price=rows["model_underlying"][i],
            )
        events.append(
            MarketEvent(
                symbol=rows["symbol"][i],
                timestamp=rows["timestamp"][i],
                bid=rows["bid"][i],
                ask=rows["ask"][i],
                last=rows["last"][i],
                volume=rows["volume"][i],
                model_greeks=greeks,
            )
        )
    return events
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/storage/tests/test_tick_reader.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/storage/src/storage/tick_reader.py packages/storage/tests/test_tick_reader.py
git commit -m "feat(storage): add TickReader for Parquet Hive-partitioned reads"
```

---

### Task 4: DecisionLogger (DuckDB)

**Files:**
- Create: `packages/storage/src/storage/decision_logger.py`
- Test: `packages/storage/tests/test_decision_logger.py`

- [ ] **Step 1: Write failing tests**

Create `packages/storage/tests/test_decision_logger.py`:

```python
from datetime import UTC, datetime

from core.events import MarketEvent, SignalEvent
from core.models import Contract, Greeks, Leg, Order, ValidationResult

from storage.decision_logger import DecisionLogger


def _make_signal():
    c = Contract(symbol="AAPL", sec_type="OPT", expiry="20260620", strike=150.0, right="C")
    order = Order(legs=[Leg(contract=c, quantity=1)], strategy_id="ic_1")
    return SignalEvent(
        strategy_id="ic_1",
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        direction="ENTER",
        proposed_order=order,
        reason="IV spike",
        context={"iv_rank": 0.85},
    )


def _make_market():
    return MarketEvent(
        symbol="AAPL260620C00150000",
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        bid=5.10,
        ask=5.30,
        last=5.20,
        volume=50,
        model_greeks=Greeks(
            delta=0.55, gamma=0.03, vega=0.18,
            theta=-0.05, implied_vol=0.25, underlying_price=150.15,
        ),
    )


def test_log_approved_decision(tmp_path):
    logger = DecisionLogger(tmp_path / "analytics.duckdb")
    logger.log(_make_signal(), _make_market(), ValidationResult(approved=True))
    rows = logger.query("SELECT * FROM decisions")
    assert len(rows) == 1
    assert rows[0]["strategy_id"] == "ic_1"
    assert rows[0]["risk_approved"] == True  # noqa: E712 — DuckDB BOOLEAN may be numpy.bool_
    assert rows[0]["delta"] == 0.55
    logger.close()


def test_log_rejected_decision(tmp_path):
    logger = DecisionLogger(tmp_path / "analytics.duckdb")
    logger.log(
        _make_signal(),
        _make_market(),
        ValidationResult(approved=False, reason="Delta limit exceeded"),
    )
    rows = logger.query("SELECT * FROM decisions WHERE risk_approved = false")
    assert len(rows) == 1
    assert rows[0]["risk_reason"] == "Delta limit exceeded"
    logger.close()


def test_query_empty(tmp_path):
    logger = DecisionLogger(tmp_path / "analytics.duckdb")
    rows = logger.query("SELECT * FROM decisions")
    assert rows == []
    logger.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/storage/tests/test_decision_logger.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement DecisionLogger**

Create `packages/storage/src/storage/decision_logger.py`:

```python
import json
from pathlib import Path

import duckdb

from core.events import MarketEvent, SignalEvent
from core.models import Order, ValidationResult


class DecisionLogger:
    def __init__(self, db_path: str | Path) -> None:
        self._db = duckdb.connect(str(db_path))
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                timestamp TIMESTAMPTZ,
                strategy_id TEXT,
                symbol TEXT,
                bid DOUBLE,
                ask DOUBLE,
                last_price DOUBLE,
                iv DOUBLE,
                delta DOUBLE,
                underlying_price DOUBLE,
                direction TEXT,
                reason TEXT,
                context_json TEXT,
                order_json TEXT,
                risk_approved BOOLEAN,
                risk_reason TEXT
            )
        """)

    def log(
        self,
        signal: SignalEvent,
        market: MarketEvent,
        result: ValidationResult,
    ) -> None:
        greeks = market.model_greeks
        self._db.execute(
            "INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                signal.timestamp,
                signal.strategy_id,
                market.symbol,
                market.bid,
                market.ask,
                market.last,
                greeks.implied_vol if greeks else None,
                greeks.delta if greeks else None,
                greeks.underlying_price if greeks else None,
                signal.direction,
                signal.reason,
                json.dumps(signal.context),
                json.dumps(_order_to_dict(signal.proposed_order)),
                result.approved,
                result.reason,
            ],
        )

    def query(self, sql: str) -> list[dict]:
        result = self._db.execute(sql)
        if result.description is None:
            return []
        cols = [d[0] for d in result.description]
        return [dict(zip(cols, row)) for row in result.fetchall()]

    def close(self) -> None:
        self._db.close()


def _order_to_dict(order: Order) -> dict:
    return {
        "strategy_id": order.strategy_id,
        "order_type": order.order_type,
        "limit_price": order.limit_price,
        "time_in_force": order.time_in_force,
        "legs": [
            {
                "symbol": leg.contract.symbol,
                "sec_type": leg.contract.sec_type,
                "expiry": leg.contract.expiry,
                "strike": leg.contract.strike,
                "right": leg.contract.right,
                "quantity": leg.quantity,
            }
            for leg in order.legs
        ],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/storage/tests/test_decision_logger.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/storage/src/storage/decision_logger.py packages/storage/tests/test_decision_logger.py
git commit -m "feat(storage): add DecisionLogger with DuckDB for signal/risk snapshots"
```

---

### Task 5: TradeStore (SQLite WAL)

**Files:**
- Create: `packages/storage/src/storage/trade_store.py`
- Test: `packages/storage/tests/test_trade_store.py`

- [ ] **Step 1: Write failing tests**

Create `packages/storage/tests/test_trade_store.py`:

```python
import pytest
from datetime import UTC, datetime

from core.events import FillEvent, OrderEvent
from core.models import Contract, Leg, Order

from storage.trade_store import TradeStore


def _make_order_event():
    c = Contract(symbol="AAPL", sec_type="STK")
    order = Order(legs=[Leg(contract=c, quantity=100)], strategy_id="momentum_1")
    return OrderEvent(
        order=order,
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        approved_by="PreTradeValidator",
    )


def _make_fill_event():
    c = Contract(symbol="AAPL", sec_type="STK")
    leg = Leg(contract=c, quantity=100, entry_price=150.0)
    return FillEvent(
        order_id="ORD-001",
        legs_filled=[leg],
        timestamp=datetime(2026, 6, 4, 14, 30, 1, tzinfo=UTC),
        commission=1.0,
    )


@pytest.mark.asyncio
async def test_log_order(tmp_path):
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    order_id = await store.log_order(_make_order_event())
    assert order_id is not None
    rows = await store.query_orders()
    assert len(rows) == 1
    assert rows[0]["strategy_id"] == "momentum_1"
    assert rows[0]["approved_by"] == "PreTradeValidator"
    await store.close()


@pytest.mark.asyncio
async def test_log_fill(tmp_path):
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    await store.log_fill(_make_fill_event())
    rows = await store.query_fills()
    assert len(rows) == 1
    assert rows[0]["order_id"] == "ORD-001"
    assert rows[0]["commission"] == 1.0
    await store.close()


@pytest.mark.asyncio
async def test_query_orders_by_strategy(tmp_path):
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    await store.log_order(_make_order_event())
    rows = await store.query_orders(strategy_id="momentum_1")
    assert len(rows) == 1
    empty = await store.query_orders(strategy_id="nonexistent")
    assert len(empty) == 0
    await store.close()


@pytest.mark.asyncio
async def test_query_fills_by_order_id(tmp_path):
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    await store.log_fill(_make_fill_event())
    rows = await store.query_fills(order_id="ORD-001")
    assert len(rows) == 1
    empty = await store.query_fills(order_id="ORD-999")
    assert len(empty) == 0
    await store.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/storage/tests/test_trade_store.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement TradeStore**

Create `packages/storage/src/storage/trade_store.py`:

```python
import json
import uuid
from pathlib import Path

import aiosqlite

from core.events import FillEvent, OrderEvent


class TradeStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                strategy_id TEXT NOT NULL,
                approved_by TEXT NOT NULL,
                order_type TEXT NOT NULL,
                limit_price REAL,
                time_in_force TEXT NOT NULL,
                legs_json TEXT NOT NULL
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                commission REAL NOT NULL,
                legs_json TEXT NOT NULL
            )
        """)
        await self._db.commit()

    async def log_order(self, event: OrderEvent) -> str:
        order_id = str(uuid.uuid4())
        legs = [
            {
                "symbol": leg.contract.symbol,
                "sec_type": leg.contract.sec_type,
                "expiry": leg.contract.expiry,
                "strike": leg.contract.strike,
                "right": leg.contract.right,
                "quantity": leg.quantity,
            }
            for leg in event.order.legs
        ]
        await self._db.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order_id,
                event.timestamp.isoformat(),
                event.order.strategy_id,
                event.approved_by,
                event.order.order_type,
                event.order.limit_price,
                event.order.time_in_force,
                json.dumps(legs),
            ),
        )
        await self._db.commit()
        return order_id

    async def log_fill(self, event: FillEvent) -> None:
        legs = [
            {
                "symbol": leg.contract.symbol,
                "sec_type": leg.contract.sec_type,
                "quantity": leg.quantity,
                "entry_price": leg.entry_price,
            }
            for leg in event.legs_filled
        ]
        await self._db.execute(
            "INSERT INTO fills (order_id, timestamp, commission, legs_json) VALUES (?, ?, ?, ?)",
            (
                event.order_id,
                event.timestamp.isoformat(),
                event.commission,
                json.dumps(legs),
            ),
        )
        await self._db.commit()

    async def query_orders(self, strategy_id: str | None = None) -> list[dict]:
        if strategy_id:
            cursor = await self._db.execute(
                "SELECT * FROM orders WHERE strategy_id = ?", (strategy_id,)
            )
        else:
            cursor = await self._db.execute("SELECT * FROM orders")
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def query_fills(self, order_id: str | None = None) -> list[dict]:
        if order_id:
            cursor = await self._db.execute(
                "SELECT * FROM fills WHERE order_id = ?", (order_id,)
            )
        else:
            cursor = await self._db.execute("SELECT * FROM fills")
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def close(self) -> None:
        if self._db:
            await self._db.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest packages/storage/tests/test_trade_store.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/storage/src/storage/trade_store.py packages/storage/tests/test_trade_store.py
git commit -m "feat(storage): add TradeStore with SQLite WAL for orders and fills"
```

---

### Task 6: StorageSubscriber + Storage Exports

**Files:**
- Create: `packages/storage/src/storage/subscriber.py`
- Modify: `packages/storage/src/storage/__init__.py`
- Test: `packages/storage/tests/test_subscriber.py`

- [ ] **Step 1: Write failing tests**

Create `packages/storage/tests/test_subscriber.py`:

```python
import pytest
from datetime import UTC, datetime

from core.bus import EventBus
from core.events import FillEvent, MarketEvent, OrderEvent
from core.models import Contract, Leg, Order

from storage.subscriber import StorageSubscriber
from storage.tick_writer import TickWriter
from storage.trade_store import TradeStore


def _stk_contract():
    return Contract(symbol="AAPL", sec_type="STK")


def _stk_event():
    return MarketEvent(
        symbol="AAPL",
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        bid=150.10,
        ask=150.20,
        last=150.15,
        volume=100,
    )


def _order_event():
    c = Contract(symbol="AAPL", sec_type="STK")
    order = Order(legs=[Leg(contract=c, quantity=100)], strategy_id="test")
    return OrderEvent(
        order=order,
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        approved_by="PreTradeValidator",
    )


def _fill_event():
    c = Contract(symbol="AAPL", sec_type="STK")
    return FillEvent(
        order_id="ORD-001",
        legs_filled=[Leg(contract=c, quantity=100, entry_price=150.0)],
        timestamp=datetime(2026, 6, 4, 14, 30, 1, tzinfo=UTC),
        commission=1.0,
    )


@pytest.mark.asyncio
async def test_routes_market_event_to_writer(tmp_path):
    bus = EventBus()
    writer = TickWriter(tmp_path / "data", flush_interval=1)
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    sub = StorageSubscriber(bus, writer, store)
    sub.register_contract("AAPL", _stk_contract())
    await sub.start()
    await bus.publish(_stk_event())
    await sub.stop()
    files = list((tmp_path / "data").rglob("*.parquet"))
    assert len(files) == 1


@pytest.mark.asyncio
async def test_caches_latest_market_event(tmp_path):
    bus = EventBus()
    writer = TickWriter(tmp_path / "data", flush_interval=100)
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    sub = StorageSubscriber(bus, writer, store)
    sub.register_contract("AAPL", _stk_contract())
    await sub.start()
    await bus.publish(_stk_event())
    assert sub.last_market("AAPL") is not None
    assert sub.last_market("AAPL").bid == 150.10
    await sub.stop()


@pytest.mark.asyncio
async def test_routes_order_event(tmp_path):
    bus = EventBus()
    writer = TickWriter(tmp_path / "data", flush_interval=100)
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    sub = StorageSubscriber(bus, writer, store)
    await sub.start()
    await bus.publish(_order_event())
    rows = await store.query_orders()
    assert len(rows) == 1
    await sub.stop()


@pytest.mark.asyncio
async def test_routes_fill_event(tmp_path):
    bus = EventBus()
    writer = TickWriter(tmp_path / "data", flush_interval=100)
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    sub = StorageSubscriber(bus, writer, store)
    await sub.start()
    await bus.publish(_fill_event())
    rows = await store.query_fills()
    assert len(rows) == 1
    assert rows[0]["order_id"] == "ORD-001"
    await sub.stop()


@pytest.mark.asyncio
async def test_two_opt_contracts_write_to_separate_partitions(tmp_path):
    bus = EventBus()
    writer = TickWriter(tmp_path / "data", flush_interval=1)
    store = TradeStore(tmp_path / "trades.db")
    await store.init()
    sub = StorageSubscriber(bus, writer, store)

    c150 = Contract(
        symbol="AAPL260620C00150000",
        sec_type="OPT",
        expiry="20260620",
        strike=150.0,
        right="C",
    )
    c155 = Contract(
        symbol="AAPL260620C00155000",
        sec_type="OPT",
        expiry="20260620",
        strike=155.0,
        right="C",
    )
    sub.register_contract("AAPL260620C00150000", c150)
    sub.register_contract("AAPL260620C00155000", c155)
    await sub.start()

    await bus.publish(
        MarketEvent(
            symbol="AAPL260620C00150000",
            timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
            bid=5.10, ask=5.30, last=5.20, volume=50,
        )
    )
    await bus.publish(
        MarketEvent(
            symbol="AAPL260620C00155000",
            timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
            bid=3.10, ask=3.30, last=3.20, volume=30,
        )
    )
    await sub.stop()

    files = list((tmp_path / "data").rglob("*.parquet"))
    assert len(files) == 2
    paths_str = [str(f) for f in files]
    assert any("strike=150.0" in p for p in paths_str)
    assert any("strike=155.0" in p for p in paths_str)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest packages/storage/tests/test_subscriber.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement StorageSubscriber**

Create `packages/storage/src/storage/subscriber.py`:

```python
from core.bus import EventBus
from core.events import FillEvent, MarketEvent, OrderEvent
from core.models import Contract

from storage.tick_writer import TickWriter
from storage.trade_store import TradeStore


class StorageSubscriber:
    def __init__(
        self,
        bus: EventBus,
        tick_writer: TickWriter,
        trade_store: TradeStore,
    ) -> None:
        self._bus = bus
        self._tick_writer = tick_writer
        self._trade_store = trade_store
        self._contract_map: dict[str, Contract] = {}
        self._last_market: dict[str, MarketEvent] = {}

    def register_contract(self, symbol: str, contract: Contract) -> None:
        self._contract_map[symbol] = contract

    def last_market(self, symbol: str) -> MarketEvent | None:
        return self._last_market.get(symbol)

    async def start(self) -> None:
        self._bus.subscribe(MarketEvent, self._on_market)
        self._bus.subscribe(OrderEvent, self._on_order)
        self._bus.subscribe(FillEvent, self._on_fill)

    async def stop(self) -> None:
        self._bus.unsubscribe(MarketEvent, self._on_market)
        self._bus.unsubscribe(OrderEvent, self._on_order)
        self._bus.unsubscribe(FillEvent, self._on_fill)
        self._tick_writer.close()
        await self._trade_store.close()

    async def _on_market(self, event: MarketEvent) -> None:
        self._last_market[event.symbol] = event
        contract = self._contract_map.get(event.symbol)
        if contract:
            self._tick_writer.write(event, contract)

    async def _on_order(self, event: OrderEvent) -> None:
        await self._trade_store.log_order(event)

    async def _on_fill(self, event: FillEvent) -> None:
        await self._trade_store.log_fill(event)
```

- [ ] **Step 4: Update storage package exports**

Replace `packages/storage/src/storage/__init__.py`:

```python
from storage.decision_logger import DecisionLogger
from storage.subscriber import StorageSubscriber
from storage.tick_reader import TickReader
from storage.tick_writer import TickWriter
from storage.trade_store import TradeStore

__all__ = [
    "DecisionLogger",
    "StorageSubscriber",
    "TickReader",
    "TickWriter",
    "TradeStore",
]
```

- [ ] **Step 5: Run all storage tests**

```bash
uv run pytest packages/storage/tests/ -v
```

Expected: all 23 tests PASS (5 writer + 6 reader + 3 decision + 4 trade + 5 subscriber).

- [ ] **Step 6: Run linter**

```bash
uv run ruff check packages/storage/
uv run ruff format --check packages/storage/
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add packages/storage/
git commit -m "feat(storage): add StorageSubscriber and set up package exports"
```

---

### Task 7: HistoricalDataHandler (`market-data`)

**Files:**
- Modify: `packages/market-data/pyproject.toml`
- Create: `packages/market-data/src/market_data/historical.py`
- Modify: `packages/market-data/src/market_data/__init__.py`
- Test: `packages/market-data/tests/test_historical.py`

- [ ] **Step 1: Update market-data dependencies**

Replace `packages/market-data/pyproject.toml`:

```toml
[project]
name = "market-data"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "trading-core",
    "pyarrow>=18.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/market_data"]

[tool.uv.sources]
trading-core = { workspace = true }
```

Run `uv sync` and verify it succeeds.

- [ ] **Step 2: Write failing tests**

Create `packages/market-data/tests/test_historical.py`:

```python
import pytest
from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq

from core.events import MarketEvent
from core.models import Contract, Greeks
from core.partitions import tick_partition_path

from market_data.historical import HistoricalDataHandler, TICK_SCHEMA


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
        bid=150.10, ask=150.20, last=150.15, volume=100,
    )
    opt_event = MarketEvent(
        symbol="AAPL260620C00150000",
        timestamp=datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC),
        bid=5.10, ask=5.30, last=5.20, volume=50,
        model_greeks=Greeks(
            delta=0.55, gamma=0.03, vega=0.18,
            theta=-0.05, implied_vol=0.25, underlying_price=150.15,
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
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest packages/market-data/tests/test_historical.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement HistoricalDataHandler**

Create `packages/market-data/src/market_data/historical.py`:

```python
from collections.abc import AsyncIterator
from pathlib import Path

import pyarrow as pa
import pyarrow.dataset as ds

from core.data_handler import DataHandler
from core.events import MarketEvent
from core.models import Bar, Contract, Greeks
from core.partitions import tick_contract_dir, tick_partition_path

TICK_SCHEMA = pa.schema([
    ("timestamp", pa.timestamp("us", tz="UTC")),
    ("symbol", pa.string()),
    ("bid", pa.float64()),
    ("ask", pa.float64()),
    ("last", pa.float64()),
    ("volume", pa.int64()),
    ("model_delta", pa.float64()),
    ("model_gamma", pa.float64()),
    ("model_vega", pa.float64()),
    ("model_theta", pa.float64()),
    ("model_iv", pa.float64()),
    ("model_underlying", pa.float64()),
])


class HistoricalDataHandler(DataHandler):
    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)

    async def subscribe_quote(
        self, contract: Contract
    ) -> AsyncIterator[MarketEvent]:
        contract_dir = tick_contract_dir(self._base_dir, contract)
        if not contract_dir.exists():
            return
        dates = sorted(
            d.name.removeprefix("date=")
            for d in contract_dir.iterdir()
            if d.is_dir() and d.name.startswith("date=")
        )
        for date_str in dates:
            partition_dir = tick_partition_path(
                self._base_dir, contract, date_str
            )
            dataset = ds.dataset(
                str(partition_dir), format="parquet", schema=TICK_SCHEMA
            )
            events = _table_to_events(dataset.to_table())
            events.sort(key=lambda e: e.timestamp)
            for event in events:
                yield event

    async def fetch_history(
        self, contract: Contract, duration: str, bar_size: str
    ) -> list[Bar]:
        events: list[MarketEvent] = []
        async for event in self.subscribe_quote(contract):
            events.append(event)
        if not events:
            return []
        by_date: dict[str, list[MarketEvent]] = {}
        for e in events:
            date_key = e.timestamp.strftime("%Y-%m-%d")
            by_date.setdefault(date_key, []).append(e)
        bars = []
        for date_key in sorted(by_date):
            day = by_date[date_key]
            bars.append(
                Bar(
                    timestamp=day[0].timestamp,
                    symbol=contract.symbol,
                    open=day[0].last,
                    high=max(e.last for e in day),
                    low=min(e.last for e in day),
                    close=day[-1].last,
                    volume=sum(e.volume for e in day),
                )
            )
        return bars


def _table_to_events(table) -> list[MarketEvent]:
    rows = table.to_pydict()
    events = []
    for i in range(len(rows["timestamp"])):
        greeks = None
        if rows["model_delta"][i] is not None:
            greeks = Greeks(
                delta=rows["model_delta"][i],
                gamma=rows["model_gamma"][i],
                vega=rows["model_vega"][i],
                theta=rows["model_theta"][i],
                implied_vol=rows["model_iv"][i],
                underlying_price=rows["model_underlying"][i],
            )
        events.append(
            MarketEvent(
                symbol=rows["symbol"][i],
                timestamp=rows["timestamp"][i],
                bid=rows["bid"][i],
                ask=rows["ask"][i],
                last=rows["last"][i],
                volume=rows["volume"][i],
                model_greeks=greeks,
            )
        )
    return events
```

- [ ] **Step 5: Update market-data exports**

Replace `packages/market-data/src/market_data/__init__.py`:

```python
from market_data.historical import HistoricalDataHandler

__all__ = ["HistoricalDataHandler"]
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run pytest packages/market-data/tests/test_historical.py -v
```

Expected: all 6 tests PASS.

Note: `test_integration_tick_writer_to_historical_handler` imports `storage.tick_writer` — this works because `storage` is installed in the workspace. The integration test intentionally crosses package boundaries to verify schema compatibility.

- [ ] **Step 7: Run full Phase 2 test suite + linter**

```bash
uv run pytest packages/core/tests/ packages/storage/tests/ packages/market-data/tests/ -v
```

Expected: all 62 tests PASS (33 core + 23 storage + 6 market-data).

```bash
uv run ruff check packages/core/ packages/storage/ packages/market-data/
uv run ruff format --check packages/core/ packages/storage/ packages/market-data/
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add packages/market-data/
git commit -m "feat(market-data): add HistoricalDataHandler reading Parquet for backtest"
```

---

## Phase 3–4 Roadmap

### Phase 3: Trading Logic (strategy + risk)

**Depends on:** Phase 1 (core) complete. Phase 2 NOT required — can run in parallel.

| Task | Package | Key Deliverable |
|------|---------|-----------------|
| 3.1 | strategy | `BaseStrategy` — `on_market_event()`, `signal()`, `on_fill()` |
| 3.2 | strategy | `MultiLegOrder` — factory methods: `iron_condor()`, `bull_call_spread()`, `covered_call()`, `straddle()` |
| 3.3 | strategy | `GreeksCalculator.composite(legs)` — multi-leg Greeks aggregation |
| 3.4 | risk | `PreTradeValidator` — sync validation (position limits, Delta/Vega, spread check) |
| 3.5 | risk | `RealTimeMonitor` — async Greeks drift + drawdown monitoring |
| 3.6 | risk | `CircuitBreaker` — emergency stop + flatten all positions |

### Phase 4: Integration (backtest + live path + assembly)

**Depends on:** Phase 2 + Phase 3 complete.

| Task | Package | Key Deliverable |
|------|---------|-----------------|
| 4.1 | backtest | `SimulatedExecutor` — fill-at-next-bar-open, commission model |
| 4.2 | backtest | `BacktestRunner` — replays Parquet → MarketEvent → EventBus |
| 4.3 | backtest | Performance metrics (Sharpe, max drawdown, win rate) |
| 4.4 | tws-client | IB connection manager + auto-reconnect |
| 4.5 | tws-client | Quote subscription + option chain flow |
| 4.6 | market-data | `LiveDataHandler` — wraps tws-client, implements DataHandler ABC |
| 4.7 | execution | `LiveGateway` — single-leg + BAG multi-leg order submission |
| 4.8 | apps/trader | Live + backtest assembly (`main.py` + config loading) + wire DecisionLogger into risk pipeline |
