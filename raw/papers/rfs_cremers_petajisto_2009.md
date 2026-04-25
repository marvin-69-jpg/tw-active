---
title: How Active Is Your Fund Manager? A New Measure That Predicts Performance
authors: [K. J. Martijn Cremers, Antti Petajisto]
year: 2009
month: 09
venue: Review of Financial Studies
volume: 22
issue: 9
pages: 3329-3365
doi: 10.1093/rfs/hhp057
ssrn_id: 891719
url: https://academic.oup.com/rfs/article-abstract/22/9/3329/1574080
pdf: null  # RFS paywall + SSRN paywall + Petajisto 個人站只放 SSRN link
accessed: 2026-04-25
fetched_via: tools/papers.py search (crossref) — metadata only
citations: 1262
followup: 2013 Financial Analysts Journal 69(4) "Active Share and Mutual Fund Performance" (Petajisto solo, SSRN 1685942)
---

# How Active Is Your Fund Manager? — Cremers-Petajisto (2009 RFS)

## 為什麼沒抓到 PDF

- RFS paywall
- SSRN 891719 paywall（compliance-first 套不過）
- Petajisto 個人站 [petajisto.net/research.html](https://www.petajisto.net/research.html) 只放 SSRN 連結，沒貼 PDF
- 沒有對應的 NBER WP

## 核心概念：Active Share

$$\text{Active Share} = \frac{1}{2} \sum_i \left| w_{\text{fund},i} - w_{\text{bench},i} \right|$$

- $w_{\text{fund},i}$ = 基金對股票 $i$ 的權重
- $w_{\text{bench},i}$ = benchmark 對股票 $i$ 的權重
- AS = 0 → 完全複製 benchmark（**closet indexer**）
- AS = 1 → 完全不重疊
- 經驗門檻：**< 60% = closet indexer**，**> 80% = truly active**

## 重點 takeaways

1. **Active Share 是 Tracking Error 的補集**
   - Tracking Error 衡量「波動偏離」
   - Active Share 衡量「持股偏離」
   - 兩個維度組成 2×2 矩陣：高 AS + 低 TE = stock picker；低 AS + 高 TE = factor bet；高 AS + 高 TE = concentrated stock picker；低 AS + 低 TE = closet indexer
   - 傳統只看 TE 會把 closet indexer 跟 factor bet 混在一起

2. **實證：高 AS 預測較高 alpha**
   - Top quintile AS（基本上 stock picker）net-of-fee benchmark-adjusted alpha 顯著為正
   - Bottom quintile AS（closet indexer）net alpha 顯著為負——**收主動 fee、做被動事**
   - 對 small-cap fund 尤其明顯

3. **closet-indexing 是顯著現象**
   - 樣本中很大比例的「主動」基金 AS < 60%
   - 1980 年代 closet indexing 罕見、2000 年代後比例飆升（fee 競爭壓力）

4. **方法論貢獻**
   - 引入一個**規範性**指標（不只 descriptive）——AS 數字本身就是「主動程度」的衡量，可以拿來 lint fund 的命名
   - 後續監管（特別是歐洲 ESMA）把 AS 揭露列為主動基金分類的考量

## 跟 PSTZ 路線的關係

- PSTZ 2014 在 fund 層面找不到 diseconomies → fund-level alpha 平均 ≈ 0
- Cremers-Petajisto 切角度：fund 層平均 ≈ 0 是因為**裡面摻了大量 closet indexer 拉低**，把 closet indexer 篩掉後，true active 仍有 alpha
- 兩家不衝突——平均 0 是 industry composition 的結果

## 後續

- Petajisto (2013 FAJ) "Active Share and Mutual Fund Performance"（SSRN 1685942）——更新樣本、回應 Frazzini-Friedman-Pomorski (AQR 2016) 的批評
- Cremers, Ferreira, Matos, Starks (2016 JFE) 跨國研究：AS 揭露規則跨國比較
- 學界爭議仍在：AQR 一派質疑 AS-alpha 關聯只是 size 因子代理

## 對台灣主動 ETF 的 implication

- **可以直接算**：用 cmoney 21 檔 active ETF 持股 + 0050 基準持股 → 算每檔 AS，看誰是真主動、誰是 closet
- **預期**：規模大的主動 ETF AS 會偏低（呼應 [[wiki/mechanisms/diseconomies-of-scale]] 的「規模一上來會 closet 化」），規模小的可能 AS 較高
- **揭露落差**：台灣主動 ETF 沒有 AS 揭露要求，投資人無法直接判斷一檔基金是真主動還是 closet——這是個明顯的 disclosure gap
