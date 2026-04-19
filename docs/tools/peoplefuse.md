# peoplefuse — Phase 6 wiki × datastore 融合

**建立日期**：2026-04-19（Round 45，managerwatch project Phase 6）
**CLI**：`tools/peoplefuse.py`
**Skill**：`.claude/skills/peoplefuse/SKILL.md`
**上游**：`raw/store.db`（P4）+ `tools/signals.py`（P5）

---

## 1. 問題脈絡

`wiki/` 是手寫 markdown 知識庫，`raw/store.db` 是結構化時序資料——兩邊沒有橋。研究成果只能在 daily report 裡 one-off 引用，無法累積在人物/ETF/基金等 wiki entity 頁上。

核心論點：**「同一經理人在基金月報 vs ETF 日揭露上的差距」是這個 repo 的核心研究洞察**，最自然的呈現載體是 `wiki/people/<manager>.md`——每位經理人有一頁，資料部分自動渲染，研究備註手寫。

這就是 Phase 6：把 datastore/signals 的資料**渲染進 wiki entity 頁的 AUTO 區塊**，同時保留手寫區塊不動。

---

## 2. 設計思路

### 核心決策

- **wiki entity page = source of truth**：frontmatter 定義 manager 的 `etfs` / `funds`，peoplefuse 讀 frontmatter 再 query datastore
- **AUTO / 手寫雙區塊**：`<!-- AUTO:START peoplefuse v1 ... -->` 到 `<!-- AUTO:END -->` 之間是 peoplefuse 管，**外面絕不動**
- **stdlib only + subprocess**：跟 datastore/signals 一致，不引 Jinja2 / PyYAML。Frontmatter 用 mini YAML parser（支援 `key: [a, b]` + `key:\n  - item`）
- **冪等**：同一份資料 render 多次產生同樣輸出（除了 AUTO 區塊 header 的時間戳）
- **失敗友善**：某段查詢失敗（例如 signal 查詢報錯）只會讓該段變成 `（查詢失敗：…）`，不會整頁毀掉

### 渲染區塊

peoplefuse 在 AUTO 區塊內渲染 4 段：

1. **ETF 持股表**（每檔 etf 一張）：最新 `data_date` 的 top 15 股票（kind='stock'），含權重和股數
2. **基金月報 Top 10 時序**（每檔 fund 一張）：最近 3 個月 Top 10 的 pct 時序表
3. **雙軌差距**（ETF × fund 第一組）：兩邊同時持有的 code，按 `|Δpp|` 排序取 top 10
4. **訊號命中**（signal 4 多基金共識 @ 最新月份）：篩出本人管理的基金有出現的 hit

雙軌差距是研究 thesis 的具體呈現——**同一位經理人在兩個產品上的權重差距**，這是 JOY 88 想做但沒做出的視圖。

### Frontmatter schema

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

`etfs` / `funds` 吃 list 支援一人多產品。`funds` 的 match 用 LIKE（DB 裡 fund_name 常帶「(基金之配息來源可能為收益平準金)」備註，frontmatter 寫短名即可）。

---

## 3. 實作

### CLI 指令

| 指令 | 用途 |
|---|---|
| `list` | 列出 `wiki/people/*.md` 有 frontmatter 的人物概覽 |
| `init <slug>` | 建立空 frontmatter 樣板（idempotent，已有則略） |
| `render <slug>` | 渲染單一人物頁 AUTO 區塊 |
| `render --all` | 全渲染（有 etfs 或 funds 的才跑） |
| `diff <slug>` | 印雙軌差距表到 stdout（不寫檔，供 one-off 查看） |

### AUTO marker

```
<!-- AUTO:START peoplefuse v1 | generated 2026-04-19T04:37Z -->
...
<!-- AUTO:END -->
```

找不到 start marker → append 到檔末。找到 start 但無 end → 安全起見從 start 處覆蓋並補新 block。

### 與 datastore / signals 的橋

```python
query_etf_holdings(etf)  → subprocess datastore.py query holdings --etf X --json
query_fund_monthly(name) → subprocess datastore.py query fund --name X --json
query_signal_4(month)    → subprocess signals.py detect 4 --month YYYYMM --threshold 1
```

純讀，不改 DB。peoplefuse 失效時改 datastore/signals schema 需要改 mapper，但大部分欄位是 row dict 直接透傳。

---

## 4. 首次揭露：peoplefuse 首渲

### 陳釧瑤（統一 00981A）

渲染後頁面 AUTO 區塊自動含：
- ETF top 15：2330 8.67% / 2383 7.46% / 2308 6.12% / 3653 5.91% / ...
- 基金 Top 10（202603）：2330 9.57% / 2383 7.02% / 2308 6.05% / ...
- **雙軌差距 Top 3**：2330 -0.90pp、3017 -0.71pp、2345 +0.44pp
  - 意義：ETF 較分散、基金在 2330/3017 較集中 → 基金揭露相對「展示性」
- 訊號命中：她管的基金命中 10 個 signal 4（多基金共識）hit

### 呂宏宇（復華 00991A）

- ETF top 3：2330 16.57% / 2383 9.68% / 2308 6.79%
- 基金 Top 10：2330 18.23% / 2383 7.89% / 8299 7.40% / ...
- **雙軌差距 Top 3**：2408 -2.15pp、2383 +1.79pp、2330 -1.66pp
  - 意義：2330 基金更集中（符合 JOY 88 spec「重倉型」），但 2383 反而 ETF 更重（代表 ETF 比基金更押 CCL 敘事）
- 訊號：命中 9 個 signal 4 hit（其中 3017 奇鋐、2345 智邦是跨多家投信共識）

**兩位雙軌差距風格對比**：
- 陳釧瑤：小差距（均在 1pp 內），基金 ETF 近乎平行操作
- 呂宏宇：大差距（2pp 級別），兩個產品在某些 code 有明顯策略差異

這是 peoplefuse 沒做之前**靠肉眼比對 JSON dump 看不出來的結構化洞察**，一跑 render 就呈現。

---

## 5. 穩定度 & 失敗模式

### 穩定度：✅ 中（新工具，測試覆蓋率限於首渲 2 位）

- 純讀操作，不會破壞 datastore
- AUTO marker 雙保險：找不到 start → append、找不到 end → 從 start 處覆寫
- frontmatter 解析是 mini YAML，相容性有限（不支援嵌套 dict、multi-line string）

### 已知失敗模式

| 症狀 | 原因 | 解法 |
|---|---|---|
| render 時 ETF 表空 | datastore 該 ETF 無資料 | 先 `./tools/datastore.py ingest etf-daily --code XX` |
| 基金 Top 10 只有 1 個月 | backfill 時該基金可能跨 fund_class 或上市未久 | 增加 comid-specific backfill |
| 雙軌差距交集小 | ETF `data_date` 跟基金 `ym` 不在同一天（正常）或 ETF 海外部位多 | 正確行為；差距表只看 stock kind |
| AUTO 區塊跑去第二次 append（有重複） | marker 格式被手動改壞 | 手動刪多餘 block，重跑 render |
| `peoplefuse render --all` 跑很久 | 每人每段都 subprocess datastore | 大量渲染時可加快取（未做） |

### 待補（未做）

- **`wiki/people/index.md` 自動生成**：列出所有 manager + 管的 ETF/基金 + 最強訊號 hit。plan Stage 5
- **訊號擴展**：目前只渲染 signal 4，可加 signal 5/7/9 區塊
- **快取層**：大量 render 時每人重複 subprocess 同一 datastore query，可加 memoize
- **多 manager 共管同一檔**：當前 frontmatter 是 1-manager-per-page，需要 review 時再擴
- **頁面 lint**：檢查 AUTO marker 是否成對、frontmatter 必填欄位
- **Phase 7 回測 hook**：signals hit 後 N 月的報酬驗證訊號品質

---

## 6. 研究意義

Phase 6 第一次讓 wiki entity 頁**即有敘事又有資料表**。過往 wiki 只寫研究結論，data table 要跑 SQL 手貼；peoplefuse 後，人物頁**打開就看到當下資料 + 差距 + 訊號**，研究備註區塊繼續手寫整理洞察。

長期目標：這個 pattern 擴展到：
- `wiki/etfs/<code>.md` AUTO 區塊：歷史 AUM / top 持股 / 換手率
- `wiki/issuers/<slug>.md` AUTO 區塊：旗下所有 ETF 持股 overlap / manager 名單
- `wiki/mechanisms/<slug>.md` AUTO 區塊：受該機制影響的 ETF / 事件 list

Phase 6 只先做 people，但 render pipeline（frontmatter → subprocess → splice）可直接復用。
