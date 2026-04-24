# ManagerWatch Skill

觸發：「經理人」「SITCA」「投信公會」「月報 Top 10」「季報 ≥1%」「基金持股」「IN2629」「IN2630」「雙軌」「同經理人」「主動基金持股」「managerwatch」

**研究筆記**：`docs/tools/managerwatch.md`（SITCA 破解過程 / 雙軌 finding / 穩定度）

---

## 用途

**雙軌分析**：同一經理人同時操盤 ETF（日揭露）+ 主動基金（月揭露 Top 10）。ETF 持股是「法規妥協版」，基金才是他真正想重壓的組合。差距 = 制度造成的策略分裂。

來源：SITCA IN2629（月報）/ IN2630（季報）。

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
| `./tools/managerwatch.py companies` | SITCA 投信代碼清單 |
| `./tools/managerwatch.py classes` | 基金分類代碼（AL11 = 國內主動 ETF 股票型） |
| `./tools/managerwatch.py catalog` | 本專案 19 檔觀測清單（13 基金 + 6 ETF，加 `--json`） |
| `./tools/managerwatch.py sitca monthly --month 202603 --class AL11` | 當月某類型全部基金 Top 10 |
| `./tools/managerwatch.py sitca monthly --month 202603 --by comid --comid A0009 --class AA1` | 某投信所有基金 Top 10 |
| `./tools/managerwatch.py sitca quarterly --quarter 202512 --class AL11` | 季報 ≥1% 全持股 |

加 `--json` 供下游使用。

常用投信代碼：A0005 元大 / A0009 統一 / A0022 復華 / A0032 野村 / A0037 國泰

---

## 關鍵地雷

1. **歷史期 filter 完全失效**：SITCA server 對非最新期忽略所有 `--class` / `--comid`，固定回兆豐資料。只能查**當月**。歷史期走 `mopsetf`（Top 5）。
2. **季報無名次欄**：IN2630 的 `rank` 欄為 null，正常現象。
3. **公司代碼用錯 → 404**：先跑 `companies` 確認。

詳細踩雷記錄見 `docs/tools/managerwatch.md`。
