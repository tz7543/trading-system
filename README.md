# Trading System

美股量化交易系統，整合技術分析、風控管理與自動化執行。

## 功能

- 技術分析（VWAP、均線、布林帶、量價）
- 風控計算（停損 / 加倉 / 盈虧比 / 部位大小）
- 海龜交易策略（CTA 突破點位）
- 盤前掃描 / 強勢股篩選
- Interactive Brokers 下單整合

## 專案結構

```
trading-system/
├── strategies/     # 交易策略
├── analysis/       # 技術分析模組
├── risk/           # 風控計算
├── data/           # 資料取得與處理
└── tests/          # 測試
```

## 環境需求

- Python 3.11+
- Interactive Brokers TWS / IB Gateway

## 快速開始

```bash
pip install -r requirements.txt
python main.py
```
