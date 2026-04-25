---
name: matched_pairs
description: 同股票 active vs passive 揭露日 abnormal vol 配對比較（H4' of etf-transparency-frontrunning）
---

# matched_pairs — H4' same-stock paired test

## 觸發詞

H4'、matched pairs、same-stock 配對、stock-mix confound、配對檢驗

## 一句話

跑 `tools/matched_pairs.py`：對同時被 active 和 passive 加碼的同一檔股票，分別算它在 active vs passive 揭露日的 abnormal vol median，做 paired comparison，控制掉 stock 特性，回答「H1 v2 active < passive 是不是 stock-mix 假象」。

## 速查

```bash
# 全 pipeline（重用 frontrunning vol cache）
uv run tools/matched_pairs.py --no-fetch

# 提高配對門檻（每側至少 3 events）
uv run tools/matched_pairs.py --no-fetch --min-events-per-side 3

# JSON 輸出
uv run tools/matched_pairs.py --json --no-fetch
```

## 輸出

- 終端：paired summary + Top 15 active-stronger / Top 15 passive-stronger
- `site/preview/matched_pairs.json`：完整 JSON

## 配對方法

```
對每檔同時出現在 active 和 passive 兩組的股票:
  active_median  = median([r_T for active events on this code])
  passive_median = median([r_T for passive events on this code])
  diff_median    = active_median - passive_median

paired summary:
  - sign ratio: % of stocks where active > passive
  - median of diffs
  - mean / p25 / p75 of diffs
```

## 解讀

- `median_of_diffs > +0.05` → H1 v2 翻盤被 stock-mix confound（配對下 active 仍較強）
- `median_of_diffs < -0.05` → H1 v2 結論成立（配對下 active 仍較弱）
- `|median_of_diffs| ≤ 0.05` → 兩者接近，差距可能來自 stock mix

## 已知局限

1. **overlap 樣本小**：典型 ~28 檔。min-events-per-side 太高會更小，太低引入 outlier
2. **passive 那側 n 普遍 2-5**：易被單事件 outlier 主導（國巨、台灣大這類）
3. **沒考慮時間分佈**：同股 active vs passive event date 可能落在不同市場 regime
4. **沒做正式 statistical test**：用 sign ratio + median diff 替代 Wilcoxon（缺 scipy）

## 跟其他工具的關係

- `frontrunning.py`：events 來源 + abnormal_ratio function
- `cumulative_drag.py`：H4 的 portfolio-aggregate 版（per-AUM 累積）
- 三者是 H1 / H4 / H4' 的並列檢驗，共用 events + vol cache

## 對應 mechanism page

- [[wiki/mechanisms/etf-transparency-frontrunning]]
- 檢驗 **H4'**（H1 v2 是否被 stock mix confound）
- 結果（2026-04-25）：86% overlap stocks passive 較強，median diff -0.99 → H1 v2 強化
