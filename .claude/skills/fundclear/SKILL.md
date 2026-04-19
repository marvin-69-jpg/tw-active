# FundClear ETF Prospectus Skill

觸發：「抓公開說明書」「prospectus」「MOPS」「fundclear」「ETF 母體」「ETF 列表」「基金資訊觀測站」「集保」「批次抓 ETF」

**研究筆記**：`docs/tools/fundclear.md`（破解過程、finding、穩定度）—— 本 SKILL.md 是操作手冊，筆記是為什麼做

---

## 核心認知

**Round 1-43 盲點**：台灣 ETF 公開說明書**不在 MOPS**，在 **FundClear（集保結算所 基金資訊觀測站）**。2026-04-19 破解。

來源：`https://www.fundclear.com.tw/`

---

## 環境

```bash
export PATH="/home/node/.local/bin:$PATH"   # 要 uv（CLI shebang 用）
cd /home/node/tw-active
```

CLI：`tools/fundclear.py`（PEP 723 inline script，`uv run` 自動裝 pypdf 進快取）

---

## Subcommand 速查

| 指令 | 用途 |
|---|---|
| `./tools/fundclear.py list` | 列所有主動 ETF（代號/名稱/上市日/規模/說明書檔名） |
| `./tools/fundclear.py list --all` | 列全市場 ETF（約 333 檔） |
| `./tools/fundclear.py list --json` | JSON 輸出（給下游程式用） |
| `./tools/fundclear.py info <code>` | 單檔完整 FundClear 欄位 |
| `./tools/fundclear.py fetch <code>` | 下載單檔 PDF → `raw/prospectus/` |
| `./tools/fundclear.py fetch --all` | 下載所有主動 ETF PDF（已存在自動跳過） |
| `./tools/fundclear.py extract <code>` | 抽文到 stdout |
| `./tools/fundclear.py extract <code> --save` | 抽文存成 `.txt` |

**輸出路徑**（預設）：`raw/prospectus/<CODE>_<fileName>.pdf` 和同名 `.txt`

---

## 常用 Pattern

### Pattern 1：母體驗證（Round 40 式 audit 替代方案）

```bash
./tools/fundclear.py list --json > /tmp/active-etfs.json
```

之後用 jq / node 交叉比對 `wiki/etfs/` 現有頁 → 找漏掉的代號。
這比抓 TWSE / TPEx 篩選器頁**省一次 scraping 步驟**（FundClear 含 TWSE+TPEx 全母體）。

### Pattern 2：單檔深挖

```bash
./tools/fundclear.py info 00981A                    # 先看基本欄位
./tools/fundclear.py fetch 00981A                   # 下載 PDF
./tools/fundclear.py extract 00981A --save          # 抽文存 .txt
# 然後用 Read /Grep 讀 raw/prospectus/00981A_*.txt 找階梯費率/AP 名單/風險揭露
```

### Pattern 3：批次補全

```bash
./tools/fundclear.py fetch --all                    # 下載 28 檔全部
# 之後逐檔抽文
for code in $(./tools/fundclear.py list --json | node -e 'JSON.parse(require("fs").readFileSync(0)).forEach(r=>console.log(r.code))'); do
  ./tools/fundclear.py extract "$code" --save
done
```

---

## API 底層（給排錯用）

### 列表 API
```
POST https://www.fundclear.com.tw/api/etf/product/query
Content-Type: application/json
body: {"_pageSize":500,"_pageNum":1,"etfCate":[…7 類…], ...}
```
- 回傳 `{total, list: [{stockNo, name, listingDate, issuer, detail3, ...}]}`
- **`detail3` = 公開說明書 fileName**
- **`etfType` 不吃「主動」字串**（400 error）—— client-side `name.startsWith("主動")` 過濾

### 下載 API
```
POST https://www.fundclear.com.tw/api/etf/product/download-file
Content-Type: application/json
body: {"fileName": "202603_A00009_E45_3.pdf"}
```
- 回傳 raw PDF bytes（Content-Type 騙人寫 application/json）
- **無 session / cookie / referer 檢查 / CAPTCHA**，curl 直打即可

---

## 覆蓋度（2026-04-19）

- FundClear 主動 ETF 母體 = **28 檔**（`00400A / 00401A / 00980A-00998A`）
- 研究 Round 1-43 ingest 的 24 檔**全在母體內**
- **00999A 野村臺灣高息尚未掛牌**，不在 FundClear（pre-listing）
- 全市場 ETF 共 333 檔

---

## 與既有工具分工

- `tools/wiki.py` — wiki lint / gaps / match（**不用改**）
- `tools/fundclear.py` — **新：公開說明書 pipeline**
- `.claude/skills/browser/` — agent-browser（Yahoo / TWSE / TPEx / SITCA 等仍用）

**決策樹**：
- 要公開說明書 PDF / 文字 → 用 fundclear（絕大多數情況最快）
- 要 Yahoo profile / 費率欄位 / 推薦演算法觀察 → 用 browser skill
- 要 SITCA 公告 / 金管會函 → 用 browser skill（需 ASP.NET postback）
- 要 TWSE 成交排名 / e添富統計 → 用 browser skill
- 要 ETF 母體清單 → **優先用 fundclear list**（替代 TWSE / TPEx audit）

---

## 失敗模式預警

1. `/usr/bin/env: 'uv' not found` → 先 `export PATH="/home/node/.local/bin:$PATH"`
2. `etfType` 欄位不能直接傳「主動」，會 400 → 用 client-side 過濾
3. 新上市 ETF 可能要等 1-2 個交易日才會進 FundClear → 跟 TWSE primary source 交叉驗
4. `detail3` 空字串 → 偶爾有極新 ETF 說明書未上架，fetch 會跳過並告警
