import argparse
import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from trading_app.assembly import (
    build_backtest_app,
    build_live_app,
    load_strategy,
    subscribe_strategy,
)
from trading_app.config import TraderConfig, load_config


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.command == "validate-config":
        return 0
    if args.command == "backtest":
        return asyncio.run(_run_backtest(config))
    if args.command == "live":
        return asyncio.run(_run_live(config))

    parser.error("missing command")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    config_parser = argparse.ArgumentParser(add_help=False)
    config_parser.add_argument(
        "--config",
        type=Path,
        default=Path("apps/trader/config.toml"),
        help="Path to config.toml",
    )
    parser = argparse.ArgumentParser(prog="trading-app", parents=[config_parser])
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-config", parents=[config_parser])
    subparsers.add_parser("backtest", parents=[config_parser])
    subparsers.add_parser("live", parents=[config_parser])
    return parser


async def _run_backtest(config: TraderConfig) -> int:
    strategy_config = _require_strategy(config)
    contracts = _require_contracts(config)
    app = await build_backtest_app(
        config,
        contracts=contracts,
        start=config.backtest.start or datetime.now(UTC),
    )
    try:
        strategy = load_strategy(
            strategy_config.class_path,
            strategy_config.strategy_id,
            app.bus,
            app.clock,
            strategy_config.params,
        )
        subscribe_strategy(app.bus, strategy)
        await app.run()
    finally:
        await app.close()
    return 0


async def _run_live(config: TraderConfig) -> int:
    strategy_config = _require_strategy(config)
    contracts = _require_contracts(config)
    app = await build_live_app(config, contracts=contracts)
    try:
        strategy = load_strategy(
            strategy_config.class_path,
            strategy_config.strategy_id,
            app.bus,
            app.clock,
            strategy_config.params,
        )
        subscribe_strategy(app.bus, strategy)
        await app.connect()
        await app.run_market_data()
    finally:
        await app.close()
    return 0


def _require_contracts(config: TraderConfig):
    contracts = [contract.to_contract() for contract in config.contracts]
    if not contracts:
        raise ValueError("At least one [[contracts]] entry is required")
    return contracts


def _require_strategy(config: TraderConfig):
    if config.strategy is None:
        raise ValueError("[strategy] config is required")
    return config.strategy
