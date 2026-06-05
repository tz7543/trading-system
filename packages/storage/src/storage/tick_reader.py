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
