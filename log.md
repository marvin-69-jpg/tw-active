# tw-active — 操作記錄

## 2026-04-25

- 建 papers fetcher（`tools/papers.py` + `.claude/skills/papers/` + `docs/tools/papers.md`），薄 wrapper 包 paper-search-mcp + 本地 NBER curl（PR #96 已 merge）
- 抓 PSTZ 2014 NBER w19891 PDF，建 raw sidecar [[raw/papers/nber_w19891]]
- 開 wiki 第一篇 mechanism：[[wiki/mechanisms/diseconomies-of-scale]]——把「主動基金規模一變大效益遞減」這個直覺接到學術文獻（PSTZ 2014 industry-level 的關鍵 framing），並 map 到台灣主動 ETF 的場景（權值股集中度、closet-indexing、配息平準金 indirect channel）
- 補抓 Berk-Green NBER w9275 全文 + CHHK 2004 AER abstract（paywall）+ PSTZ-Zhu 2021 SSRN abstract（paywall），各自寫 raw sidecar。把規模遞減 mechanism page 的 Sources 與「文獻地圖」鋪完整：理論（Berk-Green 2004）→ 首篇實證（CHHK 2004）→ 方法論翻案（PSTZ 2014）→ robust 升級（PSTZ-Zhu 2021）
