# Morning Post Skill（盤前指引）

觸發：「盤前指引」「文案」「morning post」「產文案」「產盤前」「今天的盤前」「盤前」

---

## 核心

每日盤前根據前一日 21 檔主動 ETF 經理人持股變化，產出：
1. **文字文案**（貼 Threads / Discord）
2. **卡片圖**（`.png`，可選）

資料來源：`site/preview/flow.json`（由 `preview_flow.py` 從 `raw/cmoney/shares/` 計算）

---

## 環境

```bash
export PATH="/home/node/.local/bin:$PATH"
cd /home/node/tw-active
```

---

## 標準流程（只要文案）

```bash
# Step 1：確認 flow.json 日期是今天（或昨個交易日）
uv run python3 -c "import json; d=json.load(open('site/preview/flow.json')); print(d['as_of'], len(d['etfs_covered']), '家已揭露')"

# Step 2：產文案，直接貼給使用者
uv run tools/morning_post.py
```

文案格式：
```
盤前指引 · M/D 主動 ETF 經理人動向（X/21 家已揭露）

4 家以上共識買進：
・股名 代號 +XX億 （ETF清單）
...

單一大注：
・股名 代號 +XX億 （ETF清單）
...

共識賣：無 / 有...

主動 ETF 昨日淨流入 +XX億...
```

---

## 附圖流程（可選）

```bash
uv run tools/gen_flow_card.py /tmp/flow_card.png
# → 輸出 /tmp/flow_card.png（1080px 寬）
```

用 Read 工具讀圖給使用者看確認，確認後讓使用者自行貼文。

---

## flow.json 過期時

flow.json 的 `as_of` 不是今天 → 需重建：

```bash
# 重算 flow
uv run tools/preview_flow.py

# 如果 shares raw 也沒更新 → 先 debug preview pipeline
# → 切換到 preview SKILL
```

詳見 `.claude/skills/preview/SKILL.md`。

---

## 門檻設定（在 morning_post.py 頂部）

| 常數 | 預設 | 意義 |
|---|---|---|
| `CONSENSUS_BUY_MIN_FAMILIES` | 4 | 幾家以上算共識買進 |
| `CONSENSUS_SELL_MIN_FAMILIES` | 3 | 幾家以上算共識賣 |
| `SINGLE_BET_MIN_NTD` | 3億 | 單一大注最低門檻 |
| `SINGLE_BET_MAX_SHOW` | 6 | 最多顯示幾檔 |
| `DOMINANT_ETF_PCT` | 0.5 | >50% 淨流入來自單一 ETF → 提示 basket buy |

---

## 與其他 Skill 分工

| 需求 | 用哪個 |
|---|---|
| 重建 flow.json / 排查資料 stale | **preview skill** |
| 產 Threads 長篇研究文 | **research skill** |
| 當日 ETF 持股 ground truth | **etfdaily skill** |
