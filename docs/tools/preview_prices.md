# preview_prices — 抓單股歷史收盤價供 preview overlay + P&L 計算

**建立日期**：2026-04-19
**Source migration**：2026-04-20 Round 48 TWSE STOCK_DAY → **FinMind**
**CLI**：`tools/preview_prices.py`
**輸入**：`site/preview/<etf>.json`（preview 每日持股壓縮檔）
**輸出**：`site/preview/<etf>-prices.json`

---

## 1. 問題脈絡

tw-active preview 兩個下游消費者：

1. **單股 detail chart 疊股價線**：區分「主動擇時 vs 被動權重拉伸」。Round 47 已上線。
2. **經理人 P&L 計算**（Round 48 新需求）：股數 × 股價可算每檔持股的實際損益，比報酬率報告更誠實。

研究軸：「經理人裁量權 vs 公開說明書的落差」——擇時品質 + P&L 是兩個具體 proxy。

---

## 2. Round 48 Source Migration（TWSE → FinMind）

### 為什麼棄用 TWSE STOCK_DAY legacy

Round 47 初版走 `https://www.twse.com.tw/exchangeReport/STOCK_DAY?date=YYYYMM01&stockNo=XXXX`（民國日期），TPEx 走 `tradingStock` fallback。觀察到的問題：

- **請求量炸裂**：n 檔 × m 月（主動 ETF 12 月歷史 × 500+ 檔 ≈ 6000 calls）
- **429 頻繁**：跑到一半就被擋，要加長 sleep 又拖慢
- **endpoint 狀態不穩**：legacy endpoint 不在 OpenAPI，隨時可能被砍
- **Yahoo chart v8 備案也失敗**：IP-level rate limit 從 pod 打很快被 429（query2 subdomain 也擋）

### 改用 FinMind

```
https://api.finmindtrade.com/api/v4/data
    ?dataset=TaiwanStockPrice
    &data_id=XXXX
    &start_date=YYYY-MM-DD
    &end_date=YYYY-MM-DD
```

**優勢**：

- TWSE + TPEx 同一 endpoint，無需判斷 .TW vs .TWO
- 單次請求拿整段（12 月 = 1 call，不是 12 calls）→ 6000 calls 降到 500
- ISO 日期格式（無需解析民國）
- 免費 tier 免 token，文件 ~600 req/hr
- 沒被 429（Round 48 smoke test 通過）
- 95 檔 × 218 天 = 20049 points · 35 秒跑完

**仍有的限制**：

- 不提供**除權息還原**；研究擇時時其實不用還原（要看經理人當下的價格）
- 免費 tier 有 rate limit；若研究 scale 上去（21 檔 ETF × 500 檔個股）可能要 token

---

## 3. 實作

### 基本用法

```bash
# 抓 00981A 全部持過的股票（current + exited + NEW）
./tools/preview_prices.py site/preview/00981a.json

# 只抓幾檔做 smoke test
./tools/preview_prices.py site/preview/00981a.json --codes 2330,6488 --out /tmp/test.json

# 調慢 sleep 避免被擋（預設 0.2）
./tools/preview_prices.py site/preview/00981a.json --sleep 0.3
```

### Code filtering

TW 股代號 regex：`^\d{4,6}[A-Z]?$`（4-6 digits + 可選 1 個大寫後綴）

Skip 的 code 類型：
- 海外股（`AMD US` / `268A JP` / `BLSH US`）
- 期貨（`202605TX` / `202606FESB`）
- Cash markers（`C_NTD` / `M_NTD` / `PFUR_NTD` / `RDI_NTD`）
- 貨幣（`M_EUR` / `DA_NTD`）

下游 preview_build P&L 計算只處理 TW 股。

### 輸出 shape

```json
{
  "as_of": "20260417",
  "first_date": "20250526",
  "codes": ["1210", "1303", ...],
  "prices": {
    "2330": [
      {"date": "20250526", "close": 976.0},
      {"date": "20250527", "close": 965.0},
      ...
    ]
  },
  "source": "finmind_v4",
  "generated_at": "2026-04-20T15:30:00Z"
}
```

### Resume / incremental save

- 如果 output path 已存在且 `as_of` + `source` 相同 → 只補缺的 code
- 每 20 檔 flush 一次到磁碟，kill -9 也不會全白跑
- 換 source 會失效既有 cache（`source != finmind_v4` → 全重抓）

---

## 4. Finding

### Round 48 Smoke test

- 00981A 95 檔全部 TW → 92 有效（3 檔非 TW code 被 skip）
- 每檔 ~218 天資料齊（涵蓋 2025-05-26 → 2026-04-17）
- 20049 points · 35 秒 · 無 429
- TPEx 股（5483 中美晶 / 6488 環球晶 / 3189 景碩 等）全正常拿到

### 已知限制

- 無除權息還原
- 新上市股可能 series 較短 → 前端 / P&L 計算要容忍 sparse series
- 非 TW code（海外、期貨）直接 skip（P&L 下游不支援）

---

## 5. 研究用途

1. **擇時品質**：ADD 點疊股價低點 = 主動擇時；疊高點 = 追漲（既有 overlay）
2. **出清點分析**：EXIT 在相對高還是低？
3. **權重漂移來源**：權重漲但股價跌 = 經理人主動加碼；權重漲股價更漲 = 被動拉權重
4. **P&L**（Round 48 新）：每檔持股 `Σ(-Δshares × price) + shares_now × price_now`
5. **批次分析**：21 檔主動 ETF 的 ADD 事件統計「相對 60d high 位置」分佈
