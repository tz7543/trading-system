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
