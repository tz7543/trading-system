# IV Rank Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add IV Rank / IV Percentile calculations and a high-IV strategy entry hook that emits `ENTER` signals.

**Architecture:** Pure metric functions live in `strategy.iv_metrics` and depend only on standard Python. `IVRankEntryStrategy` lives in `strategy.iv_entry`, depends on `core` and injected provider/factory callables, and keeps storage/data-handler source selection outside `strategy`.

**Tech Stack:** Python 3.11, dataclasses, pytest, pytest-asyncio, existing `core` and `strategy` packages.

---

## Files

- Create: `packages/strategy/src/strategy/iv_metrics.py`
- Create: `packages/strategy/src/strategy/iv_entry.py`
- Create: `packages/strategy/tests/test_iv_metrics.py`
- Create: `packages/strategy/tests/test_iv_entry.py`
- Modify: `packages/strategy/src/strategy/__init__.py`

## Tasks

- [x] Write failing tests for IV metrics.
  - `calculate_iv_rank([0.20, 0.30, 0.50], 0.425) == 75.0`
  - `calculate_iv_percentile([0.20, 0.30, 0.50], 0.30) == 66.666...`
  - invalid/empty history raises `ValueError`
  - flat history returns `100.0` at or above the flat value and `0.0` below it

- [x] Write failing tests for `IVRankEntryStrategy`.
  - High IV Rank emits one `ENTER` signal.
  - Low IV Rank emits no signal.
  - Duplicate high-IV events emit only one signal.
  - Other symbols are ignored.

- [x] Run focused tests red.
  - `uv run pytest packages/strategy/tests/test_iv_metrics.py packages/strategy/tests/test_iv_entry.py -q`
  - Expected: import failures for missing modules.

- [x] Implement `strategy.iv_metrics`.
  - `IVMetrics` dataclass with `current_iv`, `iv_rank`, `iv_percentile`, `history_count`.
  - `valid_iv_values(values)`.
  - `calculate_iv_rank(history, current_iv)`.
  - `calculate_iv_percentile(history, current_iv)`.
  - `calculate_iv_metrics(history, current_iv)`.

- [x] Implement `strategy.iv_entry`.
  - Constructor validates threshold is between `0.0` and `100.0`.
  - `on_market_event()` filters symbol, calls metrics provider, checks threshold and `_entered`.
  - Publishes `ENTER` with the injected order and context.
  - `on_fill()` is a no-op for this slice.

- [x] Export `IVMetrics`, metric functions, and `IVRankEntryStrategy` from `strategy`.

- [x] Run focused and broad verification.
  - `uv run pytest packages/strategy/tests/test_iv_metrics.py packages/strategy/tests/test_iv_entry.py -q`
  - `uv run pytest packages/strategy/tests -q`
  - `uv run pytest -q`
  - `uv run ruff check .`
  - `uv run ruff format --check .`

## Rollback

Delete the new IV modules/tests and remove their exports from `strategy/__init__.py`.
