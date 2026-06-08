# Greeks Position Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a strategy-layer delta hedge component that emits `ADJUST` signals from aggregate portfolio Greeks drift.

**Architecture:** `DeltaHedgeStrategy` lives in `packages/strategy` and depends only on `core` models/events plus an injected Greeks provider. It computes a stock hedge order and publishes through `BaseStrategy.signal()`, leaving risk validation and execution to existing app wiring.

**Tech Stack:** Python 3.11, pytest, pytest-asyncio, existing `core` and `strategy` packages.

---

## Files

- Create: `packages/strategy/src/strategy/delta_hedge.py`
- Create: `packages/strategy/tests/test_delta_hedge.py`
- Modify: `packages/strategy/src/strategy/__init__.py`

## Tasks

- [x] Write failing tests in `packages/strategy/tests/test_delta_hedge.py`.
  - Verify an out-of-threshold delta emits one `ADJUST` signal.
  - Verify in-threshold delta emits no signal.
  - Verify low gamma uses the normal cooldown.
  - Verify high gamma uses the shorter cooldown.
  - Verify invalid constructor inputs raise `ValueError`.

- [x] Run focused tests red:
  - `uv run pytest packages/strategy/tests/test_delta_hedge.py -q`
  - Expected: import failure for `strategy.delta_hedge`.

- [x] Implement `DeltaHedgeStrategy`.
  - Constructor stores hedge contract settings and cooldown parameters.
  - `on_market_event()` ignores other symbols.
  - `_should_rebalance()` checks delta threshold, rounded hedge quantity, and gamma-aware cooldown.
  - `_publish_adjustment()` builds a one-leg stock `Order` and calls `signal("ADJUST", ...)`.

- [x] Export `DeltaHedgeStrategy` from `strategy.__init__`.

- [x] Run focused tests green:
  - `uv run pytest packages/strategy/tests/test_delta_hedge.py -q`

- [x] Run relevant package verification:
  - `uv run pytest packages/strategy/tests -q`
  - `uv run pytest packages/strategy/tests packages/risk/tests apps/trader/tests -q`
  - `uv run ruff check .`
  - `uv run ruff format --check .`

## Rollback

Delete `delta_hedge.py`, `test_delta_hedge.py`, and the export lines in
`strategy/__init__.py`.
