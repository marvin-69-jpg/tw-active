# preview_prices — 抓單股歷史收盤價供 preview overlay

**建立日期**：2026-04-19
**CLI**：`tools/preview_prices.py`
**輸入**：`site/preview/<etf>.json`（preview 每日持股壓縮檔）
**輸出**：`site/preview/<etf>-prices.json`

---

## 1. 問題脈絡

tw-active preview 的單股 detail chart 只畫**權重 %** 隨時間（ENTRY/ADD/REDUCE/PEAK 事件點）。使用者回饋「我想要有股價對照」—— 光看權重無法區分：

- 加碼是經理人主動擇時（智慧）vs 股價漲被動拉權重（公式結果）
- 減碼是賣在高點（智慧）vs 停損砍在低點（追漲殺跌）
- 出清是高檔獲利了結 vs 低檔認賠殺出

疊上股價線後，ADD/REDUCE/EXIT 事件的時機品質就能**視覺化**回答。對應 CLAUDE.md 的研究軸「經理人裁量權 vs 公開說明書的落差」。

---

## 2. 破解思路

### 為什麼不走 `twquote daily`？

`twquote daily` 只回傳**單日快照**（TWSE STOCK_DAY_ALL + TPEx mainboard），無法回溯歷史。

### 採用 TWSE `STOCK_DAY` legacy endpoint

```
https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=YYYYMM01&stockNo=XXXX
```

每次回傳**單股單月**的 daily OHLC（日期為民國）。穩定、無 CAPTCHA。

### 上櫃股票走 TPEx

```
https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?code=XXXX&date=YYYY/MM/01&response=json
```

欄位順序與 TWSE 略異但都有「收盤」。

### Fallback 策略

每檔股票**第一個月**先試 TWSE：
- 有資料 → 後續月份都走 TWSE
- 沒資料 → 整段改走 TPEx
- 兩邊都沒 → 標記 none（可能停牌/下市），跳過剩餘月份

這樣 n 檔 × m 月的總 call 數從 2nm 降到 n×m + n 左右。

---

## 3. 實作

### 基本用法

```bash
# 抓 00981A 全部持過的股票（current + exited）
./tools/preview_prices.py site/preview/00981a.json

# 只抓幾檔做 smoke test
./tools/preview_prices.py site/preview/00981a.json --codes 2330,6488 --out /tmp/test.json

# 調慢 sleep 避免被擋
./tools/preview_prices.py site/preview/00981a.json --sleep 0.5
```

### 輸出 shape

```json
{
  "as_of": "20260417",
  "first_date": "20250526",
  "codes": ["1210", "1303", ...],
  "prices": {
    "2330": [
      {"date": "20250526", "close": 1025.0},
      {"date": "20250527", "close": 1040.0},
      ...
    ]
  },
  "generated_at": "2026-04-19T15:30:00Z"
}
```

### Resume / incremental save

- 如果 output path 已存在且 `as_of` 相同 → 只補缺的 code（中斷可繼續）
- 每 10 檔 flush 一次到磁碟，kill -9 也不會全白跑

---

## 4. Finding

### 成本 & 穩定度

- 87 檔 × 11-12 月 ≈ 1000 calls
- `sleep 0.25` 下約 8 分鐘跑完
- TWSE 某些月份會回 `stat != OK`（該月無交易 / 停牌），fetcher 視為空月而非錯誤
- TPEx 未觀察到 429

### 已知限制

- 不處理**除權息還原**，只取「收盤價」原始值 —— 畫圖會看到除息跳空。研究擇時時其實也不用還原（要看的是經理人當下看到的價格）
- 部分 D 字尾 ETF 標的或新上市股可能查無歷史 → series 會較短，前端要容忍短 series
- 僅日 K；分 K / 週 K 不支援

---

## 5. 研究用途

1. **擇時品質**：ADD 點疊股價低點 = 主動擇時；疊高點 = 追漲
2. **出清點分析**：EXIT 在相對高還是低？
3. **權重漂移來源**：權重漲但股價跌 = 經理人主動加碼；權重漲股價更漲 = 被動拉權重
4. **批次分析**：21 檔主動 ETF 的 ADD 事件統計「相對 60d high 位置」分佈 → 主動 ETF 族群的擇時偏好（擇時派 vs 動量派）
