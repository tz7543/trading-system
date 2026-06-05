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
    ib.isConnected.return_value = True
    assert mgr.is_connected is True

    mgr.disconnect()
    ib.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_auto_reconnect_on_disconnect():
    ib = _make_mock_ib()
    mgr = ConnectionManager(ib, host="127.0.0.1", port=7497, client_id=1)
    await mgr.connect()
    ib.connectAsync.reset_mock()

    with patch(
        "tws_client.connection.asyncio.sleep", new_callable=AsyncMock
    ) as mock_sleep:
        ib.disconnectedEvent.emit()
        assert mgr._reconnect_task is not None
        await mgr._reconnect_task
        mock_sleep.assert_awaited_once_with(30)
        assert ib.connectAsync.await_count == 1
