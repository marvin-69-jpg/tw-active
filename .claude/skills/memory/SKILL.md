# Memory Skill

觸發：session 開始、「記憶健康」「memory lint」「memory stats」「記憶品質」「合併記憶」「promote feedback」「記得什麼」「recall」「brief」

---

## CLI

所有操作都透過 `tools/memory.py`：

```bash
cd /home/node/agent-memory-research
export PATH="/home/node/.local/bin:$PATH"
uv run python3 tools/memory.py <subcommand>
```

| Subcommand | 用途 |
|------------|------|
| `improve` | 整合 lint + consolidate，session 開頭跑 |
| `lint` | 格式 + 結構檢查 |
| `consolidate` | 語意分析：重複、過時、promotion、cross-ref |
| `stats` | 記憶分佈概覽 |
| `recall <query>` | 跨 memory/ + wiki/ 搜尋，brain-first lookup |
| `brief` | Session 啟動 briefing — 壓縮輸出 agent 目前知道的一切 |

可選參數：
- `--memory-dir PATH` — 記憶目錄（預設 `/home/node/.claude/projects/-home-node/memory/`）
- `--claude-md PATH` — CLAUDE.md 路徑（預設 `/home/node/CLAUDE.md`）

---

## Operation 1：Session Startup（每個新 session）

**觸發**：session 開始，讀完 MEMORY.md 之後。

```bash
cd /home/node/agent-memory-research && export PATH="/home/node/.local/bin:$PATH" && uv run python3 tools/memory.py improve
```

### 處理輸出

| Category | 意思 | 怎麼做 |
|----------|------|--------|
| `FIX` | 格式錯誤、MEMORY.md 脫鉤 | **當場修**，不要拖 |
| `OBSERVE` | wiki Implementation section 有待回流的觀察 | 讀該 wiki page，根據這個 session 的經驗補上觀察結果 |
| `MERGE` | 近似重複記憶 | 讀兩個檔案，合併成一條，刪掉另一條，更新 MEMORY.md |
| `REVIEW` | project 記憶超過 14 天 | 讀該記憶，確認是否過時。過時就刪或更新 |
| `PROMOTE` | feedback 群聚，CLAUDE.md 沒涵蓋 | 讀那幾條 feedback，判斷是否穩定。穩定的話合併成一條 CLAUDE.md 規則 |
| `NOTE` | 平衡建議 | 記下來，對話中適時處理 |

---

## Operation 2：On-Demand Check（使用者主動問）

使用者說「記憶狀態」「memory 健康嗎」之類的。

1. 跑 `stats` 看分佈
2. 跑 `consolidate` 看詳細分析
3. 回報結果 + 建議的 action

---

## Operation 3：Merge（合併重複記憶）

consolidate 報告說有 MERGE 候選時：

1. 讀兩個記憶檔的完整內容
2. 判斷是否真的重複（description 相似不代表內容重複）
3. 如果確認重複：
   - 合併內容到其中一個檔案（保留所有有用資訊）
   - 刪掉另一個
   - 更新 MEMORY.md index

---

## Operation 4：Promote（升級 feedback 到 CLAUDE.md）

consolidate 報告說有 PROMOTE 候選時：

1. 讀該 topic 下所有 feedback 記憶
2. 判斷 pattern 是否穩定（被糾正過多次 = 穩定）
3. 如果穩定：
   - 寫一條 CLAUDE.md 規則（簡潔、有 Why）
   - 開 PR 到對應的 repo
   - feedback 記憶保留（作為歷史記錄）

**注意**：CLAUDE.md（`/home/node/CLAUDE.md`）是 root-owned symlink，無法直接改。promote 的目標是各專案自己的 CLAUDE.md（例如 `/home/node/agent-memory-research/CLAUDE.md`）。

---

## Operation 5：Recall（brain-first lookup）

使用者問的問題可能跟過去研究或記憶有關時。

```bash
cd /home/node/agent-memory-research && export PATH="/home/node/.local/bin:$PATH" && uv run python3 tools/memory.py recall <keywords>
```

- 同時搜尋 memory/（auto-memory）和 wiki/（研究 wiki）
- 按 keyword 出現次數排序，顯示 top 10
- 輸出每個命中檔案的名稱、type、description、compiled truth 摘要
- 用來回答問題前先查 brain，external 是 fallback

---

## Operation 6：Brief（session 啟動 briefing）

新 session 開始時，在 `improve` 之後跑，快速掌握全局。

```bash
cd /home/node/agent-memory-research && export PATH="/home/node/.local/bin:$PATH" && uv run python3 tools/memory.py brief
```

- 輸出 auto-memory 分佈 + 每條記憶的 name/description
- 輸出 wiki 的 concepts / products / people 分類列表
- 輸出已實作到 openab-bot 的 pattern
- 一次讀完就掌握「我目前知道什麼」

---

## 來源

Sleep-time compute pattern — GBrain dream cycle + Letta Context Constitution。
用 session 啟動時機代替 cron，每次對話都讓記憶系統比上次更好。
