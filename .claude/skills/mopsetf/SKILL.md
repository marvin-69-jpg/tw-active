# MOPSETF Skill

觸發：「MOPS 主動 ETF」「公開資訊觀測站 ETF」「t78sb39」「歷史月報」「主動 ETF 前五大」「MOPS Top 5」「mopsetf」「補歷史持股」

**研究筆記**：`docs/tools/mopsetf.md`（MOPS 破解過程 / SITCA 分工 / finding / 穩定度）

---

## 用途

**歷史月報補洞**：SITCA IN2629/IN2630 對非最新期 filter 完全失效（server bug）。歷史月份的主動 ETF 持股要走 MOPS `t78sb39_q3`。

限制：Top **5**（比 SITCA 月報 Top 10 淺）、只含 AL11 主動 ETF（不含主動基金）。

---

## 環境

```bash
export PATH="/home/node/.local/bin:$PATH"
cd /home/node/tw-active
```

---

## Subcommand 速查

| 指令 | 用途 |
|---|---|
| `./tools/mopsetf.py monthly --month 202602` | 該月主動 ETF 全部 Top 5（人類可讀） |
| `./tools/mopsetf.py monthly --month 202602 --json` | JSON 輸出 |
| `./tools/mopsetf.py monthly --month 202602 --save-raw` | 連原始 HTML 存到 `.tmp/mops/`（debug 用） |
| `./tools/mopsetf.py parse <html-path> --json` | 解析本地 HTML（offline 測試用） |

---

## 關鍵地雷

1. **month 參數用西元 YYYYMM**，CLI 自動轉民國年塞進 POST body
2. **同月優先用 SITCA**（Top 10 較深），MOPS 只填 SITCA 失效的歷史月
3. **次月第 10 營業日才公布**，跟 SITCA 同步

詳細踩雷記錄見 `docs/tools/mopsetf.md`。
