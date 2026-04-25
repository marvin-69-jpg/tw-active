# active_share — Active Share 計算工具

## 問題

Cremers-Petajisto (2009 RFS) 的 Active Share 是衡量「主動 vs benchmark 持股偏離度」的標準指標，但台灣主動 ETF 沒人公開算過、且台灣 SITCA/FSC 沒揭露要求。要從外面驗證 closet indexing 假說，必須自己算。

## 破解

不抓 0050 持股做 base（raw 沒存、要再開一條 fetcher），改用 industry-mean 近似。Trade-off：

- **失**：AS 數字不能直接套 Cremers-Petajisto 的 60/80 門檻
- **得**：免拉新資料、純從 `raw/cmoney/` 算、看相對排序仍清楚（誰跟主動共識最像、誰最獨立）

過濾規則：只留 TW 4-digit 股票代號（`^\d{4}[A-Z]?$`），現金 / 保證金 / 應收付 / 外股（XX US/GY/LN）/ 公司債（B-prefix）/ 期權（TXO）全濾。TW 曝險 < 50% 整檔 ETF 排除（00986A/00988A/00990A/00997A 都是外股導向）。

## Finding（2026-04-25 第一次跑）

- **17 檔 TW-focused vs 4 檔外股導向**——0986A/0988A/0990A/0997A TW 曝險都 < 25%，靠主動 ETF 包裝買美股
- **「三胞胎」**：00981A ↔ 00995A AS = 20.5%、加 00994A 形成最緊密 cluster（pairwise AS 全 < 26%）。三檔幾乎同一 portfolio
- **5 檔大型權值股共識圈**：00400A / 00981A / 00991A / 00994A / 00995A 互相 AS 都 < 36%，high-overlap cluster
- **異類**：00984A（高息）vs 其他大多數 ETF AS = 73-79%；00993A 也偏離主流
- **AS vs industry-mean 排序**：00993A 60.4%、00984A 60.0% → 最不從眾；00995A 29.3%、00994A 32.5% → 最像「主動 ETF 平均人」

## 已知限制

- 沒有 0050 base，無法算 Cremers-Petajisto 原始定義的 AS
- 一天 snapshot，沒做時序分析（規模 → AS 的因果還沒建立）
- cmoney CI 跨 ETF push 時間不同步，最新日期可能差 1 天

## 下一步

1. 抓 0050 持股 raw（Yuanta 官網 / TWSE 0050 component），改算原始 AS
2. 時序：每月跑一次、看 AS 隨規模變化
3. 補進 `wiki/mechanisms/closet-indexing.md` 的 Compiled Truth，把「觀察命題」變成「實證結果」
