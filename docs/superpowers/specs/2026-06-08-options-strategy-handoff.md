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

## 三、未完成的工作（按優先順序）

深度研究識別了 4 項高價值增強，已完成前 1 項，剩餘 3 項各需獨立的
brainstorming → spec → plan → implementation 循環。

### B. Greeks 部位管理（下一個）

**現況：** `RealTimeMonitor` 已有 delta/vega 漂移監控和告警，但只做監控不做動作。
**缺什麼：**
- Delta-neutral rebalance 邏輯（計算對沖數量 → 提交調整訂單）
- Gamma-aware 再平衡頻率控制（Gamma 越高 → 越頻繁調整）
- `SignalEvent.direction="ADJUST"` 已支援，但沒有策略邏輯觸發它
**依賴：** `LiveGateway`（execution）需已可用才能測試完整 adjust 流程

### C. IV Rank / IV Percentile 進場邏輯

**現況：** `HistoricalDataHandler` 存 tick 資料含 `model_iv`，但只來自 live push。
**缺什麼：**
- 52 週 IV 歷史資料來源（IB `reqHistoricalData` 不直接提供 IV 歷史）
- IV Rank 和 IV Percentile 計算模組
- 策略進場訊號整合（IV Rank > 70 → 適合賣權策略）
**阻塞：** 需先決定 IV 歷史資料來源（自行蒐集 vs 外部資料）

### D. Rolling / 提前行權處理

**現況：** 無相關事件類型或邏輯。
**缺什麼：**
- `AssignmentEvent` 事件類型
- Roll-leg 建構器（關閉到期腿 + 開啟下期腿）
- 部位重組邏輯（partial assignment 偵測）
**依賴：** 需 execution 層的 assignment callback 支援

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
