import math
from datetime import UTC, datetime
from unittest.mock import MagicMock

import ib_async as ibi

from core.events import MarketEvent
from core.models import Contract
from tws_client.converters import ticker_to_market_event, to_ib_contract


def test_to_ib_contract_stk():
    contract = Contract(symbol="AAPL", sec_type="STK", exchange="SMART", currency="USD")
    ib_c = to_ib_contract(contract)
    assert isinstance(ib_c, ibi.Stock)
    assert ib_c.symbol == "AAPL"
    assert ib_c.exchange == "SMART"
    assert ib_c.currency == "USD"


def test_to_ib_contract_opt():
    contract = Contract(
        symbol="AAPL",
        sec_type="OPT",
        expiry="20260620",
        strike=150.0,
        right="C",
        exchange="SMART",
        currency="USD",
    )
    ib_c = to_ib_contract(contract)
    assert isinstance(ib_c, ibi.Option)
    assert ib_c.symbol == "AAPL"
    assert ib_c.lastTradeDateOrContractMonth == "20260620"
    assert ib_c.strike == 150.0
    assert ib_c.right == "C"


def test_ticker_to_market_event():
    ticker = ibi.Ticker()
    ticker.contract = ibi.Stock("AAPL", "SMART", "USD")
    ticker.bid = 149.9
    ticker.ask = 150.1
    ticker.last = 150.0
    ticker.volume = 5000
    ticker.time = datetime(2026, 6, 5, 14, 30, tzinfo=UTC)
    mock_greeks = MagicMock()
    mock_greeks.delta = 0.55
    mock_greeks.gamma = 0.03
    mock_greeks.vega = 0.12
    mock_greeks.theta = -0.05
    mock_greeks.impliedVol = 0.25
    mock_greeks.undPrice = 150.0
    ticker.modelGreeks = mock_greeks
    event = ticker_to_market_event(ticker, "AAPL")
    assert isinstance(event, MarketEvent)
    assert event.symbol == "AAPL"
    assert event.bid == 149.9
    assert event.last == 150.0
    assert event.volume == 5000
    assert event.model_greeks is not None
    assert event.model_greeks.delta == 0.55
    assert event.model_greeks.implied_vol == 0.25


def test_ticker_to_market_event_nan_values():
    ticker = ibi.Ticker()
    ticker.contract = ibi.Stock("AAPL", "SMART", "USD")
    ticker.bid = math.nan
    ticker.ask = math.nan
    ticker.last = math.nan
    ticker.volume = 0
    ticker.time = None
    ticker.modelGreeks = None
    event = ticker_to_market_event(ticker, "AAPL")
    assert event.bid == 0.0
    assert event.ask == 0.0
    assert event.last == 0.0
    assert event.model_greeks is None


def test_ticker_event_carries_contract():
    contract = Contract(
        symbol="AAPL", sec_type="OPT", expiry="20260119", strike=150.0, right="C"
    )
    ticker = ibi.Ticker()
    ticker.contract = ibi.Stock("AAPL", "SMART", "USD")
    ticker.bid = 5.0
    ticker.ask = 5.2
    ticker.last = 5.1
    ticker.volume = 100
    ticker.time = datetime(2026, 1, 19, 14, 30, tzinfo=UTC)
    ticker.modelGreeks = None
    event = ticker_to_market_event(ticker, "AAPL", contract=contract)
    assert event.contract is contract
