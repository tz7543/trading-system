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
        volume=int(ticker.volume)
        if ticker.volume and not math.isnan(ticker.volume)
        else 0,
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
