from collections.abc import AsyncIterator
from pathlib import Path

import pyarrow as pa
import pyarrow.dataset as ds

from core.data_handler import DataHandler
from core.events import MarketEvent
from core.models import Bar, Contract, Greeks
from core.partitions import tick_contract_dir, tick_partition_path

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


class HistoricalDataHandler(DataHandler):
    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)

    async def subscribe_quote(self, contract: Contract) -> AsyncIterator[MarketEvent]:
        contract_dir = tick_contract_dir(self._base_dir, contract)
        if not contract_dir.exists():
            return
        dates = sorted(
            d.name.removeprefix("date=")
            for d in contract_dir.iterdir()
            if d.is_dir() and d.name.startswith("date=")
        )
        for date_str in dates:
            partition_dir = tick_partition_path(self._base_dir, contract, date_str)
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


def _table_to_events(table: pa.Table) -> list[MarketEvent]:
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
