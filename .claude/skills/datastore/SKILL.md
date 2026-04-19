# Datastore Skill

觸發：「datastore」「SQLite」「store.db」「ingest」「backfill」「持股 diff」「consensus」「某股票被哪些 ETF 持有」「跨 ETF 比較」「時序儲存」

**研究筆記**：`docs/tools/datastore.md`（schema 設計、data_date 正規化、已知陷阱）—— 本 SKILL.md 是操作手冊

---

## 核心

SQLite 單檔（`raw/store.db`，gitignored）集中 Phase 1 (managerwatch) + Phase 2 (etfdaily) 的輸出。四張 holdings 表 + 一張 meta + 一張 ingest log。subprocess 呼叫兩個 primary CLI 的 `--json` 做 ingest，冪等可重跑。

與 **managerwatch / etfdaily** 分工：
- 兩者是 **primary-source fetcher**（出 JSON）
- datastore 是 **時序 store + query layer**（吃 JSON 入 SQL）
- 下游（Phase 5 signal engine / Phase 6 wiki fusion）都從 datastore 讀

---

## 環境

```bash
export PATH="/home/node/.local/bin:$PATH"
cd /home/node/tw-active
```

CLI：`tools/datastore.py`（PEP 723 inline、stdlib only、`sqlite3` 內建）

---

## Subcommand 速查

| 指令 | 用途 |
|---|---|
| `./tools/datastore.py init` | 建表（第一次或 reset 後） |
| `./tools/datastore.py ingest sitca-monthly --month 202603 --class AL11` | 月報 Top 10 |
| `./tools/datastore.py ingest sitca-monthly --month 202603 --comid A0009 --class AA1` | 某投信全台股基金 |
| `./tools/datastore.py ingest sitca-quarterly --quarter 202603 --class AL11` | 季報 ≥1% |
| `./tools/datastore.py ingest mops-monthly --month 202602` | MOPS 主動 ETF Top 5（補 SITCA 歷史期洞） |
| `./tools/datastore.py ingest etf-daily --all [--date YYYYMMDD]` | 6 檔 ETF 日持股 |
| `./tools/datastore.py ingest etf-daily --code 00981A --date 20260417` | 單檔 |
| `./tools/datastore.py ingest all --date 20260417` | 便利：6 ETF daily |
| `./tools/datastore.py backfill sitca-monthly --from 202504 --to 202603 --class AL11` | 批次月報（12 個月一次） |
| `./tools/datastore.py backfill mops-monthly --from 202511 --to 202602` | 批次 MOPS Top 5（SITCA 失效月） |
| `./tools/datastore.py backfill etf-daily --from 20260301 --to 20260417 --all` | 批次 ETF daily（自動跳週末） |
| `./tools/datastore.py backfill retry` | 重跑 ingest_log 裡 ok=0 的 target |
| `./tools/datastore.py query holdings --etf 00981A [--date 20260417]` | 某 ETF 持股 |
| `./tools/datastore.py query fund --name 統一台股增長 --ym 202603` | 基金月報 Top 10 |
| `./tools/datastore.py query consensus --code 2330 [--date 20260417]` | 某股票持有者 |
| `./tools/datastore.py query diff --etf 00981A --from 20260410 --to 20260417` | 跨日 diff |
| `./tools/datastore.py stats` | coverage + 最近 10 筆 ingest |
| `./tools/datastore.py whitelist list` | 看 13 檔主動式 ETF 基金白名單 |
| `./tools/datastore.py whitelist coverage` | raw vs active_etf view 覆蓋差距（量化 SITCA 歷史期 filter bug 汙染） |
| `./tools/datastore.py whitelist add --fund-short ... --etf-code ...` | 新掛牌加入白名單 |
| `./tools/datastore.py migrate kind` | holdings_etf_daily.kind 中→英正規化（schema drift 修復，idempotent） |

> **active_etf view**：下游（signals / peoplefuse）預設查 `active_etf_monthly` / `active_etf_quarterly` view（只回 13 檔白名單），繞過 SITCA IN2629/IN2630 歷史期 filter 失效造成的兆豐 fallback 汙染。要看 raw 用 `signals.py --include-all-funds` 或直接 `query fund`。詳見 [[wiki/mechanisms/sitca-history-filter-bug]]。

所有 `query` 支援 `--json`。

---

## Schema 速查

```sql
holdings_fund_monthly    (ym, fund_name, rank)         -- SITCA IN2629 Top 10
holdings_fund_quarterly  (yq, fund_name, code)         -- SITCA IN2630 ≥1%
holdings_etf_daily       (data_date, etf, code, kind)  -- etfdaily
etf_meta_daily           (data_date, etf)              -- aum/units/nav
ingest_log               (id AUTOINCREMENT)            -- 每次 ingest trace
```

`data_date` 統一 `YYYY-MM-DD`（datastore `_normalize_date` 處理各家 issuer 格式差異）。

---

## 常用 Pattern

### Pattern 1：初次 bootstrap

```bash
./tools/datastore.py init
./tools/datastore.py ingest sitca-monthly --month 202603 --class AL11
./tools/datastore.py ingest etf-daily --all --date 20260417
./tools/datastore.py stats
```

### Pattern 2：每日 snapshot（排程入口）

```bash
./tools/datastore.py ingest all   # 自動退最近交易日
```
每天跑一次即可累積時序。建議接到 cron 或開 CronCreate。

### Pattern 3：某股票「共識」

```bash
./tools/datastore.py query consensus --code 2330 --date 20260417
```
輸出：該股被幾檔 ETF 持有（含各自權重）+ 上月月報 Top 10 出現次數（基金清單）。

### Pattern 4：同經理人雙軌查（Phase 5 訊號雛形）

```bash
# 統一 陳釧瑤：基金 Top 10 vs ETF 持股
./tools/datastore.py query fund --name 統一台股增長 --ym 202603 --json > /tmp/fund.json
./tools/datastore.py query holdings --etf 00981A --date 20260417 --json > /tmp/etf.json
# 用 jq / Python diff
```

### Pattern 5：歷史 backfill（bootstrap 時序）

```bash
# Stage 1：SITCA 月報 12 個月
./tools/datastore.py backfill sitca-monthly --from 202504 --to 202603 --class AL11

# Stage 3：4 家可回查投信 × 一段日期（自動 weekday filter）
./tools/datastore.py backfill etf-daily --from 20260301 --to 20260417 --code 00991A
./tools/datastore.py backfill etf-daily --from 20260301 --to 20260417 --code 00980A
./tools/datastore.py backfill etf-daily --from 20260301 --to 20260417 --code 00993A
./tools/datastore.py backfill etf-daily --from 20260301 --to 20260417 --code 00982A

# 統一 00981A / 00988A 不支援歷史 → 只能 daily forward fill（排程每日 ingest all）

# 失敗（國定假日 / 上游暫時不穩）之後 retry
./tools/datastore.py backfill retry
./tools/datastore.py stats   # 確認 ingest_log ok=1 比例
```

### Pattern 6：跨日 rotation 觀察

```bash
./tools/datastore.py ingest etf-daily --code 00981A --date 20260410
./tools/datastore.py ingest etf-daily --code 00981A --date 20260417
./tools/datastore.py query diff --etf 00981A --from 20260410 --to 20260417
```
輸出 Added / Removed / Changed。ETF 週換股速度的量化起點。

---

## 已知陷阱

1. **統一（ezmoney）不支援歷史日期** — XLSX 只回最新，重跑會覆蓋同一筆
2. **安聯（allianz）data_date 比請求日落後一天** — `consensus --date 20260417` 會漏 00993A，這是 issuer as-of 規則
3. **managerwatch quarterly by-comid 濾不乾淨** — 已知 limit（見 managerwatch skill），datastore 照吃，事後在 SQL 層再 filter
4. **週末跑 `ingest etf-daily`** 若沒 `--date`，CLI 自動退最近交易日；若手動給 `--date 20260419`（週日）會失敗
5. **`--all` 不含群益 00992A / 00997A / 安聯 00984A** — CATALOG 只有 JOY 88 6 檔，擴 CATALOG 要改 etfdaily
6. **kind 欄位歷史有中英混用** — 2026-04-19 前的 ingest 對 00980A/00993A 留下 `股票`/`期貨` 標籤；新 ingest 已在 datastore boundary normalize 成 `stock`/`future`，舊資料用 `migrate kind` 修
7. **MOPS vs SITCA 同月衝突** — `holdings_fund_monthly` PK `(ym, fund_name, rank)`，MOPS rank 1-5 會覆蓋 SITCA rank 1-5（沒金額、一致 pct）。SOP：最新期只跑 SITCA（深到 Top 10），SITCA 失效的歷史月才跑 MOPS（見 [[wiki/mechanisms/sitca-history-filter-bug]] + `docs/tools/mopsetf.md`）

---

## 與其他 Skill 分工

| 需求 | 用哪個 |
|---|---|
| 抓 SITCA 月/季報 | **managerwatch skill**（primary source） |
| 抓 MOPS 主動 ETF 歷史月報 Top 5 | **mopsetf skill**（primary source，補 SITCA 歷史期洞） |
| 抓 6 投信 ETF 日揭露 | **etfdaily skill**（primary source） |
| **累積時序 + 跨資料源 query** | **datastore skill**（本 skill） |
| ETF 公開說明書 PDF | **fundclear skill** |
| ETF 盤後量化 / 三大法人 | **twquote skill** |

**決策樹**：
- 問「這檔 ETF 現在有什麼？」→ **etfdaily**（primary，最新）
- 問「這檔 ETF 歷史某日 / 跨日變化？」→ **datastore**（時序 + diff）
- 問「某股票現在被多少 ETF 持有？」→ **datastore query consensus**
- 問「某經理人基金 vs ETF 差距？」→ **datastore**（join fund_monthly + etf_daily）
- 要新增資料源 → 先擴 managerwatch 或 etfdaily，再加 datastore ingest

---

## Phase Roadmap（managerwatch project）

| Phase | 目標 | 狀態 |
|---|---|---|
| P1 | SITCA IN2629 + IN2630 | ✅ 2026-04-19 |
| P2 | 6 投信 ETF 每日 CSV/JSON 日持股揭露 | ✅ 2026-04-19 |
| P3 | ezmoney 提前版 / yuantafunds 預覽 API | ⬜（deferred） |
| **P4** | **SQLite 時序儲存（catalog × date）** | **✅ 2026-04-19** |
| P5 | 9 種訊號偵測引擎 | ⬜ |
| P6 | `wiki/people/<manager>.md` 融合 | ⬜ |
