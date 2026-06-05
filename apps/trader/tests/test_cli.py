from trading_app.cli import main


def test_validate_config_command_uses_default_config():
    assert main(["validate-config", "--config", "apps/trader/config.toml"]) == 0
