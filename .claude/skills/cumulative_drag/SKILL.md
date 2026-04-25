---
name: cumulative_drag
description: 主動 ETF 年化 cumulative front-running drag / AUM（H4 of etf-transparency-frontrunning mechanism）
---

# cumulative_drag — H4 年化累積 IP-leak 暴露

## 觸發詞

H4、cumulative drag、年化累積 cost、turnover × frontrunning、累積 leak

## 一句話

跑 `tools/cumulative_drag.py`：在 frontrunning H1 v2 之上，把每事件的 abnormal vol 按「年化加總、normalize by AUM」算，比較 active vs passive 累積 cost，回答「主動 ETF 雖然 per-event leak 較小，但 turnover 高頻、累積是否反而更大？」

## 速查

```bash
# 全 pipeline（重用 frontrunning vol cache，不用再 fetch）
uv run tools/cumulative_drag.py --no-fetch

# 含 fetch（首次跑 / 補新 events）
uv run tools/cumulative_drag.py

# 限定主動 ETF
uv run tools/cumulative_drag.py --etfs 00981A,00994A --no-fetch

# JSON 輸出
uv run tools/cumulative_drag.py --json --no-fetch
```

## 輸出

- 終端：group pooled / active by-ETF / passive by-ETF 三表
- `site/preview/cumulative_drag.json`：完整 JSON

## Metric

對每事件（reuse frontrunning events）：
```
excess_ratio          = max(r_T - 1, 0)
excess_volume_shares  = excess_ratio × baseline_med_vol     # generic spillover
manager_drag          = |Δshares| × excess_ratio            # bound by manager exposure
```

ETF 層級年化 + AUM normalize：
```
annualizer = 365 / days_span
per_AUM_kshares_per_yi = sum(metric) × annualizer / 1000 / AUM_yi
```

Pooled = AUM-weighted across ETFs。

## 對齊規則（重要）

**被動事件強制限制到主動的時間窗口**（active dates min..max）。raw shares-passive 有 800 個揭露日，主動只有 ~239 日，不對齊就是拿不對等的累積期間比。

## 已知局限

1. **沒乘 close price**：FinMind 配額用完，metric 維度是「股」不是 NTD。跨股票（不同單價）粗略
2. **AUM 是 snapshot**：用最近 AUM 估早期 ETF 的 per-AUM cost，會 underestimate
3. **00401A/00997A 太新**：baseline window 不足，全 0 被 filter（占 active AUM 2.9%，對結論影響小）
4. **passive 樣本只有 5 檔**：0056 一檔 single-handedly 主導 passive baseline

## 跟 frontrunning 的關係

- **frontrunning.py** = per-event ratio summary（看 magnitude）
- **cumulative_drag.py** = annualized × AUM-normalized（看 cumulative cost）
- 兩者共用 events、vol cache，但 metric / aggregation 不同
- H1 是「per-event 主動是否較強」（v2 答案：不是）；H4 是「per-AUM 年化是否較強」

## 對應 mechanism page

- [[wiki/mechanisms/etf-transparency-frontrunning]]
- 檢驗 **H4**：高 turnover × per-event front-running → 累積 drag 更大
- 結果：weakly supported（active drag/AUM = 2.0× passive，driver 是 events/yr 高 20×）
