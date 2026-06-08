# IV Rank Entry Design

**Goal:** Add IV Rank / IV Percentile calculations and a strategy entry hook for
high-implied-volatility option strategies.

## Problem

The system stores option ticks with `model_iv`, but there is no reusable module that
turns that history into IV Rank or IV Percentile. Strategy code also has no standard
way to emit entry signals when IV is high enough for premium-selling strategies.

## Data Source Decision

Use locally accumulated option tick history as the first 52-week IV source.

`TickWriter`, `TickReader`, and `HistoricalDataHandler` already persist and recover
`model_iv` through `MarketEvent.model_greeks.implied_vol`. IB historical data does not
directly provide a 52-week IV series, so this slice treats vendor or external IV history
as a later provider implementation, not a dependency for strategy behavior.

Strategy code must not import `storage` or `market-data`. It receives a metrics provider
or precomputed history from app/backtest wiring.

## In Scope

- Pure IV Rank / IV Percentile functions in `packages/strategy`.
- A small dataclass for the computed metrics.
- A high-IV entry strategy that publishes `SignalEvent.direction="ENTER"` when
  IV Rank is above a configured threshold.
- Tests for formulas, empty/flat history edge cases, and signal publication.

## Out of Scope

- External IV vendors.
- A new live data collection job.
- A specific options order recipe. The strategy receives an injected order factory so
  iron condor, short put, and other premium-selling orders can be wired separately.

## Metrics

All public metric values use a 0-100 scale because the handoff uses thresholds such as
`IV Rank > 70`.

```text
IV Rank = ((current_iv - historical_min) / (historical_max - historical_min)) * 100
IV Percentile = count(history_iv <= current_iv) / count(history_iv) * 100
```

Invalid history values are ignored when they are `None`, `NaN`, or below zero.

If no valid history remains, metrics raise `ValueError("iv history is empty")`.
If all historical IV values are equal, IV Rank is `100.0` when `current_iv` is greater
than or equal to that flat value, otherwise `0.0`.

## Strategy Behavior

Create `strategy.iv_entry.IVRankEntryStrategy`.

The strategy receives:

- `metrics_provider: Callable[[MarketEvent], IVMetrics | None]`
- `order_factory: Callable[[MarketEvent, IVMetrics], Order]`
- `entry_rank_threshold`, default `70.0`

On a matching market event, if metrics are available and
`metrics.iv_rank >= entry_rank_threshold`, the strategy emits an `ENTER` signal. The
signal context includes `iv_rank`, `iv_percentile`, `current_iv`, and `history_count`.

The strategy gates duplicate entries with a simple `_entered` flag. It resets on any
fill for the same strategy id only when all filled leg quantities net to zero is not
implemented in this slice; explicit exit/position lifecycle remains app-level work.

## Tests

- IV Rank normal formula.
- IV Percentile normal formula.
- Empty/invalid history raises.
- Flat history rank behavior.
- High IV Rank emits one `ENTER` signal with context.
- Low IV Rank emits no signal.
- Duplicate high-IV market events emit only one entry signal.
- Strategy ignores events for other symbols.

## Rollback

Remove the IV metrics module, IV entry strategy, tests, and exports. No data schema or
live execution behavior changes are required.
