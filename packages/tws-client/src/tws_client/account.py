import logging

import ib_async as ibi

logger = logging.getLogger(__name__)


class AccountState:
    def __init__(self, ib: ibi.IB) -> None:
        self._ib = ib
        self._values: dict[str, float] = {}

    async def start(self) -> None:
        for item in await self._ib.accountSummaryAsync():
            self._store(item)
        self._ib.accountSummaryEvent += self._store

    def _store(self, item) -> None:
        try:
            self._values[item.tag] = float(item.value)
        except (TypeError, ValueError):
            logger.debug("Non-numeric account value %s=%r", item.tag, item.value)

    def equity(self) -> float | None:
        return self._values.get("NetLiquidation")

    def margin_cushion(self) -> float | None:
        cushion = self._values.get("Cushion")
        if cushion is not None:
            return cushion
        ewl = self._values.get("EquityWithLoanValue")
        maint = self._values.get("FullMaintMarginReq")
        if ewl and maint is not None:
            return (ewl - maint) / ewl
        return None
