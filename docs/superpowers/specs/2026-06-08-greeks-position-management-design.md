# Greeks Position Management Design

**Goal:** Add strategy-layer delta rebalancing that can turn portfolio Greeks drift into
`ADJUST` signals without coupling strategy code to IB, storage, or live-only execution.

## Problem

The risk monitor already detects delta and vega drift, but it only publishes alerts and
can trigger the circuit breaker. The strategy package has no logic that responds to
portfolio Greeks drift by proposing an adjustment order, even though
`SignalEvent.direction="ADJUST"` already exists.

## In Scope

- A reusable strategy component that calculates stock hedge quantity from aggregate
  portfolio delta.
- `ADJUST` signal publication using existing `BaseStrategy.signal()`.
- Gamma-aware rebalance cadence: higher absolute gamma permits more frequent hedge
  checks.
- Focused tests for hedge quantity, no-op thresholds, cooldown behavior, and exported
  package API.

## Out of Scope

- Live IB assignment callbacks.
- Option-leg rolling.
- IV rank or IV percentile entry logic.
- Direct order submission from strategy code. Existing app wiring remains responsible
  for `SignalEvent -> RiskPipeline -> OrderEvent -> LiveGateway`.

## Proposed Behavior

Create `strategy.delta_hedge.DeltaHedgeStrategy`.

The strategy receives an injected `greeks_provider: Callable[[], Greeks]`. On a matching
`MarketEvent`, it reads current aggregate Greeks and computes:

```text
hedge_quantity = round(target_delta - current_delta)
```

Positive quantity buys the underlying stock; negative quantity sells it. If the absolute
delta drift is at or below `delta_threshold`, or the rounded hedge quantity is zero, the
strategy does nothing.

The generated order is a single-stock `Order` with one `Leg` for the configured hedge
symbol. The signal uses `direction="ADJUST"` and includes `context["proposed_greeks"]`
with the hedge delta so the existing pre-trade validator can evaluate the post-adjust
portfolio delta.

## Gamma-Aware Cadence

The strategy stores the timestamp of the most recent adjustment. If another hedge is
needed before the active cooldown has elapsed, it does nothing.

- Normal cooldown: `min_rebalance_seconds`
- High-gamma cooldown: `high_gamma_min_rebalance_seconds`
- High gamma is active when `abs(current_gamma) >= high_gamma_threshold`

This keeps low-gamma books from overtrading while allowing high-gamma books to rebalance
more frequently.

## Error Handling

Constructor validation rejects:

- `delta_threshold < 0`
- cooldown values below zero
- `high_gamma_threshold < 0`
- `high_gamma_min_rebalance_seconds > min_rebalance_seconds`

Runtime data is intentionally simple. The strategy ignores market events for other
symbols and does not catch exceptions from the injected Greeks provider.

## Tests

- Emits an `ADJUST` stock hedge signal when delta drift exceeds threshold.
- Does not emit when delta is inside threshold.
- Uses the longer cooldown when gamma is below the high-gamma threshold.
- Allows earlier rebalance when gamma is above the high-gamma threshold.
- Exports `DeltaHedgeStrategy` from `strategy`.

## Rollback

Remove `strategy/delta_hedge.py`, its tests, and the package export. No persisted data,
schema, or live execution behavior changes are involved.
