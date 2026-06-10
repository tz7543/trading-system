import logging

import ib_async as ibi

from core.models import MarginInfo

logger = logging.getLogger(__name__)


class AccountState:
    def __init__(self, ib: ibi.IB) -> None:
        self._ib = ib
        self._values: dict[str, float] = {}

    async def start(self) -> None:
        for item in await self._ib.accountSummaryAsync():
            self._store(item)
        self._ib.accountSummaryEvent += self._store

    def _store(self, item: ibi.AccountValue) -> None:
        try:
            self._values[item.tag] = float(item.value)
        except (TypeError, ValueError):
            logger.debug("Non-numeric account value %s=%r", item.tag, item.value)

    def equity(self) -> float | None:
        return self._values.get("NetLiquidation")

    def margin_info(self) -> MarginInfo | None:
        init = self._values.get("FullInitMarginReq")
        maint = self._values.get("FullMaintMarginReq")
        ewl = self._values.get("EquityWithLoanValue")
        if init is None or maint is None or ewl is None:
            return None
        return MarginInfo(init_margin=init, maint_margin=maint, equity_with_loan=ewl)

    def margin_cushion(self) -> float | None:
        cushion = self._values.get("Cushion")
        if cushion is not None:
            return cushion
        ewl = self._values.get("EquityWithLoanValue")
        maint = self._values.get("FullMaintMarginReq")
        # Falsy ewl (0.0 = zero equity) intentionally returns None to avoid
        # division by zero.
        if ewl and maint is not None:
            return (ewl - maint) / ewl
        return None
