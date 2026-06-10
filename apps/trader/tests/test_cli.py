import asyncio
from datetime import UTC, datetime

import pytest

from core import EventBus, SimClock
from trading_app import cli
from trading_app.cli import _ensure_paper_guard, main
from trading_app.config import TraderConfig, TwsConfig


def test_validate_config_command_uses_default_config():
    assert main(["validate-config", "--config", "apps/trader/config.toml"]) == 0


def test_paper_guard_blocks_live_port(monkeypatch):
    monkeypatch.delenv("IB_CONFIRM_LIVE", raising=False)
    config = TraderConfig(tws=TwsConfig(port=7496))
    with pytest.raises(RuntimeError, match="IB_CONFIRM_LIVE"):
        _ensure_paper_guard(config)


def test_paper_guard_allows_paper_port():
    _ensure_paper_guard(TraderConfig(tws=TwsConfig(port=7497)))  # must not raise


def test_paper_guard_env_override(monkeypatch):
    monkeypatch.setenv("IB_CONFIRM_LIVE", "YES")
    _ensure_paper_guard(TraderConfig(tws=TwsConfig(port=7496)))  # must not raise


class _StubLiveApp:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.bus = EventBus()
        self.clock = SimClock(datetime(2026, 6, 10, tzinfo=UTC))

    async def connect(self) -> None:
        self.calls.append("connect")

    async def run_market_data(self) -> None:
        self.calls.append("run_market_data")
        await asyncio.Event().wait()

    async def risk_check_loop(self, interval: float) -> None:
        self.calls.append("risk_check_loop")
        await asyncio.Event().wait()

    async def watchdog_loop(self, interval: float = 10.0) -> None:
        self.calls.append("watchdog_loop")
        await asyncio.Event().wait()

    async def close(self) -> None:
        self.calls.append("close")


class _StubStrategy:
    async def on_market_event(self, event) -> None:
        pass

    async def on_fill(self, event) -> None:
        pass


def test_run_live_creates_and_cancels_loop_tasks(tmp_path, monkeypatch):
    # Must be a sync def — cli.main() calls asyncio.run() internally, which
    # would RuntimeError inside a pytest-asyncio async test (nested loop).
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[tws]
port = 7497

[[contracts]]
symbol = "AAPL"
sec_type = "STK"

[strategy]
class_path = "dummy:Dummy"
strategy_id = "s1"
""".strip(),
        encoding="utf-8",
    )
    calls: list[str] = []
    app = _StubLiveApp(calls)

    async def _fake_build(config, ib=None, contracts=()):
        return app

    monkeypatch.setattr(cli, "build_live_app", _fake_build)
    monkeypatch.setattr(cli, "load_strategy", lambda *a, **k: _StubStrategy())
    # Signal handler install → immediately schedule shutdown so main returns.
    monkeypatch.setattr(
        asyncio.SelectorEventLoop,
        "add_signal_handler",
        lambda self, sig, cb: self.call_soon(cb),
        raising=False,
    )

    result = cli.main(["live", "--config", str(config_path)])

    assert result == 0
    assert "run_market_data" in calls
    assert "risk_check_loop" in calls
    assert "watchdog_loop" in calls
    assert calls[-1] == "close"  # close after all tasks are done
