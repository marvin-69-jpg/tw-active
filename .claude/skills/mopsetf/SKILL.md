# MOPSETF Skill

觸發：「MOPS 主動 ETF」「公開資訊觀測站 ETF」「t78sb39」「歷史月報」「主動 ETF 前五大」「MOPS Top 5」「mopsetf」「補歷史持股」

**研究筆記**：`docs/tools/mopsetf.md`（MOPS 破解過程、跟 SITCA 分工、finding、穩定度）

---

## 核心

SITCA IN2629 / IN2630 對**非最新期**所有 filter 完全失效（見 [[wiki/mechanisms/sitca-history-filter-bug]]）。歷史月報要補必須改走其他 primary source。

MOPS `t78sb39_q3`（**國內成分主動式 ETF → 每月持股前五大個股**）是歷史期唯一**跨投信彙整**、server-side filter 正常的 AJAX endpoint：
- Depth：Top **5**（比 SITCA 月報 Top 10 淺）
- Breadth：只有 AL11 主動 ETF（13 檔），沒有主動基金（managerwatch 對照組會少一邊）
- 歷史可查：驗證 2025Q4 到 202603 全可用
- 無 CAPTCHA、無 session token、POST body 帶 ROC year/month 即回 HTML

**分工**：
- **最新期（當月）** → managerwatch（SITCA）拿 Top 10
- **歷史期** → mopsetf（MOPS）拿 Top 5

---

## 環境

```bash
export PATH="/home/node/.local/bin:$PATH"
cd /home/node/tw-active
```

CLI：`tools/mopsetf.py`（PEP 723 inline、stdlib-only）

---

## Subcommand 速查

| 指令 | 用途 |
|---|---|
| `./tools/mopsetf.py monthly --month 202602` | 該月主動 ETF 全部基金 Top 5（人類可讀） |
| `./tools/mopsetf.py monthly --month 202602 --json` | 同上 JSON（下游 ingest 用） |
| `./tools/mopsetf.py monthly --month 202602 --save-raw` | 連同原始 HTML 存到 `.tmp/mops/` 供解析 debug |
| `./tools/mopsetf.py parse <html-path> --json` | 解析本地 HTML（offline 測試用） |

預留（未實作）：
- `navhistory --code <fund>` — 每日 NAV
- `industry --week YYYYMMDD` — 每週投資產業類股比例
- `quarterly --quarter YYYYMM` — 每季持股明細

---

## 常用 Pattern

### Pattern 1：補歷史月份的主動 ETF Top 5

```bash
for m in 202511 202512 202601 202602; do
  ./tools/mopsetf.py monthly --month "$m" --json > "raw/mops/monthly_$m.json"
done
```

### Pattern 3：同月 SITCA vs MOPS 交叉比對

```bash
# SITCA 只在最新期有用
./tools/managerwatch.py sitca monthly --month 202603 --class AL11 --json > /tmp/sitca.json
./tools/mopsetf.py monthly --month 202603 --json > /tmp/mops.json
# MOPS Top 5 應該是 SITCA Top 10 的前 5（可用來驗兩邊抓到的是同一份資料）
```

---

## 已知陷阱

1. **ROC 民國紀年**：`month` 參數用西元 YYYYMM（如 202602），CLI 自動轉成民國 115 年 02 月塞進 POST body。
2. **fund_name 差異**：MOPS 回傳完整全名（`統一台股增長主動式ETF證券投資信託基金`），whitelist 用短名（`...主動式ETF基金`）。CLI 已做 normalize，但如果**直接存 `fund_name_raw`** 進 DB，`active_etf_monthly` view 會過濾掉。一律用 normalize 過的 `fund_name`。
3. **Top 5 不是 Top 10**：MOPS 這個 endpoint 只揭露前五大，depth 比 SITCA 月報淺。做訊號偵測要注意權重尾巴（>第 5 名的標的）看不到。
4. **有手續費紀錄但沒有 PK conflict 風險**：`holdings_fund_monthly` 的 PK 是 `(ym, fund_name, rank)`，MOPS 跟 SITCA 同月同檔基金會衝突。**SOP：同月優先用 SITCA（Top 10 較深），MOPS 只填 SITCA 失效的歷史月**。
5. **兩步 AJAX 協定**：第一步 `ajax_t78sb39_new` handshake（目前可省略，server 直打第二步也給資料），保留防未來加驗證。
6. **資料延遲**：次月第 10 個營業日才公布，跟 SITCA 同步。

---

## 與其他 Skill 分工

| 需求 | 用哪個 |
|---|---|
| 最新月主動 ETF Top 10 | **managerwatch**（SITCA 最新期 filter 正常） |
| 歷史月主動 ETF 持股 | **mopsetf**（本 skill，Top 5） |
| 主動基金（非 ETF）Top 10 | **managerwatch**（最新期 SITCA） |
| 每日持股（T+0 或 T+1） | **etfdaily**（ezmoney 統一）/ **browser**（其他投信官網） |
| 公開說明書 | **fundclear** |

---

## 資料落地

JSON stdout → pipe 到 `raw/mops/monthly_<ym>.json`（archive）。
