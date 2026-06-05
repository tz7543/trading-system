from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backtest.executor import SimulatedExecutor
from backtest.metrics import compute_metrics
from backtest.runner import BacktestRunner
from core.bus import EventBus
from core.clock import SimClock
from core.events import MarketEvent, OrderEvent
from core.models import Contract, Leg, Order
from core.partitions import tick_partition_path

TICK_SCHEMA = pa.schema(
    [
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
    ]
)


def _write_ticks(base_dir: Path, contract: Contract, date: str, rows: list[dict]):
    partition = tick_partition_path(base_dir, contract, date)
    partition.mkdir(parents=True, exist_ok=True)
    nulls = {
        "model_delta": None,
        "model_gamma": None,
        "model_vega": None,
        "model_theta": None,
        "model_iv": None,
        "model_underlying": None,
    }
    for row in rows:
        for k, v in nulls.items():
            row.setdefault(k, v)
    table = pa.table(
        {col: [r[col] for r in rows] for col in TICK_SCHEMA.names},
        schema=TICK_SCHEMA,
    )
    pq.write_table(table, partition / "000000.parquet", use_dictionary=False)


@pytest.mark.asyncio
async def test_end_to_end_backtest(tmp_path):
    """Full backtest: Parquet → replay → signal → fill → metrics."""
    from market_data.historical import HistoricalDataHandler

    contract = Contract(symbol="AAPL", sec_type="STK")
    t1 = datetime(2026, 6, 4, 14, 30, 0, tzinfo=UTC)
    t2 = datetime(2026, 6, 4, 14, 31, 0, tzinfo=UTC)
    t3 = datetime(2026, 6, 4, 14, 32, 0, tzinfo=UTC)
    _write_ticks(
        tmp_path,
        contract,
        "2026-06-04",
        [
            {
                "timestamp": t1,
                "symbol": "AAPL",
                "bid": 99.9,
                "ask": 100.1,
                "last": 100.0,
                "volume": 1000,
            },
            {
                "timestamp": t2,
                "symbol": "AAPL",
                "bid": 104.9,
                "ask": 105.1,
                "last": 105.0,
                "volume": 1000,
            },
            {
                "timestamp": t3,
                "symbol": "AAPL",
                "bid": 109.9,
                "ask": 110.1,
                "last": 110.0,
                "volume": 1000,
            },
        ],
    )

    bus = EventBus()
    clock = SimClock(t1)
    data_handler = HistoricalDataHandler(tmp_path)
    executor = SimulatedExecutor(bus, clock)

    async def signal_on_market(event: MarketEvent) -> None:
        if event.last == 100.0:
            order = Order(
                legs=[Leg(contract=contract, quantity=100)],
                strategy_id="test",
            )
            await executor.on_order(
                OrderEvent(order=order, timestamp=clock.now(), approved_by="test")
            )
        elif event.last == 105.0:
            order = Order(
                legs=[Leg(contract=contract, quantity=-100)],
                strategy_id="test",
            )
            await executor.on_order(
                OrderEvent(order=order, timestamp=clock.now(), approved_by="test")
            )

    bus.subscribe(MarketEvent, signal_on_market)
    runner = BacktestRunner(bus, clock, data_handler, executor, [contract])
    fills = await runner.run()

    assert len(fills) == 2
    # Buy order placed at t1 (price=100), fills at t2 (price=105)
    assert fills[0].legs_filled[0].entry_price == 105.0
    assert fills[0].legs_filled[0].quantity == 100
    # Sell order placed at t2 (price=105), fills at t3 (price=110)
    assert fills[1].legs_filled[0].entry_price == 110.0
    assert fills[1].legs_filled[0].quantity == -100

    result = compute_metrics(fills, initial_equity=100000.0)
    # PnL: (110 - 105) * 100 = $500
    assert result.total_pnl == pytest.approx(500.0)
    assert result.total_commission > 0
    assert result.win_rate == 1.0
