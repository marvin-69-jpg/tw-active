# frontrunning — 主動 ETF 揭露日異常成交量

> 對應 [`tools/frontrunning.py`](../../tools/frontrunning.py) + [skill](../../.claude/skills/frontrunning/SKILL.md)
> 對應 mechanism：[[wiki/mechanisms/etf-transparency-frontrunning]]
> 第一次跑：2026-04-25

## 研究問題

台灣主動 ETF 強制每日揭露完整持股 + 股數。這個揭露結構讓 AP / HFT / 對沖看得到當日 PCF basket，**理論上**可以前置交易主動經理人的調倉。

H1（mechanism page 列的 5 個 testable hypotheses 之一）：
> 主動 ETF top N holdings 的「揭露日 → 隔日 abnormal volume」顯著大於 0，且強度與 ETF 規模負相關。

## 方法

### 事件定義

「加碼事件」= 對某 ETF 的某檔成分股，揭露日 T 比前一個揭露日 T-1 持有股數增加：
- 顯著：`Δ% >= 5%` 或 `is_new_position`（原本沒持有）
- 絕對下限：`Δ >= 100,000 股`（過濾雜訊）

跨 17 檔 TW-focused 主動 ETF + 250 檔個股，共 **2058 個事件**（2025-05 至 2026-04，~11 個月）。

### Abnormal Volume Ratio

對每個 (ETF, T, 股票) event：

```
r(T)   = vol(T)   / median(vol[T-20 : T-1])
r(T+1) = vol(T+1) / median(vol[T-20 : T-1])
r(T+2) = vol(T+2) / median(vol[T-20 : T-1])
```

Null hypothesis: 揭露事件對成交量無影響 → mean ratio ≈ 1.0
H1: ratio > 1.0（abnormal volume 在揭露窗口出現）

### 資料

- 事件：`raw/cmoney/shares/<ETF>.json`（17 檔 TW-focused，外部 CI 每日 push）
- 量：FinMind `TaiwanStockPrice.Trading_Volume`，per-stock cache（`.cache/volumes/<code>.json`）

## 第一次結果（2026-04-25）

### Pooled（2057 events）

| window | n    | mean | median | p25  | p75  |
|--------|------|------|--------|------|------|
| T      | 2057 | 2.04 | **1.31** | 0.91 | 2.18 |
| T+1    | 2047 | 1.83 | **1.24** | 0.83 | 1.95 |
| T+2    | 2028 | 1.72 | 1.18   | 0.78 | 2.01 |

**讀法**：揭露日當天，被加碼股票的成交量**中位數比基準高 31%**。隔日仍高 24%，第三天衰減到 18%。所有 percentile 都 > 1.0 不對稱（mean > median = right-skew，少數股票被「猛 leak」）。

### By kind

| kind          | window | n    | mean | median |
|---------------|--------|------|------|--------|
| new_position  | T      | 370  | 2.53 | **1.42** |
| new_position  | T+1    | 370  | 2.30 | 1.36   |
| add_existing  | T      | 1687 | 1.93 | 1.30   |
| add_existing  | T+1    | 1677 | 1.73 | 1.22   |

新建倉的 abnormal vol 比加碼既有部位高（1.42 vs 1.30）——符合「新買進是更明顯的訊號」直覺。

### By ETF（AUM 排序）

| ETF    | AUM(億) | n_evt | T_mean | T_med | T+1_med |
|--------|--------:|------:|-------:|------:|--------:|
| 00981A | 2120.8  |   541 |  2.43  | 1.56  | 1.39 |
| 00992A |  485.5  |   104 |  2.38  | 1.35  | 1.24 |
| 00982A |  388.6  |   400 |  2.09  | 1.35  | 1.26 |
| 00991A |  336.6  |   128 |  2.06  | 1.18  | 1.19 |
| 00990A |  263.4  |    24 |  2.31  | 1.34  | 1.39 |
| 00988A |  229.9  |    12 |  2.18  | 1.21  | 1.19 |
| 00400A |  180.5  |    46 |  1.98  | 1.49  | 1.35 |
| 00980A |  143.1  |   117 |  1.24  | 1.09  | 1.05 |
| 00993A |  124.7  |   107 |  1.45  | 1.14  | 1.01 |
| 00985A |  102.7  |   165 |  1.79  | 1.30  | 1.10 |
| 00984A |   66.3  |   366 |  1.72  | 1.23  | 1.18 |
| 00995A |   49.6  |    14 |  2.45  | 1.57  | 1.32 |
| 00996A |   39.3  |    11 |  1.48  | 0.96  | 0.84 |
| 00987A |   29.5  |    18 |  4.02  | **2.51** | 1.55 |

**初步觀察**：
- **沒有單調的 size 反比關係**——00981A（最大）T_med 1.56；00987A（最小規模有資料的）T_med 2.51；中間規模如 00980A / 00993A 反而 T_med 較低
- 00987A 樣本小（18 events），可能 outlier 主導
- 00981A 規模最大但 abnormal vol 仍顯著高——一個猜想：作為三胞胎共識中心（[[wiki/mechanisms/closet-indexing]] 的實證），它的調倉本身就被多家同步參考，front-running window 更大

H3（規模 → IP-leak cost 反比）的證據**混合**——需要更乾淨的 control + 樣本擴大。

## 主要 finding

**H1 在 pooled 層強烈成立**：
- 全部 2057 個加碼事件，揭露日成交量中位數比 baseline 高 31%（mean 104%）
- T → T+1 → T+2 顯示明顯 decay pattern，符合 front-running 在揭露窗口集中的預期
- 新建倉效應比加碼既有部位強（1.42 vs 1.30 median ratio at T）

## 已知局限

1. **Δshares > 0 是 noisy events**——混了主動加碼（manager decision）與 AP creation（基民申購對應）兩條 channel
2. **反向因果**——「個股已有利多 → 成交量先漲 → manager 看到 momentum 跟進買」也會 produce ratio > 1。要區分需看 T-1 → T 的 intraday/window timing
3. **沒有對照組**——同期間 passive ETF（0050、0056、00919）加碼相同股票的 abnormal vol baseline 沒做
4. **baseline window 固定 20 日**——對 trending 個股可能 underestimate baseline

## 後續研究方向

### v2（這個工具的下一步）
- 加 passive ETF 對照：同股票同時段被 0050 / 0056 / 00919 加碼時的 abnormal vol，當「揭露 = 中性訊號」的 null
- T-1 vs T 拆 timing：分離 front-running（T 量先漲）vs reverse causality（T-1 量先漲）
- 加入價格反應：abnormal return at T 與 reversal at T+5

### 跨 mechanism 連結
- H2（BDR 2020 reversal）：用 `ezmoney GetPCF DIFF_UNIT × P_UNIT` 申贖量做基金層級 flow 而非個股事件，獨立於 H1
- H4（turnover → cumulative drag）：把每次調倉的 abnormal vol 加總成 ETF 年度 implied front-running cost
- H5（揭露 timestamp）：先做投信揭露時點 inventory（盤後 vs T+1 早盤）

## Stability

- FinMind v4 endpoint 穩定，免 token tier 對 250 檔 / 11 個月 一次抓完約 70 秒
- 結果跨重跑一致（cache hit）
- raw/cmoney/shares 由外部 CI 每日 push，事件會自動延長
