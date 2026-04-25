---
title: 規模遞減（Diseconomies of Scale in Active Management）
type: mechanism
tags: [active-management, scale, alpha-decay, industry-crowding]
slug: diseconomies-of-scale
aliases: [decreasing returns to scale, 規模不經濟, scale and skill, alpha decay]
created: 2026-04-25
updated: 2026-04-25
sources:
  - raw/papers/nber_w19891.md
  - raw/papers/nber_w9275.md
  - raw/papers/aer_chhk_2004.md
  - raw/papers/ssrn_3886275.md
---

# 規模遞減（Diseconomies of Scale in Active Management）

## TL;DR

主動型基金規模一變大，平均能否再贏 benchmark 就變難——這是 finance 文獻三十年來反覆驗證、且在 2014 之後**從「fund-level」轉向「industry-level」**的經典機制。台灣主動 ETF 上市才一年、AUM 已破 X 千億，這個機制在這裡會以「擁擠 → 大型權值股集中度上升 → tracking 0050 化」的形態出現。值得長期觀察。

## Compiled Truth

### 機制本身

「規模遞減」在學術上拆兩層：

1. **Fund-level diseconomies**：單一基金變大 → 該基金 alpha 下降。直覺：要部署的錢多了，要嘛被迫買流動性差的小型股（成本上升），要嘛被迫稀釋到更大型股（idea 飽和）。經典出處 Berk & Green (2004 JPE) 的理論模型 + Chen, Hong, Huang, Kubik (2004 AER, 通稱 CHHK) 的實證。
2. **Industry-level diseconomies**：整個主動產業變大 → 任何**單一**基金的 alpha 都下降。直覺：所有主動經理人在搶同一池 mispricing，池子被分得更薄。Pastor, Stambaugh, Taylor (2014, 通稱 PSTZ) 首篇實證。

PSTZ 2014 用 1979–2011 美國 3,126 檔股票型主動共同基金，發現：
- **Industry-level 證據強且 robust**——active fund 產業 AUM 占股市市值比上升 → 各檔基金 benchmark-adjusted alpha 顯著下降，high-turnover / high-volatility / small-cap 基金尤其明顯（擁擠交易直覺一致）。
- **Fund-level 證據其實弱**——OLS 看起來顯著（CHHK 結論），但有兩種 econometric bias（skill 是 omitted variable + Stambaugh 1999 finite-sample bias）；用 recursive demeaning 修掉之後**統計上不顯著**。
- **平均技能在上升、平均 alpha 沒上升**——1979 平均 skill 24bp/月、2011 平均 42bp/月，新進 fund 比老 fund skilled，但被 industry growth 把進步**全部吃完**。原文：「the active management industry today is bigger and more competitive… it takes more skill just to keep up with the rest of the pack」。
- **年輕 fund 贏老 fund**——3 年內基金 vs 10 年以上基金，年化 gross benchmark-adjusted return 差 ~0.9%，這也是 industry-level 機制的副產品（fund 生命週期內產業在膨脹）。

### 為什麼這個機制對「主動 ETF」特別有意義

主動 ETF（vs 主動共同基金）多了三件事讓 diseconomies 更難避開：

1. **Daily basket 揭露**——美國 transparent 主動 ETF 每天揭股、半透明型也得每季公布完整 holdings。經理人想要的「藏單買」空間比共同基金小，**alpha 半衰期更短**，規模一上來會更早撞牆。
2. **In-kind creation/redemption 把流動性風險轉嫁**——表面上 issuer 沒有流動性壓力（AP 自己處理），但實際上 AP 報價會反映持股流動性瑕疵，會以 premium/discount 形態流回終端投資人。
3. **Benchmark hugging 動機**——若主動 ETF 規模膨脹後 alpha 消失，issuer 為了保 AUM 寧願 closet-index（拿 fee 不冒 tracking error 風險）。台灣主動 ETF 公開說明書多數寫「不限定追蹤特定指數」但實務上很容易漂向台灣 50。

### 我觀察到的漏洞 / 不對稱（台灣主動 ETF 場景）

- **權值股集中度上升的可觀察 signal**：用我們的 cross-ETF aggregation（[[wiki/mechanisms/preview-aggregation]] 待建），追蹤每月主動 ETF 對台積電（2330）、聯發科（2454）、鴻海（2317）的合計權重。若 21 檔主動 ETF 的台積電合計權重持續上升 → 規模壓力把 active 推向 0050 結構的證據。[speculation]
- **「skill 上升、alpha 不變」的 framing 拿來看台灣**：台灣主動 ETF 才一年，個別經理人可能真有技能，但若整個主動 ETF 池快速膨脹（2025-Q4 → 2026-Q1 AUM 翻倍），PSTZ 的結論會迅速 apply——**新進經理人技能更高、但平均 benchmark-adjusted return 不會改善**。這提供一個**可證偽**的長期觀察命題。
- **issuer 揭露落差**：公開說明書談「主動管理創造超額報酬」是事前承諾，沒有一家會在規模膨脹時主動揭露「我們的 alpha 已經因為 AUM 變大而下降」。投資人沒有合約上的工具強迫 issuer 公開 alpha decay。
- **配息平準金當「規模遞減」的緩衝**：規模膨脹後若 alpha 不夠付高息，issuer 改用收益平準金 / 資本利得補息，把「規模遞減」隱藏在配息結構裡——這是台灣特有的 indirect channel，PSTZ 美國資料看不到。詳見 [[wiki/mechanisms/income-equalization]]（待建）。

### 文獻地圖（時間順序）

| 年 | 論文 | 角色 | sidecar |
|---|---|---|---|
| 2002 / 2004 | Berk & Green NBER w9275 / JPE | **理論母題**——rational model of fund flows，把 decreasing returns to scale 當外生假設、推出「平均 alpha = 0」均衡 | [[raw/papers/nber_w9275]] |
| 2004 | Chen, Hong, Huang, Kubik (CHHK) AER | **首篇 fund-level 實證**——OLS 看 fund return 隨 size 下降；liquidity / small-cap fund 尤其明顯 | [[raw/papers/aer_chhk_2004]] |
| 2014 | Pastor, Stambaugh, Taylor (PSTZ) NBER w19891 | **方法論翻案**——recursive demeaning 修 bias 後 fund-level 不顯著、industry-level 顯著；提出「skill 上升、alpha 不變」framing | [[raw/papers/nber_w19891]] |
| 2021 / 2022 | PSTZ + Zhu SSRN 3886275 / CFR | PSTZ 2014 robust 升級版，instrument 換更強 | [[raw/papers/ssrn_3886275]] |

## Timeline

- **2026-04-25** — 補抓 Berk-Green 2002 NBER w9275 全文 + CHHK 2004 AER abstract + PSTZ-Zhu 2021 SSRN abstract，文獻地圖鋪完整（[[raw/papers/nber_w9275]] / [[raw/papers/aer_chhk_2004]] / [[raw/papers/ssrn_3886275]]）
- **2026-04-25** — 抓到 PSTZ 2014 NBER w19891 全文，建立此 mechanism page（[[raw/papers/nber_w19891]]）

## Related

- [[wiki/mechanisms/income-equalization]] — 規模遞減在台灣的 indirect channel（待建）
- [[wiki/mechanisms/tracking-error]] — closet-indexing 的可觀測指標（待建）
- [[wiki/mechanisms/preview-aggregation]] — cross-ETF 權值集中度監控（待建）

## Sources

- [[raw/papers/nber_w19891]] — Pastor, Stambaugh, Taylor (2014) "Scale and Skill in Active Management" NBER WP w19891
- [[raw/papers/nber_w9275]] — Berk & Green (2002 NBER WP / 2004 JPE) "Mutual Fund Flows and Performance in Rational Markets"
- [[raw/papers/aer_chhk_2004]] — Chen, Hong, Huang, Kubik (2004) "Does Fund Size Erode Mutual Fund Performance?" *AER* 94(5)（abstract only，AER paywall）
- [[raw/papers/ssrn_3886275]] — Pastor, Stambaugh, Taylor & Zhu (2021 SSRN / 2022 CFR) "Diseconomies of Scale in Active Management: Robust Evidence"（abstract only，SSRN paywall）
