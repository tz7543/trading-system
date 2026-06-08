# Assignment and Rolling Design

**Goal:** Add the first assignment/rolling primitives needed to handle option
assignment and roll remaining option exposure.

## Problem

The system has fills and orders, but no event type for option assignment and no strategy
helper for rolling an option leg. The handoff calls out three missing pieces:

- `AssignmentEvent`
- roll-leg builders
- partial assignment detection / position restructuring

## In Scope

- Add `AssignmentEvent` to `core.events`.
- Export the event from `core`.
- Add strategy helpers for:
  - calculating stock delivery from an assigned short call/put
  - detecting partial assignment against an open short option leg
  - applying assignment to a `Position`
  - building a close-and-open roll order for an option leg
- Add a `LiveGateway.on_assignment(...)` hook that publishes `AssignmentEvent`.

## Out of Scope

- Automatic inference of IB assignments from every possible `execDetailsEvent` shape.
- Assignment-aware storage schemas.
- Full portfolio lifecycle reconciliation.
- Strategy-specific roll timing rules.

The live gateway hook gives app-level callback wiring a typed target without forcing
unverified IB callback assumptions into this slice.

## Event Model

`AssignmentEvent` contains:

- `strategy_id`
- `timestamp`
- `assigned_contract`
- `contracts_assigned`
- `stock_quantity`
- `account`
- `underlying_price`

`stock_quantity` follows short option assignment economics:

- short call assignment delivers stock: `-contracts * multiplier`
- short put assignment receives stock: `+contracts * multiplier`

## Position Adjustment

`apply_assignment(position, event)`:

- finds the matching short option leg
- reduces that short option quantity toward zero by `contracts_assigned`
- adds or merges the resulting stock leg
- preserves other legs and position metadata

It raises `ValueError` when the assignment has no matching short option leg or assigns
more contracts than are open.

`is_partial_assignment(position, event)` is true when assigned contracts are fewer than
the matching open short contracts.

## Rolling

`build_roll_order(leg, new_expiry, new_strike=None, strategy_id="")` creates a two-leg
order:

1. close the existing option leg with `-leg.quantity`
2. open the replacement option leg with the original `leg.quantity`

The helper validates that the leg is an option, quantity is non-zero, and the new expiry
differs from the current expiry.

## Tests

- `AssignmentEvent` stores assignment details.
- Short put assignment creates long stock and reduces short put exposure.
- Short call assignment creates short stock and reduces short call exposure.
- Partial assignment detection.
- Over-assignment raises.
- Roll order closes the near leg and opens the far leg.
- Roll order rejects non-option legs and same expiry.
- `LiveGateway.on_assignment()` publishes an `AssignmentEvent`.

## Rollback

Remove `AssignmentEvent`, the assignment helper module/tests, gateway hook/tests, and
exports. No persisted data schema changes are involved.
