# Signals Skill

觸發：「訊號」「signal」「共識」「連續加碼」「核心出場」「多基金持有」「誰在加碼」「JOY 88」「rotation speed」

**研究筆記**：`docs/tools/signals.md`（9 種訊號定義 + 首次 findings + 設計決策）—— 本 SKILL.md 是操作手冊

---

## 核心

從 `raw/store.db`（datastore P4）偵測 9 種經理人策略訊號。純 SQL + Python，JSONL 輸出。

訊號類別：
- **共識類**（4 / 7）：多基金同時持有 / 快速形成
- **加碼類**（5 / 6）：連續上升 / 雙軌加碼
- **減碼類**（8 / 9）：高權重腰斬 / 核心出場
- **升級類**（1 / 2）：季報→月報晉升 / 季報→ETF 激活
- **雙軌類**（3 / 6）：需 manager mapping，Phase 6 才啟用

本版實作 7 個（1/2/4/5/7/8/9），延後 3/6。

---

## 環境

```bash
export PATH="/home/node/.local/bin:$PATH"
cd /home/node/tw-active
./tools/signals.py stats   # 先看 datastore 覆蓋率
```

---

## Subcommand 速查

| 指令 | 用途 |
|---|---|
| `./tools/signals.py stats` | Datastore 覆蓋率 + 9 訊號狀態 |
| `./tools/signals.py explain <1-9>` | 單一訊號邏輯 + 需要資料 |
| `./tools/signals.py detect 4 --month 202603 --threshold 3` | 多基金共識（當月 N 檔以上基金同時持有） |
| `./tools/signals.py detect 5 --from 202504 --to 202603 --min-months 3` | 連續加碼 ≥M 月 |
| `./tools/signals.py detect 7 --from 202601 --to 202603 --n-funds 3 --delta-pct 5` | 跨月共識形成 |
| `./tools/signals.py detect 8 --from 202504 --to 202603 --high-pct 10 --low-pct 5` | 高權重單月腰斬 |
| `./tools/signals.py detect 9 --from 202512 --to 202603 --consecutive 3` | 連 M 月 Top 10 然後消失 |
| `./tools/signals.py detect 1 --quarter 202603 --next-month 202604` | 季報→月報晉升（等 quarterly backfill） |
| `./tools/signals.py detect 2 --quarter 202603 --etf-date 20260417` | 季報潛伏 ETF 激活（等 quarterly backfill） |
| `./tools/signals.py all --from 202601 --to 202603` | 跑 4/5/7/8/9 全部 |

所有 detect 訊號都輸出 JSONL 到 stdout，hit 計數到 stderr。

**資料過濾**：預設查 `active_etf_monthly` / `active_etf_quarterly` view（13 檔正式主動式 ETF 基金白名單）。加 `--include-all-funds` 旗標（放在 subcommand 前）繞過到 raw 表，用來研究 SITCA 歷史期 filter 失效的兆豐 fallback 汙染本身（詳見 [[wiki/mechanisms/sitca-history-filter-bug]]）：

```bash
./tools/signals.py --include-all-funds detect 4 --month 202511 --threshold 5
```

---

## 輸出 schema

```jsonc
{
  "signal_id": 4,
  "signal_name": "多基金共識",
  "as_of": "202603",            // YYYYMM 或 YYYY-MM-DD
  "code": "2330",
  "name": "台積電",
  ...訊號專屬欄位
}
```

統一欄位：`signal_id / signal_name / as_of / code / name`，方便 jq 過濾或 downstream aggregate。

---

## 常用 Pattern

### Pattern 1：每月底跑 snapshot

```bash
# 最新月份（假設 datastore 已 ingest 202603）
MONTH=202603
./tools/signals.py detect 4 --month $MONTH --threshold 3 > /tmp/s4.jsonl
./tools/signals.py detect 7 --from 202601 --to $MONTH --n-funds 3 > /tmp/s7.jsonl
./tools/signals.py detect 5 --from 202601 --to $MONTH --min-months 3 > /tmp/s5.jsonl
./tools/signals.py detect 9 --from 202512 --to $MONTH --consecutive 3 > /tmp/s9.jsonl

# 合併後去重
cat /tmp/s*.jsonl | jq -s 'group_by(.code) | map({code: .[0].code, name: .[0].name, signals: [.[].signal_id]})'
```

### Pattern 2：單碼深究

```bash
# 奇鋐（3017）最近 3 個月在多少基金的 Top 10
./tools/signals.py detect 4 --month 202603 --threshold 1 | jq 'select(.code=="3017")'
./tools/signals.py detect 5 --from 202601 --to 202603 --min-months 2 | jq 'select(.code=="3017")'
```

### Pattern 3：挑訊號參數掃描

```bash
# threshold 2 / 3 / 5 各看多少命中
for t in 2 3 5; do
  n=$(./tools/signals.py detect 4 --month 202603 --threshold $t 2>&1 >/dev/null | tail -1)
  echo "threshold=$t  $n"
done
```

### Pattern 4：匯入到每日 report

```bash
# 跑完後轉 markdown 表
./tools/signals.py detect 7 --from 202601 --to 202603 --n-funds 3 --delta-pct 5 \
  | jq -r '"| \(.code) | \(.name) | \(.n_funds_from)→\(.n_funds_to) | +\(.pct_delta)pp |"'
```

---

## 訊號選用決策樹

- 問「現在誰被多數基金持有？」→ **signal 4**
- 問「誰正在變成共識？」→ **signal 7**（比 4 早一拍）
- 問「哪個基金對某碼長期有信心？」→ **signal 5**
- 問「誰被腰斬 / 退出核心？」→ **signal 8**（單月暴跌）/ **signal 9**（連續 M 月在核心後消失）
- 問「季報觀察池 → 月報重倉？」→ **signal 1**（等 quarterly）
- 問「某經理人雙軌加碼？」→ **signal 3/6**（等 P6 manager mapping）

---

## 已知陷阱

1. **signal 5/9 混入非 AL11 基金**：目前 SQL 未加 `fund_class` 過濾，若 datastore 有其他類基金會混入噪音。手動加 `| jq 'select(.fund_name | contains("ETF基金"))'` 先擋
2. **signal 1/2 總是 0 hits**：因為 `holdings_fund_quarterly` 還沒 backfill。先跑 `./tools/datastore.py ingest sitca-quarterly --quarter 202603 --class AL11`
3. **signal 9 對資料缺漏敏感**：「假出場」hit 請 cross-check `ingest_log.row_count` 該月是否正常
4. **signal 3/6 會 exit code 3**：設計如此，提醒走 Phase 6 路徑
5. **JSONL 不是有效 JSON array**：用 `jq -s` 吞整個檔變 array，或逐行 `jq -c` 處理

---

## 與其他 Skill 分工

| 需求 | 用哪個 |
|---|---|
| 建資料 | datastore skill（init / ingest / backfill） |
| 時序 / 跨日 diff / 單次 query | **datastore skill**（`query diff / consensus / holdings`） |
| **多訊號偵測 / 規則化掃描** | **signals skill**（本 skill） |
| 挑某經理人雙軌軌跡（P6） | 等 wiki/people skill |
| 回測訊號命中後報酬 | 等 P7（可用 twquote skill 抓價位） |

**決策樹**：
- 一次性問「某檔股票在多少 ETF」→ datastore `query consensus`
- 規則化掃描多訊號 + JSONL pipe → signals
- 要做 daily report 段落 → signals all → jq → markdown

---

## Phase 狀態

| Phase | 目標 | 狀態 |
|---|---|---|
| P4 | datastore 時序儲存 | ✅ |
| **P5** | **9 訊號引擎（7 實作）** | **✅ MVP** |
| P6 | wiki/people 融合 + signal 3/6 啟用 | ⬜ |
| P7 | 回測 hook（yfinance / twquote） | ⬜（deferred） |
