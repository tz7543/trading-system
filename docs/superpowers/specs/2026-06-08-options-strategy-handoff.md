# 期權策略擴展 — 交接文檔

**日期：** 2026-06-08
**範圍：** `packages/strategy` 期權策略工廠 + strike 選擇模組
**基線 SHA：** `6e239b6`（工作開始前）
**當前 HEAD：** `7033bec`（11 個 commits）
**測試狀態：** 59/59 通過，ruff lint/format 乾淨

---

## 一、完成的工作

### 1. 多腿期權策略擴展（4 → 15 種）

**檔案：** `strategy/multi_leg.py`（4 個原有 + 11 個新增工廠函式）

| 類別 | 策略 | 腿數 | 備註 |
|------|------|------|------|
| 垂直價差 | `bull_call_spread` | 2 | 原有 |
| | `bear_put_spread` | 2 | 新增 — 看跌 debit |
| | `bull_put_spread` | 2 | 新增 — 看漲 credit |
| | `bear_call_spread` | 2 | 新增 — 看跌 credit |
| 波動率 | `straddle` | 2 | 原有 |
| | `strangle` | 2 | 新增 — 不同行權價 |
| 蝶式 | `call_butterfly` | 3 | 新增 — 1/-2/1 call，等距驗證 |
| | `put_butterfly` | 3 | 新增 — 1/-2/1 put，等距驗證 |
| | `iron_butterfly` | 4 | 新增 — ATM straddle + OTM wings，等距驗證 |
| 範圍 | `iron_condor` | 4 | 原有 |
| 保護/收入 | `covered_call` | 2 | 原有 |
| | `collar` | 3 | 新增 — 股票 + put + short call |
| | `protective_put` | 2 | 新增 — 股票 + put |
| | `cash_secured_put` | 1 | 新增 — 單腿 short put |
| 時間結構 | `calendar_spread` | 2 | 新增 — 跨到期日，同 strike |
| | `diagonal_spread` | 2 | 新增 — 跨到期日，不同 strike |

**設計要點：**
- 所有函式都是純工廠函式：驗證輸入 → 建立 `Leg`/`Contract` → 回傳 `Order`
- Calendar/diagonal 靠每個 `Leg` 各自的 `Contract.expiry` 支援跨到期日
- Butterfly 類策略（含 iron_butterfly）都有等距驗證（`1e-9` 容差）
- `quantity < 1` 和 strike 順序驗證使用描述性 `ValueError`

### 2. 動態 Strike 選擇模組

**檔案：** `strategy/strike_selector.py`（4 個純函式）

| 函式 | 用途 |
|------|------|
| `filter_strikes(strikes, price, max_distance)` | 縮小 strike 範圍到 ATM ± N 檔 |
| `select_atm(strikes, price, offset)` | ATM 選擇 + 偏移（等距 tie-break 取較低 strike） |
| `select_by_delta(strikes, greeks_map, target_delta, right)` | Delta-based 精確選擇（put 用 abs(delta)） |
| `select_strike(strikes, price, right, target_delta?, greeks_map?, offset?)` | 統一入口：有 Greeks 走 delta-based，否則 fallback ATM |

**設計要點：**
- 純函式，無狀態，無 IO，無新依賴（只用 `core.models.Greeks`）
- `select_by_delta` 用 `round(distance, 6)` 消除 IEEE 754 浮點誤差
- strategy 不依賴 market-data 或 tws-client — Greeks 由呼叫端注入

---

## 二、文件產出

| 檔案 | 類型 |
|------|------|
| `docs/superpowers/specs/2026-06-08-dynamic-strike-selection-design.md` | 設計規格 |
| `docs/superpowers/plans/2026-06-08-expand-option-strategies.md` | 實作計畫（已完成） |
| `docs/superpowers/plans/2026-06-08-dynamic-strike-selection.md` | 實作計畫（已完成） |

---

## 三、延續工作完成狀態（2026-06-08）

深度研究識別了 4 項高價值增強。原始交接時已完成 A，後續已完成 B、C、D
的 spec → plan → implementation → verification 循環。

### B. Greeks 部位管理（已完成）

**新增檔案：**
- `docs/superpowers/specs/2026-06-08-greeks-position-management-design.md`
- `docs/superpowers/plans/2026-06-08-greeks-position-management.md`
- `packages/strategy/src/strategy/delta_hedge.py`
- `packages/strategy/tests/test_delta_hedge.py`

**完成內容：**
- `DeltaHedgeStrategy` 透過注入的 `greeks_provider` 讀取組合 Greeks。
- 計算 delta-neutral 股票對沖數量：`round(target_delta - current_delta)`。
- 以 `SignalEvent.direction="ADJUST"` 發出調整訊號。
- 訊號 context 包含 `proposed_greeks`，讓既有 `PreTradeValidator` 驗證調整後 delta。
- Gamma-aware cooldown：高 gamma 使用較短再平衡間隔。
- `apps/trader/tests/test_assembly.py` 驗證 `ADJUST` 訊號可走到 live app 的 `LiveGateway` mock 下單路徑。

### C. IV Rank / IV Percentile 進場邏輯（已完成）

**新增檔案：**
- `docs/superpowers/specs/2026-06-08-iv-rank-entry-design.md`
- `docs/superpowers/plans/2026-06-08-iv-rank-entry.md`
- `packages/strategy/src/strategy/iv_metrics.py`
- `packages/strategy/src/strategy/iv_entry.py`
- `packages/strategy/tests/test_iv_metrics.py`
- `packages/strategy/tests/test_iv_entry.py`

**完成內容：**
- 資料來源決策：第一版使用本系統自行累積的 option tick `model_iv` 歷史；
  `storage.TickReader` 與 `market_data.HistoricalDataHandler` 已能讀回
  `MarketEvent.model_greeks.implied_vol`。外部 IV vendor 留作後續 provider。
- `IVMetrics` dataclass。
- `calculate_iv_rank()`、`calculate_iv_percentile()`、`calculate_iv_metrics()`。
- 指標使用 0-100 scale，符合 `IV Rank > 70` 的策略語義。
- `IVRankEntryStrategy` 在高 IV Rank 時透過注入的 order factory 發出 `ENTER` 訊號。
- strategy 不依賴 `storage`、`market-data`、IB 或 live/backtest mode。

### D. Rolling / 提前行權處理（已完成第一版 primitives）

**新增/修改檔案：**
- `docs/superpowers/specs/2026-06-08-assignment-rolling-design.md`
- `docs/superpowers/plans/2026-06-08-assignment-rolling.md`
- `core.events.AssignmentEvent`
- `packages/strategy/src/strategy/assignment.py`
- `packages/strategy/tests/test_assignment.py`
- `LiveGateway.on_assignment()`

**完成內容：**
- 新增 `AssignmentEvent`，包含 assigned contract、assigned contracts、stock quantity、
  account 與 underlying price。
- `assignment_stock_quantity()` 依 short call/put assignment 語義計算股票交割數量。
- `apply_assignment()` 更新 `Position`：減少被 assignment 的 short option 腿，並新增或合併股票腿。
- `is_partial_assignment()` 偵測部分 assignment。
- `build_roll_order()` 建立 close existing leg + open replacement leg 的兩腿 roll order。
- `LiveGateway.on_assignment()` 提供 execution 層 typed assignment event 發布 hook。

**仍留待後續 live smoke test：**
- 自動從 IB `execDetailsEvent` / `positionEvent` 推斷 assignment 的 adapter。此版已提供
  typed event 與 gateway hook，避免在未驗證 IB callback 細節前寫入不可靠推斷邏輯。

### Verification

```
uv run pytest packages/core/tests packages/strategy/tests packages/execution/tests -q
# 127 passed

uv run pytest -q
# 204 passed

uv run ruff check .
# All checks passed

uv run ruff format --check .
# 82 files already formatted
```

---

## 四、Commit 歷史

```
7033bec feat(strategy): export strike selector functions
c3752f7 test(strategy): add iron condor strike selection integration test
07612bb feat(strategy): add strike selector functions (filter, atm, delta, unified)
88187e8 docs(strategy): add dynamic strike selection implementation plan
9c68e0e docs(strategy): add dynamic strike selection design spec
2d6bc10 fix(strategy): add iron_butterfly equidistant validation and missing tests
50779ed feat(strategy): export all 15 multi-leg strategy factories
761a840 feat(strategy): add calendar_spread, diagonal_spread factories
179e413 feat(strategy): add collar, protective_put, cash_secured_put factories
8f2b705 feat(strategy): add strangle, call_butterfly, put_butterfly, iron_butterfly factories
31e4d56 feat(strategy): add bear_put_spread, bull_put_spread, bear_call_spread factories
```

---

## 五、已知技術細節

- **Pyright 報 `reportMissingImports`** — uv workspace 的 `src/` layout 在 IDE 中不解析，runtime 正常。非真實問題。
- **`select_by_delta` 的浮點修正** — spec 原本用 `(distance, strike)` 排序，實作加了 `round(distance, 6)` 避免 `0.0999...8 < 0.1000...3` 打破 tie-break 語義。
- **Calendar/diagonal 到期日驗證** — 只驗證 `near_expiry != far_expiry`，不驗證哪個更早（呼叫端責任，因為日期格式可能是 `YYYYMMDD` 字串或其他格式）。
