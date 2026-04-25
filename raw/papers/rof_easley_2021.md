---
title: The Active World of Passive Investing
authors: [David Easley, David Michayluk, Maureen O'Hara, Tālis J. Putniņš]
year: 2021
month: 08
venue: Review of Finance
volume: 25
issue: 5
pages: 1433-1471
doi: 10.1093/rof/rfab021
ssrn_id: 3220842
url: https://academic.oup.com/rof/article-abstract/25/5/1433/6362580
pdf: null  # OUP paywall, open PDF link returns HTML login wall
accessed: 2026-04-25
fetched_via: tools/papers.py search (crossref) — metadata + abstract only
citations: 62
---

# The Active World of Passive Investing — Easley, Michayluk, O'Hara, Putniņš (2021 RoF)

## 為什麼沒抓到 PDF

- OUP open PDF 連結 redirect 到 login wall
- SSRN 3220842 paywall
- 作者個人站沒放 PDF

## 核心論點

ETF 不是同質的「被動」工具——大多數其實是**形式主動**或**功能主動**。作者提出新的 **activeness index** 拆 ETF 的活躍程度，發現 cross-section 越來越被「高度主動的 ETF」主導。

兩種「主動」的 taxonomy：
1. **Active in form**——目的就是產 alpha（包括所謂 active ETF、smart beta、factor ETF、sector ETF）
   - 特徵：positive flow-performance sensitivity（基金績效好 → 申購多）、ETF 中費率最高、portfolio 內部 turnover 高
2. **Active in function**——本身可能是 passive 設計，但被當作主動投資組合的**積木**（sector / country / theme ETF 被機構拿來輪動）
   - 特徵：portfolio 內部 turnover 低（成分股不動），但**二級市場 turnover 高**（被頻繁交易）；持股集中

## 關鍵 takeaways

1. **「被動 ETF」是一個語義誤解**——大部分 ETF 在 form 或 function 上是主動工具
2. **Activeness 是 spectrum**，不是 binary——可以量化
3. **ETF 的活躍化降低**對價格發現的擔憂——傳統批評「ETF 化會殺掉 price discovery」可能過慮，因為大量 ETF 本身就在做 active discovery
4. **fee 競爭壓力**：active ETF 的興起壓縮整個資管產業 fee 結構，連 mutual fund 都受影響

## 方法論細節

- 提出 activeness index（可拆兩維度）
- 樣本：美國 ETF 全宇宙
- 跨類別比較：active in form vs in function vs pure passive

## 對台灣主動 ETF 的 implication

- **正向 angle**：台灣 21 檔主動 ETF 是 active in form 的 textbook 例子。Easley et al 的框架說「這不是壞事，這是 ETF 演化的下一階段」。對「主動 ETF 是不是真的有 alpha」的 framing 可以從「他們是不是 closet」轉到「他們是 active in form / function 的哪一格」
- **可量化 mapping**：
  - 拿 cmoney 持股時序的 month-on-month turnover → portfolio internal turnover 軸
  - 拿 TWSE OpenAPI 日成交量 / AUM → secondary market turnover 軸
  - 兩軸畫散布圖，把 21 檔主動 ETF + 對照組（0050、0056、00919）放上去 → 看誰落在哪一格
- **fee 結構配對**：搭配 fundclear 公開說明書 fee 階梯，看 active in form 的 ETF fee 是否真的較高（理論預測 yes）
- 缺口：作者沒處理「強制揭露持股」的場景。台灣主動 ETF 比美國 transparent ETF 揭露更頻繁（每日），active-in-form 的 cost / fragility 結構不一樣
