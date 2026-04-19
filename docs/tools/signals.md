# signals — Phase 5 訊號偵測引擎

**建立日期**：2026-04-19（Round 45，managerwatch project Phase 5）
**CLI**：`tools/signals.py`
**Skill**：`.claude/skills/signals/SKILL.md`
**上游**：`raw/store.db`（datastore P4 產出）

---

## 1. 問題脈絡

P4 datastore 把 SITCA 月報 Top 10 + ETF 日揭露堆成一個 SQLite 時序庫，但**「這個月誰加碼了、誰被多數基金共識買了、誰連續幾個月升」每次都要手寫 SQL**。JOY 88 原型 web dashboard 定義 9 種訊號來量化這些問題，但它是 React + FastAPI + yfinance 回測版，我們的研究 repo 要的是 **stdlib-only CLI + JSONL 輸出**，讓 downstream 可以 pipe 到 reports / wiki fusion。

核心論點：**「月報 Top 10 (法規要求揭露)」vs「ETF 日揭露 (完整持股)」中間的差距就是經理人裁量權在法規邊界上的操作空間**。訊號引擎就是把這個空間量化出來。

---

## 2. 設計思路

### 核心決策

- **stdlib only（`sqlite3` + `argparse` + `json`）**：跟 datastore 一致，PEP 723 inline script，不引入 pandas / sqlalchemy
- **每個訊號 = 一個 `detect_signal_N()` 函式**：SQL 心臟 + Python 後處理，方便單測和 swap 閾值
- **JSONL 輸出**：`signal_id / signal_name / as_of / code / name / ...` 欄位統一，pipe 到 jq / wiki ingest 都不用轉
- **閾值全部 CLI 參數化**：不 hardcode（如 signal 4 threshold、signal 5 min-months），讓研究者能掃參數
- **manager mapping 延後**：signal 3 / 6 需要「同一經理人的基金 + ETF」mapping，這個在 P6 wiki/people 融合時才會有，先實作占位

### 9 種訊號對應狀態

| # | 訊號 | SQL 範圍 | 本版狀態 |
|---|---|---|---|
| 1 | 季報→月報 Top 10 晉升 | `fund_quarterly JOIN fund_monthly (next_month)` | ✅ 實作（等 quarterly 資料） |
| 2 | 季報潛伏 ETF 激活 | `fund_quarterly JOIN etf_daily` | ✅ 實作（等 quarterly 資料） |
| 3 | 雙軌建倉（同經理人） | 需 manager ↔ (fund, etf) | ⏸ 延後 P6 |
| 4 | 多基金共識 | `fund_monthly GROUP BY code` | ✅ 實作 + 實測 |
| 5 | 連續加碼（單基金單碼） | `fund_monthly` 時序 | ✅ 實作 + 實測 |
| 6 | 雙軌加碼（同經理人） | 需 manager mapping | ⏸ 延後 P6 |
| 7 | 共識形成（跨月權重合計上升） | 跨月 `fund_monthly` aggregate | ✅ 實作 + 實測 |
| 8 | 高權重減碼 | `fund_monthly` 時序 | ✅ 實作（目前 0 hits 於 AL11） |
| 9 | 核心出場 | 連續 M 月在 Top 10 + 消失 | ✅ 實作 + 實測 |

**7 個實作 / 9 個訊號**。3 & 6 等 P6 解 manager mapping。

### 訊號 5/8 的「連續月」判定

`ym` 欄位是 `'YYYYMM'` 字串，所以連續性判定用 helper `_next_ym()`：
- `202512 → 202601` ✅（年度進位）
- `202504 → 202506` ❌（跳了 202505，不算連續，可能是停揭）

這避免了「資料缺漏月」被當成連續上升。實務上 SITCA 月報每月都發，不連續幾乎一定是 backfill 漏抓，signal 5 自動跳過。

### 訊號 9 的「也不在季報」判定

`also_absent_from_quarterly` 欄位在 quarterly 資料空時總是 `true`（因為 `SELECT ... WHERE yq=?` 回空）。所以本版 signal 9 等於純「月報連續 M 月 + 本月消失」。等 quarterly backfill 好會自動多一層過濾（核心出場 = 月報消失 **且** 季報也消失 = 真正退出 vs 跌到 Top 10 外但季報 ≥1% 仍持有）。

---

## 3. 實作

### CLI 介面

```
signals detect 4 --month 202603 --threshold 3
signals detect 5 --from 202504 --to 202603 --min-months 4
signals detect 7 --from 202601 --to 202603 --n-funds 3 --delta-pct 5
signals detect 8 --from 202504 --to 202603 --high-pct 10 --low-pct 5
signals detect 9 --from 202512 --to 202603 --consecutive 3
signals detect 1 --quarter 202603 --next-month 202604        # 等 quarterly
signals detect 2 --quarter 202603 --etf-date 20260417        # 等 quarterly
signals all    --from 202601 --to 202603                      # 跑 4/5/7/8/9
signals explain 4
signals stats
```

所有 `detect` 吐 JSONL 到 stdout，hit 計數到 stderr（方便 `> hits.jsonl` 不污染）。

### 輸出欄位（統一 schema）

```jsonc
{
  "signal_id": 4,
  "signal_name": "多基金共識",
  "as_of": "202603",            // YYYYMM 或 YYYY-MM-DD
  "code": "2330",               // 股票代碼
  "name": "台積電",
  // signal-specific fields ↓
  "n_funds": 13,
  "total_pct": 135.5,
  "avg_pct": 10.42,
  "funds": ["中國信託...", "兆豐...", ...]
}
```

`as_of` / `code` / `name` 跨訊號一致，適合 downstream 做 deduplication 和 join。

---

## 4. 首次揭露：signals-powered findings（202603 AL11）

### F1：signal 4 — 多基金共識 Top 5

| # | code | name | n_funds | total_pct |
|---|---|---|---|---|
| 1 | 2330 | 台積電 | **13** | 135.5% |
| 2 | 3017 | 奇鋐 | 10 | 41.5% |
| 3 | 2345 | 智邦 | 9 | 36.69% |
| 4 | 2383 | 台光電 | 8 | 41.62% |
| 5 | 2308 | 台達電 | 8 | 38.37% |

**2330 被 13 檔基金月報 Top 10 共同持有，合計權重 135.5%**（因為不同基金各自配 ~10%）。Top 5 清一色 AI 供應鏈（台積電/ASIC/伺服器散熱），與 2026 Q1 AI 主題敘事吻合。

### F2：signal 7 — 共識形成速度（202601→202603）

| code | name | n_funds 從→到 | total_pct 從→到 |
|---|---|---|---|
| 3017 奇鋐 | 1 → 10 | 2.39% → 41.5% | **+39.11pp** |
| 2383 台光電 | 2 → 8 | 6.37% → 41.62% | +35.25pp |
| 2345 智邦 | 1 → 9 | 3.05% → 36.69% | +33.64pp |
| 6223 旺矽 | 0 → 6 | 0 → 29.04% | +29.04pp |
| 3665 貿聯-KY | 0 → 4 | 0 → 17.81% | +17.81pp |

**3 個月從 1 檔到 10 檔基金共同持有 = 共識形成超高速**。這是 signal 7 的設計原意：signal 4 告訴你「現在誰是共識」，signal 7 告訴你「誰正在變成共識」——後者時序更早，訊號更 actionable。

### F3：signal 5 — 連續加碼 ≥4 個月

117 筆 hits（AL11 + 部分兆豐類股基金資料）。觀察：
- **持續加碼超過 4 個月 + 絕對權重 >5%** 的是強信心持倉
- 噪音：兆豐類股基金因 cross-ingested 入 datastore，很多債券/海外部位也會觸發（因為 SITCA IN2629 的 AL11 分類之外還有其他類也在 DB 裡）
- **下次改進**：加 `--fund-class AL11` filter 濾雜訊

### F4：signal 9 — 核心出場（3 月連續消失）

**兆豐臺灣藍籌30ETF基金 2330 avg_pct 35.29% 連 3 月後在 202603 消失** 是最戲劇的 hit。但這很可能是 **ingest 覆蓋率缺口**（該基金不在 AL11、某月漏抓），非真實出場。

**教訓**：signal 9 目前過度敏感於資料缺漏。P5 不靠回測驗真實性（見 plan Option B），但要在 wiki 層標記「需人工確認」。實作上可能需要在 signal 9 加 `--require-ingest-log-ok` 條件。

---

## 5. 穩定度 & 失敗模式

### 穩定度：✅ 中（取決於上游資料覆蓋率）

- SQL / Python 邏輯純粹，無外部依賴
- 單一訊號跑 < 200ms（fund_monthly 3130 rows 級別）
- `signals all` 在 ym_to=202603 完整跑約 1 秒

### 已知失敗模式

| 症狀 | 原因 | 解法 |
|---|---|---|
| signal 5/9 在混合 fund_class 下噪音高 | 目前 ingest 把 AL11 + 其他 class 混入 | 加 `WHERE fund_class='AL11'` filter（未做） |
| signal 1/2 總是 0 hits | `holdings_fund_quarterly` 是空的 | backfill quarterly（plan 有列）|
| signal 9 抓到「假出場」 | ingest 缺該月該基金資料 | cross-check ingest_log.row_count |
| 同一碼重複出現在不同訊號 | 設計如此 — 跨訊號疊加才有故事 | downstream 去重依需求 |

### 待補（未做）

- **`--fund-class` filter**：所有 signal 的 SQL 加 `WHERE fund_class IN (?)`
- **ETF-only 變體 signals**：如「ETF 持股連續 N 日 weight ↑」「ETF Top 10 換手率」，目前純基金視角
- **signal 3/6 manager mapping**：等 P6 `wiki/people/<manager>.md` 建好後做 mapping file
- **回測 hook（JOY 88 Option A）**：接 twquote.py 算訊號命中後 N 個月的報酬，validate 訊號品質
- **信號 dashboard markdown render**：`signals all --render reports/YYYY-MM-DD-signals.md` 直接做 daily summary

---

## 6. 研究意義

9 種訊號的共同假設：**主動型 ETF 不只是「包裝過的基金」，而是同一投信的雙軌產品**。基金月報 Top 10（法規要求）+ ETF 日揭露（完整持股）交叉比對後，能看到：

1. **經理人真正的 conviction**（連續加碼 / 雙軌建倉 = 押寶；高權重減碼 = 避險）
2. **市場共識的形成速度**（signal 7 是這類研究最缺的 timing tool）
3. **法規邊界的灰色地帶**（核心出場但季報仍持有 = 「降溫」非「退出」）

這跟這個 repo 的總研究問題——**台灣主動型 ETF 的制度漏洞**——直接接合。Phase 6 wiki/people 融合會把 signal hits 掛到 `wiki/people/<manager>.md` 做「這個經理人的操作軌跡」頁面，是 P5 → P6 的自然延伸。
