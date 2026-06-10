# Live Execution Path Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修復稽核確認的實盤路徑 Critical 缺陷：訂單身分統一、訂單狀態閉環、風控真值改用 IB account、重連重訂閱 + watchdog、paper/live 守門。

**Architecture:** 事件驅動 uv-workspace monorepo。canonical `order_id` 在 `OrderEvent` 鑄造，貫穿 gateway/executor/storage/risk；新 `OrderStatusEvent` 閉環；`AccountState`（tws-client）提供 IB 權威 equity/margin；per-contract 行情身分（`contract_key`）支撐 greeks 聚合與 tick 路由。

**Tech Stack:** Python 3.11、ib_async 2.1.0、aiosqlite、pydantic v2、pytest + pytest-asyncio（auto mode）、eventkit（測試模擬 IB 事件）。

**Spec:** `docs/superpowers/specs/2026-06-10-live-path-hardening-design.md`（rev 4）

**Rollback:** 全部變更可 `git revert` squash commit；SQLite 新欄/新表為向後相容附加，必要時刪 `data/*.db` 重建。

**驗證基線:** 開工前 `uv run pytest -q` 必須是 244 passed。`.py` 檔案由 hook 自動 ruff format/fix——不要手動格式化。

---

### Task 1: core 事件與模型擴充（基礎層，其他任務全依賴）

**Files:**
- Modify: `packages/core/src/core/models.py`（新增 `contract_key`）
- Modify: `packages/core/src/core/events.py`（OrderEvent.order_id、FillEvent.strategy_id、OrderStatusEvent、MarketEvent.contract）
- Modify: `packages/core/src/core/__init__.py`（re-export）
- Test: `packages/core/tests/test_events.py`、`packages/core/tests/test_models.py`

- [ ] **Step 1: 寫失敗測試（contract_key）**

在 `packages/core/tests/test_models.py` 追加：

```python
from core.models import contract_key


def test_contract_key_stock():
    c = Contract(symbol="AAPL", sec_type="STK")
    assert contract_key(c) == "AAPL"


def test_contract_key_option():
    c = Contract(
        symbol="AAPL", sec_type="OPT", expiry="20260119", strike=150.0, right="C"
    )
    assert contract_key(c) == "AAPL|20260119|150.0|C"


def test_contract_key_distinguishes_legs():
    call = Contract(
        symbol="AAPL", sec_type="OPT", expiry="20260119", strike=150.0, right="C"
    )
    put = Contract(
        symbol="AAPL", sec_type="OPT", expiry="20260119", strike=150.0, right="P"
    )
    assert contract_key(call) != contract_key(put)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest packages/core/tests/test_models.py -k contract_key -v`
Expected: FAIL — `ImportError: cannot import name 'contract_key'`

- [ ] **Step 3: 實作 contract_key**

在 `packages/core/src/core/models.py` 末尾（`assignment_stock_quantity` 之前）加：

```python
def contract_key(contract: Contract) -> str:
    if contract.sec_type == "STK":
        return contract.symbol
    return f"{contract.symbol}|{contract.expiry}|{contract.strike}|{contract.right}"
```

- [ ] **Step 4: 跑測試確認通過**

Run: `uv run pytest packages/core/tests/test_models.py -k contract_key -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 寫失敗測試（事件欄位）**

在 `packages/core/tests/test_events.py` 追加：

```python
from datetime import UTC, datetime

from core.events import FillEvent, MarketEvent, OrderEvent, OrderStatusEvent
from core.models import Contract, Leg, Order


def _order() -> Order:
    leg = Leg(contract=Contract(symbol="AAPL", sec_type="STK"), quantity=100)
    return Order(legs=[leg], strategy_id="s1")


def test_order_event_mints_order_id():
    e1 = OrderEvent(order=_order(), timestamp=datetime.now(UTC), approved_by="v")
    e2 = OrderEvent(order=_order(), timestamp=datetime.now(UTC), approved_by="v")
    assert e1.order_id and e2.order_id
    assert e1.order_id != e2.order_id


def test_fill_event_carries_strategy_id():
    fill = FillEvent(
        order_id="oid-1",
        legs_filled=[],
        timestamp=datetime.now(UTC),
        commission=0.0,
        strategy_id="s1",
    )
    assert fill.strategy_id == "s1"


def test_order_status_event_fields():
    e = OrderStatusEvent(
        order_id="oid-1",
        status="REJECTED",
        timestamp=datetime.now(UTC),
        broker_order_id="7",
        reason="margin",
    )
    assert e.status == "REJECTED"
    assert e.filled_quantity == 0
    assert e.remaining_quantity == 0


def test_market_event_optional_contract():
    c = Contract(symbol="AAPL", sec_type="STK")
    e = MarketEvent(
        symbol="AAPL",
        timestamp=datetime.now(UTC),
        bid=1.0,
        ask=2.0,
        last=1.5,
        volume=10,
        contract=c,
    )
    assert e.contract is c
```

- [ ] **Step 6: 跑測試確認失敗**

Run: `uv run pytest packages/core/tests/test_events.py -v`
Expected: 新測試 FAIL（unexpected keyword / ImportError）

- [ ] **Step 7: 實作事件擴充**

`packages/core/src/core/events.py`：

頂部 import 改為：

```python
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from core.models import Bar, Contract, Greeks, Leg, Order
```

`MarketEvent` 末位加欄位：

```python
    bar: Bar | None = None
    contract: Contract | None = None
```

`OrderEvent` 末位加欄位：

```python
@dataclass
class OrderEvent:
    order: Order
    timestamp: datetime
    approved_by: str
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
```

`FillEvent` 末位加欄位：

```python
@dataclass
class FillEvent:
    order_id: str
    legs_filled: list[Leg]
    timestamp: datetime
    commission: float
    strategy_id: str = ""
```

`FillEvent` 之後新增：

```python
@dataclass
class OrderStatusEvent:
    order_id: str
    status: Literal["SUBMITTED", "PARTIAL", "FILLED", "CANCELLED", "REJECTED"]
    timestamp: datetime
    broker_order_id: str = ""
    filled_quantity: int = 0
    remaining_quantity: int = 0
    reason: str = ""
```

`packages/core/src/core/__init__.py`：events import 區塊加 `OrderStatusEvent`，
models import 區塊加 `contract_key`；兩者同步加進 `__all__`（字母序）。

- [ ] **Step 8: 跑 core 全部測試**

Run: `uv run pytest packages/core/tests -q`
Expected: 全 PASS

- [ ] **Step 9: Commit**

```bash
rtk git add packages/core && rtk git commit -m "feat(core): canonical order_id, OrderStatusEvent, FillEvent.strategy_id, MarketEvent.contract, contract_key"
```

---

### Task 2: TradeStore — canonical ID、named INSERT、broker_order_id 遷移、order_status 表

**Files:**
- Modify: `packages/storage/src/storage/trade_store.py`
- Test: `packages/storage/tests/test_trade_store.py`

- [ ] **Step 1: 更新既有測試 + 寫失敗測試**

`packages/storage/tests/test_trade_store.py`：既有斷言 `log_order` 自產 UUID 的
測試（約 35-36 行）改為斷言回傳 `event.order_id`。追加：

```python
async def test_order_fill_join_by_canonical_id(tmp_path):
    store = TradeStore(tmp_path / "t.db")
    await store.init()
    order_event = _make_order_event()  # 既有 helper；OrderEvent 現在自帶 order_id
    await store.log_order(order_event)
    fill = FillEvent(
        order_id=order_event.order_id,
        legs_filled=[],
        timestamp=datetime.now(UTC),
        commission=1.0,
        strategy_id="s1",
    )
    await store.log_fill(fill)
    fills = await store.query_fills(order_id=order_event.order_id)
    assert len(fills) == 1
    await store.close()


async def test_migration_adds_broker_order_id(tmp_path):
    db_path = tmp_path / "old.db"
    conn = await aiosqlite.connect(db_path)
    await conn.execute(
        """CREATE TABLE orders (
            id TEXT PRIMARY KEY, timestamp TEXT NOT NULL,
            strategy_id TEXT NOT NULL, approved_by TEXT NOT NULL,
            order_type TEXT NOT NULL, limit_price REAL,
            time_in_force TEXT NOT NULL, legs_json TEXT NOT NULL)"""
    )
    await conn.commit()
    await conn.close()
    store = TradeStore(db_path)
    await store.init()  # 必須對舊 schema 做 ALTER
    cursor = await store._db.execute("PRAGMA table_info(orders)")
    cols = [row[1] for row in await cursor.fetchall()]
    assert "broker_order_id" in cols
    await store.close()


async def test_log_status_records_and_backfills(tmp_path):
    store = TradeStore(tmp_path / "t.db")
    await store.init()
    order_event = _make_order_event()
    await store.log_order(order_event)
    status = OrderStatusEvent(
        order_id=order_event.order_id,
        status="SUBMITTED",
        timestamp=datetime.now(UTC),
        broker_order_id="42",
    )
    await store.log_status(status)
    orders = await store.query_orders()
    assert orders[0]["broker_order_id"] == "42"
    statuses = await store.query_statuses(order_event.order_id)
    assert statuses[0]["status"] == "SUBMITTED"
    await store.close()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest packages/storage/tests/test_trade_store.py -v`
Expected: 新測試 FAIL（no attribute log_status / 欄位缺失）

- [ ] **Step 3: 實作 TradeStore**

`packages/storage/src/storage/trade_store.py` 變更：

1. 頂部 import：移除 `import uuid`，`from core.events import FillEvent, OrderEvent, OrderStatusEvent`。
2. `init()` 的 orders CREATE 之後加遷移與新表：

```python
        cursor = await self._db.execute("PRAGMA table_info(orders)")
        cols = [row[1] for row in await cursor.fetchall()]
        if "broker_order_id" not in cols:
            await self._db.execute(
                "ALTER TABLE orders ADD COLUMN broker_order_id TEXT"
            )
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS order_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                status TEXT NOT NULL,
                broker_order_id TEXT,
                timestamp TEXT NOT NULL,
                reason TEXT
            )
        """)
```

（注意：新建資料庫的 orders CREATE TABLE DDL 也加上 `broker_order_id TEXT`
欄位，PRAGMA 分支只服務舊檔。）

3. `log_order()` 改用 event.order_id 與**具名欄位 INSERT**：

```python
    async def log_order(self, event: OrderEvent) -> str:
        db = self._require_db()
        legs = [...]  # 不變
        await db.execute(
            """INSERT INTO orders
               (id, timestamp, strategy_id, approved_by, order_type,
                limit_price, time_in_force, legs_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.order_id,
                event.timestamp.isoformat(),
                event.order.strategy_id,
                event.approved_by,
                event.order.order_type,
                event.order.limit_price,
                event.order.time_in_force,
                json.dumps(legs),
            ),
        )
        await db.commit()
        return event.order_id
```

4. 新增：

```python
    async def log_status(self, event: OrderStatusEvent) -> None:
        db = self._require_db()
        await db.execute(
            """INSERT INTO order_status
               (order_id, status, broker_order_id, timestamp, reason)
               VALUES (?, ?, ?, ?, ?)""",
            (
                event.order_id,
                event.status,
                event.broker_order_id,
                event.timestamp.isoformat(),
                event.reason,
            ),
        )
        if event.status == "SUBMITTED" and event.broker_order_id:
            await db.execute(
                "UPDATE orders SET broker_order_id = ? WHERE id = ?",
                (event.broker_order_id, event.order_id),
            )
        await db.commit()

    async def query_statuses(self, order_id: str) -> list[dict]:
        db = self._require_db()
        cursor = await db.execute(
            "SELECT * FROM order_status WHERE order_id = ? ORDER BY id",
            (order_id,),
        )
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row, strict=False)) for row in rows]
```

- [ ] **Step 4: 跑 storage 測試確認通過**

Run: `uv run pytest packages/storage/tests/test_trade_store.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
rtk git add packages/storage && rtk git commit -m "feat(storage): canonical order id, broker_order_id migration, order_status table"
```

---

### Task 3: StorageSubscriber — status 訂閱、per-contract 查找、tick 路由修正

**Files:**
- Modify: `packages/storage/src/storage/subscriber.py`
- Test: `packages/storage/tests/test_subscriber.py`

- [ ] **Step 1: 寫失敗測試**

`packages/storage/tests/test_subscriber.py` 追加（沿用既有 fixture 風格）：

```python
from core.models import contract_key


async def test_last_market_by_contract_distinguishes_legs(subscriber_env):
    bus, subscriber = subscriber_env  # 依既有 fixture 命名調整
    call = Contract(symbol="AAPL", sec_type="OPT", expiry="20260119",
                    strike=150.0, right="C")
    put = Contract(symbol="AAPL", sec_type="OPT", expiry="20260119",
                   strike=150.0, right="P")
    await bus.publish(_market_event("AAPL", contract=call, last=5.0))
    await bus.publish(_market_event("AAPL", contract=put, last=3.0))
    assert subscriber.last_market_by_contract(contract_key(call)).last == 5.0
    assert subscriber.last_market_by_contract(contract_key(put)).last == 3.0


async def test_tick_routing_uses_event_contract(tmp_path, subscriber_env):
    # 同 symbol 的 STK 與 OPT 事件各自寫進自己的分區（不靠 register_contract）
    bus, subscriber = subscriber_env
    stk = Contract(symbol="AAPL", sec_type="STK")
    opt = Contract(symbol="AAPL", sec_type="OPT", expiry="20260119",
                   strike=150.0, right="C")
    await bus.publish(_market_event("AAPL", contract=stk, last=200.0))
    await bus.publish(_market_event("AAPL", contract=opt, last=5.0))
    subscriber._tick_writer.close()  # flush
    # 路徑無關斷言：不假設 fixture 的 base dir 前綴，整樹掃描分區段
    files = [str(p) for p in tmp_path.rglob("*.parquet")]
    assert any("sec_type=STK" in f and "symbol=AAPL" in f for f in files)
    assert any("sec_type=OPT" in f and "strike=150.0" in f for f in files)


async def test_on_status_logged(subscriber_env):
    bus, subscriber, store = subscriber_env
    status = OrderStatusEvent(order_id="o1", status="SUBMITTED",
                              timestamp=datetime.now(UTC), broker_order_id="9")
    await bus.publish(status)
    assert (await store.query_statuses("o1"))[0]["broker_order_id"] == "9"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest packages/storage/tests/test_subscriber.py -v`
Expected: 新測試 FAIL

- [ ] **Step 3: 實作 StorageSubscriber**

```python
from core.events import FillEvent, MarketEvent, OrderEvent, OrderStatusEvent
from core.models import Contract, contract_key
```

`__init__` 加 `self._last_by_contract: dict[str, MarketEvent] = {}`。

新增方法與 handler；`start`/`stop` 同步增訂 `OrderStatusEvent`：

```python
    def last_market_by_contract(self, key: str) -> MarketEvent | None:
        return self._last_by_contract.get(key)

    async def _on_market(self, event: MarketEvent) -> None:
        self._last_market[event.symbol] = event
        if event.contract is not None:
            self._last_by_contract[contract_key(event.contract)] = event
        contract = event.contract or self._contract_map.get(event.symbol)
        if contract:
            self._tick_writer.write(event, contract)

    async def _on_status(self, event: OrderStatusEvent) -> None:
        await self._trade_store.log_status(event)
```

- [ ] **Step 4: 跑測試確認通過 + Commit**

Run: `uv run pytest packages/storage/tests -q` → PASS

```bash
rtk git add packages/storage && rtk git commit -m "feat(storage): order status subscription, per-contract market lookup, contract-aware tick routing"
```

---

### Task 4: SimulatedExecutor — canonical ID 透傳

**Files:**
- Modify: `packages/backtest/src/backtest/executor.py:40-46`
- Test: `packages/backtest/tests/test_executor.py`（更新 `sim-N` 斷言）

- [ ] **Step 1: 更新測試**

`rtk grep "sim-" packages/backtest/tests apps/trader/tests` 找出 `sim-N` 斷言。
**只改 SimulatedExecutor 輸出的斷言**（test_executor.py、test_assembly.py 中
經 executor 產生的 fill）→ 改為斷言 `fill.order_id == order_event.order_id`
與 `fill.strategy_id == order_event.order.strategy_id`。
**不要動 `test_metrics.py`**——其中的 `sim-` 是手工建構 FillEvent 的任意標籤，
與 executor 無關（計畫審查發現）。

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest packages/backtest/tests/test_executor.py -v`
Expected: FAIL

- [ ] **Step 3: 實作**

`executor.py`：刪除 `self._fill_counter`（含 `__init__` 與遞增行），FillEvent 改為：

```python
            fill = FillEvent(
                order_id=order_event.order_id,
                legs_filled=legs_filled,
                timestamp=self._clock.now(),
                commission=total_commission,
                strategy_id=order_event.order.strategy_id,
            )
```

- [ ] **Step 4: 跑 backtest 測試 + Commit**

Run: `uv run pytest packages/backtest/tests -q` → PASS

```bash
rtk git add packages/backtest && rtk git commit -m "feat(backtest): SimulatedExecutor passes through canonical order_id and strategy_id"
```

---

### Task 5: LiveGateway 重寫 — 狀態閉環、增量 fill、內部錯誤可見化

**Files:**
- Modify: `packages/execution/src/execution/live_gateway.py`
- Test: `packages/execution/tests/test_live_gateway.py`

- [ ] **Step 1: 更新既有測試 + 寫失敗測試（逐一進行，一次一個紅燈）**

既有變更：`test_live_gateway.py:160` 一帶的 `order_id == "1"` 斷言改為
`== event.order_id`；`filledEvent` 觸發改為 `fillEvent.emit(trade, fill)`
（兩參數）。

新測試（fixture 沿用既有 mock IB + eventkit.Event 模式；`trade.log` 用
`ib_async.TradeLogEntry`）：

```python
async def test_submitted_status_published_on_place(gateway_env):
    bus, gateway, ib, received = gateway_env  # received 收集 OrderStatusEvent
    event = _order_event_single_leg()
    await gateway.on_order(event)
    assert received[0].status == "SUBMITTED"
    assert received[0].order_id == event.order_id
    assert received[0].broker_order_id == str(ib.placed_trade.orderStatus.orderId)


async def test_terminal_inactive_with_error_maps_rejected(gateway_env):
    ...
    trade.orderStatus.status = "Inactive"
    trade.log.append(TradeLogEntry(time=..., status="Inactive",
                                   message="margin insufficient", errorCode=201))
    trade.statusEvent.emit(trade)
    await asyncio.sleep(0)
    assert received[-1].status == "REJECTED"
    assert "margin" in received[-1].reason


async def test_cancel_after_warning_is_cancelled_not_rejected(gateway_env):
    # 先存活期警告（非零 errorCode），後人工取消（最後一條 errorCode=0）
    trade.log.append(TradeLogEntry(..., message="held", errorCode=399))
    trade.log.append(TradeLogEntry(..., status="Cancelled", message="", errorCode=0))
    trade.orderStatus.status = "Cancelled"
    trade.statusEvent.emit(trade)
    await asyncio.sleep(0)
    assert received[-1].status == "CANCELLED"


async def test_incremental_fills_no_double_count(gateway_env):
    # 兩次 fillEvent.emit(trade, fill_i) → 兩個 FillEvent，各含該筆 execution
    ...
    assert len(fills) == 2
    assert fills[0].legs_filled[0].quantity == 50
    assert fills[1].legs_filled[0].quantity == 50
    assert all(f.order_id == event.order_id for f in fills)
    assert all(f.strategy_id == "s1" for f in fills)


async def test_partial_status_from_fill_remaining(gateway_env):
    # fill 後 orderStatus.remaining=50 → OrderStatusEvent(PARTIAL, filled=50)
    ...


async def test_submitted_not_regressed_after_partial(gateway_env):
    # PARTIAL 之後 statusEvent 再 emit "Submitted"（filled>0）→ 派生 PARTIAL
    # 且 memo 去重，不發布倒退的 SUBMITTED
    ...
    statuses = [e.status for e in received]
    assert statuses.count("PARTIAL") == 1
    assert "SUBMITTED" not in statuses[statuses.index("PARTIAL"):]


async def test_bag_fills_attributed_per_leg(gateway_env):
    # BAG 雙腿：fillEvent 各 emit 一筆（contract 分別為兩腿期權）
    # → 兩 FillEvent 的 leg contract_key 不同
    ...


async def test_internal_error_publishes_rejected(gateway_env):
    # BAG leg con_id=0 → on_order 不拋出，發布 OrderStatusEvent(REJECTED)
    event = _order_event_bag_unqualified()
    await gateway.on_order(event)
    assert received[-1].status == "REJECTED"
    assert "con_id" in received[-1].reason
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest packages/execution/tests -v`
Expected: 新測試 FAIL

- [ ] **Step 3: 實作 LiveGateway**

`live_gateway.py` 的 `LiveGateway` 類重寫（模組層 helper `_build_single_leg`
/`_combo_limit_price`/`_build_bag`/`_to_ib_contract_with_conid`
/`_from_ib_contract` 全部不變）：

```python
from core.events import AssignmentEvent, FillEvent, OrderEvent, OrderStatusEvent

_TERMINAL_CANCEL_STATES = {"Cancelled", "ApiCancelled", "Inactive"}


class LiveGateway:
    def __init__(self, bus: EventBus, clock: Clock, ib: ibi.IB) -> None:
        self._bus = bus
        self._clock = clock
        self._ib = ib
        self._pending_tasks: set[asyncio.Task] = set()
        self._status_memo: dict[str, tuple[str, int]] = {}
        self._live_orders: dict[str, tuple] = {}  # order_id → (trade, on_status, on_fill)

    async def on_order(self, event: OrderEvent) -> None:
        order = event.order
        try:
            if len(order.legs) == 1:
                ib_contract, ib_order = _build_single_leg(order)
            else:
                ib_contract, ib_order = _build_bag(order)
            trade = self._ib.placeOrder(ib_contract, ib_order)
        except Exception as exc:
            logger.error("Order build/place failed for %s: %s",
                         order.strategy_id, exc)
            await self._publish_status(
                event.order_id, "REJECTED", reason=str(exc)
            )
            return

        broker_id = str(trade.orderStatus.orderId)
        logger.info("Placed order %s (broker %s) for %s",
                    event.order_id, broker_id, order.strategy_id)
        # 先預埋 memo 再發布：IB 隨後的 statusEvent("Submitted", filled=0)
        # 走 _on_status 時會被去重，不會發第二次 SUBMITTED（計畫審查發現）。
        self._status_memo[event.order_id] = ("SUBMITTED", 0)
        await self._publish_status(
            event.order_id, "SUBMITTED", broker_order_id=broker_id
        )

        def on_status(t: ibi.Trade) -> None:
            self._spawn(self._on_status(t, event.order_id, broker_id))

        def on_fill(t: ibi.Trade, f: ibi.Fill) -> None:
            self._spawn(
                self._on_fill(t, f, event.order_id, order.strategy_id, broker_id)
            )

        trade.statusEvent += on_status
        trade.fillEvent += on_fill
        # 保存 handler 引用供終態清理（IB 長期持有 Trade，未斷開會在
        # shutdown 後收到 late callback；計畫審查發現）。
        self._live_orders[event.order_id] = (trade, on_status, on_fill)

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._pending_tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._pending_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.critical("Gateway event task failed: %s",
                            task.exception(), exc_info=task.exception())

    async def _on_status(
        self, trade: ibi.Trade, order_id: str, broker_id: str
    ) -> None:
        ib_status = trade.orderStatus.status
        filled = int(trade.orderStatus.filled)
        remaining = int(trade.orderStatus.remaining)
        status, reason = _derive_status(ib_status, filled, trade)
        if status is None:
            return
        memo_key = (status, filled)
        if self._status_memo.get(order_id) == memo_key:
            return
        self._status_memo[order_id] = memo_key
        await self._publish_status(
            order_id, status, broker_order_id=broker_id,
            filled_quantity=filled, remaining_quantity=remaining, reason=reason,
        )
        if status in ("FILLED", "CANCELLED", "REJECTED"):
            self._cleanup_order(order_id)

    def _cleanup_order(self, order_id: str) -> None:
        # 終態清理：防 memo 洩漏 + 斷開 eventkit handler 防 late callback
        self._status_memo.pop(order_id, None)
        entry = self._live_orders.pop(order_id, None)
        if entry is not None:
            trade, on_status, on_fill = entry
            trade.statusEvent -= on_status
            trade.fillEvent -= on_fill

    async def _on_fill(
        self, trade: ibi.Trade, fill: ibi.Fill,
        order_id: str, strategy_id: str, broker_id: str,
    ) -> None:
        contract = _from_ib_contract(fill.contract)
        qty = int(fill.execution.shares)
        if fill.execution.side == "SLD":
            qty = -qty
        commission = (
            fill.commissionReport.commission if fill.commissionReport else 0.0
        )
        await self._bus.publish(
            FillEvent(
                order_id=order_id,
                legs_filled=[Leg(contract=contract, quantity=qty,
                                 entry_price=fill.execution.avgPrice)],
                timestamp=self._clock.now(),
                commission=commission,
                strategy_id=strategy_id,
            )
        )
        remaining = int(trade.orderStatus.remaining)
        if remaining > 0:
            await self._on_status(trade, order_id, broker_id)

    async def _publish_status(
        self, order_id: str, status: str, *, broker_order_id: str = "",
        filled_quantity: int = 0, remaining_quantity: int = 0, reason: str = "",
    ) -> None:
        await self._bus.publish(
            OrderStatusEvent(
                order_id=order_id, status=status, timestamp=self._clock.now(),
                broker_order_id=broker_order_id,
                filled_quantity=filled_quantity,
                remaining_quantity=remaining_quantity, reason=reason,
            )
        )


def _derive_status(
    ib_status: str, filled: int, trade: ibi.Trade
) -> tuple[str | None, str]:
    if ib_status == "Filled":
        return "FILLED", ""
    if ib_status in _TERMINAL_CANCEL_STATES:
        last = trade.log[-1] if trade.log else None
        if last is not None and last.errorCode:
            return "REJECTED", last.message
        return "CANCELLED", ""
    if ib_status in ("PendingSubmit", "PreSubmitted", "Submitted"):
        return ("PARTIAL", "") if filled > 0 else ("SUBMITTED", "")
    return None, ""
```

`on_assignment` 不變。刪除舊的 `_on_filled`/`_on_fill_done`/`_publish_fill`。

- [ ] **Step 4: 跑測試確認通過 + Commit**

Run: `uv run pytest packages/execution/tests -q` → PASS

```bash
rtk git add packages/execution && rtk git commit -m "feat(execution): order status closure, incremental fills, internal-error rejection events"
```

---

### Task 6: AppRiskState 重做 — 沖銷、greeks_lookup、min_dte、multiplier

**Files:**
- Modify: `apps/trader/src/trading_app/assembly.py:45-94`（AppRiskState）
- Test: `apps/trader/tests/test_assembly.py`

- [ ] **Step 1: 更新既有測試 + 寫失敗測試**

既有：`test_assembly.py:357` 一帶 `strategy_id == "sim-1"` → 改斷言真正的
strategy_id。新測試：

```python
def _opt(strike, right):
    return Contract(symbol="AAPL", sec_type="OPT", expiry="20991231",
                    strike=strike, right=right)


def test_netting_open_close_removes_position():
    state = AppRiskState(clock=SimClock(datetime(2026, 6, 10, tzinfo=UTC)))
    leg = Leg(contract=_opt(150.0, "C"), quantity=-1, entry_price=2.0)
    state.record_fill(FillEvent("o1", [leg], datetime.now(UTC), 1.0, "s1"))
    closing = Leg(contract=_opt(150.0, "C"), quantity=1, entry_price=1.0)
    state.record_fill(FillEvent("o2", [closing], datetime.now(UTC), 1.0, "s1"))
    assert state.positions() == []
    assert state.min_dte() is None


def test_portfolio_greeks_per_contract_lookup():
    call, put = _opt(150.0, "C"), _opt(140.0, "P")
    events = {
        contract_key(call): _mkt("AAPL", contract=call,
                                 model_greeks=Greeks(delta=0.5)),
        contract_key(put): _mkt("AAPL", contract=put,
                                model_greeks=Greeks(delta=-0.3)),
    }
    state = AppRiskState(clock=_clock(), greeks_lookup=events.get)
    state.record_fill(FillEvent("o1", [Leg(call, 1)], _now(), 0.0, "s1"))
    state.record_fill(FillEvent("o2", [Leg(put, 2)], _now(), 0.0, "s1"))
    g = state.portfolio_greeks()
    assert g.delta == pytest.approx(0.5 * 100 + (-0.3) * 2 * 100)


def test_stock_delta_no_multiplier():
    stk = Contract(symbol="AAPL", sec_type="STK")
    state = AppRiskState(clock=_clock(), greeks_lookup=lambda k: None)
    state.record_fill(FillEvent("o1", [Leg(stk, 100)], _now(), 0.0, "s1"))
    assert state.portfolio_greeks().delta == pytest.approx(100)


def test_greeks_parity_with_composite_single_symbol():
    # 單 symbol 場景：AppRiskState 聚合 == GreeksCalculator.composite
    opt = _opt(150.0, "C")
    greeks = Greeks(delta=0.5, gamma=0.02, vega=0.1, theta=-0.05)
    legs = [Leg(contract=opt, quantity=2)]
    expected = GreeksCalculator.composite(legs, {"AAPL": greeks})
    state = AppRiskState(
        clock=_clock(),
        greeks_lookup={
            contract_key(opt): _mkt("AAPL", contract=opt, model_greeks=greeks)
        }.get,
    )
    state.record_fill(FillEvent("o1", legs, _now(), 0.0, "s1"))
    actual = state.portfolio_greeks()
    assert actual.delta == pytest.approx(expected.delta)
    assert actual.vega == pytest.approx(expected.vega)
    assert actual.theta == pytest.approx(expected.theta)


def test_cashflow_uses_multiplier():
    state = AppRiskState(initial_equity=10_000.0, clock=_clock())
    leg = Leg(contract=_opt(150.0, "C"), quantity=-1, entry_price=2.0)
    state.record_fill(FillEvent("o1", [leg], _now(), 1.0, "s1"))
    assert state.equity() == pytest.approx(10_000.0 + 2.0 * 100 - 1.0)


def test_min_dte():
    state = AppRiskState(clock=SimClock(datetime(2026, 6, 10, tzinfo=UTC)))
    near = Contract(symbol="AAPL", sec_type="OPT", expiry="20260620",
                    strike=150.0, right="C")
    state.record_fill(FillEvent("o1", [Leg(near, -1)], _now(), 0.0, "s1"))
    assert state.min_dte() == 10
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `uv run pytest apps/trader/tests/test_assembly.py -v`
Expected: FAIL

- [ ] **Step 3: 實作 AppRiskState**

`assembly.py` 中整類替換：

```python
GreeksLookup = Callable[[str], MarketEvent | None]


class AppRiskState:
    def __init__(
        self,
        initial_equity: float = 0.0,
        clock: LiveClock | SimClock | None = None,
        greeks_lookup: GreeksLookup | None = None,
    ) -> None:
        self._initial_equity = initial_equity
        self._clock = clock or LiveClock()
        self._greeks_lookup = greeks_lookup or (lambda _key: None)
        self._net: dict[str, Leg] = {}
        self._strategy_by_key: dict[str, str] = {}
        self._realized_pnl: float = 0.0

    def record_fill(self, event: FillEvent) -> None:
        for leg in event.legs_filled:
            mult = leg.contract.multiplier if leg.contract.sec_type == "OPT" else 1
            if leg.entry_price:
                self._realized_pnl -= leg.quantity * leg.entry_price * mult
            key = contract_key(leg.contract)
            existing = self._net.get(key)
            new_qty = (existing.quantity if existing else 0) + leg.quantity
            if new_qty == 0:
                self._net.pop(key, None)
                self._strategy_by_key.pop(key, None)
            else:
                self._net[key] = Leg(
                    contract=leg.contract, quantity=new_qty,
                    entry_price=leg.entry_price,
                )
                self._strategy_by_key[key] = event.strategy_id
        self._realized_pnl -= event.commission

    def positions(self) -> list[Position]:
        # 語意變更（有意修正）：max_position_size 現在計算「淨未平倉合約
        # 部位數」（每個 contract_key 一筆），不再計算歷史成交筆數——
        # 舊行為連平倉 fill 都累計，是稽核確認的 bug。
        return [
            Position(legs=[leg], strategy_id=self._strategy_by_key.get(key, ""))
            for key, leg in self._net.items()
        ]

    def portfolio_greeks(self) -> Greeks:
        total = Greeks()
        for key, leg in self._net.items():
            if leg.contract.sec_type == "STK":
                total = total + Greeks(delta=leg.quantity)
                continue
            market = self._greeks_lookup(key)
            greeks = market.model_greeks if market else None
            if greeks is None:
                logger.debug("No greeks for %s; skipping", key)
                continue
            total = total + greeks * (leg.quantity * leg.contract.multiplier)
        return total

    def min_dte(self) -> int | None:
        dtes = [
            (
                datetime.strptime(leg.contract.expiry, "%Y%m%d")
                .replace(tzinfo=UTC)
                .date()
                - self._clock.now().date()
            ).days
            for leg in self._net.values()
            if leg.contract.sec_type == "OPT" and leg.contract.expiry
        ]
        return min(dtes) if dtes else None

    def equity(self) -> float:
        # backtest 現金流近似（已知限制）；live 路徑改用 AccountState
        return self._initial_equity + self._realized_pnl

    def proposed_greeks(self, signal: SignalEvent) -> Greeks:
        ...  # 不變，原樣保留
```

注意 import 增加 `UTC`、`contract_key`。`record_fill` 的現金流符號：賣出
（qty<0）收現金 → `-qty*price*mult` 為正，與既有語意一致且補上 multiplier。

- [ ] **Step 4: 跑測試 + Commit**

Run: `uv run pytest apps/trader/tests/test_assembly.py -q` → PASS

```bash
rtk git add apps/trader && rtk git commit -m "feat(app): AppRiskState netting, per-contract greeks aggregation, min_dte, multiplier-aware cashflow"
```

---

### Task 6b: PreTradeValidator — 多腿訂單按 leg 數計算部位（計畫審查迭代 2 採納）

**Files:**
- Modify: `packages/risk/src/risk/pre_trade.py:17`
- Test: `packages/risk/tests/test_pre_trade.py`

- [ ] **Step 1: 寫失敗測試**

```python
def test_multi_leg_order_counts_each_leg():
    limits = RiskLimits(max_delta=1e9, max_vega=1e9, max_drawdown=0.5,
                        max_position_size=3, max_margin_utilization=1.0)
    validator = PreTradeValidator(limits)
    # 4 腿 iron condor、現有 0 部位：4 > 3 → 拒絕
    # 用既有 _signal(legs=...) helper（test_pre_trade.py:18）；
    # 合約直接內聯建構，不引用任何不存在的 helper
    legs = [
        Leg(
            contract=Contract(symbol="SPY", sec_type="OPT", expiry="20260119",
                              strike=float(strike), right=right),
            quantity=qty,
        )
        for strike, right, qty in
        [(140, "P", 1), (145, "P", -1), (155, "C", -1), (160, "C", 1)]
    ]
    signal = _signal(legs=legs)
    # 若該測試檔尚未 import Contract/Leg，從 core.models 補 import
    result = validator.validate(signal, Greeks(), Greeks(), positions=[])
    assert not result.approved
    assert "Position limit" in result.reason
```

- [ ] **Step 2: 確認失敗**

Run: `uv run pytest packages/risk/tests/test_pre_trade.py -k multi_leg -v`
Expected: FAIL（現行 `len(positions)+1` 算 1，通過驗證）

- [ ] **Step 3: 實作**

`pre_trade.py:17` 一行變更：

```python
        new_count = len(positions) + len(signal.proposed_order.legs)
```

（與 AppRiskState 的「每 contract_key 一個淨部位」語意一致：N 腿訂單最多
新增 N 個淨部位。risk 包仍只依賴 core——無架構違規。）

- [ ] **Step 4: 跑 risk 測試 + Commit**

Run: `uv run pytest packages/risk/tests -q` → PASS

```bash
rtk git add packages/risk && rtk git commit -m "fix(risk): count each proposed leg toward max_position_size"
```

---

### Task 7: AccountState（tws-client）

**Files:**
- Create: `packages/tws-client/src/tws_client/account.py`
- Modify: `packages/tws-client/src/tws_client/__init__.py`
- Test: `packages/tws-client/tests/test_account.py`（新檔）

- [ ] **Step 1: 寫失敗測試**

```python
from types import SimpleNamespace

import eventkit

from tws_client.account import AccountState


def _av(tag, value):
    return SimpleNamespace(tag=tag, value=value, account="DU1", currency="USD")


class FakeIB:
    def __init__(self, values):
        self._values = values
        self.accountSummaryEvent = eventkit.Event()

    async def accountSummaryAsync(self, account=""):
        return self._values


async def test_equity_and_cushion_from_summary():
    ib = FakeIB([_av("NetLiquidation", "100000"), _av("Cushion", "0.45")])
    state = AccountState(ib)
    await state.start()
    assert state.equity() == 100000.0
    assert state.margin_cushion() == 0.45


async def test_cushion_fallback_computed():
    ib = FakeIB([
        _av("NetLiquidation", "100000"),
        _av("EquityWithLoanValue", "100000"),
        _av("FullMaintMarginReq", "20000"),
    ])
    state = AccountState(ib)
    await state.start()
    assert state.margin_cushion() == pytest.approx(0.8)


async def test_no_data_returns_none():
    state = AccountState(FakeIB([]))
    await state.start()
    assert state.equity() is None
    assert state.margin_cushion() is None


async def test_event_updates_values():
    ib = FakeIB([_av("NetLiquidation", "100000")])
    state = AccountState(ib)
    await state.start()
    ib.accountSummaryEvent.emit(_av("NetLiquidation", "90000"))
    assert state.equity() == 90000.0
```

- [ ] **Step 2: 確認失敗**

Run: `uv run pytest packages/tws-client/tests/test_account.py -v`
Expected: FAIL（module not found）

- [ ] **Step 3: 實作**

`packages/tws-client/src/tws_client/account.py`：

```python
import logging

import ib_async as ibi

logger = logging.getLogger(__name__)


class AccountState:
    def __init__(self, ib: ibi.IB) -> None:
        self._ib = ib
        self._values: dict[str, float] = {}

    async def start(self) -> None:
        for item in await self._ib.accountSummaryAsync():
            self._store(item)
        self._ib.accountSummaryEvent += self._store

    def _store(self, item) -> None:
        try:
            self._values[item.tag] = float(item.value)
        except (TypeError, ValueError):
            logger.debug("Non-numeric account value %s=%r", item.tag, item.value)

    def equity(self) -> float | None:
        return self._values.get("NetLiquidation")

    def margin_cushion(self) -> float | None:
        cushion = self._values.get("Cushion")
        if cushion is not None:
            return cushion
        ewl = self._values.get("EquityWithLoanValue")
        maint = self._values.get("FullMaintMarginReq")
        if ewl and maint is not None:
            return (ewl - maint) / ewl
        return None
```

`__init__.py` 加 `from tws_client.account import AccountState` 與 `__all__` 條目。

- [ ] **Step 4: 跑測試 + Commit**

Run: `uv run pytest packages/tws-client/tests -q` → PASS

```bash
rtk git add packages/tws-client && rtk git commit -m "feat(tws-client): AccountState with IB accountSummary equity and margin cushion"
```

---

### Task 8: 行情發布端附掛 contract + ConnectionManager 重連修正

**Files:**
- Modify: `packages/tws-client/src/tws_client/converters.py:25`（簽名加 contract）
- Modify: `packages/tws-client/src/tws_client/market_feed.py`、`live_data.py`
  （呼叫端把訂閱的 core Contract 傳給 converter）
- Modify: `packages/market-data/src/market_data/historical.py`
  （`subscribe_quote` yield 的 MarketEvent 附 `contract=contract`）
- Modify: `packages/tws-client/src/tws_client/connection.py`
- Test: `packages/tws-client/tests/test_converters.py`、`test_connection.py`、
  `packages/market-data/tests/test_historical.py`

- [ ] **Step 1: 寫失敗測試**

`test_converters.py`：

```python
def test_ticker_event_carries_contract():
    contract = Contract(symbol="AAPL", sec_type="OPT", expiry="20260119",
                        strike=150.0, right="C")
    event = ticker_to_market_event(_ticker(), "AAPL", contract=contract)
    assert event.contract is contract
```

`test_connection.py`：

```python
async def test_disconnect_does_not_stack_reconnect_tasks(monkeypatch):
    # 連續兩次 _on_disconnect，第二次不得建立新 task
    ...
    manager._on_disconnect()
    first = manager._reconnect_task
    manager._on_disconnect()
    assert manager._reconnect_task is first


async def test_on_reconnected_callbacks_fired(monkeypatch):
    fired = []
    manager.on_reconnected.append(lambda: fired.append(1))
    # 模擬 connectAsync 成功的 _reconnect()
    await manager._reconnect()
    assert fired == [1]
```

`test_historical.py`：斷言 yield 出的事件 `event.contract == contract`。

- [ ] **Step 2: 確認失敗** — 各檔 `-v` 跑，新測試 FAIL。

- [ ] **Step 3: 實作**

`converters.py`：

```python
def ticker_to_market_event(
    ticker: ibi.Ticker, symbol: str, contract: Contract | None = None
) -> MarketEvent:
    ...
    return MarketEvent(..., model_greeks=model_greeks, contract=contract)
```

`market_feed.py`/`live_data.py`：訂閱處已有 core `Contract`，呼叫
`ticker_to_market_event(ticker, contract.symbol, contract=contract)`。

`historical.py`：`subscribe_quote` 建構事件時附 `contract=contract`
（讀 Parquet 重建事件處，分區本身就按 contract 劃分）。

`connection.py`：

```python
    def __init__(self, ...) -> None:
        ...
        self.on_reconnected: list[Callable[[], None]] = []

    def _on_disconnect(self) -> None:
        if not self._auto_reconnect:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return
        logger.warning("TWS disconnected, reconnecting in %ds",
                       self._reconnect_delay)
        self._reconnect_task = asyncio.ensure_future(self._reconnect())

    async def _reconnect(self) -> None:
        delay = self._reconnect_delay
        max_delay = 300
        while self._auto_reconnect:
            await asyncio.sleep(delay)
            try:
                await self._ib.connectAsync(
                    self._host, self._port, self._client_id, timeout=4
                )
            except Exception:
                logger.exception("Reconnection failed, retrying in %ds",
                                 min(delay * 2, max_delay))
                delay = min(delay * 2, max_delay)
                continue
            logger.info("Reconnected to TWS")
            for callback in self.on_reconnected:
                try:
                    callback()
                except Exception:
                    logger.exception("on_reconnected callback failed")
            return
```

- [ ] **Step 4: 跑測試 + Commit**

Run: `uv run pytest packages/tws-client/tests packages/market-data/tests -q` → PASS

```bash
rtk git add packages/tws-client packages/market-data && rtk git commit -m "feat(tws-client,market-data): MarketEvent carries source contract; reconnect guard and callbacks"
```

---

### Task 9: RiskPipeline — status 訂閱、async check_now、equity-None 語意、alert logging

**Files:**
- Modify: `apps/trader/src/trading_app/assembly.py`（RiskPipeline、`_wire_risk_pipeline`、型別別名）
- Test: `apps/trader/tests/test_assembly.py`

- [ ] **Step 1: 寫失敗測試**

```python
async def test_rejected_status_emits_alert(pipeline_env):
    bus, pipeline, alerts = pipeline_env
    await bus.publish(OrderStatusEvent(order_id="o1", status="REJECTED",
                                       timestamp=_now(), reason="margin"))
    assert any("REJECTED" in a.message and "margin" in a.message for a in alerts)


async def test_check_now_triggers_circuit_break_on_margin(pipeline_env):
    # margin_cushion_provider 回 0.01 → 熔斷 + AlertEvent
    await pipeline.check_now()
    assert pipeline.circuit_breaker.is_triggered


async def test_equity_none_skips_checks_and_rejects_signals(pipeline_env):
    # equity_provider 回 None：check_now 不產生回撤警報；on_signal 拒絕
    await pipeline.check_now()
    assert not pipeline.circuit_breaker.is_triggered
    await pipeline.on_signal(_signal())
    assert orders_published == []  # 且決策日誌 reason 含 "account data unavailable"


async def test_alert_logger_subscriber(caplog):
    # log_alerts 訂閱者：AlertEvent → logger.warning
    ...
```

- [ ] **Step 2: 確認失敗** — `uv run pytest apps/trader/tests -v` FAIL。

- [ ] **Step 3: 實作**

`assembly.py`：

1. 型別別名改：`EquityProvider = Callable[[], float | None]`；新增
   `MarginCushionProvider = Callable[[], float | None]`、
   `MinDteProvider = Callable[[], int | None]`。
2. `RiskPipeline.__init__` 加參數
   `margin_cushion_provider: MarginCushionProvider | None = None`、
   `min_dte_provider: MinDteProvider | None = None`（預設 `lambda: None`）。
3. `on_signal` 開頭（circuit breaker 檢查之後）加：

```python
        if self._equity_provider() is None:
            await self._log_decision(
                signal,
                ValidationResult(
                    approved=False, reason="account data unavailable"
                ),
            )
            return
```

4. 新增 handler 與 check_now；`on_fill` 內的監控段改為呼叫 `check_now()`：

```python
    async def on_order_status(self, event: OrderStatusEvent) -> None:
        if event.status in ("REJECTED", "CANCELLED"):
            await self._bus.publish(
                AlertEvent(
                    message=(
                        f"Order {event.order_id} {event.status}: {event.reason}"
                    ),
                    value=0.0,
                    timestamp=self._clock.now(),
                )
            )

    async def check_now(self) -> None:
        if not self._monitor:
            return
        equity = self._equity_provider()
        if equity is None:
            logger.debug("Equity unavailable; skipping risk check")
            return
        greeks = self._portfolio_greeks_provider()
        min_dte = self._min_dte_provider()
        cushion = self._margin_cushion_provider()
        for alert in self._monitor.check(
            greeks, equity, min_dte=min_dte, margin_cushion=cushion
        ):
            await self._bus.publish(alert)
        if (
            self._circuit_breaker
            and not self._circuit_breaker.is_triggered
            and self._monitor.should_circuit_break(
                greeks, equity, min_dte=min_dte, margin_cushion=cushion
            )
        ):
            self._circuit_breaker.trigger()
            await self._bus.publish(
                AlertEvent(
                    message="Circuit breaker triggered",
                    value=equity,
                    timestamp=self._clock.now(),
                )
            )

    async def on_fill(self, event: FillEvent) -> None:
        if self._fill_recorder:
            self._fill_recorder(event)
        await self.check_now()
```

5. 模組層加 alert 可見性訂閱者，並在 `_wire_risk_pipeline` 接線：

```python
def log_alerts(bus: EventBus) -> None:
    async def _on_alert(event: AlertEvent) -> None:
        logger.warning("ALERT: %s (value=%s)", event.message, event.value)

    bus.subscribe(AlertEvent, _on_alert)
```

`_wire_risk_pipeline` 內加 `bus.subscribe(OrderStatusEvent, pipeline.on_order_status)`
與 `log_alerts(bus)`，並把新 providers 接上（live 在 Task 10、backtest 用
AppRiskState 的 `equity`/`min_dte` 與 `lambda: None` cushion）。

- [ ] **Step 4: 跑測試 + Commit**

Run: `uv run pytest apps/trader/tests -q` → PASS

```bash
rtk git add apps/trader && rtk git commit -m "feat(app): risk pipeline status alerts, async check_now, equity-None guard, alert logging"
```

---

### Task 10: Live 組裝 — AccountState 接線、重連迴圈、watchdog、週期檢查、config、守門

**Files:**
- Modify: `apps/trader/src/trading_app/config.py`（TwsConfig.stale_data_seconds、RiskConfig.check_interval_seconds）
- Create: `apps/trader/src/trading_app/watchdog.py`
- Modify: `apps/trader/src/trading_app/assembly.py`（LiveApp、build_live_app）
- Modify: `apps/trader/src/trading_app/cli.py`（守門 + task 接線）
- Test: `apps/trader/tests/test_watchdog.py`（新）、`test_config.py`、`test_cli.py`、`test_assembly.py`

- [ ] **Step 1: 寫失敗測試**

`test_config.py`：

```python
def test_new_timing_fields_defaults():
    config = TraderConfig()
    assert config.tws.stale_data_seconds == 60.0
    assert config.risk.check_interval_seconds == 30.0


def test_timing_fields_must_be_positive():
    with pytest.raises(ValidationError):
        TwsConfig(stale_data_seconds=0)
    with pytest.raises(ValidationError):
        RiskConfig(check_interval_seconds=-1)
```

`test_watchdog.py`：

```python
async def test_stale_symbol_alerts_once_until_recovery():
    clock = SimClock(datetime(2026, 6, 10, tzinfo=UTC))
    dog = MarketDataWatchdog(clock=clock, stale_seconds=60.0)
    await dog.on_market(_mkt("AAPL"))
    clock.advance_to(clock.now() + timedelta(seconds=61))
    assert len(dog.check_now()) == 1
    clock.advance_to(clock.now() + timedelta(seconds=61))
    assert dog.check_now() == []          # 冷卻
    await dog.on_market(_mkt("AAPL"))     # 恢復
    clock.advance_to(clock.now() + timedelta(seconds=61))
    assert len(dog.check_now()) == 1      # 重置後再告警
```

`test_cli.py`：

```python
def test_paper_guard_blocks_live_port(monkeypatch):
    monkeypatch.delenv("IB_CONFIRM_LIVE", raising=False)
    config = TraderConfig(tws=TwsConfig(port=7496))
    with pytest.raises(RuntimeError, match="IB_CONFIRM_LIVE"):
        _ensure_paper_guard(config)


def test_paper_guard_allows_paper_port():
    _ensure_paper_guard(TraderConfig(tws=TwsConfig(port=7497)))  # 不拋


def test_paper_guard_env_override(monkeypatch):
    monkeypatch.setenv("IB_CONFIRM_LIVE", "YES")
    _ensure_paper_guard(TraderConfig(tws=TwsConfig(port=7496)))  # 不拋
```

`test_assembly.py`：重連迴圈測試——

```python
class CountingDataHandler:
    """每次 subscribe_quote 立即結束 stream（模擬斷線後 stream 死亡）。"""

    def __init__(self):
        self.subscribe_count = 0

    async def subscribe_quote(self, contract):
        self.subscribe_count += 1
        return
        yield  # pragma: no cover — 使函式成為 async generator


async def test_run_market_data_resubscribes_after_reconnect(live_app_env):
    app, handler = live_app_env  # handler 為 CountingDataHandler
    app._reconnected.set()  # sticky 場景：callback 比 wait 先 fire
    task = asyncio.create_task(app.run_market_data())
    await asyncio.sleep(0)  # 第一輪結束 → wait 立即返回（sticky）→ 第二輪
    await asyncio.sleep(0)
    app._shutdown = True
    app._reconnected.set()
    await asyncio.wait_for(task, timeout=1)
    assert handler.subscribe_count >= 2


async def test_run_market_data_exits_on_shutdown(live_app_env):
    app, handler = live_app_env
    task = asyncio.create_task(app.run_market_data())
    await asyncio.sleep(0)
    app._shutdown = True
    app._reconnected.set()
    await asyncio.wait_for(task, timeout=1)  # 不掛起即通過
```

`test_cli.py`：task 生命週期——

```python
def test_run_live_creates_and_cancels_loop_tasks(monkeypatch):
    # 注意：必須是同步 def——cli.main() 內部呼叫 asyncio.run()，
    # 在 pytest-asyncio 的 async 測試內會 RuntimeError（雙重 loop）。
    # mock build_live_app 回傳 stub app（connect/run_market_data/
    # risk_check_loop/watchdog_loop/close 均為記錄呼叫的 stub coroutine），
    # mock signal handler 安裝後立即 set shutdown event。
    calls = []
    app = _StubLiveApp(calls)
    monkeypatch.setattr("trading_app.cli.build_live_app", _returns(app))
    monkeypatch.setattr("trading_app.cli.load_strategy", _noop_strategy)
    result = cli.main(["live", "--config", str(_paper_config_path)])
    assert result == 0
    assert "run_market_data" in calls
    assert "risk_check_loop" in calls
    assert "watchdog_loop" in calls
    assert calls[-1] == "close"  # close 在所有 task 結束之後
```

- [ ] **Step 2: 確認失敗** — `uv run pytest apps/trader/tests -v` FAIL。

- [ ] **Step 3: 實作**

`config.py`：

```python
class TwsConfig(BaseModel):
    ...
    stale_data_seconds: float = Field(default=60.0, gt=0)


class RiskConfig(BaseModel):
    ...
    check_interval_seconds: float = Field(default=30.0, gt=0)
```

`watchdog.py`：

```python
import logging

from core import AlertEvent, Clock, MarketEvent

logger = logging.getLogger(__name__)


class MarketDataWatchdog:
    def __init__(self, clock: Clock, stale_seconds: float = 60.0) -> None:
        self._clock = clock
        self._stale_seconds = stale_seconds
        self._last_seen: dict[str, object] = {}
        self._alerted: set[str] = set()

    async def on_market(self, event: MarketEvent) -> None:
        self._last_seen[event.symbol] = self._clock.now()
        self._alerted.discard(event.symbol)

    def check_now(self) -> list[AlertEvent]:
        now = self._clock.now()
        alerts = []
        for symbol, last in self._last_seen.items():
            age = (now - last).total_seconds()
            if age > self._stale_seconds and symbol not in self._alerted:
                self._alerted.add(symbol)
                alerts.append(
                    AlertEvent(
                        message=f"Market data stale for {symbol}: {age:.0f}s",
                        value=age,
                        timestamp=now,
                    )
                )
        return alerts
```

`assembly.py` — `build_live_app`：

```python
    account_state = AccountState(ib)
    risk_state = AppRiskState(
        initial_equity=config.risk.initial_equity,
        clock=clock,
        greeks_lookup=storage_subscriber.last_market_by_contract,
    )
    risk_pipeline = _wire_risk_pipeline(
        ...,
        equity_provider=account_state.equity,
        margin_cushion_provider=account_state.margin_cushion,
        min_dte_provider=risk_state.min_dte,
    )
```

（`_wire_risk_pipeline` 加對應參數，backtest 路徑傳 `risk_state.equity` 等。）
`LiveApp` 加欄位 `account_state: AccountState` 與 `watchdog: MarketDataWatchdog`；
`connect()` 改：

```python
    async def connect(self) -> None:
        await self.connection.connect()
        await self.account_state.start()
```

`run_market_data` 重連迴圈（sticky Event 協議）：

```python
@dataclass
class LiveApp:
    ...
    _reconnected: asyncio.Event = field(default_factory=asyncio.Event)
    _shutdown: bool = False

    def __post_init__(self) -> None:
        self.connection.on_reconnected.append(self._reconnected.set)
        self.bus.subscribe(MarketEvent, self.watchdog.on_market)

    async def run_market_data(self) -> None:
        while not self._shutdown:
            await publish_market_data(self.bus, self.data_handler, self.contracts)
            if self._shutdown:
                return
            await self._reconnected.wait()
            self._reconnected.clear()
            await self.bus.publish(
                AlertEvent(
                    message="market data restarting after reconnect",
                    value=0.0,
                    timestamp=self.clock.now(),
                )
            )

    async def risk_check_loop(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            await self.risk_pipeline.check_now()

    async def watchdog_loop(self, interval: float = 10.0) -> None:
        while True:
            await asyncio.sleep(interval)
            for alert in self.watchdog.check_now():
                await self.bus.publish(alert)

    async def close(self) -> None:
        self._shutdown = True
        self._reconnected.set()  # 喚醒 run_market_data 以便退出
        ...  # 其餘不變
```

`cli.py`：

```python
def _ensure_paper_guard(config: TraderConfig) -> None:
    paper_ports = {7497, 4002}
    if config.tws.port in paper_ports:
        return
    if os.environ.get("IB_CONFIRM_LIVE") == "YES":
        return
    raise RuntimeError(
        f"Port {config.tws.port} is not a paper trading port. "
        "Set IB_CONFIRM_LIVE=YES to confirm live trading."
    )
```

`_run_live` 在 `build_live_app` 前呼叫 `_ensure_paper_guard(config)`；
task 接線：

```python
        tasks = [
            asyncio.create_task(app.run_market_data()),
            asyncio.create_task(
                app.risk_check_loop(config.risk.check_interval_seconds)
            ),
            asyncio.create_task(app.watchdog_loop()),
        ]
        try:
            await shutdown.wait()
        finally:
            for task in tasks:
                task.cancel()
            # 必須 await 被取消的 task 再 close 共享資源（bus/storage/
            # connection），否則 teardown 期間 task 仍可能寫入（計畫審查發現）
            await asyncio.gather(*tasks, return_exceptions=True)
```

（`_run_live` 整體結構：`try` 內為 strategy 載入 + connect + tasks + wait，
`finally` 內 `await app.close()` 維持不變——gather 在內層 finally，先於
close 執行。）

**備註（計畫審查裁決）**：`LiveApp._reconnected` 用 `field(default_factory=
asyncio.Event)` 安全——Python 3.10+ 已移除 asyncio 原語的建構期 loop 綁定
（首次 await 才取 running loop），且 `build_live_app` 為 async 函式、必然在
loop 內執行。Codex 的 cross-loop Critical 主張依此否決。

- [ ] **Step 4: 跑 app 測試 + Commit**

Run: `uv run pytest apps/trader/tests -q` → PASS

```bash
rtk git add apps/trader && rtk git commit -m "feat(app): live wiring — AccountState, reconnect loop, watchdog, periodic risk check, paper guard"
```

---

### Task 11: Pre-commit hook + 全量驗證

**Files:**
- Create: `scripts/githooks/pre-commit`
- Modify: `AGENTS.md`（hook 啟用說明，一段即可）

- [ ] **Step 1: 建 hook**

`scripts/githooks/pre-commit`：

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
uv run ruff check .
uv run pytest -q
```

```bash
chmod +x scripts/githooks/pre-commit
git config core.hooksPath scripts/githooks
```

AGENTS.md 的 Build/Test 段落加一行說明：
`git config core.hooksPath scripts/githooks` 啟用 commit 前自動 lint+test。

- [ ] **Step 2: 全量驗證**

Run: `uv run pytest -q && uv run ruff check .`
Expected: 全 PASS（基線 244 + 新增測試），零 lint 錯誤。

- [ ] **Step 3: Commit**

```bash
rtk git add scripts AGENTS.md && rtk git commit -m "chore: pre-commit hook running ruff + pytest"
```

---

## 跨任務一致性備忘

- `OrderStatusEvent`、`contract_key` 由 Task 1 定義，Task 2/3/5/9 直接 import。
- `FillEvent.strategy_id` 由 Task 1 定義，Task 4/5/6 寫入/讀取。
- `AccountState` 由 Task 7 定義，Task 10 接線。
- `last_market_by_contract` 由 Task 3 定義，Task 10 注入 AppRiskState。
- `on_reconnected` 由 Task 8 定義，Task 10 的 `LiveApp.__post_init__` 掛接。
- 測試中 mock IB 事件一律用真 `eventkit.Event`（既有 test_live_gateway.py 模式），
  不可用 MagicMock（`+=` 會 rebind）。
- 所有 `.py` 寫入由 hook 自動 format——不要手動跑 ruff format。
