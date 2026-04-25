---
name: active_share
description: 算 21 檔台灣主動 ETF 的 Active Share（Cremers-Petajisto 2009），看誰是 closet indexer、哪幾檔擁擠在同一 trade。觸發：Active Share / 主動程度 / closet indexing / 擁擠交易 / 持股重疊 / 跟 0050 像不像。
---

# active_share

`tools/active_share.py` 用 `raw/cmoney/<code>/` 最新一天的持股，算：
1. 每檔 AS vs industry-mean（21 檔自家平均當 benchmark）
2. pairwise AS matrix（最重疊 / 最分歧的對）

只算 TW 4-digit 股票部位，外股 / 現金 / 保證金 / 期權 / 公司債全濾掉，TW 曝險 < 50% 的 ETF 整檔排除。

## 觸發詞

Active Share、AS、closet indexing、影子指數化、擁擠交易、持股重疊、誰跟誰像、跟 0050 像不像、主動程度

## CLI

```bash
uv run tools/active_share.py                 # 預設輸出（人類友好表格）
uv run tools/active_share.py --pairs 15      # 印 pairwise 最近/最遠 15 對
uv run tools/active_share.py --json          # JSON 輸出（給下游 wiki / pages）
```

## 限制

- v0 用 industry-mean 當 benchmark，不是 Cremers-Petajisto 原版的 0050/TAIEX → AS 數字**不能套 60/80 門檻**，只能看相對排序
- 真要套 60/80 需抓 0050 持股做 base，目前 raw 沒存
- 持股以 cmoney CI 最新一天為準，跨 ETF 日期可能差一天（cmoney push 時間）

## 跟其他工具的關係

- 持股原料：`raw/cmoney/<code>/batch_*.json`（外部 CI push）
- 跟 [[wiki/mechanisms/closet-indexing]] 對應，數字可直接補進 mechanism page 的 Compiled Truth
