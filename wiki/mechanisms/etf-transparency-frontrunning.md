---
title: 強制每日揭露 vs 主動經理人 IP 保護（Transparency vs Front-Running Trade-Off）
type: mechanism
tags: [active-etf, disclosure, front-running, microstructure, regulatory-design, taiwan-loophole]
slug: etf-transparency-frontrunning
aliases: [transparency trade-off, front-running risk, 揭露漏洞, ANT, 主動 ETF 透明度, 持股每日揭露]
created: 2026-04-25
updated: 2026-04-25
sources:
  - raw/papers/cblr_haeberle_2022.md
  - raw/papers/jof_bendavid_2018.md
  - raw/papers/rof_brown_2020.md
  - raw/papers/rof_easley_2021.md
---

# 強制每日揭露 vs 主動經理人 IP 保護

## TL;DR

台灣主動 ETF **強制每日揭露完整持股**——這是法規路徑依賴（沿用被動 ETF 揭露規則），不是經過 trade-off 衡量的決策。美國 2019 年後特地設計了 **ANTs（actively managed non-transparent ETFs）** 結構（Precidian ActiveShares、NYSE AMS）就是為了堵這個洞：揭露讓散戶看得到、也讓 AP / 對沖基金看得到，主動經理人的 stock-picking IP 在揭露當天就 leak 出去。台灣選的這條路，事實上等於**用法規強制經理人放棄 IP 保護**，但 fee 結構（1.0-1.2%）卻是按「保有 IP」訂的——這是結構性 mismatch。

## Compiled Truth

### 為什麼揭露頻率是個 trade-off

ETF 跟 mutual fund 的核心差異之一是**揭露顆粒度與頻率**：

| | 持股揭露頻率 | 顆粒度 | IP 保護 |
|---|---|---|---|
| 美國 mutual fund | 季 / 月 | top 10 + 其他總和 | 高（季度才看得到） |
| 美國 transparent ETF（包括 active） | 每日 | 全持股 + 權重 | 低 |
| 美國 ANTs（2019 後） | 每日 | proxy basket（非真實 portfolio） | 高 |
| 美國 semi-transparent | 每日 | 部分揭露 + 延遲完整 | 中 |
| **台灣主動 ETF** | **每日** | **全持股 + 權重 + 股數** | **極低** |
| 台灣 mutual fund | 月 | top 10 | 中 |

**揭露 = 對散戶透明 = 好**，傳統 framing 直覺如此。但 Haeberle (2022 CBLR) 與相關文獻指出這個 framing 漏掉一面：

1. **front-running 入口**——AP、HFT、對沖基金看得到當日持股，可預判主動經理人的調倉方向
2. **stock-picking IP 蒸發**——主動經理人收 fee 是賣 stock-picking 能力，但能力每日被強制公開
3. **逆向選擇放大**——當 IP 被即時 leak，理性的好經理人會選擇做 mutual fund（季揭露）而非 active ETF。長期下來 active ETF 池可能 **negative selection**

### 美國的監管演化（給台灣對照）

- **1993-2008**：ETF 都是被動 + 強制每日揭露
- **2008-2019**：第一批 active ETF 出現（強制每日揭露），規模一直長不大——**結構性原因正是 transparency**
- **2019**：SEC ETF Rule 通過 + 同年批准 Precidian ActiveShares 等 ANT 結構
- **2020-2024**：active ETF AUM 從 ~1% 漲到 ~7-8%（Haeberle 預測事後驗證）
- **核心 lesson**：監管者意識到 transparency 是雙刃，主動商品需要替代揭露結構

### 台灣現況

- **法規來源**：金管會證期局《證券投資信託基金管理辦法》與配套函令對 ETF（不分主被動）統一要求每日揭露 PCF（Portfolio Composition File，申贖籃）
- **揭露管道**：投信官網 + 集保 cmoney pocket.tw + ezmoney AssetExcelNPOI + ezmoney GetPCF（已逆推進 raw/cmoney/）
- **顆粒度**：持股代號、名稱、權重 %、股數，全部揭露，**沒有 ANT 等價結構**
- **時點**：T+0 揭露當日 PCF（隔日生效），實質是「明天會被買 / 賣什麼」的明牌

### 我觀察到的漏洞 / 不對稱（台灣主動 ETF 場景）

1. **Fee 結構與揭露結構錯配**——主動 ETF fee 1.0-1.2%（vs 0050 的 0.32%），fee 差約 70-90 bps。理論上這個 fee premium 是付給「stock-picking IP」，但 IP 每日被法規強制 leak。這個結構性 mismatch 在公開討論中沒人提
2. **front-running「測試命題」**——主動 ETF 大量加碼的股票，揭露當天 / 隔天應該出現「同向異常成交量」，且強度高於同等規模的被動 ETF 加碼相同股票
3. **規模越小、leak 越致命**——小規模主動 ETF 持股集中度高、單一加碼動作對成分股佔比大，front-running profit 比例越高 → 規模天花板存在（呼應 [[wiki/mechanisms/diseconomies-of-scale]] 但因果路徑不同：不是 alpha decay，是 IP leak）
4. **揭露時間 micro-timing 是 implementation detail**——目前 cmoney 與投信官網的揭露時間點（盤後 vs 盤前 vs 即時）對 front-running window 大小有直接影響。需要實證確認各家投信揭露 timestamp 分佈
5. **主動 ETF 反而「鼓勵跟單」的市場效果**——揭露頻率高 → 散戶以「跟單買法人」心態追主動 ETF top holdings → 這個 follow-on flow 本身就是 front-running 的助燃劑
6. **配息平準金的揭露 lag**——持股每日揭露，但配息來源拆解（資本利得 vs 收益平準金 vs 本金）只在配息日揭露。揭露**透明度的不對稱**：價格相關資訊高頻、收益品質資訊低頻 [speculation - 法規範圍待補]

### 可量化的 testable hypotheses

用我們手上有的資料可以直接做：

**H1（front-running effect）**：主動 ETF top N holdings 的「揭露日 → 隔日 abnormal volume」顯著大於 0，且強度與 ETF 規模負相關
- 資料：raw/cmoney/<code>/ + FinMind TaiwanStockPrice 日成交量
- 對照：同期被動 ETF（0050、0056、00919）相同股票的成交量

**H2（Brown-Davies-Ringgenberg 2020 在台灣成立）**：主動 ETF 高 flow 後 5-10 日 reversal
- 資料：ezmoney GetPCF DIFF_UNIT × P_UNIT（已存 reference memory）+ FinMind 個股價格
- 預期：1-2% / 月 reversal premium（美國數字直接 transplant）

**H3（規模 → IP-leak cost）**：規模越大的主動 ETF，front-running cost / AUM 比例越低（因為單筆調倉佔成分股比例小）
- 對 H1 結果跨 ETF 規模做迴歸

**H4（活躍化 = front-running 暴露）**：高 portfolio turnover 的主動 ETF（active in form, Easley et al 2021），front-running cost 的 cumulative drag 越大
- 資料：cmoney 月度持股時序算 turnover + 上面 H1 的 abnormal volume

**H5（揭露時點 micro-timing 影響）**：盤後（vs 盤前 vs T+1 早盤）揭露的投信，front-running window 大小不同 → effect size 不同
- 需要先做 timestamp inventory（各家投信揭露時點）

## Timeline

- **2026-04-25** — 抓 Easley et al 2021 RoF（abstract）+ Brown-Davies-Ringgenberg 2020 RoF（abstract）+ Ben-David et al 2018 JoF（NBER w20071 全文）+ Haeberle 2022 CBLR（全文）。開此 mechanism page，把「揭露 vs IP 保護」trade-off 的法律 + 金融文獻地圖鋪好，並列出 5 個可量化 testable hypotheses

## Related

- [[wiki/mechanisms/closet-indexing]] — 另一個面向：揭露讓我們可以驗 closet indexing；但揭露本身也讓主動經理被迫「看起來像 closet」（不敢做太大調倉避免 leak）
- [[wiki/mechanisms/diseconomies-of-scale]] — 規模上限：透過 IP-leak 路徑而非 alpha decay 路徑
- [[wiki/mechanisms/income-equalization]] — 揭露不對稱：價格高頻、收益品質低頻（待建）
- [[wiki/mechanisms/creation-redemption]] — AP 套利機制：front-running 的執行載體（待建）

## Sources

- [[raw/papers/cblr_haeberle_2022]] — Haeberle (2022) "The Emergence of the Actively Managed ETF" *Columbia Business Law Review* 2021(3)，**全文**，核心法律 framing
- [[raw/papers/jof_bendavid_2018]] — Ben-David, Franzoni, Moussawi (2018) "Do ETFs Increase Volatility?" *JoF* 73(6)，NBER w20071 全文，ETF flow → underlying vol 主流 channel
- [[raw/papers/rof_brown_2020]] — Brown, Davies, Ringgenberg (2020) "ETF Arbitrage, Non-Fundamental Demand, and Return Predictability" *RoF* 25(4)，flow predict reversal
- [[raw/papers/rof_easley_2021]] — Easley, Michayluk, O'Hara, Putniņš (2021) "The Active World of Passive Investing" *RoF* 25(5)，active in form / function 的 taxonomy
- 後續未抓：
  - Madhavan (2014) / Madhavan-Sobczyk (2016) ETF microstructure
  - Precidian ActiveShares SEC filings（一手法律文件）
  - 亞洲區（中、港、韓）主動 ETF 揭露規則對比
