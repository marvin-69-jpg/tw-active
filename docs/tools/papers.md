# papers — 學術論文 fetcher

## 問題

研究主動 ETF 規模 vs 績效這類議題，需要快速抓 NBER / SSRN / Crossref / arxiv 的論文 metadata 與 PDF。手動 curl 每個 source 寫 fetcher 太冗，但每個 source 的 quirks 又很多（rate limit / paywall / API key）。

## 破解

不重新發明輪子。直接借用 `openags/paper-search-mcp`：
- 已 cover arxiv / pubmed / biorxiv / crossref / openalex / semantic / ssrn / unpaywall 等 20+ source
- 已有 `paper-search` CLI 和 `claude-code/SKILL.md`
- compliance-first（SSRN 只試公開 PDF link，不繞驗證）

`tools/papers.py` 是薄 wrapper，做兩件事：
1. **委派** `paper-search search/download/read` 到上游 CLI（位置 `/home/node/paper-search-mcp/`）
2. **補強** NBER：上游沒 NBER connector，這層直接 curl `nber.org/system/files/working_papers/wXXXXX/wXXXXX.pdf`

## 為什麼不直接用上游 skill

- tw-active 規範「工具放專案內」（feedback_tools_in_project memory）
- 我們需要 NBER 補強
- 想統一 PDF 落點 `raw/papers/`

## 實作

PEP 723 inline Python，subprocess 委派 + urllib 抓 NBER。沒有自己重寫任何 source connector。

## Finding

- ✅ arxiv PDF 直抓穩定
- ✅ crossref abstract / DOI / citation 齊全（PSTZ NBER w19891 cite=13、CHHK AER cite=1110 都拿得到）
- ✅ NBER 直 curl 200，無反爬
- ❌ SSRN PDF 多數 fail（包括 PSTZ 2021 SSRN 3886275），有 SSRN ID 但要 PDF 全文時要去 author personal site / NBER WP 版
- ⚠ semantic 免 key 5 秒內就 429，要設 `SEMANTIC_SCHOLAR_API_KEY` env var 才好用
- ⚠ unpaywall fallback 需要 `UNPAYWALL_EMAIL` env var，沒設會被跳過

## 穩定度

上游 `paper-search-mcp` 是活躍維護的開源專案，每月都在更新 source list。NBER curl 是公開 endpoint，跟我們其他 primary source（TWSE/TPEx OpenAPI）一樣穩。

## 已知限制

期刊版全文（AER/JFE/JPE/RFS/JF）一律 paywall，套子套不過。對應策略：
1. 找 author personal site 上的 working paper PDF
2. 找 NBER WP 對應版本（多數美國 finance/econ 教授會 deposit 到 NBER）
3. 找 SSRN preprint（碰運氣）
