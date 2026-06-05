# Trading System 交接文件

**日期：** 2026-06-05
**狀態：** Phase 4B 完成，Phase 4C 待開始

---

## 1. 專案概述

美股量化交易系統，透過 Interactive Brokers TWS API 進行股票與期權交易。Python 3.11+ monorepo，使用 `uv workspaces` 管理。Live trading 與 backtest 共用同一套策略代碼，透過 DI 切換 DataHandler 與 Executor。

**設計規格：** `docs/superpowers/specs/2026-06-04-tws-monorepo-design.md`

---

## 2. 目前規模

| 指標 | 數值 |
|------|------|
| Source files | 28 |
| Test files | 27 |
| Source LoC | ~1,700 |
| Test LoC | ~2,700 |
| Tests | 113（全部通過） |
| Commits | 35 |

---

## 3. Monorepo 結構與依賴方向

```
packages/
  core/          ← 零外部依賴，所有 package 依賴它
  storage/       ← Parquet tick 讀寫、DuckDB 決策日誌、SQLite 訂單/成交
  market-data/   ← HistoricalDataHandler（回測用 Parquet 讀取）
  strategy/      ← BaseStrategy ABC、多腿期權工廠、Greeks 計算
  risk/          ← PreTradeValidator → RealTimeMonitor → CircuitBreaker
  backtest/      ← SimulatedExecutor、BacktestRunner、PerformanceMetrics
  tws-client/    ← IB TWS API adapter（ib_async）
  execution/     ← LiveGateway（實盤下單）
apps/
  trader/        ← 系統入口（尚未實作，Phase 4C）
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

## 4. 各 Phase 完成狀態

### Phase 1: Workspace + Core（已完成）

| 模組 | 檔案 | 說明 |
|------|------|------|
| models | `core/models.py` | Contract, Leg, Order, Bar, Greeks, OptionChain, RiskLimits, Position |
| events | `core/events.py` | MarketEvent, SignalEvent, OrderEvent, FillEvent, AlertEvent |
| bus | `core/bus.py` | EventBus — `subscribe(type, handler)` / `publish(event)` |
| clock | `core/clock.py` | Clock Protocol, LiveClock, SimClock |
| data_handler | `core/data_handler.py` | DataHandler ABC — `subscribe_quote()`, `fetch_history()` |
| partitions | `core/partitions.py` | Hive partition path 工具 |

### Phase 2: Data Layer（已完成）

| 模組 | 檔案 | 說明 |
|------|------|------|
| tick_writer | `storage/tick_writer.py` | Parquet batch write（Hive partitioned） |
| tick_reader | `storage/tick_reader.py` | Parquet 讀取 |
| decision_logger | `storage/decision_logger.py` | DuckDB 決策/風控記錄 |
| trade_store | `storage/trade_store.py` | SQLite WAL — 訂單與成交 |
| subscriber | `storage/subscriber.py` | EventBus → storage 橋接 |
| historical | `market_data/historical.py` | HistoricalDataHandler（回測用） |

### Phase 3: Trading Logic（已完成）

| 模組 | 檔案 | 說明 |
|------|------|------|
| base | `strategy/base.py` | BaseStrategy ABC（`on_market` → `_signal`） |
| greeks_calc | `strategy/greeks_calc.py` | 持倉 Greeks 合成 |
| multi_leg | `strategy/multi_leg.py` | Iron Condor、Bull Call Spread、Covered Call、Straddle 工廠 |
| pre_trade | `risk/pre_trade.py` | PreTradeValidator — delta/vega/position 限制 |
| monitor | `risk/monitor.py` | RealTimeMonitor — drawdown + Greeks drift |
| circuit_breaker | `risk/circuit_breaker.py` | CircuitBreaker — 日損限額 |

### Phase 4A: Backtest Engine（已完成）

| 模組 | 檔案 | 說明 |
|------|------|------|
| executor | `backtest/executor.py` | SimulatedExecutor — next-tick fill、模擬佣金 |
| runner | `backtest/runner.py` | BacktestRunner — 時間排序 replay、fill pending |
| metrics | `backtest/metrics.py` | PerformanceMetrics — FIFO trade matching、PnL、drawdown |

### Phase 4B: Live Trading Path（已完成）

| 模組 | 檔案 | 說明 |
|------|------|------|
| converters | `tws_client/converters.py` | core ↔ ib_async 型別轉換（NaN-safe） |
| connection | `tws_client/connection.py` | ConnectionManager — connect/disconnect/auto-reconnect (30s) |
| market_feed | `tws_client/market_feed.py` | MarketDataFeed — Ticker.updateEvent → AsyncIterator via Queue |
| live_data | `tws_client/live_data.py` | LiveDataHandler — 實作 DataHandler ABC |
| option_chain | `tws_client/option_chain.py` | OptionChainService — chain 查詢 + qualify |
| live_gateway | `execution/live_gateway.py` | LiveGateway — 單腿/BAG 下單 + FillEvent 發布 |

### Phase 4C: App Assembly（待開始）

計畫已記錄在 Phase 4B plan 底部：

| Task | 說明 |
|------|------|
| 4C.1 | Config loading（config.toml → Pydantic model） |
| 4C.2 | Live mode assembly（EventBus wiring，包括 `bus.subscribe(OrderEvent, gateway.on_order)`） |
| 4C.3 | Backtest mode assembly（同一策略代碼，替換 DataHandler + Executor） |
| 4C.4 | Integration test（完整 pipeline：backtest + risk + storage） |

---

## 5. 關鍵設計決策

### 5.1 EventBus 架構

所有元件透過 `EventBus` 溝通。事件流：

```
MarketEvent → Strategy.on_market()
           → SignalEvent → PreTradeValidator
                        → OrderEvent → LiveGateway/SimulatedExecutor
                                     → FillEvent → StorageSubscriber
                                                 → RealTimeMonitor
```

`EventBus.publish()` 是 async — 依序呼叫所有 handler。

### 5.2 DataHandler DI

Strategy 不直接 import DataHandler 實作：
- **Live:** `LiveDataHandler`（tws-client）透過 `main.py` 注入
- **Backtest:** `HistoricalDataHandler`（market-data）透過 runner 注入

兩者都實作 `core.data_handler.DataHandler` ABC。

### 5.3 LiveDataHandler 放在 tws-client（非 market-data）

設計規格 §6 文字說 market-data，但 §2.2 依賴圖顯示 market-data 不依賴 tws-client。使用者決定放 tws-client，保持 market-data 純粹（只做回測資料讀取）。

### 5.4 MarketDataFeed 訂閱計數

`subscribe()` 是普通 method（非 async generator），eager 檢查並遞增計數，回傳 `_subscribe_inner()` async generator。原因：async generator body 在第一次 `__anext__()` 才執行，若用 async def subscribe 做 limit check 會被延遲。

### 5.5 eventkit Event 橋接

ib_async 的 `Ticker.updateEvent` 是 eventkit 同步 callback。橋接模式：
1. `on_update(ticker)` — 同步 callback，呼叫 `queue.put_nowait(event)`
2. `_subscribe_inner()` — async generator，`yield await queue.get()`
3. `aclose()` 觸發 `finally` block — 取消訂閱 + `cancelMktData`

### 5.6 LiveGateway sync→async 橋接

`trade.filledEvent` 是 eventkit 同步 callback，但 `EventBus.publish()` 是 async。使用 `asyncio.ensure_future()` 橋接，task 存在 `_pending_fills` set 避免 GC 回收。

### 5.7 BAG 下單 con_id 保護

`_build_bag()` 在每個 leg 檢查 `con_id != 0`，若為 0 則 raise ValueError。原因：IB 的 BAG order 需要每個 ComboLeg 有有效的 conId，必須先呼叫 `OptionChainService.qualify()`。

### 5.8 LiveGateway bus 訂閱延遲到 Phase 4C

`LiveGateway.__init__` **不會** 呼叫 `bus.subscribe(OrderEvent, self.on_order)`。Bus wiring 在 Phase 4C 的 apps/trader 組裝階段完成。與 `SimulatedExecutor` 一致（runner 直接呼叫 `executor.on_order()`）。

---

## 6. IB TWS API 注意事項

| 項目 | 說明 |
|------|------|
| Pacing | Historical data 每次 reqHistoricalDataAsync 後 sleep 15s |
| 訂閱上限 | MarketDataFeed 追蹤數量，預設 max=100，超過 raise SubscriptionLimitError |
| 每日斷線 | TWS ~23:45 EST 關閉連線，ConnectionManager 30s 後自動重連 |
| BAG 價格符號 | Credit spread → 負 lmtPrice，debit spread → 正。caller 設定，LiveGateway 直接傳遞 |
| qualifyContracts | 下 BAG 單前必須 qualify，否則 con_id=0 被 _build_bag 擋住 |
| Greeks tick | Live 用 `model_greeks`（tick 13），backtest 用 py_vollib（待實作） |
| Paper TWS | port 7497（預設），live port 7496 |

---

## 7. 測試架構

所有 tws-client 和 execution 測試 **mock ib_async.IB**，驗證轉換邏輯和控制流，不驗證 IB 連線。

關鍵 mock 模式：
- `eventkit.Event` — 用真實 Event（非 MagicMock），因為 `+=` operator 行為不同
- `OptionComputation` / `BarData` — 用 MagicMock 設定屬性（NamedTuple 建構子跨版本不一致）
- `asyncio.sleep` — 用 `patch` mock 避免真實等待（pacing test、reconnect test）
- `ConnectionManager._reconnect_task` — 測試中 `await mgr._reconnect_task` 取代 `asyncio.sleep(0)` polling

**Manual smoke-test checklist**（Phase 4C 完成後執行，記錄在 Phase 4B plan 底部）：
1. ConnectionManager.connect() 連接 paper TWS
2. 斷線重連（kill TWS → 等 30s → 重啟）
3. Live quote 訂閱（AAPL bid/ask/last）
4. Option Greeks（tick 13）
5. Option chain 查詢
6. Historical data + pacing 驗證
7. 單腿 LMT 委託 + FillEvent
8. BAG 委託（bull call spread）
9. Credit spread 負 lmtPrice

---

## 8. 常用指令

```bash
uv sync                              # 安裝所有 workspace 依賴
uv run pytest                        # 跑全部 113 個測試
uv run pytest -v                     # verbose 模式
uv run pytest -k 'test_name'         # 跑單一測試
uv run pytest packages/tws-client/   # 跑單一 package
uv run ruff check .                  # Lint
uv run ruff format .                 # Format
```

---

## 9. 檔案速查

### Core（核心模型與基礎設施）

```
packages/core/src/core/
  models.py          Contract, Leg, Order, Bar, Greeks, OptionChain, RiskLimits, Position
  events.py          MarketEvent, SignalEvent, OrderEvent, FillEvent, AlertEvent
  bus.py             EventBus（subscribe / publish）
  clock.py           Clock Protocol, LiveClock, SimClock
  data_handler.py    DataHandler ABC（subscribe_quote, fetch_history）
  partitions.py      tick_partition_path(), tick_contract_dir()
```

### TWS Client（IB API 封裝）

```
packages/tws-client/src/tws_client/
  converters.py      to_ib_contract(), ticker_to_market_event(), ib_bar_to_bar(), _safe()
  connection.py      ConnectionManager（connect, disconnect, auto-reconnect）
  market_feed.py     MarketDataFeed（subscribe → AsyncIterator[MarketEvent]）
  live_data.py       LiveDataHandler（DataHandler ABC 實作）
  option_chain.py    OptionChainService（get_chain, qualify）
```

### Execution

```
packages/execution/src/execution/
  live_gateway.py    LiveGateway（on_order → placeOrder → FillEvent）
```

### Backtest

```
packages/backtest/src/backtest/
  executor.py        SimulatedExecutor（next-tick fill, 模擬佣金）
  runner.py          BacktestRunner（time-sorted replay）
  metrics.py         compute_metrics()（FIFO trade matching, PnL, drawdown）
```

### Strategy

```
packages/strategy/src/strategy/
  base.py            BaseStrategy ABC（on_market → _signal → SignalEvent）
  greeks_calc.py     GreeksCalculator（持倉 Greeks 合成）
  multi_leg.py       iron_condor(), bull_call_spread(), covered_call(), straddle()
```

### Risk

```
packages/risk/src/risk/
  pre_trade.py       PreTradeValidator（delta/vega/position 限制）
  monitor.py         RealTimeMonitor（drawdown + Greeks drift 即時監控）
  circuit_breaker.py CircuitBreaker（日損限額熔斷）
```

### Storage

```
packages/storage/src/storage/
  tick_writer.py     TickWriter（Parquet Hive-partitioned batch write）
  tick_reader.py     TickReader（Parquet 讀取）
  tick_schema.py     TICK_SCHEMA（PyArrow schema 定義）
  decision_logger.py DecisionLogger（DuckDB 決策/風控記錄）
  trade_store.py     TradeStore（SQLite WAL — 訂單與成交）
  subscriber.py      StorageSubscriber（EventBus → storage 橋接）
```

---

## 10. 下一步：Phase 4C

Phase 4C 是最後的組裝階段，把所有 package 連接成可運行的系統：

1. **Config loading** — `apps/trader/config.toml` → Pydantic model（TWS 連線參數、風控限額、策略參數）
2. **Live mode assembly** — 建立 `IB()` → `ConnectionManager` → `LiveDataHandler` → `LiveGateway`，wiring EventBus（包括 `bus.subscribe(OrderEvent, gateway.on_order)`）
3. **Backtest mode assembly** — 同一策略代碼，替換 `HistoricalDataHandler` + `SimulatedExecutor`
4. **Integration test** — 完整 pipeline：market data → strategy → risk → execution → storage

完成 Phase 4C 後，需執行上述 manual smoke-test checklist 驗證 IB 連線。
