# TW Quote Skill

觸發：「三大法人」「外資」「投信買超」「T86」「daily quote」「ETF 成交」「定期定額」「自營商」「買賣超」「openapi」「TWSE API」「TPEx API」「盤後」「schema」「OpenAPI 欄位」

**研究筆記**：`docs/tools/twquote.md`（破解過程、三條線整合邏輯、finding、穩定度）—— 本 SKILL.md 是操作手冊，筆記是為什麼做

---

## 核心

台灣證券市場有兩家官方 OpenAPI + 一支 legacy endpoint，合起來就是「散戶/法人買賣超 + 個股盤後量化資料」的完整 pipeline。Round 1-43 **完全沒用過**，全部靠 scraping Yahoo / MoneyDJ。

**三條線**：

| 來源 | 用途 | 穩定度 |
|---|---|---|
| TWSE OpenAPI `openapi.twse.com.tw/v1/` | 上市個股日成交、定期定額排名、外資 Top 20 | ✅ 官方、無 CAPTCHA |
| TWSE legacy `/fund/T86` | 三大法人個股買賣超（OpenAPI 無此 endpoint） | ✅ 官方、只需 date 參數 |
| TPEx OpenAPI `www.tpex.org.tw/openapi/v1/` | 上櫃個股日成交、三大法人（D 字尾 / 00998A 都在這） | ✅ 官方 |

---

## 環境

```bash
export PATH="/home/node/.local/bin:$PATH"   # uv 在此
cd /home/node/tw-active
```

CLI：`tools/twquote.py`（PEP 723 inline script、stdlib-only）

---

## Subcommand 速查

| 指令 | 用途 |
|---|---|
| `./tools/twquote.py daily <code>` | 個股日成交（收盤/量/高低）— 含 TWSE+TPEx |
| `./tools/twquote.py insti <code> [--date YYYYMMDD]` | 三大法人個股買賣超（外資/投信/自營商明細） |
| `./tools/twquote.py active [--date YYYYMMDD]` | **28 檔主動 ETF 盤後總覽**（日成交 + 三大法人合併） |
| `./tools/twquote.py qfii [<code>]` | 外資持股 Top 20 |
| `./tools/twquote.py etfrank --active-only` | 定期定額交易戶數月報 |
| `./tools/twquote.py paths twse\|tpex` | 列 OpenAPI 全部 endpoint（發掘/debug） |
| `./tools/twquote.py schema <twse\|tpex> <path>` | 顯示某 path 的回傳欄位（name/type/描述，自動解 `$ref`、24h 檔案快取） |

加 `--json` 下游用。

---

## 常用 Pattern

### Pattern 1：Round 44+ 主動 ETF 盤後 snapshot

```bash
./tools/twquote.py active --date 20260417
```
一次看 28 檔主動 ETF 的：收盤 / 成交量 / 外資淨 / 投信淨 / 自營淨 / 三大淨，TWSE + TPEx 合併。

**已知洞察**（2026-04-17 snapshot）：
- 投信買賣超 = 0/28（100%）→ 投信不買自家 ETF
- 自營商（主要避險）是大宗交易方 → 這是 AP 套利的 proxy
- ETFRank 月報 28 檔主動中只有 2 檔入榜前 20

### Pattern 2：回答 Open Q #6（成交量 #1 的意義）

```bash
./tools/twquote.py insti 00981A --date 20260417 --json
```
看 `foreign_net / dealer_hedge_net / trust_net` 比例。自營商(避險) 占比高 = AP 頻繁做 NAV 套利。

### Pattern 3：發掘新 endpoint

```bash
./tools/twquote.py paths twse | grep -E "法人|融資|融券|鉅額"
./tools/twquote.py paths tpex | grep ETF
```
TWSE 143 條、TPEx 225 條，常用的只有 ~10 條，其他可按需開發。

---

## Data schema（給 ingest 用）

### T86（TWSE 三大法人個股）

19 欄位，`twquote insti` 已 normalize 成 7 欄：
- `foreign_net` — 外資買賣超（不含自營商）
- `trust_net` — 投信買賣超
- `dealer_self_net` — 自營商自行買賣
- `dealer_hedge_net` — 自營商避險（AP 套利主要走這）
- `dealer_net` — 自營商合計
- `total_net` — 三大法人合計

股數，非張數（1 張 = 1000 股）。TPEx 的 API 沒有拆「自行/避險」。

### Date 格式陷阱

- TWSE OpenAPI 內部 `Date` 欄：`1150417` 民國格式
- TWSE T86 query 參數：`20260417` 西元格式
- TPEx OpenAPI：**`1150417` 民國格式** — 要用 `_ymd_to_roc()` 轉

CLI 已封裝，都用 `--date YYYYMMDD` 西元輸入，內部自動轉。

---

## 與其他 Skill 分工

| 需求 | 用哪個 |
|---|---|
| 公開說明書 PDF / 文字 | **fundclear skill** |
| ETF 母體清單 | **fundclear skill**（更全） |
| 個股盤後量化（法人/成交/持股） | **twquote skill**（本 skill） |
| 定期定額散戶偏好 | **twquote skill** `etfrank` |
| Yahoo profile / MoneyDJ 費率 / 推薦演算法觀察 | **browser skill** |
| SITCA 公告 / 投信官網 | **browser skill** |

**決策順序**：研究新資料 → 先 `twquote paths` grep 看有沒有 official endpoint → 再看 fundclear → 最後才 browser scraping。

---

## 失敗模式預警

1. **週末/假日 `insti` 查 T86 回 `stat=很抱歉，沒有符合條件的資料!`** → 指定 `--date` 為上個交易日
2. **TPEx `Date` 欄位是民國** → 若你直接 grep 要記得 `1150417` 不是 `20260417`
3. **自行 curl OpenAPI 不用帶 header**，但偶爾要加 `User-Agent`（CLI 已加）
4. **TPEx insti 沒有「自營商自行 vs 避險」細分** → D 字尾 ETF 的 AP 套利強度需用其他方式估
5. **新 ETF 可能要 1-2 交易日才在 OpenAPI 出現** → 跟 FundClear 交叉驗
