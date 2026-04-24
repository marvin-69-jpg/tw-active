# TW Quote Skill

觸發：「三大法人」「外資」「投信買超」「T86」「ETF 成交」「自營商」「買賣超」「TWSE API」「TPEx API」「盤後」「OpenAPI 欄位」

**研究筆記**：`docs/tools/twquote.md`（破解過程 / 三條線整合 / finding / 穩定度）

---

## 用途

ETF **本身**的盤後市場資料（cmoney 沒有的角度）：
- 三大法人買賣超（外資 / 投信 / 自營商）→ AP 套利強度 proxy
- 個股日成交、外資持股 Top 20、定期定額月報

來源：TWSE OpenAPI + TWSE T86 legacy + TPEx OpenAPI，三條官方線合併。

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
| `./tools/twquote.py active [--date YYYYMMDD]` | 21 檔主動 ETF 盤後總覽（收盤/量/三大法人） |
| `./tools/twquote.py insti <code> [--date YYYYMMDD]` | 單檔三大法人明細 |
| `./tools/twquote.py daily <code>` | 個股日成交 |
| `./tools/twquote.py qfii [<code>]` | 外資持股 Top 20 |
| `./tools/twquote.py etfrank --active-only` | 定期定額交易戶數月報 |
| `./tools/twquote.py paths twse\|tpex` | 列出全部 endpoint（發掘用） |
| `./tools/twquote.py schema <twse\|tpex> <path>` | 查某 endpoint 回傳欄位 |

加 `--json` 供下游使用。

---

## 關鍵地雷

1. **週末/假日** `insti` 查 T86 回空 → 改 `--date` 為上一個交易日
2. **TPEx Date 是民國格式**（`1150417`）— CLI 已封裝，`--date` 統一用西元輸入

詳細踩雷記錄見 `docs/tools/twquote.md`。
