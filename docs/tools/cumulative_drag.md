# cumulative_drag — 主動 ETF 年化累積 front-running 暴露

> 對應 [`tools/cumulative_drag.py`](../../tools/cumulative_drag.py) + [skill](../../.claude/skills/cumulative_drag/SKILL.md)
> 對應 mechanism：[[wiki/mechanisms/etf-transparency-frontrunning]] H4
> 第一次跑：2026-04-25

## 研究問題

H1 v2 翻盤後（active per-event abnormal vol = 1.31 < passive 2.12，見 [`docs/tools/frontrunning.md`](frontrunning.md) v2 段）剩下一個 angle：

> H4：主動 ETF per-event abnormal vol 較弱沒錯，但 turnover 高頻 → events / 年數量多很多 → **年化累積 implied front-running cost / AUM** 可能反而比被動大。

如果 H4 成立，Haeberle 「主動 IP leak」框架在台灣依然有 bite，只是 magnitude 不在單事件 magnitude，而在**累積密度**。

## 方法

重用 frontrunning 的事件定義（見 frontrunning.md），但把分析角度從「per-event ratio 平均」換成「年化加總後 normalize by AUM」。

### 三道 metric

對每個 event（ETF, T, 股票, Δshares）：

```
r_T          = vol(T) / median(vol[T-20:T-1])
excess_ratio = max(r_T - 1, 0)

excess_volume_shares = excess_ratio × baseline_med_vol
  → 「揭露日比 baseline 多出來的市場成交股數」
  → 解讀：generic spillover（front-running + ETF rebalance + retail follow）
  → 量綱：股

manager_drag = |Δshares| × excess_ratio
  → 「manager 調倉曝光股數 × 揭露日 abnormal 強度」
  → 解讀：bound by manager 自己的部位變化，較貼近實際 IP-leak cost
  → 量綱：股
```

### 年化 + AUM normalize

對每檔 ETF：

```
days_span    = max(event_dates) - min(event_dates)
annualizer   = 365 / days_span
annual_X     = sum(per-event X) × annualizer
per_AUM_kshares_per_yi = annual_X / 1000 / AUM(億)
```

### Pooled

AUM-weighted 平均（避免小 ETF 的 outlier 主導）：
```
group_per_AUM = Σ(per_AUM_X × AUM) / Σ AUM
```

### 重要的窗口對齊

被動 ETF 的 `raw/cmoney/shares-passive/` 從 2022-12 就有資料（800 個揭露日），主動只有 2025-05 至今（最多 239 日）。**必須把被動事件限制到主動的時間窗口內**，否則就是拿 3+ 年的累積 vs 11 個月的累積，不對稱。

實作：window-aligned by `[min(active_dates), max(active_dates)]`。

## 第一次結果（2026-04-25）

時間窗口：2025-05-13 至 2026-04-24（約 11 個月）

### Active vs Passive Pooled (AUM-weighted)

| group   | n_etf | AUM(億)  | evt/yr | excess_kshares/億/年 | drag_kshares/億/年 |
|---------|------:|---------:|-------:|---------------------:|-------------------:|
| active  |    17 |  4735.0  |  5810  |             44813.6  |          **775.0** |
| passive |     5 | 27246.4  |   284  |               346.6  |          **382.2** |

**active / passive ratio**：
- `events_per_year`：**20.5×**（這是 H4 的主驅動力）
- `excess_volume_per_AUM`：**129.29×**（被 small-cap 低 baseline 放大）
- `manager_drag_per_AUM`：**2.03×**（最貼近 IP-leak cost 的指標）

→ **H4 weakly supported**：主動 ETF 年化 cumulative drag/AUM 比被動高 2.0×。
   driver 是 events/yr 高出 20×，但每事件的 manager 曝光量小很多，淨效果只到 2×。

### Active by ETF（drag/AUM 排序）

| ETF    | AUM(億)  | evt/yr | excess_k/億/yr | drag_k/億/yr |
|--------|---------:|-------:|---------------:|-------------:|
| 00994A |     38.1 |    365 |      2,605,733 |   **19,740** |
| 00993A |    124.7 |    592 |        108,036 |        2,399 |
| 00400A |    180.5 |  1,199 |        193,700 |        2,305 |
| 00987A |     29.5 |     98 |        121,393 |        1,716 |
| 00984A |     66.3 |    500 |         83,530 |        1,673 |
| 00985A |    102.7 |    217 |         57,793 |        1,076 |
| 00982A |    388.6 |    441 |         12,167 |          951 |
| 00991A |    336.6 |    349 |         22,817 |          870 |
| 00995A |     49.6 |    128 |        242,319 |          600 |
| 00992A |    485.5 |    333 |          8,724 |          515 |
| 00981A |  2,120.8 |    598 |          7,241 |          431 |
| 00996A |     39.3 |    154 |         60,729 |          377 |
| 00980A |    143.1 |    129 |          6,841 |          119 |
| 00990A |    263.4 |     71 |          5,356 |          113 |
| 00988A |    229.9 |     28 |          3,037 |           56 |
| 00401A |     30.6 |    365 |              0 |            0 |
| 00997A |    105.7 |    243 |              0 |            0 |

00401A / 00997A 全 0：兩檔太新（最早揭露日 2026-03-31 / 2026-04-10），baseline window 20 日的成分股還沒抓到 vol cache → 都被 filter 掉（enriched 數 < raw events）。

00994A 異常高（drag 19740）：38.1 億小規模 + 365 events/yr 高 turnover + 持股偏小型股低 baseline vol，三條路徑同向放大。

### Passive by ETF

| ETF    | AUM(億)   | evt/yr | excess_k/億/yr | drag_k/億/yr |
|--------|----------:|-------:|---------------:|-------------:|
| 0056   |  5,835.7  |    124 |          844.9 |     1,239.1  |
| 006208 |  3,887.8  |     26 |          463.3 |       287.0  |
| 0050   | 16,612.1  |     29 |          145.0 |       123.6  |
| 00692  |    500.4  |     78 |          473.0 |        21.8  |
| 00891  |    410.4  |     27 |          163.7 |         8.7  |

0056 的 drag/AUM 1239 反而比多數主動 ETF 高 — 高息策略本身就有可觀的調倉 turnover（季度 reweight），加上是大資金 single tracker，調倉時 Δshares 大、每次都被 front-run。0056 single-handedly 把 passive pooled drag 拉到 382。

## 主要 finding

### H4 結論：**weakly supported**

主動 ETF 年化 cumulative manager_drag / AUM = **2.0× passive**。比 v2 翻盤前期待的「明顯更大」要小很多。

#### 為什麼比想像中小

1. **per-event drag 確實小**（v1 → v2 已知）：active T median 1.31 vs passive 2.12，excess_ratio 平均小一截
2. **但 events/yr 差 20×**：active 17 ETFs × 平均 ~340 events/yr = 5810；passive 5 ETFs × 平均 ~57 events/yr = 284
3. **每事件 |Δshares| 也差很多**：被動 ETF rebalance 時調的股數遠大於主動微調，每事件 manager_drag 大
4. **三股力量相乘抵消**：(1.31/2.12) × (5810/284) × (small per-event Δshares) → 最終 2.03×

#### 為什麼還是 > 1×

主動 ETF 累積 IP-leak cost 確實比被動高，但**敘事不應該強推**：
- 2× 這個量級在 noise / 樣本誤差範圍內可以爭辯
- 0056 一檔幾乎獨自決定 passive baseline；換其他被動 ETF 樣本可能比例就翻
- 真正可能更乾淨的測法：對「相同股票被主動 vs 被動加碼」配對比較（matched pairs），需要 v3

### 解讀差距：excess_volume 129× vs manager_drag 2×

- `excess_volume_per_AUM` = 129×：主動 ETF 持股偏小型股，baseline vol 小，揭露日 abnormal vol 看起來「百分比上很大」，但 manager 自己根本沒進這麼多股
- `manager_drag_per_AUM` = 2×：用 manager 真的買的股數當上限，差距收斂回 2 倍
- **manager_drag 是更貼近真實 cost 的 metric**

這也呼應 v2 的另一個觀察：被動 ETF 的 abnormal vol 是大量 AP / index trader 同步 trade 的結果，跟 manager 自己 leak 的比例不同。

## 已知局限

1. **AUM 是 snapshot**：用 2026-04-25 抓到的 AUM 估算「整段 11 個月平均」，會 underestimate 早期較小 ETF 的 per-AUM cost
2. **manager_drag 沒乘 close price**：FinMind 配額用完，沒抓收盤價。若加 close 換成 NTD，跨 ETF 比較會更精準（小型股每股價格低、權值股每股價格高，現在的 shares-only metric 偏向 favor 大股本股票）
3. **00401A / 00997A 全 0**：太新，baseline window 不足；對 H4 結論影響微小（兩檔 AUM 加起來 136 億，總 active AUM 4735 的 2.9%）
4. **0056 單檔主導 passive**：5835 億 AUM 在 27246 總 AUM 中佔 21%，但其 drag 1239 在 pooled 382 中貢獻 ~70%。passive 樣本應擴充其他高息 / 主題 ETF
5. **window-aligned 後 passive events 從 625 → 152**：剩 152 個事件 across 5 ETFs，per-ETF 樣本中位數 28，統計力有限
6. **沒對 same-stock 做 matched pairs**：active vs passive rebalance 同一檔股票時的 abnormal vol 比較會更乾淨；現在是 portfolio-aggregate 比較

## 對 mechanism page 的修正

H4 的 entry：
- **weak support**：主動 cumulative drag / AUM = 2.0× passive，driver 是 turnover 高出 20×
- 但兩個前提需要謹慎：(1) AUM normalize 後比例是 2× 不是 10×；(2) 高度依賴單一 passive 樣本（0056）
- 真正 testable refinement：matched-pair comparison（H4'）

## 後續研究方向

### v2
- 配額恢復後加 close price，把 metric 換成 NTD 化
- 加 same-stock matched pairs：對同檔股票分別在 active 與 passive event 時的 abnormal vol 比較（控制股票特性）
- 擴充 passive 樣本（00919 / 00713 / 00733）

### 跨 mechanism 連結
- H2（BDR 2020 reversal）：用 ezmoney GetPCF 申贖量做基金層級 flow 而非個股事件
- H3（規模 → IP-leak cost）：把 by_etf 表跑 size regression
- H5（揭露 timestamp）：先做投信揭露時點 inventory

## Stability

- 100% cache hit（vol cache 由 frontrunning v2 已 populate）
- 跨重跑結果一致
- FinMind 配額：免費 tier 600/hr，跑 cumulative_drag 不需 fetch 即可（重用 vol cache）；只有第一次跑 frontrunning 需要 fetch
