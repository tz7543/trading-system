# Swing Scanner Design (2026-06-12)

## Goal

Add a `scan` CLI subcommand that evaluates a configured list of US stock
symbols against the swing-trading rule set from the knowledge base and prints,
for each symbol: a verdict (CANDIDATE / WATCH / REJECT / SKIP), entry
reference price, stop-loss, T1 target, reward-risk ratio, suggested position
size, and an exit plan. The scanner is a deterministic, pure-Python rule
engine — no LLM involvement, no order placement, no position management.

Knowledge sources (memory): Obsidian vault synthesis 2026-06-09, swing
research 2026-06-09. Rebound (搶反彈) tactics are explicitly out of scope for
v1.

## Rule Set

All prices are daily bars. The scanner is long-only (200SMA rule: above the
line, longs only). Entry reference price = latest daily close; the report
notes that next-day entries must re-check RR against the actual fill price.

Boundary convention: every threshold below states its equality behavior
explicitly; unit tests must pin each equality edge.

### Regime gates (any failure → REJECT with reasons)

| Gate | Rule | Source |
|------|------|--------|
| Trend strength | pass iff ADX(14) > 20 (exactly 20 fails); 20 < ADX ≤ 25 flagged "中間態" warning; ADX > 25 noted as confirmed trend | KB: ADX<20 趨勢指標失效 |
| Bull regime | pass iff close > SMA(200) | KB: 200MA 牛熊分界，上方只做多 |
| Higher timeframe | pass iff weekly close > weekly SMA(10) (weekly bars resampled from daily by ISO calendar week) | KB: 多週期方向一致 — proxy chosen here, see Assumptions |
| Data sufficiency | ≥ 340 daily bars required (covers SMA(200), and a fully populated 120-value BB-width distribution including its 20-bar warmup, with margin) — else SKIP, not REJECT | — |

### Volatility haircuts (do not reject; scale suggested size)

- ATR ratio = ATR(5) / ATR(20); if ratio > 1.5 (strict) → size multiplier 0.5
  (KB: 高波動縮倉50%).
- Optional VIX input (config; no data feed). Bands are half-open
  `[low, high)`: vix < 15 → 1.25; 15 ≤ vix < 25 → 1.0; 25 ≤ vix < 35 → 0.75;
  vix ≥ 35 → 0.5. If not provided, multiplier 1.0 and the report marks VIX as
  unchecked.

### Entry signal — 波段四重確認 (all four → CANDIDATE)

1. **Squeeze (蓄勢):** BB width (20, 2σ, SMA basis) was in squeeze at least
   once within the last `squeeze_lookback = 10` sessions, today inclusive
   (sessions t−9 … t). "In squeeze" at session s: width(s) ≤ the 20th
   percentile (nearest-rank method: the ⌈0.2 × N⌉-th smallest, ties inclusive)
   of the width distribution over the 120 sessions ending at and including s.
2. **Trigger (突破):** today's close crosses above the BB middle band
   (yesterday close ≤ middle(t−1), today close > middle(t)) AND band width
   expands (width(t) > width(t−1)).
3. **Volume:** today's volume > SMA(volume, 20) (strict).
4. **Momentum:** MACD(12, 26, 9) has DIF > DEA AND histogram expanding
   (hist(t) > hist(t−1)).

If gates pass but only the squeeze condition holds (no trigger yet) → WATCH
("蓄勢中"). Any other partial combination → REJECT listing the failed
confirmations.

### Stop-loss (KB formula)

```
atr_stop      = 2 × ATR(14)
struct_stop   = entry − (min(low, last 20 sessions) − 0.1 × ATR(14))
ma_stop       = entry − SMA(20)
stop_distance = max(0.5 × ATR(14), min(atr_stop, struct_stop, ma_stop))
stop_distance = min(stop_distance, 2 × ATR(14))   # hard cap
stop_price    = entry − stop_distance
```

Degenerate guards:

- A struct_stop or ma_stop term that is ≤ 0 (possible for WATCH reporting;
  impossible for CANDIDATE because the trigger requires close > BB middle =
  SMA(20)) is excluded from the `min`.
- If ATR(14) = 0 or the resulting stop_distance ≤ 0 (flat/degenerate series),
  the symbol is verdict SKIP with reason "degenerate price series". RR and
  share count are only ever computed when stop_distance > 0 — no division by
  zero path exists.

### Target and reward-risk

- T1 = the most recent pivot high above entry within the search window of the
  last 120 sessions excluding the final 2 sessions (a pivot needs 2 confirmed
  bars on its right, so t−1 and t are unconfirmable). Pivot high = a bar
  whose high is strictly greater than the highs of the 2 bars on each side;
  equal highs (flat tops) do not qualify and fall through to the fallback.
- If no such pivot exists (e.g. price at new highs or flat-top structure):
  T1 = entry + 2.5 × stop_distance, flagged `t1_fallback = true`.
- RR = (T1 − entry) / stop_distance. RR < 2.5 (KB: 波段盈虧比 ≥ 1:2.5) →
  downgrade CANDIDATE to WATCH with reason "盈虧比不足".

### Position sizing

```
shares = floor( floor(equity × risk_pct ÷ stop_distance) × atr_multiplier × vix_multiplier )
```

Sizing inputs (`equity`, `risk_pct` default 1.5% per KB, optional `vix`) come
ONLY from `[scanner]` config — they are not duplicated in `ScanParams`
(single authority; `ScanParams` holds rule/indicator constants only).

### Exit plan (informational output only)

- Three defense lines with current values: SMA(5) (跌破減倉 50%), SMA(10)
  (跌破減至 25%), SMA(20) (收盤跌破全出).
- T1 reached → sell 30–50%, move stop to cost.
- Time stops: ≤ 5 sessions with unrealized gain < 0.5R → halve; ≤ 15 sessions
  without reaching T1 → exit all.

### Manual checklist (not automatable in v1; printed per CANDIDATE)

- 距財報 ≥ 3 天 (no earnings calendar feed).
- 與既有持倉相關性 < 0.7 (no portfolio correlation data).
- 重大事件日 (FOMC/CPI) 自行確認.

## Architecture

Dependency direction follows AGENTS.md: the rule engine depends only on
`core`; data access is injected at the app layer via the existing
`DataHandler` abstraction.

### `packages/strategy/src/strategy/swing/indicators.py`

Pure functions over `list[float]` / `list[core.Bar]`, no third-party deps:
`sma`, `ema`, `atr` (Wilder), `adx` (Wilder 14), `bollinger` (middle/upper/
lower/width), `percentile_rank`, `macd` (dif/dea/hist series), `pivot_highs`,
`resample_weekly`. Each returns full series aligned to input (None-padded
warmup) so the rule engine can inspect t and t−1.

**Timestamp type caveat:** ib_async delivers `datetime.date` (not `datetime`)
for `"1 day"` bars, so `Bar.timestamp` holds a `date` at runtime despite its
`datetime` annotation. `resample_weekly` and any timestamp-touching code MUST
accept `date | datetime`, keying ISO weeks via `.isocalendar()` (valid on
both) and never calling time-of-day or tzinfo APIs.

### `packages/strategy/src/strategy/swing/scanner.py`

- `ScanParams` dataclass: rule/indicator constants only (adx_min=20,
  sma_long=200, weekly_sma=10, squeeze_lookback=10, squeeze_pct=20,
  bb_pct_window=120, min_bars=340, min_rr=2.5, atr_ratio_max=1.5,
  pivot_window=120, …) with KB defaults. No sizing fields.
- `ScanResult` dataclass: symbol, verdict, reasons list, entry, stop,
  stop_basis (which term won), t1, t1_fallback, rr, shares, multipliers,
  exit_plan (ma5/ma10/ma20 values, time-stop text), manual_checklist,
  indicator snapshot (adx, atr, bb_width_pct, …).
- `evaluate(symbol: str, bars: list[Bar], params: ScanParams, equity: float,
  risk_pct: float, vix: float | None) -> ScanResult` — pure function, no
  I/O. `symbol` is an explicit argument so empty/short `bars` still yield a
  well-formed SKIP result.

### `apps/trader` wiring

- `cli.py`: add `scan` subparser (reuses `--config`; adds `--json PATH`
  optional output file), mirroring the existing subcommand pattern.
- `config.py`: new optional `[scanner]` Pydantic section with
  `extra="forbid"` like every other section: `symbols: list[str]` (non-empty),
  `equity: float` (> 0), `risk_pct: float = 0.015`, `vix: float | None =
  None`. Nothing else — `ScanParams` constants are not exposed in config for
  v1 (YAGNI). Modeled as `scanner: ScannerConfig | None = None` on
  `TraderConfig`; running `scan` without the section is a config error
  (mirrors the existing `_require_strategy` pattern).
- `assembly.py`: `run_scan(config, data_handler: DataHandler | None = None)`.
  When `data_handler` is None (production), build `ConnectionManager`,
  `await connect()`, and wrap `LiveDataHandler(conn.ib)`; tests inject a fake
  `DataHandler` and never touch TWS. Per symbol:
  `fetch_history(contract, "2 Y", "1 day")` (~504 bars; the existing
  hardcoded 15 s pacing sleep, `useRTH=True`, `whatToShow="TRADES"` are
  accepted as-is and non-configurable) → `evaluate` → collect results.
  Fetch/qualification failures mark that symbol SKIP and the scan continues.
  Runtime ≈ 15 s × N symbols is printed up front; if N > 40 a warning notes
  the expected duration (soft cap, not enforced).

### Output

One summary table (symbol, verdict, entry, stop, T1, RR, shares, top reason)
sorted CANDIDATE → WATCH → REJECT → SKIP, then a detail block per
CANDIDATE/WATCH including all four confirmations, gate values, exit plan, and
the manual checklist.

`--json` schema (explicit, test-assertable): top level
`{"generated_at": "<ISO-8601>", "results": [<result>, …]}` where each result
is `dataclasses.asdict(ScanResult)` with: dates serialized as `YYYY-MM-DD`
strings, floats rounded to 4 decimals, `None` preserved as JSON null, verdict
as plain string.

## Error handling

- TWS not reachable → single clear error before any scanning (only when no
  fake handler injected).
- Unqualifiable contract / empty history / insufficient bars / degenerate
  series → SKIP with reason, scan continues.
- All numeric edge cases (flat series, zero volume) must not raise; gates
  evaluate False with reason, and the stop-distance guard above prevents any
  division by zero.

## Testing (TDD)

- Indicators: golden-value tests against a fixed ~30-bar synthetic OHLC
  series EMBEDDED in the test file, with expected Wilder ATR/ADX values
  derived step-by-step in comments (tolerance 1e-6) — no external fixture
  dependency; property checks (warmup padding lengths, ISO-week resample
  boundaries, `date` vs `datetime` timestamps both accepted).
- Rule engine: synthetic bar fixtures, one pass + one fail case per gate and
  per confirmation, plus equality-edge tests for every boundary (ADX = 20,
  VIX = 15/25/35, ratio = 1.5, width = exact 20th percentile); stop formula
  boundaries (0.5×ATR floor binds, 2×ATR cap binds, struct vs MA vs ATR term
  winning, ATR = 0 → SKIP); T1 pivot vs flat-top fallback vs last-2-sessions
  exclusion; RR downgrade; sizing multiplier flooring.
- App layer: `[scanner]` config validation (missing section, empty symbols,
  extra keys forbidden); `run_scan` end-to-end with an injected fake
  `DataHandler` (no TWS) asserting verdicts, SKIP-on-failure continuation,
  and the exact `--json` schema; CLI dispatch test consistent with existing
  subcommand tests.

## Assumptions (surfaced per AGENTS.md)

1. "多週期方向一致" is implemented as weekly close > weekly SMA(10) — the KB
   names the principle but not a formula.
2. `squeeze_lookback = 10`, the nearest-rank percentile method, and the pivot
   definition (strict 2-bar flanks) are scanner parameters/conventions not
   specified by the KB; all live in `ScanParams` or are documented here.
3. Entry reference = latest close (scan runs after market close).
4. Long-only; shorts are out of scope (KB: 200MA 上方只做多, and the live
   system's swing allocation is long-biased).

## Out of scope (v1)

Rebound (搶反彈) mode; earnings calendar, correlation, GEX/DIX, intraday
timeframes; automatic order placement; position monitoring (live path already
owns it); config exposure of `ScanParams` constants; any LLM usage.

## Rollback

Purely additive change (new `strategy.swing` module, new subcommand, new
optional config section). Revert the single squash-merge commit; no
migrations, no flags.
