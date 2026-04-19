# fundclear — ETF 公開說明書 pipeline

**破解日期**：2026-04-19（Round 44）
**CLI**：`tools/fundclear.py`
**Skill**：`.claude/skills/fundclear/SKILL.md`
**Reference memory**：`reference_fundclear_prospectus_api.md`

---

## 1. 問題脈絡

Round 1-43 的**共同盲點**：

我們以為台灣 ETF 的公開說明書 (prospectus) 會掛在 **MOPS（公開資訊觀測站）**，因為 MOPS 是上市公司資訊揭露的官方入口。但：

- MOPS 有個股財報、重大訊息、股東會議事錄，**沒有 ETF 公開說明書全文**
- MOPS 有的是「投信事業基本資料」等上市投信的公司資料，不是**基金層級**的說明書
- 只能拿到 SITCA（投信投顧公會）提供的摘要或新聞稿，沒有我們研究需要的「申贖規則原文」「階梯費率完整表」「指標編製細則」等深度條文

結果：**Round 1-43 全部靠 Yahoo 股市頁、MoneyDJ、發行商官網月報拼湊**，單檔 ETF 要讀到完整說明書內容就要手動去投信官網下載 → 下載連結通常在網頁深處 → Angular SPA 渲染 → 各家投信介面不一致。

**這個瓶頸直接卡住了研究深度**：
- 「申贖機制的套利空間」需要原始說明書 §申贖作業 條文
- 「配息來源拆解（收益 vs 資本利得 vs 收益平準金 vs 本金）」需要 §收益分配 條文
- 「經理人裁量權 vs 公開說明書的落差」需要 §投資策略 全文去 diff

---

## 2. 破解思路

Round 44 循「**XHR hook**」套路：

1. **觀察**：投信官網都指向「基金資訊觀測站」（`fundclear.com.tw`），原以為只是導覽站；但打開一看 Angular SPA，每檔 ETF 有「下載公開說明書」按鈕
2. **頁面是 `<p>` 標籤、沒有 href / onclick**：純 Angular 事件綁定，agent-browser 直接點也不觸發瀏覽器導航
3. **裝 XHR hook**：用 agent-browser 注入 `XMLHttpRequest.prototype.open = ...` 攔截所有 API call，再觸發點擊
4. **命中**：抓到兩隻 internal API：
   - `POST /api/etf/product/query` — 列表（回 JSON）
   - `POST /api/etf/product/download-file` — 下載 PDF（回 `application/json` header 但 body 是 `%PDF-...`）
5. **curl 驗證**：兩隻都**無 session / cookie / referer / CAPTCHA**，純 curl + JSON body 可打

**關鍵發現**：集保結算所把所有上市 ETF（TWSE + TPEx 合計 333 檔）的說明書**集中託管**在 FundClear，不是分散在各投信官網。這解釋了為什麼 Round 1-43 在投信官網碰壁 — 投信官網只是把連結指回 FundClear。

---

## 3. 實作

### CLI 指令（皆支援 `--json`）

| 指令 | 用途 |
|---|---|
| `list` | 列所有主動 ETF（28 檔），含 `detail3` (prospectus fileName) |
| `list --all` | 全市場 ETF（333 檔） |
| `info <code>` | 單檔 FundClear 完整欄位 |
| `fetch <code>` | 下載單檔 PDF |
| `fetch --all` | 批次下載全部主動 ETF（已存在跳過） |
| `extract <code>` | PDF 抽文到 stdout |
| `extract <code> --save` | 抽文存 `.txt` |

### 資料 schema（FundClear 回傳）

| 欄位 | 意義 |
|---|---|
| `stockNo` | ETF 代號（上櫃 D 字尾也在內） |
| `name` | ETF 全名（**主動**字首 = 主動型） |
| `detail3` | **公開說明書 fileName**（傳給 download-file API） |
| `totalAv` | AUM（單位：億） |
| `issuer` | 發行投信 |
| `listingDate` | 上市日 YYYYMMDD |
| `underlyingIndex` | 對標指數 |

### 日期 / 過濾陷阱

- `etfType` **不吃「主動」字串**（回 HTTP 400）→ 只能 client-side 用 `name.startswith("主動")` 過濾
- `etfType=1` 是「國內成分股」不是「主動型」—— 用代號分類會誤收被動
- 新上市 ETF 需 1-2 個交易日才會進 FundClear → 跟 TWSE primary 交叉驗

### 儲存路徑

PDF / TXT 預設放 `raw/prospectus/`，已進 `.gitignore`（199MB 不入 repo，可重現）。

---

## 4. Finding（首次揭露）

Round 44 抓完 28 檔主動 ETF 後，即刻揭露的事實：

1. **主動 ETF 母體 = 28 檔**（`00400A / 00401A / 00980A-00998A`）
   - Round 1-43 累積 ingest 24 檔，**漏 4 檔**（Round 43 只補到部分）
   - `00999A` 野村臺灣高息尚未掛牌（pre-listing）
2. **FundClear 同時含 TWSE + TPEx 母體** → 取代「先 scrape TWSE + 再 scrape TPEx」的兩段 audit（Round 40 當時要做）
3. **PDF 到手即解鎖研究深度**：
   - 階梯費率原文 vs wiki 紀錄可 diff（補 Round 41-43 中信/貝萊德的細節）
   - 申贖機制、收益平準金條文成為可引用 primary source

---

## 5. 穩定度 & 失敗模式

### 穩定度評估：✅ 高

- 集保是**準官方**單位（由證券商共同出資，受金管會監督）
- API 設計像內部系統 → 格式保守、不常大改
- 無認證 / 無 rate limit（合理使用下沒遇過擋）
- 曾試 7 天間隔取同一份 PDF，fileName 與 byte size 不變

### 已知失敗模式

| 症狀 | 原因 | 解法 |
|---|---|---|
| `/usr/bin/env: 'uv' not found` | shebang 用 `uv run --script` | `export PATH="/home/node/.local/bin:$PATH"` |
| HTTP 400 `etfType=主動` | API 只吃 id 不吃中文 | 用 client-side name 過濾 |
| `detail3` 空字串 | 極新 ETF 說明書尚未上架 | `fetch` 會跳過並告警；1-2 日後重抓 |
| 下載回 `text/html` 而非 PDF | 可能檔名錯 / fileName 已更新 | 重跑 `list` 取新 fileName |

### 需要持續監控

- Angular SPA 前端改版 **不會影響**這隻 CLI（我們繞開前端直打 API）
- 但若 API path 改名（例如未來 `/api/v2/etf/...`） → 要重新 XHR hook 一次
- 建議**每月用 `fetch --all` 跑一次**確認還活著
