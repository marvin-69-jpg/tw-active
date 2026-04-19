---
title: 國泰投信（Cathay Securities Investment Trust）
type: issuer
tags: [issuer, active-etf, cathay, local-sitc, large-local]
slug: cathay
aliases: [國泰投信, 國泰證券投資信託, Cathay SITC, cathaysite]
created: 2026-04-18
updated: 2026-04-18
sources:
  - raw/2026/04/18-cathay-00400a-yahoo.md
---

# 國泰投信（Cathay Securities Investment Trust）

## TL;DR

**國泰證券投資信託股份有限公司**，國泰金控旗下，本研究於 Round 23（2026-04-18）首次納入——**第 10 家進入範圍的投信**。國泰是台灣**大型本土投信**（被動 ETF 00878 永續高股息為其旗艦，AUM 超過 1,800 億）。首檔主動型 ETF [[wiki/etfs/00400a|00400A 主動國泰動能高息]]（2026-03-30 成立、**19 天破百億、107.18 億**）。費率特徵：管理費 **flat 0.9%**（與元大 00990A 齊等，本土 flat 最高）+ **保管費罕見階梯 0.06%/0.04%**（本土台股常態為 flat 0.035%，國泰為異常高水準）。官網 `cathaysite.com.tw` **Access Denied**（本土投信官網抓取困難第 5 家累積）。

## Compiled Truth

### 基本資料

| 欄位 | 內容 |
|---|---|
| 全稱 | 國泰證券投資信託股份有限公司 |
| 英文 | Cathay Securities Investment Trust Co., Ltd. |
| 電話 | 02-2700-8399 |
| 地址 | 台北市大安區敦化南路 2 段 39 號 6 樓 |
| 官網 | https://www.cathaysite.com.tw/ |
| 母集團 | 國泰金控（Cathay Financial Holding）|
| 規模定位 | 台灣大型本土投信（被動 ETF 00878 1800+ 億、為市場旗艦之一）|

### 主動型 ETF 發行清單（2026-04-18）

| 代號 | 名稱 | 成立日 | 類型 | 經理人 | 費率結構 | 規模 |
|---|---|---|---|---|---|---|
| [[wiki/etfs/00400a\|00400A]] | 主動國泰動能高息 | **2026-03-30** | 台股主動（動能+高息雙 factor）| 梁恩溢 | **flat 0.9%** + 保管費階梯 0.06%/0.04% | **107.18 億**（19 天）|

（其他主動 ETF 待追蹤）

### 費率策略（1 檔 ETF 初步歸納）

| ETF | 規模 | 管理費 | 保管費結構 |
|---|---|---|---|
| 00400A 動能高息 | 107 億 | **flat 0.9%** | **≤100 億 0.06% / >100 億 0.04% 階梯** |

**本土 flat 0.9% 雙例**：
- 元大 00990A 全球 AI（flat 0.9% + flat 0.15%）
- **國泰 00400A 台股動能高息（flat 0.9% + 階梯 0.06%/0.04%）**
- **兩大本土龍頭管理費同步 0.9%**——推測「龍頭自我定位溢價」 `[speculation]`

**保管費異常**：
- 本土台股常態：flat 0.035%（群益/台新/復華/第一金/中信同主題）
- **國泰 00400A**：階梯 0.06%/0.04%
- 最低 0.04% 仍比常態高 14%，最高 0.06% 約為 1.7 倍
- 動機未揭露（Access Denied 下本輪無法驗證官網）

### 揭露風格：尚未驗證（官網 Access Denied）

- 官網 cathaysite.com.tw **Access Denied**（本輪）
- Yahoo 資料充足但 benchmark 欄位空白、保管費文字冗長但未解釋
- 官網抓取困難是**本土投信第 5 家**：統一（URL 失效）、群益（URL 重導）、元大（timeout）、第一金（eval null）、中信（allowlist 擋）、**國泰（Access Denied）**
- → 外資投信（安聯、野村）官網相對穩定，**散戶研究本土產品的資訊成本系統性較高**

## 我觀察到的漏洞 / 不對稱

### 1. 官網 Access Denied — 散戶第一層研究即被阻擋 `[confirmed]`

`cathaysite.com.tw` 對一般請求回傳 403/Access Denied（Akamai/Cloudflare 防護猜測），散戶只能：
- 從 Yahoo 看基本資料（但 benchmark 空白、動機未解釋）
- 從 MoneyDJ / 鉅亨 / 經濟日報看新聞
- 找券商下單頁（有 KYC 門檻）

→ 官網是散戶理解產品的第一層入口，Access Denied 實質阻礙研究。

### 2. 保管費高於本土常態但動機不揭露 `[confirmed]`

0.06%/0.04% vs 本土 flat 0.035%，**國泰在本土台股主動 ETF 保管費為最高**（排除統一 00981A 特殊案例）。可能機制：
- 保管銀行選擇（國泰世華 vs 其他）
- 策略複雜度（動能換手高）
- 集團內部定價

→ 散戶買進時無法區分「設計考量」與「國泰金內部利益安排」。

### 3. 主動產品線單薄但爆量快 `[confirmed]`

國泰在主動 ETF 市場**晚入**（2026-03-30，晚首批 10 個月），但首檔 19 天 107 億——**延後入市 + 品牌爆發**策略類似元大（00990A）。被動端依賴 00878 永續高股息（1800 億），主動端可能意圖跟上 00981A 統一、00991A 復華。

## Timeline

- **2026-03-30** — 00400A 成立
- **2026-04-18 Round 23** — 首次建立 issuer 頁，從 00400A 切入。第 10 家投信。官網 Access Denied。

## Related

- [[wiki/etfs/00400a]] — 首檔主動 ETF（台股、動能+高息、flat 0.9%）
- [[wiki/issuers/yuanta]] — 元大投信（本土 flat 0.9% 齊等、延後入市同策略）
- [[wiki/issuers/uni-president]] — 統一投信（規模爆量對比、壽險/銀行集團）
- [[wiki/people/liang-en-yi]] — 梁恩溢（待建）
- [[wiki/mechanisms/active-etf-fee-disclosure]] — 第 10 家加入

## Sources

- [[raw/2026/04/18-cathay-00400a-yahoo]]

## TODO

- 官網 Access Denied 繞過（User-Agent / Referer / allowlist 解除）
- 被動 ETF 完整清單（00878、00881、國泰 20 年等級債⋯）
- 國泰金集團股權結構與國泰世華保管業務關係
- 其他主動 ETF 規劃（是否有 004xxA 系列延伸）
- 國泰 00400A 公開說明書：動能/高息定義、選股池、配息、保管費結構動機
- 梁恩溢經理人背景
