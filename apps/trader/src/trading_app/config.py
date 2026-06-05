import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.models import Contract, RiskLimits


class TwsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=7497, ge=1, le=65535)
    client_id: int = Field(default=1, ge=0)
    max_subscriptions: int = Field(default=100, gt=0)


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_delta: float = Field(default=500.0, gt=0)
    max_vega: float = Field(default=1000.0, gt=0)
    max_drawdown: float = Field(default=0.05, gt=0, lt=1)
    max_position_size: int = Field(default=10, gt=0)
    max_margin_utilization: float = Field(default=0.8, gt=0, le=1)
    initial_equity: float = Field(default=0.0, ge=0)

    def to_risk_limits(self) -> RiskLimits:
        return RiskLimits(
            max_delta=self.max_delta,
            max_vega=self.max_vega,
            max_drawdown=self.max_drawdown,
            max_position_size=self.max_position_size,
            max_margin_utilization=self.max_margin_utilization,
        )


class BacktestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticks_dir: Path = Path("data/ticks")
    start: datetime | None = None


class StorageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticks_dir: Path = Path("data/ticks")
    decision_db: Path = Path("data/decisions.duckdb")
    trade_db: Path = Path("data/orders.db")


class ContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    sec_type: Literal["STK", "OPT"]
    currency: str = "USD"
    exchange: str = "SMART"
    expiry: str = ""
    strike: float = 0.0
    right: Literal["C", "P", ""] = ""
    multiplier: int = 100
    con_id: int = 0

    def to_contract(self) -> Contract:
        return Contract(
            symbol=self.symbol,
            sec_type=self.sec_type,
            currency=self.currency,
            exchange=self.exchange,
            expiry=self.expiry,
            strike=self.strike,
            right=self.right,
            multiplier=self.multiplier,
            con_id=self.con_id,
        )


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_path: str
    strategy_id: str
    params: dict[str, Any] = Field(default_factory=dict)


class TraderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tws: TwsConfig = Field(default_factory=TwsConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    contracts: list[ContractConfig] = Field(default_factory=list)
    strategy: StrategyConfig | None = None


def load_config(path: str | Path = Path("apps/trader/config.toml")) -> TraderConfig:
    with Path(path).open("rb") as file:
        data = tomllib.load(file)
    return TraderConfig.model_validate(data)
