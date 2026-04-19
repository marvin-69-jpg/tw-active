# ETF Daily Skill

觸發：「每日持股」「PCF」「日揭露」「主動 ETF 持股」「ezmoney」「fhtrust」「nomurafunds」「allianzgi」「capitalfund」「主動 ETF 日資料」「單日持股」「etfdaily」

**研究筆記**：`docs/tools/etfdaily.md`（6 家投信破解過程、normalize schema、finding、穩定度）—— 本 SKILL.md 是操作手冊

---

## 核心

主動 ETF 受法規強制**每日揭露完整持股**（相對基金只需月報 Top 10）。6 發行投信各自在官網揭露，6 種技術堆疊（XLSX with cookie / JSON with date / XLSX pure GET / JSON with antiforgery / JSON pure POST），Round 45 一次全破。

與 **managerwatch** 互補：managerwatch 抓 SITCA 月/季報（基金 ground truth），etfdaily 抓投信官網（ETF 日揭露）。同經理人跨兩個產品的差距 = 法規造成的策略分裂。

---

## 環境

```bash
export PATH="/home/node/.local/bin:$PATH"   # uv
cd /home/node/tw-active
```

CLI：`tools/etfdaily.py`（PEP 723 inline、只依賴 `openpyxl`）

---

## Subcommand 速查

| 指令 | 用途 |
|---|---|
| `./tools/etfdaily.py catalog` | 6 檔主動 ETF + issuer + 內部 ID 對照 |
| `./tools/etfdaily.py holdings <code> [--date YYYYMMDD]` | 抓單檔完整持股（normalize 輸出） |
| `./tools/etfdaily.py fetch <code> [--date YYYYMMDD]` | 下載原始 XLSX/JSON 到 `raw/etfdaily/<code>/<date>.*` |
| `./tools/etfdaily.py fetch --all` | 批次下載 6 檔 |
| `./tools/etfdaily.py list capital` | 群益全產品 fundId 對照 |

加 `--json` 下游用（catalog / holdings）。

---

## 5 家 endpoint 矩陣（一頁備忘）

| ETFs | issuer | 內部 ID | method | 歷史日期 | auth |
|---|---|---|---|---|---|
| 00981A / 00988A | `uni` (ezmoney.com.tw) | 49YTW / 61YTW | GET XLSX | ❌ | cookie jar（302 anti-bot） |
| 00991A | `fhtrust` (fhtrust.com.tw) | ETF23 | GET XLSX | ✅ | 無 |
| 00980A / 00985A | `nomura` (nomurafunds.com.tw) | 00980A / 00985A | POST JSON | ✅ | 無 |
| 00993A / 00984A | `allianz` (etf.allianzgi.com.tw) | E0002 / E0001 | POST JSON | ✅ | ASP.NET antiforgery（雙重 submit） |
| 00982A / 00992A / 00997A | `capital` (capitalfund.com.tw) | 399 / 500 / 502 | POST JSON | ✅ | 無 |

**Round 49 擴充**：野村 00985A、安聯 00984A、群益 00992A/00997A 進 CATALOG，AL11 台股 13 檔白名單 + 海外 sibling 覆蓋從 4 升到 8。

**仍待破解**：國泰 00400A（cathaysite.com.tw）、台新 00987A（tsit.com.tw）、第一金 00994A（firstsite.com.tw）、中信 00995A（ctbcinvestments.com）、兆豐 00996A（megafunds.com.tw）—— 各自官網 fetcher 需個別研究。

復華整條 ETF 線有 20+ slug（用 `/ETF/etf_list` 爬對照表）。

---

## Normalize schema

不論 XLSX 還是 JSON，`holdings` subcommand 都輸出統一格式：

```json
{
  "etf": "00981A",
  "issuer": "統一投信",
  "source": "ezmoney.com.tw",
  "format": "xlsx|json",
  "data_date": "2026-04-17",
  "aum": 9.55e9,         // optional（XLSX 沒 parse metadata）
  "units": 1.03e9,
  "nav": 12.13,
  "holdings": [
    {"code": "2330", "name": "台積電", "shares": 100000, "weight_pct": 9.57, "kind": "stock"},
    ...
  ]
}
```

---

## 常用 Pattern

### Pattern 1：每日 snapshot

```bash
./tools/etfdaily.py fetch --all
# → raw/etfdaily/<code>/<YYYYMMDD>.{xlsx|json}
```
預設用最近交易日（週末自動退到週五）。每日排程一次 = 完整時序起點，對應 Phase 4 SQLite 儲存。

### Pattern 2：歷史持股 diff（同經理人雙軌）

```bash
# 復華 00991A 2026-03-15 持股
./tools/etfdaily.py holdings 00991A --date 20260315 --json > /tmp/0315.json
./tools/etfdaily.py holdings 00991A --date 20260415 --json > /tmp/0415.json
diff /tmp/0315.json /tmp/0415.json
```
支援歷史回查的有：復華 / 野村 / 安聯 / 群益。統一（ezmoney）只回最新。

### Pattern 3：跨 ETF 對照

```bash
for code in 00981A 00988A 00991A 00980A 00993A 00982A; do
  ./tools/etfdaily.py holdings $code --date 20260417 --json
done
```
搭配 Unix tool grep / jq 對比各 ETF Top 持股（台積電、台達電等共識）。

---

## 已知陷阱

1. **統一不支援 `--date`** — XLSX 檔名內嵌 server 最新日，加 `&date=` 參數被忽略。歷史靠每日自抓存檔；深度歷史由外部 CI 每日 push raw JSON 至 `raw/cmoney/`（Round 50 起取代原本的 4ru1013 第三方 dump backfill）。
2. **統一國際股代號非全數字**（00988A: `LITE US` / `6787 JP`）— parser 已容許。
3. **復華 週末用 today 會「查無資料」** — CLI 預設已用 `_last_weekday_ymd`；手動 curl 要自己挑交易日。
4. **復華 HEAD 回 404 但 GET 回 200** — 別用 HEAD 探活，直接 GET。
5. **野村 `SearchDate=""` 或空 body 回 `StatusCode:5`** — CLI 已 default last_weekday。
6. **安聯 antiforgery：cookie `X-XSRF-TOKEN` 必須同時塞 cookie 和 header** — ASP.NET Core 雙重 submit。
7. **群益回 HTTP 200 + `code:0 + message:查無資料`** — 非交易日也回 200，檢查 `data.stocks` 長度。
8. **期貨 / 現金 / 債券 table**：野村 / 安聯都會附期貨欄，normalize 後 `kind` 標明；欄位統一但 weight_pct 可能為負（避險口數）。

---

## 與其他 Skill 分工

| 需求 | 用哪個 |
|---|---|
| ETF 公開說明書全文 | **fundclear skill** |
| ETF 盤後量化 / 法人買賣 | **twquote skill** |
| 基金月報 Top 10 / 季報 ≥1% | **managerwatch skill** |
| ETF 每日持股完整揭露 | **etfdaily skill**（本 skill） |
| 投信官網活動文 / 研究報告 | **browser skill** |

**決策樹**：
- 問「ETF 今天重壓什麼？比例多少？」→ **etfdaily**（精度到股數 + 權重）
- 問「基金經理人上月重壓什麼？（跨基金多檔）」→ **managerwatch**
- 問「ETF 規則書怎麼寫？」→ **fundclear**

---

## Phase Roadmap（managerwatch project）

| Phase | 目標 | 狀態 |
|---|---|---|
| P1 | SITCA IN2629 + IN2630 | ✅ 2026-04-19 |
| **P2** | **6 投信 ETF 每日 CSV/JSON 日持股揭露** | **✅ 2026-04-19** |
| P3 | ezmoney 提前版 / yuantafunds 預覽 API | ⬜ |
| P4 | SQLite 時序儲存（catalog × date） | ⬜ |
| P5 | 9 種訊號偵測引擎 | ⬜ |
| P6 | `wiki/people/<manager>.md` 融合 | ⬜ |
