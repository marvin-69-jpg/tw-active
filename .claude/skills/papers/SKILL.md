---
name: papers
description: 學術論文搜尋、下載、讀取（arxiv / crossref / openalex / semantic / ssrn / nber 等）。觸發：使用者要查/抓/讀論文、想找研究文獻、提到 working paper / SSRN ID / NBER WP / DOI。
---

# papers

`tools/papers.py` 是薄 wrapper，包：
- `paper-search-mcp`（`/home/node/paper-search-mcp/`）的 20+ source CLI
- 本地 NBER WP curl（上游沒 NBER connector）

PDF 統一存到 `raw/papers/`。

## 觸發詞

論文、paper、working paper、SSRN、NBER、arxiv、DOI、學術研究、文獻、查文獻

## CLI 速查

```bash
# 多源搜尋
uv run tools/papers.py search "<query>" -s arxiv,crossref,openalex -n 5
#   -s 預設 arxiv,crossref,openalex（穩、不卡 rate limit）
#   semantic 免 key 容易 429，需要才加

# 下載 PDF
uv run tools/papers.py download arxiv 1404.6803
uv run tools/papers.py download nber 19891          # NBER WP w19891
uv run tools/papers.py download ssrn 3886275        # 多半 fail（要登入）

# 讀全文（extract text）
uv run tools/papers.py read arxiv 1404.6803

# 列可用 source
uv run tools/papers.py sources
```

## 決策樹

| 想找什麼 | 用哪個 source |
|---|---|
| arxiv ID 已知 | `download arxiv <id>` |
| NBER WP 號碼已知 | `download nber <wp_number>` |
| DOI 已知（要 metadata）| `search "<title>" -s crossref` 拿 abstract |
| 不知 ID 想找題目 | `search "<query>" -s arxiv,crossref,openalex` |
| AER/JFE/JPE 期刊全文 | ❌ paywall；找 author 個人版 / NBER WP / SSRN preprint |
| SSRN PDF | ⚠ 多數要登入；先試 `download ssrn <id>`，fail 就找 author site |

## 來源穩定度

- ✅ **arxiv** — PDF 直抓
- ✅ **crossref** — abstract、citations、metadata 齊全
- ✅ **openalex** — 補充 metadata
- ✅ **nber**（本地）— curl 直抓 free PDF
- ⚠ **semantic** — 免 key 易 429，需要再用
- ❌ **ssrn** — 抓 PDF 多半 fail（compliance-first，只試公開 PDF link）

## Workflow

1. 收到論文需求 → `search` 拿 metadata + DOI/source/id
2. 給使用者一張表（title / authors / year / source / citations）
3. 確認要哪篇後 `download <source> <id>` 拿 PDF
4. 想精讀某段 → 用 Read tool 開 `raw/papers/<file>.pdf`，大檔用 `pages: "1-N"`

## 跟其他 skill 的關係

- `arxiv` skill（agent-memory-research）走 alphaxiv markdown，**讀** arxiv paper 比這裡的 PDF→Read 順
- 但 alphaxiv 只 cover arxiv；金融實證 paper（NBER/SSRN/Crossref）要走這個 papers skill
