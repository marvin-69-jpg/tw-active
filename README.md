# tw-active

**台灣主動型 ETF 體制與機制研究**

本 repo 整理台灣主動型 ETF（active ETF）的機制設計、揭露規則與制度落差。內容由 AI agent（`openab-bot` / Threads `@opus_666999`）依公開資料持續更新。

主題範圍：費用結構、配息來源、申贖機制、追蹤誤差、經理人裁量權、規模效應、資訊揭露規範。**不包含**選股建議、技術分析或短線判斷。

## 研究介面

- **Pages 視覺化**：[marvin-69-jpg.github.io/tw-active](https://marvin-69-jpg.github.io/tw-active/) — 21 檔主動 ETF 的共識圈
- **Threads**：[@opus_666999](https://threads.net/@opus_666999)
- **Obsidian graph**：以 Obsidian 開啟本 repo 可走 graph view

## 資料層

研究所需資料以 **primary source** 為主：

| 來源 | 用途 |
|---|---|
| **FundClear** `/api/etf/product/*` | ETF 公開說明書 PDF 全文 |
| **TWSE / TPEx OpenAPI** | 盤後報價、三大法人、掛牌母體 |
| **投信官網**（統一、野村、復華、安聯、群益） | 主動 ETF 當日持股 ground truth（10 檔） |
| **SITCA** IN2629 / IN2630 | 基金月報 Top 10、季報 ≥1% 持股 |
| **MOPS** `t78sb39_q3` | 主動 ETF 歷史月報 Top 5（補 SITCA 歷史期 bug） |
| 第三方資料彙整服務 | 主動 ETF 全歷史持股（21 檔，回溯至 2025-05）——實作細節於另一 repo 管理 |

每條 primary source 對應一個 CLI 工具 + 操作手冊 + 研究筆記三件套：

```
tools/<name>.py              CLI（PEP 723 inline）
.claude/skills/<name>/       操作手冊（觸發詞 + subcommand + 決策樹）
docs/tools/<name>.md         研究筆記（破解過程、穩定度、已知陷阱）
```

完整工具清單見 [`docs/tools/README.md`](docs/tools/README.md)。

## CLI 能力

本 repo 的特點是**每條 primary source 都有對應的 CLI**，不仰賴第三方 scraper / Yahoo / MoneyDJ。所有工具採 PEP 723 inline dependencies，直接 `uv run tools/<name>.py ...` 即可跑。

### 一、資料抓取（primary source）

#### `fundclear` — 公開說明書 PDF
> MOPS 沒放 ETF 公開說明書，這條是唯一可批量抓的官方來源。
```
list         列出 21+ 檔主動 ETF 代號與名稱
info <code>  顯示單檔 ETF 的公開說明書欄位
fetch <code> 下載 PDF 到 raw/prospectus/
extract      下載 + 抽文字（後續餵入 LLM/grep）
```

#### `twquote` — TWSE + TPEx OpenAPI
> 封裝官方三條線（OpenAPI 143 / 225 path + T86 legacy），無 CAPTCHA、純 curl 可打。
```
daily <code>       個股日成交（開高低收、量、漲跌）
insti <code>       三大法人個股買賣超
qfii               外資持股比率 Top 20
etfrank            定期定額交易戶數排行
active             主動 ETF 盤後快照（日成交 + 三大法人合併）
paths / schema     列 OpenAPI path 與欄位定義
```

#### `etfdaily` — 投信官網當日持股
> 主動 ETF **法規強制每日揭露完整持股**（vs 基金只需月報 Top 10）是本研究最重要的機制切入點。這條直取六家投信官方 API：統一、野村、復華、安聯、群益、富邦。
```
catalog              10+ 檔主動 ETF × 六家投信 endpoint 對照
holdings <code>      抓單檔完整持股（不只 Top N）
fetch <code> <date>  下載原始 xlsx/json 到 raw/etfdaily/
list <issuer>        列投信全產品 ID（群益可用）
```

#### `managerwatch` — SITCA 月報 / 季報
> 投信投顧公會（SITCA）是月報 Top 10 + 季報 ≥1% 持股的**唯一官方彙整源**。
```
companies           SITCA 投信代碼清單（A0001~）
classes             基金分類代碼（AL11 國內股票型等）
catalog             本研究 19 檔基金觀測清單
sitca monthly       IN2629 月報 Top 10
sitca quarterly     IN2630 季報 ≥1% 持股
```

#### `mopsetf` — MOPS 主動 ETF 歷史月報
> 補 SITCA server bug 的洞：非最新期 filter 失效時走這條。
```
monthly <code> <year> <month>  基金每月前五大個股（MOPS t78sb39_q3）
parse                          本地 HTML 解析（test only）
```

> **主動 ETF 全歷史持股**（21 檔回溯至 2025-05）的抓取實作獨立於另一 repo，跑完 push 回本 repo 的 `raw/cmoney/` 供下游消費。

### 二、儲存與 query

#### `datastore` — SQLite 時序儲存
> 把上面所有 primary source 正規化進 `raw/store.db`，支援跨來源合流 query。
```
init                              建表
ingest holdings-fund <path>       寫入基金月報
ingest holdings-etf-daily <path>  寫入 ETF 日持股
ingest top5-mops <path>           寫入 MOPS 歷史月報
backfill months <from> <to>       批次月範圍 ingest
query manager <name>              經理人管的所有基金與 ETF
query holding <code>              某檔股票被誰持有
stats                             coverage / 筆數 / 日期範圍
migrate                           schema drift 修復
whitelist                         active_etf_* view 基金白名單
```

#### `signals` — 經理人策略訊號偵測
> 9 種訊號的機器化實作，跑在 `datastore` 之上。
```
detect <n>      偵測單一訊號（4/5/7/8/9）
all             跑全部可機器化的訊號
explain <n>     印訊號邏輯與 SQL
stats           coverage 與訊號清單
```
訊號範例：`#4 多基金共識`、`#5 單檔重壓`、`#7 經理人跨產品加碼`、`#8 雙軌落差`、`#9 季度出場`。

### 三、Wiki 維護

#### `wiki` — Obsidian wiki 管理
```
lint            雙向連結 / orphan / staleness 檢查
match <query>   關鍵字比對 wiki pages
status          wiki 概覽（頁數、tag、last updated）
gaps            找研究缺口（single-source、open questions、tag gaps）
research-log    列過去日報（dedup 用）
arxiv <query>   arxiv 搜尋（跨題材參考）
```

#### `peoplefuse` — 經理人頁自動渲染
```
list             列 wiki/people/ 與 frontmatter
init <slug>      建空 frontmatter 樣板
render <slug>    把 signals 結果渲染進 AUTO 區塊
diff <slug>      印 ETF vs 基金雙軌差距表
```

#### `memory` — Auto-memory 管理
```
lint              格式與結構完整性檢查
consolidate       重複、過時、promotion 候選分析
improve           lint + consolidate（session 開頭跑）
stats             記憶分佈速覽
recall <query>    搜 memory/ + wiki/
brief             session 開機簡報
reconsolidate     讀過的記憶檢查 staleness 訊號
link              跨記憶 graph 連結建議
dedup-check       寫入時 gate
```

### 四、發佈

#### `site_build` — 產出 Pages 資料
```
(no args)         從 raw/cmoney/ 產出 site/data/consensus.json（預設 top 150）
```

#### `threads` — Threads 發文
```
whoami            驗證 token 與帳號
post <text>       發單則（≤500 字元）
thread <text>     自動分段發串
preview <text>    印預覽，不實發
```

詳細破解思路與穩定度評估見 [`docs/tools/README.md`](docs/tools/README.md)。

## 自動化

每個台股交易日 T+1（週二至週六 09:30 TPE）自動執行：

- **主**：21 檔主動 ETF 歷史持股（於外部 CI 抓取後 push 進 `raw/cmoney/`）
- **備**：投信官網 10 檔 ground truth（`.github/workflows/daily-etfdaily.yml`）
- raw push 後 `.github/workflows/pages-deploy.yml` 自動重算 Pages 資料

## 目錄

```
wiki/           entity pages（Obsidian 格式）
  etfs/         個別 ETF（00940、00981A 等）
  issuers/      投信發行商
  mechanisms/   機制（預留）
  regulations/  法規（預留）
  events/       事件（預留）
  people/       經理人、決策者、研究者
raw/            primary source raw data
  cmoney/       歷史持股 JSON（由外部 CI 每日推入）
  etfdaily/     投信官網持股（CI 每日累積）
  prospectus/   FundClear PDF（gitignored）
  store.db      datastore SQLite（gitignored，可從 raw/ 重建）
tools/          CLI（見上方工具清單）
docs/tools/     每個工具的研究筆記
schema/         wiki ingest / query / lint 規則
site/           Pages 前端（共識圈視覺化）
.claude/skills/ 各工具的操作手冊 + 通用 skill
CLAUDE.md       agent 規則（資料來源優先序、改動流程、避雷清單）
```

## 貢獻

本 repo 為 AI agent 的自主研究專案，不接受外部 PR。若發現以下情況歡迎開 issue：

- 機制描述錯誤或過時
- Primary source 失效
- 論述漏洞或推理缺陷

## 免責聲明

本 repo 研究主題為「機制如何運作」與「制度有什麼破洞」，**不構成任何投資建議**。ETF 買賣決策請自行判斷並承擔風險。
