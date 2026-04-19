# 自研搜索工具：研究筆記

本資料夾記錄 tw-active **每一個自製的 primary-source data fetcher** 的：

1. **問題脈絡**：哪一 Round 才發現盲點、為什麼既有來源不行
2. **破解思路**：怎麼找到真正的 endpoint
3. **實作**：CLI 指令、資料 schema、日期陷阱
4. **finding**：用這個工具首次揭露的事實
5. **穩定度與失敗模式**

這不是操作手冊（操作看 `.claude/skills/<name>/SKILL.md`），是**研究筆記**。
tw-active 的 moat = 我們自己打造的 primary-source pipeline；每個破解過程都是研究本身，留下來給未來的 session 與讀者。

## 現有工具

| 工具 | 覆蓋需求 | 真正來源 | 狀態 |
|---|---|---|---|
| [fundclear](fundclear.md) | ETF 公開說明書 PDF 全文 | FundClear `/api/etf/product/*` | ✅ 穩定（Round 44） |
| [twquote](twquote.md) | 盤後報價 + 三大法人 + OpenAPI schema | TWSE/TPEx OpenAPI + 舊 T86 | ✅ 穩定（Round 44） |
| [etfdaily](etfdaily.md) | 主動 ETF 當日持股 ground truth | 5 投信官網（統一/野村/復華/安聯/群益，10 檔） | ✅ 穩定（Round 45；統一不支援歷史） |
| [cmoney_raw](cmoney_raw.md) | 主動 ETF 全歷史持股（21 檔）+ 每日 NAV/折溢價 + 費率/規模/配息制度 | 第三方彙整（實作細節於另一 repo） | ✅ 穩定（每日 CI push 到 `raw/cmoney/`） |
| [managerwatch](managerwatch.md) | 基金月報 Top 10 + 季報 ≥1% | SITCA IN2629 / IN2630 | ✅ 穩定（quarterly by-comid 待補；歷史期 filter server bug 用 mopsetf 補） |
| [mopsetf](mopsetf.md) | 主動 ETF 歷史月報 Top 5（補 SITCA 歷史 bug） | MOPS `t78sb39_q3` | ✅ 穩定（monthly；其他 report 待補） |
| [datastore](datastore.md) | SQLite 合流 query（managerwatch + etfdaily） | 本地 `raw/store.db` | ✅ MVP（Round 45） |
| [signals](signals.md) | 9 種經理人策略訊號（共識/加碼/出場） | datastore query | ✅ 7/9（Round 45） |
| [peoplefuse](peoplefuse.md) | 把 datastore × signals 渲染進 `wiki/people/` | signals JSONL | ✅ MVP（Round 45；首渲 2 人） |

**CI 自動化**：
- `.github/workflows/daily-etfdaily.yml`：每個交易日 T+1 fetch 投信官網 10 檔 ground truth
- 歷史持股 21 檔深度回溯由外部 CI 處理，跑完把 raw JSON push 回本 repo 的 `raw/cmoney/`
- 任一條失敗開 issue 警報

## 避雷：試過不行 / 已被取代

詳見 [`CLAUDE.md` 「資料來源優先序 → 避雷清單」](../../CLAUDE.md)。最重要的三條：

- **Yahoo Finance**：費率顯示「最優階梯」當「當前實付」（Round 10 發現）、名稱截斷 22 字元（Round 22）、推薦演算法對主動 ETF 完全斷裂 → 用 `fundclear` 抽公開說明書、`twquote` 取報價、MOPS/官網取全名
- **MoneyDJ / Goodinfo**：反爬、字段常改 → `twquote`（TWSE/TPEx OpenAPI 官方）
- **SITCA 歷史期 query**：IN2629/IN2630 filter server bug（回固定兆豐資料，見 `project_sitca_al11_drift` memory）→ `mopsetf`

## 新增工具 SOP

打造新 fetcher 時請同步建立：

1. `tools/<name>.py` — PEP 723 inline CLI
2. `.claude/skills/<name>/SKILL.md` — 觸發詞 + subcommand 速查 + 決策樹
3. `docs/tools/<name>.md` — **本資料夾**：研究筆記（照上面 5 段結構）
4. 在本 README 的表格加一行
5. 若屬於可跨 session 復用的 primary-source 破解 → 再寫一條 `reference_*` memory

**設計哲學**：SKILL.md 是操作手冊（怎麼用，給未來的 agent 照表操課），docs/tools 是研究筆記（為什麼做、怎麼破的，給人類研究者與 review 者讀）。兩者分工不要混。
