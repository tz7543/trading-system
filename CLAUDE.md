# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Quantitative trading system for US equities and options via Interactive Brokers TWS API. Python 3.11+ monorepo managed with `uv workspaces`. Pre-implementation stage — approved design spec at `@docs/superpowers/specs/2026-06-04-tws-monorepo-design.md`.

## Monorepo Structure

```
packages/
  core/          ← Zero external deps; all other packages depend on this
  tws-client/    ← IB TWS API adapter (ib_async)
  market-data/   ← DataHandler ABC + live/historical implementations
  storage/       ← Parquet (Hive-partitioned), DuckDB, SQLite WAL
  risk/          ← Three-tier: PreTradeValidator → RealTimeMonitor → CircuitBreaker
  strategy/      ← Strategy base class + multi-leg options support
  backtest/      ← Backtest engine (same strategy code as live)
  execution/     ← Live execution gateway
apps/
  trader/        ← System entry point (main.py + config.toml)
```

Dependency direction: all packages → `core`, never reverse.

## Build & Run Commands

```bash
uv sync                              # Install all workspace dependencies
uv run pytest                        # Run all tests
uv run pytest -k 'test_name'         # Run single test
uv run ruff check .                  # Lint
uv run ruff format .                 # Format
uv run python apps/trader/main.py    # Run trader
```

## Conventions

- **Commits**: Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`)
- **Type hints**: Required on all function signatures (Python 3.11+ syntax)
- **Async**: Use `asyncio` natively; `ib_async` is the TWS client library
- **DI pattern**: Strategy never imports DataHandler concretely — injected via `main.py`
- **Strategy isolation**: Strategy only receives `MarketEvent`, never portfolio state (prevents look-ahead bias)

## IB TWS API Gotchas

- **Pacing limits**: Historical data 2s/request, 5 requests/15s global, 60 requests/10m
- **Daily disconnect**: TWS closes connection ~23:45 EST; auto-reconnect after 30s
- **Option validation**: Must call `qualifyContracts()` before BAG order placement
- **BAG price sign**: Credit spread → negative `lmtPrice`; debit spread → positive
- **Greeks ticks**: Prefer `model_greeks` (tick 13) for live; fallback to `py_vollib` for backtest
- **Market data subscriptions**: Initial 100 minimum; auto-scales with account equity

## Storage Conventions

- **Ticks**: Parquet with Hive partitioning — `ticks/sec_type=STK/symbol={sym}/date={date}/data.parquet`
- **Options ticks**: `ticks/sec_type=OPT/symbol={sym}/expiry={exp}/strike={k}/right={r}/date={date}/data.parquet`
- **DuckDB**: Single writer process only; analytics queries
- **SQLite**: WAL mode for orders/fills — single writer, multiple readers

## Key Dependencies

ib_async, pandas, pyarrow, duckdb, aiosqlite, pydantic, loguru, py_vollib, pytest, pytest-asyncio, ruff
