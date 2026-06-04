# Trading System — TWS API Monorepo 設計規格

**日期：** 2026-06-04  
**狀態：** 已核准  
**範圍：** Monorepo 結構 + IB TWS API 整合（股票、期權、期權策略、報價、回測）

---

## 1. 背景與目標

建立一套美股量化交易系統，整合 Interactive Brokers TWS API，涵蓋：
- 即時報價（股票 + 期權 + Greeks）
- 任意多腿期權策略下單（Iron Condor、Bull Call Spread、Covered Call、Straddle 等）
- 完整日誌（報價流、決策、訂單、成交）
- Live trading 與 Backtest 跑同一套策略代碼

### 技術選型

| 面向 | 選擇 | 原因 |
|------|------|------|
| IB 連線環境 | TWS（port 7497） | 本機開發，有 GUI 監控 |
| Python IB 套件 | ib_insync / ib_async | asyncio 原生，reqId 自動管理，開發效率高 |
| Monorepo 工具 | uv workspaces | 單一 lockfile，`uv sync` 一鍵，比 Poetry 快 10-100x |
| 報價儲存 | Parquet（分日） | 壓縮率佳，DuckDB/pandas 直讀，回測直接用 |
| 決策日誌 | DuckDB | 可 JOIN 報價做覆盤分析 |
| 訂單/成交日誌 | SQLite | 事務性，狀態機追蹤 |
| Greeks 計算 | IB 推播優先，補值用 py_vollib | Live 用市場定價，回測用 Black-Scholes |

---

## 2. 架構總覽

### 2.1 Package 結構

```
trading-system/
├── pyproject.toml              ← uv workspace root
├── uv.lock                     ← 單一 lockfile
├── packages/
│   ├── core/                   ← 零外部依賴，所有人依賴它
│   ├── tws-client/             ← IB 連線 adapter
│   ├── market-data/            ← 資料抽象層
│   ├── storage/                ← 日誌與持久化
│   ├── risk/                   ← 風控三層
│   ├── strategy/               ← 策略基類 + 期權建模
│   ├── backtest/               ← 回測引擎
│   └── execution/              ← 實盤執行閘道
├── apps/
│   └── trader/
│       ├── main.py             ← 系統入口
│       └── config.toml         ← 連線、風控、策略參數
└── data/
    ├── ticks/                  ← Parquet 報價（按 symbol/日期）
    ├── decisions.duckdb        ← 決策覆盤
    ├── orders.db               ← 訂單狀態（SQLite）
    └── fills.db                ← 成交明細（SQLite）
```

### 2.2 依賴方向（單向，無循環）

```
apps/trader
    │
    ├──► execution  ──► tws-client ──► core
    ├──► strategy   ──► market-data ──► core
    ├──► backtest   ──► market-data ──► core
    ├──► risk       ──────────────────► core
    └──► storage    ──────────────────► core
```

`core` 永不依賴其他 package。`tws-client` 只知道 IB API，不知道策略邏輯。`strategy` 完全不知道 IB 的存在。

---

## 3. 核心資料模型（`core/models.py`）

```python
# 輔助型別（stub，實作時補齊欄位）
@dataclass
class Bar:
    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int

@dataclass
class OptionChain:
    expirations: list[str]     # ["20250117", "20250221", ...]
    strikes: list[float]       # [150.0, 152.5, 155.0, ...]
    multiplier: int            # 通常 100

@dataclass
class RiskLimits:
    max_delta: float           # 組合 Delta 上限（絕對值）
    max_vega: float            # 組合 Vega 上限
    max_drawdown: float        # 最大回撤（0~1）
    max_position_size: int     # 單一持倉最大張數
    max_margin_utilization: float  # 保證金使用率上限（0~1）

    @classmethod
    def from_config(cls) -> "RiskLimits": ...

@dataclass
class ValidationResult:
    approved: bool
    reason: str | None = None  # 若拒絕，人類可讀原因

@dataclass
class Contract:
    symbol: str
    sec_type: Literal["STK", "OPT"]
    currency: str = "USD"
    exchange: str = "SMART"
    # 期權專屬
    expiry: str = ""                 # "20250117"（YYYYMMDD）
    strike: float = 0.0
    right: Literal["C", "P", ""] = ""
    multiplier: int = 100
    con_id: int = 0                  # IB 內部唯一 ID

@dataclass
class Leg:
    contract: Contract
    quantity: int                    # 正數=買，負數=賣
    entry_price: float = 0.0

@dataclass
class Greeks:
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0
    implied_vol: float = 0.0
    underlying_price: float = 0.0

@dataclass
class Position:
    legs: list[Leg]
    strategy_id: str
    greeks: Greeks | None = None     # 合成 Greeks（多腿加總）
    unrealized_pnl: float = 0.0

@dataclass
class Order:
    legs: list[Leg]
    strategy_id: str
    order_type: Literal["MKT", "LMT", "STP"] = "LMT"
    limit_price: float | None = None
    time_in_force: Literal["DAY", "GTC"] = "DAY"
```

---

## 4. 事件系統（`core/events.py` + `core/bus.py`）

### 4.1 五種核心事件

```python
@dataclass
class MarketEvent:
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    last: float
    volume: int
    greeks: Greeks | None = None   # 期權有值，股票為 None
    bar: Bar | None = None

@dataclass
class SignalEvent:
    strategy_id: str
    timestamp: datetime
    direction: Literal["ENTER", "EXIT", "ADJUST"]
    proposed_order: Order
    reason: str                    # 人類可讀的觸發原因
    context: dict                  # 指標快照（存入決策日誌）

@dataclass
class OrderEvent:
    order: Order
    timestamp: datetime
    approved_by: str

@dataclass
class FillEvent:
    order_id: str
    legs_filled: list[Leg]         # 含實際成交價
    timestamp: datetime
    commission: float

@dataclass
class AlertEvent:
    message: str
    value: float                   # 觸發閾值的實際數值（如當前 delta）
    timestamp: datetime
```

### 4.2 事件流

```
MarketEvent ──► EventBus ──► Strategy.on_market_event()
                                    │
                              SignalEvent
                                    │
                          PreTradeRiskValidator
                                    │
                     ┌──────────────┴──────────────┐
                     │ approved                    │ rejected
                     ▼                             ▼
               OrderEvent                  DecisionLog（記錄拒絕）
                     │
               CircuitBreaker（若觸發，攔截於此）
                     │
               ExecutionGateway（live / sim）
                     │
                FillEvent ──► Portfolio + RiskMonitor
```

### 4.3 時間控制（live/backtest 切換關鍵）

```python
class LiveClock:
    def now(self) -> datetime: return datetime.now(UTC)

class SimClock:
    def now(self) -> datetime: return self._current
    def advance_to(self, ts: datetime): self._current = ts
```

---

## 5. TWS Client 層（`tws-client/`）

### 5.1 連線管理

- 連線至 TWS，port 7497
- 訂閱 `disconnectedEvent`，斷線後 30 秒自動重連（應對 IB 23:45 EST 日終斷線）
- 單一 `IB()` 實例，整個系統共用

### 5.2 報價訂閱

| API | 用途 | 限制 |
|-----|------|------|
| `reqMktData(genericTickList="")` | bid/ask/last 即時推播；OPT contract 自動觸發 `tickOptionComputation`（tick 10-13）推送 Greeks | 100 concurrent subscriptions |
| `reqRealTimeBars` | 每 5 秒一根 OHLCV bar | 每次請求計 1 subscription |
| `reqHistoricalData` | 歷史 K 線（系統啟動預熱） | 同 contract 15s 間隔，10分鐘 ≤60次 |
| `reqSecDefOptParams` | 取期權鏈（expirations + strikes） | 無速率限制 |

### 5.3 期權鏈流程

1. `reqSecDefOptParams(underlying, con_id)` → 取所有到期日 + 行使價
2. 策略選定腿的組合 → 建立 `Leg[]`
3. `qualifyContracts()` → 批次填入每腿的 `con_id`（BAG 下單前必須）
4. 組裝 IB BAG Contract → `placeOrder()`

### 5.4 多腿執行

- 單腿：直接 Contract + Order
- 多腿：組裝 `secType="BAG"` 的 ComboLeg 結構
- 每腿需有 `con_id`（步驟 3 已填入）
- 下單以淨 debit/credit 作為 `lmtPrice`

### 5.5 速率限制防護

| 問題 | 解法 |
|------|------|
| Historical data pacing | `fetch_history()` 每次請求後強制 `sleep(15s)` |
| 100 市場資料線上限 | `MarketDataFeed` 維護訂閱計數，超限拋例外 |
| Tick-by-tick 15s 間隔 | 改用 `reqMktData` streaming（無此限制） |

---

## 6. 資料抽象層（`market-data/`）

```python
class DataHandler(ABC):
    @abstractmethod
    async def subscribe_quote(self, contract: Contract) -> AsyncIterator[MarketEvent]: ...

    @abstractmethod
    async def fetch_history(self, contract, duration, bar_size) -> list[Bar]: ...

class LiveDataHandler(DataHandler):
    """包裝 tws-client，strategy 完全不知道 IB 的存在"""

class HistoricalDataHandler(DataHandler):
    """從 data/ticks/ 讀 Parquet，回測用"""
```

---

## 7. 日誌與持久化層（`storage/`）

### 7.1 儲存格式

| 資料 | 格式 | 路徑 |
|------|------|------|
| 報價 / bar / Greeks | Parquet（分日） | `data/ticks/{symbol}/{date}.parquet` |
| 決策 / 訊號 | DuckDB | `data/decisions.duckdb` |
| 訂單狀態 | SQLite | `data/orders.db` |
| 成交明細 | SQLite | `data/fills.db` |
| 系統/錯誤 log | 結構化 JSON | stdout + rotating file |

### 7.2 決策記錄欄位

每筆 `SignalEvent` 同時記錄：
- 觸發時間、strategy_id
- 市場快照：bid/ask/last/IV/delta/underlying_price
- 策略判斷：方向、人類可讀原因、所有指標值
- 提議訂單內容
- 風控結果：APPROVED / REJECTED / MODIFIED + 原因

### 7.3 接入方式

`StorageSubscriber` 訂閱 EventBus 所有事件，被動記錄，策略代碼零感知。  
報價以 buffer 批次寫入（每 N 筆 flush），決策/訂單/成交即時寫入。

---

## 8. 策略層（`strategy/`）

### 8.1 策略基類

- `on_market_event(MarketEvent)` — 收行情，計算訊號
- `signal(direction, order, reason, context)` — 發出訊號（附完整決策上下文）
- `on_fill(FillEvent)` — 更新內部狀態
- 策略不知道 IB、不知道儲存層、不知道 live/backtest

### 8.2 多腿期權建模（`strategy/option_leg.py`）

`MultiLegOrder` 提供 factory methods：

| 策略 | 腿數 |
|------|------|
| `iron_condor()` | 4 腿 |
| `bull_call_spread()` | 2 腿 |
| `covered_call()` | 2 腿（股票 + call） |
| `straddle()` | 2 腿 |
| 自訂 `Order(legs=[...])` | 任意腿數 |

### 8.3 Greeks 計算

- Live：優先使用 `MarketEvent.greeks`（IB 推播的市場定價）
- Backtest / 補值：`py_vollib` Black-Scholes 本地計算
- 多腿合成：各腿 Greeks × quantity 加總

---

## 9. 風控層（`risk/`）

### 9.1 三層防線

**Layer 1 — Pre-Trade Validator**（同步，μs 級）
- 觸發時機：`SignalEvent` → `OrderEvent` 之間
- 檢查項目：倉位上限、Delta 敞口、Vega 敞口、保證金、Bid-Ask spread
- 結果：APPROVED → 發出 `OrderEvent`；REJECTED → 記錄到決策日誌

**Layer 2 — Real-Time Monitor**（非同步，持續運行）
- 監控：持倉合成 Greeks 漂移、最大回撤、保證金使用率
- 觸發告警或啟動 Circuit Breaker

**Layer 3 — Circuit Breaker**（緊急斷路）
- 觸發後：停止所有新訂單、市價平倉所有持倉、取消所有掛單
- 觸發條件：最大回撤超限、Delta breach、手動觸發

---

## 10. 回測引擎（`backtest/`）

### 10.1 設計原則

`BacktestRunner` 只做一件事：把歷史資料逐筆封裝成 `MarketEvent` 送進 `EventBus`。  
策略代碼**一行不改**，只換 `DataHandler`（Parquet）和 `ExecutionGateway`（SimulatedExecutor）。

### 10.2 模擬成交

- Fill at next bar open（最保守，無 look-ahead bias）
- 佣金模擬：IB 期權 $0.65/contract，最低 $1.00

### 10.3 績效指標

基礎：Total Return、Annualized Return、Sharpe Ratio、Max Drawdown、Win Rate、Profit Factor  
期權專屬：Avg Days in Trade、Avg Entry/Exit IV、Theta Collected、Delta PnL、Vega PnL

---

## 11. 系統組裝（`apps/trader/main.py`）

### Live 模式組裝順序

1. 建立 `LiveClock` + `EventBus`
2. 連線 TWS → `LiveDataHandler`
3. 掛上 `PreTradeValidator` + `RealTimeMonitor` + `CircuitBreaker`
4. 掛上 `LiveGateway`（訂閱 `OrderEvent`）
5. 掛上 `StorageSubscriber`（訂閱所有事件）
6. 載入策略
7. `bus.run_forever()`

### Backtest 模式（只換兩個元件）

```
LiveDataHandler   → HistoricalDataHandler（data/ticks/）
LiveGateway       → SimulatedExecutor
LiveClock         → SimClock（由 BacktestRunner 控制）
```

策略、風控、日誌代碼完全不變。

---

## 12. 外部依賴清單

| Package | 用途 |
|---------|------|
| `ib_async` | IB TWS 連線（ib_insync 繼承者） |
| `py_vollib` | Black-Scholes Greeks 計算 |
| `pandas` | 資料處理 |
| `pyarrow` | Parquet 讀寫 |
| `duckdb` | 決策日誌查詢 |
| `aiosqlite` | 訂單/成交非同步 SQLite |
| `pydantic` | Config 驗證 |
| `loguru` | 結構化日誌 |
| `pytest` + `pytest-asyncio` | 測試 |

---

## 13. 尚未涵蓋（下一階段）

- Dashboard / 即時監控 UI
- 多策略並發資源調度
- 期權 IV Surface 建模（vol skew）
- 自動選股 / 期權鏈掃描（Watchlist 整合）
- CI/CD pipeline（GitHub Actions）
