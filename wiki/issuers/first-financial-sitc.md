---
title: 第一金投信（First Financial Securities Investment Trust）
type: issuer
tags: [issuer, active-etf, first-financial, local-sitc, taiwan-50-benchmark]
slug: first-financial-sitc
aliases: [第一金投信, 第一金證券投資信託, First Financial SITC, fsitc]
created: 2026-04-18
updated: 2026-04-18
sources:
  - raw/2026/04/18-fsitc-00994a-yahoo.md
---

# 第一金投信（First Financial Securities Investment Trust）

## TL;DR

**第一金證券投資信託股份有限公司**，第一金控旗下 `[speculation]`，本研究於 Round 20（2026-04-18）首次納入——**第 9 家進入範圍的投信**。首檔主動型 ETF 為 [[wiki/etfs/00994a|00994A 主動第一金台股優]]（2025-12-26 成立、24.28 億）。費率結構特徵：**管理費 flat 0.7%（本土主動 ETF flat 最低）+ 保管費 flat 0.035%**——**本土 flat 費率向下競爭第 4 家**。揭露風格屬中性保守：官網（fsitc.com.tw）本輪 eval 失敗（JS 延遲或動態載入），Yahoo 資料頁基本齊全但無特殊主動策略揭露。**研究價值**：作為本土 flat 費率最低家庭驗證「費率競爭 vs 規模競爭」關係——24 億規模說明**低費率本身無法吸引規模，品牌/通路仍主導**。

## Compiled Truth

### 基本資料

| 欄位 | 內容 |
|---|---|
| 全稱 | 第一金證券投資信託股份有限公司 |
| 英文 | First Financial Securities Investment Trust Corp. |
| 電話 | (02) 2504-1000 |
| 地址 | 台北市 10477 民權東路三段 6 號 7 樓 |
| 官網 | https://www.fsitc.com.tw/ |
| 母集團 | 第一金控 `[speculation]`（「第一金」名稱與第一金融控股同源，需驗證股權結構）|

### 主動型 ETF 發行清單（2026-04-18）

| 代號 | 名稱 | 成立日 | 類型 | 經理人 | 費率結構 | 規模 |
|---|---|---|---|---|---|---|
| [[wiki/etfs/00994a\|00994A]] | 主動第一金台股優 | 2025-12-26 | 台股主動 / Taiwan 50 benchmark | 張正中 | **flat 0.7%** | **24.28 億** |

（其他主動 ETF 待追蹤）

### 費率策略（1 檔 ETF 初步歸納）

| ETF | 規模 | 管理費結構 | 管理費 | 保管費 |
|---|---|---|---|---|
| 00994A 台股優 | 24 億 | **flat** | **0.70%** | 0.035% |

**本土 flat 費率家族光譜**（Round 20 更新）：
- 第一金 0.70% < 台新 0.75% < 群益 00982A 0.80% < 元大 00990A 0.90%
- 野村 00985A 0.45% 為增強指數型 outlier
- **第一金為本土 flat 最低**

### 揭露風格特徵

#### 1. 官網動態載入困難 `[confirmed]`

本輪嘗試 fsitc.com.tw eval 產品連結失敗（homepage 只抓到 title），可能為：
- JS 延遲渲染
- SPA 路由（需 click trigger）
- 反爬蟲攔截

→ 本土投信第 4 家官網抓取困難（統一 ezmoney、群益 product URL、元大 timeout、第一金 eval）。
→ 見 [[wiki/mechanisms/issuer-voluntary-disclosure]] 揭露光譜「技術可及性」維度潛在新增。

#### 2. Yahoo 資料揭露標準

Yahoo 基金資料頁齊全，但**無特殊的主動策略揭露**（對比復華活動頁 4 維框架 + 20+ 個股舉例）——屬**標準揭露**（中性保守）。

## 我觀察到的漏洞 / 不對稱

### 1. 母集團股權結構不揭露 `[speculation]`

「第一金」名稱直接指向第一金控，但官網 homepage 未明確標示「第一金控旗下」或「XXX 集團成員」。**散戶無法從官網第一層資訊判斷股權結構**，對投信獨立性、資源配置的判斷有盲點。

### 2. 低費率 + 低規模的「規模漲不大」陷阱 `[speculation]`

管理費 0.7% × 24 億 = 年收 0.17 億，對比復華同期 2.47 億、元大 2.29 億。主動 ETF 固定成本（研究團隊、行銷、法遵）決定下限，**若規模長期維持 24 億**，第一金投信面臨：
- 停售產品
- 或補費率調整（將 flat 0.7% 改回最高 0.8% 或 0.9%）
- 或併入集團其他產品線

→ 本土 flat 向下競爭的**潛在成本**——費率低但規模跟不上，反而不如階梯或高 flat 策略。

### 3. Taiwan 50 benchmark 與「趨勢優選」命名模糊 `[confirmed]`

00994A 揭露 benchmark 為 Taiwan 50 指數，但名稱「趨勢優選」暗示主動選股。**第一金投信揭露未展開**：
- 選股池是否限制 Taiwan 50？
- 「趨勢」的技術定義？

→ 散戶可能誤讀為增強指數型（類 00985A），但費率 0.7% 遠高於 00985A 0.45%。

## Timeline

- **2025-12-26** — 00994A 成立
- **2026-04-18 Round 20** — 首次建立 issuer 頁，從 00994A 切入。本土 flat 費率家族完成 4 家光譜。

## Related

- [[wiki/etfs/00994a]] — 首檔主動 ETF（台股、Taiwan 50 benchmark、flat 0.7%）
- [[wiki/issuers/nomura|野村]] — 本土 flat 0.45% outlier（增強指數）
- [[wiki/issuers/tsit|台新]] — 本土 flat 0.75%
- [[wiki/issuers/capital-sitc|群益]] — 本土 flat 0.8%（00982A）
- [[wiki/issuers/yuanta|元大]] — 本土 flat 0.9%
- [[wiki/people/chang-cheng-chung]] — 張正中（待建）
- [[wiki/mechanisms/active-etf-fee-disclosure]] — 揭露光譜第 9 家加入

## Sources

- [[raw/2026/04/18-fsitc-00994a-yahoo]]

## TODO

- 母集團股權結構確認（第一金控旗下？）
- 被動型 ETF 完整清單
- fsitc.com.tw 官網下輪重試 eval（JS 延遲或 SPA 路由）
- 00994A 公開說明書核對選股池定義
- 公司年報、AUM 排名
- 第一金投信是否規劃其他主動 ETF
