---
title: 影子指數化（Closet Indexing）與 Active Share
type: mechanism
tags: [active-management, closet-indexing, active-share, tracking-error, disclosure-gap]
slug: closet-indexing
aliases: [closet indexer, active share, AS, 影子指數, 假主動, 實質被動]
created: 2026-04-25
updated: 2026-04-25
sources:
  - raw/papers/rfs_cremers_petajisto_2009.md
  - raw/papers/nber_w19891.md
---

# 影子指數化（Closet Indexing）與 Active Share

## TL;DR

「主動」基金可能持股結構幾乎照抄 benchmark，只在權重上小幅偏離——拿主動的 fee、做被動的事。Cremers & Petajisto (2009 RFS) 提出 **Active Share (AS)** 作為衡量「持股偏離」的標準化指標。台灣主動 ETF 沒有 AS 揭露規範，投資人無法直接判斷一檔基金是真主動還是 closet——這是直接可指出的揭露漏洞，而且我們有資料可以自己算。

## Compiled Truth

### Active Share 的定義

$$\text{AS} = \frac{1}{2} \sum_i \left| w_{\text{fund},i} - w_{\text{bench},i} \right|$$

每檔股票算「基金權重 - benchmark 權重」絕對值，全部加總除以 2。範圍 0–1：
- **AS = 0** → 完全複製 benchmark = 完美 closet
- **AS = 1** → 完全不重疊 = 持股全在 benchmark 之外
- 經驗門檻（Cremers-Petajisto 2009）：
  - **AS < 60%** → closet indexer
  - **AS > 80%** → truly active
  - 60–80% → 中間地帶（factor tilt 為主）

### Active Share vs Tracking Error

兩個維度衡量「主動程度」的不同 channel：

| | 低 TE（波動偏離小） | 高 TE（波動偏離大） |
|---|---|---|
| **低 AS（持股近 benchmark）** | closet indexer | factor bet（systematic risk tilt） |
| **高 AS（持股遠 benchmark）** | diversified stock picker | concentrated stock picker |

只看 TE 會把 closet indexer 跟 factor bet 混在一起。Active Share 是 TE 的**補集**，不是替代。

### 為什麼 closet indexing 會發生

1. **Fee 與 benchmark 風險的不對稱**——主動 fee 收的是「跑贏」期望，但若跑輸 benchmark，AUM 會大量流失。經理人有強誘因「不要輸太多」→ hugging benchmark
2. **規模遞減**——AUM 大到一定程度，要部署的資金太大，被迫稀釋到大型權值股，不知不覺收斂到 benchmark（[[wiki/mechanisms/diseconomies-of-scale]] 的副產品）
3. **Career risk**——個人經理人不想承擔 underperform benchmark 的職涯風險，會選 hug

### 我觀察到的漏洞 / 不對稱（台灣主動 ETF 場景）

- **AS 無揭露要求**——台灣 SITCA / FSC 對主動 ETF 沒有 AS 揭露規範。歐洲 ESMA 已要求基金分類時揭露 AS，台灣沒跟上。投資人想判斷「這檔到底多主動」只能自己算 [speculation - 法規範圍待補]
- **Benchmark 選擇 arbitrage**——台灣主動 ETF 公開說明書多數寫「不限定追蹤特定指數」或寫「**績效比較指標**」（不是「追蹤指標」）。沒有 binding benchmark 的話 AS 計算 base 模糊，issuer 可以選對自己有利的 benchmark 自評，這個結構性 loophole 比有 binding benchmark 的美國基金更嚴重
- **可量化的監測命題**：用我們有的 cmoney 21 檔主動 ETF 持股 × 0050 持股，可以算每檔 AS（vs 0050）：
  - 預測 1：規模 > 50 億的主動 ETF AS 會 < 70%（大部位被迫往大型股集中）
  - 預測 2：科技類（00989A、00991A、00992A）AS 會比較高（自選成分多）
  - 預測 3：高息類（00984A、00998A）AS 會接近 00919/00713 等被動高息 ETF（投資宇宙重疊度高）
- **配息平準金當 closet 的「掩護」**——若一檔主動 ETF 實質是 closet 但 fee 是 1.2%（高於 0050 的 0.32%），唯一把費差「賺回來」的方式是高息——但高息又透過收益平準金 / 資本利得分配虛胖，投資人看到的「殖利率」掩護了實質的 closet+fee drag。詳見 [[wiki/mechanisms/income-equalization]]（待建）

## Timeline

- **2026-04-25** — 抓 Cremers-Petajisto 2009 RFS metadata（PDF paywall），開此 mechanism page；計畫做台灣主動 ETF 的 AS 計算 prototype（[[raw/papers/rfs_cremers_petajisto_2009]]）

## Related

- [[wiki/mechanisms/diseconomies-of-scale]] — closet indexing 的「為什麼會發生」之一
- [[wiki/mechanisms/income-equalization]] — closet 的「掩護機制」（待建）
- [[wiki/mechanisms/tracking-error]] — 跟 AS 互補的另一個維度（待建）

## Sources

- [[raw/papers/rfs_cremers_petajisto_2009]] — Cremers & Petajisto (2009) "How Active Is Your Fund Manager?" *RFS* 22(9)
- [[raw/papers/nber_w19891]] — PSTZ 2014（提供「為什麼平均 alpha = 0」的另一個解釋角度）
- 後續未抓：
  - Petajisto (2013) "Active Share and Mutual Fund Performance" *FAJ* 69(4)
  - Cremers, Ferreira, Matos, Starks (2016) "Indexing and Active Fund Management: International Evidence" *JFE*
