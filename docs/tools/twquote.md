# twquote — TWSE/TPEx 盤後 + 三大法人 + Swagger 自助

**破解日期**：2026-04-19（Round 44）
**CLI**：`tools/twquote.py`
**Skill**：`.claude/skills/twquote/SKILL.md`
**Reference memory**：`reference_tw_openapi.md`

---

## 1. 問題脈絡

Round 1-43 要抓「某檔 ETF 今天外資買了幾張、投信賣了幾張、自營商避險多少」時的處理方式：

- 去 Yahoo 財經 / MoneyDJ 爬前端 table
- 抓到的是**單檔 daily 畫面**，要批量就要迴圈 28 檔各開一個 request
- Yahoo 欄位偶爾改名 / class name 改 / 反爬
- 沒有「自營商**自行**買賣 vs **避險**買賣」的細分 — 這是研究 AP（Authorized Participant）套利強度最關鍵的訊號

三大缺口：
1. **沒有 batch snapshot**：無法一次拿 28 檔主動 ETF 的盤後
2. **沒有自營商拆分**：Yahoo 只有「自營商合計」
3. **沒有穩定定期定額排名**：TWSE 網站有但要 form POST + CAPTCHA 式參數

研究「AP 套利 proxy」「散戶定期定額偏好」「投信是否左手賣給右手」卡在這裡。

---

## 2. 破解思路

Round 44 從三條線入手：

### 線 1：TWSE OpenAPI（意外還活著）

隨手 `curl https://openapi.twse.com.tw/v1/swagger.json` → 回 **143 條 path 的完整 OpenAPI 2.0 文件**。官方持續維護，可 curl 直打無 CAPTCHA。包含：
- `/exchangeReport/STOCK_DAY_ALL` — 上市個股日成交（ETF 含）
- `/fund/MI_QFIIS_sort_20` — 外資持股 Top 20
- `/ETFReport/ETFRank` — 定期定額交易戶數月報

### 線 2：TWSE legacy `/fund/T86`（OpenAPI 沒收錄的寶藏）

OpenAPI 143 條 grep 「法人」竟然**沒有個股三大法人買賣超**。追查發現 TWSE 有一隻 legacy 端點：
```
https://www.twse.com.tw/fund/T86?response=json&date=YYYYMMDD&selectType=ALL
```

回 19 欄位 JSON，**含自營商自行 vs 避險拆分**（第 15 / 17 欄）。這支 endpoint 沒進 OpenAPI，所以 Round 1-43 都不知道。

### 線 3：TPEx OpenAPI（上櫃對應 set）

`https://www.tpex.org.tw/openapi/swagger.json` → **225 條 OpenAPI 3.0 path**（比 TWSE 還多）。含：
- `/tpex_3insti_daily_trading` — 上櫃三大法人個股（D 字尾 + 00998A 全含）
- `/tpex_mainboard_daily_close_quotes` — 上櫃個股日成交

### 關鍵合併

三條線分別能抓的東西不同 → CLI 把「主動 ETF 盤後」做成 `active` 指令，自動合併 TWSE + TPEx 成一個 28 檔 table，並補齊 T86 的自營商拆分。

---

## 3. 實作

### CLI 指令（皆支援 `--json`）

| 指令 | 用途 | 資料來源 |
|---|---|---|
| `daily <code>` | 個股日成交 | TWSE STOCK_DAY_ALL + TPEx mainboard |
| `insti <code> [--date YYYYMMDD]` | 三大法人個股買賣超 | TWSE T86 + TPEx 3insti |
| `active [--date YYYYMMDD]` | **28 檔主動 ETF 盤後總覽** | 全部合併 |
| `qfii [<code>]` | 外資持股 Top 20 | TWSE MI_QFIIS_sort_20 |
| `etfrank --active-only` | 定期定額月報 | TWSE ETFRank |
| `paths twse\|tpex` | 列全部 OpenAPI path | swagger.json |
| `schema <twse\|tpex> <path>` | **欄位定義自助**（含 `$ref` 解析） | swagger.json |

`schema` 是 Round 44 後加的（借鏡 `jerryliutaipei/twse-openapi-processor`）—— 支援 swagger 2.0 inline 與 OpenAPI 3.0 `$ref` 兩種格式，24h 檔案快取 (`.tmp/swagger/`) 不重複打 network。

### T86 資料 schema（stdlib normalize 成 7 欄）

| 欄 | 意義 | 研究價值 |
|---|---|---|
| `foreign_net` | 外資買賣超（不含自營商） | 主動 ETF 外資比重 |
| `trust_net` | 投信買賣超 | **主動 ETF 投信 0/28 → 投信不買自家 ETF** |
| `dealer_self_net` | 自營商自行買賣 | 做市活動 proxy |
| `dealer_hedge_net` | 自營商避險 | **AP 套利強度 proxy** |
| `dealer_net` | 自營商合計 | |
| `total_net` | 三大法人合計 | |

單位是**股**不是張（1 張 = 1000 股）。TPEx insti API **沒有** 自行/避險拆分（這是研究上櫃 D 字尾套利的缺口）。

### 日期格式陷阱（已內部封裝）

| 系統 | 格式 | 範例 |
|---|---|---|
| TWSE OpenAPI 回傳 `Date` | 民國 | `1150417` |
| TWSE T86 query 參數 | 西元 | `20260417` |
| TPEx OpenAPI 回傳 `Date` | 民國 | `1150417` |

CLI 統一 **`--date YYYYMMDD` 西元輸入**，內部 `_ymd_to_roc()` 自動轉。週末/假日自動倒推 `_guess_last_trading_day()`。

---

## 4. Finding（首次揭露）

### 2026-04-17 snapshot 立即揭露

1. **投信買賣超 = 0 / 28 主動 ETF（100%）** — 投信**不買自家 ETF**，這是規則還是慣例？接下 `regulations/` wiki 要補
2. **自營商（避險）主導成交** — 主動 ETF 成交量 #1 的「真正買賣方」主要是自營商避險，回答 Open Q #6：成交量 ≠ 散戶熱度，而是 AP 套利的 NAV 跟蹤活動
3. **ETFRank 前 20 中主動 ETF 只 2 檔**（`00981A` #8、`00982A` #20）— 定期定額散戶的主動 ETF 滲透率遠低於被動 ETF

### 額外 by-product

- 143 + 225 條 OpenAPI path 被完整讀進 wiki/tools 決策樹 → 發掘後續 endpoint 不必從頭 Google
- `schema` 指令讓未來破解新 endpoint 只要 `twquote schema ... <path>` 就能看欄位意義，**無需重抓 swagger、無需進瀏覽器**

---

## 5. 穩定度 & 失敗模式

### 穩定度評估

| 來源 | 穩定度 | 風險 |
|---|---|---|
| TWSE OpenAPI | ✅✅ 高 | 官方持續維護、格式穩定 |
| TWSE T86 (legacy) | ✅ 中-高 | 近 10 年未改 URL，但**是 legacy**、未來可能被收掉或搬家 |
| TPEx OpenAPI | ✅✅ 高 | 官方、225 條 schema 齊全 |

### 已知失敗模式

| 症狀 | 原因 | 解法 |
|---|---|---|
| `insti` 假日回 `stat=很抱歉，沒有符合條件的資料!` | T86 不含非交易日 | CLI 已自動倒推；使用者可 `--date` 指定上個交易日 |
| TPEx Date 欄位是 `1150417` | 民國格式 | 用 `_ymd_to_roc()` 轉；不要直接 grep `20260417` |
| 新 ETF 1-2 交易日後才出現 | OpenAPI 有 upload lag | 跟 FundClear 交叉驗 |
| TPEx insti 沒自行/避險拆分 | TPEx API 本身未提供 | D 字尾 AP 套利強度要另尋 proxy |
| T86 若下架 | legacy 可能退役 | 屆時需找 replacement；建議每月跑一次確認還活著 |

### 需要持續監控

- `twquote paths twse | wc -l` 應保持 143 上下，異常劇變 = 官方大改格式
- `twquote paths tpex | wc -l` 應保持 225 上下
- T86 回應若突變為 403 / 404 → **主要風險來源**，要立即找 alternative
