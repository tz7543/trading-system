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
