import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import ib_async as ibi
import pytest
from eventkit import Event

from core.models import Contract
from tws_client.live_data import LiveDataHandler
from tws_client.option_chain import OptionChainService


class FakeTicker:
    def __init__(self):
        self.updateEvent = Event("updateEvent")
        self.bid = 149.9
        self.ask = 150.1
        self.last = 150.0
        self.volume = 1000
        self.time = datetime(2026, 6, 5, 14, 30, tzinfo=UTC)
        self.modelGreeks = None
        self.contract = ibi.Stock("AAPL", "SMART", "USD")


@pytest.mark.asyncio
async def test_subscribe_quote_yields_events():
    mock_ib = MagicMock()
    mock_ib.qualifyContractsAsync = AsyncMock()
    fake_ticker = FakeTicker()
    mock_ib.reqMktData.return_value = fake_ticker

    handler = LiveDataHandler(mock_ib)
    contract = Contract(symbol="AAPL", sec_type="STK")
    gen = handler.subscribe_quote(contract)

    async def push_tick():
        await asyncio.sleep(0)
        fake_ticker.updateEvent.emit(fake_ticker)

    task = asyncio.create_task(push_tick())
    event = await gen.__anext__()
    await task
    assert event.symbol == "AAPL"
    assert event.last == 150.0
    await gen.aclose()


@pytest.mark.asyncio
async def test_fetch_history_with_pacing():
    mock_ib = MagicMock()
    mock_ib.qualifyContractsAsync = AsyncMock()
    # Use MagicMock for BarData — its NamedTuple constructor signature
    # may vary across ib_async versions. We only read named attributes.
    bar = MagicMock()
    bar.date = datetime(2026, 6, 5, tzinfo=UTC)
    bar.open = 100.0
    bar.high = 105.0
    bar.low = 99.0
    bar.close = 103.0
    bar.volume = 50000
    mock_ib.reqHistoricalDataAsync = AsyncMock(return_value=[bar])

    handler = LiveDataHandler(mock_ib)
    contract = Contract(symbol="AAPL", sec_type="STK")

    with patch(
        "tws_client.live_data.asyncio.sleep", new_callable=AsyncMock
    ) as mock_sleep:
        bars = await handler.fetch_history(contract, "1 D", "1 day")

    assert len(bars) == 1
    assert bars[0].symbol == "AAPL"
    assert bars[0].close == 103.0
    mock_sleep.assert_awaited_once_with(15)


@pytest.mark.asyncio
async def test_get_option_chain_filters_smart():
    mock_ib = MagicMock()
    chains = [
        ibi.OptionChain(
            exchange="SMART",
            underlyingConId=265598,
            tradingClass="AAPL",
            multiplier="100",
            expirations=frozenset(["20260620", "20260717"]),
            strikes=frozenset([145.0, 150.0, 155.0]),
        ),
        ibi.OptionChain(
            exchange="CBOE",
            underlyingConId=265598,
            tradingClass="AAPL",
            multiplier="100",
            expirations=frozenset(["20260620"]),
            strikes=frozenset([150.0]),
        ),
    ]
    mock_ib.reqSecDefOptParamsAsync = AsyncMock(return_value=chains)

    svc = OptionChainService(mock_ib)
    result = await svc.get_chain("AAPL", 265598)

    assert result is not None
    assert result.exchange == "SMART"
    assert result.trading_class == "AAPL"
    assert result.multiplier == 100
    assert "20260620" in result.expirations
    assert 150.0 in result.strikes
