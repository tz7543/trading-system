# Live Execution Path Hardening — Design Spec

**日期：** 2026-06-10（rev 2，含 review gate 迭代 1 修訂）
**狀態：** 待 review gate 迭代 2
**來源：** 2026-06-10 全庫稽核 M0+M1 任務計畫；使用者決策：半自動（告警後人工介入）、風控真值用 IB account、煙霧測試排在本工作之後

## 1. 問題陳述

稽核確認實盤路徑有四個 Critical 缺陷（C1-C4）與兩個 High 缺陷（H2、H3 live 部分），共同後果是：
訂單與成交無法關聯、拒單後系統盲目、風控 greeks 恆為 0、equity 把現金流當損益、
TWS 重連後行情靜默死亡、DTE/保證金警報是死代碼。paper smoke test 前必須修復。

## 2. 範圍

**包含**：T0.1 紅燈測試、T0.2 pre-commit、T0.3 paper/live 守門、T1.1 訂單 ID 統一、
T1.2 訂單狀態閉環、T1.3 風控真值改用 IB account、T1.4 重連重訂閱 + watchdog。

**不包含**（明確擱置）：float→Decimal、回測 streaming（個股為主，資料量小）、
回測路徑的 mark-to-market equity（記錄為已知限制）、bus 泛型型別、CI/CD、
即時 commission 精確性（見 §3.2 commission 政策）。

## 3. 設計

### 3.1 訂單身分統一（修 C1）

**原則**：一個 canonical `order_id` 在訂單批准時鑄造一次，貫穿 order→fill→position；
broker orderId 是附屬屬性，僅供對帳。

- `core/events.py`：`OrderEvent` **末位**新增
  `order_id: str = field(default_factory=lambda: str(uuid.uuid4()))`（既有 positional
  建構不受影響）。
- `core/events.py`：`FillEvent` 末位新增 `strategy_id: str = ""` —— 部位歸屬的載體
  （review 發現：沒有它，§3.3 的沖銷與策略歸因不可同時實作）。
- `storage/trade_store.py`：`log_order()` 改用 `event.order_id` 作主鍵（移除自產
  UUID，回傳值不變仍為 order_id）；`orders` 表新增 `broker_order_id TEXT`。
  **輕量遷移**：`init()` 在 CREATE 之後以 `PRAGMA table_info(orders)` 檢查，
  缺欄位則 `ALTER TABLE orders ADD COLUMN broker_order_id TEXT`（既有本機 DB
  自動升級，無需重建）。
- `execution/live_gateway.py`：`on_order()` 以 closure 攜帶 `event.order_id` 與
  `event.order.strategy_id` 進 fill/status 回呼；`FillEvent.order_id` = canonical ID。
- `backtest/executor.py`：`SimulatedExecutor` 的 FillEvent 同樣回填
  `event.order_id` 與 `strategy_id`。
- `assembly.py`：`Position.strategy_id` 改用 `event.strategy_id`。
- `core/__init__.py` 等 package root 同步 re-export 新增符號（assembly 以
  package root 匯入）。

### 3.2 訂單狀態閉環（修 C2）

新事件（`core/events.py`，並 re-export）：

```python
@dataclass
class OrderStatusEvent:
    order_id: str            # canonical ID
    status: Literal["SUBMITTED", "PARTIAL", "FILLED", "CANCELLED", "REJECTED"]
    timestamp: datetime
    broker_order_id: str = ""
    filled_quantity: int = 0
    remaining_quantity: int = 0
    reason: str = ""
```

- `LiveGateway.on_order()`：placeOrder 後立即發布 `SUBMITTED`（含 broker_order_id）。
- **狀態映射（單一明確規則，紅燈測試 fixture 必須照此模擬）**：
  - `Filled` → FILLED
  - `Cancelled` / `ApiCancelled` / `Inactive`：若 `trade.log` 含任何
    `errorCode` 條目 → **REJECTED**（reason = 該條 message）；否則 → **CANCELLED**。
    （IB 的 `Inactive` 也可能是暫態如 RTH 外掛單；以 error log 區分拒單與非拒單。）
  - `PendingSubmit` / `PreSubmitted` / `Submitted` → 一律 SUBMITTED（明確收斂）。
  - handler 以 last-status memo 去重（ib_async 同一狀態可能重複觸發）。
- **部分成交**：訂閱 `trade.fillEvent`（每筆 execution 觸發）發布**增量** FillEvent，
  取代現行 `filledEvent`（只在完全成交時觸發、重放全部 fills 會重複計算）。
  `filled_quantity`/`remaining_quantity` 取自 `trade.orderStatus`，隨 PARTIAL
  狀態事件發布。
- **Commission 政策（明確限制）**：`commissionReport` 在 ib_async 中於 fillEvent
  之後才到達。增量 FillEvent 的 `commission` = 該 execution 的 commissionReport
  若已存在，否則 0.0。即時 commission 可能低估——可接受，因 live equity 已改用
  IB NetLiquidation（§3.3），不依賴自算 commission；儲存層精確對帳屬未來工作。
  測試只在 report 已附掛時斷言 commission。
- **Gateway 內部錯誤可見化**：`on_order()` 以 try/except 包住建單與下單，
  失敗（如 con_id 未 qualify 的 ValueError）→ 發布
  `OrderStatusEvent(REJECTED, reason=str(exc))`，不再任由 bus 吞掉。
- `storage`：新 `order_status` 表（append-only：order_id, status, broker_order_id,
  timestamp, reason）；`StorageSubscriber` 訂閱 OrderStatusEvent 寫入，
  SUBMITTED 時回填 `orders.broker_order_id`。
- `RiskPipeline`：訂閱 OrderStatusEvent；REJECTED/CANCELLED → 發布
  `AlertEvent(message=..., value=0.0, timestamp=...)`。
- **AlertEvent value 慣例**：營運類警報（拒單、重連、watchdog）`value=0.0`；
  數值類警報（回撤、greeks、margin）沿用實際數值。
- **半自動告警可見性**：`assembly.py` 新增 AlertEvent → `logger.warning` 訂閱者。

### 3.3 風控真值改用 IB Account（修 C3、H2）

**原則**：equity 與保證金用 broker 權威值；greeks 從行情快照聚合；不再自算現金流。

- 新模組 `tws_client/account.py`：`AccountState`（並於 package root re-export）——
  `start()` 呼叫 `ib.accountSummaryAsync()` 建立快照並訂閱 `ib.accountSummaryEvent`
  持續更新。**明確指定 tag 清單**：`NetLiquidation,EquityWithLoanValue,FullMaintMarginReq,Cushion`
  （預設 tag 子集不含 Cushion，不指定會永遠拿不到）。提供：
  - `equity() -> float | None`（NetLiquidation；尚無資料回 None）
  - `margin_cushion() -> float | None`（優先 `Cushion` tag；缺值時以
    (EquityWithLoanValue − FullMaintMarginReq)/EquityWithLoanValue 計算；
    無資料回 None——monitor 對 None 不檢查，不誤報）
- `AppRiskState` 修正（live 與 backtest 共用）：
  - 建構子新增 `market_lookup: MarketLookup | None` 注入（接
    `StorageSubscriber.last_market`，解決 AppRiskState 無行情存取的缺口）。
  - **部位沖銷**：以 `(con_id, symbol, expiry, strike, right)` 為 key 淨額累計，
    歸零即移除（取代 append-only list）。`con_id=0`（backtest/STK 未 qualify）
    **刻意容忍**——key 含 symbol/expiry/strike/right 足以消歧。
  - **greeks 聚合**：`portfolio_greeks()` = 對每個淨部位 leg 查 `market_lookup`
    取 `model_greeks`，**委派給 `strategy/greeks_calc.composite()`**——它已內含
    multiplier 與 STK delta=quantity 語意，**不得**在外層再乘 multiplier
    （review 發現：外乘會對 STK 重複套用）。無行情的 leg 跳過並記 debug log。
  - **multiplier 修正**：現金流計算乘上 `contract.multiplier`（backtest equity
    仍為現金流近似，**已知限制**，live 不使用它）。
  - `min_dte() -> int | None`：未平倉期權部位的 expiry 對 clock.now() 的最小 DTE。
- **live 接線**（assembly.py）：`equity_provider` → `AccountState.equity`（None
  時 fallback 0.0 並記 warning）；`on_fill` 與週期檢查傳入 `min_dte` 與
  `margin_cushion`。backtest 接線維持 AppRiskState。
- **週期性風控檢查**：LiveApp 新增 `risk_check_loop()` task。**可測試性設計**：
  檢查邏輯抽為 `RiskPipeline.check_now()` 同步可呼叫方法（呼叫
  `monitor.check(greeks, equity, min_dte, margin_cushion)` 發布警報、
  `should_circuit_break()` 為真即觸發熔斷 + AlertEvent）；loop task 僅負責
  「每 `risk.check_interval_seconds`（預設 30，**需在 RiskConfig 宣告**，
  extra="forbid"）呼叫一次」。測試直接呼叫 `check_now()`，不依賴真實時間。

### 3.4 重連重訂閱 + Watchdog（修 C4；半自動）

- `ConnectionManager`：
  - `_on_disconnect()` 加 **running-task guard**：既有 `_reconnect_task` 未完成
    則不重複啟動（review 發現：現行代碼會無條件覆蓋，疊加重連任務）。
  - 新增 `on_reconnected: list[Callable[[], None]]`；`_reconnect()` 成功後逐一
    同步呼叫（單一 callback 失敗記 log 不影響其他）。
- `LiveApp.run_market_data()` 重連迴圈，**明確 Event 協議防 lost-wakeup**：
  ```
  reconnected = asyncio.Event()          # callback: reconnected.set()（sticky）
  while not shutdown:
      await publish_market_data(...)     # 結束 = 所有 stream 死亡
      if shutdown: break
      await reconnected.wait()           # callback 可能已先 set——sticky 不丟失
      reconnected.clear()                # 先 clear 再重建，新斷線會再 set
      publish AlertEvent("market data restarting after reconnect", value=0.0)
  ```
  callback 在重建**之前**就可能 fire——sticky Event 保證不丟 wakeup；
  clear 在 wait 返回後、重建前，保證重建期間的新斷線不被吞。
- **Watchdog**：獨立類 `MarketDataWatchdog`（assembly.py 或 core）——
  訂閱 MarketEvent 記錄每 symbol 最後接收時間（**注入 `Clock`**，非直接
  `time.monotonic`，保證可測試）；提供 `check_now() -> list[AlertEvent]`：
  逾 `tws.stale_data_seconds`（預設 60，**需在 TwsConfig 宣告**）無 tick →
  AlertEvent（每 symbol 觸發後進入冷卻，恢復收 tick 才重置，避免刷屏）。
  LiveApp loop task 週期呼叫。測試用 SimClock 推進時間 + 直接呼叫 `check_now()`。

### 3.5 Paper/Live 守門（T0.3）

- `cli.py` 的 `live` 命令啟動前呼叫 `_ensure_paper_guard(config)`：
  port 不在 {7497, 4002}（paper TWS/Gateway）時，要求環境變數
  `IB_CONFIRM_LIVE=YES`，否則 raise 並提示。預設設定永遠安全。

### 3.6 Pre-commit（T0.2）

- `scripts/githooks/pre-commit`（committed）：`uv run ruff check . && uv run pytest -q`；
  以 `git config core.hooksPath scripts/githooks` 啟用（寫入 AGENTS.md 說明）。

## 4. 預期變更的既有測試（修訂「零退化」宣稱）

以下測試斷言**舊的錯誤行為**，屬預期變更（非退化），實作時同步更新：

1. `packages/execution/tests/test_live_gateway.py:160` —— 斷言
   `FillEvent.order_id == "1"`（TWS orderId）→ 改斷言 canonical order_id。
2. `apps/trader/tests/test_assembly.py:357` —— 斷言
   `Position.strategy_id == "sim-1"`（實為 order_id hack）→ 改斷言真正的
   strategy_id（經 FillEvent.strategy_id）。
3. `packages/storage/tests/test_trade_store.py:35-36` —— 斷言 log_order 自產
   UUID → 改斷言使用 event.order_id。
4. 既有 `filledEvent` 相關 gateway 測試 → 改為 `fillEvent` 增量語意。

其餘測試不得退化。

## 5. 測試策略（TDD，紅燈先行）

全部沿用既有 mock 模式（真 `eventkit.Event` 模擬 ib_async 事件，現有測試已採用）：

1. 拒單：mock `trade.statusEvent` 觸發 `Inactive` + trade.log 含 errorCode 條目
   → 斷言 OrderStatusEvent(REJECTED, reason=錯誤訊息) + AlertEvent +
   order_status 表有紀錄。（fixture 必須照 §3.2 映射規則模擬。）
2. 取消：`Cancelled` 無 error log → OrderStatusEvent(CANCELLED)。
3. 部分成交：兩筆 execution 經 `fillEvent` → 兩個增量 FillEvent，數量不重複；
   commission 僅在 report 已附掛的 fixture 中斷言。
4. ID 一致性：下單→成交後 `query_fills(order_id)` 非空（join 成立）；
   orders.broker_order_id 已回填。
5. 既有 DB 遷移：以舊 schema 建 orders 表 → `init()` 後 broker_order_id 欄存在。
6. greeks 非零：期權持倉 + model_greeks 行情 + market_lookup 注入 →
   `portfolio_greeks().delta != 0`；STK 部位不重複乘 multiplier。
7. 沖銷：開倉 + 反向平倉 → `positions()` 為空；`min_dte()` 隨之為 None。
8. AccountState：mock accountSummary 值 → equity/margin_cushion 正確；
   無資料 → None；monitor 對 None 不產生警報。
9. 週期檢查：margin_cushion=0.01 → `check_now()` 觸發熔斷 + AlertEvent。
10. 重連：模擬 stream 死亡 + reconnected 已先 set（sticky 場景）→ 訂閱重建
    （呼叫次數斷言）；`_on_disconnect` 重入 → 不疊加 reconnect task。
11. watchdog：SimClock 推進 61s 無 tick → `check_now()` 回傳 AlertEvent；
    再推進 → 冷卻不重複；收 tick 後重置。
12. 守門：port=7496 無環境變數 → raise；`IB_CONFIRM_LIVE=YES` → 通過；
    port=7497 → 不需環境變數。
13. gateway 內部錯誤：con_id=0 的 BAG → OrderStatusEvent(REJECTED)，
    不再被 bus 靜默吞掉。

## 6. Rollback 策略

- 純代碼變更：`git revert` 整個 squash commit。
- SQLite schema：`broker_order_id` 為 nullable 新欄、`order_status` 為新表——
  舊代碼讀舊欄位不受影響，revert 後無需 down migration；如需淨化，刪除
  `data/*.db` 重建（開發階段無生產資料）。
- 行為開關：無 feature flag；告警為純新增路徑，回滾無副作用。

## 7. 完成訊號（驗收）

- §5 的 13 項測試全綠；§4 列出的預期變更之外，其餘既有測試不退化。
- `uv run ruff check .` 通過。
- 稽核 C1-C4、H2、H3(live) 對應缺陷的紅燈測試轉綠。

## 8. Review Gate 修訂紀錄

**迭代 1（opus + codex，2026-06-10）**：採納——FillEvent 增 strategy_id（O-C2）、
預期變更測試清單（O-C1）、market_lookup 注入與 composite 委派防 STK 重複乘
（O-I3）、sticky Event 協議（O-I4）、accountSummary 明確 tag 清單（O-I5）、
Inactive 以 error log 區分拒單（O-M6 + X-2）、commission 滯後政策（O-M7 + X-1）、
reconnect running-task guard（X-3）、config 欄位宣告（X-4）、SQLite ALTER 遷移
（X-5）、AlertEvent value 慣例（X-6）、watchdog/週期檢查注入 Clock 與 check_now
可測試設計（X-7）、package root re-export（X-8）、con_id=0 容忍聲明（O-M9）。
