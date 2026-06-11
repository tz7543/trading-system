from unittest.mock import AsyncMock, MagicMock

import ib_async as ibi
import pytest

from tws_client.option_chain import OptionChainService


def _make_chain(
    exchange: str,
    expirations=None,
    strikes=None,
    multiplier="100",
    trading_class="AAPL",
):
    return ibi.OptionChain(
        exchange=exchange,
        underlyingConId=265598,
        tradingClass=trading_class,
        multiplier=multiplier,
        expirations=frozenset(expirations or ["20260620", "20260717"]),
        strikes=frozenset(strikes or [145.0, 150.0, 155.0]),
    )


@pytest.mark.asyncio
async def test_get_chain_returns_smart_exchange():
    mock_ib = MagicMock()
    mock_ib.reqSecDefOptParamsAsync = AsyncMock(
        return_value=[
            _make_chain("CBOE"),
            _make_chain("SMART"),
        ]
    )
    svc = OptionChainService(mock_ib)
    result = await svc.get_chain("AAPL", 265598)

    assert result is not None
    assert result.exchange == "SMART"


@pytest.mark.asyncio
async def test_get_chain_converts_multiplier_to_int():
    mock_ib = MagicMock()
    mock_ib.reqSecDefOptParamsAsync = AsyncMock(
        return_value=[_make_chain("SMART", multiplier="100")]
    )
    svc = OptionChainService(mock_ib)
    result = await svc.get_chain("AAPL", 265598)

    assert result is not None
    assert result.multiplier == 100
    assert isinstance(result.multiplier, int)


@pytest.mark.asyncio
async def test_get_chain_expirations_are_sorted_list():
    mock_ib = MagicMock()
    mock_ib.reqSecDefOptParamsAsync = AsyncMock(
        return_value=[
            _make_chain("SMART", expirations=["20260717", "20260620", "20260515"])
        ]
    )
    svc = OptionChainService(mock_ib)
    result = await svc.get_chain("AAPL", 265598)

    assert result is not None
    assert isinstance(result.expirations, list)
    assert result.expirations == sorted(result.expirations)


@pytest.mark.asyncio
async def test_get_chain_strikes_are_sorted_list():
    mock_ib = MagicMock()
    mock_ib.reqSecDefOptParamsAsync = AsyncMock(
        return_value=[_make_chain("SMART", strikes=[155.0, 145.0, 150.0])]
    )
    svc = OptionChainService(mock_ib)
    result = await svc.get_chain("AAPL", 265598)

    assert result is not None
    assert isinstance(result.strikes, list)
    assert result.strikes == sorted(result.strikes)


@pytest.mark.asyncio
async def test_get_chain_returns_none_when_no_smart():
    mock_ib = MagicMock()
    mock_ib.reqSecDefOptParamsAsync = AsyncMock(
        return_value=[
            _make_chain("CBOE"),
            _make_chain("AMEX"),
        ]
    )
    svc = OptionChainService(mock_ib)
    result = await svc.get_chain("AAPL", 265598)

    assert result is None


@pytest.mark.asyncio
async def test_get_chain_returns_none_for_empty_list():
    mock_ib = MagicMock()
    mock_ib.reqSecDefOptParamsAsync = AsyncMock(return_value=[])
    svc = OptionChainService(mock_ib)
    result = await svc.get_chain("AAPL", 265598)

    assert result is None


@pytest.mark.asyncio
async def test_get_chain_passes_symbol_and_con_id_to_ib():
    mock_ib = MagicMock()
    mock_ib.reqSecDefOptParamsAsync = AsyncMock(return_value=[])
    svc = OptionChainService(mock_ib)
    await svc.get_chain("SPY", 756733)

    mock_ib.reqSecDefOptParamsAsync.assert_awaited_once_with("SPY", "", "STK", 756733)


@pytest.mark.asyncio
async def test_qualify_returns_contracts_with_con_id_populated():
    mock_ib = MagicMock()
    contract = ibi.Stock("AAPL", "SMART", "USD")
    qualified = ibi.Stock("AAPL", "SMART", "USD")
    qualified.conId = 265598
    mock_ib.qualifyContractsAsync = AsyncMock(return_value=[qualified])

    svc = OptionChainService(mock_ib)
    result = await svc.qualify([contract])

    assert len(result) == 1
    assert result[0].conId == 265598


@pytest.mark.asyncio
async def test_qualify_passes_all_contracts_to_ib():
    mock_ib = MagicMock()
    contracts = [
        ibi.Stock("AAPL", "SMART", "USD"),
        ibi.Stock("SPY", "SMART", "USD"),
    ]
    mock_ib.qualifyContractsAsync = AsyncMock(return_value=contracts)

    svc = OptionChainService(mock_ib)
    await svc.qualify(contracts)

    # qualifyContractsAsync is called with *contracts (unpacked)
    mock_ib.qualifyContractsAsync.assert_awaited_once_with(*contracts)


@pytest.mark.asyncio
async def test_qualify_empty_list_returns_empty():
    mock_ib = MagicMock()
    mock_ib.qualifyContractsAsync = AsyncMock(return_value=[])

    svc = OptionChainService(mock_ib)
    result = await svc.qualify([])

    assert result == []
    mock_ib.qualifyContractsAsync.assert_awaited_once_with()
