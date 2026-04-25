---
title: Do ETFs Increase Volatility?
authors: [Itzhak Ben-David, Francesco Franzoni, Rabih Moussawi]
year: 2018
month: 12
venue: Journal of Finance
volume: 73
issue: 6
pages: 2471-2535
doi: 10.1111/jofi.12727
nber_id: w20071
ssrn_id: 1967599
url: https://onlinelibrary.wiley.com/doi/10.1111/jofi.12727
pdf: raw/papers/nber_w20071.pdf  # NBER WP 2014 完整版
accessed: 2026-04-25
fetched_via: tools/papers.py search (crossref) + curl NBER
citations: 533
related_earlier: 2011 SSRN 1967599 "ETFs, Arbitrage, and Contagion"
related_later: 2016 NBER w22829 "Exchange Traded Funds (ETFs)" (survey)
---

# Do ETFs Increase Volatility? — Ben-David, Franzoni, Moussawi (2018 JoF)

## 來源

- 期刊版：Journal of Finance 73(6), 2018-11-18，paywall（Wiley）
- NBER 完整版：w20071，2014-04，open access PDF（已存 raw）
- 引用 533 次（2026-04 crossref），後 ETF microstructure 文獻的核心 anchor

## 核心假說與發現

ETF 因為交易成本低、流動性高，是 short-horizon liquidity traders 的 catalyst。流動性 shock 可以透過 **arbitrage channel**（AP 創造/贖回）傳播到 underlying securities，使成分股 **non-fundamental volatility 上升**。

實證設計：用 index reconstitution 的 exogenous variation（被納入指數的股票會被 ETF 持有，這個變化外生於股票本身基本面）。

主要 findings：
1. ETF ownership 高的股票，**volatility 顯著較高**
2. ETF ownership 增加股票價格的 **negative autocorrelation**（reversal pattern，符合 non-fundamental shock 後續被 correct）
3. 這個 volatility 上升是**不可分散的風險**，市場有定價：高 ETF ownership 股票 earn risk premium up to **56 bps / 月**

## 關鍵 takeaways

1. **ETF 不只是被動載體**——AP 套利機制把 ETF 流量翻譯成成分股的真實買賣壓力；持有比例越高的股票越被影響
2. **方向性結論**：ETF inclusion 不是中性，是會增加 host stock 的非基本面波動
3. **delegate trading 的副作用**：散戶買 ETF（看似分散風險），實際把 idiosyncratic noise 注入成分股
4. **後續文獻分支**：
   - **Brown-Davies-Ringgenberg (2020 RoF)** 接著做：ETF flow 本身就是 non-fundamental demand 的訊號，可預測 reversal
   - **Easley et al (2021 RoF)** 指出 ETF 不是同質的，要拆「active in form」vs「active in function」

## 方法論細節

- 樣本：1996-2014 美國上市 ETF + 成分股
- 識別策略：Russell 1000/2000 reconstitution（市值門檻附近的股票進出指數，類 RDD）
- Outcome：日內 / 日 / 週 volatility，autocorrelation，return premium

## 對台灣主動 ETF 的 implication

- BDFM 主要研究 **passive index ETF**——但結論的 channel（AP arbitrage 傳遞 flow）對主動 ETF 同樣適用，甚至更強：
  - 台灣主動 ETF 強制每日揭露持股，AP 看到底牌可以更精準預判申贖造成的 basket trade
  - 主動 ETF 規模較小（vs 0050），單日申贖佔成分股成交的比例可能更顯著 → flow → vol 的傳遞係數更大
- 待量化：用 cmoney 持股時序 × FinMind 個股 vol 看主動 ETF top holdings 的 vol 是否 abnormally 高
- 對「強制揭露」這個制度的雙刃面：透明 = 散戶看得到；但也 = 大戶看得到 → 需要 transparency vs front-running 的 trade-off 文獻接著讀（[[raw/papers/cblr_haeberle_2022]]）
