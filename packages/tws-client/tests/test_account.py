from types import SimpleNamespace

import eventkit
import pytest

from tws_client.account import AccountState


def _av(tag, value):
    return SimpleNamespace(tag=tag, value=value, account="DU1", currency="USD")


class FakeIB:
    def __init__(self, values):
        self._values = values
        self.accountSummaryEvent = eventkit.Event()

    async def accountSummaryAsync(self, account=""):
        return self._values


async def test_equity_and_cushion_from_summary():
    ib = FakeIB([_av("NetLiquidation", "100000"), _av("Cushion", "0.45")])
    state = AccountState(ib)
    await state.start()
    assert state.equity() == 100000.0
    assert state.margin_cushion() == 0.45


async def test_cushion_fallback_computed():
    ib = FakeIB(
        [
            _av("NetLiquidation", "100000"),
            _av("EquityWithLoanValue", "100000"),
            _av("FullMaintMarginReq", "20000"),
        ]
    )
    state = AccountState(ib)
    await state.start()
    assert state.margin_cushion() == pytest.approx(0.8)


async def test_no_data_returns_none():
    state = AccountState(FakeIB([]))
    await state.start()
    assert state.equity() is None
    assert state.margin_cushion() is None


async def test_event_updates_values():
    ib = FakeIB([_av("NetLiquidation", "100000")])
    state = AccountState(ib)
    await state.start()
    ib.accountSummaryEvent.emit(_av("NetLiquidation", "90000"))
    assert state.equity() == 90000.0
