---
name: frontrunning
description: 主動 ETF 揭露日異常成交量（H1 of etf-transparency-frontrunning mechanism）
---

# frontrunning — H1 front-running effect 量測

## 觸發詞

front-running、揭露日異常量、H1、frontrunning、leak cost

## 一句話

跑 `tools/frontrunning.py` 把 21 檔主動 ETF 的「加碼事件」對應到 FinMind 個股成交量，算 abnormal volume ratio（vol(T) / median(vol[T-20:T-1])），輸出 pooled / per-ETF / new-vs-add 三層摘要。

## 速查

```bash
# 全 pipeline（events → fetch FinMind → analyze）
uv run tools/frontrunning.py

# 單檔測試
uv run tools/frontrunning.py --etfs 00981A

# 改顯著條件
uv run tools/frontrunning.py --min-pct 10 --min-shares 500000

# 只用 cache 不抓網路
uv run tools/frontrunning.py --no-fetch
```

## 輸出

- 終端：pooled / by-kind / by-ETF 三表
- `site/preview/frontrunning.json`：完整 JSON（可被 site/ 前端視覺化）
- `.cache/volumes/<code>.json`：FinMind 個股成交量快取（per-stock，跨 ETF 共用）

## 事件定義

對每檔 ETF × 股票時序：
- prev_shares → cur_shares：Δ > 0
- 顯著條件：`Δ% >= --min-pct (預設 5%)` 或 `is_new_position`
- 絕對下限：`Δ >= --min-shares (預設 100,000 股)`
- 第一個揭露日不算（沒 prev）

## Abnormal ratio

```
r(T)   = vol(T)   / median(vol[T-20 : T-1])
r(T+1) = vol(T+1) / median(vol[T-20 : T-1])
```

H1 預期 mean ratio > 1.0；衰減（T → T+1 → T+2）也是 expected pattern。

## 已知局限（重要）

1. **Δshares > 0 是 noisy events**——混了主動加碼與 AP creation 兩條 channel，沒分離
2. **反向因果風險**——「volume 已先漲 → manager 看到買單跟進」也會產生 ratio > 1。要分離需看 T-1 → T 的 timing；目前只看 ≥ T
3. **沒有對照組**——passive ETF 加碼相同股票時的 abnormal vol 對照組留 v2
4. **Baseline window 固定 20 trading days**——對波動行情可能 bias

## 跟其他工具的關係

- 事件來源：`raw/cmoney/shares/<ETF>.json`（外部 CI 每日 push）
- 量資料：FinMind `TaiwanStockPrice` 的 `Trading_Volume` 欄（同 `tools/preview_prices.py` 用的 dataset，但本 tool 用 volume 不用 close）
- AUM：`raw/cmoney/meta/<ETF>.json` 第 8 欄（億）

## 對應 mechanism page

- [[wiki/mechanisms/etf-transparency-frontrunning]]
- 檢驗的是該 page 的 **H1**（其他 H 還沒實作）
