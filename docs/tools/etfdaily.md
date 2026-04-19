# etfdaily — 主動 ETF 每日持股揭露 pipeline（6 發行投信）

**破解日期**：2026-04-19（Round 45，managerwatch project Phase 2）
**CLI**：`tools/etfdaily.py`
**Skill**：`.claude/skills/etfdaily/SKILL.md`
**Reference memory**：`reference_ezmoney_daily_holdings.md`（統一一家的完整技術細節）

---

## 1. 問題脈絡

主動 ETF 有個 twquote 破解後浮現的怪事：**投信買賣超 = 0/28**（Round 44 finding）。投信不交易自家 ETF，那他們在哪裡表達觀點？答案分兩邊：

- **基金 Top 10**（SITCA 月揭露，managerwatch Phase 1 已破）— 經理人真實重壓
- **ETF 每日持股**（各投信官網日揭露）— **被透明度約束後的妥協版**

兩邊差距 = 法規造成的策略分裂。要量化這個差距，**日揭露的完整持股**是必要資料。

Round 1-44 全部沒碰這條線。6 家發行投信各自做自家官網，Angular SPA + 六種不同的授權機制（cookie jar / ASP.NET antiforgery / pure POST / URL path / query string），每一家都要獨立 XHR hook 破。

---

## 2. 破解思路

Phase 2 一次並行 XHR hook 4 家（第 5 家用 curl fundCode 對照表完成），總共 ~20 分鐘 wall-clock。手法：

### 共通套路（fundclear Round 44 + ezmoney extension）

1. **agent-browser 打開 ETF 產品頁** — 多半 Angular SPA，頁面按鈕不是 `<a href>`
2. **Hook 全通道**：
   - `XMLHttpRequest.prototype.open` — 傳統 AJAX
   - `fetch` — 現代 JS
   - `window.location.href / assign / replace` — ← **ezmoney 走這條，不走 XHR**
   - `<a href>` click listener
   - `form submit`
   - `Blob / URL.createObjectURL` — client-side xlsx 組檔（群益 SheetJS 走這）
3. **掃 inline script** 找關鍵字：`NPOI / Excel / Download / Export / Asset / Portfolio / Holdings / buyback / FundAssets`
4. **curl 驗證** + 找 anti-bot cookie（`__nxquid` / `X-XSRF-TOKEN` / 其他）

### 6 家各自的 quirk

| 投信 | 技術堆疊 | 關鍵 quirk |
|---|---|---|
| **統一** ezmoney | ASP.NET + Vue | 按鈕走 `window.location.assign()` 不走 XHR。首次 302 設 `__nxquid` anti-bot cookie，`curl -L -c jar -b jar` 即過 |
| **野村** nomurafunds | Angular + ASP.NET Web API | 頁面竟會 JS redirect 到 **fhtrust.com.tw**（復華）當誘餌，API 仍掛自家 `/API/ETFAPI/api/Fund/GetFundAssets`。從 Angular bundle 拆 `main.*.js` 找 `apiUrl` |
| **復華** fhtrust | 純 server-rendered | 產品 tab href 全部錯指到 `capitalfund.com.tw/399`（頁面 bug），真正下載連結在 `#stockhold` 區塊的 `<a href>` 直連 `/api/assetsExcel/<slug>/<YYYYMMDD>`。**連 hook 都不用裝**，產品 slug 不是證券代號（00991A→ETF23）要自己建表 |
| **安聯** etf.allianzgi | Angular + ASP.NET Core | 持股直接 render 在 DOM 沒下載按鈕 → 反而暴露 JSON API。需 AntiForgery 雙重 submit：GET 拿 `X-XSRF-TOKEN` cookie，POST 塞同值 header。FundNo 是 E0001/E0002，不是證券代號 |
| **群益** capitalfund | Angular + client-side SheetJS | 「下載 XLSX」按鈕是 client-side 從 JSON 組檔 → 直接打 `/CFWeb/api/etf/buyback` 最乾淨。`/assets/conf/app.json` 洩 API base |

### 所有 6 家共通事實（與 SITCA 不同）

- 都**無 CAPTCHA、無登入、無 rate limit 偵測**
- 都是 **per-issuer sandbox**：nomura API 只吃 nomura 自家基金，fhtrust 只吃 fhtrust 自家
- 都在**自家官網 domain**（不像 FundClear 那樣有集中託管）
- 資料**即日可查**（T+0 或 T+1）

---

## 3. 實作

### CLI 指令（皆可 `--json`）

| 指令 | 用途 |
|---|---|
| `catalog` | 6 檔 ETF 代號 + issuer + 內部 ID 對照 |
| `holdings <code> [--date YYYYMMDD]` | 抓單檔完整持股（normalize 輸出） |
| `fetch <code> [--date YYYYMMDD]` | 下載原始 XLSX/JSON 到 `raw/etfdaily/` |
| `fetch --all` | 批次 6 檔一次抓 |
| `list capital` | 群益 /etf/list 全產品對照 |

### 依賴

只一個：`openpyxl`（讀統一/復華 XLSX）。其他四家 API 回 JSON，stdlib 搞定。

### Normalize schema

不論 XLSX / JSON，`holdings` 輸出統一成：

```json
{
  "etf": "00981A",
  "issuer": "統一投信",
  "source": "ezmoney.com.tw",
  "format": "xlsx",
  "data_date": "2026-04-17",
  "aum": 9.55e9,
  "units": 1.03e9,
  "nav": 12.13,
  "holdings": [
    {"code": "2330", "name": "台積電", "shares": 6556000, "weight_pct": 8.67, "kind": "stock"}
  ]
}
```

### 儲存路徑

- Normalize 結果 → stdout（--json）給 Phase 4 SQLite ingest
- 原始檔（`fetch`）→ `raw/etfdaily/<code>/<YYYYMMDD>.{xlsx|json}`（已進 `.gitignore`，不入 repo）

### 日期預設

週末跑會 **自動退回上一個週五**（`_last_weekday_ymd`）。不處理國定假日 — 若拿不到資料使用者可 `--date` override。

---

## 4. Finding（首次揭露）

破解當天（2026-04-19 週六）跑 `fetch --all --date 20260417` 後即刻看到：

### F1：同經理人雙軌差距量化（vs SITCA 月報）

| ETF | 台積電 ETF 權重 | 基金 Top 10 台積電權重 | 差距 |
|---|---|---|---|
| **00981A** 陳釧瑤 | **8.67%**（2026-04-17 ETF 日揭露） | **9.57%**（2026-03 SITCA 月報 Top 10） | ETF 低 0.9pp |
| **00991A** 呂宏宇 | **16.57%**（2026-04-17 ETF） | ~9%（JOY 88 原文指出對應基金是 9%） | ETF 高 ~7pp（反向！） |

呂宏宇的 case 反而是 **ETF 比基金重壓台積電**；陳釧瑤 case 是 **ETF 較分散**。這兩個 case 一低一高驗證了「不是單向向下妥協」的假設 —— 法規不是單純讓 ETF 變低權重，而是**讓經理人用不同 bucket 分工**。Phase 5 訊號引擎要測的就是這個 pattern。

### F2：主動 ETF 台積電權重光譜（2026-04-17 snapshot）

| ETF | 台積電權重 |
|---|---|
| 00991A 復華 | **16.57%**（top） |
| 00993A 安聯 | 7.87% |
| 00981A 統一 | 8.67% |
| 00982A 群益 | 8.23% |
| 00980A 野村 | 8.74% |
| 00988A 統一全球 | 0%（只投海外） |

JOY 88 原文說「台積電從 5.6% 到 19.8% 差距」是跨所有主動 ETF；我們直接 primary source 驗證，5 檔國內主動 ETF 範圍 **7.87% ~ 16.57%**（不到 19.8% 是因為當日非 JOY 88 snapshot 當日）。

### F3：00988A 統一全球創新 = 日本 + 美國科技股 basket

最大持股：
- LITE US（LUMENTUM）7.02%
- SNDK US（SANDISK）4.70%
- MU US（MICRON）3.74%
- 6787 JP（MEIKO ELECTRONICS）3.62%

**台股 0 檔**。這與所有其他 5 檔國內主動 ETF 完全不同宇宙，陳意婷的雙軌對照（統一全天候 基金 vs 00988A）是台股 vs 全球的**跨宇宙比較**，與 JOY 88 原文「★★」評分吻合（不像陳釧瑤/呂宏宇那種同宇宙 diff 價值高）。

### F4：群益 00982A「第二名非台積電」的奇景

群益是唯一一檔主動 ETF，**第一重倉（台積電 8.23%）與第二重倉（聖暉 7.64%）差距只 0.59pp**。其他 5 檔主動 ETF 首二重倉差距都 ≥1pp。聖暉是半導體廠務工程，這是群益的 DNA——賭設備商不賭龍頭。可寫入 `wiki/people/` 當群益經理人特色標籤。

### F5：安聯 50 檔滿載 vs 群益 58 檔 vs 其他 ~50 檔

六檔主動 ETF 持股數（2026-04-17）：00981A=53 / 00988A=51 / 00991A=50 / 00980A=57 / 00993A=50 / 00982A=58。**都壓在 50-58 區間**，沒有分散型（100+ 檔）或超集中型（30-）。可能是**主動 ETF 規範的隱含上下限**，值得追查法規原文（fundclear 公開說明書已入手，可交叉）。

### F6：00981A §10 10% 基本上限實測超標 7 天（2026-01 第 3 週密集）

**背景**：`§10` 基金管理辦法規定單一有價證券權重 ≤10%，追蹤指數型經金管會核准得放寬到 20%。之前已知：
- 00985A 野村臺灣增強50（26.28% 峰值）→ 疑似 20% 放寬適用
- 00991A 復華台灣未來50（20.44% 峰值）→ 疑似 20% 放寬適用
- 00981A 統一台股增長 → **未知是否有放寬**

**歷史回填 88 個交易日（2025-11-28 → 2026-04-17）** 後的 2330 權重分佈（資料來源：Round 50 起全面走外部彙整服務 push 至 `raw/cmoney/`）：

| 指標 | 值 |
|---|---|
| range | 8.61% – 10.56% |
| avg | 9.41% |
| 天數 ≥9% | 74/88（84.1%） |
| 天數 ≥10% | 7/88（8.0%） |
| 峰值 | **10.56% @ 2026-01-20** |

**>10% 的 7 天集中於 2026-01-05 ~ 2026-01-21**（2 週內）：01-05, 01-06, 01-08, 01-16, 01-19, 01-20, 01-21。主要是 2026-01 第 2-3 週台積電 rally（財報 / 法說）期間，看起來是**權重被動推過 10%**（漲出來）而非主動加碼。

**意義**：
1. 00981A 在產品分類上是「主動式 ETF」而非追蹤指數型。若無 20% 放寬核准 → 這 7 天**構成 §10 違反**
2. 若有放寬 → 「主動式」標籤與法規適用分類錯配的問題更嚴重（參 [[active-etf-top10-consensus]] 的行銷/法遵分類落差論點）
3. 三檔主動 ETF 的 §10 對 2330 權重分佈光譜：
   - **00981A**：peak 10.56%、大多 9-10%（貼近但偶爾超過 10% 基本上限）
   - **00991A**：peak 20.44%、常態貼近 20%（疑似 20% 放寬適用）
   - **00985A**：peak 26.28%、常態**超過 20%**（即便放寬也疑似違反）

**觀察方式**：
```bash
uv run --no-project python3 -c "
import sqlite3
c = sqlite3.connect('raw/store.db')
for row in c.execute(\"\"\"SELECT data_date, weight_pct
  FROM holdings_etf_daily
  WHERE etf='00981A' AND code='2330' AND weight_pct>=10
  ORDER BY weight_pct DESC\"\"\"):
    print(row)
"
```

### 回填來源：外部 CI（Round 50 起的正式來源）

統一 ezmoney `AssetExcelNPOI` 不支援 `--date`，官方路徑（MOPS / TWSE / 統一官網）不保留歷史。

**Round 50** 起改用第三方資料彙整服務補齊 21 檔主動 ETF 的深度歷史，00981A 與 00988A 亦在內。每日由外部 CI workflow 抓取後 push 到本 repo 的 `raw/cmoney/`，下游 `holdings_etf_daily` 從中 ingest。實作與破解細節於另一 repo 管理。

**歷史足跡**（僅備查）：Round 50 之前曾短暫用 `github.com/4ru1013/united-etf-00981a-portfolio` 第三方 dump 回填 00981A 自 2025-11-28 起的 88 個交易日（見 CLAUDE.md 避雷清單）；Round 50 起該路徑整個廢除。

---

## 5. 穩定度 & 失敗模式

### 穩定度評估：✅ 中高

- 法規強制日揭露 → 投信**不能**亂改 API（漏一天會被罰）
- 6 個 endpoint 都**無 rate limit 偵測**，批次抓 6 檔一次 ~4 秒
- 4/6 家（fhtrust/nomura/allianz/capital）**支援歷史日期**，可以回查回補
- 1/6 家（統一）**不支援歷史**，只能每日排程抓存

### 已知失敗模式

| 症狀 | 原因 | 解法 |
|---|---|---|
| `/usr/bin/env: 'uv' not found` | shebang 用 `uv run --script` | `export PATH="/home/node/.local/bin:$PATH"` |
| 復華 `查無資料` (12 bytes) | 非交易日 | CLI 已 default `_last_weekday_ymd`；手動要自挑 |
| 復華 `HEAD` 404 | fhtrust 只實作 GET | 別用 HEAD 探活 |
| 野村 `StatusCode:5` 空 Entries | date 查無資料 | 改指定有效交易日 |
| 安聯 `403 Missing antiforgery` | 沒塞 X-XSRF-TOKEN header | CLI 已封裝 |
| 群益 `code:0 message:"查無資料"` | 非交易日 / 未揭露 | 檢查 `data.stocks` 長度 |
| 00988A parser 空 holdings（舊版） | XLSX 代號非全數字（`LITE US`） | parser 已改用 code 非空判斷 |

### 需要持續監控

- **統一 `__nxquid` cookie 機制改版** → 最不穩定的一家（nginx-level anti-bot 可能升級）
- **安聯 FundNo 編碼**（E0001/E0002）新 ETF 掛牌時會是 E0003, ... 需要動態抓
- **復華 slug**（ETF23 等）新 ETF 掛牌要跑 `/ETF/etf_list` 更新
- **每月跑一次 `fetch --all`** 驗 6 條線仍活

### 擴充方向（未做）

- 群益 00992A (500) / 00997A (502) 加進 CATALOG（目前只含 JOY 88 6 檔）
- 安聯 00984A (E0001) 加進 CATALOG
- 復華全系列 20+ ETF slug 透過 `/ETF/etf_list` 爬對照
- XLSX metadata（淨資產、單位數、淨值）parser 完善（目前只 parse holdings table）
