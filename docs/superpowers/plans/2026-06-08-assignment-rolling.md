# Assignment and Rolling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add typed option assignment events, tested assignment position adjustment, and roll-order builders.

**Architecture:** `core.events` owns `AssignmentEvent`. `strategy.assignment` owns pure position/rolling helpers and depends only on `core.models`/`core.events`. `LiveGateway` exposes a small `on_assignment()` publishing hook for app-level IB callback wiring.

**Tech Stack:** Python 3.11 dataclasses, pytest, pytest-asyncio, existing `core`, `strategy`, and `execution` packages.

---

## Files

- Modify: `packages/core/src/core/events.py`
- Modify: `packages/core/src/core/__init__.py`
- Modify: `packages/core/tests/test_events.py`
- Create: `packages/strategy/src/strategy/assignment.py`
- Create: `packages/strategy/tests/test_assignment.py`
- Modify: `packages/strategy/src/strategy/__init__.py`
- Modify: `packages/execution/src/execution/live_gateway.py`
- Modify: `packages/execution/tests/test_live_gateway.py`

## Tasks

- [x] Write failing core event test for `AssignmentEvent`.

- [x] Write failing strategy assignment tests.
  - Short put assignment reduces short put quantity and adds long stock.
  - Short call assignment reduces short call quantity and adds short stock.
  - Partial assignment detection returns true for fewer assigned contracts than open.
  - Over-assignment raises `ValueError`.
  - Roll order closes existing leg and opens far-expiry replacement.
  - Roll order rejects non-option legs and same expiry.

- [x] Write failing execution test for `LiveGateway.on_assignment()`.
  - Subscribe to `AssignmentEvent`.
  - Call `gateway.on_assignment(...)`.
  - Assert one typed assignment event is published.

- [x] Run focused tests red.
  - `uv run pytest packages/core/tests/test_events.py packages/strategy/tests/test_assignment.py packages/execution/tests/test_live_gateway.py -q`
  - Expected: missing `AssignmentEvent` / `strategy.assignment` symbols.

- [x] Implement `AssignmentEvent` and core export.

- [x] Implement `strategy.assignment`.
  - `assignment_stock_quantity(contract, contracts_assigned)`
  - `matching_short_option_leg(position, assignment)`
  - `is_partial_assignment(position, assignment)`
  - `apply_assignment(position, assignment)`
  - `build_roll_order(leg, new_expiry, new_strike=None, strategy_id="")`

- [x] Export assignment helpers from `strategy`.

- [x] Implement `LiveGateway.on_assignment()`.

- [x] Run focused and broad verification.
  - `uv run pytest packages/core/tests/test_events.py packages/strategy/tests/test_assignment.py packages/execution/tests/test_live_gateway.py -q`
  - `uv run pytest packages/core/tests packages/strategy/tests packages/execution/tests -q`
  - `uv run pytest -q`
  - `uv run ruff check .`
  - `uv run ruff format --check .`

## Rollback

Remove `AssignmentEvent`, `strategy.assignment`, related exports, gateway hook, tests,
and this plan/spec pair.
