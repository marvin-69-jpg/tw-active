# Ingest Skill

觸發：「整理這篇」「讀這個連結」「加到 repo」「ingest」、或使用者丟了一個 URL

---

## 流程

1. **用 agent-browser 讀取文章**（參考 `browser` skill）
   ```bash
   CHROME_PATH=/usr/bin/chromium npx agent-browser open "<url>"
   npx agent-browser eval '(() => {
     const h1 = (document.querySelector("h1")||{}).textContent||"";
     const ps = [...document.querySelectorAll("p")]
       .map(p => p.textContent.trim())
       .filter(t => t.length > 20);
     return JSON.stringify({ title: h1.trim(), body: ps.join("\n\n") });
   })()'
   npx agent-browser close
   ```
   - X/Twitter 推文用 X 專用 pattern（見 browser skill）
   - 讀完一定要 `close`

2. **存 raw 全文**到 `raw/<author>-<short-slug>.md`，保留原文結構，頂部加 metadata（Author / Date / Source）

3. **執行 wiki ingest**（依 `schema/CLAUDE.md` 的 Ingest 流程）：

   **Orient** → 讀 index.md + log.md（最近 5 筆）+ raw

   **Extract** → 抽出所有 concept / entity / people / product

   **Match（CLI）** → 用 CLI 找 related pages：
   ```bash
   cd /home/node/agent-memory-research && export PATH="/home/node/.local/bin:$PATH"
   uv run python3 tools/wiki.py match <keyword1> <keyword2> ...
   ```
   用 Extract 抽出的每個 entity 作為 keyword。CLI 回傳 ranked list，取代手動掃 index.md。

   **Plan** → 根據 match 結果 + extract 結果，列出要新建 / 更新的 pages
   - **Micro-source gate**：來源 < 500 字（單則推文）→ 只更新已有 page，不建新 concept page

   **Execute** → 逐頁處理（rewrite Current Understanding，append Key Sources，add cross-links in Related）

   **Verify（CLI）** → 跑 lint 檢查 bidirectional links：
   ```bash
   uv run python3 tools/wiki.py lint
   ```
   修完所有 errors（missing backlinks）再繼續。

   **Update Meta** →
   1. 更新 index.md（新 page + 修改 page 的 summary）
   2. Append log.md（含 `- Insights:` 欄位記錄跨來源連結）
   3. 檢查 concept-map.md — 新 page 要加到對應 layer
   4. 檢查 open-questions.md — 新來源是否回應了某個 open question

4. **寫 Ingest Murmur**（對外 Threads 版的短篇）

   ingest 完 wiki 後，產一篇「研究側記」存到 `reports/threads/YYYY-MM-DD-murmur-<slug>.md`。這是給外面的人看的，Threads 會用。

   **風格規則**（見記憶 `feedback_research_writing_style.md`，每次動筆前讀）：
   - 第一人稱。用「剛讀完」「我發現」「我想了一下」這種主詞開頭。
   - 好奇的小孩語氣。允許誠實的驚訝、疑惑、不確定。
   - 話要講完整。每個句子都要有主詞動詞，不用破折號接片語、不用 ellipsis、不用標語式短句。
   - 不譬喻。不要「像 X 一樣」「就像人腦」。
   - 不排比。不要「①②③」「A, B, C」。用連接詞把思考串成一段。

   **結構**：
   1. 講我剛讀完什麼、其中哪一段讓我停下來想。
   2. 描述那個觀察本身、為什麼覺得意外。
   3. 我讀完之後的一個小反思。
   4. 結尾說這篇整理到 wiki 的哪頁。

   **長度**：200-400 字。比每日 Threads 版短，更像研究途中的隨手筆記。

   **Frontmatter**：
   ```
   ---
   date: YYYY-MM-DD
   type: ingest-murmur
   source: raw/<filename>.md
   wiki_page: <page-name>
   ---
   ```

5. **Commit & push**
   ```bash
   cd /home/node/agent-memory-research
   git add -A
   git commit -m "ingest: <作者> — <標題> (<日期>)"
   git push
   ```

6. **發 murmur 到 Threads**（人工 confirm）

   ```bash
   uv run python3 tools/threads.py preview reports/threads/YYYY-MM-DD-murmur-<slug>.md
   ```

   貼 preview 結果給使用者看，**等使用者明確說「發」或「post」再執行**：

   ```bash
   uv run python3 tools/threads.py post reports/threads/YYYY-MM-DD-murmur-<slug>.md
   ```

   - 帳號見 `reference_threads_account.md`（目前 `opus_666999`）
   - 單篇 ≤500 字元用 `post`，超過用 `thread`（會自動切段 + reply chain）
   - **不要自動 post**。每篇都要使用者點頭。回報 post ID 和 URL `https://www.threads.net/@<account>/post/<id>`

---

## CLI 工具

| 指令 | 何時用 | 用途 |
|---|---|---|
| `wiki.py match <keywords>` | Extract 後 | 找 related pages，取代手動掃 index |
| `wiki.py lint` | Execute 後 | 驗證 bidirectional links、meta-page staleness |
| `wiki.py status` | 任何時候 | 快速 overview（page count、last ingest、tag 分佈） |

所有指令前都要 `cd /home/node/agent-memory-research && export PATH="/home/node/.local/bin:$PATH"`。

---

## 注意事項

- **一律用 agent-browser 讀取 URL**，不要用 curl hack 或 WebFetch
- **arxiv 論文用 alphaxiv skill**（`curl -sL "https://www.alphaxiv.org/overview/{PAPER_ID}.md"`），比讀 PDF 更完整
- Wiki pages 用 Obsidian `[[wiki-links]]` 格式互相連結
- 一個概念一個 page，不要合併
- 筆記用繁體中文，技術名詞保留英文
- 保留重要的原文引用（blockquote）
- 每個 claim 要有 source（link 到 `[[raw/filename]]`）
- **Micro-source**（< 500 字）只更新已有 page，不建新 concept page
- **每次 ingest 都要寫 murmur**（Step 4），放 `reports/threads/`，作為對外 Threads 側記
