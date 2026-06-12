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

### Regime gates (any failure → REJECT with reasons)

| Gate | Rule | Source |
|------|------|--------|
| Trend strength | ADX(14) > 20; 20–25 flagged "中間態" warning, > 25 noted as confirmed trend | KB: ADX<20 趨勢指標失效 |
| Bull regime | close > SMA(200) | KB: 200MA 牛熊分界，上方只做多 |
| Higher timeframe | weekly close > weekly SMA(10) (weekly bars resampled from daily, ISO weeks) | KB: 多週期方向一致 — proxy chosen here, see Assumptions |
| Data sufficiency | ≥ 320 daily bars required (120-day BB-width percentile window on top of SMA(200)) — else SKIP, not REJECT | — |

### Volatility haircuts (do not reject; scale suggested size)

- ATR ratio = ATR(5) / ATR(20); if > 1.5 → size multiplier 0.5 (KB: 高波動縮倉50%).
- Optional VIX input (config or flag; no data feed): < 15 → 1.25, 15–25 → 1.0,
  25–35 → 0.75, > 35 → 0.5. If not provided, multiplier 1.0 and the report
  marks VIX as unchecked.

### Entry signal — 波段四重確認 (all four → CANDIDATE)

1. **Squeeze (蓄勢):** BB width (20, 2σ, SMA basis) fell below the 20th
   percentile of its trailing 120-day distribution at least once within the
   last `squeeze_lookback = 10` sessions.
2. **Trigger (突破):** today's close crosses above the BB middle band
   (yesterday close ≤ middle, today close > middle) AND band width expands
   (width_t > width_{t-1}).
3. **Volume:** today's volume > SMA(volume, 20).
4. **Momentum:** MACD(12, 26, 9) has DIF > DEA AND histogram expanding
   (hist_t > hist_{t-1}).

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

Degenerate guard: if struct_stop or ma_stop is ≤ 0 (entry below the 20-day
low buffer or below SMA(20) — cannot happen for a CANDIDATE because the
trigger requires close > BB middle = SMA(20), but can happen for WATCH
reporting), that candidate term is excluded from the `min`.

### Target and reward-risk

- T1 = the most recent pivot high above entry within the last 120 sessions.
  Pivot high = a bar whose high exceeds the highs of the 2 bars on each side.
- If no such pivot exists (price at new highs): T1 = entry + 2.5 ×
  stop_distance, flagged `t1_fallback = true`.
- RR = (T1 − entry) / stop_distance. RR < 2.5 (KB: 波段盈虧比 ≥ 1:2.5) →
  downgrade CANDIDATE to WATCH with reason "盈虧比不足".

### Position sizing

```
shares = floor(equity × risk_pct ÷ stop_distance) × atr_multiplier × vix_multiplier
```

`risk_pct` default 1.5% (KB: 波段單筆風險 1.5%). Multipliers applied to the
share count, floored.

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

### `packages/strategy/src/strategy/swing/scanner.py`

- `ScanParams` dataclass: every constant above (adx_min=20, sma_long=200,
  weekly_sma=10, squeeze_lookback=10, squeeze_pct=20, bb_window=120,
  min_rr=2.5, risk_pct=0.015, time_stop_days=(5, 15), …) with KB defaults.
- `ScanResult` dataclass: symbol, verdict, reasons list, entry, stop,
  stop_basis (which term won), t1, t1_fallback, rr, shares, multipliers,
  exit_plan (ma5/ma10/ma20 values, time-stop text), manual_checklist,
  indicator snapshot (adx, atr, bb_width_pct, …).
- `evaluate(bars: list[Bar], params: ScanParams, equity: float, vix: float | None) -> ScanResult` —
  pure function, no I/O.

### `apps/trader` wiring

- `cli.py`: add `scan` subparser (reuses `--config`; adds `--json PATH`
  optional output file).
- `config.py`: new optional `[scanner]` Pydantic section: `symbols:
  list[str]`, `equity: float`, `risk_pct: float = 0.015`, `vix: float | None
  = None`, plus optional overrides mirroring `ScanParams` fields. `scan`
  without a `[scanner]` section is a config error.
- `assembly.py`: `run_scan(config)` — `ConnectionManager` connect →
  `LiveDataHandler.fetch_history(contract, "2 Y", "1 day")` per symbol
  (existing 15 s pacing sleep applies; runtime ≈ 15 s × N symbols, stated in
  output) → `evaluate` → render console table + optional JSON dump.
  Per-symbol fetch/qualification failures mark that symbol SKIP and continue.

### Output

One summary table (symbol, verdict, entry, stop, T1, RR, shares, top reason)
sorted CANDIDATE → WATCH → REJECT → SKIP, then a detail block per
CANDIDATE/WATCH including all four confirmations, gate values, exit plan, and
the manual checklist. `--json` writes the full `ScanResult` list.

## Error handling

- TWS not reachable → single clear error before any scanning.
- Unqualifiable contract / empty history / insufficient bars → SKIP with
  reason, scan continues.
- All numeric edge cases (flat series, zero volume) must not raise; gates
  evaluate False with reason.

## Testing (TDD)

- Indicators: golden-value tests against hand-computed short series (Wilder
  ATR/ADX verified against published worked examples); property checks
  (warmup padding lengths, weekly resample boundaries).
- Rule engine: synthetic bar fixtures, one pass + one fail case per gate and
  per confirmation; stop formula boundaries (0.5×ATR floor binds, 2×ATR cap
  binds, struct vs MA vs ATR term winning); T1 pivot vs fallback; RR
  downgrade; sizing multipliers.
- App layer: `[scanner]` config validation errors; `run_scan` end-to-end with
  a fake `DataHandler` (no TWS) asserting verdicts and JSON output; CLI
  dispatch test consistent with existing subcommand tests.

## Assumptions (surfaced per AGENTS.md)

1. "多週期方向一致" is implemented as weekly close > weekly SMA(10) — the KB
   names the principle but not a formula.
2. `squeeze_lookback = 10` sessions and the pivot definition (2-bar flanks)
   are scanner parameters not specified by the KB; both sit in `ScanParams`.
3. Entry reference = latest close (scan runs after market close).
4. Long-only; shorts are out of scope (KB: 200MA 上方只做多, and the live
   system's swing allocation is long-biased).

## Out of scope (v1)

Rebound (搶反彈) mode; earnings calendar, correlation, GEX/DIX, intraday
timeframes; automatic order placement; position monitoring (live path already
owns it); any LLM usage.

## Rollback

Purely additive change (new `strategy.swing` module, new subcommand, new
optional config section). Revert the single squash-merge commit; no
migrations, no flags.
