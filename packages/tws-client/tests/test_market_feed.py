import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import ib_async as ibi
import pytest
from eventkit import Event

from core.models import Contract
from tws_client.market_feed import MarketDataFeed, SubscriptionLimitError


class FakeTicker:
    def __init__(self):
        self.updateEvent = Event("updateEvent")
        self.bid = 0.0
        self.ask = 0.0
        self.last = 0.0
        self.volume = 0
        self.time = None
        self.modelGreeks = None
        self.contract = ibi.Stock("AAPL", "SMART", "USD")


@pytest.mark.asyncio
async def test_subscribe_yields_market_events():
    """Ticker.updateEvent → asyncio.Queue → AsyncIterator[MarketEvent]."""
    mock_ib = MagicMock()
    fake_ticker = FakeTicker()
    mock_ib.reqMktData.return_value = fake_ticker

    feed = MarketDataFeed(mock_ib)
    contract = Contract(symbol="AAPL", sec_type="STK")

    gen = feed.subscribe(contract)

    async def push_tick():
        await asyncio.sleep(0)
        fake_ticker.bid = 149.9
        fake_ticker.ask = 150.1
        fake_ticker.last = 150.0
        fake_ticker.volume = 1000
        fake_ticker.time = datetime(2026, 6, 5, 14, 30, tzinfo=UTC)
        fake_ticker.updateEvent.emit(fake_ticker)

    task = asyncio.create_task(push_tick())
    event = await gen.__anext__()
    await task
    assert event.symbol == "AAPL"
    assert event.bid == 149.9
    assert event.last == 150.0
    assert event.volume == 1000
    await gen.aclose()


@pytest.mark.asyncio
async def test_unsubscribe_cancels_mkt_data():
    """Closing the generator calls ib.cancelMktData."""
    mock_ib = MagicMock()
    fake_ticker = FakeTicker()
    mock_ib.reqMktData.return_value = fake_ticker

    feed = MarketDataFeed(mock_ib)
    contract = Contract(symbol="AAPL", sec_type="STK")

    gen = feed.subscribe(contract)

    async def push_and_close():
        await asyncio.sleep(0)
        fake_ticker.last = 100.0
        fake_ticker.time = datetime(2026, 6, 5, 14, 30, tzinfo=UTC)
        fake_ticker.updateEvent.emit(fake_ticker)

    task = asyncio.create_task(push_and_close())
    await gen.__anext__()
    await task
    await gen.aclose()
    mock_ib.cancelMktData.assert_called_once()
    assert feed.subscription_count == 0


def test_subscription_limit_exceeded():
    """Raises SubscriptionLimitError when >max active subscriptions.

    subscribe() is a regular method (not async generator) — it checks and
    increments the count eagerly before returning the async generator.
    No need to start the generators to trigger the limit.
    """
    mock_ib = MagicMock()
    mock_ib.reqMktData.return_value = FakeTicker()

    feed = MarketDataFeed(mock_ib, max_subscriptions=2)
    feed.subscribe(Contract(symbol="AAPL", sec_type="STK"))
    feed.subscribe(Contract(symbol="MSFT", sec_type="STK"))

    with pytest.raises(SubscriptionLimitError):
        feed.subscribe(Contract(symbol="GOOG", sec_type="STK"))
