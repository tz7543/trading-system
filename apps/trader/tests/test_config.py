from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_app.config import RiskConfig, TraderConfig, TwsConfig, load_config


def test_load_config_from_existing_toml():
    config = load_config(Path("apps/trader/config.toml"))

    assert config.tws.host == "127.0.0.1"
    assert config.tws.port == 7497
    assert config.tws.client_id == 1
    assert config.risk.max_delta == 500.0
    assert config.risk.to_risk_limits().max_position_size == 10
    assert config.backtest.ticks_dir == Path("data/ticks")
    assert config.storage.trade_db == Path("data/orders.db")
    assert config.contracts == []
    assert config.strategy is None


def test_load_config_with_contracts_and_strategy(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[[contracts]]
symbol = "AAPL"
sec_type = "STK"
exchange = "SMART"
currency = "USD"

[[contracts]]
symbol = "AAPL"
sec_type = "OPT"
expiry = "20260620"
strike = 150.0
right = "C"

[strategy]
class_path = "my_strategy:MomentumStrategy"
strategy_id = "momentum-1"
params = { threshold = 150.0 }
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert [contract.to_contract().symbol for contract in config.contracts] == [
        "AAPL",
        "AAPL",
    ]
    assert config.contracts[1].to_contract().right == "C"
    assert config.strategy is not None
    assert config.strategy.class_path == "my_strategy:MomentumStrategy"
    assert config.strategy.params == {"threshold": 150.0}


def test_config_rejects_invalid_risk_limits(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[tws]
host = "127.0.0.1"
port = 7497
client_id = 1

[risk]
max_delta = -1
max_vega = 1000.0
max_drawdown = 0.05
max_position_size = 10
max_margin_utilization = 0.8
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_config(config_path)


def test_new_timing_fields_defaults():
    config = TraderConfig()
    assert config.tws.stale_data_seconds == 60.0
    assert config.risk.check_interval_seconds == 30.0


def test_timing_fields_must_be_positive():
    with pytest.raises(ValidationError):
        TwsConfig(stale_data_seconds=0)
    with pytest.raises(ValidationError):
        RiskConfig(check_interval_seconds=-1)
