# Wiki Schema

規則給 LLM 讀，用來維護 `wiki/` 目錄。

## 檔案格式

每個 wiki page 是一個 markdown 檔，路徑：
```
wiki/<category>/<slug>.md
```

Category：`etfs / issuers / mechanisms / regulations / events / people`

## Frontmatter

```yaml
---
title: 顯示名（中文優先）
type: etf | issuer | mechanism | regulation | event | person
tags: [tag1, tag2]  # 複選：如 active-etf, fee-structure, distribution, tracking
slug: 檔名（不含副檔名）
aliases: [別名1, 別名2]  # e.g. ETF 代號、英文名、簡稱
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources:  # raw/ 裡對應的原始檔
  - raw/YYYY/MM/DD-<source-slug>.md
---
```

## Body 結構（Compiled Truth + Timeline pattern）

```markdown
# <標題>

## TL;DR
一句話到三句話，這個 entity 是什麼、為什麼值得研究、最重要的機制漏洞或特徵是什麼。

## Compiled Truth
可改寫的現況描述。ETF 的規模、費用、持股、機制細節等。如果有新資訊就直接改這一段，不 append。

### 關鍵機制
<按需要分小節：費用結構、配息政策、申贖規則、經理人裁量、追蹤方法論⋯>

### 我觀察到的漏洞 / 不對稱
<如果有的話，具體描述：什麼機制在什麼情況下會讓投資人吃虧、為什麼、有沒有先例>

## Timeline
Append-only 事件日誌。時間倒序（新的在上）。

- **YYYY-MM-DD** — 事件描述（[[source]]）

## Related
- [[wiki/xxx]] — 關係說明

## Sources
- [[raw/YYYY/MM/DD-xxx.md]]
- 外部連結：官方月報 / 公開說明書 / 法規條文
```

## Linking

- Wiki-link 用 `[[wiki/path/slug]]` 格式，支援 Obsidian graph view
- Raw file 引用用 `[[raw/YYYY/MM/DD-slug]]`
- 外部連結用 markdown `[text](url)`

## Entity 類型細則

### etfs/
- slug 用代號：`00981a.md`、`00940.md`
- title 用「代號 + 中文全名」：`00981A — 統一 FANG+ 主動式 ETF`
- aliases 放常見簡稱、英文名、發行商別名

### issuers/
- slug 用英文短名：`uni-president.md`、`yuanta.md`、`cathay.md`
- title 中文全名：`統一投信`
- 內容重點：旗下 ETF 組合、歷史紀錄、配息政策、曾經的爭議

### mechanisms/
- slug 用英文 kebab-case：`income-equalization.md`、`creation-redemption.md`、`tracking-error.md`
- 解釋機制**運作邏輯 + 揭露規則 + 台灣實務上的破洞**
- 如果機制有跨國比較（美國 ETF vs 台灣 ETF），單獨一個小節

### regulations/
- slug 用法規簡稱：`sitca-active-etf.md`、`sitc-law.md`
- 內容：法源、條文重點、主管機關、實際執行狀況、灰色地帶

### events/
- slug 用日期 + 簡稱：`2024-07-etf-boom.md`、`2025-XX-distribution-controversy.md`
- 單一事件深度拆解（不是日誌，日誌在 log.md 或各 entity 的 Timeline）

### people/
- slug 用英文名：`wu-ching-chuan.md`
- title 中英並陳
- 關注他們的：立場、利益相關、歷史發言、實際決策

## Ingest 流程

1. Raw 存檔 → `raw/YYYY/MM/DD-<source-slug>.md`（記 url、抓取時間、原文 metadata）
2. 識別內容涉及的 entities → 建或更新對應 wiki page
3. 寫 Compiled Truth（現況）與 Timeline entry（事件）
4. Cross-link 相關 entities
5. 更新 `index.md` 表格
6. 在 `log.md` 加一筆記錄
7. `reports/threads/YYYY-MM-DD.md` 寫 Threads murmur 短版

## 品質檢查

Lint 規則（見 `tools/wiki.py lint`）：
- 每個 wiki page 必須有 frontmatter 四欄：title, type, slug, updated
- Timeline entry 要有日期和來源連結
- Cross-link 的 target 必須存在
- 沒有 source 的「我觀察到的漏洞」要標 `[speculation]` tag
