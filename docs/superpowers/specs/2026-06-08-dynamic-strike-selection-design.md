# Dynamic Strike Selection Design

## Goal

Add a pure-function strike selection module to the strategy package that
intelligently picks option strikes from an option chain. Supports delta-based
selection (primary) with ATM-relative fallback when live Greeks are unavailable.

## Context

The trading system has 15 multi-leg strategy factory functions in
`strategy/multi_leg.py` that accept static strike parameters. The
`OptionChainService` in `tws-client` already provides full
expiration x strike matrices via `reqSecDefOptParams`. What is missing is the
logic to select strikes from those matrices.

## Architecture

### New File

`packages/strategy/src/strategy/strike_selector.py`

### Dependencies

Only `core.models` (`Greeks`, `OptionChain`) and `typing`. No new third-party
packages. The strategy package continues to depend only on core.

### Data Flow

```
app wiring (injects chain data + optional greeks_map)
    |
    v
strategy/strike_selector.py  -- pure functions, filtering only
    |
    v returns strike float values
strategy/multi_leg.py         -- builds Order from selected strikes
```

The selector does not fetch data. The caller (app layer or strategy logic)
provides the option chain, underlying price, and optionally a Greeks map. This
preserves the architecture rule that strategy does not depend on market-data or
tws-client.

## Public API

### `filter_strikes(strikes, underlying_price, max_distance=10) -> list[float]`

Narrow a full strike list to ATM +/- `max_distance` strikes. Returns a sorted
subset. Returns empty list if strikes is empty.

Parameters:
- `strikes: list[float]` -- sorted strike prices from OptionChain
- `underlying_price: float` -- current underlying price
- `max_distance: int` -- number of strikes above and below ATM to keep

### `select_atm(strikes, underlying_price, offset=0) -> float`

Find the strike closest to the underlying price.

- `offset=0` returns the ATM strike
- `offset=+1` returns one strike above ATM, `offset=-1` one below
- Raises `ValueError` if strikes is empty or offset is out of range
- Tie-breaking: when two strikes are equidistant from the price, return the
  lower strike (deterministic)

Parameters:
- `strikes: list[float]` -- sorted strike prices
- `underlying_price: float` -- current underlying price
- `offset: int` -- number of strikes to shift from ATM (positive = higher,
  negative = lower)

### `select_by_delta(strikes, greeks_map, target_delta, right) -> float`

Find the strike whose delta is closest to the target.

- For calls (`right="C"`): compare delta values directly (positive)
- For puts (`right="P"`): compare absolute values of delta
- Only considers strikes present in greeks_map
- Raises `ValueError` if no Greeks are available for any strike
- Tie-breaking: when two strikes have equally close delta, return the one
  closer to ATM (requires underlying_price -- see note below)

Parameters:
- `strikes: list[float]` -- available strikes (used to scope the search)
- `greeks_map: dict[float, Greeks]` -- mapping of strike price to Greeks
- `target_delta: float` -- desired delta magnitude, always positive (e.g.,
  0.30 means "30-delta"). For calls the function matches against raw delta;
  for puts it matches against abs(delta). The caller never passes negative
  values.
- `right: Literal["C", "P"]` -- option type

Note: `select_by_delta` does not need `underlying_price` for tie-breaking
because delta ties at different strikes are astronomically rare with
real market data. If they occur, the function picks the lower strike
(same rule as `select_atm`).

### `select_strike(strikes, underlying_price, right, target_delta=None, greeks_map=None, offset=0) -> float`

Unified entry point with automatic fallback.

- If `target_delta` and `greeks_map` are both provided: delegates to
  `select_by_delta`
- Otherwise: delegates to `select_atm` with the given offset
- This is the recommended function for strategy code -- pass Greeks when
  available (live trading), omit for ATM fallback (backtesting, pre-market)

Parameters:
- `strikes: list[float]`
- `underlying_price: float`
- `right: Literal["C", "P"]`
- `target_delta: float | None`
- `greeks_map: dict[float, Greeks] | None`
- `offset: int` -- only used in ATM fallback path

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Empty strikes list | `ValueError("no strikes available")` |
| No Greeks for any strike in greeks_map | `ValueError("no greeks available for any strike")` |
| Offset out of range | `ValueError("offset N out of range, only M strikes available")` |
| Two strikes equidistant from ATM | Pick the lower strike |
| Two strikes with equally close delta | Pick the lower strike |

## Testing Strategy

Approximately 15-18 tests in `packages/strategy/tests/test_strike_selector.py`:

**filter_strikes:**
- Normal filtering returns correct subset
- Empty strikes returns empty list
- max_distance boundary (all strikes within range)

**select_atm:**
- Exact ATM match
- Two equidistant strikes (tie-break to lower)
- Positive and negative offsets
- Offset out of range raises ValueError
- Empty strikes raises ValueError

**select_by_delta:**
- Normal call delta selection (e.g., target 0.30)
- Normal put delta selection (absolute value comparison)
- No Greeks available raises ValueError
- Partial Greeks (only some strikes have data)

**select_strike:**
- With greeks_map + target_delta: routes to delta-based
- Without greeks_map: routes to ATM fallback
- With target_delta but without greeks_map: routes to ATM fallback

**Integration scenario:**
- Simulate Iron Condor strike selection: select 4 strikes (put buy, put sell,
  call sell, call buy) using delta targets on realistic chain data

## What This Does NOT Do

- Does not fetch option chains or market data (caller responsibility)
- Does not compute Greeks (caller provides them)
- Does not select expiration dates (separate concern)
- Does not cache or remember previous selections
- Does not validate that strikes come from a valid OptionChain
- Does not provide high-level strategy builders (e.g., `build_iron_condor`) --
  the caller combines selector output with multi_leg factory functions

## Exports

Update `packages/strategy/src/strategy/__init__.py` to export:
`filter_strikes`, `select_atm`, `select_by_delta`, `select_strike`
