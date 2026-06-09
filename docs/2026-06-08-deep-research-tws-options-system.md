# TWS 期權交易系統深度研究報告

**日期**: 2026-06-08
**方法**: 深度研究工作流（104 agent、22 來源、84 claims、25 對抗驗證、21 確認 / 4 駁回）

---

## 一、TWS API 與 ib_async 升級建議

### 1. ib_async v2.0.1 重大更新 (信心：高)

**來源**: https://github.com/ib-api-reloaded/ib_async

| 新特性 | 對專案的影響 |
|--------|------------|
| **Greeks 原生數學運算**（加/減/乘） | 可取代 `greeks_calc.py` 的手動計算邏輯 |
| **Bag contracts 可 hash** | LiveGateway 的 BAG combo 追蹤可用 dict/set |
| **Order deletion bug fix** | 修正驗證警告時誤刪活單的致命 bug |

行動項: 升級至 v2.0.1+，評估是否用原生 Greeks 運算取代 `GreeksCalculator.composite()`。

### 2. 歷史數據 pacing 限制 (信心：高)

**來源**: https://interactivebrokers.github.io/tws-api/historical_limitations.html

- **硬上限**: 50 個同時開啟的歷史數據請求
- **Pacing violations 觸發條件**（30 秒以下 bar）：
  - 15 秒內重複相同請求
  - 2 秒內對同一合約 6+ 請求
  - 10 分鐘內 60+ 請求
  - BID_ASK 請求**雙倍計算**
- **期權鏈查詢**: `reqSecDefOptParams` **無節流限制**，官方明確建議取代 `reqContractDetails`

行動項: market-data package 需實作 semaphore-based request throttler，期權鏈改用 `reqSecDefOptParams`。

---

## 二、風險管理強化

### 3. Margin 即時監控 (信心：高)

**來源**: https://interactivebrokers.github.io/tws-api/margin.html, https://www.ibkrguides.com/traderworkstation/margin-monitoring.htm

| 機制 | 用途 |
|------|------|
| **WhatIf Order** (`Order.WhatIf=True`) | 下單前模擬 margin 影響，回傳 `OrderState` 含 InitMargin/MaintMargin Before/After |
| **五種 Margin 類型** | Current Initial、Current Maintenance、Post-Expiry、Look Ahead、Overnight |
| **三級警報** | Yellow (10% cushion)、Orange (cushion 耗盡)、Red (即將清算) |

注意: ib_insync issue #380 記錄了 WhatIf 回應的 timing bug，可能回傳 default/infinity 值，需實作回應驗證。

行動項: `PreTradeValidator` 整合 WhatIf margin 檢查，`RealTimeMonitor` 加入 margin cushion 監控。

### 4. Gamma / Pin Risk 管理 (信心：高)

**來源**: https://menthorq.com/guide/gamma-risk/, OCC, Numerix 白皮書

- ATM 期權到期前 delta 可從 0.50 劇烈變動至 0.90 或接近 0（~1% 標的波動即觸發）
- **Pin risk**: 標的在到期日收盤價接近 strike 時，assignment 不確定性持續至 5:30 PM ET
- **建議緩解**: 到期日最後交易時段平倉接近 strike 的 short options

行動項: risk package 需加入 DTE 感知的 gamma 監控，隨到期日接近升級警報等級。

---

## 三、執行流程優化

### 5. BAG Combo 下單機制 (信心：高)

**來源**: https://www.ibkrguides.com/traderworkstation/notes-on-combination-orders.htm, https://www.interactivebrokers.com/campus/trading-lessons/python-complex-orders/, https://interactivebrokers.github.io/tws-api/spread_contracts.html

| 規則 | 詳情 |
|------|------|
| **Limit price 正負號** | 收到現金 = 正（賣 credit spread）、付出現金 = 負（買 debit spread） |
| **NonGuaranteed 參數** | 非保證單需顯式設定 `smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]` |
| **腿數上限** | 保證 spread 最多 6 腿 |
| **SmartRouting** | 逐腿分別路由，IB 吸收 legging risk（保證模式）或由交易者承擔（非保證模式） |

專案現況: `LiveGateway._build_bag()` 已實作基本 BAG pattern，但缺少 NonGuaranteed 設定和 limit price 正負號處理邏輯。

### 6. Adaptive Algo 限制 (信心：高)

**來源**: https://www.interactivebrokers.com/campus/trading-lessons/adaptive/

> Adaptive Algo 不支援 spread/combo 訂單，僅適用於單腿訂單。

關鍵限制：專案主要策略（Iron Condor、Credit Spread 等）都是多腿，無法使用 Adaptive Algo。執行層需依賴標準 LMT/MKT 或 REL+MKT 訂單類型。

---

## 四、盈虧比與策略選擇框架

### 7. Iron Condor 最佳參數 (信心：中)

**來源**: https://quantstrategy.io/blog/how-to-build-and-adjust-the-iron-condor-strategy-for/, https://docs.orats.io/backtest-api-guide/backtester-methodology.html, projectfinance.com (71,417 筆回測), tastytrade 研究

| 參數 | 建議值 | 來源 |
|------|--------|------|
| Short strike delta | 10-20 delta | 多來源一致 |
| DTE | 30-45 天 | tastytrade 16delta/45DTE 研究 |
| 獲利出場 | 收到 premium 的 50% | 71,417 筆回測 ~85% managed win rate |
| 時間出場 | 21 DTE 前 | gamma risk 管理（此 claim 被 1-2 駁回為非絕對標準） |
| **POP 參考** | 10delta: 80-90%, 20delta: 70-80% | 理論值，未計入 credit buffer |

### 回測滑價模型（ORATS）(信心：高)

| 腿數 | 填單品質（mid-point 比例） | 公式 |
|------|---------------------------|------|
| 1 腿 | 75% | Buy = Bid + (Ask-Bid) * 0.75 |
| 2 腿 | 66% | |
| 3 腿 | 56% | |
| 4 腿 | 53% | Sell = Ask - (Ask-Bid) * 0.53 |

行動項: backtest package 需整合 ORATS 滑價模型，strategy package 需加入 delta-based strike selector。

---

## 五、被駁回的聲明

| 聲明 | 投票 | 真相 |
|------|------|------|
| 「已到期期權歷史數據完全不可用」 | 1-2 | IB 有提供部分已到期期權數據，有限制但非完全不可用 |
| 「所有多腿單必須用 BAG + reqContractDetails 取得 conId」 | 1-2 | conId 也可從 `reqSecDefOptParams` + `qualifyContracts` 取得 |
| 「Adaptive Algo 平均填單價格優於一般限價單」 | 1-2 | 來源過度推論 |
| 「21 DTE 是 gamma 風控的業界標準閾值」 | 1-2 | 常用但非絕對標準 |

---

## 六、專案缺口與優先行動項

### P0（高風險，影響正確性）
1. **`LiveGateway` limit price 正負號處理** — credit spread 用正價、debit spread 用負價
2. **NonGuaranteed combo routing 參數** — 缺少此設定可能導致下單被拒
3. **WhatIf margin 檢查** — 整合至 `PreTradeValidator`
4. **ib_async 升級至 v2.0.1+** — 修正活單誤刪 bug

### P1（風控強化）
5. **Gamma/DTE 監控** — 到期日接近時升級警報，自動建議平倉
6. **Margin cushion 即時監控** — 三級警報系統
7. **ORATS 滑價模型** — 整合至 backtest executor

### P2（策略優化）
8. **Delta-based strike selector** — 取代固定寬度翅膀
9. **Theta decay sweet spot 入場** — 30-45 DTE 視窗
10. **50% profit exit 機制** — 自動獲利了結

### P3（架構改進）
11. **Request throttler** — semaphore-based，遵守 50 並發 / 10 分鐘 60 次限制
12. **期權鏈改用 `reqSecDefOptParams`** — 避免 throttling
13. **GreeksCalculator 升級** — 評估原生 Greeks 運算 vs fallback

---

## 七、待解問題

1. ib_async v2.1.0 vs v2.0.1 — 是否修復了 WhatIf margin timing bug？
2. 保證 vs 非保證 combo 填單品質差異 — 需實測比較
3. 五種 margin 類型的閾值對映 — 哪種觸發哪級 circuit breaker？
4. ORATS 滑價模型 vs 實際 IB SmartRouted combo 填單 — 是否充分近似？

---

## 來源清單

### 官方文件（Primary）
- https://github.com/ib-api-reloaded/ib_async
- https://interactivebrokers.github.io/tws-api/historical_limitations.html
- https://interactivebrokers.github.io/tws-api/options.html
- https://interactivebrokers.github.io/tws-api/margin.html
- https://interactivebrokers.github.io/tws-api/spread_contracts.html
- https://www.ibkrguides.com/traderworkstation/notes-on-combination-orders.htm
- https://www.ibkrguides.com/traderworkstation/margin-monitoring.htm
- https://www.interactivebrokers.com/campus/trading-lessons/python-complex-orders/
- https://www.interactivebrokers.com/campus/trading-lessons/adaptive/
- https://docs.orats.io/backtest-api-guide/backtester-methodology.html

### 社群與部落格
- https://github.com/ib-api-reloaded/ib_async/discussions/105
- https://github.com/ib-api-reloaded/ib_async/discussions/119
- https://menthorq.com/guide/gamma-risk/
- https://quantstrategy.io/blog/how-to-build-and-adjust-the-iron-condor-strategy-for/
- https://optionalpha.com/help/understanding-alpha-and-expected-value
- https://datadrivenoptions.com/rolling-iron-condors/
- https://www.theoptionpremium.com/p/best-stocks-for-credit-spreads-a-7-step-selection-framework
- https://www.quantstart.com/articles/Event-Driven-Backtesting-with-Python-Part-I/

*統計: 5 個搜尋角度 | 22 來源 | 84 聲明 | 25 對抗驗證 | 21 確認 / 4 駁回 | 7 合成發現*
