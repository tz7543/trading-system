# Repository Guidelines

## Operating Principles

State assumptions before nontrivial work. If the request has multiple valid
interpretations, surface the tradeoff before editing.

Use the minimum code or documentation change that solves the request. Do not add
speculative features, abstractions, or configurability.

Make surgical changes only. Do not refactor adjacent code, reformat unrelated
files, or remove pre-existing dead code unless explicitly asked.

Define a verifiable goal for each behavior change, then run the focused check
that proves it. For documentation-only changes, verify links, paths, and config
syntax instead of running unrelated test suites.

## Project Overview

This is a Python 3.11+ `uv` workspace for a US equities/options trading system
using Interactive Brokers TWS / IB Gateway. The approved design spec is
@docs/superpowers/specs/2026-06-04-tws-monorepo-design.md.

The CLI entry point is committed but paper TWS smoke test is still pending.

```bash
uv run python apps/trader/main.py validate-config [--config apps/trader/config.toml]
uv run python apps/trader/main.py backtest [--config apps/trader/config.toml]
uv run python apps/trader/main.py live [--config apps/trader/config.toml]
```

## Project Structure & Module Organization

Workspace packages live under `packages/*` with code in `src/<module>/` and
tests in `tests/`.

- `packages/core`: shared domain types, events, clocks, and interfaces. It has
  no higher-level package dependencies.
- `packages/tws-client`: Interactive Brokers TWS adapter built on `ib_async`.
- `packages/market-data`: `DataHandler` implementations for live and
  historical data.
- `packages/storage`: Parquet tick storage, DuckDB analytics, SQLite trade
  state, and decision logging.
- `packages/risk`: pre-trade validation, real-time monitoring, and circuit
  breakers.
- `packages/strategy`: strategy base classes, multi-leg options helpers, and
  Greeks aggregation.
- `packages/backtest`: event replay, simulated execution, and performance
  metrics.
- `packages/execution`: live execution gateway.
- `apps/trader`: application assembly and configuration. Keep app config in
  `apps/trader/config.toml`.

Keep generated market data and local artifacts under `data/` or ignored local
directories.

## Architecture Rules

Keep dependency direction clean: shared domain types belong in `core`, and
`core` must not import higher-level packages.

`strategy` should not know about IB, storage, or live/backtest mode. Inject data
access via the `DataHandler` abstraction and pass strategies market/fill events,
not portfolio internals, to avoid look-ahead bias.

`risk` should validate orders and monitor exposure without depending on
`strategy` or `storage`. App-level wiring is responsible for connecting
strategy, risk, storage, and execution.

Backtest and live trading should share strategy code. Differences belong in the
data handler, clock, and execution gateway implementations.

## Build, Test, and Development Commands

- `uv sync` - install workspace and development dependencies from `uv.lock`.
- `uv run pytest` - run all package tests configured by `pyproject.toml`.
- `uv run pytest packages/risk/tests` - run one package's tests.
- `uv run pytest -k test_name` - run tests matching a name expression.
- `uv run ruff check .` - lint imports, modernization, bugbear, simplify, and
  Ruff rules.
- `uv run ruff format .` - format Python files.

## Coding Style & Naming Conventions

Use Python 3.11 syntax with type hints on public function signatures. Ruff
targets `py311`, formats to 88 columns, and enforces import ordering with
first-party modules listed in `ruff.toml`.

Distribution names may use hyphens, but import packages use underscores. For
example, `tws-client` exposes `tws_client`.

## Testing Guidelines

Tests use `pytest` and `pytest-asyncio` with `asyncio_mode = "auto"`. Put tests
beside each package in `packages/<name>/tests/` and name files `test_*.py`.

Prefer focused tests for trading rules, event ordering, risk checks,
persistence schemas, and backtest/live parity. For behavior changes, add or
update a test that demonstrates the expected outcome before relying on manual
verification.

## Interactive Brokers TWS Notes

- Historical data has strict pacing. Keep request throttling explicit.
- TWS / IB Gateway can disconnect during daily maintenance; reconnection logic
  should be deliberate and tested.
- Options and BAG orders require contract qualification before placement.
- Credit and debit spread limit price signs must be handled intentionally.
- Prefer live model Greeks when available; use calculated Greeks only as a
  fallback or for backtests.

## Storage Conventions

- Stock ticks: `data/ticks/sec_type=STK/symbol={sym}/date={date}/data.parquet`.
- Option ticks:
  `data/ticks/sec_type=OPT/symbol={sym}/expiry={exp}/strike={k}/right={r}/date={date}/data.parquet`.
- DuckDB is for analytics and decision logs; keep writes single-process.
- SQLite should use WAL mode for orders/fills where one writer and many readers
  are expected.

## Commit & Pull Request Guidelines

Recent history uses Conventional Commits, often scoped by package, such as
`feat(backtest): add BacktestRunner` or
`fix(risk): remove namespace collision`. Keep commits small and tied to one
concern.

PRs should include a short problem statement, the implemented change, test
evidence, linked issue or plan when relevant, and screenshots only for
UI-facing changes.

## Auto-Format Hooks

`.py` files are auto-formatted on every Write/Edit via tool hooks
(`.claude/settings.json` and `.codex/hooks.json` both run
`uvx ruff format` + `uvx ruff check --fix`). Do not manually format or fix
lint errors that Ruff handles — the hook does it automatically.

## Caveats

- `README.md` is stale — it describes the old flat layout and pip workflow.
  Do not reference it for project structure or setup instructions.
- No CI/CD pipeline — all verification is local (`uv run pytest`,
  `uv run ruff check .`).
- Refer to `docs/HANDOFF.md` for current project status and next steps.
