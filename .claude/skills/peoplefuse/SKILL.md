# Peoplefuse Skill

觸發：「人物頁」「經理人頁」「wiki 融合」「manager 頁」「雙軌差距」「wiki/people render」「peoplefuse」

**研究筆記**：`docs/tools/peoplefuse.md`（設計決策 + 首渲 finding + 研究意義）—— 本 SKILL.md 是操作手冊

---

## 核心

把 datastore + signals 的結構化資料渲染進 `wiki/people/<slug>.md` 的 AUTO 區塊；手寫區塊絕不動。純讀上游、idempotent。

AUTO 區塊產出 4 段：
1. ETF 持股 top 15
2. 基金月報 Top 10 時序
3. 雙軌差距（ETF vs 基金，按 |Δpp| 排序）
4. signal 4 訊號命中（本人管的基金有出現的）

---

## 環境

```bash
export PATH="/home/node/.local/bin:$PATH"
cd /home/node/tw-active
./tools/peoplefuse.py list   # 看目前有 frontmatter 的 people 頁
```

前置：
- `raw/store.db` 裡有對應 ETF / 基金的資料（先跑 datastore ingest）
- `tools/signals.py` 可執行（P5 merged）

---

## Subcommand 速查

| 指令 | 用途 |
|---|---|
| `./tools/peoplefuse.py list` | 列出 `wiki/people/*.md` 有 frontmatter 的概覽 |
| `./tools/peoplefuse.py init <slug>` | 建立空 frontmatter 樣板（idempotent） |
| `./tools/peoplefuse.py render <slug>` | 渲染單一人物頁 |
| `./tools/peoplefuse.py render --all` | 全渲染（有 etfs 或 funds 的才跑） |
| `./tools/peoplefuse.py diff <slug>` | 印雙軌差距表到 stdout（不寫檔） |

---

## Frontmatter 格式

```yaml
---
name: 陳釧瑤
slug: chen-chuan-yao
company: A0009
company_name: 統一投信
etfs: [00981A]
funds:
  - 統一台股增長主動式ETF基金
aliases: [Chuan-Yao Chen]
---
```

- `etfs` / `funds` 吃 list（同 manager 可掛多檔）
- `funds` 寫短名即可，DB 查詢走 LIKE `%短名%`
- `aliases` 目前未用但保留給未來 cross-reference

---

## 常用 Pattern

### Pattern 1：新增一位 manager

```bash
# 1. 建立 stub
./tools/peoplefuse.py init lu-hung-yu

# 2. 編輯 frontmatter 加 etfs / funds（用 Read + Edit）
#    確認 funds 字串在 datastore 能 LIKE match：
./tools/datastore.py query fund --name "復華台灣未來50" --ym 202603 | head -3

# 3. 渲染
./tools/peoplefuse.py render lu-hung-yu
```

### Pattern 2：每次 datastore 有新資料就全渲染

```bash
./tools/datastore.py ingest all
./tools/peoplefuse.py render --all
```

### Pattern 3：快速看雙軌差距不寫檔

```bash
./tools/peoplefuse.py diff chen-chuan-yao
```

輸出 markdown 表（交集 stock codes 按 |Δpp| 排序），適合當 daily report 的一段。

### Pattern 4：驗證 AUTO 區塊不影響手寫

```bash
# 編輯手寫區塊
# ...
./tools/peoplefuse.py render chen-chuan-yao
# AUTO 區塊外的手寫內容不變；diff 應該只看到 AUTO block 換
```

---

## AUTO marker 規則

```
<!-- AUTO:START peoplefuse v1 | generated <iso-ts>Z -->
...
<!-- AUTO:END -->
```

- **外區域手寫**：peoplefuse 絕對不動
- **找不到 START**：append 到檔末
- **找到 START 但無 END**：從 START 處安全覆蓋並補新 block
- **區塊出現多次**：peoplefuse 只替換第一對。手動清掉多餘的就好

---

## 已知陷阱

1. **基金 fund_name 在 DB 有備註**：frontmatter 寫短名（如 `統一台股增長主動式ETF基金`），DB LIKE 會自動 match 含備註版本
2. **ETF 持股為空**：先 `./tools/datastore.py ingest etf-daily --code XXXX`
3. **基金月報只顯示 1 個月**：backfill 該基金 class 不含之前月份（例如 AL11 是主動 ETF 基金分類，剛成立的 ETF 歷史短）
4. **訊號 hit 段落為空**：當月該 manager 的基金沒進 signal 4 threshold=1 的 hit（幾乎不可能，除非 datastore 月份為空）
5. **diff 交集小**：ETF 持股含海外部位（kind='future'/'bond'），diff 只算 kind='stock' 的交集

---

## 與其他 Skill 分工

| 需求 | 用哪個 |
|---|---|
| 建資料 / backfill | datastore skill |
| 偵測訊號 | signals skill |
| **渲染人物頁 AUTO 區塊** | **peoplefuse skill**（本 skill） |
| 人工手寫研究備註 | 直接用 Edit/Write 改 AUTO 區塊外的文字 |
| wiki 知識 ingest 新 entity | ingest skill |

**決策樹**：
- 要「看當下資料」→ datastore query
- 要「看訊號」→ signals detect
- 要「整合到 manager 檔案長期累積」→ peoplefuse render

---

## Phase 狀態

| Phase | 目標 | 狀態 |
|---|---|---|
| P4 | datastore 時序儲存 | ✅ |
| P5 | signals 引擎（7/9） | ✅ |
| **P6** | **wiki/people AUTO 渲染（MVP 2 人）** | **✅ MVP** |
| P6.2 | `wiki/people/index.md` 自動生成 | ⬜ |
| P6.3 | `wiki/etfs` / `wiki/issuers` 同 pattern | ⬜ |
| P7 | 回測 / signal 3/6 manager mapping 啟用 | ⬜ |
