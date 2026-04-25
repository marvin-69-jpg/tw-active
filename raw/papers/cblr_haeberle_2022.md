---
title: The Emergence of the Actively Managed ETF
authors: [Kevin S. Haeberle]
year: 2022
month: 01
venue: Columbia Business Law Review
volume: 2021
issue: 3
pages: null
doi: 10.52214/cblr.v2021i3.9110
ssrn_id: 3975739
url: https://journals.library.columbia.edu/index.php/CBLR/article/view/9110
pdf: raw/papers/cblr_haeberle_2022.pdf  # open access via Columbia Library
accessed: 2026-04-25
fetched_via: tools/papers.py search (crossref) + curl Columbia journals
citations: 0
type: legal-review
---

# The Emergence of the Actively Managed ETF — Haeberle (2022 CBLR)

## 來源

- 開放存取（Columbia Business Law Review、Columbia 圖書館 PDF），全文已抓
- 引用 0 次（法律 review 流通圈不同於金融期刊，不是品質訊號）

## 核心論點

從 1993 第一檔 ETF 上市以來，ETF 主要被 passive 占據。Haeberle 主張**主動 ETF 即將成為投資地景的重要一環**，原因是 (a) 市場創新（ANTs—actively managed non-transparent ETFs）+ (b) SEC 2019 規則變更（新增 "ETF Rule" 簡化 ETF 註冊、開放 semi-transparent / non-transparent 結構）。

## 關鍵 takeaways

1. **歷史脈絡**：傳統認為主動 ETF 不可能 scale，因為 ETF 強制每日揭露持股 = AP 跟對沖基金可以**前置交易（front-running）**主動經理人的策略——這是主動 ETF 一直長不大的結構性原因
2. **2019 SEC ETF Rule + 多家 sponsor 的 ANT 結構審批**改變了遊戲：
   - **Precidian ActiveShares**——揭露 proxy basket 而非真實 portfolio
   - **NYSE AMS / Natixis / T. Rowe Price** 等 semi-transparent 結構
   - 這些設計讓主動經理人可以**保護持股秘密**同時享 ETF 結構優勢（稅效率、二級市場流動性）
3. **監管 implication**：
   - SEC 對「投資人能否獲得足夠 transparency」與「主動經理 IP 保護」的 trade-off 重新拉線
   - intermediary（顧問、券商）需要新的盡職調查框架——主動 ETF 跟主動 mutual fund 的揭露結構不同
4. **市場 implication**：作者預測未來幾年主動 ETF 占比顯著上升（事後驗證：2020-2024 美國 active ETF AUM 從 ~1% 漲到 ~7-8%）

## 跟金融文獻的關係

- 金融文獻（BDFM 2018、BDR 2020）研究 ETF arbitrage 的 cost
- Haeberle 從**法律 / 制度設計**角度補另一面：揭露頻率與粒度本身就是制度選擇，不是 god-given
- 對「揭露 = 透明 = 好」的天真 framing 是直接的反駁：揭露讓散戶看得到、也讓對手看得到

## 對台灣主動 ETF 的 implication（這是核心）

**台灣選的是 transparent 路線**——所有主動 ETF 強制每日揭露完整持股（cmoney / 投信官網）。Haeberle 的框架說明這個選擇有**可量化的 cost**：

1. **front-running 入口**：AP / 機構 / 程式單看到當日揭露 → 預判明天主動經理可能的調倉方向 → 在主動經理買進前先買、賣出前先賣
   - 美國 ANT 結構就是為了堵這個洞才設計
   - 台灣選 transparent 路線是**主動讓出 IP 保護**——可能是法規路徑依賴（被動 ETF 揭露規則照搬）而非經過 trade-off 的決策
2. **可量化的 testable**：
   - 拿 cmoney 持股時序 × FinMind 個股價量 → 看主動 ETF 大量加碼的股票，揭露當天 / 隔天的「同向異常成交量」是否顯著
   - 對照組：被動 ETF 同樣加碼相同股票時的成交量反應
   - 若主動 ETF 的「揭露 → 隔日異常量」效應比被動 ETF 強，就有 prima facie 證據
3. **主動 fee 的反向選擇**：主動經理人收的 fee 是「stock-picking IP」的價，但 IP 每日被公開 → fee 在補一個被法規強制 leak 的東西。這是**結構性 mismatch**，issuer / regulator 都沒在公開討論
4. **政策建議方向**（純研究，不是倡議）：可能的設計選項：
   - 揭露頻率降為週 / 月（跟主動 mutual fund 月報對齊）
   - 揭露顆粒度降低（top N + 其他總和，非全持股）
   - ANT-style proxy basket
   - 維持現狀但揭露 fee 須補貼 disclosure cost

## 缺口 / 需要追的後續文獻

- 美國 ANT 結構 vs transparent active ETF 的實證對比（fee、tracking、performance）
- Madhavan 2014 / Madhavan-Sobczyk 2016 ETF microstructure
- 中國 / 香港 / 韓國的主動 ETF 揭露規則對比（亞洲區監管 benchmarking）
