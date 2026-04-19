# mopsetf — MOPS 主動 ETF 歷史月報 pipeline

**破解日期**：2026-04-19（Round 47）
**CLI**：`tools/mopsetf.py`
**Skill**：`.claude/skills/mopsetf/SKILL.md`
**Reference memory**：`reference_mops_active_etf_top5.md`
**關聯**：[[wiki/mechanisms/sitca-history-filter-bug]]、`docs/tools/managerwatch.md` F5 段

---

## 1. 問題脈絡

Round 46 Stage M 定位：SITCA IN2629 / IN2630 對**非最新期**的 server-side filter 完全失效，所有 `rdo1` / `ddlQ_Class` / `ddlQ_Comid` 組合都被忽略，固定回 A0001 兆豐 dropdown 首項的基金表。這是 server bug，managerwatch 本身無法修。

後果：`holdings_fund_monthly` / `holdings_fund_quarterly` 歷史期全是兆豐髒資料，`active_etf_monthly` view 過濾完 = 0 rows。**00981A 等 13 檔主動 ETF 基金的時序訊號完全斷線**——跨月 rotation、複眼共識、季報潛伏激活這些訊號都要歷史資料。

備選清單：
- 各投信官網 PDF 月報（發行商自揭露，13 檔分散在 8+ 家投信，格式不一）
- FundClear 公開說明書（不是每月持股）
- ezmoney 日揭露（只有統一的、且只當日不支援歷史）
- MOPS（候選但從沒試過，Round 1-46 路斷在 SITCA 身上）

優先序評估：MOPS 若能工作 → **跨投信彙整 + 歷史可查**，一條線解決全部 13 檔；各投信官網要一家家接。先試 MOPS。

---

## 2. 破解思路

MOPS 「主動式 ETF 專區」入口：`/mops/web/t78sb39_new`。頁面下拉可選四種揭露：
- 基金每月持股前五大個股
- 基金每日淨資產價值
- 基金每週投資產業類股比例
- 基金每季持股明細

XHR 截流發現：不是 ASP.NET PostBack（跟 SITCA 不同），是**簡單 AJAX**：
- `POST /mops/web/ajax_t78sb39_new`（handshake，`type=03`）
- `POST /mops/web/ajax_t78sb39_q3`（實際 data，帶 `year` + `month`）

實驗確認：
- **單打第二步也回資料**（handshake 目前非必要，但保留防未來 server 加驗證）
- POST body：`{firstin: "true", run: "", off: "1", step: "1", fund_no: "0", TYPEK: "all", year: "115", month: "02"}`
- `year` 民國紀年（西元 -1911）
- HTTP 200 + 完整 HTML（裡頭是 `<table class='hasBorder'>` per fund）
- 無 CAPTCHA、無 rate limit（連抓 5 個月 OK）
- 沒 session cookie，冷打也能回

**跟 SITCA filter bug 的差異**：SITCA 的 `rdo1` 模式要 server 根據下拉重新查 DB，歷史期這條 code path 壞掉 fallback 到首項。MOPS 這個 endpoint 只吃 `year/month`，路徑比較直，沒有 fallback 邏輯可錯。

### HTML 結構

每檔基金一個區塊：
```html
<table class='noBorder'>
  ... 民國 115 年 02 月 ... 公司代號：A0009&nbsp;... 公司名稱：統一投信 ...
</table>
<table class='hasBorder'>
  <tr class='tblHead'>...</tr>
  <tr><td rowspan=5>基金名稱</td><td>1</td><td>2330</td><td>台積電</td><td>9.14</td></tr>
  <tr><td>2</td><td>...</td></tr>
  ...
</table>
```

- 公司 header 在獨立 `<table class='noBorder'>`，用 `COMPANY_HEADER_RE` 抓民國年月 / comid / 公司名
- 基金 table 是 `<table class='hasBorder'>`，第一 row 有 `rowspan=5` 的基金名稱欄，後 4 rows 只 4 欄
- parser 靠「offset proximity」配對 header ↔ table（header 在 table 前最近者為準）

### fund_name 對齊

MOPS 回完整全名 `統一台股增長主動式ETF證券投資信託基金`，whitelist 用短名 `統一台股增長主動式ETF基金`。
Normalize：`.replace("證券投資信託基金", "基金")`。
這讓 `active_etf_monthly` view（用 exact match / prefix 規則）自動涵蓋 MOPS ingest 的 row，不用改 view。

---

## 3. 實作

### CLI 結構

```
tools/mopsetf.py
  monthly --month YYYYMM [--json] [--save-raw]   ← 已實作
  parse <html-path> [--json]                     ← offline 測試
  navhistory --code <fund>                       ← TODO
  industry --week YYYYMMDD                       ← TODO
  quarterly --quarter YYYYMM                     ← TODO
```

PEP 723 inline（`uv run --script` shebang），stdlib-only（regex 解 HTML，不拉 BeautifulSoup）。

### 資料 schema

每筆 holding（JSON）：
```json
{
  "fund_name": "統一台股增長主動式ETF基金",
  "fund_name_raw": "統一台股增長主動式ETF證券投資信託基金",
  "comid": "A0009",
  "company_name": "統一投信",
  "top5": [
    {"rank": 1, "code": "2330", "name": "台積電", "pct": 9.14},
    ...
  ]
}
```

### datastore 整合

`tools/datastore.py`：
- `MOPSETF = TOOLS_DIR / "mopsetf.py"` 常數
- `_ingest_mops_monthly(conn, month)` 跑 CLI → JSON → 寫 `holdings_fund_monthly`
  - `class_code = "AL11"`（MOPS 只揭露 AL11 主動 ETF 股票型）
  - `kind = "stock"`、`amount = NULL`（MOPS 揭露欄位沒金額，只有 pct）
- `cmd_ingest_mops_monthly(--month)` 與 `cmd_backfill_mops_monthly(--from --to)`
- 新 subparsers：`ingest mops-monthly` / `backfill mops-monthly`

PK `(ym, fund_name, rank)`：同月 MOPS rank 1-5 不會跟 SITCA rank 1-10 衝突（重疊 1-5），SOP 是**同月只跑一邊**—— 最新期用 SITCA（Top 10 較深），SITCA 失效的歷史月用 MOPS。

### Raw 落地

`--save-raw` 存到 `.tmp/mops/t78sb39_q3_<roc_year><month>.html`（例如 `t78sb39_q3_11502.html`）。
`raw/2026/04/mops/` 保留第一次破解當天抓下來的 5 個月 HTML 作歷史證據。

---

## 4. Finding（首次揭露）

### F1: 00981A 五個月持股 rotation（2025-11 → 2026-03）

MOPS backfill 202511–202602 + SITCA 202603：

| 月 | #1 | #2 | #3 | #4 | #5 |
|---|---|---|---|---|---|
| 202511 | 台積電 | 緯穎 | 台光電 | 奇鋐 | 金像電 |
| 202512 | 台積電 | 台達電 | 台光電 | 緯穎 | 群聯 |
| 202601 | 台積電 | 台達電 | 群聯 | 台光電 | 緯穎 |
| 202602 | 台積電 | 台達電 | 台光電 | 奇鋐 | 緯穎 |
| 202603 | 台積電 | 台光電 | 台達電 | 奇鋐 | 健策 |

**Rotation 觀察**：
- 台積電穩 #1（權重 9-10% 上緣）
- 台光電長期核心
- 緯穎 202511-202602 四連月 → 202603 消失（大砍倉）
- 健策 202603 首次進 Top 5（建倉訊號）
- 金像電 202511 單月現身後消失

### F2: 202601 複眼共識（JOY 88 signal #3 首次偵測）

MOPS 202601 AL11 全表跨基金統計：
- **群聯 8299**：Top 5 出現在 **6 檔**主動 ETF（從 0 → 6 集體建倉）
- **台達電 2308**：Top 5 出現在 **7 檔**（從分散 → 集中）

同月全業界 13 檔裡有 6-7 檔同時把同一個標的排進 Top 5 = 典型複眼共識訊號。沒歷史資料這訊號偵測不出來；MOPS backfill 後即刻浮現。

### F3: MOPS Top 5 vs SITCA Top 10 一致性驗證

202603 兩邊對跑：MOPS Top 5 是 SITCA Top 10 的**前五大子集**，rank 與 pct 一致。→ 兩條來源可信、可 merge，SOP「同月優先 SITCA」安全。

---

## 5. 穩定度與失敗模式

### 穩定度評估：✅ 中高

- **MOPS 是 TWSE 子公司運營**（官方資訊揭露平台），公告義務決定格式保守
- AJAX endpoint 比 ASP.NET PostBack 簡單，不需 `__VIEWSTATE`
- 無 CAPTCHA、無 rate limit、單 session 抓 10+ 月沒被擋
- 資料 SLA：次月第 10 營業日（同 SITCA）

### 已知失敗模式

| 症狀 | 原因 | 解法 |
|---|---|---|
| `/usr/bin/env: 'uv' not found` | shebang 用 `uv run --script` | `export PATH="/home/node/.local/bin:$PATH"` |
| HTML 回來但 funds=[] | regex 沒命中（MOPS 改版？） | `--save-raw` 留 HTML 到 `.tmp/mops/`，review 結構後調整 `COMPANY_HEADER_RE` / `FUND_TABLE_RE` |
| fund_name 在 view 被過濾 | 用了 `fund_name_raw` | 一律用 normalize 過的 `fund_name` |
| 民國年換算錯 | `ym_to_roc` 輸入不是 YYYYMM | CLI 已 regex 檢查 |
| 當月還沒公布 | 次月第 10 營業日前 | 等 |
| handshake 變強制 | server 加驗證（未來可能） | CLI 已保留 step 1，照舊跑 |

### 需要持續監控

- MOPS 改版（從 ASPX 年代 UI → 可能某天換 React）→ 要重新 XHR hook
- 新 ETF 成立 → 次月會自動出現在回應，不需改 code
- SITCA server bug 是否修復 → 每月重跑一次 managerwatch 驗證；修好後 MOPS 退為 backup

建議**每月與 SITCA 平行跑一次** `./tools/mopsetf.py monthly --month <上月> --json` 做交叉驗證，同時留資料副本。
