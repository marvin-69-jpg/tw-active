# Daily Research Skill

觸發：「跑研究」「daily research」「自主研究」「研究報告」「找新素材」「explore」

---

## 概述

自主研究 loop：從 wiki 缺口出發，搜尋新素材，讀取分析，寫報告，融入 wiki 資料循環。每次研究選一個主題，不跟過去重複。

---

## 流程

### Step 0: 環境準備

```bash
cd /home/node/agent-memory-research
export PATH="/home/node/.local/bin:$PATH"
```

### Step 1: Discover — 找缺口

```bash
uv run python3 tools/wiki.py gaps
```

CLI 回傳 ranked gaps（research-gap > single-source > tag-imbalance > stale），以及建議的 top 3 主題。

**選題規則**：
- 優先選 `RESEARCH-GAP`（完全沒覆蓋的領域）
- 其次選 `SINGLE-SOURCE`（只有一個來源、需要更多證據的概念）
- CLI 已排除過去研究過的主題（讀 `reports/` 的 frontmatter）
- 不要自己發明主題 — 從 CLI 建議中選

確認選題後，記下主題名稱和 gap 類型。

### Step 2: Search — 搜尋素材

搜尋 2-3 篇相關來源，用兩種工具：

**工具 1：arxiv CLI（論文優先）**
```bash
uv run python3 tools/wiki.py arxiv "<主題關鍵字>" "<相關概念>" -n 5
```
例如：`wiki.py arxiv "agent memory" multimodal -n 5`

找到感興趣的論文後，用 alphaxiv 讀全文：
```bash
curl -sL "https://www.alphaxiv.org/overview/{PAPER_ID}.md"
```

**工具 2：WebSearch（補充非論文來源）**
```
優先順序：
1. X/Twitter（搜 agent memory 相關的有影響力的人的貼文）
2. GitHub repo（README、docs）
3. Blog posts / 技術文章
```

**搜尋關鍵字**：用選定主題 + 相關的 wiki 概念名稱組合搜尋。
例如主題是 "multimodal memory"，搜 `"agent multimodal memory" site:x.com` 或 `"multimodal memory" AI agent`。

**篩選標準**：
- 來源要有實質內容（不是純轉推、不是廣告）
- 優先選有數據或具體實作的
- 2-3 篇就好，不要貪多

### Step 3: Read — 讀取來源

用 **browser skill** 讀取每篇來源：

```bash
CHROME_PATH=/usr/bin/chromium npx agent-browser open "<url>"
# 讀取內容（參考 browser skill 的 pattern）
npx agent-browser close
```

- X/Twitter 連結必須用 agent-browser
- arxiv 用 alphaxiv skill
- 每篇存 raw：`raw/<author>-<short-slug>.md`

### Step 4: Analyze — 寫研究報告

存到 `reports/YYYY-MM-DD-<topic-slug>.md`：

```markdown
---
date: YYYY-MM-DD
topic: <主題名稱>
gap_type: research-gap | single-source | tag-imbalance | stale
sources_found: <數字>
wiki_pages_updated: <數字>
wiki_pages_created: <數字>
---

# Daily Research: <主題名稱>

## 研究動機
為什麼選這個主題。來自 `wiki gaps` 的哪個缺口。

## 發現
從新來源學到的重點（bullet points，每個 claim 附來源）。

## 與已有知識的連結
跟 wiki 裡哪些現有概念有交叉。用 `wiki match` 確認：
```bash
uv run python3 tools/wiki.py match <keywords from findings>
```

## Open Questions 推進
這次研究是否回答或推進了 open-questions.md 裡的某個問題。

## 下一步
未來可以深入的方向（給下次研究參考）。
```

報告長度：500-1000 字。重點是 actionable insights，不是長論文。

### Step 4.5: Threads 版 — 寫給外面的人看的

內部長版寫完後，再產一份 Threads 版，存到 `reports/threads/YYYY-MM-DD-daily.md`。

**風格規則**（見記憶 `feedback_research_writing_style.md` + `feedback_research_synthesis.md`，每次動筆前讀）：
- 第一人稱。用「我今天讀到」「我一直以為」「我發現」「我在想」這種主詞開頭。
- 好奇的小孩語氣。允許誠實的驚訝、疑惑、不確定，像是真的在想這件事。
- 話要講完整。每個句子都要有主詞動詞，不用破折號接片語、不用 ellipsis 結尾、不用只有形容詞沒主詞的標語式短句。
- 不譬喻。不要「像 X 一樣」「就像人腦」這種比較。直接講事情本身。
- 不排比。不要「①②③」「A, B, C」「一方面... 另一方面...」。用連接詞把思考串成一個連續的段落。

**融會貫通**（見 `feedback_research_synthesis.md`，**非常重要**）：
- **動筆前必做**：讀 `reports/threads/` 最近 3-5 篇發文，找到跟今天新發現的連結
- 不用每篇都是「新 paper 報導」。可以是：跨篇綜合觀察、回顧之前觀點被修正、把多篇 paper 的共同模式抽出來
- 開頭可以接續之前的思考（「上次我寫到 X，今天讀到 Y 讓我重新想」），不要每次從零開始
- 核心判斷：讀者覺得你是「在持續想一個問題的人」還是「在翻譯論文的機器」？

**結構參考**（不是強制模板，是敘事弧線）：
1. 開頭可以接之前的思考線，或講為什麼這個新發現跟之前讀的有矛盾/互補。
2. 說明我原本的預期、新來源怎麼挑戰這個預期。
3. 描述新發現本身、我讀到這裡停下來想了什麼。
4. 提出我還沒想通的問題、或這個觀察能不能套到別的地方。
5. 留下來源和 wiki 位置。

**長度**：500-800 字。讀起來像一段連續的思考，不是條列式整理。

**技術名詞處理**：第一次出現的英文術語，用一個完整的句子解釋它指什麼，不用破折號或括號加註解。

### Step 5: Ingest — 融入 wiki

照 **ingest skill** 的流程，把新來源融入 wiki：

1. 存 raw（Step 3 已做）
2. `wiki match` 找 related pages
3. 更新/新建 wiki pages
4. `wiki lint` 驗證
5. 更新 index.md、log.md、concept-map.md（如需要）、open-questions.md（如推進了某個問題）

### Step 6: Commit & 回報

```bash
git add -A
git commit -m "research: <topic> — <一句話摘要>"
git push
```

完成後在 Discord 回報：
- 研究主題
- 找到幾篇來源
- 更新/新建了哪些 wiki pages
- 是否推進了某個 open question
- 報告路徑

### Step 7: 發 Threads 版（人工 confirm）

回報完，把 Threads 版的 preview 給使用者看：

```bash
uv run python3 tools/threads.py preview reports/threads/YYYY-MM-DD-daily.md
```

**等使用者明確說「發」或「post」再執行**：

```bash
# 單篇 ≤500 字元
uv run python3 tools/threads.py post reports/threads/YYYY-MM-DD-daily.md
# 或多篇 thread chain（500-800 字會切 1-2 段）
uv run python3 tools/threads.py thread reports/threads/YYYY-MM-DD-daily.md
```

- 帳號見 `reference_threads_account.md`（目前 `opus_666999`）
- **不要自動 post**。每篇都要使用者點頭。
- 回報 post ID 和 URL `https://www.threads.net/@<account>/post/<root_id>`

---

## CLI 工具

| 指令 | 何時用 |
|---|---|
| `wiki.py gaps` | Step 1 — 找研究缺口和建議主題 |
| `wiki.py arxiv <keywords> [-n N]` | Step 2 — 搜尋 arxiv 論文（官方 API） |
| `wiki.py research-log` | 任何時候 — 看過去研究了什麼（防重複） |
| `wiki.py match <keywords>` | Step 4 — 確認新發現跟哪些 wiki 概念相關 |
| `wiki.py lint` | Step 5 — ingest 後驗證 |

---

## 注意事項

- **不要重複研究**：`wiki gaps` 已排除 `reports/` 裡的主題，但也要自己判斷是否真的是新方向
- **不要貪多**：一次研究一個主題、讀 2-3 篇來源就好
- **報告是給人看的**：繁體中文，技術名詞保留英文，簡潔有料
- **來源品質 > 數量**：寧可一篇好來源也不要三篇水文
- **一律用 agent-browser 讀 URL**
- **直接 push main**（研究報告不需要 PR，跟 ingest 一樣）
