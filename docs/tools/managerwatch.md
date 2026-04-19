# managerwatch — SITCA 經理人持股交叉比對 pipeline

**破解日期**：2026-04-19（Round 45）
**CLI**：`tools/managerwatch.py`
**Skill**：`.claude/skills/managerwatch/SKILL.md`
**Project memory**：`project_manager_holdings_tool.md`
**參考原型**：`reference_joy88_fund_dashboard.md`（2026-04-18 JOY 88 dashboard 小作文）

---

## 1. 問題脈絡

Round 1-44 的研究都落在 **ETF 本身**：盤後量化（twquote）、公開說明書（fundclear）、發行商官網月報拼湊。

但 Round 44 的 finding「投信買賣超 = 0/28」帶出一個更深的問題：**投信不買自家 ETF，那他們在哪裡表達真實立場？**

答案：**自家主動基金的 Top 10**。

同一家投信，同一個經理人，旗下同時有：
- **主動基金**（例如統一奔騰）：月揭露 Top 10，可重壓、波動可接受、經理人表達完整
- **主動 ETF**（例如 00981A）：日揭露、受透明度約束，為了不被 front-run 只能「妥協版」持股

兩者的差距 = **法規造成的策略分裂**。這是比「ETF vs 被動指數」更深一層的制度漏洞：ETF 的持股只是經理人真實想法的**妥協版**，基金才是 ground truth。

Round 1-44 **完全沒有**這兩條線：
- SITCA `IN2629.aspx` — 基金月報 Top 10
- SITCA `IN2630.aspx` — 基金季報全部 ≥1%

靈感來自 2026-04-18 Threads 上 @winwin17888 轉發 JOY 88 的 dashboard 小作文（9 種經理人訊號、13 基金 + 6 ETF 交叉比對、Manager ↔ ETF mapping）。我們的版本走 CLI + wiki-based research，不做 web dashboard。

---

## 2. 破解思路

SITCA 網站技術老派，是 **ASP.NET WebForms + PostBack**：

1. 第一次 GET `IN2629.aspx` 拿 HTML → 從中 extract `__VIEWSTATE` / `__VIEWSTATEGENERATOR` / `__EVENTVALIDATION`（cookie 同時抓）
2. 第二次 POST 回同一頁，payload 包 hidden tokens + 查詢條件 + `BtnQuery=查詢`
3. HTML 回傳包含持股 table（每檔基金一段）

**關鍵發現**（兩條線卡關之處）：

### 陷阱 A：radio button 要帶

表單 UI 有兩個面板切換（「依類型查詢」/「依公司查詢」），radio 欄位是 `ctl00$ContentPlaceHolder1$rdo1`：
- `rbClass` → 依基金分類查（AA1 國內股票型等）
- `rbComid` → 依投信查（A0009 統一等）

**不帶這個 radio → 後端 default 跑某條路但 dropdown 值不吃，回空白 table**。我第一版 POST 漏了這欄，花一小時反覆確認才發現。

### 陷阱 B：月報 10 欄 vs 季報 9 欄

兩張表結構幾乎一樣但 column 數不同：
- **IN2629**（月報 Top 10）：10 欄 = 基金名稱 / 名次 / 標的種類 / 代號 / 名稱 / 金額 / 擔保機構 / 次順位 / 受益權單位數 / 比例%
- **IN2630**（季報 ≥1%）：9 欄 = 去掉「名次」欄（SITCA 註明「名次乙欄係空白」）

parser 統一用 `has_rank: bool` 決定 `data_col_count = 9 or 8`（不含基金名稱那欄）。

### 陷阱 C：rowspan 結構

每檔基金第一 row 有 `rowspan=N` 的**基金名稱欄**，後續 N-1 rows 少這欄。parser 要 track `remaining_rows` + `current_fund`。

### 陷阱 D：投信代碼不能靠猜

第一版 CATALOG 裡用錯了五家的 `comid`（把 A0012 當復華，實際是華南永昌；A0026 當群益，實際是中國信託…）→ by-comid 查詢 HTTP 404。

**必須先跑 `companies` 從 IN2629 首頁的 `<select>` 抓 option value → 用實際代碼回填**。已內建成 subcommand。

---

## 3. 實作

### CLI 指令（皆支援 `--json`）

| 指令 | 用途 |
|---|---|
| `companies` | SITCA 投信代碼清單（從 IN2629 首頁抓） |
| `classes` | 基金分類代碼清單（AA1 / AL11 / AL12 等） |
| `catalog` | 本專案 19 檔觀測清單（6 ETF + 13 基金 JOY 88 spec） |
| `sitca monthly --month YYYYMM [--by class\|comid] [--class ...] [--comid ...]` | IN2629 月報 Top 10 |
| `sitca quarterly --quarter YYYYMM ...` | IN2630 季報 ≥1% |

### 資料 schema（parser 輸出）

每筆 holding：
```json
{
  "fund": "統一台股增長主動式ETF基金",
  "fund_note": "基金之配息來源可能為收益平準金",
  "rank": 1,            // 季報為 null
  "kind": "01",         // 標的種類代碼
  "code": "2330",
  "name": "台積電",
  "amount": 9553280000, // 市值（TWD）
  "pct": 9.57           // % of NAV
}
```

### 儲存路徑

raw HTML / JSON 建議放 `raw/sitca/` + 檔名帶月份（`monthly_AL11_202603.html`）。目前 CLI 只回 stdout，Phase 4 SQLite ingest 時再補檔案落地。

---

## 4. Finding（首次揭露）

破解當天跑兩個 query 即刻看到的事實：

### F1: 6 檔主動 ETF 月報 Top 10 全員現身（2026-03）

AL11 class 月報 2026-03 共 60 row（6 檔 × 10）。我們握有**全部 6 檔主動 ETF 經理人「顯性層」的完整 snapshot**，不再需要個別去投信官網拼湊。

### F2: 陳釧瑤（00981A）基金 vs ETF 的差距 — 確認 JOY 88 論點

**00981A 統一台股增長主動式ETF**（月報 2026-03 Top 10）：
- 台積電 9.57%（ETF 權重在 ~10%，受透明度約束）
- 台光電 7.02%、台達電 6.05%、奇鋐 6.03%、健策 5.77%

JOY 88 原文指出陳釧瑤在**統一奔騰基金**的台積電權重與此明顯不同（基金更集中、雙軌差距就是制度漏洞）。奔騰月報 Top 10 下一步用 `by comid A0009` 再 diff。

### F3: 「複眼」效應 — 同投信跨基金共識

by-comid 查 A0009（統一投信）一次回 32 檔基金 × Top 10 = 320 rows。**同標的出現在多檔基金 Top 10**即是「多基金共識」訊號（JOY 88 spec #4）。這是 Phase 5 訊號偵測引擎的 raw material。

### F4: 季報比月報深十倍

AL11 class 季報 2025Q4 共 790 row（6 檔 × 平均 130+ 檔持股 ≥1%）。**月報只有 Top 10 權重高位，季報看到完整尾巴**，對研究「候選池」（權重 2.5%+ 但未進 Top 10）尤其關鍵 —— 季報潛伏標的下一季晉升月報 Top 10 = JOY 88 訊號 #2「季報潛伏激活」。

### F5: 季報 by-comid 失效（2026-04-19 Round 46 Stage M 已定位根因）

原以為 IN2630 season `by=comid` 的 filter 邏輯有 bug，Stage M 調查發現**不是 managerwatch 送錯 params，是 SITCA server 對非最新期完全忽略所有 filter**（`rdo1` 三種 mode、`ddlQ_Comid` / `ddlQ_Class` / `rbComCL` 組合下拉都無效），固定回傳 comid dropdown 首項（A0001 兆豐）的基金表。月報 IN2629 行為一致。

詳見 [[wiki/mechanisms/sitca-history-filter-bug]]。

**實證**：

```bash
./tools/managerwatch.py sitca monthly --month 202602 --by class --class AL11 --json > /tmp/a.json
./tools/managerwatch.py sitca monthly --month 202602 --by class --class AA1 --json > /tmp/b.json
# rows 完全相同，全為兆豐 28 檔
```

**意味著**：
- managerwatch 本身無 bug，不需修 code
- 歷史月/季報要補必須改走其他 primary source（投信官網 PDF、MOPS、ezmoney/yuantafunds 官網）
- 若 SITCA 未來修好 server，managerwatch 會自動開始回正確資料

---

## 5. 穩定度 & 失敗模式

### 穩定度評估：✅ 中高

- SITCA 是**法定公會**、由金管會監督 → 公告義務使表格格式保守
- ASPX PostBack 技術老派但**一致**（沒看過 Angular 改版）
- 無 CAPTCHA、無 rate limit（單 session 跑 30+ 次 query 沒被擋）
- 資料 SLA：月報次月第 10 營業日、季報季末次月第 10 營業日（延遲可靠）

### 已知失敗模式

| 症狀 | 原因 | 解法 |
|---|---|---|
| `/usr/bin/env: 'uv' not found` | shebang 用 `uv run --script` | `export PATH="/home/node/.local/bin:$PATH"` |
| 回空 table（只有 header） | 漏 `rdo1` radio | CLI 已封裝；自己 curl 記得帶 `rbClass` / `rbComid` |
| HTTP 404 | comid 不存在 | 先跑 `companies`；代碼會隨投信分合更新 |
| `TypeError: rank None` | IN2630 沒名次欄 | parser `has_rank=False` |
| 月份查無資料 | 該月未公布 | 月報要等次月第 10 營業日 |
| 歷史期任何 filter 不生效（月/季報） | SITCA server bug，非本 CLI 問題 | 無法繞過。改用其他 primary source 補歷史（見 F5 / wiki/mechanisms/sitca-history-filter-bug）|

### 需要持續監控

- SITCA 改版（ASPX 可能整個換 SPA）→ 一旦改版要重新 XHR hook
- 新基金分類代碼（AL13 等）→ 每季 `classes` 跑一次確認
- 投信合併/分拆 → `companies` 跑一次更新 CATALOG

建議**每月跑一次** `sitca monthly --month <上月> --class AL11` 確認 pipeline 仍活。
