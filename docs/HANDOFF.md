# Trading System 交接文件

**日期：** 2026-06-10
**狀態：** 實盤路徑硬化（PR #1）已合併；Paper TWS manual smoke test 待執行
**上一版：** 2026-06-05（Phase 4C 完成版，本文件已全面更新取代）

---

## 1. 專案概述

美股量化交易系統，透過 Interactive Brokers TWS API 進行股票與期權交易。Python 3.11+ monorepo，使用 `uv workspaces` 管理。Live trading 與 backtest 共用同一套策略代碼，透過 DI 切換 DataHandler 與 Executor。

**設計規格：**
- 系統架構：`docs/superpowers/specs/2026-06-04-tws-monorepo-design.md`
- 實盤路徑硬化：`docs/superpowers/specs/2026-06-10-live-path-hardening-design.md`
  （含完整的 review gate 修訂紀錄；對應實作計畫在
  `docs/superpowers/plans/2026-06-10-live-path-hardening.md`）

---

## 2. 目前規模

| 指標 | 數值 |
|------|------|
| Source files | 50 |
| Test files | 42 |
| Source LoC | ~4,400 |
| Test LoC | ~6,800 |
| Tests | 315（全部通過） |
| Commits | 62 |

---

## 3. Monorepo 結構與依賴方向

```
packages/
  core/          ← 零外部依賴，所有 package 依賴它
  storage/       ← Parquet tick 讀寫、DuckDB 決策日誌、SQLite 訂單/成交/狀態
  market-data/   ← HistoricalDataHandler（回測用 Parquet 讀取）
  strategy/      ← BaseStrategy ABC、多腿期權工廠、Greeks 計算
  risk/          ← PreTradeValidator → RealTimeMonitor → CircuitBreaker
  backtest/      ← SimulatedExecutor、BacktestRunner、PerformanceMetrics
  tws-client/    ← IB TWS API adapter（ib_async）+ AccountState
  execution/     ← LiveGateway（實盤下單 + 訂單狀態閉環）
apps/
  trader/        ← 系統入口、config、live/backtest assembly、watchdog
```

依賴方向（單向無循環）：

```
apps/trader
    ├──► execution  ──► tws-client ──► core
    ├──► strategy   ──────────────────► core
    ├──► backtest   ──► market-data ──► core
    ├──► risk       ──────────────────► core
    └──► storage    ──────────────────► core
```

---

## 4. 2026-06-10 實盤路徑硬化（PR #1，squash commit f7a4a4e）

### 4.1 背景

2026-06-10 全庫稽核確認實盤路徑有四個 Critical（C1-C4）與兩個 High（H2、H3）
缺陷。PR #1 全數修復，測試 244 → 315。開發流程：spec/plan 各經 3 輪
opus+codex review gate、每任務 TDD + 雙階段審查（規格符合性 + 品質）、
PR 級雙 AI 終審。

### 4.2 修復對照表

| 稽核缺陷 | 修復 | 關鍵檔案 |
|---|---|---|
| C1 訂單身分斷裂（orders 存 UUID、fills 存 TWS orderId，永遠 join 不上） | canonical `order_id` 在 `OrderEvent` 鑄造一次貫穿全鏈；`broker_order_id` 經 SUBMITTED 狀態回填；SQLite 舊檔自動 ALTER 遷移 | `core/events.py`、`storage/trade_store.py`、`execution/live_gateway.py` |
| C2 拒單/取消/部分成交無事件 | 新 `OrderStatusEvent`（SUBMITTED/PARTIAL/FILLED/CANCELLED/REJECTED）；增量 per-execution fills；gateway 內部錯誤發布 REJECTED | `execution/live_gateway.py`、`storage/subscriber.py` |
| C3 風控數據失真（greeks 恆 0、現金流當 equity） | equity/margin_cushion/margin_info 改用 IB accountSummary；AppRiskState 改 contract_key 沖銷 + per-contract greeks 聚合；equity None → 拒訊號 + 跳過監控 | `tws_client/account.py`、`apps/trader/.../assembly.py` |
| C4 重連後行情靜默死亡 | streams 與重連訊號競速（asyncio.wait FIRST_COMPLETED），重連後自動取消卡死 streams 並重訂閱；MarketDataWatchdog 60s 無 tick 告警（per-contract key） | `assembly.py`、`tws_client/connection.py`、`apps/trader/.../watchdog.py` |
| H2 DTE/保證金警報死代碼 | `min_dte`/`margin_cushion` 接入 `RiskPipeline.check_now()` | `assembly.py` |
| H3 風控只在成交時檢查 | 週期性 `risk_check_loop`（預設 30s，config 可調） | `assembly.py`、`cli.py` |
| （安全網） | paper 守門：非 {7497, 4002} port 需 `IB_CONFIRM_LIVE=YES`；pre-commit hook | `cli.py`、`scripts/githooks/pre-commit` |

### 4.3 已知限制（刻意接受，smoke test 時對照）

1. **非終態訂單的 gateway closure 殘留**：斷線後未收到終態的訂單，其
   fillEvent handler 與 closure 留存至 session 結束（每單一筆，有界）。
   重連後的訂單對帳屬後續工作。
2. **增量 FillEvent 的 commission 可能為 0.0**：IB 的 commissionReport 在
   fillEvent 之後才到達。live equity 用 NetLiquidation，不依賴自算 commission；
   儲存層精確對帳屬未來工作。
3. **backtest equity 仍為現金流近似**（含 multiplier 修正但無 mark-to-market）；
   live 路徑不使用它。
4. **平倉訂單仍計入 max_position_size**（方向盲點）：接近部位上限時，
   減倉單可能被誤擋。既有語意，未修。
5. **min_dte 用 UTC 日界**：跨 UTC 午夜時 DTE 可能與交易所當地日差一天。
   對 gamma 風險警示帶可接受。

---

## 5. 關鍵設計決策

### 5.1 EventBus 架構（更新後事件流）

```
MarketEvent ──► Strategy.on_market() ──► SignalEvent
                                            │
                              RiskPipeline.on_signal()
                              （熔斷檢查 → equity-None 守衛 → PreTradeValidator
                                [含 margin_info] → DecisionLogger）
                                            │
                                       OrderEvent（自帶 canonical order_id）
                                            │
                        LiveGateway / SimulatedExecutor
                              │                    │
                    OrderStatusEvent          FillEvent（增量、帶 strategy_id）
                    （SUBMITTED/PARTIAL/           │
                     FILLED/CANCELLED/        StorageSubscriber（orders/fills join）
                     REJECTED）                AppRiskState（沖銷 + greeks）
                              │               RiskPipeline.on_fill → check_now()
                    StorageSubscriber（order_status 表 + broker_order_id 回填）
                    RiskPipeline.on_order_status（REJECTED/CANCELLED → AlertEvent）
                              │
                    AlertEvent ──► logger.warning（半自動：人工監督）
```

`EventBus.publish()` 是 async，依序呼叫 handler；handler 例外被 bus 吞掉並記
log（gateway 因此自行 try/except 並發布 REJECTED，不依賴 bus 傳播）。

### 5.2 訂單狀態映射規則（live_gateway）

- 終態（ib_async DoneStates：Filled/Cancelled/ApiCancelled/Inactive）才判定
  REJECTED/CANCELLED：看 `trade.log` **最後一條**——errorCode 非零 → REJECTED，
  否則 CANCELLED（存活期警告後的人工取消不會誤判）。
- 非終態：filled == 0 → SUBMITTED；filled > 0 → PARTIAL（不會倒退）。
- 去重 memo key =（派生狀態, filled_quantity）；下單時預埋 ("SUBMITTED", 0)
  防 IB 回聲重複。
- **終態清理只拆 statusEvent handler**——fillEvent handler 刻意保留：TWS 的
  execDetails 與 orderStatus 無順序保證，Filled 先到時晚到的成交明細仍須發布
  （PR 終審 Critical 修復）。

### 5.3 風控真值來源（半自動設計）

- equity = IB NetLiquidation；margin_cushion = IB Cushion tag（fallback 計算）；
  margin_info = FullInitMarginReq/FullMaintMarginReq/EquityWithLoanValue →
  進 PreTradeValidator 的 max_margin_utilization 檢查。
- `AccountState.start()` 先 accountSummaryAsync 快照、再訂閱 accountSummaryEvent
  持續更新。注意：`accountSummaryAsync()` 不接受 tag 參數，底層請求已含
  完整 tag 集（**Cushion 是否實際出現需在 paper smoke test 驗證**）。
- equity 為 None（帳戶資料未就緒/斷流）→ 拒絕新訊號 + 跳過監控，
  **絕不 fallback 0.0**（會誤觸發回撤熔斷）。
- RealTimeMonitor 無狀態：條件持續期間每次 check 都重發警報（per-fill +
  每 30s）。未來加警報 sink（如推播）需自帶去重。

### 5.4 per-contract 行情身分

期權 MarketEvent 的 symbol 是標的代碼，同標的多腿會塌縮。解法：
`contract_key()`（STK → "AAPL"；OPT → "AAPL|20260119|150.0|C"）+
`MarketEvent.contract` 欄位 + `StorageSubscriber.last_market_by_contract()`。
greeks 聚合、tick 分區路由、watchdog 全部按 contract key 運作。

### 5.5 重連自動重訂閱（C4 核心）

`MarketDataFeed` 的 stream 是無限 async generator（斷線時卡在 `queue.get()`
永不返回），所以 `LiveApp.run_market_data()` 用 `asyncio.wait(FIRST_COMPLETED)`
把「發布任務」與「重連訊號」競速：重連先到 → cancel 卡死的 streams
（generator finally 會跑 cancelMktData + 歸還訂閱額度）→ sticky Event
clear → 發 restart alert → 重訂閱。`ConnectionManager._on_disconnect` 有
running-task guard（不疊加重連任務）；`on_reconnected` callbacks 各自
try/except 隔離。

### 5.6 歷史設計決策（沿用 2026-06-05 版）

- **DataHandler DI**：strategy 不 import 實作；live 用 LiveDataHandler
  （tws-client）、backtest 用 HistoricalDataHandler（market-data）。
- **LiveDataHandler 放 tws-client 非 market-data**：保持 market-data 不依賴
  tws-client（使用者決策）。
- **MarketDataFeed.subscribe 是普通 method**：eager 檢查訂閱上限後回傳
  async generator（generator body 延遲執行，上限檢查不能放裡面）。
- **eventkit 同步 callback → async 橋接**：`queue.put_nowait` + async generator；
  gateway 用 `asyncio.ensure_future` + `_pending_tasks` set 防 GC。
- **BAG 下單 con_id 保護**：leg.con_id==0 → 發布 REJECTED（先
  `OptionChainService.qualify()`）。BAG 成交按個別 leg 合約回報，
  `fill.contract` 即正確歸屬。
- **LiveGateway bus 訂閱在 assembly 完成**（非 `__init__`）。

---

## 6. IB TWS API 注意事項

| 項目 | 說明 |
|------|------|
| Pacing | Historical data 每次 reqHistoricalDataAsync 後 sleep 15s |
| 訂閱上限 | MarketDataFeed 預設 max=100，超過 raise SubscriptionLimitError |
| 每日斷線 | TWS ~23:45 EST 關閉；ConnectionManager 指數退避重連（30s→300s），重連後自動重訂閱行情 |
| BAG 價格符號 | `_combo_limit_price()` 處理：is_credit=True 且價格為正 → 取負（API 慣例：BUY 動作下負 lmtPrice = 收權利金） |
| NonGuaranteed | BAG 單自動帶 `smartComboRoutingParams=[TagValue("NonGuaranteed","1")]` |
| qualifyContracts | BAG 下單前必須 qualify，con_id=0 會收到 REJECTED 狀態事件 |
| Greeks tick | Live 用 `model_greeks`（tick 13）；backtest 計算式 Greeks 待實作 |
| Paper 守門 | port ∈ {7497, 4002} 直接放行；其他 port 需環境變數 `IB_CONFIRM_LIVE=YES` 否則啟動即拒 |
| execDetails vs orderStatus | 兩條 callback 流無順序保證——fill handler 終態後仍保留即為此故 |

---

## 7. 測試架構

所有 tws-client 和 execution 測試 **mock ib_async.IB**，驗證轉換邏輯和控制流。

關鍵 mock 模式：
- `eventkit.Event` — 用真實 Event（非 MagicMock，`+=` 行為不同）；
  `ibi.Trade()` 會自動建立真實 events
- `TradeLogEntry(time, status, message, errorCode)` — 拒單 fixture 必須照
  §5.2 映射規則模擬（終態 + 最後一條非零 errorCode）
- `asyncio.sleep` — patch 掉避免真實等待
- 無限 stream 場景用 `HangingDataHandler`（卡在 `Event().wait()`），
  有限 stream 用 `CountingDataHandler` —— 兩者覆蓋 run_market_data 的
  兩個分支
- CLI 測試是**同步** def（`cli.main` 內部 `asyncio.run`，async 測試會雙重 loop）

### Pre-commit hook

```bash
git config core.hooksPath scripts/githooks   # 啟用（主 checkout 已設定）
```
每次 commit 前自動跑 `ruff check .` + `pytest -q`。

---

## 8. 常用指令

```bash
uv sync                              # 安裝所有 workspace 依賴
uv run pytest -q                     # 跑全部 315 個測試
uv run pytest packages/execution/    # 跑單一 package
uv run ruff check .                  # Lint
uv run python apps/trader/main.py validate-config
uv run python apps/trader/main.py backtest
uv run python apps/trader/main.py live    # 需 [strategy] + [[contracts]] config
```

---

## 9. 檔案速查（PR #1 後新增/重點變更標 ★）

```
packages/core/src/core/
  models.py          Contract, Leg, Order, Greeks, Position, RiskLimits,
                     MarginInfo, ★contract_key()
  events.py          MarketEvent(★contract), SignalEvent, OrderEvent(★order_id),
                     FillEvent(★strategy_id), ★OrderStatusEvent, AlertEvent
  bus.py / clock.py / data_handler.py / partitions.py

packages/tws-client/src/tws_client/
  connection.py      ConnectionManager（★重連 guard + on_reconnected callbacks）
  ★account.py        AccountState（equity / margin_cushion / margin_info）
  converters.py      ticker_to_market_event（★帶 contract）
  market_feed.py / live_data.py / option_chain.py

packages/execution/src/execution/
  live_gateway.py    ★全面重寫：狀態閉環、增量 fills、_derive_status、
                     終態清理（保留 fill handler）

packages/storage/src/storage/
  trade_store.py     ★canonical ID、broker_order_id 遷移、order_status 表
  subscriber.py      ★OrderStatusEvent 訂閱、last_market_by_contract、
                     contract 優先 tick 路由
  tick_writer.py / tick_reader.py（★事件帶 contract）/ decision_logger.py

packages/risk/src/risk/
  pre_trade.py       ★按 proposed legs 計數 + margin_info 檢查啟用
  monitor.py / circuit_breaker.py

packages/backtest/src/backtest/
  executor.py        ★canonical order_id/strategy_id 透傳
  runner.py / metrics.py

apps/trader/src/trading_app/
  assembly.py        ★AppRiskState 重做（沖銷/greeks/min_dte）、RiskPipeline
                     （check_now/on_order_status/equity-None 守衛）、LiveApp
                     （重連迴圈/risk_check_loop/watchdog_loop）、log_alerts
  ★watchdog.py       MarketDataWatchdog（per-contract staleness）
  cli.py             ★paper 守門、三 task 生命週期（cancel→gather→close）
  config.py          ★stale_data_seconds、check_interval_seconds

scripts/githooks/pre-commit   ★ruff + pytest
```

---

## 10. 下一步

### 10.1 Manual Paper TWS Smoke Test（最優先）

原 Phase 4B 清單 + PR #1 新增驗證點：

1. ConnectionManager.connect() 連接 paper TWS（port 7497）
2. 斷線重連（kill TWS → 重啟）→ **驗證行情自動重訂閱 + restart alert**
3. Live quote 訂閱（AAPL bid/ask/last）→ **驗證 MarketEvent.contract 附掛**
4. Option Greeks（tick 13）→ **驗證 portfolio_greeks 非零**
5. Option chain 查詢 + qualify
6. Historical data + pacing 驗證
7. 單腿 LMT 委託 → **驗證 SUBMITTED → FILLED 狀態事件 + orders/fills join**
8. **故意觸發拒單**（如超出購買力）→ 驗證 REJECTED 事件 + AlertEvent + order_status 表
9. BAG 委託（bull call spread）→ **驗證 per-leg fill 歸屬**
10. Credit spread 負 lmtPrice
11. **AccountState：確認 accountSummary 實際回傳 Cushion tag**（spec 註記的
    待驗證點；若缺失，fallback 計算路徑需確認 EquityWithLoanValue/
    FullMaintMarginReq 存在）
12. **watchdog**：停掉某合約行情 60s → 驗證 stale alert
13. **paper 守門**：把 config port 改 7496 啟動 → 應拒絕

執行時對照 §4.3 已知限制，區分新 bug 與已記錄行為。

### 10.2 稽核 backlog（M2/M3，未排程）

- 決策日誌無條件記錄（目前無行情快照時跳過——稽核 H4）
- TickWriter flush 改 asyncio.to_thread + 記憶體 batch counter（稽核 H5/M4）
- 歷史資料缺失 fail-fast（稽核 M6）
- option_chain.py / throttler.py 補測試
- metrics.py 改 math.fsum；converters timestamp 缺失記 warning
- 平倉訂單的部位計數方向性（§4.3 限制 4）
- 重連後訂單對帳（§4.3 限制 1）

### 10.3 記憶與文件指標

- 完整稽核報告（Repo Map / 發現 / 策略 / 任務計畫）在 2026-06-10 稽核對話；
  缺陷狀態摘要在專案記憶 `project_live-gateway-gaps.md`。
- `README.md` 仍是舊扁平結構（稽核裁定刪除、由 AGENTS.md 單一擔當——尚未執行）。
