from pathlib import Path

from trading_app.cli import main
from trading_app.config import TraderConfig, load_config

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.toml")


def load_default_config() -> TraderConfig:
    return load_config(DEFAULT_CONFIG_PATH)


if __name__ == "__main__":
    raise SystemExit(main())
