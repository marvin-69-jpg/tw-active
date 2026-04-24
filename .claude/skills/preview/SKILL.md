# Preview Pipeline Skill

觸發：「preview」「Pages 資料沒更新」「as_of 停在舊日期」「flows stale」「股價 overlay 怪」「preview_build」「preview_prices」「daily-preview」「pages-deploy 沒 trigger」

**研究筆記**：`docs/tools/cmoney_raw.md`（raw 結構 + 四層鏈 + debug SOP）、`docs/tools/preview_prices.md`（FinMind fetcher + cache key 教訓）—— 本 SKILL.md 是操作手冊

---

## 核心

Pages 上的 `as_of` 不是單一 workflow 推的，是**四層堆疊**。任一層 stale 整條斷、但綠燈不等於資料對。

```
Layer 1  外部 CI → raw/cmoney/{<ETF>/batch_*, shares/*, premium/*, dividend/*, meta/*}
   ↓           （push 路徑觸發 daily-preview）
Layer 2  .github/workflows/daily-preview.yml → tools/preview_build.py
   ↓           → site/preview/<etf>.json、etfs.json、flow.json、scale.json
Layer 3  同 workflow → tools/preview_prices.py（FinMind）
   ↓           → site/preview/<etf>-prices.json
Layer 4  .github/workflows/pages-deploy.yml（site/** 路徑觸發）
              → GitHub Pages
```

**關鍵認知**：Layer 1 外部 CI 叫 `daily-cmoney`（private repo），跟本 repo 的 `daily-etfdaily` **無關**。Pages 每日節奏 = Layer 1 節奏（見 memory `feedback_tw_active_daily_means_cmoney`）。

---

## 環境

```bash
export PATH="/home/node/.local/bin:$PATH"
cd /home/node/tw-active
export GH_TOKEN=$(cat /home/node/.gh-token-marvin)
```

CLI：
- `tools/preview_build.py` — Layer 2，讀 raw/cmoney/ 產 site/preview/
- `tools/preview_prices.py` — Layer 3，吃 site/preview/<etf>.json 產 <etf>-prices.json
- `tools/preview_all.py` — batch 版：上述兩層 + etfs.json 合成
- `tools/preview_flow.py` — 從 raw/cmoney/shares/ 計算資金流向，產 site/preview/flow.json（供 morning_post 用）
- `tools/preview_scale.py` — 跨 ETF 規模/申購/飛輪分析，產 site/preview/scale.json（讀 shares+premium+meta+prices+pcf）

---

## Debug SOP：Pages 資料看起來沒更新

**不要猜、逐層查**。四條命令定位到壞掉的那層：

```bash
# Layer 1 — raw 到了沒
ls -lt raw/cmoney/shares/ | head -5
jq '.Data[0][0]' raw/cmoney/shares/00981A.json   # 最新日期

# Layer 2 — preview build 有讀到新 raw 嗎
jq '{as_of, first_date, n_days}' site/preview/00981a.json

# Layer 3 — prices 有對齊 preview 的 first_date 嗎
jq '{as_of, first_date, pts_2330: (.prices["2330"] | length)}' site/preview/00981a-prices.json

# Layer 4 — Pages 有 deploy 嗎
gh run list --workflow=pages-deploy.yml --limit 3
```

### 層別症狀對應

| 症狀 | 壞在哪 |
|---|---|
| `raw/cmoney/shares/*.json` mtime 是昨天 | Layer 1：private repo `daily-cmoney` 沒跑或失敗 |
| shares 新但 `site/preview/00981a.json.as_of` 舊 | Layer 2：`daily-preview` 沒跑，或 `preview_build.load_latest_raw` 挑錯 batch |
| preview `first_date=20260416`、`n_days=3` | Layer 2：union 壞了/只挑單一 batch，所有 holding 被誤標 NEW |
| preview 對了但 prices 每檔只 3 點 | Layer 3：cache key 沒含 first_date，resume 繼承舊 series |
| site/preview/ 全對但 Pages 畫面舊 | Layer 4：`pages-deploy` 沒自動 cascade（GH 預設 token 設計） |

---

## Pattern 1：手動重建全部 preview

```bash
# Layer 2 + 3 一起跑
CODES=$(ls raw/cmoney/shares/ | grep -E '^[0-9]{5}[A-Z]\.json$' | sed 's/\.json$//' | tr '\n' ' ')
uv run tools/preview_all.py $CODES
for code in $CODES; do
  lc=$(echo "$code" | tr 'A-Z' 'a-z')
  uv run tools/preview_prices.py "site/preview/${lc}.json"
done
```

然後 `git add site/preview/ && git commit && git push`，pages-deploy 會自動跑（path 命中）。

---

## Pattern 2：在 GH Actions 重建

```bash
gh workflow run daily-preview.yml
gh run list --workflow=daily-preview.yml --limit 2
# 等跑完後 pages-deploy 不會 cascade，手動觸發
gh workflow run pages-deploy.yml
```

---

## Pattern 3：單檔 prices 強制重抓

preview 擴歷史範圍後，prices cache 會因為 `first_date` 變動自動 invalidate（見 `preview_prices.py:220`）。但若要手動強制重抓：

```bash
rm site/preview/00981a-prices.json
uv run tools/preview_prices.py site/preview/00981a.json
```

---

## 三個已知地雷（2026-04-20 debug 出來）

### 🪤 Layer 2：load_latest_raw 挑單一 batch

`raw/cmoney/<ETF>/` 有：
- `batch_*_r3.json` — 每日 delta（3 天）
- `batch_*_r400.json` / `batch_*_r800.json` — 週期全量 backfill

**挑單一都錯**：
- 挑 largest `r` → 昨天 r400 蓋今天 r3，`as_of` 慢一天
- 挑 latest `ts` → 只剩 3 天歷史，全部 holding 被當 NEW

**正解**：union 所有 batch，以 `(date, code)` 為 key 去重，newer overwrite older。實作在 `preview_build.load_latest_raw`（PR #22/#23）。

### 🪤 Layer 3：cache key 只比 as_of

`preview_prices.py` resume 檢查必須是 `(as_of, first_date, source)` 三項全等。早期版本只比 `(as_of, source)`，當 preview 擴歷史（`first_date` 20260416 → 20250526）時 `as_of` 沒變 → resume 回來 3 天 series → Pages 股價 overlay 只有 3 點（PR #24）。

**通則**：cache key = 所有會影響輸出形狀的輸入欄位的聯集。這條寫進 memory `feedback_cache_key_must_cover_all_deps`，不只 preview 適用。

### 🪤 Layer 3 後續：已污染檔案不會自己修好

PR #24 修了 cache key，但 PR #23 run 已經把「新 first_date + 舊 3 點 series」寫進 `*-prices.json`。PR #24 merge 後的 run 檢查 `(as_of, first_date, source)` 三項全等 → 繼續 resume 3 點 → Pages 股價一直 3 點（PR #27 砍檔才解）。

**修 cache key 的 SOP**：同一 PR 或下一個 PR 砍掉現存 `*-prices.json`（或對等的 cache 檔），強迫重抓。cache fix 只防**未來**污染，救不了**過去**。

### 🪤 Layer 2↔3：P&L 需要 preview_build 跑兩次

`preview_build._compute_stock_pnl` 需要 `raw/cmoney/shares/<etf>.json` **和** `site/preview/<etf>-prices.json` 都存在才算。workflow 預設順序：

1. `preview_all` (→ `preview_build`) — prices 檔還沒建 → `pnl=None`
2. `preview_prices` — 才建 prices

首次 run 或 prices 被砍（如 PR #27）後，pass 1 算不出 P&L。舊版 workflow 沒 pass 2 → Pages P&L 視圖全空。

**正解**：workflow 加 pass 2，prices 完成後再 `preview_all` 一次（PR #29）。多 ~30 秒但把依賴寫明。以前沒顯形是因為磁碟上老是有舊 `*-prices.json`（即使 3 點）讓 preview_build 找得到 → 雖然 P&L 算得爛但不是 None。

### 🪤 Layer 2：ETF 自身 sparkline 走另一條 fetch 路徑

`preview_all._fetch_etf_price_series`（首頁 etfs.json 的 `price_series`）跟個股 `preview_prices.fetch_history`（detail 卡的 `<etf>-prices.json`）**不是同一個 code path**。Round 48 把 `preview_prices` 從 TWSE STOCK_DAY 遷到 FinMind 時，個股那條改了，ETF 這條漏改 → `_fetch_etf_price_series` 一直呼叫已被刪掉的 `fetch_twse_month` → 每檔 raise → 首頁 sparkline 全空但 daily-preview 綠燈（exception 被吞）。PR #31 修。

**通則**：source migration 要全 repo grep 舊 API 名稱，不只看 unit test 過。被吞的 exception 是這類 silent breakage 的溫床。

### 🪤 Layer 4：GH Actions 不 cascade

`daily-preview` push 後 `pages-deploy` **不會自動觸發**。GH Actions 的 default `GITHUB_TOKEN` 為避免遞迴刻意不 fire 後續 workflow。選一：

1. 手動 `gh workflow run pages-deploy.yml`（目前做法）
2. `daily-preview` 結尾加 `gh workflow run pages-deploy.yml`（要 PAT）
3. 改用 PAT push 整條鏈自動

---

## 與其他 Skill 分工

| 需求 | 用哪個 |
|---|---|
| 當日 ETF 持股 ground truth | **etfdaily** |
| 歷史持股 / 股數 / 折溢價 raw（21 檔） | 讀 `raw/cmoney/`（外部 CI push） |
| 把 raw 變成 Pages 消費的 JSON | **preview**（本 skill） |
| 個股歷史日收盤 | `preview_prices`（內嵌於本 skill） |
| 基金月/季報 | **managerwatch** |
| 公開說明書全文 | **fundclear** |

---

## Memory 指標

下次 Pages 問題進來，memory 會自動載入三條相關：
- `project_tw_active_preview_pipeline` — 四層鏈總覽（指向本 skill）
- `feedback_cache_key_must_cover_all_deps` — cache key 通則
- `feedback_tw_active_daily_means_cmoney` — Layer 1 歸屬 private repo CI
