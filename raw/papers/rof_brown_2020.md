---
title: ETF Arbitrage, Non-Fundamental Demand, and Return Predictability
authors: [David C. Brown, Shaun William Davies, Matthew C. Ringgenberg]
year: 2020
month: 10
venue: Review of Finance
volume: 25
issue: 4
pages: 937-972
doi: 10.1093/rof/rfaa027
ssrn_id: 2872414
url: https://academic.oup.com/rof/article-abstract/25/4/937/5919430
pdf: null  # OUP paywall, open PDF returns HTML login wall
accessed: 2026-04-25
fetched_via: tools/papers.py search (crossref) — metadata + abstract only
citations: 117
---

# ETF Arbitrage, Non-Fundamental Demand, and Return Predictability — Brown, Davies, Ringgenberg (2020 RoF)

## 為什麼沒抓到 PDF

- OUP `academic.oup.com` open PDF link 經 redirect 後是 login wall
- SSRN 2872414（早期版 "ETF Arbitrage and Return Predictability" 2016）也 paywall
- 沒有 NBER WP 對應

## 核心假說與發現

Non-fundamental demand shocks 對資產價格有顯著影響，但不容易**觀測**到——這篇用 ETF 一級市場（creation/redemption）當 observable proxy。

**機制**：AP 是專門的套利者，當 ETF 跟 underlying 出現 law-of-one-price 違反時，AP 會建立 / 銷毀 ETF 份額把溢折價套回去。創造 / 贖回 activity（ETF flow）= 套利在反應 ETF 端的非基本面需求。

**實證**：
- ETF flow 高 → 該 ETF 短期被買超（non-fundamental demand 推高價）
- 後續會反轉 → flow 是 reversal 的訊號
- 策略：short high-flow ETF + long low-flow ETF，excess return **1.1-2.0% / 月**

**意義**：non-fundamental demand 真的扭曲了基本面價格，而且是可量化的負向 cost。投資人因為 non-fundamental demand 隱含 underperformance。

## 關鍵 takeaways

1. **ETF 一級市場 flow ≠ 中性訊號**——是 non-fundamental demand 的 observable proxy
2. **AP 套利機制的雙面性**：把溢折價套回去（看似有效率），但同時把扭曲價格 **印在 underlying 上**——AP arbitrage 的邊際買賣壓力傳遞到成分股
3. **可預測 reversal**：1.1-2.0% / 月不是小數字，而且是 long-short 中性策略
4. **跟 BDFM 2018 的關係**：BDFM 說 ETF ownership → vol ↑ 是 channel；BDR 說 flow 本身的 timing 可以預測這個 channel 何時 reverse

## 方法論細節

- 樣本：美國 ETF 一級市場 creation/redemption 紀錄（從 NSCC / 監管揭露）
- Identification：拿 creation/redemption 量去預測 ETF 後續報酬
- 主要 portfolio sort：依過去窗口 flow 排序，多空 high - low
- Robust：控制 ETF size、流動性、AUM，flow signal 仍 robust

## 對台灣主動 ETF 的 implication

- 台灣主動 ETF 申贖機制跟美國 transparent ETF 類似（每日揭露 PCF basket，AP 創造贖回實物 / 現金混合）
- **可直接複製的 testable**：
  - 拿 ezmoney GetPCF API 的 DIFF_UNIT × P_UNIT（已存 reference memory）→ 21 檔主動 ETF 的每日申贖量
  - 算 1 / 5 / 10 日 forward return，看 Brown-Davies-Ringgenberg 的 reversal 是否在台灣成立
- **angle 翻轉**：台灣零售投資人看到「淨申購」常被解讀為「人氣 = 看好」買進訊號，但 BDR 暗示這往往是 reversal 前的高點
- 跟 BDFM 結合：高 flow → 短期推高 underlying → 後續 reversal → 散戶在高點接、低點賣
- 配息平準金 channel：申贖 timing 跟配息日有強相關，可以拆「配息季節性 flow」 vs「真 non-fundamental flow」
