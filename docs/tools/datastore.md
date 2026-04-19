# datastore — SQLite 時序儲存（managerwatch + etfdaily 合流）

**建立日期**：2026-04-19（Round 45，managerwatch project Phase 4）
**CLI**：`tools/datastore.py`
**Skill**：`.claude/skills/datastore/SKILL.md`
**DB 檔**：`raw/store.db`（gitignored，可從 primary source 重現）

---

## 1. 問題脈絡

Phase 1 (managerwatch) 抓 SITCA 月/季報、Phase 2 (etfdaily) 抓 6 投信官網日揭露，兩條 pipeline 都是**每次 re-fetch + re-parse**，有三個實務問題：

1. **時序查詢做不到**：同 ETF 跨日的持股變動、同基金跨月的 Top 10 rotation，沒有 canonical store 就只能手工 diff JSON dump
2. **跨資料源 join 困難**：「經理人 X 的基金 月報 vs ETF 日揭露」這種 Phase 5 的核心查詢，需要在同一個 datastore 裡 SQL JOIN
3. **覆蓋率盲點**：手工 fetch 容易漏日、漏 ETF，沒集中 ingest log 就不知道哪天哪檔 miss 了

Phase 3（ezmoney 提前版 / yuantafunds 預覽 API）的價值不如先做 datastore——**先讓現有兩條 pipeline 能累積**，後面再加 data source。

---

## 2. 設計思路

### 核心決策

- **SQLite 單檔**（`raw/store.db`）而非 Postgres/DuckDB：
  - Pod sandbox 環境零部署成本
  - 研究 repo 資料量小（每日 6 ETF × 60 holdings × 365 日 ≈ 130k rows/年，還遠在 SQLite 甜蜜區）
  - 支援 `INSERT OR REPLACE` 做冪等 ingest
- **subprocess 呼叫 primary CLI 的 `--json` 輸出** 而非直接 import：
  - 保持三個 CLI 各自獨立可執行（符合 CLAUDE.md「CLI + skill 架構」規範）
  - `managerwatch.py` / `etfdaily.py` 的 PEP 723 dependency（openpyxl）不污染 datastore
  - 日後若 primary CLI 改版 JSON schema，datastore 是唯一 downstream consumer，修補面小
- **stdlib only**（`sqlite3` 內建）：不增加 dependency

### Schema（4 holdings + 1 meta + 1 log）

| 表 | Primary Key | 來源 | 粒度 |
|---|---|---|---|
| `holdings_fund_monthly` | `(ym, fund_name, rank)` | SITCA IN2629 | 每基金 Top 10 × 每月 |
| `holdings_fund_quarterly` | `(yq, fund_name, code)` | SITCA IN2630 | 每基金 ≥1% × 每季 |
| `holdings_etf_daily` | `(data_date, etf, code, kind)` | etfdaily | 每 ETF 完整持股 × 每日 |
| `etf_meta_daily` | `(data_date, etf)` | etfdaily | AUM/units/NAV × 每日 |
| `ingest_log` | AUTOINCREMENT | 自動寫入 | 每次 ingest trace |

**為什麼 monthly PK 用 `rank` 而 quarterly 用 `code`**：
- 月報是 **Top 10 固定排名**，rank 本身就是天然主鍵，連某基金拆兩行（例如 target_type 不同但 target_name 同）也能容納
- 季報 **≥1% 持股**，無固定排名上限（可能 30+ 檔），用 `code` 當 PK 才能保證同一 holding 不重複

### ingest 流程（冪等）

```
CLI --json → JSON → transform → INSERT OR REPLACE → log
```

每次 ingest 同 (ym, fund, rank) 或 (data_date, etf, code, kind) 重跑會 **overwrite** 舊 row（`INSERT OR REPLACE`），所以可以安全 re-run backfill。

---

## 3. 實作

### CLI 指令

| 指令 | 用途 |
|---|---|
| `init` | 建表（idempotent，safe to re-run） |
| `ingest sitca-monthly --month YYYYMM [--class AL11] [--comid A0009]` | 月報 Top 10 |
| `ingest sitca-quarterly --quarter YYYYMM [--class AL11] [--comid A0009]` | 季報 ≥1% |
| `ingest etf-daily (--code CODE \| --all) [--date YYYYMMDD]` | ETF 日揭露 |
| `ingest all [--date YYYYMMDD]` | 便利：6 ETF daily |
| `backfill sitca-monthly --from YYYYMM --to YYYYMM [--class CLS] [--comid CID]` | 批次月報 |
| `backfill etf-daily --from YYYYMMDD --to YYYYMMDD (--code CODE \| --all)` | 批次 ETF daily（自動跳週末） |
| `backfill retry` | 重跑 `ingest_log` 裡 ok=0 的 target |
| `query holdings --etf CODE [--date YYYYMMDD]` | 某 ETF 持股（預設最新） |
| `query fund --name PATTERN [--ym YYYYMM]` | 基金月報 Top 10（模糊 match） |
| `query consensus --code STOCK [--date YYYYMMDD]` | 某股票被多少 ETF/基金持有 |
| `query diff --etf CODE --from YYYYMMDD --to YYYYMMDD` | 同 ETF 跨日持股差異 |
| `stats` | coverage + 列數 + 日期範圍 + 最近 10 筆 ingest |

所有 query 都吃 `--json`。

### 跨 CLI data_date 正規化

各家 etfdaily 輸出的 `data_date` 格式不一（issuer leak）：

| Issuer | 原始格式 |
|---|---|
| 統一 | `""`（XLSX 內沒 metadata） |
| 野村 | `2026/04/17` |
| 復華 | `20260417` |
| 安聯 | `2026-04-16T00:00:00` |
| 群益 | `2026-04-17` |

datastore `_normalize_date()` 統一吐 `YYYY-MM-DD`。空字串時 fallback 用 CLI 傳入的 `--date` 或最近交易日。

### 已知陷阱

1. **統一不支援歷史日期**（XLSX 只回最新），ingest 時 data_date 會用 fallback 值，若連跑兩天會覆蓋同一 row
2. **安聯 data_date 比請求日晚一天**（issuer 的 as-of 規則），`consensus --date 20260417` 會漏掉 00993A —— 這是資料源事實，不是 bug
3. **季報 quarterly by-comid filter 破功** 是 managerwatch 的 known limit（見 `docs/tools/managerwatch.md`），datastore 照吃，ingest 後可在 SQL 層 `WHERE comid=` filter

---

## 4. 首次揭露：datastore-powered findings

初次載入 202603 月報 AL11（130 rows）+ 20260417 6 檔 ETF（321 rows），`query consensus --code 2330 --date 20260417` 即刻得到：

### F1：2330（台積電）主動 ETF 集中度 vs 基金 Top 10

| ETF / Fund | 權重 |
|---|---|
| 復華 00991A ETF | **16.57%** |
| 野村 00980A ETF | 8.74% |
| 統一 00981A ETF | 8.67% |
| 群益 00982A ETF | 8.63% |
| 統一 00988A ETF | 1.74% |
| 野村臺灣增強50 基金（月報 #1） | **24.27%** |
| 復華台灣未來50 基金（月報 #1） | **18.23%** |
| 第一金台股趨勢 基金（月報 #1） | 16.57% |
| 統一台股增長 基金（月報 #1） | 9.57% |

**同經理人雙軌差距（統一 陳釧瑤）**：基金 9.57% vs ETF 8.67% = **-0.9pp**（ETF 較分散）。
**同經理人雙軌差距（復華 呂宏宇）**：基金 18.23% vs ETF 16.57% = **-1.66pp**（ETF 亦較分散）。

這與 Phase 2 etfdaily finding 的 **「呂宏宇 ETF 16.57% > 基金 9%」呈反向**，因為當時用的是第一金基金（呂宏宇也操盤）而非復華。datastore 集中後才看得出「同經理人跨家操盤」的 confusion —— Phase 6 wiki 融合需要 manager ↔ (fund, etf) 多對多解析。

### F2：ingest throughput

- SITCA 月報 AL11 1 類 = 130 rows，ingest 約 3 秒
- 6 ETF daily snapshot = 321 rows，ingest 約 20 秒（瓶頸在各家 API 非 SQLite write）
- 單次 SQL query（consensus / holdings / fund / stats）< 50ms

---

## 5. 穩定度 & 失敗模式

### 穩定度：✅ 中高

- SQLite 無遠端依賴，重建成本 = 重跑 ingest（可從 primary source 完全重現）
- 冪等 `INSERT OR REPLACE`，backfill 可無限 retry
- ingest_log 保留每筆失敗原因，後續可以 `WHERE ok=0` 抓出要重跑的

### 已知失敗模式

| 症狀 | 原因 | 解法 |
|---|---|---|
| `subprocess fail` stderr 帶 `_last_weekday_ymd` 訊息 | 上游 CLI shebang 找不到 uv | `export PATH="/home/node/.local/bin:$PATH"` |
| `invalid JSON from managerwatch.py` | 上游 CLI crash，stderr 有錯 | 看 ingest_log.error 欄 |
| 00993A 永遠落後一日 | 安聯 API as-of 邏輯 | 用 `query diff --from d1 --to d2` 時避開 00993A 或接受 offset |
| `ingest etf-daily --date 20260420` 抓不到資料 | 週末 / 非交易日 | CLI 預設已 fallback 最近交易日 |

### 待補（未做）

- **排程每日 `ingest all`**：目前靠手動跑，缺 crontab 自動化
- **Phase 5 signal 引擎**：在 datastore 上實作 9 種 JOY 88 原文提到的訊號（rotation 速度 / 集中度變化 / 同經理人 dual-track divergence…）
- **Phase 6 wiki 融合**：`wiki/people/<manager>.md` 頁面從 datastore 拉資料動態渲染
- **quarterly filter fix**：修 managerwatch 的 by-comid 問題，或在 datastore ingest 層做 fallback post-filter
- **國定假日聰明處理**：目前 fhtrust 遇國定假日拋例外被 ingest_log 標 ok=0；可改為回 0-row success 讓 stats 更乾淨

---

## 6. Backfill run（2026-04-19）

首次 batch backfill 實戰紀錄，照 `docs/plans/backfill.md` Stage 1 + Stage 3 執行。

### Before（只有 P4 smoke test snapshot）

```
holdings_fund_monthly      130 rows  [202603 → 202603]
holdings_etf_daily         321 rows  [2026-04-16 → 2026-04-17]
etf_meta_daily               6 rows
```

### After（Stage 1 + Stage 3 完成）

```
holdings_fund_monthly     3130 rows  [202504 → 202603]   24× 成長
holdings_etf_daily        7244 rows  [2026-02-26 → 2026-04-17]   22× 成長
etf_meta_daily             138 rows
ingest_log                 151 筆，其中 4 筆 ok=0（全為國定假日 fhtrust 查無資料）
```

- Stage 1：AL11 12 個月一次 ingest，12/12 成功，~6 秒
- Stage 3：4 家可回查投信（復華/野村/安聯/群益）× 35 個日曆日 weekday filter 後 = 140 calls，134 成功 + 6 空回應（國定假日），~180 秒
- Stage 4（統一兩檔 forward fill）：等每日 cron 排程

### 首個時序 finding：群益 00982A 兩個月換手

\`./tools/datastore.py query diff --etf 00982A --from 20260302 --to 20260417\` 回傳：
- **移除 20 檔**（含群聯 4.88%、文曄 2.57%、京元電子 2.55%、超豐 2.47%）
- **新增 16 檔**（穩懋 5.46%、頎邦 2.10%、啟碁 1.88%、聯電 0.47%、和碩 0.28%）

46 天內 36 次持股變動 = 月均 ~24 檔 rotation。以群益台灣精選強棒原有 60 檔規模換算，**約 40% 月換手率**。對照 JOY 88 原文「葉信良一季換 50%」，群益這檔雖未列 JOY 88 4 象限但屬於同類「高頻狙擊型」。這是 P5 訊號引擎「rotation 速度」訊號的第一個 baseline。

---

## 7. Active ETF 白名單 + view（2026-04-19 Round 46）

Stage A 回填季報時揭露：**SITCA IN2629 的 AL11 分類在 202603 以前只有兆豐投信的 28 檔傳統/被動/組合基金**，其他 12 家發行主動式 ETF 的投信完全沒登記在 AL11。202603 修正後 AL11 月報才回乾淨 13 檔。

詳見 [[wiki/mechanisms/sitca-history-filter-bug]]（原以為是 AL11 分類漂移，Round 46 Stage M 修正為 SITCA 歷史期查詢 filter 失效）。

### 雙軌 schema

- `holdings_fund_monthly` / `holdings_fund_quarterly`：raw 表，忠實保留 SITCA 回傳（含漂移資料）作為制度漏洞研究素材
- `active_etf_whitelist`：13 檔正式主動式 ETF 基金的 fund_short（名稱前綴）+ 可選 etf_code / issuer / note
- `active_etf_monthly` / `active_etf_quarterly`：**下游預設查詢點**。SQL view 以 `LIKE fund_short || '%'`（含空格 / 左括號變體）過濾 raw 表

`datastore.py init` 會自動建 view + seed 13 檔。

### 白名單子命令

```bash
./tools/datastore.py whitelist list                 # 看當前白名單
./tools/datastore.py whitelist coverage             # 對比 raw vs view（量化漂移）
./tools/datastore.py whitelist add --fund-short "XXX主動式ETF基金" \
    --etf-code 00XXX --issuer "XX投信" --note "新掛牌"
./tools/datastore.py whitelist remove --fund-short "..."
./tools/datastore.py whitelist reseed               # 重灌種子（idempotent）
```

### 下游適配

- `signals.py` 預設查 `active_etf_*` view；加 `--include-all-funds` 旗標可繞過看 raw（用來研究 SITCA server fallback bug 本身）
- `peoplefuse.py` 無需改——它透過 `datastore.py query fund --name <short>` 用 LIKE 明確指定基金，本來就不受汙染
- `datastore.py query fund` 目前仍走 raw 表（給使用者自由查詢任何基金），需要乾淨資料時自己改用 view

### 白名單維護時點

1. 新主動式 ETF 掛牌 → 手動 `whitelist add`
2. 若 SITCA 修復歷史期 filter bug → raw 表會自動開始回真實資料，view 會跟著變乾淨（無需改 code）
3. 白名單變更後**不需要** re-ingest raw 表（view 會自動反映）

---

## 8. kind 欄位正規化（2026-04-19 Round 46 Stage K）

Stage D 回填 60-120 天 ETF daily 歷史資料時暴露：**`holdings_etf_daily.kind` 欄位存在中英文標籤混用**，各 issuer parser 吐出來的 `kind` 值不一致：

| ETF | Issuer | 歷史資料 kind 值 |
|---|---|---|
| 00980A | 野村 | `stock` + `股票` + `期貨`（**同一天 API 回的不同 section 各自使用不同標籤**） |
| 00993A | 安聯 | `股票` + `期貨`（純中文） |
| 00981A / 00988A / 00991A / 00982A | 統一 / 群益 / 復華 | `stock`（純英文） |

### 影響

下游任何 `WHERE kind='stock'` 的 query 會系統性漏掉野村 / 安聯大部分歷史持股。例如：
- `signals.py` detect #1（集中度）若將來加 kind filter 會誤判
- 任何 `GROUP BY kind` 的統計會出現重複分類

這是 **schema drift**（同一 logical field 在不同 upstream 以不同 value 表示）的典型案例。

### 修復：normalization at ingest + one-shot migration

在 datastore `_ingest_etf_daily_one` 入 table 前 apply `_normalize_kind()`（中→英 mapping），並提供一次性 migration 修舊資料：

```bash
./tools/datastore.py migrate kind
```

Migration 使用 `UPDATE OR REPLACE`（SQLite 原生語法）避免 PK 衝突——實測 00980A 在同一 `(data_date, etf, code)` 不會同時有多個 kind label，因此 UPDATE 安全、無資料損失。

**mapping 表**：`股票/Stock/現股/equity → stock`、`期貨/futures/Future → future`、`現金/Cash → cash`、`債券/Bond → bond`。未知值原樣 pass through 以便 debug（遇到新 label 會浮現在 `SELECT DISTINCT kind`）。

### 根因選擇：normalize at boundary vs source

兩個修法：(a) 在 `etfdaily.py` 各 issuer parser 處 normalize、(b) 在 `datastore.py` ingest 處 normalize。

選 (b) 的理由：
- **datastore 是 single consumer**，normalization 集中在 boundary 一次
- etfdaily 的 JSON 輸出保持 **issuer 原始語意**（野村就是回中文，這是事實），供其他 downstream（如直接看 JSON 的人）了解 issuer 行為
- 未來若新增其他 downstream 會各自 normalize，保留彈性

代價：etfdaily 的 JSON 仍不一致，若誰不經 datastore 直接消費要自行處理。權衡可接受。

### 執行紀錄

```
before: stock 9607, 股票 6604, 期貨 130
after:  stock 16211, future 130
→ 6734 rows 正規化，0 PK 衝突，migration 全程 < 100ms
```
