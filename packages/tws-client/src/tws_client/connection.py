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
        self._reconnect_task: asyncio.Task | None = None
        self._ib.disconnectedEvent += self._on_disconnect

    async def connect(self) -> None:
        await self._ib.connectAsync(self._host, self._port, self._client_id, timeout=4)
        logger.info("Connected to TWS at %s:%d", self._host, self._port)

    def disconnect(self) -> None:
        self._auto_reconnect = False
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
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
            self._reconnect_task = asyncio.ensure_future(self._reconnect())

    async def _reconnect(self) -> None:
        await asyncio.sleep(self._reconnect_delay)
        try:
            await self._ib.connectAsync(self._host, self._port, self._client_id, timeout=4)
            logger.info("Reconnected to TWS")
        except Exception:
            logger.exception("Reconnection failed, will retry on next disconnect")
