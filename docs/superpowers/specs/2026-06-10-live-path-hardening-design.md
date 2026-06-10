# Live Execution Path Hardening — Design Spec

**日期：** 2026-06-10
**狀態：** Draft（待 review gate）
**來源：** 2026-06-10 全庫稽核 M0+M1 任務計畫；使用者決策：半自動（告警後人工介入）、風控真值用 IB account、煙霧測試排在本工作之後

## 1. 問題陳述

稽核確認實盤路徑有四個 Critical 缺陷（C1-C4）與兩個 High 缺陷（H2、H4），共同後果是：
訂單與成交無法關聯、拒單後系統盲目、風控 greeks 恆為 0、equity 把現金流當損益、
TWS 重連後行情靜默死亡、DTE/保證金警報是死代碼。paper smoke test 前必須修復。

## 2. 範圍

**包含**：T0.1 紅燈測試、T0.2 pre-commit、T0.3 paper/live 守門、T1.1 訂單 ID 統一、
T1.2 訂單狀態閉環、T1.3 風控真值改用 IB account、T1.4 重連重訂閱 + watchdog。

**不包含**（明確擱置）：float→Decimal、回測 streaming（個股為主，資料量小）、
回測路徑的 mark-to-market equity（記錄為已知限制）、bus 泛型型別、CI/CD。

## 3. 設計

### 3.1 訂單身分統一（修 C1）

**原則**：一個 canonical `order_id` 在訂單批准時鑄造一次，貫穿 order→fill→position；
broker orderId 是附屬屬性，僅供對帳。

- `core/events.py`：`OrderEvent` 新增 `order_id: str = field(default_factory=lambda: str(uuid.uuid4()))`。
- `storage/trade_store.py`：`log_order()` 改用 `event.order_id` 作主鍵（移除自產 UUID）；
  `orders` 表新增 `broker_order_id TEXT` 欄位（初始 NULL，由狀態事件回填）。
- `execution/live_gateway.py`：`on_order()` 以 closure 帶 `event.order_id` 進 fill 回呼；
  `FillEvent.order_id` = canonical ID（不再是 TWS orderId）。
- `backtest/executor.py`：`SimulatedExecutor` 的 FillEvent 同樣回填 `event.order_id`。
- `assembly.py`：`Position.strategy_id` 改用 `event.order.strategy_id`（語意修正），
  position 另以 canonical order_id 追溯。

### 3.2 訂單狀態閉環（修 C2）

新事件（`core/events.py`）：

```python
@dataclass
class OrderStatusEvent:
    order_id: str            # canonical ID
    status: Literal["SUBMITTED", "PARTIAL", "FILLED", "CANCELLED", "REJECTED"]
    timestamp: datetime
    broker_order_id: str = ""
    filled_quantity: int = 0
    remaining_quantity: int = 0
    reason: str = ""         # 取自 trade.log 最後一條訊息
```

- `LiveGateway.on_order()`：placeOrder 後立即發布 `SUBMITTED`（含 broker_order_id）；
  訂閱 `trade.statusEvent`，IB 狀態映射：`Cancelled`/`ApiCancelled` → CANCELLED、
  `Inactive` → REJECTED（reason 取 `trade.log[-1].message`）。handler 以 last-status memo
  去重（ib_async 同一狀態可能重複觸發）。
- **部分成交**：改訂閱 `trade.fillEvent`（每筆 execution 觸發）發布**增量** FillEvent，
  取代現行 `filledEvent`（只在完全成交時觸發、且重放全部 fills 會重複計算）。
  每筆 execution 對應一個 FillEvent；`filled_quantity`/`remaining_quantity` 由
  `trade.orderStatus` 取得並隨 PARTIAL 狀態事件發布。
- `storage`：新 `order_status` 表（append-only：order_id, status, broker_order_id,
  timestamp, reason）；`StorageSubscriber` 訂閱 OrderStatusEvent 寫入並回填
  `orders.broker_order_id`。
- `RiskPipeline`：訂閱 OrderStatusEvent；REJECTED/CANCELLED → 發布
  `AlertEvent(message=f"Order {id} {status}: {reason}")`。
- **半自動告警可見性**：`assembly.py` 新增 AlertEvent → `logger.warning` 訂閱者
  （目前 AlertEvent 發布後無人消費）。

### 3.3 風控真值改用 IB Account（修 C3、H2）

**原則**：equity 與保證金用 broker 權威值；greeks 從行情快照聚合；不再自算現金流。

- 新模組 `tws_client/account.py`：`AccountState` —— `start()` 呼叫
  `ib.accountSummaryAsync()` 建立快照並訂閱 `ib.accountSummaryEvent` 持續更新；
  提供 `equity()`（NetLiquidation）、`margin_cushion()`（IB `Cushion` tag，
  缺值時以 (EquityWithLoan − FullMaintMarginReq)/EquityWithLoan 計算，
  無資料時回傳 None——monitor 對 None 不檢查，不誤報）。
- `AppRiskState` 修正（live 與 backtest 共用部分）：
  - **部位沖銷**：以 (con_id, symbol, expiry, strike, right) 為 key 淨額累計，
    歸零即移除（取代 append-only list）。`max_position_size` 不再計入幽靈部位。
  - **greeks 聚合**：`portfolio_greeks()` 改為「持倉 legs × last_market 的
    model_greeks × multiplier」即時計算（複用 `strategy/greeks_calc.py` 的
    composite 邏輯）；無行情的 leg 跳過並記 debug log。
  - **multiplier 修正**：現金流計算乘上 `contract.multiplier`（backtest equity
    仍為現金流近似，記錄為已知限制，live 不再使用它）。
  - `min_dte()`：從未平倉期權部位的 expiry 對 clock.now() 計算最小 DTE。
- **live 接線**（assembly.py）：`equity_provider` → `AccountState.equity`；
  RiskPipeline.on_fill 與週期檢查傳入 `min_dte` 與 `margin_cushion`
  （消滅 H2 死代碼）。backtest 接線維持 AppRiskState。
- **週期性風控檢查**（修 H3 的 live 部分）：LiveApp 新增 `risk_check_loop()`
  task（間隔 `risk.check_interval_seconds`，預設 30），呼叫
  `monitor.check(greeks, equity, min_dte, margin_cushion)` 發布警報、
  `should_circuit_break()` 為真即觸發熔斷 + AlertEvent。

### 3.4 重連重訂閱 + Watchdog（修 C4；半自動）

- `ConnectionManager`：新增 `on_reconnected: list[Callable[[], None]]`；
  `_reconnect()` 成功後逐一同步呼叫（錯誤隔離：單一 callback 失敗不影響其他）。
- `LiveApp.run_market_data()`：改為迴圈——`publish_market_data()` 結束
  （= 所有 stream 死亡）後，等待 reconnected 訊號（`asyncio.Event`）再重建全部訂閱，
  直到 shutdown。重建前發 AlertEvent（"market data restarting after reconnect"）。
- **Watchdog**：LiveApp 新增 task，訂閱 MarketEvent 記錄每 symbol 最後接收
  **壁鐘時間**（非事件時間戳）；逾 `tws.stale_data_seconds`（預設 60）無 tick →
  發布 AlertEvent（每 symbol 冷卻一次，避免刷屏）。半自動原則：告警 + 自動重訂閱
  限於 reconnect 場景；其他停滯場景僅告警，人工介入。

### 3.5 Paper/Live 守門（T0.3）

- `cli.py` 的 `live` 命令啟動前呼叫 `_ensure_paper_guard(config)`：
  port 不在 {7497, 4002}（paper TWS/Gateway）時，要求環境變數
  `IB_CONFIRM_LIVE=YES`，否則 raise 並提示。預設設定永遠安全。

### 3.6 Pre-commit（T0.2）

- `scripts/githooks/pre-commit`（committed）：`uv run ruff check . && uv run pytest -q`；
  以 `git config core.hooksPath scripts/githooks` 啟用（寫入 AGENTS.md 說明）。

## 4. 錯誤處理原則

實盤 handler 失敗必須可見：gateway 內部錯誤（如 con_id 未 qualify 的 ValueError）
在 `on_order` 內 catch 後發布 `OrderStatusEvent(REJECTED, reason=...)` 而非任由
bus 吞掉（bus 行為本身不在本次範圍）。

## 5. 測試策略（TDD，紅燈先行）

全部沿用既有 mock 模式（eventkit.Event 模擬 ib_async）：

1. 拒單：mock trade.statusEvent 觸發 Cancelled → 斷言 OrderStatusEvent(REJECTED) +
   AlertEvent + order_status 表有紀錄。
2. 部分成交：兩筆 execution → 兩個增量 FillEvent，數量不重複計算。
3. ID 一致性：下單→成交後 `query_fills(order_id)` 非空（join 成立）。
4. greeks 非零：建立期權持倉 + model_greeks 行情 → `portfolio_greeks().delta != 0`。
5. equity 不因建倉下跌：AccountState mock NetLiquidation 不變 → 無回撤警報。
6. 重連：模擬 stream 死亡 + reconnected 訊號 → 訂閱重建（呼叫次數斷言）。
7. watchdog：推進 mock 時間 60s 無 tick → AlertEvent。
8. 守門：port=7496 無環境變數 → raise；有 IB_CONFIRM_LIVE=YES → 通過。
9. 沖銷：開倉+平倉 → positions() 為空。
10. 週期檢查：margin_cushion=0.01 → should_circuit_break 為真 → 熔斷觸發。

## 6. Rollback 策略

- 純代碼變更：`git revert` 整個 squash commit 即可。
- SQLite schema 變更（orders.broker_order_id、order_status 表）：開發階段資料庫
  無生產資料，rollback 程序 = 刪除 `data/*.db` 重建（CREATE TABLE IF NOT EXISTS
  自動處理）。不需 down migration。
- 行為開關：無 feature flag；半自動告警為純新增路徑，回滾無副作用。

## 7. 完成訊號（驗收）

- 第 5 節 10 項測試全綠；既有 244 測試不退化。
- `uv run ruff check .` 通過。
- 稽核 C1-C4、H2、H4（決策日誌部分見 M2，不在本次）對應缺陷的紅燈測試轉綠。
