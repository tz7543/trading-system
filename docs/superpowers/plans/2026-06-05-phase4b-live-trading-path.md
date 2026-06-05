# Phase 4B: Live Trading Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the live trading path — tws-client (IB connection, quotes, option chain, LiveDataHandler) and execution (LiveGateway for order submission).

**Architecture:** tws-client wraps `ib_async.IB` via DI (no singleton). ConnectionManager handles connect/reconnect. MarketDataFeed bridges ib_async's callback-based Ticker updates to `AsyncIterator[MarketEvent]` via `asyncio.Queue`. LiveDataHandler implements the `DataHandler` ABC and lives in tws-client (not market-data — keeps market-data pure for backtest, per §2.2 dependency graph). LiveGateway in execution subscribes to `OrderEvent`, converts to ib_async types, places orders, and publishes `FillEvent` on completion.

**Tech Stack:** `ib_async`, `eventkit` (transitive via ib_async), `asyncio`, pytest + pytest-asyncio

**Testing caveat:** All tests mock the `ib_async.IB` object. They verify model conversion, control flow, and event plumbing — NOT live IB integration. A manual smoke-test checklist (at the bottom) against paper TWS (port 7497) is the real acceptance gate. Tests that pass green prove the wiring is correct, but a real IB connection may reveal timing, data format, or pacing issues.

**Spec resolutions:**
- LiveDataHandler in tws-client (not market-data) — user decision, honors §2.2 dependency graph
- Pacing: `fetch_history()` sleeps 15s after each `reqHistoricalDataAsync` call (spec §5.5)
- Subscription limit: MarketDataFeed tracks count, raises on >100 (spec §5.2)
- BAG lmtPrice sign: credit → negative, debit → positive (spec §5.4). The caller (strategy/risk) sets the sign; LiveGateway passes through
- LiveGateway listens to `trade.filledEvent` for fill completion, reads commission from `trade.fills[i].commissionReport`
- Auto-reconnect: 30s delay after disconnect (spec §5.1), no auto-resubscribe (that's Phase 4C app-level)
- Option chain: filter by `exchange="SMART"` from `reqSecDefOptParamsAsync` results (spec §5.3)

---

## File Structure

```
packages/
  tws-client/
    src/tws_client/
      __init__.py               ← MODIFY (exports)
      converters.py             ← NEW (core↔ib_async model conversion)
      connection.py             ← NEW (ConnectionManager)
      market_feed.py            ← NEW (MarketDataFeed — subscribe quotes via IB)
      live_data.py              ← NEW (LiveDataHandler — implements DataHandler ABC)
      option_chain.py           ← NEW (OptionChainService)
    tests/
      test_converters.py        ← NEW (4 tests)
      test_connection.py        ← NEW (2 tests)
      test_market_feed.py       ← NEW (3 tests)
      test_live_data.py         ← NEW (3 tests)
      test_live_gateway.py      ← NEW (3 tests — lives in execution but tests all need IB mock)
    pyproject.toml              ← MODIFY (add ib-async dep)
  execution/
    src/execution/
      __init__.py               ← MODIFY (exports)
      live_gateway.py           ← NEW (LiveGateway)
    tests/
      test_live_gateway.py      ← NEW (3 tests)
    pyproject.toml              ← MODIFY (add tws-client dep)
```

---

### Task 1: Model Converters + pyproject.toml Setup

**Files:**
- Create: `packages/tws-client/src/tws_client/converters.py`
- Modify: `packages/tws-client/pyproject.toml`
- Test: `packages/tws-client/tests/test_converters.py`

- [ ] **Step 1: Write failing tests**

```python
# packages/tws-client/tests/test_converters.py
import math
from datetime import UTC, datetime
from unittest.mock import MagicMock

import ib_async as ibi
import pytest

from core.events import MarketEvent
from core.models import Contract, Greeks
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
    # Use MagicMock for OptionComputation — its NamedTuple constructor signature
    # varies across ib_async versions (tickAttrib may be required as first field).
    # MagicMock is safe here because we only access named attributes.
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
```

- [ ] **Step 2: Update pyproject.toml**

```toml
# packages/tws-client/pyproject.toml
[project]
name = "tws-client"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "trading-core",
    "ib-async>=1.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tws_client"]

[tool.uv.sources]
trading-core = { workspace = true }
```

- [ ] **Step 3: Install dependencies**

Run: `uv sync`
Expected: ib-async + eventkit installed

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest packages/tws-client/tests/test_converters.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tws_client.converters'`

- [ ] **Step 5: Write converters implementation**

```python
# packages/tws-client/src/tws_client/converters.py
import math
from datetime import UTC, datetime

import ib_async as ibi

from core.events import MarketEvent
from core.models import Bar, Contract, Greeks


def to_ib_contract(contract: Contract) -> ibi.Contract:
    if contract.sec_type == "STK":
        return ibi.Stock(contract.symbol, contract.exchange, contract.currency)
    if contract.sec_type == "OPT":
        return ibi.Option(
            contract.symbol,
            contract.expiry,
            contract.strike,
            contract.right,
            contract.exchange,
            currency=contract.currency,
        )
    raise ValueError(f"Unsupported sec_type: {contract.sec_type}")


def ticker_to_market_event(ticker: ibi.Ticker, symbol: str) -> MarketEvent:
    model_greeks = None
    if ticker.modelGreeks:
        mg = ticker.modelGreeks
        model_greeks = Greeks(
            delta=_safe(mg.delta),
            gamma=_safe(mg.gamma),
            vega=_safe(mg.vega),
            theta=_safe(mg.theta),
            implied_vol=_safe(mg.impliedVol),
            underlying_price=_safe(mg.undPrice),
        )
    return MarketEvent(
        symbol=symbol,
        timestamp=ticker.time if ticker.time else datetime.now(UTC),
        bid=_safe(ticker.bid),
        ask=_safe(ticker.ask),
        last=_safe(ticker.last),
        volume=int(ticker.volume) if ticker.volume and not math.isnan(ticker.volume) else 0,
        model_greeks=model_greeks,
    )


def ib_bar_to_bar(bar: ibi.BarData, symbol: str) -> Bar:
    return Bar(
        timestamp=bar.date,
        symbol=symbol,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=int(bar.volume),
    )


def _safe(val: float | None) -> float:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return 0.0
    return float(val)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest packages/tws-client/tests/test_converters.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add packages/tws-client/pyproject.toml packages/tws-client/src/tws_client/converters.py packages/tws-client/tests/test_converters.py
git commit -m "feat(tws-client): add core↔ib_async model converters and ib-async dependency"
```

---

### Task 2: ConnectionManager

**Files:**
- Create: `packages/tws-client/src/tws_client/connection.py`
- Test: `packages/tws-client/tests/test_connection.py`

- [ ] **Step 1: Write failing tests**

```python
# packages/tws-client/tests/test_connection.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from eventkit import Event

from tws_client.connection import ConnectionManager


def _make_mock_ib():
    ib = MagicMock()
    ib.connectAsync = AsyncMock()
    ib.disconnect = MagicMock()
    ib.isConnected = MagicMock(return_value=False)
    ib.disconnectedEvent = Event("disconnectedEvent")
    return ib


@pytest.mark.asyncio
async def test_connect_and_disconnect():
    ib = _make_mock_ib()
    mgr = ConnectionManager(ib, host="127.0.0.1", port=7497, client_id=1)
    await mgr.connect()
    ib.connectAsync.assert_awaited_once_with("127.0.0.1", 7497, 1, timeout=4)
    assert mgr.is_connected is True

    mgr.disconnect()
    ib.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_auto_reconnect_on_disconnect():
    ib = _make_mock_ib()
    mgr = ConnectionManager(ib, host="127.0.0.1", port=7497, client_id=1)
    await mgr.connect()
    ib.connectAsync.reset_mock()

    with patch("tws_client.connection.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        ib.disconnectedEvent.emit()
        await asyncio.sleep(0)  # let reconnect task start
        await asyncio.sleep(0)  # let it proceed
        mock_sleep.assert_awaited_once_with(30)
        assert ib.connectAsync.await_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/tws-client/tests/test_connection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tws_client.connection'`

- [ ] **Step 3: Write ConnectionManager implementation**

```python
# packages/tws-client/src/tws_client/connection.py
import asyncio
import logging

import ib_async as ibi

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(
        self,
        ib: ibi.IB,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 1,
    ) -> None:
        self._ib = ib
        self._host = host
        self._port = port
        self._client_id = client_id
        self._reconnect_delay = 30
        self._auto_reconnect = True
        self._ib.disconnectedEvent += self._on_disconnect

    async def connect(self) -> None:
        await self._ib.connectAsync(self._host, self._port, self._client_id, timeout=4)
        logger.info("Connected to TWS at %s:%d", self._host, self._port)

    def disconnect(self) -> None:
        self._auto_reconnect = False
        self._ib.disconnect()
        logger.info("Disconnected from TWS")

    @property
    def is_connected(self) -> bool:
        return self._ib.isConnected()

    @property
    def ib(self) -> ibi.IB:
        return self._ib

    def _on_disconnect(self) -> None:
        if self._auto_reconnect:
            logger.warning("TWS disconnected, reconnecting in %ds", self._reconnect_delay)
            asyncio.ensure_future(self._reconnect())

    async def _reconnect(self) -> None:
        await asyncio.sleep(self._reconnect_delay)
        try:
            await self._ib.connectAsync(self._host, self._port, self._client_id, timeout=4)
            logger.info("Reconnected to TWS")
        except Exception:
            logger.exception("Reconnection failed, will retry on next disconnect")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/tws-client/tests/test_connection.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add packages/tws-client/src/tws_client/connection.py packages/tws-client/tests/test_connection.py
git commit -m "feat(tws-client): add ConnectionManager with auto-reconnect"
```

---

### Task 3: MarketDataFeed

**Files:**
- Create: `packages/tws-client/src/tws_client/market_feed.py`
- Test: `packages/tws-client/tests/test_market_feed.py`

- [ ] **Step 1: Write failing tests**

The MarketDataFeed bridges ib_async's callback-driven `Ticker.updateEvent` into an `AsyncIterator[MarketEvent]` via `asyncio.Queue`. Tests use real `eventkit.Event` on a mock Ticker to verify the bridge works end-to-end. This is the critical integration point — if the event bridge is wrong, live data stops flowing.

```python
# packages/tws-client/tests/test_market_feed.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/tws-client/tests/test_market_feed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tws_client.market_feed'`

- [ ] **Step 3: Write MarketDataFeed implementation**

```python
# packages/tws-client/src/tws_client/market_feed.py
import asyncio
from collections.abc import AsyncIterator

import ib_async as ibi

from core.events import MarketEvent
from core.models import Contract
from tws_client.converters import ticker_to_market_event, to_ib_contract


class SubscriptionLimitError(Exception):
    pass


class MarketDataFeed:
    def __init__(self, ib: ibi.IB, max_subscriptions: int = 100) -> None:
        self._ib = ib
        self._max_subscriptions = max_subscriptions
        self._active_count = 0

    @property
    def subscription_count(self) -> int:
        return self._active_count

    def subscribe(self, contract: Contract) -> AsyncIterator[MarketEvent]:
        if self._active_count >= self._max_subscriptions:
            raise SubscriptionLimitError(
                f"Max {self._max_subscriptions} subscriptions exceeded"
            )
        self._active_count += 1
        return self._subscribe_inner(contract)

    async def _subscribe_inner(self, contract: Contract) -> AsyncIterator[MarketEvent]:
        ib_contract = to_ib_contract(contract)
        ticker = self._ib.reqMktData(ib_contract, "", False, False)
        queue: asyncio.Queue[MarketEvent] = asyncio.Queue()

        def on_update(t: ibi.Ticker) -> None:
            event = ticker_to_market_event(t, contract.symbol)
            queue.put_nowait(event)

        ticker.updateEvent += on_update
        try:
            while True:
                yield await queue.get()
        finally:
            ticker.updateEvent -= on_update
            self._ib.cancelMktData(ib_contract)
            self._active_count -= 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/tws-client/tests/test_market_feed.py -v`
Expected: 3 passed

Note: `subscribe()` is a regular method (not async generator) — it checks the subscription limit and increments the count eagerly, then returns `_subscribe_inner()` which is the actual async generator. This ensures the limit check happens at call time, not at the first `__anext__()` call.

- [ ] **Step 5: Commit**

```bash
git add packages/tws-client/src/tws_client/market_feed.py packages/tws-client/tests/test_market_feed.py
git commit -m "feat(tws-client): add MarketDataFeed with async iterator bridge and subscription limit"
```

---

### Task 4: LiveDataHandler + OptionChainService

**Files:**
- Create: `packages/tws-client/src/tws_client/live_data.py`
- Create: `packages/tws-client/src/tws_client/option_chain.py`
- Modify: `packages/tws-client/src/tws_client/__init__.py`
- Test: `packages/tws-client/tests/test_live_data.py`

- [ ] **Step 1: Write failing tests**

```python
# packages/tws-client/tests/test_live_data.py
import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import ib_async as ibi
import pytest
from eventkit import Event

from core.models import Contract
from tws_client.live_data import LiveDataHandler
from tws_client.option_chain import OptionChainService


# Note: OptionChain in test_get_option_chain_filters_smart uses the real
# ibi.OptionChain — it's a simple NamedTuple with only primitive fields,
# and we pass all fields explicitly. If this breaks, switch to MagicMock.


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

    with patch("tws_client.live_data.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
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
            exchange="SMART", underlyingConId=265598, tradingClass="AAPL",
            multiplier="100", expirations=frozenset(["20260620", "20260717"]),
            strikes=frozenset([145.0, 150.0, 155.0]),
        ),
        ibi.OptionChain(
            exchange="CBOE", underlyingConId=265598, tradingClass="AAPL",
            multiplier="100", expirations=frozenset(["20260620"]),
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/tws-client/tests/test_live_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tws_client.live_data'`

- [ ] **Step 3: Write LiveDataHandler implementation**

```python
# packages/tws-client/src/tws_client/live_data.py
import asyncio
from collections.abc import AsyncIterator

import ib_async as ibi

from core.data_handler import DataHandler
from core.events import MarketEvent
from core.models import Bar, Contract
from tws_client.converters import ib_bar_to_bar, to_ib_contract
from tws_client.market_feed import MarketDataFeed


class LiveDataHandler(DataHandler):
    def __init__(self, ib: ibi.IB, max_subscriptions: int = 100) -> None:
        self._ib = ib
        self._feed = MarketDataFeed(ib, max_subscriptions)

    async def subscribe_quote(self, contract: Contract) -> AsyncIterator[MarketEvent]:
        async for event in self._feed.subscribe(contract):
            yield event

    async def fetch_history(
        self, contract: Contract, duration: str, bar_size: str
    ) -> list[Bar]:
        ib_contract = to_ib_contract(contract)
        bars = await self._ib.reqHistoricalDataAsync(
            ib_contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=True,
        )
        await asyncio.sleep(15)
        if not bars:
            return []
        return [ib_bar_to_bar(b, contract.symbol) for b in bars]
```

- [ ] **Step 4: Write OptionChainService implementation**

```python
# packages/tws-client/src/tws_client/option_chain.py
import ib_async as ibi

from core.models import OptionChain


class OptionChainService:
    def __init__(self, ib: ibi.IB) -> None:
        self._ib = ib

    async def get_chain(
        self, symbol: str, underlying_con_id: int
    ) -> OptionChain | None:
        chains = await self._ib.reqSecDefOptParamsAsync(
            symbol, "", "STK", underlying_con_id
        )
        for chain in chains:
            if chain.exchange == "SMART":
                return OptionChain(
                    exchange=chain.exchange,
                    trading_class=chain.tradingClass,
                    multiplier=int(chain.multiplier),
                    expirations=sorted(chain.expirations),
                    strikes=sorted(chain.strikes),
                )
        return None

    async def qualify(self, contracts: list[ibi.Contract]) -> list[ibi.Contract]:
        return await self._ib.qualifyContractsAsync(*contracts)
```

- [ ] **Step 5: Update tws-client __init__.py**

```python
# packages/tws-client/src/tws_client/__init__.py
from tws_client.connection import ConnectionManager
from tws_client.converters import ib_bar_to_bar, ticker_to_market_event, to_ib_contract
from tws_client.live_data import LiveDataHandler
from tws_client.market_feed import MarketDataFeed, SubscriptionLimitError
from tws_client.option_chain import OptionChainService

__all__ = [
    "ConnectionManager",
    "LiveDataHandler",
    "MarketDataFeed",
    "OptionChainService",
    "SubscriptionLimitError",
    "ib_bar_to_bar",
    "ticker_to_market_event",
    "to_ib_contract",
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest packages/tws-client/tests/test_live_data.py -v`
Expected: 3 passed

- [ ] **Step 7: Run all tws-client tests**

Run: `uv run pytest packages/tws-client/tests/ -v`
Expected: 12 passed (4 converters + 2 connection + 3 market_feed + 3 live_data)

- [ ] **Step 8: Commit**

```bash
git add packages/tws-client/src/tws_client/live_data.py packages/tws-client/src/tws_client/option_chain.py packages/tws-client/src/tws_client/__init__.py packages/tws-client/tests/test_live_data.py
git commit -m "feat(tws-client): add LiveDataHandler, OptionChainService, and package exports"
```

---

### Task 5: LiveGateway

**Files:**
- Create: `packages/execution/src/execution/live_gateway.py`
- Modify: `packages/execution/src/execution/__init__.py`
- Modify: `packages/execution/pyproject.toml`
- Test: `packages/execution/tests/test_live_gateway.py`

- [ ] **Step 1: Update execution pyproject.toml**

```toml
# packages/execution/pyproject.toml
[project]
name = "execution"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "trading-core",
    "tws-client",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/execution"]

[tool.uv.sources]
trading-core = { workspace = true }
tws-client = { workspace = true }
```

- [ ] **Step 2: Install dependencies**

Run: `uv sync`

- [ ] **Step 3: Write failing tests**

```python
# packages/execution/tests/test_live_gateway.py
import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import ib_async as ibi
import pytest
from eventkit import Event

from core.bus import EventBus
from core.clock import LiveClock
from core.events import FillEvent, OrderEvent
from core.models import Contract, Leg, Order
from execution.live_gateway import LiveGateway


def _make_mock_ib():
    ib = MagicMock()
    ib.placeOrder = MagicMock()
    return ib


def _stk_order_event():
    legs = [Leg(contract=Contract(symbol="AAPL", sec_type="STK", con_id=265598), quantity=100)]
    order = Order(legs=legs, strategy_id="test", order_type="LMT", limit_price=150.0)
    return OrderEvent(order=order, timestamp=datetime(2026, 6, 5, 14, 30, tzinfo=UTC), approved_by="risk")


def _bag_order_event():
    legs = [
        Leg(
            contract=Contract(
                symbol="AAPL", sec_type="OPT", expiry="20260620",
                strike=150.0, right="C", con_id=100001,
            ),
            quantity=-1,
        ),
        Leg(
            contract=Contract(
                symbol="AAPL", sec_type="OPT", expiry="20260620",
                strike=155.0, right="C", con_id=100002,
            ),
            quantity=1,
        ),
    ]
    order = Order(legs=legs, strategy_id="test", order_type="LMT", limit_price=-0.50)
    return OrderEvent(order=order, timestamp=datetime(2026, 6, 5, 14, 30, tzinfo=UTC), approved_by="risk")


@pytest.mark.asyncio
async def test_single_leg_places_order():
    mock_ib = _make_mock_ib()
    mock_trade = MagicMock()
    mock_trade.orderStatus.orderId = 1
    mock_ib.placeOrder.return_value = mock_trade

    bus = EventBus()
    clock = LiveClock()
    gateway = LiveGateway(bus, clock, mock_ib)
    await gateway.on_order(_stk_order_event())

    mock_ib.placeOrder.assert_called_once()
    args = mock_ib.placeOrder.call_args
    ib_contract = args[0][0]
    ib_order = args[0][1]
    assert isinstance(ib_contract, ibi.Stock)
    assert ib_contract.symbol == "AAPL"
    assert ib_order.action == "BUY"
    assert ib_order.totalQuantity == 100
    assert ib_order.lmtPrice == 150.0


@pytest.mark.asyncio
async def test_multi_leg_places_bag_order():
    mock_ib = _make_mock_ib()
    mock_trade = MagicMock()
    mock_trade.orderStatus.orderId = 2
    mock_ib.placeOrder.return_value = mock_trade

    bus = EventBus()
    clock = LiveClock()
    gateway = LiveGateway(bus, clock, mock_ib)
    await gateway.on_order(_bag_order_event())

    mock_ib.placeOrder.assert_called_once()
    args = mock_ib.placeOrder.call_args
    ib_contract = args[0][0]
    ib_order = args[0][1]
    assert ib_contract.secType == "BAG"
    assert ib_contract.symbol == "AAPL"
    assert len(ib_contract.comboLegs) == 2
    # First leg: sell 1 AAPL call 150
    assert ib_contract.comboLegs[0].conId == 100001
    assert ib_contract.comboLegs[0].action == "SELL"
    assert ib_contract.comboLegs[0].ratio == 1
    # Second leg: buy 1 AAPL call 155
    assert ib_contract.comboLegs[1].conId == 100002
    assert ib_contract.comboLegs[1].action == "BUY"
    assert ib_contract.comboLegs[1].ratio == 1
    # Credit spread → negative lmtPrice
    assert ib_order.lmtPrice == -0.50


@pytest.mark.asyncio
async def test_fill_publishes_fill_event():
    mock_ib = _make_mock_ib()
    mock_trade = MagicMock()
    mock_trade.orderStatus.orderId = 1
    mock_trade.isDone.return_value = True
    mock_trade.fills = [
        MagicMock(
            execution=MagicMock(shares=100.0, avgPrice=150.5, side="BOT"),
            contract=ibi.Stock("AAPL", "SMART", "USD"),
            commissionReport=MagicMock(commission=1.00),
        )
    ]
    # Use a real eventkit.Event — MagicMock's __iadd__ doesn't work correctly
    # because += rebinds the attribute, losing the mock reference.
    mock_trade.filledEvent = Event("filledEvent")
    mock_ib.placeOrder.return_value = mock_trade

    bus = EventBus()
    clock = LiveClock()
    received: list[FillEvent] = []

    async def capture(event: FillEvent) -> None:
        received.append(event)

    bus.subscribe(FillEvent, capture)

    gateway = LiveGateway(bus, clock, mock_ib)
    await gateway.on_order(_stk_order_event())

    # Emit the filledEvent — the gateway's handler will call _on_filled → _publish_fill
    mock_trade.filledEvent.emit(mock_trade)
    await asyncio.sleep(0)  # let ensure_future run
    await asyncio.sleep(0)  # let _publish_fill complete

    assert len(received) == 1
    assert received[0].order_id == "1"
    assert received[0].legs_filled[0].entry_price == 150.5
    assert received[0].commission == 1.00
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest packages/execution/tests/test_live_gateway.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'execution.live_gateway'`

- [ ] **Step 5: Write LiveGateway implementation**

```python
# packages/execution/src/execution/live_gateway.py
import asyncio
import logging

import ib_async as ibi

from core.bus import EventBus
from core.clock import Clock
from core.events import FillEvent, OrderEvent
from core.models import Contract, Leg

logger = logging.getLogger(__name__)


class LiveGateway:
    def __init__(self, bus: EventBus, clock: Clock, ib: ibi.IB) -> None:
        self._bus = bus
        self._clock = clock
        self._ib = ib

    async def on_order(self, event: OrderEvent) -> None:
        order = event.order
        if len(order.legs) == 1:
            ib_contract, ib_order = _build_single_leg(order)
        else:
            ib_contract, ib_order = _build_bag(order)

        trade = self._ib.placeOrder(ib_contract, ib_order)
        logger.info("Placed order %s for %s", trade.orderStatus.orderId, order.strategy_id)
        trade.filledEvent += lambda t: self._on_filled(t)

    def _on_filled(self, trade: ibi.Trade) -> None:
        asyncio.ensure_future(self._publish_fill(trade))

    async def _publish_fill(self, trade: ibi.Trade) -> None:
        legs_filled: list[Leg] = []
        total_commission = 0.0
        for fill in trade.fills:
            contract = _from_ib_contract(fill.contract)
            qty = int(fill.execution.shares)
            if fill.execution.side == "SLD":
                qty = -qty
            legs_filled.append(
                Leg(contract=contract, quantity=qty, entry_price=fill.execution.avgPrice)
            )
            if fill.commissionReport:
                total_commission += fill.commissionReport.commission

        fill_event = FillEvent(
            order_id=str(trade.orderStatus.orderId),
            legs_filled=legs_filled,
            timestamp=self._clock.now(),
            commission=total_commission,
        )
        await self._bus.publish(fill_event)


def _build_single_leg(order) -> tuple[ibi.Contract, ibi.Order]:
    leg = order.legs[0]
    ib_contract = _to_ib_contract_with_conid(leg.contract)
    action = "BUY" if leg.quantity > 0 else "SELL"
    qty = abs(leg.quantity)

    if order.order_type == "MKT":
        ib_order = ibi.MarketOrder(action, qty)
    else:
        ib_order = ibi.LimitOrder(action, qty, order.limit_price or 0.0)

    ib_order.tif = order.time_in_force
    return ib_contract, ib_order


def _build_bag(order) -> tuple[ibi.Contract, ibi.Order]:
    underlying = order.legs[0].contract.symbol
    bag = ibi.Contract(
        secType="BAG",
        symbol=underlying,
        currency=order.legs[0].contract.currency,
        exchange="SMART",
    )
    bag.comboLegs = []
    for leg in order.legs:
        if not leg.contract.con_id:
            raise ValueError(
                f"BAG leg {leg.contract.symbol} has no con_id — "
                "call OptionChainService.qualify() first"
            )
        combo = ibi.ComboLeg(
            conId=leg.contract.con_id,
            ratio=abs(leg.quantity),
            action="BUY" if leg.quantity > 0 else "SELL",
            exchange=leg.contract.exchange,
        )
        bag.comboLegs.append(combo)

    if order.order_type == "MKT":
        ib_order = ibi.MarketOrder("BUY", 1)
    else:
        ib_order = ibi.LimitOrder("BUY", 1, order.limit_price or 0.0)

    ib_order.tif = order.time_in_force
    return bag, ib_order


def _to_ib_contract_with_conid(contract: Contract) -> ibi.Contract:
    if contract.sec_type == "STK":
        c = ibi.Stock(contract.symbol, contract.exchange, contract.currency)
    elif contract.sec_type == "OPT":
        c = ibi.Option(
            contract.symbol, contract.expiry, contract.strike,
            contract.right, contract.exchange, currency=contract.currency,
        )
    else:
        raise ValueError(f"Unsupported sec_type: {contract.sec_type}")
    if contract.con_id:
        c.conId = contract.con_id
    return c


def _from_ib_contract(ib_contract: ibi.Contract) -> Contract:
    sec_type = "OPT" if ib_contract.secType == "OPT" else "STK"
    return Contract(
        symbol=ib_contract.symbol,
        sec_type=sec_type,
        exchange=ib_contract.exchange or "SMART",
        currency=ib_contract.currency or "USD",
        expiry=getattr(ib_contract, "lastTradeDateOrContractMonth", ""),
        strike=getattr(ib_contract, "strike", 0.0),
        right=getattr(ib_contract, "right", ""),
        con_id=ib_contract.conId,
    )
```

- [ ] **Step 6: Update execution __init__.py**

```python
# packages/execution/src/execution/__init__.py
from execution.live_gateway import LiveGateway

__all__ = ["LiveGateway"]
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest packages/execution/tests/test_live_gateway.py -v`
Expected: 3 passed

- [ ] **Step 8: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass (backtest 12 + tws-client 12 + execution 3 + previous phases)

- [ ] **Step 9: Lint**

Run: `uv run ruff check .`
Expected: Clean

- [ ] **Step 10: Commit**

```bash
git add packages/execution/pyproject.toml packages/execution/src/execution/live_gateway.py packages/execution/src/execution/__init__.py packages/execution/tests/test_live_gateway.py
git commit -m "feat(execution): add LiveGateway with single-leg and BAG order support"
```

---

## Manual Smoke-Test Checklist (Phase 4C)

After Phase 4C assembly wires everything together, run these manual checks against paper TWS (port 7497). **Mocked tests above cannot catch these:**

1. **Connection**: `ConnectionManager.connect()` succeeds against paper TWS
2. **Auto-reconnect**: Kill TWS, wait >30s, restart TWS — verify reconnection
3. **Live quote**: Subscribe to AAPL, verify `MarketEvent` stream with real bid/ask/last
4. **Option Greeks**: Subscribe to an AAPL option, verify `model_greeks` populated (tick 13)
5. **Option chain**: Fetch AAPL chain, verify expirations + strikes returned
6. **Historical data**: Fetch 5 days of AAPL bars, verify pacing (15s delay)
7. **Single-leg order**: Place paper LMT buy for 1 share AAPL, verify `FillEvent`
8. **BAG order**: Place paper bull call spread (2 legs), verify correct ComboLeg construction and fill
9. **lmtPrice sign**: Place credit spread, verify negative lmtPrice sent to IB

---

## Phase 4C Roadmap (Next)

**Bus wiring note:** `LiveGateway.__init__` does NOT call `bus.subscribe(OrderEvent, self.on_order)` — this is intentional. Bus subscription wiring happens in Phase 4C (apps/trader assembly), consistent with how `SimulatedExecutor` was wired in Phase 4A (the runner calls `executor.on_order()` directly). Phase 4C.2 must wire `bus.subscribe(OrderEvent, gateway.on_order)`.

| Task | Package | Key Deliverable |
|------|---------|-----------------|
| 4C.1 | apps/trader | Config loading (config.toml → pydantic model) |
| 4C.2 | apps/trader | Live mode assembly (EventBus wiring, all subscribers including `bus.subscribe(OrderEvent, gateway.on_order)`) |
| 4C.3 | apps/trader | Backtest mode assembly (same strategy code, swapped components) |
| 4C.4 | apps/trader | Integration test: backtest pipeline with risk + storage |
