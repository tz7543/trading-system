import argparse
import asyncio
import os
import signal
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


def _ensure_paper_guard(config: TraderConfig) -> None:
    paper_ports = {7497, 4002}
    if config.tws.port in paper_ports:
        return
    if os.environ.get("IB_CONFIRM_LIVE") == "YES":
        return
    raise RuntimeError(
        f"Port {config.tws.port} is not a paper trading port. "
        "Set IB_CONFIRM_LIVE=YES to confirm live trading."
    )


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
    _ensure_paper_guard(config)
    strategy_config = _require_strategy(config)
    contracts = _require_contracts(config)
    app = await build_live_app(config, contracts=contracts)
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown.set)
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
        tasks = [
            asyncio.create_task(app.run_market_data()),
            asyncio.create_task(
                app.risk_check_loop(config.risk.check_interval_seconds)
            ),
            asyncio.create_task(app.watchdog_loop()),
        ]
        try:
            await shutdown.wait()
        finally:
            for task in tasks:
                task.cancel()
            # await cancelled tasks before closing shared resources (bus/storage/
            # connection), otherwise teardown-period tasks can still write
            await asyncio.gather(*tasks, return_exceptions=True)
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
