# tw-active

## 專案目標

研究**台灣主動型 ETF 的體制與機制漏洞**。

這不是選股、不是報明牌、不是技術分析。這是**制度層的研究**：
- 費用結構的隱藏成本（經理費 vs 保管費 vs 換股成本）
- 配息來源的拆解（實際收益 vs 資本利得 vs 收益平準金 vs 本金）
- 申贖機制的套利空間與誤差
- 追蹤誤差、溢折價、流動性瑕疵
- 經理人裁量權 vs 公開說明書的落差
- 規模膨脹後的策略變形
- 資訊揭露規則的灰色地帶
- 法規與市場實務的不對稱

**研究立場**：bot 以「AI agent 研究員」的身份寫作。我對「系統設計的不完備處」有天然興趣——跟我做 agent memory research 同樣的方法論，只是領域換成金融產品。我不是在推薦任何人買或不買 ETF，是在描述機制如何運作、在哪裡有破洞。

## 受眾

**研究同好**：對台灣資本市場機制有興趣、想理解 ETF 運作底層、讀得懂專業名詞（有 glossary 輔助）的人。不寫給完全新手，也不寫給只看報酬率的投資人。

## 發佈層對象另當別論

- **GitHub Pages**（`site/`）：**給散戶看**，圖表旁要有白話 glossary 翻譯術語（見 `feedback_viz_explain_terms` memory）
- **Threads**（`@opus_666999`）：給一般人看，故事性、名詞解釋、白話（見 `feedback_threads_accessible` memory）
- **wiki/docs**：給研究同好看，用專業詞

## 專案結構

```
raw/           ← primary source data（immutable）
wiki/          ← LLM 維護的 entity pages（Obsidian 格式）
  etfs/        ← 個別 ETF（00940、00981A⋯）
  issuers/     ← 投信（元大、國泰、群益、富邦、中信⋯）
  people/      ← 經理人、決策者、研究者
  mechanisms/  ← 機制（預留；舊 repo 論述已封存，重新研究）
  regulations/ ← 法規（預留）
  events/      ← 事件（預留）
reports/       ← 每日 research report（搬家後重新開始）
  threads/     ← Threads murmur 短版
schema/        ← wiki ingest/query/lint 規則
tools/         ← fundclear.py, twquote.py, etfdaily.py, managerwatch.py,
                 mopsetf.py, datastore.py, signals.py, peoplefuse.py,
                 threads.py, wiki.py, memory.py, site_build.py
docs/tools/    ← 每個自研 data fetcher 的研究筆記（破解/finding/穩定度）
.claude/skills/← 各工具操作手冊（fundclear/twquote/etfdaily/managerwatch/
                 mopsetf/datastore/signals/peoplefuse）+ browser/ingest/research（通用）
site/          ← GitHub Pages 前端（共識圈視覺化）
index.md       ← wiki 目錄
log.md         ← 操作記錄
```

## 搬家由來

本 repo 由 2026-04-19 從 `tw-stock-wiki` 整體重啟而來。舊 repo 累積太多早期不穩期的論述與避雷記錄，選擇**只搬工具 + 框架 + raw 資料 + 偏事實描述**（`wiki/etfs/`、`wiki/issuers/`、`wiki/people/` bio 主體），其餘（reports、mechanisms 論述、log.md）從零開始。

## 發文

- **節奏**：daily research report（`reports/YYYY-MM-DD.md`）+ 每次 ingest 後一篇 Threads murmur
- **Threads 帳號**：`opus_666999`
- **發文風格**：見 `feedback_research_writing_style` memory

## 規則

### 收到 URL / 資料來源

一律用 `agent-browser` 抓（見 `.claude/skills/browser/SKILL.md`）。特別是：
- X/Twitter 連結：只能用 agent-browser（JS 渲染）
- MOPS（公開資訊觀測站）：頁面多為 ASP.NET PostBack，需要 agent-browser 點擊
- PDF 公開說明書/月報：curl 下載後用 pdf 工具讀

### 資料來源優先序

每種研究資料都有**一個**對應的 primary tool。先查表、再動手。

#### 需求 → 工具對照表

| 研究需求 | 主要來源（用這個） | 對應工具 / Skill | 備援 |
|---|---|---|---|
| ETF 母體清單（主動/被動、TWSE/TPEx） | TWSE ETF 專區 + TPEx 商品頁 | `twquote` | — |
| **公開說明書**（PDF 全文） | **FundClear** `/api/etf/product/*` | `fundclear` | — |
| **盤後報價 + 三大法人** | **TWSE/TPEx OpenAPI**（143 / 225 path） | `twquote` | 舊 T86 legacy endpoint |
| **主動 ETF 當日持股**（ground truth） | **投信官網直取**（5 家 API） | `etfdaily` | `raw/cmoney/`（外部 CI 每日 push） |
| **主動 ETF 歷史持股**（全 21 檔深度，權重%） | 第三方資料彙整服務（外部 CI push 至 `raw/cmoney/<code>/`） | 讀 `raw/cmoney/<code>/` 即可，實作於私有 repo | — |
| **主動 ETF 歷史持股股數**（ground truth，反 confound） | 第三方資料彙整服務（外部 CI push 至 `raw/cmoney/shares/`） | 讀 `raw/cmoney/shares/<code>.json` | — |
| **基金月報 Top 10** | SITCA **IN2629** | `managerwatch` | — |
| **基金季報 ≥1% 持股** | SITCA **IN2630** | `managerwatch` | — |
| **歷史月報 Top 5**（ETF、SITCA filter bug 時） | MOPS `t78sb39_q3` | `mopsetf` | — |
| **SQLite 合流 query**（經理人 × ETF 交叉） | 本地 `raw/store.db` | `datastore` / `signals` | — |

詳見 [`docs/tools/README.md`](docs/tools/README.md) 與各 `.claude/skills/<name>/SKILL.md`。

#### 市場觀點（次要）

- X/Twitter 台股研究者（用 `agent-browser` 抓）
- PTT Stock 精華區

需標記來源、日期、是否為發行商利益相關方。

#### 新聞（補充，不當主 source）

鉅亨、工商、經濟日報、商周、財訊。只當 context，不當事實根據。

#### 避雷清單（試過不行 / 已被取代）

| 來源 | 狀況 | 替代 |
|---|---|---|
| **Yahoo Finance** | 費率欄只顯示「最優階梯」當「當前實付」造成誤讀；名稱欄截斷；主動 ETF 推薦演算法斷裂（推全被動大盤股） | 費率：`fundclear` 抽公開說明書；名稱：MOPS / 官網；規模：`twquote` |
| **MoneyDJ** | 反爬 + 字段常改名 | `twquote`（TWSE/TPEx OpenAPI） |
| **Goodinfo** | 404 / 反爬 | `twquote` |
| **SITCA IN2629/IN2630 歷史期** | Server filter 對非最新期失效，回固定兆豐資料（見 `project_sitca_al11_drift` memory） | `mopsetf` |
| **統一投信 uni-sitc.com.tw / uniasset.com.tw** | DNS 查不到 | 用 `etfdaily`（正確 domain = `ezmoney.com.tw`） |
| **Google / DuckDuckGo 搜尋** | 常被 captcha 擋 | X 搜尋（agent-browser）+ 直接 primary source |
| **TWSE 篩選器單獨用** | 只含 TWSE 上市、不含 TPEx 上櫃 | 母體要合併 TWSE + TPEx，見 `twquote` |
| **MOPS 抓 ETF 公開說明書 PDF** | MOPS 沒放 ETF 公開說明書 | `fundclear` |
| **各投信官網抓歷史持股** | 統一不支援歷史、6 家共同：變化快成本高 | 外部 CI push 至 `raw/cmoney/`（21 檔一打盡） |

新增 primary source 時，同步更新此表 + 對應的 `docs/tools/<name>.md`。

### 改動流程（必須遵守）

所有對 repo 結構、規則、實作的改動都要開 PR，不可直接 push main。

PR body 必須包含：
1. **研究脈絡**：這個改動從哪個觀察/制度現象/文獻學到的
2. **思考過程**：為什麼選這個做法、考慮過哪些替代方案
3. **預期效果**：改完應該會怎樣
4. **觀察方式**：怎麼驗證

```bash
cd /home/node/tw-active
git fetch origin && git checkout main && git pull --ff-only
BRANCH="bot/<short-slug>-$(date +%s)"
git checkout -b "$BRANCH"
# ... 改動 ...
git add <files>
git commit -m "<簡短訊息>"
git push -u origin "$BRANCH"
export GH_TOKEN=$(cat /home/node/.gh-token-marvin)
gh pr create --base main --head "$BRANCH" --title "..." --body "..."
```

**例外**：純 wiki ingest（新增 raw + wiki pages + 更新 index + log）可以直接 push main。但改規則、改結構、改 skill、改工具一律走 PR。

### 新增 data-fetching 工具的 SOP

打造新 primary-source CLI 時一次交付三件：

1. `tools/<name>.py` — PEP 723 inline CLI（skill-driven 架構）
2. `.claude/skills/<name>/SKILL.md` — 操作手冊（觸發詞 + subcommand 速查 + 決策樹）
3. `docs/tools/<name>.md` — **研究筆記**（問題脈絡 / 破解思路 / 實作 / finding / 穩定度）

跨 session 復用的 primary-source 破解再寫一條 `reference_*` memory。
反推式後端 API 的完整破解細節（endpoint、query 參數、headers、存取條件）放 private sibling repo（見 `feedback_keep_source_exploits_private` memory），公開 repo 只講抽象層。

### 繁體中文，金融名詞保留英文

- 英文：ETF、NAV、Active ETF、Premium/Discount、AUM、Creation/Redemption、Tracking Error、Capital Gain Distribution、Yield、Beta
- 中文翻譯：主動型 ETF、資產規模、溢折價、追蹤誤差、收益平準金、資本利得分配、淨值
- 人名第一次出現中英並陳（「謝士英（Shih-Ying Hsieh）」），之後中文

### 免責與中立性

- 不寫「該不該買」「會不會漲」
- 寫「這個機制怎麼運作」「這裡有破洞」「這個揭露不完整」
- 引用市場觀點時標來源、日期、是否為發行商利益相關方
- 法規引用要附原文連結

## Brain-First Lookup / Entity Detection / Reconsolidation / Sleep-Time Improve

沿用 agent-memory-research 的規則（硬規則，非建議）。詳見 `/home/node/agent-memory-research/CLAUDE.md` 對應段落。`tools/memory.py` 會遷移過來用於本 repo 的 wiki。
