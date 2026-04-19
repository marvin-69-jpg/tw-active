# ManagerWatch Skill

觸發：「經理人」「SITCA」「投信公會」「月報 Top 10」「季報 ≥1%」「基金持股」「IN2629」「IN2630」「雙軌」「同經理人」「多基金共識」「主動基金持股」「managerwatch」

**研究筆記**：`docs/tools/managerwatch.md`（SITCA 破解過程、經理人對應、finding、穩定度）—— 本 SKILL.md 是操作手冊，筆記是為什麼做

---

## 核心

同一投信的**主動基金**（月揭露 Top 10、可重壓）跟**主動 ETF**（日揭露、透明度約束）由同經理人操盤時，兩個產品的真實持股差距 = 法規造成的策略分裂。

這是 tw-active 最關鍵的制度漏洞之一。ETF 的持股只是經理人「妥協版」；基金才是他**真正想重壓**的組合。

**Primary source**：投信投顧公會（SITCA）ASPX form endpoints。

| endpoint | 內容 | 揭露時間 |
|---|---|---|
| `IN2629.aspx`（月報） | 基金 Top 10 持股（股票型/債券型/ETF） | 次月第 10 個營業日 |
| `IN2630.aspx`（季報） | 基金全部 ≥1% 持股（名次欄留白） | 季末次月第 10 個營業日 |

Round 1-43 全部遺漏這兩條線（拿 Yahoo / MoneyDJ / 投信官網 PDF 拼湊）。

---

## 環境

```bash
export PATH="/home/node/.local/bin:$PATH"   # uv 在此
cd /home/node/tw-active
```

CLI：`tools/managerwatch.py`（PEP 723 inline、stdlib-only）

---

## Subcommand 速查

| 指令 | 用途 |
|---|---|
| `./tools/managerwatch.py companies` | SITCA 投信代碼清單（A0005 元大 / A0009 統一 / …） |
| `./tools/managerwatch.py classes` | 基金分類代碼（AA1 國內股票型 / AL11 國內主動 ETF 股票型 / AL12 主動 ETF 債券型） |
| `./tools/managerwatch.py catalog` | 本專案 19 檔觀測清單（6 ETF + 13 基金，JOY 88 spec） |
| `./tools/managerwatch.py sitca monthly --month 202603 --class AL11` | 當月某類型**全部**基金 Top 10（by class） |
| `./tools/managerwatch.py sitca monthly --month 202603 --by comid --comid A0009 --class AA1` | 某投信**所有**基金 Top 10（by comid） |
| `./tools/managerwatch.py sitca quarterly --quarter 202512 --class AL11` | 某類型全部基金季報 ≥1%（by class） |

加 `--json` 下游用。

---

## 常用 Pattern

### Pattern 1：每月抓主動 ETF Top 10 全表

```bash
./tools/managerwatch.py sitca monthly --month 202603 --class AL11 --json > raw/sitca/monthly_AL11_202603.json
```
- AL11 = 國內主動 ETF 股票型（6 檔）
- AL12 = 主動 ETF 債券型
- 月報 Top 10 每檔 10 row，6 檔共 60 row

### Pattern 2：季報 ≥1% 全部持股（抓深度）

```bash
./tools/managerwatch.py sitca quarterly --quarter 202512 --class AL11 --json
```
- 季報**沒有名次欄**（SITCA 註明名次乙欄係空白）→ CLI 的 `rank` 欄為 null
- AL11 季報 2025Q4 共 790 row（ETF 平均 130+ 檔持股）

### Pattern 3：追同一投信跨基金組合（雙軌分析）

```bash
# 統一投信全產品線（ETF + 主動基金）
./tools/managerwatch.py sitca monthly --month 202603 --by comid --comid A0009 --class AA1
# 30+ 檔統一的 AA1 基金 → 過濾 catalog 裡的那幾檔來對比 00981A / 00988A

# 復華
./tools/managerwatch.py sitca monthly --month 202603 --by comid --comid A0022 --class AA1
```

雙軌價值最高的對照組（JOY 88 spec）：
- **陳釧瑤**：統一奔騰 + 00981A（基金台股集中 vs ETF 分散）★★★★★
- **呂宏宇**：復華高成長 + 00991A（台積電基金 9% vs ETF 19.8%）★★★★★
- **陳意婷**：統一全天候 + 00988A（台股 vs 全球，不同宇宙）★★

---

## 投信代碼（verified 2026-04-19）

常用：
- A0005 元大 / A0009 統一 / A0011 摩根 / A0016 群益 / A0022 復華
- A0031 貝萊德 / A0032 野村 / A0036 安聯 / A0037 國泰 / A0047 台新

完整清單跑 `companies` 指令。

---

## 已知陷阱

1. **PostBack radio 必帶**：`rdo1=rbClass` (by class) 或 `rdo1=rbComid` (by comid)。不帶 → 回空白 table。CLI 已封裝。
2. **歷史期 filter 完全失效**（2026-04-19 Round 46 Stage M 確認）：SITCA server 對**非最新期**（目前只有 202603 正常）**忽略所有 `--class` / `--comid` 參數**，固定回 A0001 兆豐 fallback。月報 IN2629 + 季報 IN2630 行為一致。詳見 [[wiki/mechanisms/sitca-history-filter-bug]]。這是 SITCA server bug，managerwatch 本身無法修 —— 要補歷史要走其他 primary source（投信官網 PDF / MOPS / ezmoney / yuantafunds）。
3. **IN2629 10 欄 vs IN2630 9 欄**：月報有名次、季報沒有（空白）。CLI 透過 `has_rank` 判斷，使用者不用管。
4. **公司代碼用錯 → HTTP 404**：例如 A0012 是華南永昌不是復華（復華是 A0022）。永遠先跑 `companies` 確認。
5. **VIEWSTATE 短時間內可重用**：同 session 內連續抓 OK；跨 session 重新 GET 一次。
6. **新基金次月才進**：新基金/ETF 成立後第一次月報要等兩個月。
7. **資料延遲**：IN2629 / IN2630 都是次月第 10 營業日才出。問「最新」時先確認月份已公布。

---

## 與其他 Skill 分工

| 需求 | 用哪個 |
|---|---|
| ETF 公開說明書條文 | **fundclear skill** |
| ETF 盤後量化、三大法人 | **twquote skill** |
| 基金月報 Top 10 / 季報 ≥1% | **managerwatch skill**（本 skill） |
| 投信官網預覽（提前版 ezmoney / yuantafunds） | **browser skill**（Phase 3 會封裝） |
| 各投信 ETF 每日 CSV（日持股揭露） | **browser skill**（Phase 2 會封裝進 managerwatch） |

**決策順序**：問「經理人重壓什麼」→ managerwatch (SITCA)；問「ETF 盤後多少量」→ twquote；問「說明書怎麼寫」→ fundclear。

---

## Phase Roadmap

| Phase | 目標 | 狀態 |
|---|---|---|
| P1 | SITCA IN2629 + IN2630 primary source 破解 | ✅ 2026-04-19 |
| P2 | 6 投信 ETF 每日 CSV 日持股揭露封裝 | ⬜ |
| P3 | ezmoney / yuantafunds API 提前版 | ⬜ |
| P4 | SQLite 時序儲存（catalog × month） | ⬜ |
| P5 | 9 種訊號偵測引擎（多基金共識、雙軌建倉、核心出場…） | ⬜ |
| P6 | `wiki/people/<manager>.md` + `wiki/events/*` fusion | ⬜ |
