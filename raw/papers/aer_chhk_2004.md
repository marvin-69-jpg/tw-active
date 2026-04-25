---
title: Does Fund Size Erode Mutual Fund Performance? The Role of Liquidity and Organization
authors: [Joseph Chen, Harrison Hong, Ming Huang, Jeffrey D. Kubik]
year: 2004
month: 12
venue: American Economic Review
volume: 94
issue: 5
pages: 1276-1302
doi: 10.1257/0002828043052277
url: https://doi.org/10.1257/0002828043052277
pdf: null  # 期刊 paywall，PDF 未抓
accessed: 2026-04-25
fetched_via: tools/papers.py search (crossref) — 只取得 metadata + abstract
citations: 1110
---

# Does Fund Size Erode Mutual Fund Performance? — CHHK (2004 AER)

## 為什麼沒抓到 PDF

- AER 期刊版 paywall
- 沒有對應的 NBER WP（CHHK 直接投 AER）
- SSRN 上有 working paper 版（doi 10.2139/ssrn.372721）但也是 abstract-only 公開

下面 abstract 是 crossref 直拿，takeaway 是讀 PSTZ 2014 對 CHHK 的引用 + 文獻記憶整理出來的（第二手）。

## Abstract（crossref，第一手）

We investigate the effect of scale on performance in the active money
management industry. We first document that fund returns, both before and
after fees and expenses, decline with lagged fund size, even after accounting
for various performance benchmarks. We then explore a number of potential
explanations for this relationship. This association is most pronounced among
funds that have to invest in small and illiquid stocks, suggesting that these
adverse scale effects are related to liquidity. Controlling for its size, a
fund's return does not deteriorate with the size of the family that it
belongs to, indicating that scale need not be bad for performance depending
on how the fund is organized. Finally, using data on whether funds are
solo-managed or team-managed and the composition of fund investments, we
explore the idea that scale erodes fund performance because of the
interaction of liquidity and organizational diseconomies.

## 重點 takeaways

1. **首篇 fund-level diseconomies 實證**——OLS 顯示 fund return 隨 lagged size 下降，**before & after fee** 都下降
2. **小型股、流動性差的基金尤其明顯**——直覺：規模一大，要嘛買到自己會推升的 illiquid 標的、要嘛被迫稀釋
3. **Family size 不重要、fund size 才重要**——規模問題是「單一基金 vs 該基金能找到的 idea」，不是「整家投信」
4. **Organizational diseconomies**：solo-managed 比 team-managed 更受規模影響——大團隊可能有 coordination cost
5. **被 PSTZ 2014 反駁**——PSTZ 指出 CHHK 的 OLS 有 econometric biases（skill omitted variable + Stambaugh 1999 finite-sample bias），用 recursive demeaning 修掉之後 fund-level effect 不顯著。這是 finance 文獻裡少見的、後 25 年完整 rebut 的方法論替換

## 為什麼仍然要記

- CHHK 是被 cite 1,110 次的 anchor paper，主動規模討論一定會被引用
- 即使 PSTZ rebut 了 fund-level、CHHK 對「liquidity 是 channel」、「small-cap fund 受影響更大」的觀察仍然 robust
- 對「小型股主動 ETF」（台灣 00984A 等高息小型股 tilt）有直接 implication
